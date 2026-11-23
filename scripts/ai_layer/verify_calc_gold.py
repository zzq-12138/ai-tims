#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gold 独立复核：只读题面文本，从文本里重新解析数值并重算答案，再与生成器写入的 gold 比对。

刻意不复用生成器的参数与中间量（生成器：参数 → 题面 + gold；本脚本：题面 → 答案），
两条代码路径相互独立，避免「用同一段代码自证」。

覆盖：route_set.tsv 的 30 条 calc（R271-R300）+ route_fix_set.tsv 的 70 条 calc + 30 条 calc_single。

输出：docs/paper/ai应用层/raw/calc_gold_verify.json
用法（仓库根目录）：
    python3 scripts/ai_layer/verify_calc_gold.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_TSV = ROOT / "scripts" / "ai_layer" / "data" / "route_set.tsv"
FIX_TSV = ROOT / "scripts" / "ai_layer" / "data" / "route_fix_set.tsv"
OUT = ROOT / "docs" / "paper" / "ai应用层" / "raw" / "calc_gold_verify.json"
TOL = 0.06


def nums_after_colon(q):
    """取「这批 N 次测量（单位）：v1、v2、…。」里的测量值列表"""
    tail = q.split("）：", 1)[1].rstrip("。")
    vals = []
    for tok in tail.replace("，", "、").split("、"):
        tok = tok.strip()
        m = re.match(r"^-?\d+(?:\.\d+)?", tok)
        if m:
            vals.append(float(m.group()))
    return vals


def parse_limits(q):
    """从题面取阈值/区间（题面里只有这一处数值定义）"""
    if "要求不超过" in q:
        m = re.search(r"要求不超过\s*(-?\d+(?:\.\d+)?)", q)
        return float(m.group(1)), None
    m = re.search(r"要求\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)", q)
    return float(m.group(1)), float(m.group(2))


def recompute(q):
    """题面 → (答案列表, 模板, 自洽检查通过)"""
    checks = []

    if "下降了多少个百分点" in q:
        init = float(re.search(r"初始[^\d]*(-?\d+(?:\.\d+)?)", q).group(1))
        cur = float(re.search(r"现测(-?\d+(?:\.\d+)?)", q).group(1))
        dec = (init - cur) * 100.0 / init
        share = cur * 100.0 / init
        checks.append(abs(dec + share - 100.0) <= 0.15)
        return [round(dec, 1), round(share, 1)], "T1", checks

    if "平均是多少毫秒" in q:
        limit, _ = parse_limits(q)
        vals = nums_after_colon(q)
        avg_ms = sum(vals) / len(vals) * 1000.0
        cnt = sum(1 for v in vals if v * 1000.0 > limit)
        checks.append(0 <= cnt <= len(vals))
        checks.append(vals and max(vals) * 1000 <= limit * 2.0)
        return [round(avg_ms, 1), cnt], "T5", checks

    if "平均值是多少" in q:
        limit, _ = parse_limits(q)
        vals = nums_after_colon(q)
        avg = sum(vals) / len(vals)
        cnt = sum(1 for v in vals if v > limit)
        checks.append(0 <= cnt <= len(vals))
        checks.append(min(vals) <= avg <= max(vals))
        return [round(avg, 1), cnt], "T4", checks

    if "合格几次" in q:
        lo, hi = parse_limits(q)
        vals = nums_after_colon(q)
        cnt = sum(1 for v in vals if lo <= v <= hi)
        checks.append(0 <= cnt <= len(vals))
        checks.append(hi > lo)
        return [cnt, round(cnt * 100.0 / len(vals), 1)], "T3", checks

    if "超标几次" in q:
        limit, _ = parse_limits(q)
        vals = nums_after_colon(q)
        cnt = sum(1 for v in vals if v > limit)
        checks.append(0 <= cnt <= len(vals))
        return [cnt, round(cnt * 100.0 / len(vals), 1)], "T2", checks

    if "与上限相差多少" in q:
        limit, _ = parse_limits(q)
        v = float(re.search(r"本次测得(-?\d+(?:\.\d+)?)", q).group(1))
        return [round(abs(v - limit), 2)], "T6", checks

    raise ValueError("无法解析的题面：" + q)


def rows_from_tsv(path, cols):
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = line.split("\t")
        out.append(dict(zip(cols, p)))
    return out


def main():
    base = rows_from_tsv(BASE_TSV, ["id", "kind", "device", "question", "context", "gold",
                                    "history_turns", "needs_tool", "subkind"])
    fix = rows_from_tsv(FIX_TSV, ["id", "kind", "subkind", "device", "question", "context", "gold",
                                  "gold_type", "template", "history_turns", "needs_tool"])
    items = [r for r in base if r.get("subkind") == "calc"] + \
            [r for r in fix if r.get("subkind") in ("calc", "calc_single")]

    results = []
    bad = 0
    for r in items:
        gold = [float(x) for x in r["gold"].split("|") if x]
        try:
            got, tmpl, checks = recompute(r["question"])
            ok = len(got) == len(gold) and all(abs(a - b) <= TOL for a, b in zip(got, gold)) \
                and all(checks)
        except Exception as e:  # 解析失败本身就是复核不通过
            got, tmpl, ok = None, "ERR", False
            checks = [f"parse_error:{e!r}"]
        if not ok:
            bad += 1
        results.append({"id": r["id"], "template": tmpl, "kind": r["kind"],
                        "subkind": r.get("subkind"), "gold": r["gold"],
                        "recomputed": [f"{v:g}" for v in got] if got else None,
                        "ok": ok, "self_checks": [bool(c) for c in checks],
                        "question": r["question"]})

    summary = {
        "n": len(results),
        "passed": len(results) - bad,
        "failed": bad,
        "by_subkind": {k: {"n": sum(1 for x in results if x["subkind"] == k),
                           "failed": sum(1 for x in results if x["subkind"] == k and not x["ok"])}
                       for k in ("calc", "calc_single")},
        "tolerance_abs": TOL,
        "method": "只读题面文本重新解析并重算，与生成器参数无关；另做区间/占比/均值自洽检查",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "items": results}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if bad:
        for x in results:
            if not x["ok"]:
                print("FAIL", x["id"], x["gold"], x["recomputed"], x["question"][:80])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
