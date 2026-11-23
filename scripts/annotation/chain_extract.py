#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五元组链式抽取（P0）：现象 → 根因/验证 → 措施/条件，三步各自可校验。

与现网单轮 7 字段 prompt 的关系：
- 本脚本是链式抽取的离线验证与 prompt 草案来源；Java 侧按同名 STEP 常量移植，
  由开关 tims.ai.extract.chain-enabled 控制，默认关闭（保持单轮行为）。
- 字段口径与 export_constructed_gold.py 的五元组一致：
  symptom / root_cause / measures / verification / conditions（含证据字段）。

子命令：
  prompts  导出三步 prompt 到 docs/paper/问题二/链式抽取/prompts.md
  run      对留出集逐条链式抽取（每张工单 3 次调用，断点续跑）
  score    与 _heldout_eval_input.jsonl 的 gold 比对，输出 metrics.json + 报告片段

口径：留出集 gold 为 construction-based gold（弱监督），不是人工标注。
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE, "docs", "paper", "问题二")
CHAIN_DIR = os.path.join(OUT_DIR, "链式抽取")
HELDOUT = os.path.join(OUT_DIR, "_heldout_eval_input.jsonl")
KEY_PATH = "/home/dev/secrets/zhipu_api_key"
GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-4-flash"

CONDITION_TYPES = ("device_model", "process_stage", "material_or_batch", "param_range", "precondition")
COND_PLACEHOLDERS = {"未提及", "无", "不适用", "未知", "暂无", "none", "n/a", "na", "-", "null"}

# ---------------- 三步 prompt（Java 侧逐字移植） ----------------
STEP1_SYSTEM = (
    "你是设备维修工单知识抽取器。本次只执行第 1 步：定位故障现象。\n"
    "规则：\n"
    "1) symptom 写用户可观察到的异常表现，不写原因、不写处理动作。\n"
    "2) symptom_evidence 必须逐字摘自工单原文；找不到可支撑的原文时，该字段为空串。\n"
    "3) 只输出一个 JSON 对象，不要解释、不要代码块：\n"
    '{"symptom": "...", "symptom_evidence": "..."}'
)

STEP2_SYSTEM = (
    "你是设备维修工单知识抽取器。本次只执行第 2 步：定位根因与验证方式。\n"
    "输入包含工单原文与第 1 步已定位的故障现象。\n"
    "原文常见段落标签：故障现象、处理经过、维修动作、结果验证、归档说明。\n"
    "规则：\n"
    "1) 只有原文给出明确结论时才填 root_cause；出现“怀疑/待查/暂未定位/等厂家/继续跟踪”时，\n"
    "   root_cause 必须为空串，has_final_root_cause=0。\n"
    "2) 原文明确排除的假设（“排除 X”“按 X 方向排查后无改善”）只能写入 excluded_hypotheses，\n"
    "   严禁写入 root_cause；排除项的 evidence 逐字摘自原文。\n"
    "3) verification 只取「结果验证」段（或复测/结果记录）里的结果值，如“温度稳定 85±2℃，连续 4 小时”；\n"
    "   **严禁把「维修动作」段（更换/调整/重新整定）当作 verification**；未验证则为空串。\n"
    "4) 数字与单位照抄原文，不换算、不编造。\n"
    "5) 只输出一个 JSON 对象：\n"
    '{"root_cause": "", "root_cause_evidence": "", "verification": "", '
    '"verification_evidence": "", "excluded_hypotheses": [{"hypothesis": "", "evidence": ""}], '
    '"has_final_root_cause": 0}'
)

STEP3_SYSTEM = (
    "你是设备维修工单知识抽取器。本次只执行第 3 步：抽取处理措施与适用条件。\n"
    "输入包含工单原文、已定位的现象、根因与验证。\n"
    "规则：\n"
    "1) measures 只写已执行的维修/调整动作；同一句中的并列动作保持为一个条目，不要拆条；\n"
    "   “先降速跑着/等厂家”这类临时处置不算措施。\n"
    "2) conditions 是「这条知识适用的条件」，取**故障发生时**的设备/工艺状态，不是维修后的目标值。\n"
    "   type 只能取 device_model/process_stage/material_or_batch/param_range/precondition；\n"
    "   只写原文明确出现或可直接推出的条件，禁止编造；没有条件输出空数组。\n"
    "3) 各类型取值口径：\n"
    "   - device_model：取「工单元数据-设备型号」或原文「设备：」行的型号（如 LAM-600、SIPLACE SX），\n"
    "     不写产线名，也不写「贴合机/贴片机/AOI 检测机」这类设备别名；\n"
    "   - param_range：故障发生时的参数与阈值（如 温度 65℃、两端压力 0.2MPa）；\n"
    "     **维修后调整到的目标值（如 调整到 85℃、压力改为 0.45MPa）不得写入**；\n"
    "     **「结果验证/复测」段里的验证值（如 稳定在 -78kPa 至 -82kPa）也不得写入**；\n"
    "   - process_stage：写工序/工步名称（如 0402 贴装、波峰焊、回流焊），\n"
    "     不写「取料后/贴合后/调整后」这类时序词；\n"
    "   - material_or_batch/precondition：只写原文明确给出的批次或前置条件。\n"
    "   禁止输出“未提及/无/不适用/未知”这类占位值。\n"
    "4) 只输出一个 JSON 对象：\n"
    '{"measures": ["..."], "conditions": [{"type": "device_model", "value": "..."}]}'
)

KEYS = {
    1: ["symptom", "symptom_evidence"],
    2: ["root_cause", "root_cause_evidence", "verification", "verification_evidence",
        "excluded_hypotheses", "has_final_root_cause"],
    3: ["measures", "conditions"],
}
_lock = threading.Lock()


def api_key(path):
    if os.environ.get("ZHIPU_API_KEY"):
        return os.environ["ZHIPU_API_KEY"].strip()
    return open(path, encoding="utf-8").read().strip()


def norm(s):
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    return "".join(ch for ch in s if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def dice(a, b):
    a, b = norm(a), norm(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    ga = Counter(a[i:i + 2] for i in range(max(1, len(a) - 1)))
    gb = Counter(b[i:i + 2] for i in range(max(1, len(b) - 1)))
    inter = sum((ga & gb).values())
    return 2.0 * inter / (sum(ga.values()) + sum(gb.values()))


def same(a, b):
    d = dice(a, b)
    if d >= 0.55:
        return True, d
    na, nb = norm(a), norm(b)
    if na and nb and (na in nb or nb in na) and min(len(na), len(nb)) / max(len(na), len(nb)) >= 0.6:
        return True, d
    return False, d


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
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    return None


def call(messages, key, retry=3):
    body = {"model": MODEL, "temperature": 0, "messages": messages}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last = None
    for a in range(retry):
        try:
            req = urllib.request.Request(GLM_URL, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", "Bearer " + key)
            with urllib.request.urlopen(req, timeout=90) as r:
                obj = json.loads(r.read().decode("utf-8"))
            return obj["choices"][0]["message"]["content"], None
        except Exception as e:  # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, str(e)[:200])
            time.sleep(2 * (a + 1))
    return None, last


# ---------------- 每步校验（生产侧同口径） ----------------
def validate_step1(obj, text):
    obj = obj if isinstance(obj, dict) else {}
    symptom = str(obj.get("symptom") or "").strip()
    evidence = str(obj.get("symptom_evidence") or "").strip()
    return {
        "symptom": symptom,
        "symptom_evidence": evidence,
        "evidence_grounded": int(bool(evidence) and (norm(evidence) in norm(text) or dice(evidence, text) >= 0.6)),
    }


def validate_step2(obj, text):
    obj = obj if isinstance(obj, dict) else {}
    rc = str(obj.get("root_cause") or "").strip()
    rce = str(obj.get("root_cause_evidence") or "").strip()
    ver = str(obj.get("verification") or "").strip()
    vere = str(obj.get("verification_evidence") or "").strip()
    excl = []
    for x in (obj.get("excluded_hypotheses") or []):
        if isinstance(x, dict):
            h, e = str(x.get("hypothesis") or "").strip(), str(x.get("evidence") or "").strip()
        else:
            h, e = str(x).strip(), ""
        if h:
            excl.append({"hypothesis": h, "evidence": e})
    # 根因若与某个排除假设等价 → 视为误用排除项，清空根因
    for x in excl:
        if rc and (norm(rc) in norm(x["hypothesis"]) or norm(x["hypothesis"]) in norm(rc)):
            rc = ""
            break
    has_final = 0 if not rc else 1
    return {
        "root_cause": rc,
        "root_cause_evidence": rce,
        "verification": ver,
        "verification_evidence": vere,
        "excluded_hypotheses": excl,
        "has_final_root_cause": has_final,
        "root_evidence_grounded": int(bool(rce) and (norm(rce) in norm(text) or dice(rce, text) >= 0.6)) if rce else 1,
        "verification_evidence_grounded": int(bool(vere) and (norm(vere) in norm(text) or dice(vere, text) >= 0.6)) if vere else 1,
    }


def validate_step3(obj):
    obj = obj if isinstance(obj, dict) else {}
    measures = [str(m).strip() for m in (obj.get("measures") or []) if str(m).strip()]
    conditions, seen = [], set()
    for c in (obj.get("conditions") or []):
        if not isinstance(c, dict):
            continue
        t, v = str(c.get("type") or "").strip(), str(c.get("value") or "").strip()
        if t in CONDITION_TYPES and v and v.lower() not in COND_PLACEHOLDERS and (t, v) not in seen:
            seen.add((t, v))
            conditions.append({"type": t, "value": v})
    invalid = len(obj.get("conditions") or []) - len(conditions)
    return {"measures": measures, "conditions": conditions,
            "invalid_conditions": max(0, invalid)}


def schema_ok(step, obj):
    return isinstance(obj, dict) and all(k in obj for k in KEYS[step])


# ---------------- run ----------------
def run_one(rec, key):
    text = rec["input"]["symptom_text"]
    meta = []
    if rec["input"].get("device_model"):
        meta.append("设备型号：%s" % rec["input"]["device_model"])
    if rec["input"].get("error_code"):
        meta.append("故障码：%s" % rec["input"]["error_code"])
    ctx = ("工单元数据：\n%s\n\n" % "\n".join(meta)) if meta else ""
    trace, errors = {}, []

    def step(no, system, user):
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        raw, err = call(msgs, key)
        obj = parse_json(raw)
        trace[str(no)] = {"raw": raw, "parsed": obj, "error": err,
                          "json_ok": int(obj is not None),
                          "schema_ok": int(schema_ok(no, obj))}
        if err or obj is None:
            errors.append("step%d:%s" % (no, err or "no_json"))
        return obj

    # 元数据只喂第 3 步：第 1/2 步必须贴近原文，混入元数据会削弱「以原文为准」的判定
    o1 = step(1, STEP1_SYSTEM, "工单原文：\n" + text)
    s1 = validate_step1(o1, text)

    o2 = step(2, STEP2_SYSTEM, "工单原文：\n%s\n\n第 1 步已定位现象：\n%s" % (text, s1["symptom"]))
    s2 = validate_step2(o2, text)

    o3 = step(3, STEP3_SYSTEM,
              ctx + "工单原文：\n%s\n\n已定位现象：%s\n根因：%s\n验证：%s"
              % (text, s1["symptom"], s2["root_cause"] or "（无最终根因）", s2["verification"] or "（未验证）"))
    s3 = validate_step3(o3)

    # 验证方式若与维修动作同源，视为把「维修动作」误当「结果验证」，清空并留痕
    if s2["verification"] and s3["measures"]:
        joined = "".join(s3["measures"])
        if norm(s2["verification"]) in norm(joined) or dice(s2["verification"], joined) >= 0.8:
            s2["verification"] = ""
            s2["verification_evidence"] = ""
            s2["ver_misattributed"] = 1

    merged = {}
    merged.update(s1)
    merged.update(s2)
    merged.update(s3)
    return {"id": rec["id"], "style": rec.get("style"), "structure": rec.get("structure"),
            "merged": merged, "trace": trace, "errors": errors}


def cmd_run(args):
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    recs = [json.loads(l) for l in open(args.heldout, encoding="utf-8") if l.strip()]
    if args.limit:
        recs = recs[:args.limit]
    done = set()
    if args.resume and os.path.exists(args.out):
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                done.add(json.loads(l)["id"])
        recs = [r for r in recs if r["id"] not in done]
    key = api_key(args.key)
    print("[chain] 待跑 %d 条（已完成 %d），每条 3 次调用，模型 %s" % (len(recs), len(done), MODEL), flush=True)
    t0 = time.time()
    with open(args.out, "a" if args.resume else "w", encoding="utf-8") as f, \
            ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, r, key): r["id"] for r in recs}
        for i, fut in enumerate(futures, 1):
            try:
                row = fut.result()
            except Exception as e:  # noqa: BLE001
                row = {"id": futures[fut], "merged": {}, "trace": {},
                       "errors": ["fatal:%s" % str(e)[:200]]}
            with _lock:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
            if i % 10 == 0 or i == len(futures):
                el = time.time() - t0
                print("[chain] %d/%d avg=%.1fs eta=%.1fmin" % (i, len(futures), el / i, el / i * (len(futures) - i) / 60),
                      flush=True)
    print("[done] -> %s total=%.1fmin" % (args.out, (time.time() - t0) / 60))


# ---------------- score ----------------
def item_f1(pred, gold, key=None):
    pred = [p for p in (pred or []) if str(p).strip()]
    gold = [g for g in (gold or []) if str(g).strip()]
    if not pred and not gold:
        return None, None, None, 0
    used, hit = set(), 0
    for g in gold:
        gv = g.get(key, "") if isinstance(g, dict) else g
        best, bi = 0.0, -1
        for j, p in enumerate(pred):
            if j in used:
                continue
            pv = p.get(key, "") if isinstance(p, dict) else p
            d = dice(pv, gv)
            if d > best:
                best, bi = d, j
        if best >= 0.5 and bi >= 0:
            used.add(bi)
            hit += 1
    p = hit / len(pred) if pred else 0.0
    r = hit / len(gold) if gold else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f, hit


def cond_match(pred, gold):
    """同类型下按值做包含/近似匹配：模型常把型号写成「产线/设备/型号」全串。"""
    gp = [(c.get("type", ""), c.get("value", "")) for c in (gold or [])]
    pp = [(c.get("type", ""), c.get("value", "")) for c in (pred or [])]
    used, tp = set(), 0
    for gt, gv in gp:
        best, bi = 0.0, -1
        for j, (pt, pv) in enumerate(pp):
            if j in used or pt != gt:
                continue
            d = dice(pv, gv)
            ng, npv = norm(gv), norm(pv)
            if ng and ng in npv:
                d = max(d, 0.95)
            if d > best:
                best, bi = d, j
        if best >= 0.6 and bi >= 0:
            used.add(bi)
            tp += 1
    prec = tp / len(pp) if pp else (1.0 if not gp else 0.0)
    rec = tp / len(gp) if gp else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1


def score(args):
    preds = {}
    for l in open(args.pred, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            preds[r["id"]] = r
    golds = {r["id"]: r for r in (json.loads(l) for l in open(args.heldout, encoding="utf-8") if l.strip())}
    rows = []
    for rid, g in golds.items():
        p = preds.get(rid, {}).get("merged") or {}
        gold = g["gold"]
        row = {"id": rid, "style": g.get("style"), "structure": g.get("structure"),
               "step_json_ok": int(sum(1 for s in (preds.get(rid, {}).get("trace") or {}).values() if s.get("json_ok"))),
               "step_schema_ok": int(sum(1 for s in (preds.get(rid, {}).get("trace") or {}).values() if s.get("schema_ok")))}
        ok, d = same(p.get("symptom", ""), gold.get("symptom", ""))
        row["sym_match"], row["sym_dice"] = int(ok), round(d, 3)
        ok, d = same(p.get("root_cause", ""), gold.get("root_cause", ""))
        row["root_match"], row["root_dice"] = int(ok), round(d, 3)
        row["root_false_fill"] = int(bool(p.get("root_cause")) and int(gold.get("has_final_root_cause", 1)) == 0)
        ok, d = same(p.get("verification", ""), gold.get("verification", ""))
        row["ver_match"], row["ver_dice"] = int(ok), round(d, 3)
        mp, mr, mf, _ = item_f1(p.get("measures"), gold.get("measures"))
        row["meas_p"], row["meas_r"], row["meas_f1"] = mp, mr, mf
        cp, cr, cf = cond_match(p.get("conditions"), gold.get("conditions"))
        row["cond_p"], row["cond_r"], row["cond_f1"] = round(cp, 3), round(cr, 3), round(cf, 3)
        ep, er, ef, eh = item_f1(p.get("excluded_hypotheses"), gold.get("excluded_hypotheses"), key="hypothesis")
        row["excl_p"], row["excl_r"], row["excl_f1"] = ep, er, ef
        row["excl_hit"] = eh
        row["excl_gold_n"] = len(gold.get("excluded_hypotheses") or [])
        row["excl_pred_n"] = len(p.get("excluded_hypotheses") or [])
        row["excl_detected"] = int(row["excl_gold_n"] > 0 and row["excl_pred_n"] > 0)
        row["evidence_grounded"] = int(bool(p.get("evidence_grounded", 0)))
        row["root_evidence_grounded"] = int(bool(p.get("root_evidence_grounded", 0)))
        rows.append(row)

    def avg(key):
        v = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(v) / len(v), 3) if v else None

    def rate(key):
        v = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(v) / len(v) * 100, 1) if v else None

    gp = [r for r in rows if r["excl_gold_n"] > 0]
    overall = {
        "n": len(rows),
        # 每步 JSON/字段完整率：单条满分 3 步，按 3 步归一化
        "step_json_ok": round(sum(r["step_json_ok"] for r in rows) / (len(rows) * 3) * 100, 1),
        "step_schema_ok": round(sum(r["step_schema_ok"] for r in rows) / (len(rows) * 3) * 100, 1),
        "symptom_match": rate("sym_match"), "symptom_dice_mean": avg("sym_dice"),
        "root_match": rate("root_match"), "root_dice_mean": avg("root_dice"),
        "root_false_fill": rate("root_false_fill"),
        "verification_match": rate("ver_match"), "verification_dice_mean": avg("ver_dice"),
        "meas_f1": avg("meas_f1"), "meas_p": avg("meas_p"), "meas_r": avg("meas_r"),
        "cond_f1": avg("cond_f1"), "cond_p": avg("cond_p"), "cond_r": avg("cond_r"),
        # excl_detect 只在「原文确有排除假设」的子集上算（与 S3 score_eval.py 同口径），分母不是 200
        "excl_detect": (round(sum(r["excl_detected"] for r in gp) / len(gp) * 100, 1) if gp else None),
        "excl_base_rate": round(len(gp) / len(rows) * 100, 1),
        "excl_gold_samples": len(gp),
        "excl_gold_items": sum(r["excl_gold_n"] for r in rows),
        "excl_pred_items": sum(r["excl_pred_n"] for r in rows),
        "excl_tp": sum(r["excl_hit"] for r in rows),
        "excl_fp": sum(r["excl_pred_n"] - r["excl_hit"] for r in rows),
        "excl_fn": sum(r["excl_gold_n"] - r["excl_hit"] for r in rows),
        "excl_f1": avg("excl_f1"),
        "evidence_grounded": rate("evidence_grounded"),
        "root_evidence_grounded": rate("root_evidence_grounded"),
    }
    out = {"all": overall}
    for s in ("dispatch", "wechat", "logbook"):
        sub = [r for r in rows if r.get("style") == s]
        if not sub:
            continue
        out[s] = {
            "n": len(sub),
            "root_match": round(sum(r["root_match"] for r in sub) / len(sub) * 100, 1),
            "root_dice_mean": round(sum(r["root_dice"] for r in sub) / len(sub), 3),
            "meas_f1": round(sum(r["meas_f1"] for r in sub if r["meas_f1"] is not None) /
                             max(1, len([r for r in sub if r["meas_f1"] is not None])), 3),
            "cond_f1": round(sum(r["cond_f1"] for r in sub) / len(sub), 3),
        }
    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    write_chain_report(out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("[score] -> %s" % args.out_json)


def write_chain_report(out):
    a = out["all"]
    lines = ["# 五元组链式抽取评测（P0）", "",
             "> 数据：`_heldout_eval_input.jsonl` 200 条留出集；真值为 construction-based gold（生成时确定，弱监督），"
             "**不是人工标注**。",
             "> 模型：glm-4-flash，三步链式调用（现象 → 根因/验证 → 措施/条件），temperature=0。", "",
             "## 总体指标", "",
             "| 指标 | 数值 |", "|---|---:|",
             "| 样本数 | %d |" % a["n"],
             "| 三步 JSON 解析成功率 | %.1f%% |" % a["step_json_ok"],
             "| 三步字段完整率 | %.1f%% |" % a["step_schema_ok"],
             "| 现象匹配率 | %.1f%% |" % a["symptom_match"],
             "| 根因匹配率 | %.1f%% |" % a["root_match"],
             "| 根因平均 dice | %.3f |" % a["root_dice_mean"],
             "| 无根因工单误填率 | %.1f%% |" % a["root_false_fill"],
             "| 验证方式匹配率 | %.1f%% |" % a["verification_match"],
             "| 验证方式平均 dice | %.3f |" % a["verification_dice_mean"],
             "| 措施条目 F1 | %.3f |" % a["meas_f1"],
             "| 适用条件 F1（同类型近似匹配） | %.3f |" % a["cond_f1"],
             "| 排除假设：含该字段的样本 | %d / %d（%.1f%%） |" % (a["excl_gold_samples"], a["n"], a["excl_base_rate"]),
             "| 排除假设样本检出率（gold>0 子集） | %.1f%% |" % (a["excl_detect"] or 0.0),
             "| 排除假设条目 TP / FP / FN | %d / %d / %d |" % (a["excl_tp"], a["excl_fp"], a["excl_fn"]),
             "| 排除假设条目 micro P / R / F1 | %.3f / %.3f / %.3f |" % (
                 a["excl_tp"] / max(1, a["excl_tp"] + a["excl_fp"]),
                 a["excl_tp"] / max(1, a["excl_tp"] + a["excl_fn"]),
                 2.0 * a["excl_tp"] / max(1, 2 * a["excl_tp"] + a["excl_fp"] + a["excl_fn"])),
             "| 排除假设样本宏平均 F1 | %.3f |" % (a["excl_f1"] or 0.0),
             "| 证据原文可回溯率 | %.1f%% |" % a["evidence_grounded"],
             "| 根因证据可回溯率 | %.1f%% |" % a["root_evidence_grounded"], "",
             "## 分模板风格", "",
             "| 风格 | n | 根因匹配率 | 根因 dice | 措施 F1 | 条件 F1 |", "|---|---:|---:|---:|---:|---:|"]
    for s in ("dispatch", "wechat", "logbook"):
        if s not in out:
            continue
        v = out[s]
        lines.append("| %s | %d | %.1f%% | %.3f | %.3f | %.3f |" % (
            s, v["n"], v["root_match"], v["root_dice_mean"], v["meas_f1"], v["cond_f1"]))
    lines += ["", "## 口径说明", "",
              "- 现象/根因/验证：dice≥0.55 或包含关系（短串占比≥0.6）记匹配。",
              "- 措施：条目级贪心匹配，dice≥0.5 记命中，汇总为微平均 P/R/F1。",
              "- 适用条件：同 type 下值做包含/近似匹配（dice≥0.6），避免「LAM-600」与「3 号线贴合机 / LAM-600」被判错。",
              "- 排除假设三种口径不可混用：① 样本检出率分母是「原文确有排除假设」的 %d 条，不是全部 %d 条；② 条目 micro P/R/F1 的分子分母是条目数（TP/FP/FN）；③ 样本宏平均 F1 的分母是「任一侧非空」的样本，纯 FP 样本按 0 计入。" % (a["excl_gold_samples"], a["n"]),
              "- 无最终根因的工单若抽出根因，计入「误填率」；验证方式与维修动作同源时按误归因清空并留痕。", "",
              "## 局限", "",
              "1. 真值为构造真值，非人工标注；指标是与构造真值的一致性，不能表述为人工标注准确率。",
              "2. 留出集为模板合成语料，长度与段落标签较规整，真实工单的口语化与信息缺失会进一步拉低指标。",
              "3. 验证方式与适用条件在构造真值里本身较短，抽取粒度差异会放大字面指标误差。",
              "4. 仅用 glm-4-flash 单模型、单次采样，未做多次采样方差估计。", ""]
    os.makedirs(CHAIN_DIR, exist_ok=True)
    with open(os.path.join(CHAIN_DIR, "链式抽取评测.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------- prompts ----------------
def cmd_prompts(args):
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    md = ["# 五元组链式抽取 Prompt（三步）", "",
          "> 用途：离线验证与 Java 侧逐字移植来源。每步单独返回 JSON，便于逐步校验与人工复核。",
          "> 口径：construction-based gold 对齐；不含标题/标签等现网展示字段。", "",
          "## Step 1 现象定位", "", "```text", STEP1_SYSTEM, "```", "",
          "## Step 2 根因与验证", "", "```text", STEP2_SYSTEM, "```", "",
          "## Step 3 措施与适用条件", "", "```text", STEP3_SYSTEM, "```", "",
          "## 步骤间传递", "",
          "- 「工单元数据：设备型号 / 故障码」只随第 3 步输入提供（第 1/2 步只读原文）；正文未出现型号时以元数据为准。",
          "- Step 2 的输入 = 工单原文 + Step 1 的 `symptom`。",
          "- Step 3 的输入 = 工单原文 + `symptom` + `root_cause`（无则标注「无最终根因」）+ `verification`。",
          "- 任一步 JSON 解析失败：该步字段置空并记录 `trace.error`，不阻塞后续步骤（降级而非重跑整链）。", ""]
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("[prompts] -> %s" % args.out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prompts")
    p.add_argument("--out", default=os.path.join(CHAIN_DIR, "prompts.md"))
    p.set_defaults(func=cmd_prompts)

    p = sub.add_parser("run")
    p.add_argument("--heldout", default=HELDOUT)
    p.add_argument("--out", default=os.path.join(CHAIN_DIR, "pred_chain.jsonl"))
    p.add_argument("--key", default=KEY_PATH)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--resume", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("score")
    p.add_argument("--heldout", default=HELDOUT)
    p.add_argument("--pred", default=os.path.join(CHAIN_DIR, "pred_chain.jsonl"))
    p.add_argument("--out-json", default=os.path.join(CHAIN_DIR, "metrics.json"))
    p.set_defaults(func=score)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
