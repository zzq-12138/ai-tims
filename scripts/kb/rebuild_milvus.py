#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全量重建 Milvus 知识向量（问题二扩容）。

- 文本口径与 ticket-knowledge/VectorSyncService 完全一致：
      title + "\n" + summary + "\n" + content
- 向量模型：智谱 embedding-3，dimensions=1024
- collection：kb_knowledge_vec（knowledge_id Int64 主键 / tenant_id Int64 /
  device_type VarChar(64) / embedding FloatVector(1024)，HNSW + COSINE，M=8、efConstruction=64）
- 策略：清空 collection 后按 DB 全量重灌，最后回写 vector_synced_at

用法：
  ZHIPU_API_KEY=$(cat /home/dev/secrets/zhipu_api_key) \
  MYSQL_PWD=$(cat /home/dev/secrets/mysql_pwd) \
  /home/dev/venvs/kb/bin/python scripts/kb/rebuild_milvus.py [--batch 16]
"""
import argparse
import json
import os
import sys
import time

import pymysql
import requests

from pymilvus import (Collection, CollectionSchema, DataType, FieldSchema,
                      connections, utility)

MYSQL_SECRET = "/home/dev/secrets/mysql_pwd"
KEY_SECRET = "/home/dev/secrets/zhipu_api_key"
COLLECTION = "kb_knowledge_vec"
DIM = 1024
API_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"


def read_secret(path, env_name):
    if os.environ.get(env_name):
        return os.environ[env_name].strip()
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def embed(texts, api_key, retries=4):
    body = {"model": "embedding-3", "input": [t[:4000] for t in texts], "dimensions": DIM}
    last = None
    for i in range(retries):
        try:
            r = requests.post(API_URL, json=body, timeout=60, headers={
                "Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
            if r.status_code == 200:
                data = r.json()["data"]
                if len(data) != len(texts):
                    raise RuntimeError("返回条数不匹配 %d vs %d" % (len(data), len(texts)))
                return [d["embedding"] for d in data]
            last = "HTTP %s %s" % (r.status_code, r.text[:200])
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError("embedding 失败: %s" % last)


def ensure_collection(alias):
    if utility.has_collection(COLLECTION, using=alias):
        return Collection(COLLECTION, using=alias)
    fields = [
        FieldSchema("knowledge_id", DataType.INT64, is_primary=True, auto_id=False),
        FieldSchema("tenant_id", DataType.INT64),
        FieldSchema("device_type", DataType.VARCHAR, max_length=64),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=DIM),
    ]
    coll = Collection(COLLECTION, CollectionSchema(fields, description="AI-TIMS knowledge vectors"),
                      using=alias, shards_num=1)
    coll.create_index("embedding", {"index_type": "HNSW", "metric_type": "COSINE",
                                    "params": {"M": 8, "efConstruction": 64}})
    return coll


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--milvus-host", default=os.environ.get("MILVUS_HOST", "127.0.0.1"))
    ap.add_argument("--milvus-port", default=os.environ.get("MILVUS_PORT", "19530"))
    ap.add_argument("--host", default=os.environ.get("MYSQL_HOST", "127.0.0.1"))
    ap.add_argument("--user", default=os.environ.get("MYSQL_USER", "dev"))
    ap.add_argument("--db", default=os.environ.get("MYSQL_DB", "aitims"))
    args = ap.parse_args()

    api_key = read_secret(KEY_SECRET, "ZHIPU_API_KEY")
    mysql_pwd = read_secret(MYSQL_SECRET, "MYSQL_PWD")

    conn = pymysql.connect(host=args.host, user=args.user, password=mysql_pwd,
                           database=args.db, charset="utf8mb4", autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SELECT id, tenant_id, IFNULL(apply_device_type,''), title,"
                    " IFNULL(summary,''), content FROM kb_knowledge"
                    " WHERE status='PUBLISHED' AND deleted=0 ORDER BY id")
        docs = cur.fetchall()
    if not docs:
        sys.exit("DB 无 PUBLISHED 知识，拒绝重建")

    connections.connect(alias="kb", host=args.milvus_host, port=str(args.milvus_port))
    coll = ensure_collection("kb")
    coll.load()
    before = coll.num_entities
    coll.delete("knowledge_id >= 0")
    coll.flush()

    ids, tenants, devices, vectors = [], [], [], []
    for i in range(0, len(docs), args.batch):
        chunk = docs[i:i + args.batch]
        texts = ["%s\n%s\n%s" % (d[3], d[4], d[5]) for d in chunk]
        vecs = embed(texts, api_key)
        ids.extend([int(d[0]) for d in chunk])
        tenants.extend([int(d[1]) for d in chunk])
        devices.extend([d[2] for d in chunk])
        vectors.extend(vecs)
        print("[embed] %d/%d" % (min(i + args.batch, len(docs)), len(docs)))

    for i in range(0, len(ids), args.batch):
        coll.insert([ids[i:i + args.batch], tenants[i:i + args.batch],
                     devices[i:i + args.batch], [list(map(float, v)) for v in vectors[i:i + args.batch]]])
    coll.flush()
    coll.load()
    milvus_count = coll.num_entities

    with conn.cursor() as cur:
        cur.execute("UPDATE kb_knowledge SET vector_synced_at=NOW()"
                    " WHERE status='PUBLISHED' AND deleted=0 AND id IN (%s)"
                    % ",".join(["%s"] * len(ids)), ids)
        cur.execute("SELECT COUNT(*), SUM(vector_synced_at IS NULL) FROM kb_knowledge"
                    " WHERE status='PUBLISHED' AND deleted=0")
        db_total, db_pending = cur.fetchone()

    result = {
        "db_published": db_total,
        "db_vector_pending": int(db_pending or 0),
        "milvus_before": before,
        "milvus_after": milvus_count,
        "consistent": int(db_total) == int(milvus_count),
        "collection": COLLECTION,
        "dim": DIM,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["consistent"]:
        sys.exit("Milvus 条数与 DB 不一致")


if __name__ == "__main__":
    main()
