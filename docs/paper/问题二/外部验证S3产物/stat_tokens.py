#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四方案推理耗时汇总：均值 / P50 / P95 / 输出 tokens/s / 峰值显存。

S1、S2、S3(未合并) 的逐条 gen_s 来自既有 rows_*.csv（不重跑、不覆盖）；
S3(已合并) 用本轮 merged_s3.json + rows_S3_merged.csv。
四列统一丢弃前 3 条（warmup），计时区间均为 generate 前 -> decode 结束。
输出 token 数：对每条 raw 输出重新分词计数（四列同一口径）。
"""
import json
import statistics
from transformers import AutoTokenizer

E = "/tmp/ext-eval"
TOK = "/root/autodl-tmp/models/Qwen2.5-7B-Instruct"
PRED = {
    "S1": "/root/autodl-tmp/eval/pred_s1_base.jsonl",
    "S2": "/root/autodl-tmp/pred_s2_rules.jsonl",
    "S3u": "/root/autodl-tmp/eval/pred_s3_lora.jsonl",
}
CSV = {
    "S1": E + "/rows_S1_base.csv",
    "S2": E + "/rows_S2_rules.csv",
    "S3u": E + "/rows_S3_lora.csv",
    "S3m": E + "/rows_S3_merged.csv",
}
DROP = 3

tok = AutoTokenizer.from_pretrained(TOK, use_fast=True)


def p95(xs):
    s = sorted(xs)
    return s[int(0.95 * (len(s) - 1))]


def read_csv(p):
    rows = []
    with open(p, encoding="utf-8") as f:
        head = f.readline().strip().split(",")
        for l in f:
            v = l.rstrip("\n").split(",")
            rows.append(dict(zip(head, v)))
    return rows


def ntok(s):
    return len(tok(s or "", add_special_tokens=False)["input_ids"])


res = {}
env = json.load(open(E + "/merged_s3.json", encoding="utf-8"))
for k in ["S1", "S2", "S3u"]:
    rows = read_csv(CSV[k])[DROP:]
    pred = {json.loads(l)["id"]: json.loads(l) for l in open(PRED[k], encoding="utf-8") if l.strip()}
    lat = [float(r["gen_s"]) for r in rows]
    tk = [ntok(pred[r["id"]].get("raw", "")) for r in rows]
    res[k] = {"n": len(rows), "mean": statistics.fmean(lat), "p50": statistics.median(lat),
              "p95": p95(lat), "min": min(lat), "max": max(lat),
              "tok_mean": statistics.fmean(tk), "tok_s_agg": sum(tk) / sum(lat),
              "tok_s_med": statistics.median([t / s for t, s in zip(tk, lat)])}

m = env["S3_merged"]
res["S3m"] = {"n": m["n"], "mean": m["mean_s"], "p50": m["p50_s"], "p95": m["p95_s"],
              "min": m["min_s"], "max": m["max_s"], "tok_mean": m["out_tokens_mean"],
              "tok_s_agg": m["tok_per_s_aggregate"], "tok_s_med": m["tok_per_s_median"]}

peak = {"S1": env["S1_base_peak"], "S2": env["S1_base_peak"],
        "S3u": env["S3_unmerged_peak"],
        "S3m": {"peak_alloc_gb": m["peak_alloc_gb"], "peak_reserved_gb": m["peak_reserved_gb"],
                "probe_n": m["n"]}}
for k in res:
    res[k].update(peak[k])

NAME = {"S1": "S1 基座", "S2": "S2 规则", "S3u": "S3 LoRA（未合并）", "S3m": "S3 LoRA（已合并）"}
L = ["| 方案 | n | 均值 (s) | P50 (s) | P95 (s) | 输出 tokens/s（聚合） | tokens/s（P50） | 峰值显存 allocated | 峰值显存 reserved |",
     "|---|---|---|---|---|---|---|---|---|"]
for k in ["S1", "S2", "S3u", "S3m"]:
    d = res[k]
    L.append("| %s | %d | %.2f | %.2f | %.2f | %.1f | %.1f | %.2f GB | %.2f GB |"
             % (NAME[k], d["n"], d["mean"], d["p50"], d["p95"], d["tok_s_agg"], d["tok_s_med"],
                d["peak_alloc_gb"], d["peak_reserved_gb"]))
md = "\n".join(L)
print(md)
json.dump({"env": env["env"], "table": res, "merge_equivalence": env.get("merge_equivalence"),
           "markdown": md}, open(E + "/latency_final.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\n[saved] " + E + "/latency_final.json")
