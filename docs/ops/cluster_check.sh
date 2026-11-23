#!/usr/bin/env bash
# TIMS K8s 集群余量体检（只读）
# 只用 kubectl 读取，不创建/修改/删除任何资源；无权限或没装 kubectl 时给出提示并正常退出。
# 用法: bash cluster_check.sh
# 说明: 统计"常规容器"的 requests/limits（K8s 调度还会看 initContainer 峰值，此处按常规容器估算）。

export LC_ALL=C
TO=""
command -v timeout >/dev/null 2>&1 && TO="timeout 10"

echo "== TIMS K8s 集群余量体检 v1.0（只读）=="
echo "time: $(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)   KUBECONFIG=${KUBECONFIG:-未设置（用默认 ~/.kube/config）}"
echo ""

# ---------- 0. 前置检查 ----------
if ! command -v kubectl >/dev/null 2>&1; then
  echo "结论: 无法检查 —— 本机没有 kubectl。"
  echo "处理: 换到能访问集群的跳板机执行；本脚本不安装任何东西。"
  exit 0
fi
if ! $TO kubectl version --request-timeout=5s >/dev/null 2>&1; then
  echo "结论: 无法检查 —— kubectl 连不上集群 API。"
  echo "可能原因: ① KUBECONFIG 未设置或路径不对 ② 证书过期 ③ 网络不通 ④ 账号被禁用。"
  echo "自检: kubectl cluster-info ; kubectl get ns"
  exit 0
fi

# ---------- 1. 采集 ----------
NODES_OK=1
NODE_TSV=$($TO kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.allocatable.cpu}{"\t"}{.status.allocatable.memory}{"\t"}{.spec.unschedulable}{"\t"}{range .status.conditions[?(@.type=="Ready")]}{.status}{end}{"\t"}{.metadata.labels.node-role\.kubernetes\.io/control-plane}{"\t"}{range .spec.taints[*]}{.key}={.value}:{.effect};{end}{"\n"}{end}' 2>/dev/null)
[ -z "$NODE_TSV" ] && NODES_OK=0

PODS_OK=1
POD_TSV=$($TO kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"|"}{.spec.nodeName}{"|"}{.status.phase}{"|"}{range .spec.containers[*]}{.resources.requests.cpu}{","}{.resources.requests.memory}{","}{.resources.limits.cpu}{","}{.resources.limits.memory}{";"}{end}{"\n"}{end}' 2>/dev/null)
[ -z "$POD_TSV" ] && PODS_OK=0

TOP_TSV=""
TOP_OK=1
TOP_TSV=$($TO kubectl top nodes --no-headers 2>/dev/null | awk '{print "TOP|"$1"|"$2"|"$4}')
[ -z "$TOP_TSV" ] && TOP_OK=0

if [ "$PODS_OK" = 0 ]; then
  echo "【采集】当前账号连 Pod 列表都读不到（RBAC 受限），只能给到节点视角或直接无法估算。"
  echo "结论: 无法检查 —— 请向集群管理员申请只读权限（nodes / pods 的 get、list）。"
  exit 0
fi

# ---------- 2. 汇总 + 输出 ----------
{ [ "$NODES_OK" = 1 ] && printf '%s\n' "$NODE_TSV" | sed 's/^/NODE\t/'
  printf '%s\n' "$POD_TSV" | sed 's/^/POD|/'
  [ -n "$TOP_TSV" ] && printf '%s\n' "$TOP_TSV"
} | awk -F'\t' '
function to_mcpu(v) {
  if (v == "") return 0
  if (v ~ /m$/) return substr(v,1,length(v)-1)+0
  return (v+0)*1000
}
function to_mi(v) {
  if (v == "") return 0
  if (v ~ /Ki$/) return substr(v,1,length(v)-2)/1024
  if (v ~ /Mi$/) return substr(v,1,length(v)-2)+0
  if (v ~ /Gi$/) return substr(v,1,length(v)-2)*1024
  if (v ~ /Ti$/) return substr(v,1,length(v)-2)*1048576
  if (v ~ /K$/)  return substr(v,1,length(v)-1)/1024
  if (v ~ /M$/)  return substr(v,1,length(v)-1)+0
  if (v ~ /G$/)  return substr(v,1,length(v)-1)*1024
  return (v+0)/1048576
}
/^NODE\t/ {
  split(substr($0,6), a, "\t")
  n++; name=a[1]
  order[n]=name
  acpu[name]=to_mcpu(a[2]); amem[name]=to_mi(a[3])
  unsched[name]=a[4]; ready[name]=a[5]; cp[name]=a[6]; taints[name]=a[7]
  next
}
/^POD\|/ {
  split(substr($0,5), b, "|")
  ns=b[1]; node=b[2]; phase=b[3]
  if (phase == "Succeeded" || phase == "Failed") next
  npod[node]++; npod_ns[ns]++
  ncn = split(b[4], cs, ";")
  for (i = 1; i <= ncn; i++) {
    if (cs[i] == "") continue
    split(cs[i], f, ",")
    rcpu = to_mcpu(f[1]); rmem = to_mi(f[2])
    lcpu = to_mcpu(f[3]); lmem = to_mi(f[4])
    nrcpu[node] += rcpu; nrmem[node] += rmem
    nlcpu[node] += lcpu; nlmem[node] += lmem
    nsrcpu[ns] += rcpu; nsrmem[ns] += rmem
    nslmem[ns] += lmem
  }
  next
}
/^TOP\|/ {
  split(substr($0,5), t, "|")
  topok[t[1]] = 1
  tacpu[t[1]] = to_mcpu(t[2]); tamem[t[1]] = to_mi(t[3])
  next
}
END {
  printf "【1】节点余量（Allocatable / 已申请 Requests / Limits）\n"
  if (n == 0) {
    printf "  （无读取节点权限，跳过；下面只给命名空间视角）\n"
  }
  tot_cpu_rem = 0; tot_mem_rem = 0
  tot_cpu_act = 0; tot_mem_act = 0; act_nodes = 0
  for (i = 1; i <= n; i++) {
    nm = order[i]
    role = (cp[nm] == "true") ? "control-plane" : "worker"
    rdy = (ready[nm] == "True") ? "Ready" : "NotReady"
    blocked = (unsched[nm] == "true") || (ready[nm] != "True") || (taints[nm] ~ /NoSchedule|NoExecute/)
    sched = blocked ? "不可调度" : "可调度"
    rem_cpu = acpu[nm] - nrcpu[nm]; if (rem_cpu < 0) rem_cpu = 0
    rem_mem = amem[nm] - nrmem[nm]; if (rem_mem < 0) rem_mem = 0
    printf "\n- %s  [%s] %s  %s  pods=%d\n", nm, role, rdy, sched, npod[nm]
    printf "  Alloc: %.1fC / %.1fG    Req: %.1fC(%.0f%%) / %.1fG(%.0f%%)    Lim: %.1fC / %.1fG\n", \
      acpu[nm]/1000, amem[nm]/1024, nrcpu[nm]/1000, (acpu[nm]>0 ? nrcpu[nm]*100/acpu[nm] : 0), \
      nrmem[nm]/1024, (amem[nm]>0 ? nrmem[nm]*100/amem[nm] : 0), nlcpu[nm]/1000, nlmem[nm]/1024
    if (topok[nm]) {
      printf "  实际: %.2fC / %.1fG（top）    按 Requests 剩余: %.1fC / %.1fG\n", \
        tacpu[nm]/1000, tamem[nm]/1024, rem_cpu/1000, rem_mem/1024
    } else {
      printf "  实际: 无 metrics 数据    按 Requests 剩余: %.1fC / %.1fG\n", rem_cpu/1000, rem_mem/1024
    }
    if (!blocked) {
      tot_cpu_rem += rem_cpu; tot_mem_rem += rem_mem
      if (topok[nm]) {
        tot_cpu_act += (acpu[nm] - tacpu[nm]); tot_mem_act += (amem[nm] - tamem[nm]); act_nodes++
      }
    }
  }

  printf "\n【2】不可调度 / 受限节点\n"
  bad = 0
  for (i = 1; i <= n; i++) {
    nm = order[i]
    tt = taints[nm]; sub(/;+$/, "", tt)
    why = ""
    if (unsched[nm] == "true") why = why "已 cordon（手动禁止调度）; "
    if (ready[nm] != "True") why = why "NotReady（节点异常）; "
    if (tt ~ /NoSchedule|NoExecute/) why = why "污点 " tt "; "
    if (why != "") { printf "  - %s: %s\n", nm, why; bad++ }
  }
  if (bad == 0 && n > 0) printf "  无：全部节点可调度（无 cordon / NotReady / 阻塞性污点）\n"
  cp_tainted = 0
  for (i = 1; i <= n; i++) if (cp[order[i]] == "true" && taints[order[i]] ~ /NoSchedule/) cp_tainted = 1
  if (n > 0) {
    if (cp_tainted) printf "  control-plane: 打了 NoSchedule 污点 → 业务 Pod 默认上不去（需 toleration）\n"
    else printf "  control-plane: 未打阻塞污点 → 业务 Pod 可以调度上去（小集群常见）\n"
  }

  printf "\n【3】命名空间 Requests Top（按内存排序）\n"
  m = 0
  for (k in nsrcpu) { m++; nlist[m] = k; nsmemkB[k] = nsrmem[k] }
  for (i = 2; i <= m; i++) {
    v = nlist[i]; j = i - 1
    while (j >= 1 && nsmemkB[nlist[j]] < nsmemkB[v]) { nlist[j+1] = nlist[j]; j-- }
    nlist[j+1] = v
  }
  printf "  %-22s %5s %9s %9s %9s\n", "namespace", "pods", "reqCPU", "reqMEM", "limMEM"
  lim = (m < 6) ? m : 6
  for (i = 1; i <= lim; i++) {
    k = nlist[i]
    printf "  %-22s %5d %8.1fC %8.1fG %8.1fG\n", k, npod_ns[k], nsrcpu[k]/1000, nsrmem[k]/1024, nslmem[k]/1024
  }

  printf "\n【4】结论（基准：一套 = 8 核 / 16 GiB / 磁盘可用 100G）\n"
  if (n == 0) {
    printf "  节点数据不可得，无法估算“还能放几套”。\n"
    printf "  只能看到：当前命名空间申请量如上，请让管理员补 nodes 只读权限后重跑。\n"
    exit
  }
  c_cpu = int(tot_cpu_rem / 8000)
  c_mem = int(tot_mem_rem / 16384)
  c_req = (c_cpu < c_mem) ? c_cpu : c_mem
  printf "  可调度节点合计剩余: %.1fC / %.1f GiB\n", tot_cpu_rem/1000, tot_mem_rem/1024
  printf "  按 Requests 估算: 约 %d 套（CPU 容 %d 套，内存容 %d 套）\n", c_req, c_cpu, c_mem
  if (act_nodes > 0) {
    a_cpu = int(tot_cpu_act / 8000); a_mem = int(tot_mem_act / 16384)
    act_copies = (a_cpu < a_mem) ? a_cpu : a_mem
    printf "  按实际用量估算: 约 %d 套（CPU 容 %d 套，内存容 %d 套；覆盖 %d 个节点，瞬时值）\n", act_copies, a_cpu, a_mem, act_nodes
  } else {
    printf "  按实际用量估算: 不可用（未装 metrics-server 或无权读取）\n"
  }
  printf "  采用口径: 以 Requests 为准（调度器按它决定能否排进去）；实际用量只说明“现在闲不闲”。\n"
  if (c_req == 0) {
    if (tot_cpu_rem < 8000) printf "  卡点: CPU 剩 %.1f 核 < 8 核；即便内存够，也排不进完整一套。\n", tot_cpu_rem/1000
    else printf "  卡点: 内存剩 %.1f GiB < 16 GiB；需扩容或拆组件（先去掉 Milvus）。\n", tot_mem_rem/1024
  }
  printf "  磁盘: 节点磁盘容量 kubectl 读不到，需在各节点跑 server_check.sh 看 /var/lib/docker 可用空间。\n"
}
'

if [ "$NODES_OK" = 0 ]; then
  echo ""
  echo "【提示】当前账号读不到 nodes（RBAC 限制：需要 nodes 的 get/list）。上面只有 Pod 视角，无法算集群余量。"
fi
echo ""
echo "备注: 统计常规容器的 requests/limits，已排除 Succeeded/Failed 的 Pod；DaemonSet 的 Pod 按实际占用计入。"
