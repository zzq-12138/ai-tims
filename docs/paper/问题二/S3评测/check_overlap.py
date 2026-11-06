#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核对 heldout 200 条与训练集 1000 条的 id 交集，并输出评测集构成。"""
import json
from collections import Counter

P = "/home/dev/ai-tims/docs/paper/问题二/"
tr = [json.loads(l) for l in open(P + "constructed_gold.jsonl", encoding="utf-8") if l.strip()]
he = [json.loads(l) for l in open(P + "_heldout_eval_input.jsonl", encoding="utf-8") if l.strip()]
tr_ids = {r.get("ticket_id") or r.get("id") for r in tr}
he_ids = {r.get("id") for r in he}
print("train n=%d heldout n=%d" % (len(tr), len(he)))
print("train id sample", sorted(tr_ids)[:3], "heldout id sample", sorted(he_ids)[:3])
print("intersection:", len(tr_ids & he_ids), sorted(tr_ids & he_ids)[:10])
print("style", Counter(r["style"] for r in he))
print("structure", Counter(r["structure"] for r in he))
print("with gold excluded", sum(1 for r in he if r["gold"].get("excluded_hypotheses")))
print("empty gold root", sum(1 for r in he if not str(r["gold"].get("root_cause") or "").strip()))
print("device_type", Counter(r["device_type"] for r in he).most_common(8))
# 文本级近似重复核查：完全相同的 symptom_text
tr_txt = {str(r.get("input", {}).get("symptom_text") or r.get("ticket_text") or "").strip() for r in tr}
same = sum(1 for r in he if str(r["input"].get("symptom_text") or "").strip() in tr_txt)
print("identical symptom_text overlap:", same)
