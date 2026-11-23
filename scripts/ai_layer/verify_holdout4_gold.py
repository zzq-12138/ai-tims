#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Holdout-4 gold 独立复核：只读题面与资料重算，不引用生成器变量。

解析路径与 gen_holdout4_set.py 不同：一律从 TSV 文本用锚点/正则取数，
按题面关键词分派题型；任何一条重算与 gold 不一致都算失败（要求 100%）。

用法（仓库根目录）：
  python3 scripts/ai_layer/verify_holdout4_gold.py
"""
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
SET = HERE / "data" / "holdout4_set.tsv"
NUM = re.compile(r"\d+(?:\.\d+)?")


def q(x, n):
    return Decimal(str(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)


def fmt(d):
    s = format(Decimal(d).normalize(), "f")
    return s if s != "-0" else "0"


def nums_after(text, anchor, stop="。"):
    body = text.split(anchor, 1)[1].split(stop, 1)[0]
    return [Decimal(x) for x in NUM.findall(body)]


def recompute(qs, ctx):
    # G5 超限环比（题面出现「比上一批的 N 个」）
    if "比上一批的" in qs:
        lim = Decimal(re.search(r"工艺上限\s*([\d.]+)", ctx).group(1))
        vals = nums_after(qs, "实测值是 ")
        prev = Decimal(re.search(r"上一批的\s*(\d+)\s*个", qs).group(1))
        cnt = Decimal(sum(1 for v in vals if v > lim))
        return "%d|%s" % (int(cnt), fmt(q(abs(cnt - prev) / prev * 100, 1)))

    # G7-A3 今日均值 vs 上一批均值
    if "均值是涨了还是降了" in qs:
        v_t = nums_after(ctx, "今天读数：", "；")
        v_p = nums_after(ctx, "上一批读数：")
        avg_t = q(sum(v_t) / Decimal(len(v_t)), 2)
        avg_p = q(sum(v_p) / Decimal(len(v_p)), 2)
        return fmt(q(abs(avg_t - avg_p) / avg_p * 100, 1))

    # G7-A1 超标个数 + 占比
    if "超标占比多少" in qs:
        lim = Decimal(re.search(r"工艺上限\s*([\d.]+)", ctx).group(1))
        vals = nums_after(ctx, "今天读数：", "；")
        cnt = Decimal(sum(1 for v in vals if v > lim))
        return "%d|%s" % (int(cnt), fmt(q(cnt / Decimal(len(vals)) * 100, 1)))

    # G7-A2 均值 + 比上限低多少
    if "比上限低多少" in qs:
        lim = Decimal(re.search(r"工艺上限\s*([\d.]+)", ctx).group(1))
        vals = nums_after(ctx, "今天这批读数：", "；")
        avg = q(sum(vals) / Decimal(len(vals)), 2)
        return "%s|%s" % (fmt(avg), fmt(q(lim - avg, 2)))

    # G3 工艺窗口个数 + 合格率
    if "在工艺窗口里的有几个" in qs:
        lo, hi = [Decimal(x) for x in re.search(
            r"工艺窗口\s*([\d.]+)\s*～\s*([\d.]+)", ctx).groups()]
        vals = nums_after(qs, "读数：")
        hit = sum(1 for v in vals if lo <= v <= hi)
        return "%d|%s" % (hit, fmt(q(Decimal(hit) / Decimal(len(vals)) * 100, 1)))

    # G4 均值 + 比下限高多少
    if "平均下来多少" in qs:
        vals = [Decimal(x) for x in re.search(r"依次是\s*([\d.、]+)", qs).group(1)
                .rstrip("、").split("、")]
        lo = Decimal(re.search(r"工艺下限\s*([\d.]+)", ctx).group(1))
        avg = q(sum(vals) / Decimal(len(vals)), 2)
        return "%s|%s" % (fmt(avg), fmt(q(avg - lo, 2)))

    # G2 成数
    if "几成" in qs:
        a, b = [Decimal(x) for x in re.search(
            r"上月\s*([\d.]+)[^，]*，本月\s*([\d.]+)", ctx).groups()]
        return fmt(q(abs(b - a) / a * 10, 1))

    # G1 达成率 + 缺口
    if "达成率" in qs or "完成率" in qs:
        plan, done = [Decimal(x) for x in re.search(
            r"本周目标\s*([\d.]+)[^，]*，实际\s*([\d.]+)", ctx).groups()]
        return "%s|%d" % (fmt(q(done / plan * 100, 1)), int(plan - done))

    # G8 不必算
    if "点检" in qs:
        return re.search(r"每\s*(\d+)\s*天点检一次", ctx).group(1)
    if "保修" in qs:
        return re.search(r"整机保修\s*(\d+)\s*个月", ctx).group(1)
    if "额定功率" in qs:
        return re.search(r"额定功率\s*([\d.]+)\s*kW", ctx).group(1)
    if "归谁管" in qs:
        return re.search(r"负责人：(\S+?)；", ctx).group(1)
    if "库位" in qs:
        return re.search(r"库位\s*(\S+?)；", ctx).group(1)
    if "保养间隔" in qs:
        return re.search(r"保养间隔\s*(\d+)\s*天", ctx).group(1)
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
            bad.append((p[0], p[7], got, p[5]))
    print({"n": n, "consistent": n - len(bad), "failed": len(bad)})
    for b in bad:
        print(b)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
