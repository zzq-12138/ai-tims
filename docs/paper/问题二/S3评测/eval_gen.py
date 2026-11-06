#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""heldout 推理：base（S1）或 lora（S3），贪心解码，逐条重试并记录。"""
import argparse
import json
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

ap = argparse.ArgumentParser()
ap.add_argument("--mode", choices=["base", "lora"], required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--max_new", type=int, default=384)
a = ap.parse_args()

tok = AutoTokenizer.from_pretrained(M, use_fast=True)
model = AutoModelForCausalLM.from_pretrained(M, torch_dtype=torch.bfloat16, device_map={"": 0})
if a.mode == "lora":
    model = PeftModel.from_pretrained(model, A)
model.eval()

recs = [json.loads(l) for l in open(IN, encoding="utf-8") if l.strip()]
if a.limit:
    recs = recs[:a.limit]

t0 = time.time()
with open(a.out, "w", encoding="utf-8") as f:
    for i, r in enumerate(recs, 1):
        text = tok.apply_chat_template(build_messages(r), tokenize=False, add_generation_prompt=True)
        ids = tok(text, return_tensors="pt", add_special_tokens=False).to("cuda")
        raw, err, t1 = None, None, time.time()
        for attempt in range(1, 4):
            try:
                with torch.no_grad():
                    out = model.generate(**ids, max_new_tokens=a.max_new,
                                         do_sample=False, pad_token_id=tok.pad_token_id)
                raw = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
                err = None
                break
            except Exception as e:  # noqa: BLE001
                err = "%s: %s" % (type(e).__name__, str(e)[:200])
                torch.cuda.empty_cache()
                time.sleep(2 * attempt)
        row = {"id": r["id"], "style": r["style"], "structure": r["structure"],
               "device_type": r["device_type"], "raw": raw, "error": err,
               "gen_s": round(time.time() - t1, 2)}
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        if i % 10 == 0 or i == len(recs):
            el = time.time() - t0
            eta = el / i * (len(recs) - i)
            print("[%s] %d/%d  avg=%.1fs  eta=%.1fmin" % (a.mode, i, len(recs), el / i, eta / 60), flush=True)

print("[done] %s -> %s  total=%.1fmin" % (a.mode, a.out, (time.time() - t0) / 60))
print("[mem] peak_alloc=%.2f GB" % (torch.cuda.max_memory_allocated() / 1024 ** 3))
