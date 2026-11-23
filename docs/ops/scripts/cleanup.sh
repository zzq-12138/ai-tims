#!/usr/bin/env bash
# =============================================================================
# cleanup.sh —— 答辩后清理 ai-tims（默认 dry-run，仅打印）
#
# 用法：
#   bash docs/ops/scripts/cleanup.sh --context <集群context>            # 演练，不删任何东西
#   bash docs/ops/scripts/cleanup.sh --context <集群context> --yes      # 真正删除
#
# 规则：
#   1) 只允许操作 namespace = ai-tims；
#   2) 必须显式传 --context，且与当前 kubectl context 完全一致，否则拒绝执行；
#   3) 默认 dry-run；只有 --yes 才会落库删除；
#   4) 只删 ai-tims 内的对象，公共 MySQL / Nacos / Harbor / vLLM 一律不动。
# =============================================================================
set -euo pipefail

NS="ai-tims"
DO_DELETE=0
EXPECTED_CONTEXT=""

say()  { printf '[cleanup] %s\n' "$*"; }
warn() { printf '[cleanup][WARN] %s\n' "$*" >&2; }
die()  { printf '[cleanup][ERROR] %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'EOF'
用法：
  cleanup.sh --context <集群context>           # dry-run，只打印
  cleanup.sh --context <集群context> --yes     # 真正删除

示例：
  kubectl config get-contexts
  bash docs/ops/scripts/cleanup.sh --context kubernetes-admin@kubernetes
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --yes)        DO_DELETE=1 ;;
    --context)    EXPECTED_CONTEXT="${2:-}"; shift ;;
    --context=*)  EXPECTED_CONTEXT="${1#*=}" ;;
    -h|--help)    usage; exit 0 ;;
    *)            die "未知参数：$1（用 --help 查看用法）" ;;
  esac
  shift
done

# --- 1. 前置校验：工具 / context / namespace --------------------------------
command -v kubectl >/dev/null 2>&1 || die "未找到 kubectl"
[ -n "${EXPECTED_CONTEXT}" ] || die "必须显式传 --context <集群context>，防止误连集群"

CURRENT_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"
[ -n "${CURRENT_CONTEXT}" ] || die "拿不到当前 context，检查 kubeconfig"
say "当前 context：${CURRENT_CONTEXT}"
[ "${CURRENT_CONTEXT}" = "${EXPECTED_CONTEXT}" ] \
  || die "context 不匹配（期望 ${EXPECTED_CONTEXT}，实际 ${CURRENT_CONTEXT}），拒绝执行"

[ "${NS}" = "ai-tims" ] || die "内部错误：namespace 常量被改，终止"
kubectl get namespace "${NS}" >/dev/null 2>&1 || die "namespace ${NS} 不存在，无需清理"

say "目标 namespace 已确认：${NS}"
say "Server：$(kubectl version --short 2>/dev/null | grep -i server || echo unknown)"

# --- 2. 打印将删除的对象（dry-run 与执行都先打印） --------------------------
print_kind() {
  local kind="$1"
  local items
  items="$(kubectl -n "${NS}" get "${kind}" -o name 2>/dev/null || true)"
  if [ -z "${items}" ]; then
    say "  ${kind}: （无）"
  else
    say "  ${kind}:"
    printf '%s\n' "${items}" | sed 's/^/    - /'
  fi
}

say "将被删除的对象："
print_kind deployments
print_kind statefulsets
print_kind services
print_kind ingress
print_kind configmaps
print_kind secrets
print_kind persistentvolumeclaims
print_kind resourcequotas
print_kind limitranges

say "PVC 数据将随删除永久丢失（etcd/minio/milvus/order-uploads）"

# --- 3. 明确列出「不删」的部分 ---------------------------------------------
cat <<'EOF'
[cleanup] 以下公共资源【不删】，清理后应保持原样：
  - MySQL   10.96.1.253:3306   库 aitims（属 mlops-train-test 公共实例）
  - Nacos   10.96.1.240:8848   命名空间 zzq-tims（ID 7a8fa30c-0121-4606-8c17-f6b932e9c80a）
  - Harbor  harbor.xnunion.com/library 下的 11 个镜像
  - vLLM    172.27.26.253:18892（对话）/ :18893（向量）
  - 任何不在 ai-tims 内的对象（含其他 namespace 的 Deployment/ConfigMap/Service/PVC）
EOF

if [ "${DO_DELETE}" -ne 1 ]; then
  say "当前为 dry-run：未删除任何对象。确认无误后加 --yes 执行。"
  exit 0
fi

# --- 4. 真正删除（按依赖顺序：先应用，后中间件，最后 namespace） ----------
say "开始删除（不可撤销）。5 秒后执行，Ctrl+C 可中止"
sleep 5

delete_kind() {
  local kind="$1"
  say "删除 ${kind} ..."
  kubectl -n "${NS}" delete "${kind}" --all --ignore-not-found --wait=true || warn "${kind} 删除存在报错，请复查"
}

delete_kind deployments
delete_kind statefulsets
delete_kind services
delete_kind ingress
delete_kind configmaps
delete_kind secrets
delete_kind persistentvolumeclaims
delete_kind resourcequotas
delete_kind limitranges

say "删除 namespace ${NS}（会带走剩余对象）"
kubectl delete namespace "${NS}" --ignore-not-found --wait=true || warn "namespace 删除报错，请复查"

say "清理结束。核对：kubectl get ns ${NS} 应返回 NotFound"
say "如需恢复：bash docs/ops/scripts/restore.sh <最近一次快照 tar.gz>"
say "注意：restore 只能恢复对象与配置，PVC 内数据需依赖快照/重建；公共库数据不在恢复范围"
