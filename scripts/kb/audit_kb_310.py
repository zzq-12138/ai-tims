#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入后终态审计：条数、设备分布、逐字段非空率、成组统计、向量状态。"""
import json
import os

import pymysql

pwd = os.environ.get("MYSQL_PWD") or open("/home/dev/secrets/mysql_pwd", encoding="utf-8").read().strip()
conn = pymysql.connect(host="127.0.0.1", user="dev", password=pwd, database="aitims",
                       charset="utf8mb4", autocommit=True)
cur = conn.cursor()

out = {}
cur.execute("SELECT status, deleted, COUNT(*) FROM kb_knowledge GROUP BY status, deleted")
out["raw_rows"] = {"%s/deleted=%d" % (s, d): c for s, d, c in cur.fetchall()}
cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0")
out["published"] = cur.fetchone()[0]

cur.execute("SELECT apply_device_type, COUNT(*) FROM kb_knowledge"
            " WHERE status='PUBLISHED' AND deleted=0 GROUP BY apply_device_type ORDER BY 2 DESC")
out["device_distribution"] = dict(cur.fetchall())

sections = {"现象": "故障现象：", "原因": "可能原因（根因）：", "区分依据": "区分依据：",
            "处置步骤": "处理步骤：", "预防": "预防措施：", "验证结果": "验证结果：",
            "适用条件": "适用条件："}
rates = {}
for label, token in sections.items():
    cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0"
                " AND content LIKE %s", ("%" + token + "%",))
    rates[label] = "%d/310" % cur.fetchone()[0]
cur.execute("SELECT MIN(CHAR_LENGTH(content)), MAX(CHAR_LENGTH(content)),"
            " ROUND(AVG(CHAR_LENGTH(content)),1) FROM kb_knowledge"
            " WHERE status='PUBLISHED' AND deleted=0")
out["content_length"] = {k: float(v) if v is not None else None
                         for k, v in zip(["min", "max", "avg"], cur.fetchone())}
out["field_coverage"] = rates

cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0"
            " AND JSON_CONTAINS(tags, '\"tier:SEED\"')")
out["tier_seed"] = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0"
            " AND JSON_CONTAINS(tags, '\"tier:SYNTHETIC\"')")
out["tier_synthetic"] = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0"
            " AND JSON_CONTAINS(tags, '\"tier:HANDBOOK\"')")
out["tier_handbook"] = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0"
            " AND tags LIKE '%cluster:SIM-%'")
out["cluster_sim_members"] = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0"
            " AND tags LIKE '%cluster:SIC-%'")
out["cluster_sic_members"] = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0"
            " AND vector_synced_at IS NULL")
out["vector_pending"] = cur.fetchone()[0]
cur.execute("SELECT COUNT(DISTINCT title) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0")
out["unique_titles"] = cur.fetchone()[0]

print(json.dumps(out, ensure_ascii=False, indent=2))
