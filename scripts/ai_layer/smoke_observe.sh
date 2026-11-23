#!/usr/bin/env bash
# 可观测性 + 管理员 Key 接口冒烟（用租户 999 做写操作，不影响租户 1）
set -u
BASE=http://127.0.0.1:8080
TID=999

TOKEN=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin@123"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")
echo "token length: ${#TOKEN}"
H=(-H "Authorization: $TOKEN" -H "X-Tenant-Id: $TID" -H 'Content-Type: application/json')

echo "== 1) overview (tenant 1 全量) =="
curl -s -H "Authorization: $TOKEN" -H 'X-Tenant-Id: 1' \
  "$BASE/api/ai/observe/overview?from=2026-11-01&to=2026-11-07" | head -c 800; echo

echo "== 2) calls page =="
curl -s -H "Authorization: $TOKEN" -H 'X-Tenant-Id: 1' \
  "$BASE/api/ai/observe/calls?page=1&size=3" | head -c 600; echo

echo "== 3) prompt versions (CHAT) =="
curl -s -H "Authorization: $TOKEN" -H 'X-Tenant-Id: 1' \
  "$BASE/api/ai/observe/prompts?scene=CHAT" | head -c 500; echo

echo "== 4) archive prompt for tenant 999 =="
curl -s "${H[@]}" -X POST "$BASE/api/ai/observe/prompts" \
  -d '{"scene":"CHAT","version":"chat-smoke-v1","content":"smoke prompt for observability verification"}' | head -c 400; echo

echo "== 5) save tenant key (tenant 999) =="
curl -s "${H[@]}" -X POST "$BASE/api/ai/admin/keys" \
  -d '{"provider":"zhipu","model":"glm-5.3-flash","apiKey":"smoke-key-1234567890abcd"}' | head -c 400; echo

echo "== 6) list keys (masked) =="
curl -s "${H[@]}" "$BASE/api/ai/admin/keys" | head -c 600; echo

KEYID=$(curl -s "${H[@]}" "$BASE/api/ai/admin/keys" \
  | python3 -c "import sys,json;d=json.load(sys.stdin)['data']['keys'];print(d[0]['id'] if d else '')")
echo "== 7) reveal key id=$KEYID (writes VIEW audit) =="
curl -s "${H[@]}" "$BASE/api/ai/admin/keys/$KEYID/reveal" | head -c 400; echo

echo "== 8) set quota 100 (tenant 999) =="
curl -s "${H[@]}" -X PUT "$BASE/api/ai/admin/keys/quota" -d '{"quotaCny":100}' | head -c 300; echo

echo "== 9) balance (tenant 999, local estimate) =="
curl -s "${H[@]}" "$BASE/api/ai/admin/keys/balance" | head -c 700; echo

echo "== 10) audits =="
curl -s "${H[@]}" "$BASE/api/ai/admin/keys/audits?limit=10" | head -c 700; echo

echo "== 11) cleanup tenant 999 key =="
KEYID=$(curl -s "${H[@]}" "$BASE/api/ai/admin/keys" \
  | python3 -c "import sys,json;d=json.load(sys.stdin)['data']['keys'];print(d[0]['id'] if d else '')")
if [ -n "$KEYID" ]; then
  curl -s "${H[@]}" -X DELETE "$BASE/api/ai/admin/keys/$KEYID" | head -c 300; echo
fi
