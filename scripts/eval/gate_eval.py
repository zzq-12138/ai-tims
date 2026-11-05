#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门控落地后的真实基线（B0）采集与汇总。

子命令：
  lg-before-backup  把清理前的 LG 结果另存（只做一次）
  collect <tag>     采集 P/N 在 HYBRID、VECTOR 两模式下的真实返回（tag=raw 门控关闭 / live 门控开启）
  lg                重跑 leave-gold-out（需门控关闭，以便拿到原始 top1）
  summarize         汇总 B0 指标 + 0.70/0.75/0.78/0.80/0.85 阈值曲线
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from statistics import median

REPO = "/home/dev/ai-tims"
DOCS = REPO + "/docs/paper/评测"
BASE = os.environ.get("KB_BASE", "http://127.0.0.1:8103")
THRESHOLDS = (0.70, 0.75, 0.78, 0.80, 0.85)


def api(query, mode, top_k=5, timeout=30):
    url = BASE + "/api/kb/search?" + urllib.parse.urlencode(
        {"query": query, "mode": mode, "topK": top_k})
    t0 = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as r:
        body = json.load(r)
    return body["data"], round((time.perf_counter() - t0) * 1000.0, 1)


def load_eval():
    rows = []
    with open(DOCS + "/eval_set.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({"query": r["query"], "expected": [x for x in r["expectedIds"].split(";") if x],
                         "device": r["deviceType"], "note": r["note"]})
    return rows


def load_neg():
    rows = []
    with open(DOCS + "/negative_set.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({"id": r["id"], "cls": r["class"], "query": r["query"],
                         "usable": [x for x in r["usableIds"].split(";") if x]})
    return rows


def summarize_resp(d, ms):
    items = d.get("items") or []
    return {
        "tier": d.get("tier"),
        "reason": d.get("reason"),
        "maxVectorScore": d.get("maxVectorScore"),
        "fallback": d.get("fallback"),
        "ms": ms,
        "items": [{"id": str(x["id"]), "score": x.get("score"),
                   "vectorScore": x.get("vectorScore")} for x in items],
    }


def collect(tag):
    out = {}
    for mode in ("HYBRID", "VECTOR"):
        p_rows, n_rows = [], []
        for i, r in enumerate(load_eval(), 1):
            d, ms = api(r["query"], mode)
            rec = summarize_resp(d, ms)
            rec.update({"key": "P-%03d" % i, "query": r["query"], "expected": r["expected"], "note": r["note"]})
            p_rows.append(rec)
            if i % 20 == 0:
                print("  [%s] P %d/100" % (mode, i), flush=True)
        for r in load_neg():
            d, ms = api(r["query"], mode)
            rec = summarize_resp(d, ms)
            rec.update({"key": r["id"], "query": r["query"], "cls": r["cls"], "usable": r["usable"]})
            n_rows.append(rec)
        out[mode] = {"P": p_rows, "N": n_rows}
        print("  [%s] done P=%d N=%d" % (mode, len(p_rows), len(n_rows)), flush=True)
    path = "%s/_gate_%s.json" % (DOCS, tag)
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[ok] ->", path)


def lg():
    before = DOCS + "/_leave_out.tsv"
    bak = DOCS + "/_leave_out_before_cleanup.tsv"
    if os.path.exists(before) and not os.path.exists(bak):
        subprocess.run(["cp", before, bak], check=True)
        print("[ok] 清理前 LG 结果已另存:", bak)
    inp = DOCS + "/_gate_lg_in.tsv"
    with open(inp, "w", encoding="utf-8") as f:
        f.write("idx\tquery\tgoldIds\n")
        for i, r in enumerate(load_eval(), 1):
            f.write("%d\t%s\t%s\n" % (i, r["query"], ",".join(r["expected"])))
    outp = DOCS + "/_leave_out_after_cleanup.tsv"
    env = dict(os.environ)
    subprocess.run(["bash", REPO + "/scripts/eval/leave_gold_out.sh", inp, outp], check=True, env=env)
    print("[ok] LG after cleanup ->", outp)


def pctl(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def by_threshold(p, n, lg_rows, t):
    """按阈值 t 计算一次门控的指标（maxVectorScore 口径，等价于线上 tier C 判据）。"""
    p_push = [x for x in p if (x["maxVectorScore"] or 0) >= t]
    p_ok = [x for x in p_push if x["items"] and x["items"][0]["id"] in x["expected"]]
    n_push = [x for x in n if (x["maxVectorScore"] or 0) >= t]
    n_err = [x for x in n_push
             if not (x["cls"] == "missing_noise" and x["items"] and x["items"][0]["id"] in x["usable"])]
    lg_push = [x for x in lg_rows if (x.get("maxVectorScore") or 0) >= t]
    return {
        "T": t,
        "P_push": len(p_push), "P_rate": round(len(p_push) / len(p), 4),
        "P_correct": len(p_ok), "P_err": len(p_push) - len(p_ok),
        "A_acc": round(len(p_ok) / len(p_push), 4) if p_push else None,
        "A_recall": round(len(p_ok) / len(p), 4),
        "N_push": len(n_push), "N_err": len(n_err),
        "N_err_rate": round(len(n_err) / len(n_push), 4) if n_push else None,
        "LG_push": len(lg_push), "LG_err_rate": 1.0 if lg_push else None,
        "C_rate": round(1 - (len(p_push) + len(n_push) + len(lg_push)) / (len(p) + len(n) + len(lg_rows)), 4),
        "mix_push": len(p_push) + len(n_push) + len(lg_push),
        "mix_err": (len(p_push) - len(p_ok)) + len(n_err) + len(lg_push),
        "mix_err_rate": round(((len(p_push) - len(p_ok)) + len(n_err) + len(lg_push))
                              / (len(p_push) + len(n_push) + len(lg_push)), 4)
        if (len(p_push) + len(n_push) + len(lg_push)) else None,
    }


def read_lg(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("idx") or line.startswith("#") or not line.strip():
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 6:
                continue
            rows.append({"idx": p[0], "top1_score": float(p[3]) if p[3] != "NA" else None,
                         "top1_id": p[4], "fallback": p[5] == "true",
                         "maxVectorScore": float(p[3]) if p[3] != "NA" else None})
    return rows


def summarize():
    raw = json.load(open(DOCS + "/_gate_raw.json", encoding="utf-8"))
    live = json.load(open(DOCS + "/_gate_live.json", encoding="utf-8"))
    lg_after = read_lg(DOCS + "/_leave_out_after_cleanup.tsv")
    lg_before = read_lg(DOCS + "/_leave_out_before_cleanup.tsv")
    result = {"threshold_curve": {}, "live_075": {}, "lg": {}}

    for mode in ("HYBRID", "VECTOR"):
        p, n = raw[mode]["P"], raw[mode]["N"]
        result["threshold_curve"][mode] = [by_threshold(p, n, lg_after, t) for t in THRESHOLDS]

        lv = live[mode]
        lp, ln = lv["P"], lv["N"]
        tiers = {}
        for x in lp + ln:
            tiers[x["tier"]] = tiers.get(x["tier"], 0) + 1
        pushed_p = [x for x in lp if x["tier"] in ("A", "B")]
        pushed_n = [x for x in ln if x["tier"] in ("A", "B")]
        a_only = [x for x in lp if x["tier"] == "A"]
        ok_a = [x for x in a_only if x["items"] and x["items"][0]["id"] in x["expected"]]
        ok_push = [x for x in pushed_p if x["items"] and x["items"][0]["id"] in x["expected"]]
        n_err = [x for x in pushed_n
                 if not (x["cls"] == "missing_noise" and x["items"] and x["items"][0]["id"] in x["usable"])]
        lat = [x["ms"] for x in lp + ln]
        lg_live = [x for x in lg_after if (x["maxVectorScore"] or 0) >= 0.75]
        result["live_075"][mode] = {
            "tier_dist": tiers,
            "P_push": len(pushed_p), "P_push_rate": round(len(pushed_p) / len(lp), 4),
            "P_err_in_push": len(pushed_p) - len(ok_push),
            "A_acc": round(len(ok_a) / len(a_only), 4) if a_only else None,
            "A_count": len(a_only),
            "push_acc": round(len(ok_push) / len(pushed_p), 4) if pushed_p else None,
            "N_push": len(pushed_n), "N_push_rate": round(len(pushed_n) / len(ln), 4),
            "N_err": len(n_err), "N_err_rate": round(len(n_err) / len(pushed_n), 4) if pushed_n else None,
            "C_rate_all": round(1 - (len(pushed_p) + len(pushed_n) + len(lg_live)) / 300, 4),
            "LG_push": len(lg_live), "LG_err_rate": 1.0 if lg_live else None,
            "mix_push": len(pushed_p) + len(pushed_n) + len(lg_live),
            "mix_err": (len(pushed_p) - len(ok_push)) + len(n_err) + len(lg_live),
            "mix_err_rate": round(((len(pushed_p) - len(ok_push)) + len(n_err) + len(lg_live))
                                  / (len(pushed_p) + len(pushed_n) + len(lg_live)), 4)
            if (len(pushed_p) + len(pushed_n) + len(lg_live)) else None,
            "P50": pctl(lat, 50), "P95": pctl(lat, 95), "P99": pctl(lat, 99), "mean": round(sum(lat) / len(lat), 1),
            "fallback_count": sum(1 for x in lp + ln if x["fallback"]),
            "maxvec_median_P": median([x["maxVectorScore"] for x in lp if x["maxVectorScore"] is not None]),
        }
        # 门控一致性：离线按 maxVectorScore 判定 与 线上 tier 是否一致
        mism = 0
        for x in lp + ln:
            pred = "C" if (x["maxVectorScore"] or 0) < 0.75 else ("B" if (x["maxVectorScore"] or 0) < 0.82 else "A")
            if pred != x["tier"]:
                mism += 1
        result["live_075"][mode]["offline_vs_live_mismatch"] = mism

    def lg_block(rows, label):
        push = [x for x in rows if (x["maxVectorScore"] or 0) >= 0.75]
        return {"label": label, "n": len(rows),
                "push_at_075": len(push),
                "top1_ids": [x["top1_id"] for x in push],
                "med": round(median([x["maxVectorScore"] for x in rows if x["maxVectorScore"] is not None]), 4)
                if rows else None}

    result["lg"] = {"before": lg_block(lg_before, "清理前"), "after": lg_block(lg_after, "清理后")}
    json.dump(result, open(DOCS + "/_gate_metrics.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n=== 阈值曲线（基于真实 vectorScore，离线复算） ===")
    print("| 模式 | T | 正例推送 | 推送率 | 正例错误 | A档准确率 | A档召回 | 负例推送 | 负例错误 | 负例错误率 | LG推送 | 混合错误率 |")
    for mode in ("HYBRID", "VECTOR"):
        for m in result["threshold_curve"][mode]:
            print("| %s | %.2f | %d/100 | %.1f%% | %d | %s | %.1f%% | %d | %d | %s | %d | %s |"
                  % (mode, m["T"], m["P_push"], m["P_rate"] * 100, m["P_err"],
                     ("%.1f%%" % (m["A_acc"] * 100)) if m["A_acc"] is not None else "-",
                     m["A_recall"] * 100, m["N_push"], m["N_err"],
                     ("%.1f%%" % (m["N_err_rate"] * 100)) if m["N_err_rate"] is not None else "-",
                     m["LG_push"],
                     ("%.1f%%" % (m["mix_err_rate"] * 100)) if m["mix_err_rate"] is not None else "-"))
    print("\n=== 门控开启实测（T=0.75, soft-band=0.07） ===")
    for mode in ("HYBRID", "VECTOR"):
        print(mode, json.dumps(result["live_075"][mode], ensure_ascii=False))
    print("\n=== LG 清理前后 ===")
    print(json.dumps(result["lg"], ensure_ascii=False))
    print("\n[ok] ->", DOCS + "/_gate_metrics.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "lg", "summarize"])
    ap.add_argument("tag", nargs="?", default="raw")
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.tag)
    elif a.cmd == "lg":
        lg()
    else:
        summarize()
