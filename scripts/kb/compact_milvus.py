#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""触发 Milvus compaction 并核对存活实体数（清理旧向量墓碑）。"""
import time

from pymilvus import Collection, connections

connections.connect(alias="c", host="127.0.0.1", port="19530")
coll = Collection("kb_knowledge_vec", using="c")
coll.load()
print("before num_entities", coll.num_entities)
coll.compact()
for _ in range(12):
    time.sleep(5)
    coll.load()
    if coll.num_entities == 310:
        break
print("after num_entities", coll.num_entities)
print("live count", coll.query(expr="knowledge_id >= 0", output_fields=["count(*)"])[0]["count(*)"])
