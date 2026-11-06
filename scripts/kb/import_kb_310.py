#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库 CSV → MySQL 幂等导入（问题二扩容）。

用法：
  MYSQL_PWD=... python3 scripts/kb/import_kb_310.py \
      --csv docs/paper/问题二/kb_310.csv [--dry-run]

匹配规则（保证可重复执行、不产生重复行）：
  1) 先按主键 id（= CSV source_id）匹配；
  2) 未命中则按 (title, apply_device_type) 匹配仍在用的行（deleted=0）；
  3) 仍未命中才 INSERT。
  已命中行：覆盖七字段正文/摘要/标签，version+1，vector_synced_at 置 NULL（等待重建向量）。

写入口径（不改表结构，DEC-11）：
  七字段全部落在 content；cluster_key/cluster_type/source_tier 落在 tags 数组。
"""
import argparse
import csv
import json
import os
import sys

import pymysql

DEFAULT_SECRET = "/home/dev/secrets/mysql_pwd"
SECTIONS = ["故障现象：", "可能原因（根因）：", "区分依据：", "处理步骤：",
            "预防措施：", "验证结果：", "适用条件："]


def read_password(cli_pwd):
    if cli_pwd:
        return cli_pwd
    if os.environ.get("MYSQL_PWD"):
        return os.environ["MYSQL_PWD"]
    with open(DEFAULT_SECRET, encoding="utf-8") as f:
        return f.read().strip()


def load_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("source_id", "category_id"):
            r[k] = int(r[k]) if r.get(k) else None
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="docs/paper/问题二/kb_310.csv")
    ap.add_argument("--host", default=os.environ.get("MYSQL_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MYSQL_PORT", "3306")))
    ap.add_argument("--user", default=os.environ.get("MYSQL_USER", "dev"))
    ap.add_argument("--db", default=os.environ.get("MYSQL_DB", "aitims"))
    ap.add_argument("--password", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = load_rows(args.csv)
    if len(rows) != 310:
        sys.exit("CSV 行数=%d，期望 310，拒绝导入" % len(rows))

    conn = pymysql.connect(host=args.host, port=args.port, user=args.user,
                           password=read_password(args.password), database=args.db,
                           charset="utf8mb4", autocommit=False)
    stats = {"insert": 0, "updated_by_id": 0, "updated_by_title": 0}
    touched_ids = []
    try:
        with conn.cursor() as cur:
            for r in rows:
                tags = json.loads(r["tags"]) if r.get("tags") else []
                payload = (
                    r["title"], r["content"], r["summary"],
                    json.dumps(tags, ensure_ascii=False),
                    r["device_type"], r["category_id"],
                )
                cur.execute("SELECT id FROM kb_knowledge WHERE id=%s", (r["source_id"],))
                hit = cur.fetchone()
                mode = "insert"
                target_id = r["source_id"]
                if hit:
                    mode = "updated_by_id"
                else:
                    cur.execute(
                        "SELECT id FROM kb_knowledge WHERE title=%s AND apply_device_type=%s "
                        "AND deleted=0 LIMIT 1", (r["title"], r["device_type"]))
                    hit2 = cur.fetchone()
                    if hit2:
                        mode = "updated_by_title"
                        target_id = hit2[0]

                if mode == "insert":
                    if not args.dry_run:
                        cur.execute(
                            "INSERT INTO kb_knowledge (id, tenant_id, title, content, summary, tags,"
                            " apply_device_type, category_id, status, version, vector_synced_at, deleted)"
                            " VALUES (%s, 1, %s, %s, %s, %s, %s, %s, 'PUBLISHED', 1, NULL, 0)",
                            (target_id,) + payload)
                else:
                    if not args.dry_run:
                        cur.execute(
                            "UPDATE kb_knowledge SET title=%s, content=%s, summary=%s, tags=%s,"
                            " apply_device_type=%s, category_id=%s, status='PUBLISHED',"
                            " version=version+1, vector_synced_at=NULL, deleted=0,"
                            " reject_reason=NULL, update_time=NOW() WHERE id=%s",
                            payload + (target_id,))
                stats[mode] += 1
                touched_ids.append(target_id)
        if args.dry_run:
            conn.rollback()
            print("[dry-run] 未提交", json.dumps(stats, ensure_ascii=False))
            return
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0")
            published = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT title) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0")
            unique_titles = cur.fetchone()[0]
            cur.execute("SELECT apply_device_type, COUNT(*) FROM kb_knowledge"
                        " WHERE status='PUBLISHED' AND deleted=0 GROUP BY apply_device_type"
                        " ORDER BY COUNT(*) DESC")
            dev = dict(cur.fetchall())
            cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0"
                        " AND vector_synced_at IS NULL")
            pending_vec = cur.fetchone()[0]
            # 七字段落到 content 的覆盖核查
            rates = {}
            for s in SECTIONS:
                cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0"
                            " AND content LIKE %s", ("%" + s + "%",))
                rates[s] = cur.fetchone()[0]
    finally:
        conn.close()

    out = {
        "action_stats": stats,
        "touched": len(set(touched_ids)),
        "published_total": published,
        "unique_titles": unique_titles,
        "device_distribution": dev,
        "vector_pending": pending_vec,
        "content_section_coverage": rates,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("\n[db] PUBLISHED=%d 唯一标题=%d 待向量化=%d" % (published, unique_titles, pending_vec))


if __name__ == "__main__":
    main()
