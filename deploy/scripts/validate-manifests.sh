#!/usr/bin/env bash
# 渲染 + 静态校验（不做任何集群写操作）。
# 优先使用 kubeconform 按 1.24.17 schema 严格校验；没有 kubeconform 时退化为
# kubectl/kustomize 渲染 + apply --dry-run=client --validate=false。
#
# 在能联网的 VM 上：
#   bash deploy/scripts/validate-manifests.sh
# 注意：k3s 1.36 跑通不能当作 1.24 兼容证据，本脚本只认 -kubernetes-version 1.24.17 的结果。
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
OVERLAY=${1:-"$ROOT/deploy/k8s/overlays/company"}
OUT=${OUT:-"$(mktemp -t tims-manifests.XXXXXX.yaml)"}

echo "==> 渲染 $OVERLAY"
if command -v kubectl >/dev/null 2>&1; then
  kubectl kustomize "$OVERLAY" > "$OUT"
elif command -v kustomize >/dev/null 2>&1; then
  kustomize build "$OVERLAY" > "$OUT"
else
  echo "缺少 kubectl / kustomize，无法渲染"; exit 2
fi
echo "    渲染结果：$OUT"

echo "==> 1.25+ 字段/API 黑名单扫描"
if grep -nE 'schedulingGates|restartPolicy:[[:space:]]*Always|podFailurePolicy|trafficDistribution|hostUsers:|seLinuxChangePolicy|appArmorProfile|apiVersion:[[:space:]]*(extensions/v1beta1|networking.k8s.io/v1beta1|policy/v1beta1|autoscaling/v2beta[0-9])' "$OUT"; then
  echo "命中 1.25+ 或已废弃 API/字段，校验失败"; exit 1
else
  echo "    未命中"
fi

echo "==> 2. kubeconform（1.24.17 schema）"
if command -v kubeconform >/dev/null 2>&1; then
  kubeconform -strict -summary -kubernetes-version 1.24.17 "$OUT"
else
  echo "    kubeconform 未安装，跳过（脚本不会把这一步当作通过）"
fi

echo "==> 3. kubectl client dry-run"
if command -v kubectl >/dev/null 2>&1; then
  kubectl apply --dry-run=client --validate=false -f "$OUT" >/dev/null
  echo "    dry-run=client 通过（仅语法/必填字段，不等于 1.24 API 兼容）"
else
  echo "    kubectl 未安装，跳过"
fi
