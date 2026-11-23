#!/usr/bin/env bash
# =============================================================================
# seed_company.sh —— 向公司内网 AI-TIMS 批量灌入维修知识（40 条，内容写死）
#
# ★★★ 本脚本会向【公司环境】写入数据，执行前务必确认 ★★★
#   1) 确认目标库的 kb_knowledge 是空的（或至少确认新增 40 条不会污染已有数据）：
#        SELECT COUNT(*) FROM aitims.kb_knowledge;
#   2) 本脚本只做“新增”，不做去重；重复执行会产生重复知识（标题相同、id 不同）。
#   3) 不调用任何外部大模型，只走本系统自己的 HTTP 接口：创建 -> submit -> publish。
#
# 回滚方式（按知识 id 逐条删除，接口：DELETE /api/kb/knowledge/{id}）：
#   脚本把每条“创建成功”的知识 id 追加到同目录的 seed_company_ids.txt（每次运行会重写该文件）。
#   回滚示例：
#     TOKEN=$(curl -s -X POST "$BASE_URL/api/auth/login" \
#       -H 'Content-Type: application/json' \
#       -d '{"username":"admin","password":"Admin@123"}' | jq -r .data.token)
#     while read -r id; do
#       curl -s -X DELETE "$BASE_URL/api/kb/knowledge/$id" -H "Authorization: $TOKEN"
#       echo
#     done < seed_company_ids.txt
#
# 依赖：curl + （jq 或 python3 二者其一；优先用 jq）
# 用法：
#   bash seed_company.sh
#   BASE_URL=http://10.96.0.18:8080 bash seed_company.sh
#   BASE_URL=http://某网关:8080 ADMIN_USER=admin ADMIN_PASS='Admin@123' bash seed_company.sh
#
# 说明：token 直接放 Authorization 头，不加 "Bearer " 前缀（Sa-Token 的用法）。
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_FILE="${SCRIPT_DIR}/seed_company_data.json"
ID_FILE="${SCRIPT_DIR}/seed_company_ids.txt"

BASE_URL="${BASE_URL:-http://10.96.0.18:8080}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-Admin@123}"

HTTP_CODE=""
RESP_BODY=""
TOKEN=""

die() { echo "[FATAL] $*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "未找到 curl"
[ -f "$DATA_FILE" ] || die "数据文件不存在：${DATA_FILE}"

if command -v jq >/dev/null 2>&1; then
  JSON_TOOL="jq"
elif command -v python3 >/dev/null 2>&1; then
  JSON_TOOL="python3"
else
  die "需要 jq 或 python3 之一来解析 JSON（内网机器常见只有 python3）"
fi

echo "[env] JSON 解析工具=${JSON_TOOL}  BASE_URL=${BASE_URL}"

# ---------------------------------------------------------------------------
# JSON 读取（数据文件）
# ---------------------------------------------------------------------------
json_len() {
  if [ "$JSON_TOOL" = "jq" ]; then
    jq 'length' "$DATA_FILE" 2>/dev/null
  else
    python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1], encoding="utf-8"))))' "$DATA_FILE" 2>/dev/null
  fi
}

json_item_title() { # $1 = 0 基下标
  if [ "$JSON_TOOL" = "jq" ]; then
    jq -r ".[$1].title" "$DATA_FILE"
  else
    python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])]["title"])' "$DATA_FILE" "$1"
  fi
}

# 输出可直接 POST /api/kb/knowledge 的单条 JSON。
# 注意：接口里的 tags 是“JSON 字符串”而不是数组，所以这里用 jq 的 tojson / python 的 json.dumps 再包一层。
json_item_body() { # $1 = 0 基下标
  if [ "$JSON_TOOL" = "jq" ]; then
    jq -c ".[$1] | {title: .title, content: .content, applyDeviceType: .applyDeviceType, tags: (.tags | tojson)}" "$DATA_FILE"
  else
    python3 -c '
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
item = data[int(sys.argv[2])]
print(json.dumps({
    "title": item["title"],
    "content": item["content"],
    "applyDeviceType": item.get("applyDeviceType", ""),
    "tags": json.dumps(item.get("tags", []), ensure_ascii=False),
}, ensure_ascii=False))
' "$DATA_FILE" "$1"
  fi
}

# ---------------------------------------------------------------------------
# JSON 读取（接口响应）
# ---------------------------------------------------------------------------
code_of() { # $1 = 响应体；取 Result.code
  local body="$1"
  if [ "$JSON_TOOL" = "jq" ]; then
    printf '%s' "$body" | jq -r 'if type=="object" then (.code|tostring) else "?" end' 2>/dev/null
  else
    printf '%s' "$body" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get("code", "?") if isinstance(d, dict) else "?")
except Exception:
    print("?")
'
  fi
}

token_of() { # $1 = 登录响应体；取 data.token
  local body="$1"
  if [ "$JSON_TOOL" = "jq" ]; then
    printf '%s' "$body" | jq -r '.data.token // empty' 2>/dev/null
  else
    printf '%s' "$body" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    print(((d.get("data") or {}).get("token") or "") if isinstance(d, dict) else "")
except Exception:
    print("")
'
  fi
}

id_of() { # $1 = 创建响应体；取 data.id（雪花 ID，转成字符串避免精度丢失）
  local body="$1"
  if [ "$JSON_TOOL" = "jq" ]; then
    printf '%s' "$body" | jq -r '.data.id // empty | tostring' 2>/dev/null
  else
    printf '%s' "$body" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    v = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
    print("" if v is None else str(v))
except Exception:
    print("")
'
  fi
}

is_ok() { case "$1" in 0|200) return 0 ;; *) return 1 ;; esac; }

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
post_json() { # $1=路径 $2=body $3=1 带 token / 0 不带
  local url="${BASE_URL}$1" tmp
  tmp="$(mktemp 2>/dev/null || echo "/tmp/seed_kb_resp.$$")"
  if [ "${3:-1}" = "1" ]; then
    HTTP_CODE=$(curl -sS -m 30 -o "$tmp" -w '%{http_code}' -X POST "$url" \
      -H 'Content-Type: application/json' \
      -H "Authorization: ${TOKEN}" \
      --data-binary "$2" 2>/dev/null) || HTTP_CODE="000"
  else
    HTTP_CODE=$(curl -sS -m 30 -o "$tmp" -w '%{http_code}' -X POST "$url" \
      -H 'Content-Type: application/json' \
      --data-binary "$2" 2>/dev/null) || HTTP_CODE="000"
  fi
  [ -n "${HTTP_CODE:-}" ] || HTTP_CODE="000"
  RESP_BODY="$(cat "$tmp" 2>/dev/null)"
  rm -f "$tmp"
}

# ---------------------------------------------------------------------------
# 1) 登录
# ---------------------------------------------------------------------------
echo "[login] POST ${BASE_URL}/api/auth/login  (user=${ADMIN_USER})"
post_json "/api/auth/login" "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}" 0
LOGIN_CODE=$(code_of "$RESP_BODY")
TOKEN=$(token_of "$RESP_BODY")
if ! is_ok "$LOGIN_CODE" || [ -z "$TOKEN" ]; then
  echo "[FATAL] 登录失败 HTTP=${HTTP_CODE} code=${LOGIN_CODE} body=${RESP_BODY}" >&2
  exit 1
fi
echo "[login] 成功 code=${LOGIN_CODE}"

# ---------------------------------------------------------------------------
# 2) 逐条灌数据
# ---------------------------------------------------------------------------
TOTAL=$(json_len)
TOTAL=${TOTAL:-0}
case "$TOTAL" in
  ''|*[!0-9]*) die "无法解析数据文件条数：${DATA_FILE}" ;;
esac
[ "$TOTAL" -gt 0 ] || die "数据文件为空：${DATA_FILE}"

: > "$ID_FILE"

OK=0
FAIL=0
i=0
while [ "$i" -lt "$TOTAL" ]; do
  n=$((i + 1))
  TITLE=$(json_item_title "$i")
  BODY=$(json_item_body "$i")

  CREATE_CODE="?"
  SUBMIT_CODE="-"
  PUBLISH_CODE="-"
  KID=""

  post_json "/api/kb/knowledge" "$BODY" 1
  CREATE_CODE=$(code_of "$RESP_BODY")

  if is_ok "$CREATE_CODE"; then
    KID=$(id_of "$RESP_BODY")
    if [ -n "$KID" ]; then
      echo "$KID" >> "$ID_FILE"
      post_json "/api/kb/knowledge/${KID}/submit" '{}' 1
      SUBMIT_CODE=$(code_of "$RESP_BODY")
      post_json "/api/kb/knowledge/${KID}/publish" '{}' 1
      PUBLISH_CODE=$(code_of "$RESP_BODY")
    else
      SUBMIT_CODE="no-id"
      PUBLISH_CODE="no-id"
    fi
  else
    SUBMIT_CODE="skip"
    PUBLISH_CODE="skip"
  fi

  if is_ok "$CREATE_CODE" && is_ok "$SUBMIT_CODE" && is_ok "$PUBLISH_CODE"; then
    OK=$((OK + 1))
    printf '[%02d/%d] %s | create=%s submit=%s publish=%s\n' \
      "$n" "$TOTAL" "$TITLE" "$CREATE_CODE" "$SUBMIT_CODE" "$PUBLISH_CODE"
  else
    FAIL=$((FAIL + 1))
    printf '[%02d/%d] %s | create=%s submit=%s publish=%s  <== 失败\n' \
      "$n" "$TOTAL" "$TITLE" "$CREATE_CODE" "$SUBMIT_CODE" "$PUBLISH_CODE"
  fi

  i=$((i + 1))
done

# ---------------------------------------------------------------------------
# 3) 汇总
# ---------------------------------------------------------------------------
CREATED=$(wc -l < "$ID_FILE" 2>/dev/null | tr -d ' ')
echo "------------------------------------------------------------"
echo "完成：成功 ${OK} 条，失败 ${FAIL} 条，共 ${TOTAL} 条"
echo "已创建 id 记录：${ID_FILE}（${CREATED} 个）"
echo "回滚（逐条删除）："
echo "  TOKEN=\$(curl -s -X POST '${BASE_URL}/api/auth/login' -H 'Content-Type: application/json' -d '{\"username\":\"admin\",\"password\":\"Admin@123\"}' | jq -r .data.token)"
echo "  while read -r id; do curl -s -X DELETE \"${BASE_URL}/api/kb/knowledge/\$id\" -H \"Authorization: \$TOKEN\"; echo; done < ${ID_FILE}"

[ "$FAIL" -eq 0 ] || exit 2
exit 0
