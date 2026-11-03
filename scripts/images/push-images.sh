#!/usr/bin/env bash
# =====================================================================
# push-images.sh - 【公司内网侧执行】批量 push 到公司镜像仓库
#
# 前提：
#   1. images.env 的 REGISTRY_PREFIX 已填写
#   2. 已完成 docker login（或设置 REG_USER/REG_PASS 环境变量由本脚本登录）
#      例：REG_USER=dev REG_PASS='xxx' ./push-images.sh
#
# 失败可见性：逐镜像 push，失败时打印镜像名与错误原文，最后汇总；任一失败则退出码非 0
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")"
source ./images.env

case "${APP_VERSION:-}" in
  ""|latest|Latest|LATEST)
    echo "[错误] APP_VERSION 未设置或为 latest" >&2; exit 1;;
esac
[ -n "${REGISTRY_PREFIX}" ] || { echo "[错误] REGISTRY_PREFIX 为空，请先在 images.env 填写公司仓库地址" >&2; exit 1; }

# ---------- 登录（可选）----------
if [ -n "${REG_USER:-}" ] && [ -n "${REG_PASS:-}" ]; then
  echo "== docker login ${REGISTRY_PREFIX%%/*} =="
  echo "${REG_PASS}" | docker login "$(echo "${REGISTRY_PREFIX}" | cut -d/ -f1)" --username "${REG_USER}" --password-stdin \
    || { echo "[错误] docker login 失败，检查账号/密码/仓库地址" >&2; exit 1; }
else
  echo "[提示] 未提供 REG_USER/REG_PASS，跳过登录（若仓库要求鉴权，push 时会报 unauthorized）"
fi

# ---------- 逐镜像 push ----------
PASS_LIST=(); FAIL_LIST=()
for svc in ${SERVICES} ${FRONT_IMAGE_NAME}; do
  IMG="${REGISTRY_PREFIX}/${svc}:${APP_VERSION}"
  echo "=================================================="
  echo "== push: ${IMG}"
  echo "=================================================="
  if OUT=$(docker push "${IMG}" 2>&1); then
    echo "${OUT}" | tail -2
    PASS_LIST+=("${svc}")
  else
    echo "[失败] ${IMG}"
    echo "${OUT}" | tail -5      # 打印错误原文尾部，便于判读（鉴权/空间/网络/tag 不存在）
    FAIL_LIST+=("${svc}")
  fi
done

# ---------- 汇总 ----------
echo
echo "================ push 汇总（版本 ${APP_VERSION}）================"
echo "成功 ${#PASS_LIST[@]} 个：${PASS_LIST[*]:-无}"
echo "失败 ${#FAIL_LIST[@]} 个：${FAIL_LIST[*]:-无}"
[ ${#FAIL_LIST[@]} -eq 0 ] || { echo "[结果] 存在失败镜像：对照上方错误原文排查后重跑本脚本（push 幂等，已成功的重复推送无副作用）"; exit 1; }
echo "[结果] 全部推送成功"
