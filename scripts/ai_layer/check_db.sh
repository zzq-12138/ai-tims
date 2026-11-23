#!/usr/bin/env bash
set -e
PASS=$(cat /home/dev/secrets/mysql_pwd)
echo "== ai_call_log columns =="
mysql -udev -p"$PASS" -D aitims -e "SHOW COLUMNS FROM ai_call_log;"
echo "== ai_* tables =="
mysql -udev -p"$PASS" -D aitims -e "SHOW TABLES LIKE 'ai_%';"
