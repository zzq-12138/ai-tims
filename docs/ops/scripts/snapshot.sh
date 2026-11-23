#!/usr/bin/env bash
# =============================================================================
# snapshot.sh —— 导出 ai-tims namespace 的全量快照
#
# 用途：答辩前/清理前留档；管理员误删后可据此恢复。
# 用法：
#   bash docs/ops/scripts/snapshot.sh
#   BACKUP_ROOT=/data/sdv1/tims/backups bash docs/ops/scripts/snapshot.sh
#
# 安全提示：
#   快照内含 Secret，YAML 中是 base64 编码的**真实凭据**（不是加密）。
#   本文件禁止提交到公开仓库、禁止外发；保存目录权限已收紧为 600/700。
# =============================================================================
set -euo pipefail

NS="ai-tims"
BACKUP_ROOT="${BACKUP_ROOT:-/data/sdv1/tims/backups}"
TS="$(date +%Y%m%d-%H%M%S)"
NAME="tims-snapshot-${TS}"
OUT="${BACKUP_ROOT}/${NAME}.tar.gz"

say() { printf '[snapshot] %s\n' "$*"; }
die() { printf '[snapshot][ERROR] %s\n' "$*" >&2; exit 1; }

command -v kubectl >/dev/null 2>&1 || die "未找到 kubectl"
kubectl get namespace "${NS}" >/dev/null 2>&1 || die "namespace ${NS} 不存在或无权访问，终止"

CTX="$(kubectl config current-context 2>/dev/null || echo unknown)"
say "当前 context：${CTX}"
say "目标 namespace：${NS}"

mkdir -p "${BACKUP_ROOT}"
chmod 700 "${BACKUP_ROOT}" 2>/dev/null || true
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${WORK}/objects"

# --- 0. 元信息 -------------------------------------------------------------
{
  echo "snapshot_time=${TS}"
  echo "kubectl_context=${CTX}"
  echo "namespace=${NS}"
  echo "kubectl_version=$(kubectl version --client --short 2>/dev/null | tr -d '\n' || true)"
  echo "server_version=$(kubectl version --short 2>/dev/null | grep -i server || true)"
} > "${WORK}/metadata.txt"

# --- 1. 全量对象 YAML（按类型分文件，便于按顺序恢复） ----------------------
say "导出对象 YAML（含 Secret，注意凭据）"
kubectl -n "${NS}" get configmaps      -o yaml > "${WORK}/objects/10-configmaps.yaml" 2>/dev/null || true
kubectl -n "${NS}" get secrets         -o yaml > "${WORK}/objects/10-secrets.yaml"    2>/dev/null || true
kubectl -n "${NS}" get pvc             -o yaml > "${WORK}/objects/20-pvc.yaml"        2>/dev/null || true
kubectl -n "${NS}" get statefulsets    -o yaml > "${WORK}/objects/30-statefulsets.yaml" 2>/dev/null || true
kubectl -n "${NS}" get deployments     -o yaml > "${WORK}/objects/40-deployments.yaml"  2>/dev/null || true
kubectl -n "${NS}" get services        -o yaml > "${WORK}/objects/50-services.yaml"     2>/dev/null || true
kubectl -n "${NS}" get ingress         -o yaml > "${WORK}/objects/60-ingress.yaml"      2>/dev/null || true
kubectl -n "${NS}" get resourcequota   -o yaml > "${WORK}/objects/60-resourcequota.yaml" 2>/dev/null || true
kubectl -n "${NS}" get limitrange      -o yaml > "${WORK}/objects/60-limitrange.yaml"   2>/dev/null || true

# --- 2. 人可读摘要 ---------------------------------------------------------
say "导出摘要"
kubectl -n "${NS}" get all -o wide            > "${WORK}/summary-all.txt"    2>/dev/null || true
kubectl -n "${NS}" get pods,sts,deploy -o wide > "${WORK}/summary-workloads.txt" 2>/dev/null || true
kubectl -n "${NS}" get pvc -o wide            > "${WORK}/summary-pvc.txt"    2>/dev/null || true
kubectl -n "${NS}" get events --sort-by=.lastTimestamp > "${WORK}/summary-events.txt" 2>/dev/null || true

# --- 3. Pod 镜像清单 -------------------------------------------------------
say "导出 Pod 镜像清单"
kubectl -n "${NS}" get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\t"}{range .spec.containers[*]}{.image}{" "}{end}{"\n"}{end}' \
  > "${WORK}/pod-images.txt" 2>/dev/null || true

# --- 4. 打包 ---------------------------------------------------------------
tar -czf "${OUT}" -C "${WORK}" .
chmod 600 "${OUT}" 2>/dev/null || true
( cd "${BACKUP_ROOT}" && sha256sum "$(basename "${OUT}")" > "$(basename "${OUT}").sha256" )
chmod 600 "${OUT}.sha256" 2>/dev/null || true

SIZE="$(du -h "${OUT}" | cut -f1)"
say "完成：${OUT}（${SIZE}）"
say "校验文件：${OUT}.sha256"
say "不含：MySQL 库内容、Nacos 配置、Harbor 镜像、vLLM —— 这些是公共资源，另行备份/保留"
say "恢复：bash docs/ops/scripts/restore.sh ${OUT}"
