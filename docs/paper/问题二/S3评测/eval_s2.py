#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2：同一基座 + 规则约束提示词 + 输出校验（无微调）。

与 S1/S3 完全相同的用户消息、贪心解码、max_new_tokens=384。
规则层（对齐路线文档 S2 定义）：
  1) 推理链终点定位：只有明确结论句才填 root_cause；出现"根因未定/待厂家/暂未定位/等厂家"则留空。
  2) 排除假设黑名单：文中"排除 X / 按 X 方向…无改善"的 X 只能进 excluded_hypotheses，不得进 root_cause。
  3) 措施条目粒度：同一句并列动作保持为一个条目，不拆成多条。
  4) 输出校验：14 字段齐全、类型正确、空根因 ⇒ has_final_root_cause=0、
     excluded_hypotheses 与 root_cause 文本重复时从根因侧清空。
"""
import argparse
import json
import re
import sys
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, "/root")
from train_lora import build_messages  # noqa: E402

M = "/root/autodl-tmp/models/Qwen2.5-7B-Instruct"
IN = "/root/autodl-tmp/data/heldout_eval.jsonl"

KEYS14 = ["symptom", "symptom_evidence", "root_cause", "root_cause_evidence", "measures",
          "verification", "verification_evidence", "conditions", "excluded_hypotheses",
          "is_excluded_hypothesis", "unverified_hypotheses", "has_final_root_cause",
          "uncertain", "note"]

S2_SYSTEM = (
    "你是半导体封装测试设备的知识抽取助手。请从工单文本中抽取结构化知识，"
    "只输出一个 JSON 对象，不要输出解释、不要加代码块。\n"
    "必须遵守以下判定规则：\n"
    "1) 先定位结论句：只有当文本明确给出已确认的根因结论时才填写 root_cause；"
    "若文本写“根因未定/暂未定位/待厂家/等厂家来看/继续跟踪”，root_cause 必须为空字符串，"
    "has_final_root_cause=0，uncertain=1。\n"
    "2) 文中出现“排除 X”“按 X 方向排查/处置后无改善”的 X 一律写入 excluded_hypotheses，"
    "严禁把被排除的假设、或现象观测句（如“同批板材厚度实测一致，喷淋流量分布偏差 25%”）当作根因。\n"
    "3) measures 只写已执行的维修/调整动作；同一句中的并列动作保持为一个条目，不要拆成多条；"
    "“先降速跑着/等厂家”这类临时处置不算措施。\n"
    "4) 数字与单位照抄原文，不要换算。\n"
    "5) 字段必须齐全且同名：symptom（现象）、symptom_evidence（现象证据原文）、"
    "root_cause（根因）、root_cause_evidence（根因证据原文）、measures（字符串数组）、"
    "verification（验证结果）、verification_evidence（验证证据原文）、"
    "conditions（数组，元素为 {\"type\",\"value\"}）、"
    "excluded_hypotheses（数组，元素为 {\"hypothesis\",\"evidence\"}，可为空数组）、"
    "is_excluded_hypothesis（0/1）、unverified_hypotheses（字符串数组，可为空）、"
    "has_final_root_cause（0/1）、uncertain（0/1）、note（无则空字符串）。"
)


def build_messages_s2(rec):
    msgs = build_messages(rec)
    msgs[0]["content"] = S2_SYSTEM
    return msgs


def parse_json(raw):
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    for i, ch in enumerate(s):
        if ch == "{":
            try:
                obj, _ = json.JSONDecoder().raw_decode(s[i:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


def norm(s):
    return re.sub(r"[\s，。；：、,.;:!?！？\"'（）()\[\]【】]", "", str(s or ""))


def validate(obj):
    """规则校验：补齐字段/类型 + 空根因一致性 + 排除假设误入根因时清空根因侧。"""
    if not isinstance(obj, dict):
        return None
    for k in KEYS14:
        obj.setdefault(k, "" if k not in ("measures", "conditions", "excluded_hypotheses",
                                          "unverified_hypotheses") else [])
    if not isinstance(obj["measures"], list):
        obj["measures"] = [str(obj["measures"])] if obj["measures"] else []
    if not isinstance(obj["unverified_hypotheses"], list):
        obj["unverified_hypotheses"] = []
    if not isinstance(obj["conditions"], list):
        obj["conditions"] = []
    if not isinstance(obj["excluded_hypotheses"], list):
        obj["excluded_hypotheses"] = []
    excl = []
    for x in obj["excluded_hypotheses"]:
        if isinstance(x, dict):
            excl.append({"hypothesis": str(x.get("hypothesis", "")), "evidence": str(x.get("evidence", ""))})
        else:
            excl.append({"hypothesis": str(x), "evidence": ""})
    obj["excluded_hypotheses"] = [x for x in excl if x["hypothesis"].strip()]

    rc = str(obj.get("root_cause") or "").strip()
    # 根因侧误用排除假设：根因文本被某个排除假设包含 → 清空根因
    for x in obj["excluded_hypotheses"]:
        h = norm(x["hypothesis"])
        if h and norm(rc) and (norm(rc) in h or h in norm(rc)):
            rc = ""
            break
    obj["root_cause"] = rc
    obj["has_final_root_cause"] = 0 if not rc else 1
    if not rc:
        obj["is_excluded_hypothesis"] = 0
    return obj


ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--max_new", type=int, default=384)
a = ap.parse_args()

tok = AutoTokenizer.from_pretrained(M, use_fast=True)
model = AutoModelForCausalLM.from_pretrained(M, torch_dtype=torch.bfloat16, device_map={"": 0})
model.eval()

recs = [json.loads(l) for l in open(IN, encoding="utf-8") if l.strip()]
if a.limit:
    recs = recs[:a.limit]

t0 = time.time()
with open(a.out, "w", encoding="utf-8") as f:
    for i, r in enumerate(recs, 1):
        text = tok.apply_chat_template(build_messages_s2(r), tokenize=False, add_generation_prompt=True)
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
        obj = validate(parse_json(raw))
        row = {"id": r["id"], "style": r["style"], "structure": r["structure"],
               "device_type": r["device_type"],
               "raw": json.dumps(obj, ensure_ascii=False) if obj is not None else raw,
               "error": err, "gen_s": round(time.time() - t1, 2)}
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        if i % 10 == 0 or i == len(recs):
            el = time.time() - t0
            print("[s2] %d/%d  avg=%.1fs  eta=%.1fmin" % (i, len(recs), el / i, el / i * (len(recs) - i) / 60),
                  flush=True)

print("[done] s2 -> %s  total=%.1fmin" % (a.out, (time.time() - t0) / 60))
print("[mem] peak_alloc=%.2f GB" % (torch.cuda.max_memory_allocated() / 1024 ** 3))
