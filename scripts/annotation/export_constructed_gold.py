#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构造真值（construction-based gold）导出为训练/评测标准格式。

注意：真值由生成器在造样本时同步确定，不是人工标注。本脚本只做格式转换，不做判定。

产出：
  constructed_gold.jsonl         逐条：ticket_id / device / ticket_text / label（五元组 + 两个二值字段）
  constructed_gold_alpaca.json   LLaMA-Factory alpaca 格式（instruction / input / output）
"""
import argparse
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE, "docs", "paper", "问题二")

INSTRUCTION = (
    "你是设备维修工单知识抽取器。请从工单文本中抽取维修知识，只输出一个 JSON 对象，字段："
    "symptom(现象)、symptom_evidence(现象原文依据)、root_cause(根因，没有则空串)、"
    "root_cause_evidence(根因依据)、measures(处理措施，字符串数组)、verification(验证结果)、"
    "verification_evidence(验证依据)、conditions(适用条件数组，元素为 {type,value}，"
    "type 取值 device_model/process_stage/material_or_batch/param_range/precondition)、"
    "excluded_hypotheses(被排除的假设数组，元素为 {hypothesis,evidence})、"
    "is_excluded_hypothesis(是否有排除假设，0/1)、unverified_hypotheses(未验证假设，数组)、"
    "has_final_root_cause(是否有最终根因，0/1)、uncertain(是否无法判断，0/1)。"
    "禁止编造文本中不存在的信息。"
)


def to_label(g):
    return {
        "symptom": g.get("symptom", ""),
        "symptom_evidence": g.get("symptom", ""),
        "root_cause": g.get("root_cause", ""),
        "root_cause_evidence": g.get("root_cause_evidence", ""),
        "measures": g.get("measures", []),
        "verification": g.get("verification", ""),
        "verification_evidence": g.get("verification", ""),
        "conditions": g.get("conditions", []),
        "excluded_hypotheses": g.get("excluded_hypotheses", []),
        "is_excluded_hypothesis": 1 if g.get("excluded_hypotheses") else 0,
        "unverified_hypotheses": g.get("unverified_hypotheses", []),
        "has_final_root_cause": int(g.get("has_final_root_cause", 0)),
        "uncertain": 0,
        "note": "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=os.path.join(OUT_DIR, "_gold_draft.jsonl"))
    ap.add_argument("--data", default=os.path.join(OUT_DIR, "annotation_set_v1.csv"))
    ap.add_argument("--out-prefix", default=os.path.join(OUT_DIR, "constructed_gold"))
    args = ap.parse_args()

    import csv
    text = {r["ticket_id"]: r["ticket_text"]
            for r in csv.DictReader(open(args.data, encoding="utf-8-sig"))}
    gold = [json.loads(l) for l in open(args.gold, encoding="utf-8") if l.strip()]

    missing = [g["ticket_id"] for g in gold if g["ticket_id"] not in text]
    alpaca, flat = [], []
    for g in gold:
        tid = g["ticket_id"]
        if tid not in text:
            continue
        label = to_label(g)
        flat.append({"ticket_id": tid, "device_type": g.get("device_type", ""),
                     "device_model": g.get("device_model", ""), "error_code": g.get("error_code", ""),
                     "ticket_text": text[tid], "label": label})
        alpaca.append({"instruction": INSTRUCTION, "input": text[tid],
                       "output": json.dumps(label, ensure_ascii=False)})

    with open(args.out_prefix + ".jsonl", "w", encoding="utf-8") as f:
        for r in flat:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(args.out_prefix + "_alpaca.json", "w", encoding="utf-8") as f:
        json.dump(alpaca, f, ensure_ascii=False, indent=1)

    print(f"[ok] {len(flat)} 条 -> {args.out_prefix}.jsonl")
    print(f"[ok] {len(alpaca)} 条 -> {args.out_prefix}_alpaca.json")
    if missing:
        print(f"[warn] {len(missing)} 条在 CSV 里找不到原文：{missing[:10]}")


if __name__ == "__main__":
    main()
