#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0.75/0.85/0.92 余弦阈值错误推送率评估（M7 追加任务）。

数据来源（全部真实调用，不构造分数）：
- 正例：docs/paper/评测/eval_set.csv 100 条，取 VECTOR 检索 top1 余弦；
- leave-gold-out：同样 100 条，逐条把 gold 从 Milvus 临时删除（scripts/eval/LeaveGoldOut.java），
  再走同一 VECTOR 接口取 top1 余弦，随后按主键恢复并校验条数；
- 负例：docs/paper/评测/negative_set.csv 100 条（四类各 25），取 VECTOR top1 余弦。

判定：top1 余弦 >= 阈值 => “系统会推送”。
可用性：
- 正例：top1 ∈ expectedIds；
- leave-gold-out：按构造不可用（gold 已删除）；额外标记 top1 是否为测试遗留重复条目；
- 负例 N1/N2/N3：按构造不可用；N4（缺字段/噪声）：top1 ∈ 原始 gold 才计可用（保守口径）。

用法: python3 threshold_eval.py [--out docs/paper/评测] [--skip-collect]
"""
import argparse
import csv
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from collections import OrderedDict

BASE = os.environ.get("KB_BASE", "http://127.0.0.1:8103")
THRESHOLDS = (0.75, 0.85, 0.92)
CLASS_CN = {
    "same_symptom_diff_cause": "同象异因",
    "out_of_domain": "领域外",
    "same_cause_diff_symptom": "同因异象",
    "missing_noise": "缺字段/噪声",
}


def http_get(path, params, timeout=20, attempts=30, wait=5):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    last = None
    for _ in range(attempts):
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(url, timeout=timeout) as r:
                body = json.load(r)
            return body["data"], (time.perf_counter() - t0) * 1000.0
        except Exception as e:
            last = e
            time.sleep(wait)
    raise last


def vector_top(query, top_k=5):
    d, ms = http_get("/api/kb/search", {"query": query, "mode": "VECTOR", "topK": top_k})
    if d.get("fallback"):
        raise SystemExit("VECTOR 检索降级（fallback=true），Milvus 未就绪，评估中止")
    items = d.get("items") or []
    return {
        "top1_score": round(float(items[0]["score"]), 4) if items else None,
        "top1_id": str(items[0]["id"]) if items else "NA",
        "top1_title": items[0].get("title") if items else "NA",
        "top5": [{"id": str(x["id"]), "score": round(float(x["score"]), 4),
                  "title": x.get("title")} for x in items],
        "ms": round(ms, 1),
    }


def load_kb(path):
    kb = json.load(open(path, encoding="utf-8"))
    return {str(x["id"]): x for x in kb}


def collect_original(queries, cache_file):
    """queries: list of (key, text)。逐条取 VECTOR top1，断点缓存。"""
    cache = json.load(open(cache_file, encoding="utf-8")) if os.path.exists(cache_file) else {}
    for i, (key, text) in enumerate(queries):
        if key in cache:
            continue
        cache[key] = vector_top(text)
        if (i + 1) % 10 == 0:
            json.dump(cache, open(cache_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("  采集", i + 1, "/", len(queries))
    json.dump(cache, open(cache_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return cache


def run_leave_gold_out(eval_rows, out_dir, leave_script, java_out):
    tsv = os.path.abspath(os.path.join(out_dir, "_leave_in.tsv"))
    java_out = os.path.abspath(java_out)
    with open(tsv, "w", encoding="utf-8") as f:
        for i, r in enumerate(eval_rows, 1):
            ids = r["expectedIds"].replace(";", ",")
            f.write(f"{i}\t{r['query']}\t{ids}\n")
    subprocess.run(["bash", os.path.abspath(leave_script), tsv, java_out], check=True)
    rows, n0, n1 = {}, None, None
    with open(java_out, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#N0"):
                n0 = int(line.split("\t")[1])
                continue
            if line.startswith("#N1"):
                n1 = int(line.split("\t")[1])
                continue
            if line.startswith("idx\t") or not line.strip():
                continue
            p = line.split("\t")
            idx = int(p[0])
            rows[idx] = {"gold_removed": p[1], "status": p[2],
                         "top1_score": None if p[3] == "NA" else round(float(p[3]), 4),
                         "top1_id": p[4], "fallback": p[5], "top5": p[6]}
    return rows, n0, n1


def usable_of(row, set_name, top1_id):
    if set_name == "P":
        return top1_id in row["expected"]
    if set_name == "LG":
        return False
    # 负例
    if row.get("class") == "missing_noise":
        return top1_id in row.get("usableIds", [])
    return False


def push_flags(score, usable):
    out = {}
    for t in THRESHOLDS:
        pushed = score is not None and score >= t
        out[f"push@{t}"] = int(pushed)
        out[f"error@{t}"] = int(pushed and not usable)
    return out


def summarize(rows, title, positive=False):
    """rows: 已带 score/usable 的样本。返回三阈值指标。"""
    res = OrderedDict()
    for t in THRESHOLDS:
        pushed = [r for r in rows if r["score"] is not None and r["score"] >= t]
        errors = [r for r in pushed if not r["usable"]]
        res[t] = {
            "推送量": len(pushed),
            "样本量": len(rows),
            "覆盖率/推送率": round(len(pushed) / len(rows) * 100, 1) if rows else 0.0,
            "错误推送率": round(len(errors) / len(pushed) * 100, 1) if pushed else 0.0,
            "错误推送量": len(errors),
            "A档准确率": round(sum(1 for r in pushed if r["correct_top1"]) / len(pushed) * 100, 1)
            if pushed and positive else None,
            "A档召回": round(sum(1 for r in pushed if r["correct_top1"]) / len(rows) * 100, 1)
            if positive and rows else None,
        }
    return {"title": title, "metrics": res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/paper/评测")
    ap.add_argument("--eval", default=None)
    ap.add_argument("--neg", default=None)
    ap.add_argument("--kb", default="/tmp/kb_dump.json")
    ap.add_argument("--leave-script", default="scripts/eval/leave_gold_out.sh")
    ap.add_argument("--skip-collect", action="store_true")
    args = ap.parse_args()
    args.eval = args.eval or os.path.join(args.out, "eval_set.csv")
    args.neg = args.neg or os.path.join(args.out, "negative_set.csv")

    eval_rows = list(csv.DictReader(open(args.eval, encoding="utf-8")))
    neg_rows = list(csv.DictReader(open(args.neg, encoding="utf-8")))
    kb = load_kb(args.kb)

    # 1) 正例原始协议
    pos_cache_file = os.path.join(args.out, "_scores_positive.json")
    if args.skip_collect and os.path.exists(pos_cache_file):
        pos_cache = json.load(open(pos_cache_file, encoding="utf-8"))
    else:
        pos_cache = collect_original([(r["query"], r["query"]) for r in eval_rows], pos_cache_file)

    # 2) leave-gold-out
    java_out = os.path.join(args.out, "_leave_out.tsv")
    if args.skip_collect and os.path.exists(java_out):
        lg_rows, n0, n1 = {}, None, None
        with open(java_out, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#N0"):
                    n0 = int(line.split("\t")[1])
                elif line.startswith("#N1"):
                    n1 = int(line.split("\t")[1])
                elif line.startswith("idx\t") or not line.strip():
                    continue
                else:
                    p = line.rstrip("\n").split("\t")
                    lg_rows[int(p[0])] = {"gold_removed": p[1], "status": p[2],
                                          "top1_score": None if p[3] == "NA" else round(float(p[3]), 4),
                                          "top1_id": p[4], "fallback": p[5]}
    else:
        lg_rows, n0, n1 = run_leave_gold_out(eval_rows, args.out, args.leave_script, java_out)
    if n0 is not None and n1 is not None and n0 != n1:
        raise SystemExit(f"leave-gold-out 恢复异常：N0={n0} N1={n1}，终止出报告")
    bad = [k for k, v in lg_rows.items() if v["status"] != "OK" or v["gold_removed"] != "1"]
    print("leave-gold-out: N0=%s N1=%s 异常条数=%d" % (n0, n1, len(bad)))

    # 3) 负例
    neg_cache_file = os.path.join(args.out, "_scores_negative.json")
    if args.skip_collect and os.path.exists(neg_cache_file):
        neg_cache = json.load(open(neg_cache_file, encoding="utf-8"))
    else:
        neg_cache = collect_original([(r["id"], r["query"]) for r in neg_rows], neg_cache_file)

    # 4) 合并逐条结果
    records = []

    def gold_titles(expected):
        return {kb.get(i, {}).get("title", "") for i in expected}

    for i, r in enumerate(eval_rows, 1):
        sc = pos_cache[r["query"]]
        exp = [x.strip() for x in r["expectedIds"].split(";") if x.strip()]
        rec = {"set": "P", "id": f"P-{i:03d}", "class": "positive", "query": r["query"],
               "score": sc["top1_score"], "top1_id": sc["top1_id"], "top1_title": sc["top1_title"],
               "expected": exp, "usable": sc["top1_id"] in exp,
               "correct_top1": sc["top1_id"] in exp, "leave_status": "NA", "ms": sc["ms"]}
        rec.update(push_flags(rec["score"], rec["usable"]))
        records.append(rec)

    lg_titles = {}
    for i, r in enumerate(eval_rows, 1):
        sc = lg_rows.get(i, {})
        exp = [x.strip() for x in r["expectedIds"].split(";") if x.strip()]
        t1 = sc.get("top1_id", "NA")
        dup = t1 != "NA" and kb.get(t1, {}).get("title") in gold_titles(exp)
        rec = {"set": "LG", "id": f"LG-{i:03d}", "class": "leave_gold_out", "query": r["query"],
               "score": sc.get("top1_score"), "top1_id": t1,
               "top1_title": kb.get(t1, {}).get("title", "NA"),
               "expected": exp, "usable": False, "correct_top1": False,
               "leave_status": sc.get("status", "MISSING"), "artifact_dup": int(dup), "ms": None}
        rec.update(push_flags(rec["score"], rec["usable"]))
        records.append(rec)

    for r in neg_rows:
        sc = neg_cache[r["id"]]
        usable_ids = [x.strip() for x in r["usableIds"].split(";") if x.strip()] if r["usableIds"] else []
        usable = sc["top1_id"] in usable_ids
        rec = {"set": "N", "id": r["id"], "class": r["class"], "query": r["query"],
               "score": sc["top1_score"], "top1_id": sc["top1_id"], "top1_title": sc["top1_title"],
               "expected": usable_ids, "usable": usable, "correct_top1": usable,
               "leave_status": "NA", "ms": sc["ms"]}
        rec.update(push_flags(rec["score"], rec["usable"]))
        records.append(rec)

    # 5) 汇总
    P = [r for r in records if r["set"] == "P"]
    LG = [r for r in records if r["set"] == "LG"]
    N = [r for r in records if r["set"] == "N"]
    pools = {
        "正例原始协议": (P, True),
        "leave-gold-out 正例": (LG, False),
        "负例合计": (N, False),
        "正例+负例（200）": (P + N, False),
        "混合等权（300）": (P + LG + N, False),
    }
    summary = OrderedDict()
    for name, (rows, pos) in pools.items():
        summary[name] = summarize(rows, name, positive=pos)

    # 负例分切片
    slices = OrderedDict()
    for cls in CLASS_CN:
        rows = [r for r in N if r["class"] == cls]
        slices[CLASS_CN[cls]] = summarize(rows, CLASS_CN[cls])

    # leave-gold-out 测试遗留重复条目占比
    lg_dup = sum(1 for r in LG if r.get("artifact_dup") and r["score"] is not None and r["score"] >= 0.75)
    lg_push = sum(1 for r in LG if r["score"] is not None and r["score"] >= 0.75)

    # 6) 写 threshold_eval.csv
    cols = ["set", "id", "class", "query", "score", "top1_id", "top1_title", "expected", "usable",
            "correct_top1", "leave_status", "artifact_dup", "ms"]
    for t in THRESHOLDS:
        cols += [f"push@{t}", f"error@{t}"]
    out_csv = os.path.join(args.out, "threshold_eval.csv")
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            row = dict(r)
            row["expected"] = ";".join(r["expected"])
            w.writerow(row)

    out_json = os.path.join(args.out, "_threshold_metrics.json")
    result = {"thresholds": list(THRESHOLDS), "pools": summary, "negative_slices": slices,
              "leave_gold_out": {"N0": n0, "N1": n1, "abnormal": len(bad),
                                 "push_at_075": lg_push, "push_at_075_artifact_dup": lg_dup}}
    json.dump(result, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 7) 控制台表
    print("\n== 阈值 × 指标 ==")
    hdr = ["集合", "T", "推送量", "样本量", "覆盖率/推送率%", "错误推送量", "错误推送率%", "A档准确率%", "A档召回%"]
    print(" | ".join(hdr))
    for name, blk in summary.items():
        for t in THRESHOLDS:
            m = blk["metrics"][t]
            print(" | ".join(str(x) for x in [name, t, m["推送量"], m["样本量"], m["覆盖率/推送率"],
                                              m["错误推送量"], m["错误推送率"],
                                              "-" if m["A档准确率"] is None else m["A档准确率"],
                                              "-" if m["A档召回"] is None else m["A档召回"]]))
    print("\n== 负例切片（错误推送率%，分母=该类 25 条） ==")
    print("类别 | 0.75 | 0.85 | 0.92")
    for name, blk in slices.items():
        print(" | ".join([name] + [str(blk["metrics"][t]["错误推送率"]) for t in THRESHOLDS]))
    print("\n输出:", out_csv, out_json)


if __name__ == "__main__":
    main()
