#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Holdout-2 裸模型基线：不加工具、不加路由，一次调用出答案。

协议与 §11/§13 的「全小模型 / 全大模型」完全一致（同一 system prompt、
temperature 0.3、max_tokens 8192），只替换题目集，保证同分母可比。

判分：calc 分片数值匹配（±0.06），simple 分片关键值包含。

用法（仓库根目录）：
  python3 scripts/ai_layer/bare_eval.py --set scripts/ai_layer/data/holdout2_set.tsv --tag holdout2
  # 第二轮起答案走缓存，0 费用
"""
import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from route_holdout_eval import (KEY_FILE, WORKERS, calc_ok, call_model, cost_of,  # noqa: E402
                                graded, load_prices, qhash)

OUT_DIR = ROOT / "docs" / "paper" / "ai应用层"
RAW_DIR = OUT_DIR / "raw"
MODELS = ["glm-4-flash", "glm-5.3-flash"]


def read_rows(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = line.split("\t")
        rows.append({"id": p[0], "slice": p[1], "trap": p[2], "template": p[3],
                     "device": p[4], "question": p[5], "context": p[6], "gold": p[7],
                     "gold_type": p[8], "history_turns": int(p[9]),
                     "needs_tool": p[10] == "True",
                     "qh": qhash({"question": p[5], "context": p[6]})})
    return rows


def rate(a, b):
    return round(100.0 * a / b, 2) if b else 0.0


def _call_retry(key, model, qs, ctx, tries=8):
    """429 限流重试（工程故障兜底，不改判分口径）。"""
    for i in range(tries):
        try:
            return call_model(key, model, qs, ctx)
        except Exception as e:  # noqa: BLE001
            if "429" not in str(e) or i == tries - 1:
                raise
            time.sleep(5.0 * (i + 1))


def run_model(key, model, rows, cache_path, tag):
    cache = {}
    if cache_path.exists():
        for x in json.loads(cache_path.read_text(encoding="utf-8")):
            cache[x["id"]] = x
    todo = [r for r in rows if not (cache.get(r["id"]) and cache[r["id"]].get("qh") == r["qh"])]
    if todo:
        workers = int(os.environ.get("BARE_WORKERS", str(WORKERS)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_call_retry, key, model, r["question"], r["context"]): r for r in todo}
            for i, f in enumerate(as_completed(futs), 1):
                r = futs[f]
                res = f.result()
                res["id"], res["qh"] = r["id"], r["qh"]
                cache[r["id"]] = res
                cache_path.write_text(json.dumps(list(cache.values()), ensure_ascii=False),
                                      encoding="utf-8")
                print("[%s] done %d/%d %s %.2fs" % (model, i, len(todo), r["id"], res["latency_s"]))

    prices = load_prices()
    detail, cost = [], 0.0
    for r in rows:
        res = cache[r["id"]]
        ok = calc_ok(r["gold"], res["answer"]) if r["slice"] == "calc" else graded(r["gold"], res["answer"])
        cost += cost_of(res, prices)
        detail.append({"id": r["id"], "slice": r["slice"], "trap": r["trap"], "question": r["question"],
                       "gold": r["gold"], "answer": res["answer"], "correct": ok,
                       "latency_s": res["latency_s"], "prompt_tokens": res["prompt_tokens"],
                       "completion_tokens": res["completion_tokens"]})

    calc = [x for x in detail if x["slice"] == "calc"]
    simple = [x for x in detail if x["slice"] == "simple"]
    summary = {
        "model": model, "n": len(detail),
        "acc": rate(sum(1 for x in detail if x["correct"]), len(detail)),
        "calc": {"n": len(calc), "acc": rate(sum(1 for x in calc if x["correct"]), len(calc))},
        "simple": {"n": len(simple), "acc": rate(sum(1 for x in simple if x["correct"]), len(simple))},
        "by_trap": {},
        "avg_latency_s": round(sum(x["latency_s"] for x in detail) / len(detail), 2),
        "cost_cny": round(cost, 4),
    }
    for t in dict.fromkeys(x["trap"] for x in detail):
        g = [x for x in detail if x["trap"] == t]
        summary["by_trap"][t] = {"n": len(g), "acc": rate(sum(1 for x in g if x["correct"]), len(g))}

    with open(RAW_DIR / ("bare_%s_%s.csv" % (tag, model)), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "trap", "slice", "gold", "answer", "correct", "latency_s"])
        for x in detail:
            w.writerow([x["id"], x["trap"], x["slice"], x["gold"],
                        x["answer"].replace("\n", " "), x["correct"], x["latency_s"]])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True, help="题目 TSV 路径")
    ap.add_argument("--tag", required=True, help="产物后缀，如 holdout2")
    ap.add_argument("--models", default=",".join(MODELS))
    args = ap.parse_args()

    rows = read_rows(args.set)
    key = KEY_FILE.read_text(encoding="utf-8").strip()
    out = {"set": args.set, "n": len(rows), "models": {}}
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        cache_path = RAW_DIR / ("bare_rows_%s_%s.json" % (args.tag, model))
        summary, detail = run_model(key, model, rows, cache_path, args.tag)
        out["models"][model] = {"summary": summary, "detail": detail}
    path = OUT_DIR / ("裸模型_%s.json" % args.tag)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    main()
