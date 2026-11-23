#!/usr/bin/env bash
# 清理冒烟写入（网关会覆盖 X-Tenant-Id，写操作实际落到租户 1）
set -u
PASS=$(cat /home/dev/secrets/mysql_pwd)
mysql -udev -p"$PASS" -D aitims -e "
DELETE FROM ai_prompt_version WHERE tenant_id=1 AND version='chat-smoke-v1';
DELETE FROM ai_tenant_key WHERE tenant_id=1 AND model='glm-5.3-flash';
UPDATE ai_tenant_quota SET quota_cny=18.0 WHERE tenant_id=1;
SELECT 'prompt' t, COUNT(*) c FROM ai_prompt_version WHERE tenant_id=1
UNION ALL SELECT 'keys', COUNT(*) FROM ai_tenant_key WHERE tenant_id=1
UNION ALL SELECT 'quota', quota_cny FROM ai_tenant_quota WHERE tenant_id=1;
"

BASE=http://127.0.0.1:8080
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin@123"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")
CID=$(curl -s -H "Authorization: $TOKEN" "$BASE/api/ai/observe/calls?page=1&size=1" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['items'][0]['id'])")
echo "== detail of call $CID =="
curl -s -H "Authorization: $TOKEN" "$BASE/api/ai/observe/calls/$CID" | head -c 900; echo
echo "== prompts after cleanup =="
curl -s -H "Authorization: $TOKEN" "$BASE/api/ai/observe/prompts?scene=CHAT" | head -c 300; echo
echo "== keys after cleanup =="
curl -s -H "Authorization: $TOKEN" "$BASE/api/ai/admin/keys" | head -c 400; echo
