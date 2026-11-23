#!/usr/bin/env bash
# 五元组字段迁移（P0/P2）：预检 → 执行 DDL → 后检。
# 仅用于本机/VM 开发库；脚本会打印 host/db 并核对行数、原始列值、新列与索引。
# 用法：bash scripts/annotation/apply_pentad_migration.sh [sql 路径]
set -euo pipefail

SQL=${1:-/home/dev/ai-tims/docs/sql/20261107_m6_pentad_condition.sql}
PW=$(cat /home/dev/secrets/mysql_pwd)
q() { mysql -h127.0.0.1 -P3306 -udev -p"$PW" -D aitims "$@"; }

AI_COLS="root_cause root_cause_evidence verification verification_evidence apply_conditions condition_keys excluded_hypotheses has_final_root_cause relation_type relation_confidence chain_trace"
KB_COLS="root_cause verification apply_conditions condition_keys"

echo "[db] host=$(hostname) db=aitims sql=$SQL"
before_ai=$(q -N -B -e "select count(*) from ai_extracted")
before_kb=$(q -N -B -e "select count(*) from kb_knowledge")
echo "[db] before rows: ai_extracted=$before_ai kb_knowledge=$before_kb"

q -N -B -e "set session group_concat_max_len=1000000; select group_concat(column_name order by ordinal_position) from information_schema.columns where table_schema='aitims' and table_name='ai_extracted'" > /tmp/cols_ai.txt
q -N -B -e "set session group_concat_max_len=1000000; select group_concat(column_name order by ordinal_position) from information_schema.columns where table_schema='aitims' and table_name='kb_knowledge'" > /tmp/cols_kb.txt
COLS_AI=$(cat /tmp/cols_ai.txt)
COLS_KB=$(cat /tmp/cols_kb.txt)
q -B -N -e "select $COLS_AI from ai_extracted order by id" > /tmp/pre_ai.tsv
q -B -N -e "select $COLS_KB from kb_knowledge order by id" > /tmp/pre_kb.tsv
echo "[db] snapshot: $(wc -l < /tmp/pre_ai.tsv) / $(wc -l < /tmp/pre_kb.tsv) 行"

echo "[db] applying $SQL"
mysql -h127.0.0.1 -P3306 -udev -p"$PW" -D aitims < "$SQL"

after_ai=$(q -N -B -e "select count(*) from ai_extracted")
after_kb=$(q -N -B -e "select count(*) from kb_knowledge")
echo "[db] after rows: ai_extracted=$after_ai kb_knowledge=$after_kb"
[ "$before_ai" = "$after_ai" ] || { echo "[FAIL] ai_extracted 行数变化"; exit 1; }
[ "$before_kb" = "$after_kb" ] || { echo "[FAIL] kb_knowledge 行数变化"; exit 1; }

q -B -N -e "select $COLS_AI from ai_extracted order by id" > /tmp/post_ai.tsv
q -B -N -e "select $COLS_KB from kb_knowledge order by id" > /tmp/post_kb.tsv
diff -q /tmp/pre_ai.tsv /tmp/post_ai.tsv >/dev/null || { echo "[FAIL] ai_extracted 旧列数值变化"; exit 1; }
diff -q /tmp/pre_kb.tsv /tmp/post_kb.tsv >/dev/null || { echo "[FAIL] kb_knowledge 旧列数值变化"; exit 1; }
echo "[db] 旧行旧列数值未变"

for c in $AI_COLS; do
  n=$(q -N -B -e "select count(*) from information_schema.columns where table_schema='aitims' and table_name='ai_extracted' and column_name='$c'")
  [ "$n" = "1" ] || { echo "[FAIL] ai_extracted 缺列 $c"; exit 1; }
done
for c in $KB_COLS; do
  n=$(q -N -B -e "select count(*) from information_schema.columns where table_schema='aitims' and table_name='kb_knowledge' and column_name='$c'")
  [ "$n" = "1" ] || { echo "[FAIL] kb_knowledge 缺列 $c"; exit 1; }
done
echo "[db] 新列齐全：ai_extracted=$(echo $AI_COLS | wc -w) 列，kb_knowledge=$(echo $KB_COLS | wc -w) 列"

idx=$(q -N -B -e "select count(*) from information_schema.statistics where table_schema='aitims' and table_name='ai_extracted' and index_name='idx_tenant_relation'")
[ "$idx" -ge 1 ] || { echo "[FAIL] 缺索引 idx_tenant_relation"; exit 1; }
idx=$(q -N -B -e "select count(*) from information_schema.statistics where table_schema='aitims' and table_name='kb_knowledge' and index_name='idx_tenant_condition'")
[ "$idx" -ge 1 ] || { echo "[FAIL] 缺索引 idx_tenant_condition"; exit 1; }
echo "[db] 索引齐全"
echo "[OK] 迁移完成，回滚语句保留在 SQL 文件末尾"
