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

echo "==> 4. LimitRange / ResourceQuota / 探针 / 端口自洽"
if command -v kubectl >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  JSON_OUT=$(mktemp -t tims-manifests.XXXXXX.json)
  kubectl create --dry-run=client -o json -f "$OUT" > "$JSON_OUT" 2>/dev/null
  python3 - "$JSON_OUT" <<'PY'
import json
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
dec = json.JSONDecoder()
objs, i, n = [], 0, len(text)
while i < n:
    while i < n and text[i].isspace():
        i += 1
    if i >= n:
        break
    obj, i = dec.raw_decode(text, i)
    objs.append(obj)

UNITS = [("Ki", 1024), ("Mi", 1024 ** 2), ("Gi", 1024 ** 3), ("Ti", 1024 ** 4),
         ("m", 0.001), ("k", 1e3), ("M", 1e6), ("G", 1e9), ("T", 1e12)]


def qty(s):
    s = str(s).strip()
    for u, f in UNITS:
        if s.endswith(u):
            return float(s[:-len(u)]) * f
    return float(s)


def pod_template(o):
    k = o.get("kind")
    if k in ("Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"):
        tpl = o["spec"]["template"]
        return tpl["spec"], int(o["spec"].get("replicas", 1)), tpl["metadata"].get("labels", {})
    if k == "Job":
        tpl = o["spec"]["template"]
        return tpl["spec"], 1, tpl["metadata"].get("labels", {})
    if k == "CronJob":
        tpl = o["spec"]["jobTemplate"]["spec"]["template"]
        return tpl["spec"], 1, tpl["metadata"].get("labels", {})
    return None, 0, {}


problems = []
workloads = {}
pod_labels = {}
for o in objs:
    spec, replicas, labels = pod_template(o)
    if spec is None:
        continue
    workloads[o["metadata"]["name"]] = (o, spec, replicas)
    pod_labels[o["metadata"]["name"]] = labels

# --- LimitRange 上界 ---
MAX_CPU, MAX_MEM = 4.0, 8 * 1024 ** 3
container_count = 0
sum_req_cpu = sum_req_mem = sum_lim_cpu = sum_lim_mem = 0.0
for name, (o, spec, replicas) in workloads.items():
    for c in spec.get("containers", []) + spec.get("initContainers", []):
        container_count += 1
        r = c.get("resources") or {}
        req, lim = r.get("requests") or {}, r.get("limits") or {}
        if "cpu" not in req or "memory" not in req or "cpu" not in lim or "memory" not in lim:
            problems.append(f"{name}/{c['name']} 未显式声明 requests+limits（配额核算不确定）")
            continue
        rc, rm = qty(req["cpu"]), qty(req["memory"])
        lc, lm = qty(lim["cpu"]), qty(lim["memory"])
        if lc > MAX_CPU + 1e-9 or lm > MAX_MEM + 1:
            problems.append(f"{name}/{c['name']} limits {lc}核/{lm/1024**3:.2f}Gi 超过 LimitRange.max")
        if rc > lc + 1e-9 or rm > lm + 1:
            problems.append(f"{name}/{c['name']} requests 大于 limits")
        sum_req_cpu += rc * replicas
        sum_req_mem += rm * replicas
        sum_lim_cpu += lc * replicas
        sum_lim_mem += lm * replicas

for key, total, cap in (("requests.cpu", sum_req_cpu, 6.0),
                        ("requests.memory", sum_req_mem, 16 * 1024 ** 3),
                        ("limits.cpu", sum_lim_cpu, 16.0),
                        ("limits.memory", sum_lim_mem, 32 * 1024 ** 3)):
    if total > cap + 1e-6:
        problems.append(f"ResourceQuota 超限：{key} 合计 {total:.3g} > {cap:.3g}")

# --- PVC / Pod / Service 计数与存储 ---
pvcs = [o for o in objs if o.get("kind") == "PersistentVolumeClaim"]
total_storage = sum(qty((p["spec"].get("resources") or {}).get("requests", {}).get("storage", "0"))
                    for p in pvcs)
if len(pvcs) > 12:
    problems.append(f"PVC 数量 {len(pvcs)} > ResourceQuota 12")
if total_storage > 100 * 1024 ** 3 + 1:
    problems.append(f"requests.storage 合计 {total_storage/1024**3:.1f}Gi > 100Gi")
total_pods = sum(rep for _, _, rep in workloads.values())
services = [o for o in objs if o.get("kind") == "Service"]
if total_pods > 40:
    problems.append(f"Pod 副本合计 {total_pods} > 40")
if len(services) > 20:
    problems.append(f"Service 数量 {len(services)} > 20")

# --- 探针端口可解析 + 应用端口口径 ---
EXPECTED = {"ticket-gateway": 8080, "ticket-system": 8101, "ticket-order": 8102,
            "ticket-knowledge": 8103, "ticket-ai": 8104, "ticket-push": 8105}
APP_PROBES = {"/actuator/health/liveness", "/actuator/health/readiness"}
probe_count = 0
for name, (o, spec, _replicas) in workloads.items():
    for c in spec.get("containers", []):
        ports = c.get("ports") or []
        by_name = {p.get("name"): p.get("containerPort") for p in ports if p.get("name")}
        numbers = {p.get("containerPort") for p in ports}
        for probe_name in ("startupProbe", "readinessProbe", "livenessProbe"):
            probe = c.get(probe_name) or {}
            http = probe.get("httpGet")
            if not http:
                continue
            probe_count += 1
            port = http.get("port")
            resolved = by_name.get(port, port) if isinstance(port, str) else port
            if resolved not in numbers:
                problems.append(f"{name}/{c['name']} {probe_name} 端口 {port} 未匹配 containerPort")
            if name in EXPECTED and http.get("path") not in APP_PROBES:
                problems.append(f"{name}/{c['name']} {probe_name} 路径 {http.get('path')} 不是 Actuator 探针路径")

for app, port in EXPECTED.items():
    if app not in workloads:
        problems.append(f"缺少应用工作负载 {app}")
        continue
    o, spec, _ = workloads[app]
    nums = [p.get("containerPort") for c in spec["containers"] for p in (c.get("ports") or [])]
    if port not in nums:
        problems.append(f"{app} containerPort 未使用约定端口 {port}（实际 {nums}）")
    svc = next((s for s in services if s["metadata"]["name"] == app), None)
    if svc is None:
        problems.append(f"{app} 缺少同名 Service")
    elif port not in [p.get("port") for p in svc["spec"]["ports"]]:
        problems.append(f"{app} Service port 与约定 {port} 不一致")

# --- Service targetPort 必须能落到后端容器端口 ---
for svc in services:
    selector = svc["spec"].get("selector") or {}
    if not selector:
        continue
    matched = [name for name in workloads
               if all(pod_labels[name].get(k) == v for k, v in selector.items())]
    for p in svc["spec"]["ports"]:
        tp = p.get("targetPort")
        if tp is None or isinstance(tp, int) or not matched:
            continue
        ok = any(tp in {cp.get("name") for cp in (c.get("ports") or [])}
                 for name in matched for c in workloads[name][1].get("containers", []))
        if not ok:
            problems.append(f"Service {svc['metadata']['name']} targetPort={tp} 在后端容器端口名中不存在")

# --- 镜像名可参数化（必须带 registry 前缀）---
for name, (o, spec, _) in workloads.items():
    for c in spec.get("containers", []):
        image = c.get("image", "")
        first = image.split("/")[0]
        if "/" not in image or not ("." in first or ":" in first):
            problems.append(f"{name}/{c['name']} 镜像 {image} 缺少 registry 前缀（不可参数化）")

if problems:
    print(f"    [FAIL] {len(problems)} 项不自洽：")
    for p in problems:
        print(f"      - {p}")
    sys.exit(1)

print(f"    [OK] 工作负载 {len(workloads)} 个 / 容器 {container_count} 个，requests+limits 全显式")
print(f"    [OK] 单容器 limits 未超 LimitRange.max（4 核 / 8Gi）")
print(f"    [OK] 汇总 requests {sum_req_cpu:.2f} 核 / {sum_req_mem/1024**3:.2f}Gi "
      f"<= 6 核 / 16Gi；limits {sum_lim_cpu:.2f} 核 / {sum_lim_mem/1024**3:.2f}Gi <= 16 核 / 32Gi")
print(f"    [OK] PVC {len(pvcs)} 个 / {total_storage/1024**3:.1f}Gi <= 12 / 100Gi；"
      f"Pod 副本 {total_pods} <= 40；Service {len(services)} <= 20")
print(f"    [OK] {probe_count} 个 httpGet 探针端口均可解析到 containerPort，路径为 Actuator 口径")
print(f"    [OK] 六服务端口 8080/8101/8102/8103/8104/8105 与 Service 一致；镜像均带 registry 前缀")
PY
  rm -f "$JSON_OUT"
else
  echo "    缺少 kubectl 或 python3，跳过自洽检查（不计为通过）"
fi
