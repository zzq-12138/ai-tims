#!/usr/bin/env bash
# 在「能访问公司镜像仓库」的机器执行（公司跳板机/构建机，需装 Docker）：
#   COMPANY_REGISTRY=harbor.公司域名 bash deploy/scripts/load-and-push.sh dist/tims-images-1.0.0.tar
# 流程：校验 sha256 -> docker load -> 重打 tag -> push
# 只加载不推送：PUSH=0 ...
set -euo pipefail

TAR=${1:-}
if [[ -z "$TAR" || ! -f "$TAR" ]]; then
  echo "用法：COMPANY_REGISTRY=<仓库域名> bash $0 <tims-images-<tag>.tar>"
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=images.env
source "$SCRIPT_DIR/images.env"

COMPANY_REGISTRY=${COMPANY_REGISTRY:-harbor.example.com}
COMPANY_REGISTRY=${COMPANY_REGISTRY%/}
PUSH=${PUSH:-1}
TARGET_PREFIX="${COMPANY_REGISTRY}/ai-tims"

command -v docker >/dev/null 2>&1 || { echo "缺少 docker"; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon 不可用"; exit 1; }

echo "==> 校验 sha256"
if [[ ! -f "$TAR.sha256" ]]; then
  echo "缺少 $TAR.sha256，拒绝继续"; exit 1
fi
TAR_DIR=$(cd "$(dirname "$TAR")" && pwd)
TAR_NAME=$(basename "$TAR")
(cd "$TAR_DIR" && sha256sum -c "${TAR_NAME}.sha256")

echo "==> docker load"
docker load -i "$TAR"

TARGETS=()
for svc in "${APP_IMAGES[@]}"; do
  src="${REGISTRY_PREFIX}/${svc}:${IMAGE_TAG}"
  dst="${TARGET_PREFIX}/${svc}:${IMAGE_TAG}"
  docker image inspect "$src" >/dev/null 2>&1 || { echo "load 后缺少 $src"; exit 1; }
  docker tag "$src" "$dst"
  TARGETS+=("$dst")
done

for entry in "${UPSTREAM_IMAGES[@]}"; do
  read -r name src <<< "$entry"
  [[ -z "${name:-}" ]] && continue
  tag=${src##*:}
  dst="${TARGET_PREFIX}/${name}:${tag}"
  docker image inspect "$src" >/dev/null 2>&1 || { echo "load 后缺少 $src"; exit 1; }
  docker tag "$src" "$dst"
  TARGETS+=("$dst")
done

if [[ "$PUSH" != "1" ]]; then
  echo "PUSH=0，已完成重打 tag，未推送："
  printf '  %s\n' "${TARGETS[@]}"
  exit 0
fi

echo "==> 推送到 ${TARGET_PREFIX}"
for img in "${TARGETS[@]}"; do
  echo "--- $img"
  docker push "$img"
done

echo
echo "推送完成。把 deploy/k8s/overlays/company/kustomization.yaml 里的"
echo "harbor.example.com 改成 ${COMPANY_REGISTRY} 后再 apply。"
