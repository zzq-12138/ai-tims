#!/usr/bin/env bash
# 在 VM 执行：把本次交付的全部镜像打包成单 tar + sha256。
#   bash deploy/scripts/save-images.sh
# 产物：
#   dist/tims-images-<tag>.tar
#   dist/tims-images-<tag>.tar.sha256
#   dist/images-<tag>.txt
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
# shellcheck source=images.env
source "$SCRIPT_DIR/images.env"

command -v docker >/dev/null 2>&1 || { echo "缺少 docker"; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon 不可用"; exit 1; }

DIST=${DIST:-"$ROOT/deploy/dist"}
mkdir -p "$DIST"
TAR="$DIST/tims-images-${IMAGE_TAG}.tar"

ALL_REFS=()
APP_REFS=()
for svc in "${APP_IMAGES[@]}"; do
  ref="${REGISTRY_PREFIX}/${svc}:${IMAGE_TAG}"
  APP_REFS+=("$ref")
  ALL_REFS+=("$ref")
done

UPSTREAM_REFS=()
for entry in "${UPSTREAM_IMAGES[@]}"; do
  read -r _name src <<< "$entry"
  [[ -z "${_name:-}" ]] && continue
  UPSTREAM_REFS+=("$src")
  ALL_REFS+=("$src")
done

echo "==> 检查本地镜像（缺失的中间件镜像会尝试 docker pull）"
for ref in "${ALL_REFS[@]}"; do
  if docker image inspect "$ref" >/dev/null 2>&1; then
    continue
  fi
  is_upstream=0
  for up in "${UPSTREAM_REFS[@]}"; do
    [[ "$ref" == "$up" ]] && is_upstream=1 && break
  done
  if [[ "$is_upstream" -eq 1 ]]; then
    echo "    拉取 $ref"
    docker pull "$ref"
  else
    echo "缺少业务镜像 $ref，请先执行 deploy/scripts/build-images.sh"; exit 1
  fi
done

echo "==> docker save -> $TAR"
docker save -o "$TAR" "${ALL_REFS[@]}"

echo "==> 生成 sha256"
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$DIST" && sha256sum "$(basename "$TAR")" > "$(basename "$TAR").sha256")
  (cd "$DIST" && sha256sum -c "$(basename "$TAR").sha256")
else
  (cd "$DIST" && shasum -a 256 "$(basename "$TAR")" > "$(basename "$TAR").sha256")
  (cd "$DIST" && shasum -a 256 -c "$(basename "$TAR").sha256")
fi

{
  echo "# images for tag ${IMAGE_TAG}"
  printf '%s\n' "${ALL_REFS[@]}"
} > "$DIST/images-${IMAGE_TAG}.txt"

echo
echo "交付文件："
ls -lh "$TAR" "$TAR.sha256" "$DIST/images-${IMAGE_TAG}.txt"
echo "把以上 3 个文件 + deploy/ 目录一起带入公司内网。"
