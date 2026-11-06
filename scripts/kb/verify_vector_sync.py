#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Milvus 与 DB 一致性核对（排除逻辑删除的残留实体）。"""
import os
import sys

import pymysql
from pymilvus import Collection, connections

MYSQL_SECRET = "/home/dev/secrets/mysql_pwd"
COLLECTION = "kb_knowledge_vec"


def pwd():
    if os.environ.get("MYSQL_PWD"):
        return os.environ["MYSQL_PWD"].strip()
    with open(MYSQL_SECRET, encoding="utf-8") as f:
        return f.read().strip()


conn = pymysql.connect(host="127.0.0.1", user="dev", password=pwd(),
                       database="aitims", charset="utf8mb4", autocommit=True)
with conn.cursor() as cur:
    cur.execute("SELECT id FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0 ORDER BY id")
    db_ids = {int(r[0]) for r in cur.fetchall()}
    cur.execute("SELECT COUNT(*) FROM kb_knowledge WHERE status='PUBLISHED' AND deleted=0"
                " AND vector_synced_at IS NULL")
    pending = cur.fetchone()[0]

connections.connect(alias="v", host="127.0.0.1", port="19530")
coll = Collection(COLLECTION, using="v")
coll.load()
live = coll.query(expr="knowledge_id >= 0", output_fields=["count(*)"])[0]["count(*)"]
ids = coll.query(expr="knowledge_id >= 0", output_fields=["knowledge_id"], limit=1000)
mv_ids = {int(x["knowledge_id"]) for x in ids}

result = {
    "db_published": len(db_ids),
    "milvus_live_entities": int(live),
    "milvus_raw_num_entities": int(coll.num_entities),
    "db_minus_milvus": len(db_ids - mv_ids),
    "milvus_minus_db": len(mv_ids - db_ids),
    "db_vector_pending": pending,
    "consistent": len(db_ids) == int(live) and not (db_ids ^ mv_ids),
}
print(result)
sys.exit(0 if result["consistent"] else 1)
