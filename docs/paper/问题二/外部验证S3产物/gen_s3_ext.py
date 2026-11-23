#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部验证集 S3 推理：Qwen2.5-7B + LoRA(s3)，贪心解码。

- system prompt 与 S1 外部评测（ext_eval.py 的 INSTRUCTION）逐字相同，便于 S1 vs S3 对照；
- user 内容与 ext_eval.py 一致："工单：\n" + text；
- 输出格式与 ext_eval.py run 子命令一致，可直接 score --tag s3。
"""
import argparse
import json
import sys
import time

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, "/tmp/ext-eval")
from ext_eval import INSTRUCTION, norm_out  # noqa: E402

M = "/root/autodl-tmp/models/Qwen2.5-7B-Instruct"
A = "/root/autodl-tmp/ckpt/qwen25-7b-lora-s3"
EXT = "/tmp/ext-eval"
FILES = ["eval_maintnet.jsonl", "eval_fujitsu.jsonl", "eval_elevator.jsonl"]

ap = argparse.ArgumentParser()
ap.add_argument("--tag", default="s3")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--max_new", type=int, default=640)
ap.add_argument("--batch", type=int, default=8)
a = ap.parse_args()

tok = AutoTokenizer.from_pretrained(M, use_fast=True)
tok.padding_side = "left"
model = AutoModelForCausalLM.from_pretrained(M, torch_dtype=torch.bfloat16, device_map={"": 0})
model = PeftModel.from_pretrained(model, A)
model.eval()

rows = []
for fn in FILES:
    rows += [json.loads(l) for l in open(EXT + "/" + fn, encoding="utf-8") if l.strip()]
if a.limit:
    rows = rows[:a.limit]

prompts = []
for r in rows:
    msgs = [{"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": "工单：\n" + r["text"]}]
    prompts.append(tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True))

lens = [len(tok(p, add_special_tokens=False)["input_ids"]) for p in prompts]
print("[info] n=%d prompt_tokens min/avg/max=%d/%.0f/%d"
      % (len(prompts), min(lens), sum(lens) / len(lens), max(lens)), flush=True)

order = sorted(range(len(prompts)), key=lambda i: lens[i])
out_path = EXT + "/pred_%s.jsonl" % a.tag
res = {}
t0 = time.time()
with open(out_path, "w", encoding="utf-8") as f:
    done = 0
    for s in range(0, len(order), a.batch):
        idx = order[s:s + a.batch]
        enc = tok([prompts[i] for i in idx], return_tensors="pt",
                  padding=True, add_special_tokens=False).to("cuda")
        t1 = time.time()
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=a.max_new, do_sample=False,
                                 pad_token_id=tok.pad_token_id)
        gen = out[:, enc["input_ids"].shape[1]:]
        texts = tok.batch_decode(gen, skip_special_tokens=True)
        dt = time.time() - t1
        for i, raw in zip(idx, texts):
            o, ok, err = None, False, ""
            p = raw.rfind("}")
            q = raw.find("{")
            if q >= 0 and p > q:
                try:
                    o = json.loads(raw[q:p + 1])
                    ok = True
                except Exception as e:  # noqa: BLE001
                    err = "%s: %s" % (type(e).__name__, str(e)[:120])
            rec = dict(id=rows[i]["id"], dataset=rows[i]["dataset"], json_ok=ok,
                       pred=norm_out(o or {}), raw=raw, error=err,
                       prompt_tokens=lens[i], gen_s=round(dt, 3))
            res[i] = rec
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        done += len(idx)
        el = time.time() - t0
        print("[%s] %d/%d  %.1fs/batch  avg=%.2fs/条  eta=%.1fmin  ok=%d"
              % (a.tag, done, len(order), dt, el / done, el / done * (len(order) - done) / 60,
                 sum(1 for r in res.values() if r["json_ok"])), flush=True)

print("[done] %d 条 -> %s  total=%.1fmin  json_ok=%d"
      % (len(res), out_path, (time.time() - t0) / 60, sum(1 for r in res.values() if r["json_ok"])))
print("[mem] peak_alloc=%.2f GB" % (torch.cuda.max_memory_allocated() / 1024 ** 3))
