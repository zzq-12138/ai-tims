#!/usr/bin/env bash
# AI-TIMS 一键启动（VM 专用）：6 个后端 + 前端，幂等（先杀旧进程再起）
# 用法：/home/dev/start_all.sh            全部拉起
#       /home/dev/start_all.sh --no-front 只起后端
# 仓库副本位于 ai-tims/scripts/start_all.sh，两处内容保持一致。
set -u

BASE=/home/dev/ai-tims/ai-tims-parent
LOGD=/home/dev/logs
mkdir -p "$LOGD" /home/dev/data/uploads

# 1) 密钥注入（与 restart_kb.sh 同口径，600 权限，不进 git）
export MYSQL_PASSWORD=$(cat /home/dev/secrets/mysql_pwd)
export RABBIT_PASSWORD=$(cat /home/dev/secrets/rabbit_pwd)
export ZHIPU_API_KEY=$(cat /home/dev/secrets/zhipu_api_key)
export LLM_API_KEY_FILE=/home/dev/secrets/zhipu_api_key
export SMTP_AUTH=$(cat /home/dev/secrets/smtp_auth)

# 服务清单：jar 相对路径|端口|日志
SERVICES="
ticket-gateway/target/ticket-gateway-1.0.0-SNAPSHOT.jar|8080|ticket-gateway-m6.log
ticket-system/target/ticket-system-1.0.0-SNAPSHOT.jar|8101|ticket-system-m6.log
ticket-order/target/ticket-order-1.0.0-SNAPSHOT.jar|8102|ticket-order-m6.log
ticket-knowledge/target/ticket-knowledge-1.0.0-SNAPSHOT.jar|8103|ticket-knowledge-m6.log
ticket-ai/target/ticket-ai-1.0.0-SNAPSHOT.jar|8104|ticket-ai-m6.log
ticket-push/target/ticket-push-1.0.0-SNAPSHOT.jar|8105|ticket-push-m6.log
"

# 2) 先等底座（Nacos/MySQL）就绪——重启后容器端口可能还在起
wait_port() {
  local port="$1" name="$2" tries="${3:-30}"
  for _ in $(seq 1 "$tries"); do
    if ss -lnt 2>/dev/null | grep -q ":$port "; then
      echo "[ok] $name :$port 已监听"
      return 0
    fi
    sleep 2
  done
  echo "[warn] $name :$port 未监听，继续启动（失败时看对应日志）"
}
wait_port 8848 Nacos 30
wait_port 3306 MySQL 15

# 3) 幂等：杀旧进程（先 TERM，15s 不退则 KILL）
kill_jar() {
  local pat="$1" p
  pgrep -f "$pat" >/dev/null 2>&1 || return 0
  for p in $(pgrep -f "$pat"); do kill "$p" 2>/dev/null || true; done
  for _ in $(seq 1 15); do
    pgrep -f "$pat" >/dev/null 2>&1 || return 0
    sleep 1
  done
  for p in $(pgrep -f "$pat"); do kill -9 "$p" 2>/dev/null || true; done
}
while IFS='|' read -r jar port log; do
  [ -z "$jar" ] && continue
  kill_jar "$(basename "$jar")"
done <<< "$SERVICES"

# 4) 起后端（cd 到 parent，nohup + setsid，日志追加）
while IFS='|' read -r jar port log; do
  [ -z "$jar" ] && continue
  echo "=== start $(date -u +%FT%TZ) $jar ===" >> "$LOGD/$log"
  ( cd "$BASE" && setsid nohup java -jar "$jar" >> "$LOGD/$log" 2>&1 < /dev/null & )
  echo "[start] $(basename "$jar") → :$port  日志 $LOGD/$log"
done <<< "$SERVICES"

# 5) 等六个端口全部监听（最多 120s）
missing=""
for _ in $(seq 1 60); do
  missing=""
  while IFS='|' read -r jar port log; do
    [ -z "$jar" ] && continue
    ss -lnt 2>/dev/null | grep -q ":$port " || missing="$missing $port"
  done <<< "$SERVICES"
  [ -z "$missing" ] && break
  sleep 2
done
[ -n "$missing" ] && echo "[warn] 仍未监听:$missing（看 /home/dev/logs 对应日志）"

# 6) 健康检查
for port in 8080 8101 8102 8103 8104 8105; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 3 "http://127.0.0.1:$port/actuator/health" 2>/dev/null || true)
  echo "[health] :$port → ${code:-000}"
done

# 7) 前端（vite 5173）
if [ "${1:-}" != "--no-front" ]; then
  /home/dev/start_front.sh
  for _ in $(seq 1 20); do
    ss -lnt 2>/dev/null | grep -q ':5173 ' && break
    sleep 1
  done
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:5173 2>/dev/null || true)
  echo "[health] :5173 → ${code:-000}"
fi

echo "=== 当前监听 ==="
ss -lnt 2>/dev/null | grep -E ':(8080|8101|8102|8103|8104|8105|5173) ' || echo "(无)"
