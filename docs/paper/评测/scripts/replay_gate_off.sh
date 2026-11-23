#!/usr/bin/env bash
# 只读重放：核对 2026-11-23 线上检索分数是否相对 11-19 整体下移
# 用法（在公司 master1 上执行）：bash replay_gate_off.sh
# 安全性：只新建独立标签的替身 Deployment，不建 Service；不改 ConfigMap/Secret/业务数据；退出时强删。
# 注意：线上 env 已经通过 envFrom 带了一个 KB_GATE_ENABLED，本脚本在 containers[0].env 追加同名项；
#       K8s 允许同名，后出现的显式 env 覆盖 envFrom，因此替身里门控确实为 false（apply 时的
#       `duplicate name "KB_GATE_ENABLED"` 警告可忽略，不要据此以为门控没关）。
set -uo pipefail
# 检索模式开关：默认 VECTOR（全库 top1 余弦，与离线评测同口径）；
# 需要线上口径时设置 MODE=HYBRID：MODE=HYBRID bash replay_gate_off.sh
MODE="${MODE:-VECTOR}"
case "$MODE" in VECTOR|HYBRID) ;; *) echo "MODE 只能是 VECTOR 或 HYBRID（当前：$MODE）"; exit 1;; esac
NS=ai-tims
SRC=ticket-knowledge
TMP=ticket-knowledge-replay

command -v kubectl >/dev/null || { echo "缺少 kubectl"; exit 1; }
command -v python3 >/dev/null || { echo "缺少 python3，请先安装：sudo yum install -y python3  或  sudo apt-get install -y python3"; exit 1; }

cat > /tmp/replay_render.py <<'PY'
import json, sys
d = json.load(sys.stdin)
for k in ("annotations", "creationTimestamp", "generation", "resourceVersion",
          "uid", "managedFields", "ownerReferences"):
    d["metadata"].pop(k, None)
d.pop("status", None)
d["metadata"]["name"] = "ticket-knowledge-replay"
d["metadata"]["labels"] = {"app": "ticket-knowledge-replay", "purpose": "replay"}
d["spec"]["replicas"] = 1
d["spec"]["selector"] = {"matchLabels": {"app": "ticket-knowledge-replay"}}
d["spec"]["strategy"] = {"type": "Recreate"}
pod = d["spec"]["template"]
pod["metadata"]["labels"] = {"app": "ticket-knowledge-replay"}
pod["metadata"].pop("annotations", None)
for k in ("affinity", "topologySpreadConstraints", "nodeSelector", "tolerations"):
    pod["spec"].pop(k, None)
c = pod["spec"]["containers"][0]
c.pop("livenessProbe", None)
c.setdefault("env", []).append({"name": "KB_GATE_ENABLED", "value": "false"})
json.dump(d, sys.stdout, ensure_ascii=False)
PY

cat > /tmp/replay_parse.py <<'PY'
import json, sys
d = json.load(sys.stdin).get("data") or {}
items = d.get("items") or []
it = items[0] if items else {}
print("\t".join([str(it.get("id", "-")), str(it.get("title", "-")).replace("\t", " "),
                 str(d.get("maxVectorScore")), str(d.get("tier")), str(d.get("fallback"))]))
PY

cleanup() {
  kubectl -n "$NS" delete deploy "$TMP" --force --grace-period=0 --ignore-not-found >/dev/null 2>&1
  for i in $(seq 1 20); do
    n=$(kubectl -n "$NS" get pods -l app="$TMP" --no-headers 2>/dev/null | wc -l)
    [ "$n" -eq 0 ] && break
    sleep 3
  done
  echo "[cleanup] 残留 Pod 数：$(kubectl -n "$NS" get pods -l app="$TMP" --no-headers 2>/dev/null | wc -l)"
}
trap cleanup EXIT INT TERM

echo "[1/5] 清理旧替身"
kubectl -n "$NS" delete deploy "$TMP" --force --grace-period=0 --ignore-not-found >/dev/null 2>&1

echo "[2/5] 以线上 Deployment 为模板生成替身（只读线上对象）"
kubectl -n "$NS" get deploy "$SRC" -o json | python3 /tmp/replay_render.py > /tmp/replay-deploy.json || { echo "模板生成失败"; exit 1; }

echo "[3/5] 创建替身并等待就绪（保留 readinessProbe）"
kubectl apply -f /tmp/replay-deploy.json >/dev/null || { echo "apply 失败"; exit 1; }
kubectl -n "$NS" rollout status deploy/"$TMP" --timeout=300s || { echo "rollout 超时"; exit 1; }
ok=0
for i in $(seq 1 60); do
  code=$(kubectl -n "$NS" exec deploy/"$TMP" -- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8103/actuator/health/readiness 2>/dev/null)
  if [ "$code" = "404" ]; then
    code=$(kubectl -n "$NS" exec deploy/"$TMP" -- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8103/actuator/health 2>/dev/null)
  fi
  [ "$code" = "200" ] && { ok=1; break; }
  sleep 3
done
[ "$ok" = "1" ] || { echo "readiness 未通过（最后 HTTP=$code）"; exit 1; }

ask() {
  kubectl -n "$NS" exec deploy/"$TMP" -- curl -s -G http://127.0.0.1:8103/api/kb/search \
    --data-urlencode "query=$1" --data "mode=$2" --data "topK=5" -H "X-Tenant-Id: 1"
}

echo "[4/5] 逐条重放（mode=$MODE；替身门控关闭）"
# 为什么必须关掉门控：C 档会把 items 清空，拿不到 top1_id / top1_title。
# 注意：maxVectorScore 在 C 档仍会返回（它在分档之前就已计算），所以「关掉门控」是为了拿到 top1 文档，
#      不是为了让分数从 null 变有值。
# 基线说明：0.76701 是回流焊「instruct + 0.70、HYBRID」的 11-19 线上读数，当时问句为
#   全角逗号版「回流焊8温区温度偏低，焊点虚焊」；换成半角空格版会低约 0.015（0.7497 vs 0.7647），
#   所以本脚本刻意用逗号版，避免把标点差异误判为模型漂移。
# 0.6751/0.6748 是回流焊「raw 无前缀」读数，不是蚀刻的基线，故蚀刻一行基线留空。
# 只有 MODE=HYBRID 时基线（0.76701）才可比；MODE=VECTOR 时基线列统一显示为 -。
printf "%-2s|%-30s|%-19s|%-24s|%-7s|%-9s|%-8s|%s\n" "#" "query" "top1_id" "top1_title" "maxVec" "base1119" "delta" "hit"
: > /tmp/replay-out.tsv
i=0
while IFS='|' read -r q exp base; do
  i=$((i+1))
  j=$(ask "$q" "$MODE")
  id=$(printf %s "$j" | python3 /tmp/replay_parse.py | cut -f1)
  ti=$(printf %s "$j" | python3 /tmp/replay_parse.py | cut -f2)
  sc=$(printf %s "$j" | python3 /tmp/replay_parse.py | cut -f3)
  hit="-"; case ";$exp;" in *";$id;"*) hit="Y";; *) hit="N";; esac
  d="-"
  [ "$MODE" != "HYBRID" ] && base="-"
  if [ "$base" != "-" ]; then
    hs=$(ask "$q" HYBRID | python3 /tmp/replay_parse.py | cut -f3)
    d=$(awk -v a="$hs" -v b="$base" 'BEGIN{if(a=="None"||a=="null")print "null";else printf "%+.4f", a-b}')
  fi
  printf "%-2s|%-30s|%-19s|%-24s|%-7s|%-9s|%-8s|%s\n" "$i" "$q" "$id" "$ti" "$sc" "$base" "$d" "$hit"
  printf "%s\t%s\t%s\t%s\n" "$sc" "$base" "$d" "$hit" >> /tmp/replay-out.tsv
done <<'Q'
回流焊8温区温度偏低，焊点虚焊|3100000000000000108|0.76701
蚀刻机过蚀刻怎么处理|2117517479423836162|-
SPI锡膏检测机出现3D光源亮度漂移应该如何排查|2117918536058552322|-
回流焊炉温失控的解决方法|2117522070425055234;2117518330221625345|-
AOI检测机程序调用错误怎么处理|2117518106325483522|-
贴片机出现传送轨道卡板应该如何排查|2117518059655462913|-
蚀刻机废液排放报警的解决方法|2117517694373527554|-
贴合机压力不均怎么处理|2117517026359312385|-
贴合机定位标记识别的解决方法|2117517116998221825|-
贴合机静电吸附不良的解决方法|2117517255108263938|-
贴合机温控异常怎么处理|2117517162896490498|-
蚀刻机蚀刻速率偏差怎么处理|2117517328441475074|-
MES终端报工接口超时怎么处理|2117984477438107650|-
Q

echo
echo "[5/5] 汇总"
awk -F'\t' '
  $2!="-"{n++; s+=$3; if(n==1||$3<mn)mn=$3; if(n==1||$3>mx)mx=$3}
  $1!="None"&&$1!="null"{m++; v+=$1; a[m]=$1}
  $4=="Y"{hit++}
  END{
    printf "有 11-19 基线条数=%d  均值差=%+.4f  最小=%+.4f  最大=%+.4f\n", n, (n?s/n:0), mn, mx
    if(m){for(i=1;i<=m;i++)for(j=i+1;j<=m;j++)if(a[i]>a[j]){t=a[i];a[i]=a[j];a[j]=t}
      printf "本次 VECTOR 得分=%d 条  均值=%.4f  中位=%.4f  （11-19 离线 P 池锚点：均值0.7784 / 中位0.7974）\n", m, v/m, (m%2?a[(m+1)/2]:(a[m/2]+a[m/2+1])/2)}
    printf "top1 命中期望文档=%d/%d\n", hit, m
  }' /tmp/replay-out.tsv

echo
echo "口径：delta 仅对前两条（11-19 线上 HYBRID 基线）计算；其余行无逐条基线，只能与分布锚点比较。"
echo "替�