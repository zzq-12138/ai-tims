#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1(base) / S3(lora) 在 heldout 200 条上的分字段、分模板评分。

判等口径（写进报告，避免"黑箱语义判等"）：
- 归一化：NFKC + 小写 + 仅保留中英文/数字。
- 相似度：字符 bigram Dice 系数。
- 标量字段判等：dice>=0.55，或一方包含另一方且长度比>=0.6。
- measures / excluded_hypotheses：条目级一对一贪心匹配（dice>=0.5 记命中），算 P/R/F1。
"""
import csv
import json
import re
import sys
import unicodedata
from collections import Counter

IN = "/home/dev/ai-tims/docs/paper/问题二/_heldout_eval_input.jsonl"
GOLD = {json.loads(l)["id"]: json.loads(l) for l in open(IN, encoding="utf-8") if l.strip()}
KEYS14 = ["symptom", "symptom_evidence", "root_cause", "root_cause_evidence", "measures",
          "verification", "verification_evidence", "conditions", "excluded_hypotheses",
          "is_excluded_hypothesis", "unverified_hypotheses", "has_final_root_cause", "uncertain", "note"]
STYLES = ["dispatch", "wechat", "logbook"]


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
        return None, "empty"
    s = raw.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    for i, ch in enumerate(s):
        if ch == "{":
            try:
                obj, _ = json.JSONDecoder().raw_decode(s[i:])
                if isinstance(obj, dict):
                    return obj, None
            except json.JSONDecodeError:
                continue
    return None, "no_json"


def item_f1(pred, gold):
    pred = [p for p in (pred or []) if str(p).strip()]
    gold = [g for g in (gold or []) if str(g).strip()]
    if not pred and not gold:
        return None, None, None
    used = set()
    hit = 0
    for g in gold:
        best, bi = 0.0, -1
        for j, p in enumerate(pred):
            if j in used:
                continue
            text = p.get("hypothesis", "") if isinstance(p, dict) else p
            d = dice(text, g.get("hypothesis", "") if isinstance(g, dict) else g)
            if d > best:
                best, bi = d, j
        if best >= 0.5 and bi >= 0:
            used.add(bi)
            hit += 1
    p = hit / len(pred) if pred else 0.0
    r = hit / len(gold) if gold else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def evaluate(path):
    preds = {}
    for l in open(path, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            preds[r["id"]] = r
    rows = []
    for rid, g in GOLD.items():
        p = preds.get(rid, {})
        obj, perr = parse_json(p.get("raw"))
        gold = g["gold"]
        row = {"id": rid, "style": g["style"], "structure": g["structure"],
               "json_ok": int(obj is not None), "err": perr or p.get("error") or "",
               "fields_ok": int(obj is not None and all(k in obj for k in KEYS14)),
               "gen_s": p.get("gen_s")}
        if obj:
            ok, d = same(obj.get("root_cause", ""), gold.get("root_cause", ""))
            row["root_match"] = int(ok)
            row["root_dice"] = round(d, 3)
            row["root_exact"] = int(norm(obj.get("root_cause")) == norm(gold.get("root_cause")))
            mp, mr, mf = item_f1(obj.get("measures"), gold.get("measures"))
            row["meas_p"], row["meas_r"], row["meas_f1"] = mp, mr, mf
            ep, er, ef = item_f1(obj.get("excluded_hypotheses"), gold.get("excluded_hypotheses"))
            row["excl_p"], row["excl_r"], row["excl_f1"] = ep, er, ef
            gp = [x for x in (gold.get("excluded_hypotheses") or []) if str(x).strip()]
            pp = [x for x in (obj.get("excluded_hypotheses") or []) if str(x).strip()]
            row["excl_gold_n"] = len(gp)
            row["excl_pred_n"] = len(pp)
            row["excl_detected"] = int(bool(gp) and bool(pp))
            mis = 0
            if gp:
                rc = obj.get("root_cause", "")
                for x in gp:
                    t = x.get("hypothesis", "") if isinstance(x, dict) else x
                    if t and same(rc, t)[0]:
                        mis = 1
                        break
            row["excl_misattrib"] = mis
        else:
            row.update({"root_match": 0, "root_dice": 0.0, "root_exact": 0,
                        "meas_p": None, "meas_r": None, "meas_f1": None,
                        "excl_p": None, "excl_r": None, "excl_f1": None,
                        "excl_gold_n": len(gold.get("excluded_hypotheses") or []),
                        "excl_pred_n": 0, "excl_detected": 0, "excl_misattrib": 0})
        rows.append(row)
    return rows


def agg(rows):
    def rate(key):
        v = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(v) / len(v) * 100, 1) if v else None

    def avgf(key):
        v = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(v) / len(v), 3) if v else None

    gp = [r for r in rows if r["excl_gold_n"] > 0]
    return {
        "n": len(rows),
        "json_valid": rate("json_ok"),
        "fields_complete": rate("fields_ok"),
        "root_match": rate("root_match"),
        "root_exact": rate("root_exact"),
        "root_dice_mean": round(sum(r["root_dice"] for r in rows) / len(rows), 3),
        "meas_f1": avgf("meas_f1"),
        "meas_p": avgf("meas_p"),
        "meas_r": avgf("meas_r"),
        "excl_detect": round(sum(r["excl_detected"] for r in gp) / len(gp) * 100, 1) if gp else None,
        "excl_f1": avgf("excl_f1"),
        "excl_misattr": round(sum(r["excl_misattrib"] for r in gp) / len(gp) * 100, 1) if gp else None,
        "excl_gold_n": len(gp),
    }


if __name__ == "__main__":
    out = {}
    pairs = [("S1_base", sys.argv[1]), ("S3_lora", sys.argv[2])]
    if len(sys.argv) > 3:
        pairs.insert(1, ("S2_rules", sys.argv[3]))
    for tag, path in pairs:
        rows = evaluate(path)
        out[tag] = {"all": agg(rows)}
        for s in STYLES:
            sub = [r for r in rows if r["style"] == s]
            out[tag][s] = agg(sub) if sub else None
        with open("/tmp/rows_%s.csv" % tag, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        out[tag]["rows_file"] = "/tmp/rows_%s.csv" % tag
    print(json.dumps(out, ensure_ascii=False, indent=2))
