#!/usr/bin/env bash
# TIMS 服务器选型体检（只读）
# 不安装任何软件、不修改系统配置、不删除文件；缺少 docker/kubectl/systemctl 时自动跳过。
# 用法: bash server_check.sh

export LC_ALL=C
HOST=$(hostname 2>/dev/null || cat /proc/sys/kernel/hostname 2>/dev/null || echo unknown)
NOW=$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo unknown)

ge() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a+0>=b+0)}'; }
gib() { awk -v k="$1" 'BEGIN{printf "%.1f", k/1048576}'; }
pct() { awk -v a="$1" -v b="$2" 'BEGIN{if(b+0==0){print 0}else{printf "%.0f", a*100/b}}'; }
# 给可能卡住的只读命令加超时（没有 timeout 命令时不加）
TO=""
command -v timeout >/dev/null 2>&1 && TO="timeout 5"

echo "== TIMS 服务器选型体检 v1.0（只读）=="
echo "host: $HOST   time: $NOW"
echo ""

# ---------- 1. CPU ----------
CPU_CORES=$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo 0)
CPU_MODEL=$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo 2>/dev/null)
[ -z "$CPU_MODEL" ] && CPU_MODEL=$(lscpu 2>/dev/null | awk -F: '/Model name/{gsub(/^ +/,"",$2); print $2; exit}')
[ -z "$CPU_MODEL" ] && CPU_MODEL="未知"
CPU_MODEL=$(echo "$CPU_MODEL" | cut -c1-58)
if [ "$CPU_CORES" -ge 8 ] 2>/dev/null; then CPU_LEVEL=推荐; CPU_TXT="够（≥8 核）"
elif [ "$CPU_CORES" -ge 4 ] 2>/dev/null; then CPU_LEVEL=勉强; CPU_TXT="勉强（4–8 核）"
else CPU_LEVEL=不建议; CPU_TXT="不够（<4 核）"; fi
echo "[1/8] CPU"
echo "  核数: $CPU_CORES 核    型号: $CPU_MODEL"
echo "  -> $CPU_CORES 核 → $CPU_TXT；基准: ≥8 推荐 / 4–8 勉强 / <4 不建议"

# ---------- 2. 内存 ----------
MEM_TOTAL_KB=$(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null)
MEM_AVAIL_KB=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null)
if [ -z "$MEM_TOTAL_KB" ]; then
  set -- $(free -k 2>/dev/null | awk '/^Mem:/{print $2, $7, $4}')
  MEM_TOTAL_KB=${1:-0}; MEM_AVAIL_KB=${2:-0}
  # 老版本 free 没有 available 列（第 7 列），退化为 free 列
  [ -z "$MEM_AVAIL_KB" ] && MEM_AVAIL_KB=${3:-0}
fi
[ -z "$MEM_AVAIL_KB" ] && MEM_AVAIL_KB=$MEM_TOTAL_KB
MEM_TOTAL=$(gib "${MEM_TOTAL_KB:-0}")
MEM_AVAIL=$(gib "${MEM_AVAIL_KB:-0}")
MEM_PCT=$(pct "${MEM_AVAIL_KB:-0}" "${MEM_TOTAL_KB:-0}")
if ge "$MEM_TOTAL" 16; then MEM_LEVEL=推荐; MEM_TXT="够（≥16G）"
elif ge "$MEM_TOTAL" 8; then MEM_LEVEL=勉强; MEM_TXT="勉强（8–16G）"
else MEM_LEVEL=不建议; MEM_TXT="不够（<8G）"; fi
echo "[2/8] 内存"
echo "  总量: ${MEM_TOTAL}G    当前可用: ${MEM_AVAIL}G（${MEM_PCT}%）"
echo "  -> ${MEM_TOTAL}G 总量 → $MEM_TXT；基准: ≥16 推荐 / 8–16 勉强 / <8 不建议"
echo "     可用 ${MEM_AVAIL}G，若低于总量一半说明已有负载占用，实际余量要打折"

# ---------- 3. 磁盘 ----------
read -r R_TOTAL R_USED R_AVAIL R_MOUNT <<EOF
$(df -Pk / 2>/dev/null | awk 'NR==2{printf "%.1f %.1f %.1f %s", $2/1048576, $3/1048576, $4/1048576, $6}')
EOF
DOCKER_DIR=/var/lib/docker
# docker 数据目录可能被改到别的盘（如 /data/docker），优先用 daemon 自报的路径
if command -v docker >/dev/null 2>&1; then
  DROOT=$($TO docker info --format '{{.DockerRootDir}}' 2>/dev/null)
  [ -n "$DROOT" ] && [ -d "$DROOT" ] && DOCKER_DIR=$DROOT
fi
[ -d "$DOCKER_DIR" ] || DOCKER_DIR=/var/lib
read -r D_TOTAL D_USED D_AVAIL D_MOUNT <<EOF
$(df -Pk "$DOCKER_DIR" 2>/dev/null | awk 'NR==2{printf "%.1f %.1f %.1f %s", $2/1048576, $3/1048576, $4/1048576, $6}')
EOF
[ -z "$D_AVAIL" ] && D_TOTAL=$R_TOTAL && D_USED=$R_USED && D_AVAIL=$R_AVAIL && D_MOUNT=$R_MOUNT
if ge "$D_AVAIL" 100; then DISK_LEVEL=推荐; DISK_TXT="够（≥100G）"
elif ge "$D_AVAIL" 50; then DISK_LEVEL=勉强; DISK_TXT="勉强（50–100G）"
else DISK_LEVEL=不建议; DISK_TXT="不够（<50G）"; fi
echo "[3/8] 磁盘"
echo "  /               总 ${R_TOTAL}G  已用 ${R_USED}G  可用 ${R_AVAIL}G  (${R_MOUNT})"
if [ "$D_MOUNT" = "$R_MOUNT" ]; then
  echo "  /var/lib/docker 与 / 同一分区（容器镜像也占这里）"
else
  echo "  /var/lib/docker 总 ${D_TOTAL}G  已用 ${D_USED}G  可用 ${D_AVAIL}G  (${D_MOUNT})"
fi
echo "  -> 可用 ${D_AVAIL}G → $DISK_TXT；基准: ≥100 推荐 / 50–100 勉强 / <50 不建议"

# ---------- 4. 负载 ----------
LOAD=$(awk '{print $1", "$2", "$3}' /proc/loadavg 2>/dev/null)
[ -z "$LOAD" ] && LOAD=$(uptime 2>/dev/null | sed 's/.*load average[s]*: *//')
LOAD1=$(echo "$LOAD" | awk -F, '{print $1}' | tr -d ' ')
if [ -n "$LOAD1" ] && [ "$CPU_CORES" -gt 0 ] 2>/dev/null; then
  if ge "$(awk -v l="$LOAD1" -v c="$CPU_CORES" 'BEGIN{print l/c}')" 0.7; then
    LOAD_TXT="偏忙（1 分钟负载已超过核数的 70%）"
  else LOAD_TXT="空闲"; fi
else LOAD_TXT="未知"; fi
echo "[4/8] 负载"
echo "  load(1/5/15 分钟): $LOAD   （$CPU_CORES 核）"
echo "  -> $LOAD_TXT；实现建议: 1 分钟负载持续低于核数 70% 视为空闲"

# ---------- 5. 内存 Top5 ----------
echo "[5/8] 占内存最多的前 5 个进程"
TOP5=$(ps -eo rss=,pid=,comm= --sort=-rss 2>/dev/null | head -5)
[ -z "$TOP5" ] && TOP5=$(ps -eo rss,pid,comm 2>/dev/null | sort -rn | head -5)
[ -z "$TOP5" ] && TOP5=$(ps aux 2>/dev/null | sort -k4 -rn | awk 'NR<=5{print $6, $2, $11}')
if [ -z "$TOP5" ]; then
  echo "  （当前环境不支持 ps 读取，跳过）"
else
  echo "$TOP5" | awk '{printf "  pid=%-7s RSS=%6.0fMB  %s\n", $2, $1/1024, $3}'
fi

# ---------- 6. 容器与编排 ----------
echo "[6/8] 容器与编排"
DOCKER_STATE="未安装（跳过）"
CONTAINER_LINE="无法确认（无 docker 或当前用户无权限）"
if command -v docker >/dev/null 2>&1; then
  DOCKER_STATE=$(docker --version 2>/dev/null | sed 's/,.*//')
  if $TO docker ps -q >/dev/null 2>&1; then
    DCNT=$($TO docker ps -q 2>/dev/null | wc -l | tr -d ' ')
    DNAMES=$($TO docker ps --format '{{.Names}}' 2>/dev/null | head -5 | tr '\n' ',' | sed 's/,$//')
    [ "${DCNT:-0}" -gt 5 ] 2>/dev/null && DNAMES="${DNAMES} 等"
    CONTAINER_LINE="运行中容器 ${DCNT} 个${DNAMES:+：$DNAMES}"
  else
    CONTAINER_LINE="docker 已装但当前用户无权读取（需 root 或加入 docker 组）"
  fi
fi
K3S_STATE="未发现"
if command -v k3s >/dev/null 2>&1; then
  K3S_STATE=$(k3s --version 2>/dev/null | head -1)
  command -v systemctl >/dev/null 2>&1 && K3S_STATE="$K3S_STATE；服务状态: $(systemctl is-active k3s 2>/dev/null)"
fi
K8S_STATE="未发现"
if command -v kubectl >/dev/null 2>&1; then
  KNODES=$(kubectl --request-timeout=5s get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
  K8S_STATE="kubectl 已装${KNODES:+，可读节点 ${KNODES} 个}"
elif [ -d /etc/kubernetes/manifests ] || [ -d /var/lib/kubelet ]; then
  K8S_STATE="发现 k8s 目录痕迹（kubelet/manifests），但无 kubectl"
fi
echo "  docker : $DOCKER_STATE"
echo "  k3s    : $K3S_STATE"
echo "  k8s    : $K8S_STATE"
echo "  容器   : $CONTAINER_LINE"

# ---------- 7. 权限 ----------
UID_NOW=$(id -u 2>/dev/null || echo 9999)
[ "$UID_NOW" = "0" ] && ROOT_STATE="是" || ROOT_STATE="否"
if command -v sudo >/dev/null 2>&1; then
  if sudo -n true >/dev/null 2>&1; then SUDO_STATE="可用（免密）"; else SUDO_STATE="需密码或不可用"; fi
else SUDO_STATE="未安装"; fi
echo "[7/8] 当前身份"
echo "  root: $ROOT_STATE    sudo: $SUDO_STATE"

# ---------- 8. 系统 ----------
OS_NAME="未知"
if [ -r /etc/os-release ]; then
  . /etc/os-release 2>/dev/null
  OS_NAME=${PRETTY_NAME:-$NAME}
fi
echo "[8/8] 系统"
echo "  发行版: $OS_NAME   内核: $(uname -r 2>/dev/null)   架构: $(uname -m 2>/dev/null)"

# ---------- 结论 ----------
BAD=0; MID=0; REASONS=""
for pair in "CPU:$CPU_LEVEL:$CPU_CORES 核" "MEM:$MEM_LEVEL:内存 ${MEM_TOTAL}G" "DISK:$DISK_LEVEL:磁盘可用 ${D_AVAIL}G"; do
  LVL=$(echo "$pair" | cut -d: -f2)
  DESC=$(echo "$pair" | cut -d: -f3)
  case "$LVL" in
    不建议) BAD=$((BAD+1)); REASONS="${REASONS}  - ${DESC} → 不建议\n" ;;
    勉强)   MID=$((MID+1)); REASONS="${REASONS}  - ${DESC} → 勉强\n" ;;
  esac
done
if [ "$BAD" -ge 2 ]; then VERDICT="不建议"
elif [ "$BAD" -eq 1 ] || [ "$MID" -ge 1 ]; then VERDICT="勉强可用"
else VERDICT="推荐"; fi

echo ""
echo "== 结论 =="
echo "总体: $VERDICT"
if [ -n "$REASONS" ]; then printf "扣分项:\n$REASONS"; else echo "扣分项: 无（CPU / 内存 / 磁盘均达到推荐线）"; fi
case "$CONTAINER_LINE" in
  *"运行中容器 0 个"*) : ;;
  *"运行中容器"*) echo "备注: 机器上已有容器在跑，实际可用余量会低于账面值，上线前需与占用方确认。" ;;
esac
if [ "$DISK_LEVEL" = "不建议" ]; then
  echo "提示: 磁盘不足 50G 时，六个微服务镜像 + MySQL/Milvus 数据会很快写满，建议换机或先扩容。"
fi
echo "参考: 本套（6 微服务 + Nacos/MySQL/Redis/RabbitMQ/Milvus）建议 8 核 / 16G / 可用 100G 以上；Milvus 最吃内存。"
