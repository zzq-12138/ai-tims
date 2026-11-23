#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
留出集 gold 独立复核：只读题面与参考资料文本，重新解析并重算，再与生成器写入的 gold 比对。

与 gen_holdout_set.py 刻意不共享任何计算函数：生成器是「参数 → 题面 + gold」，
本脚本是「题面/资料 → 答案」，两条代码路径相互独立。容差 ±0.06（绝对）。

输出：docs/paper/ai应用层/raw/holdout_gold_verify.json
用法（仓库根目录）：
    python3 scripts/ai_layer/verify_holdout_gold.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TSV = ROOT / "scripts" / "ai_layer" / "data" / "holdout_set.tsv"
OUT = ROOT / "docs" / "paper" / "ai应用层" / "raw" / "holdout_gold_verify.json"
TOL = 0.06
NUM = r"-?\d+(?:\.\d+)?"


def tail_nums(text):
    """取最后一个「：」之后、第一个「。」之前的数值列表"""
    tail = text.rsplit("：", 1)[-1].split("。", 1)[0]
    return [float(x) for x in re.findall(NUM, tail)]


def one(pat, text, cast=float):
    m = re.search(pat, text)
    if not m:
        raise ValueError("未匹配：" + pat)
    return cast(m.group(1))


def one_any(pats, text):
    for p in pats:
        m = re.search(p, text)
        if m:
            return float(m.group(1))
    raise ValueError("未匹配任一模式：" + str(pats))


def recompute(q, c, t):
    """返回 (答案列表, 自洽检查)"""
    checks = []
    if t in ("n1_t1", "n2_t1"):
        if t == "n1_t1":
            init = one(r"初始[^\d]*(" + NUM + ")", q)
            cur = one(r"现测\s*(" + NUM + ")", q)
        else:
            init = one(r"从\s*(" + NUM + r")\s*掉到", q)
            cur = one(r"掉到\s*(" + NUM + ")", q)
        dec = (init - cur) * 100.0 / init
        share = cur * 100.0 / init
        checks.append(abs(dec + share - 100.0) <= 0.15)
        return [round(dec, 1), round(share, 1)], checks

    if t in ("n1_t2", "n2_t2"):
        limit = one_any([r"要求不超过\s*(" + NUM + ")", r"越过\s*(" + NUM + ")"], q)
        vals = tail_nums(q)
        cnt = sum(1 for v in vals if v > limit)
        checks += [0 <= cnt <= len(vals), len(vals) == 8]
        return [cnt, round(cnt * 100.0 / len(vals), 1)], checks

    if t in ("n1_t3", "n2_t3"):
        m = re.search(r"要求\s*(" + NUM + r")\s*-\s*(" + NUM + ")", q) or \
            re.search(r"要落在\s*(" + NUM + r")\s*-\s*(" + NUM + ")", q) or \
            re.search(r"落在\s*(" + NUM + r")\s*-\s*(" + NUM + ")", q)
        if not m:
            raise ValueError("未匹配区间")
        lo, hi = float(m.group(1)), float(m.group(2))
        vals = tail_nums(q)
        cnt = sum(1 for v in vals if lo <= v <= hi)
        checks += [0 <= cnt <= len(vals), hi > lo, len(vals) == 8]
        return [cnt, round(cnt * 100.0 / len(vals), 1)], checks

    if t in ("n1_t4", "n2_t4"):
        limit = one_any([r"要求不超过\s*(" + NUM + ")", r"超过\s*(" + NUM + ")"], q)
        vals = tail_nums(q)
        avg = sum(vals) / len(vals)
        cnt = sum(1 for v in vals if v > limit)
        checks += [0 <= cnt <= len(vals), min(vals) <= avg <= max(vals), len(vals) == 8]
        return [round(avg, 1), cnt], checks

    if t == "trap_num_wo":
        return [one(r"累计报警\s*(\d+)\s*次", c)], checks

    if t == "trap_num_spec":
        m = re.search(r"区间为\s*(" + NUM + r")\s*-\s*(" + NUM + ")", c)
        if not m:
            raise ValueError("未匹配规格区间")
        return [float(m.group(1))], checks

    if t == "trap_num_station":
        return [one(r"配\s*(\d+)\s*个贴装头", c)], checks

    if t == "trap_num_sn":
        return [one(r"SN-\d+-(\d{3})", c)], checks

    if t == "trap_implicit_tenths":
        a = one(r"停机\s*(\d+)\s*h", c)
        b = one(r"本月停机\s*(\d+)\s*h", c)
        checks.append(b >= a)
        return [round((b - a) * 10.0 / a, 1)], checks

    if t == "trap_implicit_avg":
        limit = one(r"要求不超过\s*(" + NUM + ")", c)
        vals = tail_nums(c)
        avg = sum(vals) / len(vals)
        checks += [avg >= limit, len(vals) == 8]
        return [round(avg - limit, 2)], checks

    if t == "trap_implicit_share":
        m = re.search(r"要求\s*(" + NUM + r")\s*-\s*(" + NUM + ")", c)
        if not m:
            raise ValueError("未匹配区间")
        lo, hi = float(m.group(1)), float(m.group(2))
        vals = tail_nums(c)
        bad = sum(1 for v in vals if not (lo <= v <= hi))
        checks += [0 <= bad <= len(vals), len(vals) == 8]
        return [round(bad * 100.0 / len(vals), 1)], checks

    if t == "trap_implicit_tenths2":
        a = one(r"上次换型耗时\s*(\d+)\s*min", c)
        b = one(r"这次\s*(\d+)\s*min", c)
        checks.append(b >= a)
        return [round((b - a) * 10.0 / a, 1)], checks

    if t == "trap_colloquial_count":
        limit = one(r"要求不超过\s*(" + NUM + ")", c)
        vals = tail_nums(c)
        cnt = sum(1 for v in vals if v > limit)
        checks += [0 <= cnt <= len(vals), len(vals) == 8]
        return [cnt, round(cnt * 100.0 / len(vals), 1)], checks

    if t == "trap_colloquial_avg":
        limit_ms = one(r"要求不超过\s*(" + NUM + ")\s*ms", c)
        vals = tail_nums(c)
        avg_ms = sum(vals) / len(vals) * 1000.0
        cnt = sum(1 for v in vals if v * 1000.0 > limit_ms)
        checks += [0 <= cnt <= len(vals), len(vals) == 8]
        return [round(avg_ms, 1), cnt], checks

    if t == "trap_colloquial_single":
        limit = one(r"要求不超过\s*(" + NUM + ")", c)
        v = one(r"本次测得\s*(" + NUM + ")", c)
        checks.append(v <= limit)
        return [round(abs(v - limit), 2)], checks

    raise ValueError("未知模板：" + t)


def main():
    rows = []
    for line in TSV.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = line.split("\t")
        rows.append(dict(zip(("id", "slice", "trap", "template", "device", "question",
                              "context", "gold", "gold_type", "history_turns", "needs_tool"), p)))

    results = []
    bad = 0
    for r in rows:
        gold = [float(x) for x in r["gold"].split("|") if x]
        try:
            got, checks = recompute(r["question"], r["context"], r["template"])
            ok = len(got) == len(gold) and all(abs(a - b) <= TOL for a, b in zip(got, gold)) \
                and all(checks)
        except Exception as e:  # 解析失败即复核不通过
            got, checks, ok = None, [f"parse_error:{e!r}"], False
        if not ok:
            bad += 1
        results.append({"id": r["id"], "trap": r["trap"], "template": r["template"],
                        "gold": r["gold"], "recomputed": [f"{v:g}" for v in got] if got else None,
                        "ok": ok, "self_checks": [bool(c) for c in checks],
                        "question": r["question"]})

    summary = {
        "n": len(results),
        "passed": len(results) - bad,
        "failed": bad,
        "by_trap": {k: {"n": sum(1 for x in results if x["trap"] == k),
                        "failed": sum(1 for x in results if x["trap"] == k and not x["ok"])}
                    for k in ("N1", "N2", "T1", "T2", "T3")},
        "tolerance_abs": TOL,
        "method": "只读题面/参考资料重新解析并重算；另做区间、占比、均值自洽检查",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "items": results}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if bad:
        for x in results:
            if not x["ok"]:
                print("FAIL", x["id"], x["template"], x["gold"], x["recomputed"], x["question"][:70])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
