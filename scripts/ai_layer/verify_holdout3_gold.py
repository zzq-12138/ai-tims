#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Holdout-3 gold 独立复核：只读题面与资料重算，不引用生成器任何变量。

刻意用与 gen_holdout3_set.py 不同的解析路径（按题型关键词定位、正则取数），
只依赖 TSV 文本本身；任何一条重算结果与 gold 不一致都算失败。

用法（仓库根目录）：
  python3 scripts/ai_layer/verify_holdout3_gold.py
"""
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
SET = HERE / "data" / "holdout3_set.tsv"


def q(x, n):
    return Decimal(str(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)


def fmt(d):
    s = format(Decimal(d).normalize(), "f")
    return s if s != "-0" else "0"


NUM = re.compile(r"\d+(?:\.\d+)?")


def after(text, anchor, stop="。"):
    if anchor not in text:
        return []
    body = text.split(anchor, 1)[1].split(stop, 1)[0]
    return [Decimal(x) for x in NUM.findall(body)]


def recompute(qs, ctx):
    if "完成了计划的百分之几" in qs:
        plan, done = [Decimal(x) for x in re.search(
            r"计划\s*([\d.]+)\s*\S*?，实际完成\s*([\d.]+)", ctx).groups()]
        return "%s|%s" % (fmt(q(done / plan * 100, 1)), fmt(plan - done))
    if "几成" in qs:
        a, b = [Decimal(x) for x in re.search(
            r"上月\s*([\d.]+)[^，]*，本月\s*([\d.]+)", ctx).groups()]
        return fmt(q(abs(b - a) / a * 10, 1))
    if "落在工艺窗口内的有几个" in qs:
        lo, hi = [Decimal(x) for x in re.search(
            r"工艺窗口\s*([\d.]+)\s*～\s*([\d.]+)", ctx).groups()]
        vals = after(qs, "读数：")
        hit = sum(1 for v in vals if lo <= v <= hi)
        return "%d|%s" % (hit, fmt(q(Decimal(hit) / Decimal(len(vals)) * 100, 1)))
    if "均值多少" in qs:
        vals = after(qs, "依次为")
        lo = Decimal(re.search(r"工艺下限\s*([\d.]+)", ctx).group(1))
        avg = q(sum(vals) / Decimal(len(vals)), 2)
        return "%s|%s" % (fmt(avg), fmt(q(avg - lo, 2)))
    if "越过上限的有几个" in qs:
        lim = Decimal(re.search(r"工艺上限\s*([\d.]+)", ctx).group(1))
        vals = after(qs, "实测：")
        prev = Decimal(re.search(r"上一批的\s*(\d+)\s*个", qs).group(1))
        cnt = Decimal(sum(1 for v in vals if v > lim))
        return "%d|%s" % (int(cnt), fmt(q(abs(cnt - prev) / prev * 100, 1)))
    if "点检周期" in qs:
        return fmt(Decimal(re.search(r"每\s*(\d+)\s*天", ctx).group(1)))
    if "保修期" in qs:
        return fmt(Decimal(re.search(r"整机保修\s*(\d+)\s*个月", ctx).group(1)))
    if "额定功率" in qs:
        return fmt(Decimal(re.search(r"额定功率\s*([\d.]+)\s*kW", ctx).group(1)))
    if "谁负责" in qs or "由谁负责" in qs:
        return re.search(r"负责人：(\S+?)；", ctx).group(1)
    if "库位" in qs:
        return re.search(r"库位\s*([A-Z]?\d+-\d+)", ctx).group(1)
    raise ValueError("未知题型：" + qs[:40])


def main():
    bad, n = [], 0
    for line in SET.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = line.split("\t")
        n += 1
        got = recompute(p[5], p[6])
        if got != p[7]:
            bad.append({"id": p[0], "gold": p[7], "recomputed": got, "q": p[5]})
    print({"n": n, "consistent": n - len(bad), "failed": len(bad)})
    for b in bad:
        print(json_dumps(b))
    return 0 if not bad else 1


def json_dumps(x):
    import json
    return json.dumps(x, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
