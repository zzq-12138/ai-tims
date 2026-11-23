#!/usr/bin/env bash
# =============================================================================
# kb_migrate_export.sh —— 在【开发机 dev@192.168.40.10】上导出知识库数据
#
# 作用：用 mysqldump 只导出 kb_category + kb_knowledge 两张表的【数据】，
#       不导结构（--no-create-info），不带 Milvus 向量（向量本来也不在 MySQL 里）。
#
# 产物体积量级：320 条知识 + 少量分类，预计 1~3MB，正常不会超过 10MB。
#
# 注意：
#   1) 本脚本只在开发机执行，不连公司库、不动集群。
#   2) 密码从 /home/dev/secrets/mysql_pwd 读取，通过临时 my.cnf（chmod 600）
#      传给 mysqldump / mysql，不进命令行参数、不回显、退出即删。
#   3) 导出的是“数据快照”，导入公司库后必须把 vector_synced_at 置空，
#      由公司侧 Qwen3-Embedding-8B 重新算向量（见 kb_migrate_import.md）。
#
# 用法：
#   bash kb_migrate_export.sh
#   OUT_DIR=/home/dev/backup FORCE=1 bash kb_migrate_export.sh
# =============================================================================
set -euo pipefail

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-dev}"
DB_NAME="${DB_NAME:-aitims}"
PWD_FILE="${PWD_FILE:-/home/dev/secrets/mysql_pwd}"
OUT_DIR="${OUT_DIR:-/home/dev/backup}"
FORCE="${FORCE:-0}"

TABLES="kb_category kb_knowledge"
STAMP="$(date +%Y%m%d)"
OUT_FILE="${OUT_DIR}/kb_migrate_${STAMP}.sql"

die() { echo "[FATAL] $*" >&2; exit 1; }

command -v mysqldump >/dev/null 2>&1 || die "未找到 mysqldump"
command -v mysql >/dev/null 2>&1 || die "未找到 mysql 客户端（脚本要用它打印行数）"
[ -r "$PWD_FILE" ] || die "读不到密码文件：${PWD_FILE}（请确认权限，例如 chmod 600）"

mkdir -p "$OUT_DIR" || die "无法创建输出目录：${OUT_DIR}"

if [ -e "$OUT_FILE" ] && [ "$FORCE" != "1" ]; then
  die "输出文件已存在：${OUT_FILE}。如需覆盖请加 FORCE=1"
fi

# --- 密码只进临时配置文件，600 权限，退出即删 -------------------------------
TMP_CNF="$(mktemp "${TMPDIR:-/tmp}/kbmig.XXXXXX")"
chmod 600 "$TMP_CNF"
cleanup() { rm -f "$TMP_CNF"; }
trap cleanup EXIT INT TERM

{
  printf '[client]\n'
  printf 'user=%s\n' "$DB_USER"
  printf 'password="%s"\n' "$(tr -d '\r\n' < "$PWD_FILE")"
  printf 'host=%s\n' "$DB_HOST"
  printf 'port=%s\n' "$DB_PORT"
  printf 'default-character-set=utf8mb4\n'
} > "$TMP_CNF"

echo "[1/4] 导出 ${DB_NAME} 的 ${TABLES} ..."
# --no-create-info   只导数据，不导出 CREATE TABLE
# --complete-insert  带上列名，避免两边列顺序/新增列导致错位
# --skip-add-locks   导入时不需要 LOCK TABLES 语句（公司库给的是普通账号也能导）
# --single-transaction 一致性快照，不锁表
# --skip-triggers    不导触发器
# --no-tablespaces   MySQL 8 非 root 账号必需，否则报 PROCESS 权限错误
# 若 mysqldump 报 unknown option: --set-gtid-purged（MariaDB 客户端），删掉这一行即可
mysqldump --defaults-extra-file="$TMP_CNF" \
  --no-create-info \
  --complete-insert \
  --skip-add-locks \
  --single-transaction \
  --skip-triggers \
  --no-tablespaces \
  --set-gtid-purged=OFF \
  --default-character-set=utf8mb4 \
  "$DB_NAME" $TABLES > "$OUT_FILE" || die "mysqldump 执行失败，未生成有效文件"

[ -s "$OUT_FILE" ] || die "导出文件为空：${OUT_FILE}"

echo "[2/4] 校验导出内容（应只有 INSERT，不应有 CREATE TABLE）"
CREATE_CNT=$(grep -c '^CREATE TABLE' "$OUT_FILE" 2>/dev/null || true)
INSERT_CNT=$(grep -c '^INSERT INTO' "$OUT_FILE" 2>/dev/null || true)
echo "      CREATE TABLE 语句数 = ${CREATE_CNT:-0}（期望 0）"
echo "      INSERT INTO  语句数 = ${INSERT_CNT:-0}（期望 2：分类 1 条 + 知识 1 条）"

echo "[3/4] 打印源表行数（用于和导入后核对）"
mysql --defaults-extra-file="$TMP_CNF" -N -B -e "
SELECT CONCAT('kb_category  ', COUNT(*)) FROM \`${DB_NAME}\`.kb_category;
SELECT CONCAT('kb_knowledge ', COUNT(*)) FROM \`${DB_NAME}\`.kb_knowledge;
SELECT CONCAT('  其中 PUBLISHED ', COUNT(*)) FROM \`${DB_NAME}\`.kb_knowledge WHERE status='PUBLISHED';
SELECT CONCAT('  其中 PENDING   ', COUNT(*)) FROM \`${DB_NAME}\`.kb_knowledge WHERE status='PENDING';
SELECT CONCAT('  其中已向量化  ', COUNT(*)) FROM \`${DB_NAME}\`.kb_knowledge WHERE vector_synced_at IS NOT NULL;
" || die "查询行数失败"

echo "[4/4] 生成校验信息"
MD5=$(md5sum "$OUT_FILE" | awk '{print $1}')
SIZE=$(du -h "$OUT_FILE" | cut -f1)
BYTES=$(wc -c < "$OUT_FILE" | tr -d ' ')
{
  echo "file=${OUT_FILE}"
  echo "size=${SIZE} (${BYTES} bytes)"
  echo "md5=${MD5}"
  echo "created_at=$(date '+%Y-%m-%d %H:%M:%S')"
  echo "db=${DB_NAME} tables=${TABLES} rows_expected=320"
} | tee "${OUT_FILE}.md5"

echo "------------------------------------------------------------"
echo "导出完成：${OUT_FILE}"
echo "  md5 = ${MD5}"
echo "  体积 = ${SIZE}"
echo ""
echo "下一步：按 docs/sql/kb_migrate_import.md 的传输路线把本文件和 .md5 一起拷走。"
echo "提醒：不要把密码文件、也不要带密码的命令行写进任何笔记或聊天记录。"
