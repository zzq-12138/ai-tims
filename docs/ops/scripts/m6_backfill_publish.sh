#!/usr/bin/env bash
# =====================================================================
# M6 批量补跑 AI 抽取 —— 事件投递脚本（只发消息，不连库、不改工单）
#
# 做的事：把 payload 文件里的每一行 JSON，投递到 RabbitMQ 的 q.kb.extract。
#   - 走默认交换机（amq.default）直投队列，routing_key = 队列名；
#   - 不经过 tims.ticket.event，避免把 104 条"关单"事件同时推给 ticket-push；
#   - 口令运行时从 K8s Secret 读取，既不写文件也不进 shell 历史；
#   - 每发一条打印一个点，失败立刻停下并打印该行原文与响应。
#
# 用法（在 master1 上执行）：
#   ./m6_backfill_publish.sh --file payloads.jsonl --limit 3        # 试跑前 3 条
#   ./m6_backfill_publish.sh --file payloads.jsonl --offset 3       # 剩余全部
#   ./m6_backfill_publish.sh --file payloads.jsonl --limit 2 --dry-run
#
# 可选环境变量：
#   NS=ai-tims  RABBIT_USER=tims  SECRET_NAME=tims-app-secret
#   SECRET_KEY=RABBIT_PASSWORD  LOCAL_PORT=15672  QUEUE=q.kb.extract
#
# 退出码：0=全部 routed  2=参数/前置失败（含队列不存在）  3=有消息未 routed
# =====================================================================
set -uo pipefail

NS="${NS:-ai-tims}"
RABBIT_USER="${RABBIT_USER:-tims}"
SECRET_NAME="${SECRET_NAME:-tims-app-secret}"
SECRET_KEY="${SECRET_KEY:-RABBIT_PASSWORD}"
LOCAL_PORT="${LOCAL_PORT:-15672}"
QUEUE="${QUEUE:-q.kb.extract}"

PAYLOAD_FILE=""
LIMIT=0
OFFSET=0
DRY_RUN=0

usage() {
  sed -n '2,20p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)   PAYLOAD_FILE="${2:-}"; shift 2 ;;
    --limit)  LIMIT="${2:-0}";       shift 2 ;;
    --offset) OFFSET="${2:-0}";      shift 2 ;;
    --dry-run) DRY_RUN=1;            shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 2 ;;
  esac
done

die() { echo "[ERROR] $*" >&2; exit 2; }

[[ -n "$PAYLOAD_FILE" ]] || die "必须用 --file 指定 payload 文件"
[[ -r "$PAYLOAD_FILE" ]] || die "payload 文件不可读: $PAYLOAD_FILE"
[[ "$LIMIT"  =~ ^[0-9]+$ ]] || die "--limit 必须是数字"
[[ "$OFFSET" =~ ^[0-9]+$ ]] || die "--offset 必须是数字"

# 取本次要发送的行（跳过空行，先 offset 再 limit；limit=0 表示不限制）
mapfile -t LINES < <(awk -v off="$OFFSET" -v lim="$LIMIT" '
  NF {
    seen++
    if (seen <= off) next
    if (lim > 0 && printed >= lim) exit
    print
    printed++
  }' "$PAYLOAD_FILE")

TOTAL_LINES=$(awk 'NF{n++} END{print n+0}' "$PAYLOAD_FILE")
N=${#LINES[@]}

echo "== 待发送清单 =="
echo "  文件        : $PAYLOAD_FILE"
echo "  文件有效行  : $TOTAL_LINES"
echo "  offset/limit: $OFFSET / $LIMIT"
echo "  本次发送    : $N 条"
[[ "$N" -gt 0 ]] || die "按 offset/limit 选出来 0 条，检查参数"

# 清洗一行：去 BOM/CR/首尾空白；若是 CSV 导出（整行被双引号包裹），去掉包裹并还原 "" -> "
clean_line() {
  local p="$1"
  p="${p%$'\r'}"
  p="${p#$'\xEF\xBB\xBF'}"
  p="${p#"${p%%[![:space:]]*}"}"
  p="${p%"${p##*[![:space:]]}"}"
  if [[ ${#p} -ge 2 && "${p:0:1}" == '"' && "${p: -1}" == '"' ]]; then
    p="${p:1:${#p}-2}"
    p="${p//\"\"/\"}"
  fi
  printf '%s' "$p"
}

# 把 JSON 文本转成可以放进 JSON 字符串的转义形式
json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\t'/\\t}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  printf '%s' "$s"
}

if [[ "$DRY_RUN" == "1" ]]; then
  echo
  echo "== dry-run：仅预览，不会连接 RabbitMQ =="
  i=0
  for line in "${LINES[@]}"; do
    i=$((i + 1))
    p=$(clean_line "$line")
    printf '[%3d] %s\n' "$i" "$p"
  done
  echo
  echo "dry-run 结束，共 $N 条。去掉 --dry-run 才会真正投递。"
  exit 0
fi

command -v kubectl >/dev/null 2>&1 || die "缺少 kubectl"
command -v curl    >/dev/null 2>&1 || die "缺少 curl"

CTX=$(kubectl config current-context 2>/dev/null || true)
echo "  kubectl ctx : ${CTX:-<unknown>}"

POD=$(kubectl -n "$NS" get pod -l app=tims-rabbitmq \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
[[ -n "$POD" ]] || die "在 namespace $NS 找不到 app=tims-rabbitmq 的 Pod"
echo "  rabbitmq Pod: $POD"

RABBIT_PASS=$(kubectl -n "$NS" get secret "$SECRET_NAME" \
                -o jsonpath="{.data.${SECRET_KEY}}" 2>/dev/null | base64 -d 2>/dev/null || true)
[[ -n "$RABBIT_PASS" ]] || die "无法从 secret/$SECRET_NAME 的 $SECRET_KEY 读到口令"

# 端口被占时直接退出，避免 port-forward 静默失败
if (exec 3<>"/dev/tcp/127.0.0.1/${LOCAL_PORT}") 2>/dev/null; then
  die "本机 ${LOCAL_PORT} 已被占用，请用 LOCAL_PORT=xxxx 换一个端口"
fi

PF_LOG="${TMPDIR:-/tmp}/m6_backfill_pf_$$.log"
kubectl -n "$NS" port-forward "pod/${POD}" "${LOCAL_PORT}:15672" >"$PF_LOG" 2>&1 &
PF_PID=$!
cleanup() { kill "$PF_PID" 2>/dev/null; wait "$PF_PID" 2>/dev/null; }
trap cleanup EXIT INT TERM

BASE_URL="http://127.0.0.1:${LOCAL_PORT}"
AUTH="${RABBIT_USER}:${RABBIT_PASS}"

READY=0
for _ in $(seq 1 30); do
  if curl -fsS -m 3 -u "$AUTH" "${BASE_URL}/api/overview" >/dev/null 2>&1; then
    READY=1; break
  fi
  sleep 1
done
if [[ "$READY" != "1" ]]; then
  echo "port-forward 日志："
  sed -n '1,20p' "$PF_LOG" 2>/dev/null
  die "管理 API 未就绪（检查 ${LOCAL_PORT} 端口、Pod 状态、口令是否正确）"
fi
echo "  管理 API    : ${BASE_URL}  已连通"

QFILTER='?columns=name,state,messages_ready,messages_unacknowledged,consumers'
QINFO=$(curl -sS -m 10 -u "$AUTH" "${BASE_URL}/api/queues/%2F/${QUEUE}${QFILTER}")
if [[ "$QINFO" != *'"name"'* ]]; then
  echo "队列查询返回：$QINFO"
  die "队列 ${QUEUE} 不存在（或当前账号无该 vhost 权限）"
fi
echo "  队列状态(前): $QINFO"
DLQ_INFO=$(curl -sS -m 10 -u "$AUTH" "${BASE_URL}/api/queues/%2F/${QUEUE}.dead${QFILTER}" || true)
echo "  死信队列(前): ${DLQ_INFO:-<查询失败>}"

echo
echo "== 开始投递：$N 条 -> ${QUEUE} =="
OK=0
FAIL=0
IDX=0
for line in "${LINES[@]}"; do
  IDX=$((IDX + 1))
  PAYLOAD=$(clean_line "$line")
  if [[ "${PAYLOAD:0:1}" != "{" ]]; then
    echo
    echo "[FAIL] 第 $IDX 条不是以 { 开头的 JSON，先修正文件："
    printf '       %s\n' "$PAYLOAD"
    FAIL=$((FAIL + 1))
    break
  fi
  ESC=$(json_escape "$PAYLOAD")
  BODY="{\"properties\":{\"content_type\":\"application/json\",\"delivery_mode\":2},\"routing_key\":\"${QUEUE}\",\"payload\":\"${ESC}\",\"payload_encoding\":\"string\"}"
  RESP=$(curl -sS -m 15 -u "$AUTH" -H 'content-type: application/json' \
           -X POST "${BASE_URL}/api/exchanges/%2F/amq.default/publish" -d "$BODY" 2>&1 || true)
  if [[ "$RESP" == *'"routed":true'* ]]; then
    OK=$((OK + 1))
    printf '.'
  else
    printf '\n'
    echo "[FAIL] 第 $IDX 条未路由成功"
    echo "  payload: $PAYLOAD"
    echo "  响应   : $RESP"
    FAIL=$((FAIL + 1))
    break
  fi
done
printf '\n'

echo
echo "== 投递结束 =="
echo "  成功 routed: $OK"
echo "  失败       : $FAIL"
sleep 1
echo "  队列状态(后): $(curl -sS -m 10 -u "$AUTH" "${BASE_URL}/api/queues/%2F/${QUEUE}${QFILTER}" || true)"
echo "  死信队列(后): $(curl -sS -m 10 -u "$AUTH" "${BASE_URL}/api/queues/%2F/${QUEUE}.dead${QFILTER}" || true)"
echo
echo "注意：routed=true 只代表消息进了队列，不代表抽取成功。"
echo "      请按操作手册第六章（试跑核对）/ 第八章（全量核对）用 SQL 查 ai_extracted.status。"

if [[ "$FAIL" -gt 0 ]]; then
  exit 3
fi
exit 0
