#!/usr/bin/env bash
# =============================================================================
# restore.sh —— 从 snapshot.sh 产出的 tar.gz 恢复 ai-tims
#
# 用法：
#   bash docs/ops/scripts/restore.sh /data/sdv1/tims/backups/tims-snapshot-YYYYmmdd-HHMMSS.tar.gz
#
# 恢复顺序：ConfigMap / Secret → PVC → 中间件(StatefulSet) → 应用(Deployment) → Service → 其他
# 前置条件：namespace ai-tims 必须已存在（本脚本不会替你创建）。
# =============================================================================
set -euo pipefail

NS="ai-tims"
ARCHIVE="${1:-}"

say() { printf '[restore] %s\n' "$*"; }
die() { printf '[restore][ERROR] %s\n' "$*" >&2; exit 1; }

[ -n "${ARCHIVE}" ] || die "用法：restore.sh <备份 tar.gz>"
[ -f "${ARCHIVE}" ] || die "文件不存在：${ARCHIVE}"
command -v kubectl >/dev/null 2>&1 || die "未找到 kubectl"

# --- 1. 校验归档 -----------------------------------------------------------
if [ -f "${ARCHIVE}.sha256" ]; then
  say "校验 sha256"
  ( cd "$(dirname "${ARCHIVE}")" && sha256sum -c "$(basename "${ARCHIVE}").sha256" ) \
    || die "sha256 校验失败，归档可能损坏"
else
  say "未找到 .sha256，跳过校验（建议补校验）"
fi

# --- 2. namespace 存在性判断（必须先做） -----------------------------------
CTX="$(kubectl config current-context 2>/dev/null || echo unknown)"
say "当前 context：${CTX}"
if ! kubectl get namespace "${NS}" >/dev/null 2>&1; then
  say "namespace ${NS} 不存在。请先执行："
  say "  kubectl apply -f deploy/k8s/base/namespace.yaml"
  die "缺少目标 namespace，终止（不自动创建，避免建错环境）"
fi
say "namespace ${NS} 存在，继续"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
tar -xzf "${ARCHIVE}" -C "${WORK}"
OBJ="${WORK}/objects"
[ -d "${OBJ}" ] || die "归档结构异常：缺少 objects/ 目录"

apply_step() {
  local title="$1" file="$2"
  if [ ! -s "${file}" ]; then
    say "跳过 ${title}（文件为空）"
    return 0
  fi
  say "应用 ${title}：$(basename "${file}")"
  if kubectl apply -f "${file}"; then
    say "  -> ${title} 完成"
  else
    die "${title} 应用失败，已停止（后续步骤未执行）"
  fi
}

# --- 3. 按顺序恢复 ---------------------------------------------------------
apply_step "ConfigMap"                 "${OBJ}/10-configmaps.yaml"
apply_step "Secret"                    "${OBJ}/10-secrets.yaml"
apply_step "PVC"                       "${OBJ}/20-pvc.yaml"
apply_step "中间件 StatefulSet"         "${OBJ}/30-statefulsets.yaml"
apply_step "应用 Deployment"            "${OBJ}/40-deployments.yaml"
apply_step "Service"                   "${OBJ}/50-services.yaml"
apply_step "Ingress / Quota / LimitRange" "${OBJ}/60-ingress.yaml"
apply_step "ResourceQuota"              "${OBJ}/60-resourcequota.yaml"
apply_step "LimitRange"                 "${OBJ}/60-limitrange.yaml"

# --- 4. 等待就绪（不阻塞失败，仅提示） -------------------------------------
say "等待工作负载就绪（最多 180s，超时只告警不中断）"
kubectl -n "${NS}" rollout status statefulset --all --timeout=180s || say "警告：部分 StatefulSet 未在 180s 内就绪"
kubectl -n "${NS}" rollout status deployment  --all --timeout=180s || say "警告：部分 Deployment 未在 180s 内就绪"

say "恢复结束。请执行以下命令核对："
say "  kubectl -n ${NS} get pods"
say "  kubectl -n ${NS} get svc"
say "公共依赖（MySQL / Nacos / Harbor / vLLM）不由本脚本恢复，需在外部确认可用"
