#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A1-v1 冻结后的独立留出集：120 条，句式与开发集（route_set + route_fix_set）明显不同。

生成顺序上的硬约束：本脚本在 ModelRouter.calcVerifiable（A1-v1）冻结之后才生成，
生成后不得因为评测结果回头改 A1-v1，也不得删改本文件中的题面。

五组：
  N1  25 条：正常多步计算，只改引导语/标点，题面结构与开发集同构（应被 A1-v1 检出）
  N2  25 条：正常多步计算，同义改写（几回/均值/比例/从…掉到），预期漏检
  T1  25 条：陷阱①有数字但无需计算（工单/规格/工位/序列号查询）
  T2  25 条：陷阱②题面无数字、数据在参考资料里（隐含基数）
  T3  20 条：陷阱③口语化；10 条多步（calc）+ 10 条单步（simple，用于测误升级）

gold：全部由本脚本按参数计算，不调用任何模型；数值口径 ±0.06 绝对容差；
      另由 verify_holdout_gold.py 只读题面/参考资料独立重算复核。

输出：
  scripts/ai_layer/data/holdout_set.tsv
  scripts/ai_layer/data/holdout_java.tsv
  docs/paper/ai应用层/holdout_set_stats.json
"""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from gen_calc_set import DECLINE, LIMIT, RANGE, MS_SPECS  # noqa: E402  仅复用知识库口径

OUT_TSV = HERE / "data" / "holdout_set.tsv"
OUT_JAVA = HERE / "data" / "holdout_java.tsv"
OUT_STATS = ROOT / "docs" / "paper" / "ai应用层" / "holdout_set_stats.json"

N = 8          # 留出集每批测量次数与开发集（9）不同，避免逐字同构
TOL = 0.06


def fmt(vals):
    return "、".join(f"{v:g}" for v in vals)


def kb(device, part, metric, rule):
    return f"【{device}·{part}】指标：{metric}；{rule}。"


def vals_around(rnd, limit, lo=0.86, hi=1.14, nd=3):
    return [round(limit * rnd.uniform(lo, hi), nd) for _ in range(N)]


def vals_range(rnd, a, b, nd=3):
    pad = (b - a) * 0.35
    return [round(rnd.uniform(a - pad, b + pad), nd) for _ in range(N)]


# ---------------------------------------------------------------- N1：同构改引导语
def n1_t1(rnd, i):
    device, part, metric, rule, init0 = DECLINE[i % len(DECLINE)]
    init = int(round(init0 * rnd.uniform(0.8, 1.4) / 10.0)) * 10
    cur = int(round(init * (1 - rnd.uniform(0.10, 0.25)) / 10.0)) * 10
    q = (f"先看这个：{device}{part}初始{metric}{init}，现测{cur}，{metric}下降了多少个百分点（保留一位小数）？"
         f"现测值是初始值的百分之几（保留一位小数）？")
    gold = f"{(init - cur) * 100.0 / init:.1f}|{cur * 100.0 / init:.1f}"
    return "n1_t1", device, q, kb(device, part, metric, rule), gold


def n1_t2(rnd, i):
    device, part, metric, limit, unit, rule = LIMIT[i % len(LIMIT)]
    vals = vals_around(rnd, limit)
    cnt = sum(1 for v in vals if v > limit)
    q = (f"麻烦看下，{device}{part}{metric}要求不超过{limit:g}{unit}。这批{N}次测量（{unit}）："
         f"{fmt(vals)}。超标几次？超标占比多少（保留一位小数，%）？")
    return "n1_t2", device, q, kb(device, part, metric, rule), f"{cnt}|{cnt * 100.0 / N:.1f}"


def n1_t3(rnd, i):
    device, part, metric, lo, hi, unit, rule = RANGE[i % len(RANGE)]
    vals = vals_range(rnd, lo, hi)
    cnt = sum(1 for v in vals if lo <= v <= hi)
    q = (f"帮我核对下：{device}{part}{metric}要求{lo:g}-{hi:g}{unit}，这批{N}次测量（{unit}）："
         f"{fmt(vals)}。合格几次？合格占比多少（保留一位小数，%）？")
    return "n1_t3", device, q, kb(device, part, metric, rule), f"{cnt}|{cnt * 100.0 / N:.1f}"


def n1_t4(rnd, i):
    device, part, metric, limit, unit, rule = LIMIT[i % len(LIMIT)]
    vals = vals_around(rnd, limit)
    avg = sum(vals) / len(vals)
    cnt = sum(1 for v in vals if v > limit)
    q = (f"顺便算下，{device}{part}{metric}要求不超过{limit:g}{unit}，这批{N}次测量（{unit}）："
         f"{fmt(vals)}。平均值是多少（保留一位小数）？超过上限的有几次？")
    return "n1_t4", device, q, kb(device, part, metric, rule), f"{avg:.1f}|{cnt}"


# ---------------------------------------------------------------- N2：同义改写
def n2_t1(rnd, i):
    device, part, metric, rule, init0 = DECLINE[i % len(DECLINE)]
    init = int(round(init0 * rnd.uniform(0.8, 1.4) / 10.0)) * 10
    cur = int(round(init * (1 - rnd.uniform(0.10, 0.25)) / 10.0)) * 10
    dec = (init - cur) * 100.0 / init
    share = cur * 100.0 / init
    q = (f"从{init}掉到{cur}，{metric}跌了几个百分点（保留一位小数）？"
         f"还剩原来的百分之几（保留一位小数）？")
    return "n2_t1", device, q, kb(device, part, metric, rule), f"{dec:.1f}|{share:.1f}"


def n2_t2(rnd, i):
    device, part, metric, limit, unit, rule = LIMIT[i % len(LIMIT)]
    vals = vals_around(rnd, limit)
    cnt = sum(1 for v in vals if v > limit)
    q = (f"这{N}个读数里，越过{limit:g}{unit}的有几回？占多大比例（保留一位小数，%）？"
         f"读数：{fmt(vals)}。")
    return "n2_t2", device, q, kb(device, part, metric, rule), f"{cnt}|{cnt * 100.0 / N:.1f}"


def n2_t3(rnd, i):
    device, part, metric, lo, hi, unit, rule = RANGE[i % len(RANGE)]
    vals = vals_range(rnd, lo, hi)
    cnt = sum(1 for v in vals if lo <= v <= hi)
    q = (f"{metric}要落在{lo:g}-{hi:g}{unit}，这批读数：{fmt(vals)}。"
         f"合格的有几项？合格比例多少（保留一位小数，%）？")
    return "n2_t3", device, q, kb(device, part, metric, rule), f"{cnt}|{cnt * 100.0 / N:.1f}"


def n2_t4(rnd, i):
    device, part, metric, limit, unit, rule = LIMIT[i % len(LIMIT)]
    vals = vals_around(rnd, limit)
    avg = sum(vals) / len(vals)
    cnt = sum(1 for v in vals if v > limit)
    q = (f"{metric}均值是多少（保留一位小数）？有几回超过{limit:g}{unit}？读数：{fmt(vals)}。")
    return "n2_t4", device, q, kb(device, part, metric, rule), f"{avg:.1f}|{cnt}"


# ---------------------------------------------------------------- T1：有数字但不计算
def t1_wo(rnd, i):
    wo = f"WO-2026110-{i + 3:02d}"
    k = rnd.randint(1, 5)
    ctx = f"工单 {wo}：累计报警 {k} 次，报警码 E-{1040 + i * 7}。"
    q = f"工单 {wo} 记录了几次报警？"
    return "trap_num_wo", "MES终端", q, ctx, str(k)


def t1_spec(rnd, i):
    device, part, metric, lo, hi, unit, rule = RANGE[i % len(RANGE)]
    ver = 2 + i % 4
    ctx = f"规格书第 {ver} 版：{device}·{part}的{metric}区间为 {lo:g}-{hi:g} {unit}。"
    q = f"规格书第 {ver} 版里，{device}{metric}的下限是多少{unit}？"
    return "trap_num_spec", device, q, ctx, f"{lo:g}"


def t1_station(rnd, i):
    line = 1 + i % 3
    j = 1 + i % 5
    m = 1 + i % 3
    k = 5 + i % 3
    ctx = f"B{line} 线共 {k} 个工位，{j} 号工位配 {m} 个贴装头。"
    q = f"B{line} 线 {j} 号工位上配了几个贴装头？"
    return "trap_num_station", "贴片机", q, ctx, str(m)


def t1_sn(rnd, i):
    n = 6 + i % 8
    sn = f"SN-20261107-{40 + i:03d}"
    ctx = f"本批共 {n} 件，起始序列号 {sn}。"
    q = f"这批 {n} 件的起始序列号后三位是多少？"
    return "trap_num_sn", "MES终端", q, ctx, str(int(sn[-3:]))


# ---------------------------------------------------------------- T2：题面无数字
def t2_tenths(rnd, i):
    a = rnd.randint(8, 20)
    b = a + rnd.randint(2, 9)
    ctx = f"【{DECLINE[i % len(DECLINE)][0]}·停机记录】上月因故障停机 {a} h，本月停机 {b} h。"
    q = f"{DECLINE[i % len(DECLINE)][0]}这条线本月停机时间比上月多几成？"
    return "trap_implicit_tenths", DECLINE[i % len(DECLINE)][0], q, ctx, f"{(b - a) * 10.0 / a:.1f}"


def t2_avg(rnd, i):
    device, part, metric, limit, unit, rule = LIMIT[i % len(LIMIT)]
    vals = vals_around(rnd, limit, 1.02, 1.18)
    avg = sum(vals) / len(vals)
    ctx = f"【{device}·{part}】要求不超过 {limit:g}{unit}。测得：{fmt(vals)}。"
    q = f"{device}这批{metric}的均值比规定上限高多少{unit}（保留两位小数）？"
    return "trap_implicit_avg", device, q, ctx, f"{avg - limit:.2f}"


def t2_share(rnd, i):
    device, part, metric, lo, hi, unit, rule = RANGE[i % len(RANGE)]
    vals = vals_range(rnd, lo, hi)
    bad = sum(1 for v in vals if not (lo <= v <= hi))
    ctx = f"【{device}·{part}】要求 {lo:g}-{hi:g}{unit}。测得：{fmt(vals)}。"
    q = f"{device}这批{metric}不合格的占百分之几（保留一位小数）？"
    return "trap_implicit_share", device, q, ctx, f"{bad * 100.0 / N:.1f}"


def t2_tenths2(rnd, i):
    a = rnd.randint(15, 30)
    b = a + rnd.randint(3, 10)
    ctx = f"【换型记录】上次换型耗时 {a} min，这次 {b} min。"
    q = f"这次贴片机{i + 1}号线换型比上次多用了几成？"
    return "trap_implicit_tenths2", "贴片机", q, ctx, f"{(b - a) * 10.0 / a:.1f}"


# ---------------------------------------------------------------- T3：口语化
def t3_count(rnd, i):
    device, part, metric, limit, unit, rule = LIMIT[i % len(LIMIT)]
    vals = vals_around(rnd, limit)
    cnt = sum(1 for v in vals if v > limit)
    ctx = f"【{device}·{part}】要求不超过 {limit:g}{unit}。测得：{fmt(vals)}。"
    q = f"帮我数一下{device}这批{metric}超了几回，占多少（保留一位小数，%）？"
    return "trap_colloquial_count", device, q, ctx, f"{cnt}|{cnt * 100.0 / N:.1f}"


def t3_avg(rnd, i):
    device, part, metric, limit_ms, rule, (a, b) = MS_SPECS[i % len(MS_SPECS)]
    vals = [round(rnd.uniform(a, b), 3) for _ in range(N)]
    avg_ms = sum(vals) / len(vals) * 1000.0
    cnt = sum(1 for v in vals if v * 1000.0 > limit_ms)
    ctx = f"【{device}·{part}】要求不超过 {limit_ms} ms。测得（s）：{fmt(vals)}。"
    q = f"你帮我看看，{device}{i + 1}号线这批{metric}平均下来多少毫秒？有几回越线？"
    return "trap_colloquial_avg", device, q, ctx, f"{avg_ms:.1f}|{cnt}"


def t3_single(rnd, i):
    device, part, metric, limit, unit, rule = LIMIT[i % len(LIMIT)]
    v = round(limit * rnd.uniform(0.72, 0.96), 2)
    label = "个百分点" if unit == "%" else unit
    ctx = f"【{device}·{part}】要求不超过 {limit:g}{unit}，本次测得 {v:g}{unit}。"
    q = f"{device}{metric}跟上限还差多少{label}（保留两位小数）？"
    return "trap_colloquial_single", device, q, ctx, f"{abs(v - limit):.2f}"


# ---------------------------------------------------------------- 组装
def main():
    rnd = random.Random(20261109)
    rows = []

    def add(fn, i):
        tmpl, device, q, ctx, gold = fn(rnd, i)
        simple = tmpl.startswith("trap_num") or tmpl == "trap_colloquial_single"
        rows.append({"id": f"H{len(rows) + 1:03d}", "slice": "simple" if simple else "calc",
                     "trap": ("N1" if tmpl.startswith("n1") else "N2" if tmpl.startswith("n2")
                              else "T1" if tmpl.startswith("trap_num")
                              else "T2" if tmpl.startswith("trap_implicit") else "T3"),
                     "template": tmpl, "device": device, "question": q, "context": ctx,
                     "gold": gold, "gold_type": "numeric", "history_turns": 0, "needs_tool": False})

    for i in range(5):
        add(n1_t1, i)
    for i in range(8):
        add(n1_t2, i)
    for i in range(7):
        add(n1_t3, i)
    for i in range(5):
        add(n1_t4, i)
    for i in range(6):
        add(n2_t1, i)
    for i in range(7):
        add(n2_t2, i)
    for i in range(6):
        add(n2_t3, i)
    for i in range(6):
        add(n2_t4, i)
    for i in range(7):
        add(t1_wo, i)
    for i in range(6):
        add(t1_spec, i)
    for i in range(6):
        add(t1_station, i)
    for i in range(6):
        add(t1_sn, i)
    for i in range(7):
        add(t2_tenths, i)
    for i in range(6):
        add(t2_avg, i)
    for i in range(6):
        add(t2_share, i)
    for i in range(6):
        add(t2_tenths2, i)
    for i in range(5):
        add(t3_count, i)
    for i in range(5):
        add(t3_avg, i)
    for i in range(10):
        add(t3_single, i)

    assert len(rows) == 120, len(rows)
    seen = set()
    for r in rows:
        if r["question"] in seen:
            raise SystemExit("重复题目：" + r["id"])
        seen.add(r["question"])

    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ("id", "slice", "trap", "template", "device", "question", "context", "gold",
            "gold_type", "history_turns", "needs_tool")
    with open(OUT_TSV, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write("\t".join(str(r[k]) for k in cols) + "\n")

    with open(OUT_JAVA, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write("\t".join([r["id"], r["slice"], r["device"], r["question"], r["context"],
                               r["gold"], "0", "0", r["template"]]) + "\n")

    stats = {
        "n": len(rows),
        "slice": {k: sum(1 for r in rows if r["slice"] == k) for k in ("calc", "simple")},
        "trap": {k: sum(1 for r in rows if r["trap"] == k) for k in ("N1", "N2", "T1", "T2", "T3")},
        "templates": {t: sum(1 for r in rows if r["template"] == t)
                      for t in sorted({r["template"] for r in rows})},
        "gold_rule": f"全部由 gen_holdout_set.py 按参数计算，数值 ±{TOL} 绝对容差；不调用模型",
        "frozen_rule": "A1-v1 (ModelRouter.calcVerifiable)",
        "out": str(OUT_TSV.relative_to(ROOT)),
    }
    OUT_STATS.parent.mkdir(parents=True, exist_ok=True)
    OUT_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
