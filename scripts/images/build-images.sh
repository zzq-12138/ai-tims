#!/usr/bin/env bash
# =====================================================================
# build-images.sh - 按统一版本号构建全部交付镜像（只在 VM 上执行）
#
# 用法：
#   ./build-images.sh                 # 全量：Maven 打包 + 6 后端 + 1 前端
#   ./build-images.sh ticket-push     # 只构建指定后端服务（可多个）
#   ./build-images.sh front           # 只构建前端
#   SKIP_MAVEN=1 ./build-images.sh    # 跳过 Maven，直接用已有 jar 构建镜像
#
# 产物镜像名：${IMAGE_NAMESPACE}/${服务名}:${APP_VERSION}（见 images.env）
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"
source ./images.env

# ---------- 校验版本号：禁止 latest / 空值 ----------
case "${APP_VERSION:-}" in
  ""|latest|Latest|LATEST)
    echo "[错误] APP_VERSION 未设置或为 latest，请编辑 images.env 后重试" >&2; exit 1;;
esac

# ---------- 选择要构建的服务 ----------
TARGETS="${SERVICES}"
if [ $# -gt 0 ]; then
  TARGETS="$*"
fi

# ---------- Maven 打包 ----------
if [ "${SKIP_MAVEN:-0}" != "1" ] && [ "${TARGETS}" != "front" ]; then
  echo "== [1/2] Maven 打包（-DskipTests）=="
  MODS=$(for t in ${TARGETS}; do [ "$t" = "front" ] || printf '%s ' "$t"; done)
  if [ -n "${MODS// /}" ]; then
    (cd ../../ai-tims-parent && mvn -B -DskipTests -pl ${MODS} -am package)
  fi
else
  echo "== [1/2] 跳过 Maven（SKIP_MAVEN=1 或仅前端）=="
fi

# ---------- 构建镜像 ----------
BACKEND_DOCKERFILE="$(cd ../../docker && pwd)/backend.Dockerfile"
echo "== [2/2] docker build（--platform ${PLATFORM}）=="
for svc in ${TARGETS}; do
  if [ "$svc" = "front" ]; then
    IMG="${IMAGE_NAMESPACE}/${FRONT_IMAGE_NAME}:${APP_VERSION}"
    echo "-- 前端: ${IMG}"
    docker build --platform "${PLATFORM}" -t "${IMG}" ../../ai-tims-front
  else
    JAR="${svc}-1.0.0-SNAPSHOT.jar"
    [ -f "../../ai-tims-parent/${svc}/target/${JAR}" ] \
      || { echo "[错误] 找不到 ${svc}/target/${JAR}，先跑 Maven 或去掉 SKIP_MAVEN" >&2; exit 1; }
    IMG="${IMAGE_NAMESPACE}/${svc}:${APP_VERSION}"
    echo "-- 后端: ${IMG}"
    docker build --platform "${PLATFORM}" \
      --build-arg JAR_FILE="target/${JAR}" \
      -f "${BACKEND_DOCKERFILE}" -t "${IMG}" "../../ai-tims-parent/${svc}"
  fi
  docker image inspect "${IMG}" --format 'OK  {{.RepoTags}}  {{.Size}} bytes  {{.Architecture}}'
done

echo
echo "== 构建完成清单 =="
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep -E "^${IMAGE_NAMESPACE}/" | grep ":${APP_VERSION}"
