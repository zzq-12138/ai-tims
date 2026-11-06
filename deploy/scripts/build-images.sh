#!/usr/bin/env bash
# 在 VM（可联网、已装 JDK17 + Maven + Docker）执行：
#   bash deploy/scripts/build-images.sh
# 只构建六个业务服务；中间件在 save-images.sh 阶段拉取。
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
# shellcheck source=images.env
source "$SCRIPT_DIR/images.env"

command -v mvn >/dev/null 2>&1 || { echo "缺少 mvn（需要 JDK 17 + Maven）"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "缺少 docker"; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon 不可用"; exit 1; }

echo "==> Maven 构建（跳过测试）"
(cd "$ROOT/ai-tims-parent" && mvn -B -DskipTests clean package)

echo "==> 构建业务镜像（tag=${IMAGE_TAG}，前缀=${REGISTRY_PREFIX}）"
for svc in "${APP_IMAGES[@]}"; do
  jar=$(find "$ROOT/ai-tims-parent/$svc/target" -maxdepth 1 -type f \
          -name "${svc}-*.jar" ! -name "*.original" | head -n 1)
  if [[ -z "$jar" ]]; then
    echo "未找到 $svc 的可执行 JAR，构建失败"; exit 1
  fi
  jar_rel=${jar#"$ROOT"/}
  echo "--- $svc  <-  $jar_rel"
  docker build \
    --build-arg JAR_FILE="$jar_rel" \
    -f "$ROOT/deploy/docker/Dockerfile" \
    -t "${REGISTRY_PREFIX}/${svc}:${IMAGE_TAG}" \
    "$ROOT"
done

echo
echo "构建完成："
for svc in "${APP_IMAGES[@]}"; do
  docker image inspect "${REGISTRY_PREFIX}/${svc}:${IMAGE_TAG}" \
    --format '  {{.RepoTags}}  {{.Size}} bytes'
done
