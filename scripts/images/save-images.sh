#!/usr/bin/env bash
# =====================================================================
# save-images.sh - 把全部业务镜像 + 基础镜像 save 成 tar（含 sha256 校验）
# 只在 VM 上执行。产出：${OUT_DIR}/tims-images-${APP_VERSION}.tar(.sha256)
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"
source ./images.env

case "${APP_VERSION:-}" in
  ""|latest|Latest|LATEST)
    echo "[错误] APP_VERSION 未设置或为 latest" >&2; exit 1;;
esac

# 可选参数：只 save 指定服务（如 ./save-images.sh ticket-push），默认全量 7 镜像
TARGETS="${SERVICES}"
if [ $# -gt 0 ]; then
  TARGETS="$*"
fi

OUT_DIR="${OUT_DIR:-${OUT_DIR_DEFAULT}}"
SUFFIX=$(echo "${TARGETS}" | tr ' ' '-')
mkdir -p "${OUT_DIR}"
TAR="${OUT_DIR}/tims-images-${SUFFIX}-${APP_VERSION}.tar"

# ---------- 组装镜像清单：业务镜像 + 基础镜像 ----------
IMAGES=()
for svc in ${TARGETS}; do
  if [ "$svc" = "front" ]; then IMAGES+=("${IMAGE_NAMESPACE}/${FRONT_IMAGE_NAME}:${APP_VERSION}")
  else IMAGES+=("${IMAGE_NAMESPACE}/${svc}:${APP_VERSION}"); fi
done
BASES=("${BACKEND_BASE_IMAGE}" "${FRONT_BASE_IMAGE}")

# ---------- 拉取基础镜像（一次拉取，后续走本地缓存）----------
echo "== 拉取基础镜像（--platform ${PLATFORM}）=="
for b in "${BASES[@]}"; do
  docker pull --platform "${PLATFORM}" "${b}"
  IMAGES+=("${b}")
done

# ---------- 检查业务镜像是否都已构建 ----------
echo "== 检查业务镜像 =="
MISSING=0
for img in "${IMAGES[@]}"; do
  if ! docker image inspect "${img}" > /dev/null 2>&1; then
    echo "[缺失] ${img}（先跑 build-images.sh）" >&2; MISSING=1
  fi
done
[ "${MISSING}" = "0" ] || exit 1

# ---------- docker save ----------
echo "== docker save -> ${TAR} =="
docker save --platform "${PLATFORM}" -o "${TAR}" "${IMAGES[@]}"

# ---------- sha256 校验文件 ----------
echo "== 生成 sha256 =="
( cd "${OUT_DIR}" && sha256sum "$(basename "${TAR}")" > "$(basename "${TAR}").sha256" )

# ---------- 体积汇总 ----------
echo
echo "== 交付包清单（目录：${OUT_DIR}）=="
ls -lh "${OUT_DIR}"/$(basename "${TAR}")*
TOTAL=$(du -ch "${TAR}" | cut -f1)
echo "总体积：${TOTAL}"
echo
echo "校验方式：sha256sum -c $(basename "${TAR}").sha256"
