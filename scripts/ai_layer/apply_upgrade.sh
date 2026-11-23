#!/usr/bin/env bash
set -e
PASS=$(cat /home/dev/secrets/mysql_pwd)
mysql -udev -p"$PASS" -D aitims < /tmp/upgrade_ai_observe.sql
echo "== columns =="
mysql -udev -p"$PASS" -D aitims -e "SHOW COLUMNS FROM ai_call_log LIKE 'guard_blocked'; SHOW COLUMNS FROM ai_call_log LIKE 'prompt_version'; SHOW COLUMNS FROM ai_call_log LIKE 'trace_id';"
echo "== tables =="
mysql -udev -p"$PASS" -D aitims -e "SHOW TABLES LIKE 'ai_%';"
