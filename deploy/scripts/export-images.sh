#!/usr/bin/env bash
# 在开发机（可联网、已装 JDK17 + Maven + Docker）执行：
#   bash deploy/scripts/export-images.sh
#
# 产出：${OUT}（默认 /home/dev/tims-images）
#   <文件>.tar.gz        每个镜像一个文件（docker save | gzip）
#   MANIFEST.txt         文件名 / 镜像标签 / 大小 / md5 / 总体积，可直接阅读
#   MANIFEST.md5         md5sum -c 兼容格式，用于搬运后校验
#   load-all.sh          公司侧一键校验 + docker load
#
# 覆盖范围：六后端 + 前端（nginx）+ 四中间件，共 11 个镜像。
# 只读操作：不停止、不删除宿主机任何容器与镜像；不碰 k3s containerd。
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

REGISTRY=${REGISTRY:-harbor.xnunion.com/library}
TAG=${TAG:-1.0.0}
OUT=${OUT:-/home/dev/tims-images}
FRONT_IMAGE=${FRONT_IMAGE:-ai-tims-front}
SKIP_BUILD=${SKIP_BUILD:-0}
MANIFEST_ONLY=${MANIFEST_ONLY:-0}

APP_SVCS=(ticket-gateway ticket-system ticket-order ticket-knowledge ticket-ai ticket-push)

# 中间件：导出文件名 <- 公网上游镜像（公司内网无外网，必须随包带入）
MIDDLEWARE_FILES=(rabbitmq milvus etcd minio)
MIDDLEWARE_REFS=(
  "rabbitmq:3-management"
  "milvusdb/milvus:v2.4.15"
  "quay.io/coreos/etcd:v3.5.14"
  "milvusdb/minio:RELEASE.2024-05-28T17-19-04Z"
)

# 自建中间件：上游镜像 -> 公司 Harbor 自有名字（公司集群为 x86，导出前强制核对 linux/amd64）
REDIS_SRC=${REDIS_SRC:-redis:7-alpine}
REDIS_IMAGE=${REDIS_IMAGE:-${REGISTRY}/tims-redis:7-alpine}

command -v docker >/dev/null 2>&1 || { echo "缺少 docker"; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon 不可用"; exit 1; }

if [[ "$SKIP_BUILD" != "1" && "$MANIFEST_ONLY" != "1" ]]; then
  # 仓库按 Java 17 编译（maven.compiler.release=17），显式指定 JDK17
  if [[ -z "${JAVA_HOME:-}" && -d /usr/lib/jvm/java-17-openjdk-amd64 ]]; then
    export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
  fi
  command -v mvn >/dev/null 2>&1 || { echo "缺少 mvn（需要 JDK 17 + Maven）"; exit 1; }

  echo "==> [1/4] Maven 构建六服务（跳过测试，JAVA_HOME=${JAVA_HOME:-默认}）"
  (cd "$ROOT/ai-tims-parent" && mvn -B -q -DskipTests clean package)

  echo "==> [2/4] 构建后端镜像 -> ${REGISTRY}/<服务>:$TAG"
  for svc in "${APP_SVCS[@]}"; do
    jar=$(find "$ROOT/ai-tims-parent/$svc/target" -maxdepth 1 -type f \
            -name "${svc}-*.jar" ! -name "*.original" | head -n 1)
    if [[ -z "$jar" ]]; then
      echo "未找到 $svc 的可执行 JAR，构建失败"; exit 1
    fi
    jar_rel=${jar#"$ROOT"/}
    echo "--- $svc  <-  $jar_rel"
    docker build -q \
      --build-arg JAR_FILE="$jar_rel" \
      -f "$ROOT/deploy/docker/Dockerfile" \
      -t "${REGISTRY}/${svc}:${TAG}" \
      "$ROOT"
  done

  echo "==> [3/4] 构建前端镜像（node 编译 -> nginx 托管）-> ${REGISTRY}/${FRONT_IMAGE}:$TAG"
  docker build -q \
    -f "$ROOT/ai-tims-front/Dockerfile" \
    -t "${REGISTRY}/${FRONT_IMAGE}:${TAG}" \
    "$ROOT/ai-tims-front"
fi

if [[ "$MANIFEST_ONLY" != "1" ]]; then
  echo "==> [4/4] 拉齐中间件镜像（本地已有则跳过）"
  for ref in "${MIDDLEWARE_REFS[@]}"; do
    if docker image inspect "$ref" >/dev/null 2>&1; then
      echo "    已存在 $ref"
    else
      echo "    拉取 $ref"
      docker pull "$ref"
    fi
  done

  echo "==> 自建中间件打公司标签（强制 linux/amd64）"
  docker image inspect "$REDIS_SRC" >/dev/null 2>&1 || docker pull "$REDIS_SRC"
  arch=$(docker image inspect "$REDIS_SRC" --format '{{.Os}}/{{.Architecture}}')
  [[ "$arch" == "linux/amd64" ]] || { echo "$REDIS_SRC 架构为 $arch，不是 linux/amd64"; exit 1; }
  echo "    $REDIS_SRC ($arch) -> $REDIS_IMAGE"
  docker tag "$REDIS_SRC" "$REDIS_IMAGE"
else
  echo "==> MANIFEST_ONLY=1：跳过构建/拉取/导出，仅按现有 tar.gz 重算清单"
fi

mkdir -p "$OUT"
FILES=()
REFS=()
for svc in "${APP_SVCS[@]}"; do
  FILES+=("${svc}-${TAG}.tar.gz"); REFS+=("${REGISTRY}/${svc}:${TAG}")
done
FILES+=("${FRONT_IMAGE}-${TAG}.tar.gz"); REFS+=("${REGISTRY}/${FRONT_IMAGE}:${TAG}")
for i in "${!MIDDLEWARE_FILES[@]}"; do
  ref=${MIDDLEWARE_REFS[$i]}
  FILES+=("${MIDDLEWARE_FILES[$i]}-${ref##*:}.tar.gz")
  REFS+=("$ref")
done
FILES+=("tims-redis-${REDIS_IMAGE##*:}.tar.gz"); REFS+=("$REDIS_IMAGE")

if [[ "$MANIFEST_ONLY" == "1" ]]; then
  missing=0
  for f in "${FILES[@]}"; do
    [[ -f "$OUT/$f" ]] || { echo "缺少导出文件：$OUT/$f"; missing=1; }
  done
  [[ "$missing" -eq 0 ]] || { echo "请先正常执行一次导出（不带 MANIFEST_ONLY）"; exit 1; }
else
  echo "==> 逐个导出（docker save | gzip）-> $OUT"
  for i in "${!FILES[@]}"; do
    file=${FILES[$i]}; ref=${REFS[$i]}
    docker image inspect "$ref" >/dev/null 2>&1 || { echo "缺少镜像 $ref"; exit 1; }
    echo "--- $ref  ->  $file"
    docker save "$ref" | gzip > "$OUT/${file}.part"
    mv "$OUT/${file}.part" "$OUT/${file}"
    gzip -t "$OUT/${file}" || { echo "gzip 自检失败：$file"; exit 1; }
    # 确认 tar 内含目标镜像的 RepoTags，避免导出成别的镜像
    tmp_manifest=$(mktemp)
    tar -xzOf "$OUT/${file}" manifest.json > "$tmp_manifest"
    grep -q "\"${ref}\"" "$tmp_manifest" || { rm -f "$tmp_manifest"; echo "导出自检失败：$file 内不含 $ref"; exit 1; }
    rm -f "$tmp_manifest"
  done
fi

echo "==> 生成 MANIFEST.txt / MANIFEST.md5 / load-all.sh"
GIT_REV=$(cd "$ROOT" && git rev-parse --short HEAD 2>/dev/null || echo unknown)
GIT_REV="${GIT_REV}$(cd "$ROOT" && [[ -n "$(git status --porcelain 2>/dev/null)" ]] && echo '(worktree改动)')"
DOCKER_VER=$(docker version --format '{{.Server.Version}}')

{
  echo "AI-TIMS 离线镜像交付清单"
  echo "生成时间 : $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "构建主机 : $(hostname)"
  echo "源码版本 : ${GIT_REV}"
  echo "Docker   : ${DOCKER_VER}"
  echo "导出目录 : ${OUT}"
  echo "镜像数量 : ${#FILES[@]} 个（6 后端 + 1 前端 + 4 中间件 + 1 自建 tims-redis）"
  echo
  printf '%-46s %-62s %10s %s\n' "文件" "镜像标签" "大小" "md5"
  for i in "${!FILES[@]}"; do
    f=${FILES[$i]}
    size=$(du -h "$OUT/$f" | cut -f1)
    md5=$(md5sum "$OUT/$f" | cut -d' ' -f1)
    printf '%-46s %-62s %10s %s\n' "$f" "${REFS[$i]}" "$size" "$md5"
  done
  echo
  echo "总体积   : $(du -sh "$OUT" | cut -f1)（整个目录合计）"
  echo
  echo "== 校验（搬运后在任意 Linux 上执行，必须在 load 之前做）=="
  echo "  cd ${OUT} && md5sum -c MANIFEST.md5"
  echo "  预期：11 行全部 OK；出现 FAILED 说明传输损坏，重新拷贝该文件"
  echo
  echo "== 装载（公司内网任一装了 Docker 的机器）=="
  echo "  bash load-all.sh          # 先校验 md5，再逐个 docker load"
  echo "  或手动：docker load -i ticket-gateway-${TAG}.tar.gz"
  echo
  echo "== 若要改推到 Harbor 的其他项目（非 library）=="
  echo "  镜像已按 ${REGISTRY}/ 打好 tag，直接 push 即可；换项目只需："
  for svc in "${APP_SVCS[@]}" "$FRONT_IMAGE"; do
    echo "  docker tag ${REGISTRY}/${svc}:${TAG} <新地址>/${svc}:${TAG}"
  done
  echo
  echo "== 注意 =="
  echo "  1) 中间件镜像保留上游原名（如 rabbitmq:3-management），load 后即为此名，"
  echo "     与 deploy/k8s 里 images.env 的上游名一致。"
  echo "  2) 前端镜像的 nginx 在启动时解析上游 ticket-gateway:8080，"
  echo "     因此必须在 K8s（或能解析该名字的网络）里运行；单机 docker run 会因解析失败而退出。"
  echo "  3) 本清单只覆盖镜像文件；K8s 清单与 Secret 见 deploy/ 目录。"
} > "$OUT/MANIFEST.txt"

(cd "$OUT" && md5sum "${FILES[@]}" > MANIFEST.md5)

{
  echo '#!/usr/bin/env bash'
  echo '# 公司内网执行：先校验 md5，再逐个 docker load。用法：bash load-all.sh'
  echo 'set -euo pipefail'
  echo 'cd "$(dirname "$0")"'
  echo
  echo 'command -v docker >/dev/null 2>&1 || { echo "缺少 docker"; exit 1; }'
  echo 'docker info >/dev/null 2>&1 || { echo "docker daemon 不可用"; exit 1; }'
  echo
  echo 'echo "==> 校验 md5（失败先重拷，不要带病 load）"'
  echo 'md5sum -c MANIFEST.md5'
  echo
  echo 'echo "==> docker load"'
  for f in "${FILES[@]}"; do
    echo "docker load -i \"$f\""
  done
  echo
  echo 'echo'
  echo 'echo "==> 装载完成，镜像如下："'
  for i in "${!FILES[@]}"; do
    echo "docker image inspect \"${REFS[$i]}\" >/dev/null 2>&1 && echo \"  OK  ${REFS[$i]}\" || echo \"  缺失 ${REFS[$i]}\""
  done
  echo 'echo "下一步：把镜像 push 到 Harbor，或直接 docker run / k8s 引用。"'
} > "$OUT/load-all.sh"
chmod +x "$OUT/load-all.sh"
(cd "$OUT" && md5sum -c MANIFEST.md5 >/dev/null && echo "    自检通过：MD5 全部匹配")

echo
echo "================ 交付完成 ================"
cat "$OUT/MANIFEST.txt"
