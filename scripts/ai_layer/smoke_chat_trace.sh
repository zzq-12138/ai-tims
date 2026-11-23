#!/usr/bin/env bash
# 触发一次真实同步问答，验证 prompt 版本 / traceId / 观测聚合
set -u
echo "== chat =="
curl -s -m 120 -X POST http://127.0.0.1:8104/api/ai/chat \
  -H 'Content-Type: application/json' -H 'X-Tenant-Id: 1' \
  -d '{"question":"打印机无法开机，先检查什么？"}' | head -c 500; echo

sleep 2
PASS=$(cat /home/dev/secrets/mysql_pwd)
echo "== last calls =="
mysql -udev -p"$PASS" -D aitims -N -e \
  "select id, scene, model, prompt_version, trace_id, status, total_tokens, latency_ms from ai_call_log order by id desc limit 5;" 2>/dev/null

CID=$(mysql -udev -p"$PASS" -D aitims -N -e \
  "select id from ai_call_log where scene like 'CHAT%' order by id desc limit 1;" 2>/dev/null)
echo "== detail $CID =="
BASE=http://127.0.0.1:8080
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin@123"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")
curl -s -H "Authorization: $TOKEN" "$BASE/api/ai/observe/calls/$CID" | python3 -m json.tool | head -60
