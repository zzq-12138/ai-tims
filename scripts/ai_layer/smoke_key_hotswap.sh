#!/usr/bin/env bash
# 验证租户 Key 热更新：写入无效 Key 后立即生效（无需重启），删除后回落默认 Key
set -u
BASE=http://127.0.0.1:8080
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin@123"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")
H=(-H "Authorization: $TOKEN" -H 'Content-Type: application/json')

echo "== 1) save invalid tenant key =="
curl -s "${H[@]}" -X POST "$BASE/api/ai/admin/keys" \
  -d '{"provider":"zhipu","model":"glm-5.3-flash","apiKey":"sk-invalid-smoke-0000"}' | head -c 300; echo

echo "== 2) call chat immediately (expect 401/error, proves hot update) =="
curl -s -m 30 -X POST http://127.0.0.1:8104/api/ai/chat \
  -H 'Content-Type: application/json' -H 'X-Tenant-Id: 1' \
  -d '{"question":"打印机无法开机"}' | head -c 400; echo

echo "== 3) delete tenant key =="
KID=$(curl -s "${H[@]}" "$BASE/api/ai/admin/keys" \
  | python3 -c "import sys,json;d=json.load(sys.stdin)['data']['keys'];print(d[0]['id'] if d else '')")
curl -s "${H[@]}" -X DELETE "$BASE/api/ai/admin/keys/$KID" | head -c 200; echo

echo "== 4) call chat again (expect success via default key) =="
curl -s -m 120 -X POST http://127.0.0.1:8104/api/ai/chat \
  -H 'Content-Type: application/json' -H 'X-Tenant-Id: 1' \
  -d '{"question":"打印机无法开机，第一步做什么？"}' | head -c 300; echo
