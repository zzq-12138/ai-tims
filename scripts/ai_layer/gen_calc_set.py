#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扩容「短问句藏计算」评测集：30 条（沿用 route_set.tsv 的 R271-R300）→ 100 条。

新增 70 条多步计算题（C031-C100），全部由代码生成、gold 由代码计算，不手写、不调模型；
另加 30 条「单步数值题」（N001-N030）作为「数值外观但不需大模型」的负样本，
用于测量候选方案的误升级/误触发率。

输出：
    scripts/ai_layer/data/route_fix_set.tsv        新增 70 条 calc + 30 条 calc_single
    scripts/ai_layer/data/route_fix_java.tsv       给生产 ModelRouter 的 9 列格式（只为拿路由决策）
    docs/paper/ai应用层/calc_set_stats.json

用法（仓库根目录）：
    python3 scripts/ai_layer/gen_calc_set.py
"""
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_TSV = ROOT / "scripts" / "ai_layer" / "data" / "route_set.tsv"
OUT_TSV = ROOT / "scripts" / "ai_layer" / "data" / "route_fix_set.tsv"
OUT_JAVA = ROOT / "scripts" / "ai_layer" / "data" / "route_fix_java.tsv"
OUT_STATS = ROOT / "docs" / "paper" / "ai应用层" / "calc_set_stats.json"

# ---- 参数池：与 gen_route_set.py 的 CALC_A/B/C 同源，保证设备/部件/指标仍是项目知识库口径 ----
DECLINE = [
    ("SPI锡膏检测机", "投影光源模组", "亮度", "低于初始值 85% 即需更换", 1180),
    ("AOI光学检测机", "环形光源", "亮度", "低于初始值 85% 即需更换", 2400),
    ("刻蚀机", "射频电源", "输出功率", "低于额定值 90% 即判衰减", 800),
    ("涂覆机", "喷雾阀", "胶量", "低于标称值 85% 即需更换", 1200),
    ("回流焊", "氮气流量计", "氮气流量", "低于标称值 90% 即判供气不足", 640),
    ("波峰焊", "助焊剂泵", "喷涂量", "低于标称值 85% 即判泵衰减", 2500),
    ("X-Ray检测机", "射线管", "管电流", "低于额定值 90% 即判老化", 1600),
    ("层压机", "加热棒", "加热功率", "低于额定值 90% 即判老化", 900),
]

LIMIT = [
    ("贴片机", "贴装头升降气缸", "单次动作时间", 0.25, "s", "大于 0.25 s 即判气路或气缸问题"),
    ("回流焊", "热风马达", "温区横向温差", 3.0, "℃", "温差大于 3℃ 即判热风循环问题"),
    ("波峰焊", "锡炉", "锡波接触深度比", 0.70, "倍板厚", "超过 0.70 倍板厚即判波峰过高"),
    ("SPI锡膏检测机", "高度标定块", "高度偏差", 5.0, "μm", "偏差大于 5 μm 即为标定问题"),
    ("X-Ray检测机", "载物台夹具", "样品位移", 5.0, "μm", "位移大于 5 μm 即为夹持问题"),
    ("AOI光学检测机", "相机光源", "照度偏差", 10.0, "%", "偏差大于 10% 即为光源问题"),
    ("涂覆机", "胶阀", "出胶量偏差", 10.0, "%", "偏差大于 10% 即为胶阀问题"),
    ("刻蚀机", "真空泵", "腔体真空度", 5.0, "Pa", "真空度劣于 5 Pa 即判泵效下降"),
    ("层压机", "温控模块", "温度偏差", 2.0, "℃", "偏差大于 2℃ 即为温控问题"),
    ("回流焊", "助焊剂喷嘴", "喷涂量偏差", 10.0, "%", "偏差大于 10% 即为喷嘴问题"),
    ("MES终端", "扫码枪", "扫码失败率", 2.0, "%", "失败率大于 2% 即为扫码问题"),
]

RANGE = [
    ("波峰焊", "传送带", "传送速度", 1.0, 1.2, "m/min", "1.0-1.2 m/min 为合格"),
    ("X-Ray检测机", "射线管", "放大倍率", 3.5, 5.0, "倍", "3.5-5.0 倍为合格"),
    ("回流焊", "传送带", "传送速度", 1.0, 1.2, "m/min", "1.0-1.2 m/min 为合格"),
    ("贴片机", "供料器", "供料间距", 3.9, 4.1, "mm", "3.9-4.1 mm 为合格"),
    ("SPI锡膏检测机", "锡膏厚度", "印刷厚度", 0.10, 0.15, "mm", "0.10-0.15 mm 为合格"),
    ("AOI光学检测机", "相机", "曝光时间", 8.0, 12.0, "ms", "8-12 ms 为合格"),
    ("涂覆机", "喷头", "喷涂压力", 0.2, 0.3, "MPa", "0.2-0.3 MPa 为合格"),
    ("刻蚀机", "射频电源", "反射功率", 0.0, 5.0, "W", "0-5 W 为合格"),
    ("层压机", "液压系统", "压合压力", 1.5, 2.0, "MPa", "1.5-2.0 MPa 为合格"),
    ("MES终端", "工位终端", "上报延迟", 5.0, 15.0, "s", "5-15 s 为合格"),
    ("回流焊", "冷却区", "冷却速率", 2.0, 4.0, "℃/s", "2-4 ℃/s 为合格"),
]

N = 9  # 每批测量次数


def fmt_vals(vals):
    return "、".join(f"{v:g}" for v in vals)


def ctx(device, part, metric, rule):
    return f"【{device}·{part}】指标：{metric}；{rule}。"


def gen_vals(rnd, limit, lo_factor=0.85, hi_factor=1.15, nd=3):
    while True:
        vals = [round(limit * rnd.uniform(lo_factor, hi_factor), nd) for _ in range(N)]
        hit = [v for v in vals if v > limit]
        if 1 <= len(hit) <= 7:
            return vals, hit


def t1(rnd, i):
    device, part, metric, rule, init0 = DECLINE[i % len(DECLINE)]
    init = int(round(init0 * rnd.uniform(0.8, 1.5) / 10.0)) * 10
    cur = int(round(init * (1 - rnd.uniform(0.08, 0.28)) / 10.0)) * 10
    dec = (init - cur) * 100.0 / init
    share = cur * 100.0 / init
    q = (f"{device}{part}初始{metric}{init}，现测{cur}，{metric}下降了多少个百分点（保留一位小数）？"
         f"现测值是初始值的百分之几（保留一位小数）？")
    return q, ctx(device, part, metric, rule), f"{dec:.1f}|{share:.1f}", "T1", device


def t2(rnd, i):
    device, part, metric, limit, unit, rule = LIMIT[i % len(LIMIT)]
    vals, hit = gen_vals(rnd, limit)
    q = (f"{device}{part}{metric}要求不超过{limit:g}{unit}，这批{N}次测量（{unit}）："
         f"{fmt_vals(vals)}。超标几次？超标占比多少（保留一位小数，%）？")
    return q, ctx(device, part, metric, rule), f"{len(hit)}|{len(hit) * 100.0 / N:.1f}", "T2", device


def t3(rnd, i):
    device, part, metric, lo, hi, unit, rule = RANGE[i % len(RANGE)]
    while True:
        vals = [round(rnd.uniform(lo - (hi - lo) * 0.35, hi + (hi - lo) * 0.35), 3) for _ in range(N)]
        hit = [v for v in vals if lo <= v <= hi]
        if 1 <= len(hit) <= 7:
            break
    q = (f"{device}{part}{metric}要求{lo:g}-{hi:g}{unit}，这批{N}次测量（{unit}）："
         f"{fmt_vals(vals)}。合格几次？合格占比多少（保留一位小数，%）？")
    return q, ctx(device, part, metric, rule), f"{len(hit)}|{len(hit) * 100.0 / N:.1f}", "T3", device


def t4(rnd, i):
    """多步：先求平均，再判超过上限的次数。"""
    device, part, metric, limit, unit, rule = LIMIT[i % len(LIMIT)]
    vals, hit = gen_vals(rnd, limit)
    avg = sum(vals) / len(vals)
    q = (f"{device}{part}{metric}要求不超过{limit:g}{unit}，这批{N}次测量（{unit}）："
         f"{fmt_vals(vals)}。平均值是多少（保留一位小数）？超过上限的有几次？")
    return q, ctx(device, part, metric, rule), f"{avg:.1f}|{len(hit)}", "T4", device


MS_SPECS = [
    ("贴片机", "贴装头升降气缸", "单次动作时间", 250, "大于 0.25 s 即判气路或气缸问题", (0.22, 0.29)),
    ("AOI光学检测机", "相机", "曝光时间", 10, "8-12 ms 为合格", (0.008, 0.013)),
    ("MES终端", "工位终端", "上报延迟", 5200, "5-15 s 为合格", (4.8, 5.5)),
]


def t5(rnd, i):
    """多步 + 单位换算：s → ms，再求平均、再计数。"""
    device, part, metric, limit_ms, rule, (a, b) = MS_SPECS[i % len(MS_SPECS)]
    vals = [round(rnd.uniform(a, b), 3) for _ in range(N)]
    avg_ms = sum(vals) / len(vals) * 1000.0
    cnt = sum(1 for v in vals if v * 1000.0 > limit_ms)
    q = (f"{device}{part}{metric}要求不超过{limit_ms} ms，这批{N}次测量（s）："
         f"{fmt_vals(vals)}。平均是多少毫秒（保留一位小数）？超出上限几次？")
    return q, ctx(device, part, metric, rule), f"{avg_ms:.1f}|{cnt}", "T5", device


T6_POOL = [x for x in LIMIT if x[5] != "倍板厚"]  # 单位换成「倍板厚」后「相差多少」不自洽，排除


def t6_single(rnd, i):
    """单步数值题（简单档）：只做一次减法，用于测误升级率。
    百分数用「个百分点」表述，避免「相对差 vs 绝对差」的歧义。"""
    device, part, metric, limit, unit, rule = T6_POOL[i % len(T6_POOL)]
    v = round(limit * rnd.uniform(0.7, 1.3), 2)
    diff = abs(v - limit)
    label = "个百分点" if unit == "%" else unit
    q = (f"{device}{part}{metric}要求不超过{limit:g}{unit}，本次测得{v:g}{unit}，"
         f"与上限相差多少{label}（保留两位小数）？")
    return q, ctx(device, part, metric, rule), f"{diff:.2f}", "T6", device


def main():
    rnd = random.Random(20261108)
    rows = []

    # 70 条多步计算：T1 20 / T2 20 / T3 20 / T4 6 / T5 4
    plan = [("C%03d", t1, 20), ("C%03d", t2, 20), ("C%03d", t3, 20),
            ("C%03d", t4, 6), ("C%03d", t5, 4)]
    idx = 31
    for _, fn, cnt in plan:
        for i in range(cnt):
            q, c, gold, tmpl, device = fn(rnd, i)
            rows.append(dict(id=f"C{idx:03d}", kind="complex", subkind="calc", device=device,
                             question=q, context=c, gold=gold, gold_type="numeric",
                             template=tmpl, history_turns=0, needs_tool=False))
            idx += 1
    assert idx == 101, idx

    # 30 条单步数值题：简单档，测误升级
    for i in range(30):
        q, c, gold, tmpl, device = t6_single(rnd, i)
        rows.append(dict(id=f"N{i + 1:03d}", kind="simple", subkind="calc_single", device=device,
                         question=q, context=c, gold=gold, gold_type="numeric",
                         template=tmpl, history_turns=0, needs_tool=False))

    # 去重校验
    seen = set()
    for r in rows:
        if r["question"] in seen:
            raise SystemExit("重复题目：" + r["id"])
        seen.add(r["question"])

    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ("id", "kind", "subkind", "device", "question", "context", "gold", "gold_type",
            "template", "history_turns", "needs_tool")
    with open(OUT_TSV, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write("\t".join(str(r[k]) for k in cols) + "\n")

    # 给生产 ModelRouter 的 9 列格式
    with open(OUT_JAVA, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write("\t".join([r["id"], r["kind"], r["device"], r["question"], r["context"],
                               r["gold"], str(r["history_turns"]), "0", r["subkind"]]) + "\n")

    stats = {
        "added_calc_multi": sum(1 for r in rows if r["subkind"] == "calc"),
        "added_calc_single": sum(1 for r in rows if r["subkind"] == "calc_single"),
        "calc_total_after_expand": 30 + sum(1 for r in rows if r["subkind"] == "calc"),
        "by_template": {t: sum(1 for r in rows if r["template"] == t) for t in ("T1", "T2", "T3", "T4", "T5", "T6")},
        "devices": sorted({r["device"] for r in rows}),
        "gold_rule": "全部由代码计算，数值口径 ±0.06 绝对容差；不调用任何模型",
        "source": "参数池沿用 scripts/kb/data/*.py 的设备/部件/指标口径；数值为合成测量值",
        "out": str(OUT_TSV.relative_to(ROOT)),
    }
    OUT_STATS.parent.mkdir(parents=True, exist_ok=True)
    OUT_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
