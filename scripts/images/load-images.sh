#!/usr/bin/env bash
# =====================================================================
# load-images.sh - 【公司内网侧执行】docker load + 按公司前缀重新 tag
#
# 用法：
#   ./load-images.sh /path/to/tims-images-<版本>.tar
#   （或把 tar 与 .sha256 放本脚本同目录后：./load-images.sh）
#
# 前提：images.env 已随包带来；REGISTRY_PREFIX 已由公司使用人填写
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"
source ./images.env

case "${APP_VERSION:-}" in
  ""|latest|Latest|LATEST)
    echo "[错误] APP_VERSION 未设置或为 latest" >&2; exit 1;;
esac

# ---------- 定位 tar ----------
TAR="${1:-}"
if [ -z "${TAR}" ]; then
  TAR="./tims-images-${APP_VERSION}.tar"
  [ -f "${TAR}" ] || { echo "[错误] 未指定 tar 路径，且当前目录没有 ${TAR}" >&2; exit 1; }
fi
[ -f "${TAR}" ] || { echo "[错误] tar 不存在：${TAR}" >&2; exit 1; }

# ---------- sha256 校验 ----------
SHA="${TAR}.sha256"
if [ -f "${SHA}" ]; then
  echo "== sha256 校验 =="
  ( cd "$(dirname "$(realpath "${TAR}")")" && sha256sum -c "$(basename "${SHA}")" )
else
  echo "[警告] 找不到 ${SHA}，跳过校验（正常流程不允许跳过，请确认包完整性）" >&2
fi

# ---------- docker load ----------
echo "== docker load =="
docker load -i "${TAR}"

# ---------- 重新 tag 到公司仓库前缀 ----------
if [ -z "${REGISTRY_PREFIX}" ]; then
  echo
  echo "[提示] images.env 中 REGISTRY_PREFIX 为空，只完成 load，未做公司侧 tag。"
  echo "       填好 REGISTRY_PREFIX（如 registry.corp.example.com/tims）后重跑本脚本即可自动 tag。"
  echo "== 本地已 load 的镜像 =="
  docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^${IMAGE_NAMESPACE}/.*:${APP_VERSION}"
  exit 0
fi

echo "== tag -> ${REGISTRY_PREFIX}/xxx:${APP_VERSION} =="
FAIL=0
for svc in ${SERVICES} ${FRONT_IMAGE_NAME}; do
  SRC="${IMAGE_NAMESPACE}/${svc}:${APP_VERSION}"
  DST="${REGISTRY_PREFIX}/${svc}:${APP_VERSION}"
  if docker image inspect "${SRC}" > /dev/null 2>&1; then
    docker tag "${SRC}" "${DST}" && echo "OK  ${DST}"
  else
    echo "[缺失] ${SRC}（tar 里没有这个镜像，检查 save 是否齐全）" >&2; FAIL=1
  fi
done

echo
[ "${FAIL}" = "0" ] && echo "== load + tag 全部完成，可执行 ./push-images.sh ==" || exit 1
