#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S3「已合并 adapter」推理耗时 + 三档峰值显存。

计时区间与旧 gen_s 完全一致：generate 调用前 -> decode 结束（不含模型加载、不含分词）。
样本：留出集 200 条，前 3 条 warmup 丢弃（与重测协议一致）。
"""
import json
import statistics
import sys
import time

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, "/root")
from train_lora import build_messages  # noqa: E402

M = "/root/autodl-tmp/models/Qwen2.5-7B-Instruct"
A = "/root/autodl-tmp/ckpt/qwen25-7b-lora-s3"
IN = "/root/autodl-tmp/data/heldout_eval.jsonl"
OUT = "/tmp/ext-eval/merged_s3.json"
CSV = "/tmp/ext-eval/rows_S3_merged.csv"
MAXNEW = 384
WARMUP = 3

tok = AutoTokenizer.from_pretrained(M, use_fast=True)
tok.padding_side = "left"
recs = [json.loads(l) for l in open(IN, encoding="utf-8") if l.strip()]
print("[info] n=%d warmup=%d max_new=%d" % (len(recs), WARMUP, MAXNEW), flush=True)


def gen_one(m, rec):
    text = tok.apply_chat_template(build_messages(rec), tokenize=False, add_generation_prompt=True)
    ids = tok(text, return_tensors="pt", add_special_tokens=False).to("cuda")
    t1 = time.perf_counter()
    with torch.no_grad():
        out = m.generate(**ids, max_new_tokens=MAXNEW, do_sample=False,
                         pad_token_id=tok.pad_token_id)
    raw = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
    dt = time.perf_counter() - t1
    return raw, dt, int(out.shape[1] - ids["input_ids"].shape[1])


def probe_peak(m, tag, n=6):
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    for r in recs[:n]:
        gen_one(m, r)
    torch.cuda.synchronize()
    return {"peak_alloc_gb": round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2),
            "peak_reserved_gb": round(torch.cuda.max_memory_reserved() / 1024 ** 3, 2),
            "probe_n": n}


out = {"env": {"gpu": torch.cuda.get_device_name(0),
               "gpu_mem_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, 1),
               "dtype": "bfloat16", "framework": "transformers.generate",
               "torch": torch.__version__, "transformers": __import__("transformers").__version__,
               "peft": __import__("peft").__version__,
               "max_new_tokens": MAXNEW, "batch": 1, "do_sample": False,
               "timing": "perf_counter: before generate -> after decode (same as gen_s)"}}

model = AutoModelForCausalLM.from_pretrained(M, torch_dtype=torch.bfloat16, device_map={"": 0})
model.eval()
out["S1_base_peak"] = probe_peak(model, "S1_base")
print("[S1] " + json.dumps(out["S1_base_peak"]), flush=True)

model = PeftModel.from_pretrained(model, A)
model.eval()
out["S3_unmerged_peak"] = probe_peak(model, "S3_unmerged")
print("[S3u] " + json.dumps(out["S3_unmerged_peak"]), flush=True)

torch.cuda.reset_peak_memory_stats()
try:
    merged = model.merge_and_unload()
    out["merge_peak_alloc_gb"] = round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2)
except RuntimeError as e:
    print("[warn] GPU merge failed (%s), retry on CPU" % str(e)[:120], flush=True)
    model = model.to("cpu")
    torch.cuda.empty_cache()
    merged = model.merge_and_unload()
out["merge_peak_alloc_gb"] = round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2)
merged.eval()
print("[merge] peak_alloc=%.2f GB" % out["merge_peak_alloc_gb"], flush=True)

torch.cuda.empty_cache()
torch.cuda.reset_peak_memory_stats()
lat, ntok, ok, rows = [], [], 0, []
for i, r in enumerate(recs):
    raw, dt, n = gen_one(merged, r)
    try:
        q, p = raw.find("{"), raw.rfind("}")
        json.loads(raw[q:p + 1])
        ok += 1
    except Exception:  # noqa: BLE001
        pass
    if i < WARMUP:
        continue
    lat.append(dt)
    ntok.append(n)
    rows.append((r["id"], round(dt, 3), n, raw))
    if (i + 1) % 20 == 0:
        print("[merged] %d/%d median=%.2fs" % (i + 1, len(recs), statistics.median(lat)), flush=True)

out["S3_merged"] = {
    "n": len(lat),
    "mean_s": statistics.fmean(lat), "p50_s": statistics.median(lat),
    "p95_s": sorted(lat)[int(0.95 * (len(lat) - 1))], "min_s": min(lat), "max_s": max(lat),
    "out_tokens_mean": statistics.fmean(ntok),
    "tok_per_s_aggregate": sum(ntok) / sum(lat),
    "tok_per_s_median": statistics.median([n / t for n, t in zip(ntok, lat)]),
    "json_ok_rate": ok / len(recs),
    "peak_alloc_gb": round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2),
    "peak_reserved_gb": round(torch.cuda.max_memory_reserved() / 1024 ** 3, 2),
}
# 与未合并版本的输出一致性（验证 merge 不改变结果）
try:
    old = {}
    for l in open("/tmp/ext-eval/pred_s3_lora.jsonl", encoding="utf-8"):
        r = json.loads(l)
        old[r["id"]] = (r.get("raw") or "").strip()
    same = sum(1 for i, _, _, raw in rows if old.get(i, "") == raw.strip())
    out["merge_equivalence"] = {"compared": len(rows), "raw_exact_same": same,
                                "rate": same / len(rows)}
    print("[merge] 输出逐字一致 %d/%d" % (same, len(rows)), flush=True)
except Exception as e:  # noqa: BLE001
    out["compare_error"] = str(e)[:120]

with open(CSV, "w", encoding="utf-8") as f:
    f.write("id,gen_s,out_tokens\n")
    for i, d, n, _ in rows:
        f.write("%s,%.3f,%d\n" % (i, d, n))

json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("[saved] " + OUT)
print(json.dumps(out, ensure_ascii=False, indent=1))
