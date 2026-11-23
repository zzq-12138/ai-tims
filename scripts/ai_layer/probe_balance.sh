#!/usr/bin/env bash
# 核实智谱开放平台是否提供余额/资源包查询接口（只读，不打印 Key）
set -u
KEY=$(cat /home/dev/secrets/zhipu_api_key)
BASE=https://open.bigmodel.cn/api/paas/v4
OUT=/tmp/zhipu_probe_$$.out
for p in balance usage quota finance/balance resource/package; do
  code=$(curl -s -o "$OUT" -w "%{http_code}" -H "Authorization: Bearer $KEY" "$BASE/$p")
  echo "$p -> HTTP $code | $(head -c 160 "$OUT" | tr '\n' ' ')"
done
rm -f "$OUT"
