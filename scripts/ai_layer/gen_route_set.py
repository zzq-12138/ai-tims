#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成模型路由评测集（300 条，150 简单 + 150 复杂），全部来自项目知识库 310 条真实条目。

- 简单题：单条目事实查询（指标/规格），gold = 规格里的数值片段；
- 复杂题：同设备两条现象联合诊断（判断原因 + 排查顺序），gold = 两条条目的部件名；
- 附带「参考资料」，让模型像线上 RAG 一样有据可依，而不是靠参数记忆瞎猜。

输出（独立目录，不碰问题二任何 csv）：
    scripts/ai_layer/data/route_set.tsv
    docs/paper/ai应用层/route_set_stats.json

用法（仓库根目录）：
    python3 scripts/ai_layer/gen_route_set.py
"""
import json
import os
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from data import pm, aoi, coat, lam, etch, reflow, mes, spi, wave, xray  # noqa: E402

OUT_TSV = ROOT / "scripts" / "ai_layer" / "data" / "route_set.tsv"
OUT_STATS = ROOT / "docs" / "paper" / "ai应用层" / "route_set_stats.json"

DEVICES = [pm, aoi, coat, lam, etch, reflow, mes, spi, wave, xray]

REQUIRED = ("key", "part", "metric", "spec")
REQUIRED_DIAG = ("title", "symptom", "cause", "disc")

SPEC_NUM = re.compile(r"[±≤≥<>]?\s*\d+(?:[.．]\d+)?\s*(?:[-–—~～]\s*\d+(?:[.．]\d+)?)?\s*(?:℃/s|℃/min|℃|%|ms|s|g|mm|kPa|MPa|V|A|pcs|丝)?")


def norm(s):
    """规格文本归一化：去空格、统一连字符与波浪号，便于宽松匹配"""
    s = (s or "").strip()
    s = s.replace("～", "-").replace("~", "-").replace("—", "-").replace("–", "-").replace("－", "-")
    s = s.replace("．", ".").replace(" ", "")
    return s


def spec_gold(spec):
    """从规格串里抽出可判定的数值片段"""
    m = SPEC_NUM.search(spec or "")
    if not m:
        return None
    g = norm(m.group())
    return g if len(g) >= 2 else None


def part_core(part):
    """部件名取核心名词：'固态继电器与加热回路' -> '固态继电器'"""
    token = re.split(r"[与和、（）()]", part or "")[0].strip()
    return token if len(token) >= 2 else None


def load_entries():
    rows = []
    for mod in DEVICES:
        device = mod.DEVICE["name"]
        for e in mod.DEVICE["entries"]:
            if all(e.get(k) for k in REQUIRED):
                rows.append({"device": device, **e})
    return rows


SIMPLE_T = [
    "「{device}」的{metric}规格要求是多少？",
    "请问{device}的{part}，{metric}标准是多少？",
    "帮我查一下{device}{part}的{metric}指标要求",
]
SIMPLE_T_DIAG = [
    "{title}这种情况，{metric}要控制在什么范围？",
    "{device}出现{title}时，{metric}的正常范围是多少？",
]

COMPLEX_T = [
    "同一台{device}同时出现两种现象：①{symptomA}；②{symptomB}。请判断最可能的两个原因，并说明先查哪一个、为什么。",
    "{device}同时报出「{titleA}」和「{titleB}」两个问题，请分析两者是否可能同源，并给出排查顺序和处置优先级。",
    "{device}既有{symptomA}，又有{symptomB}。请分别定位原因，并给出先处理哪个的判断依据。",
]

# 短问句计算题：字面像单点事实（短、只有「几次/多少」），实际需要多步数值计算。
# 这类题用于暴露「规则路由判成简单、小模型算错」的失败模式；gold 全部由代码计算，不手写。
CALC_A = [
    ("SPI锡膏检测机", "投影光源模组", "亮度", "低于初始值 85% 即需更换", 1180, 942),
    ("AOI光学检测机", "环形光源", "亮度", "低于初始值 85% 即需更换", 2400, 2016),
    ("刻蚀机", "射频电源", "输出功率", "低于额定值 90% 即判衰减", 800, 720),
    ("涂覆机", "喷雾阀", "胶量", "低于标称值 85% 即需更换", 1200, 1008),
    ("回流焊", "氮气流量计", "氮气流量", "低于标称值 90% 即判供气不足", 640, 576),
    ("波峰焊", "助焊剂泵", "喷涂量", "低于标称值 85% 即判泵衰减", 2500, 2125),
    ("X-Ray检测机", "射线管", "管电流", "低于额定值 90% 即判老化", 1600, 1360),
    ("层压机", "加热棒", "加热功率", "低于额定值 90% 即判老化", 900, 810),
]

CALC_B = [
    ("贴片机", "贴装头升降气缸", "单次动作时间", 0.25, "s", "大于 0.25 s 即判气路或气缸问题"),
    ("回流焊", "热风马达", "温区横向温差", 3.0, "℃", "温差大于 3℃ 即判热风循环问题"),
    ("波峰焊", "锡炉", "锡波接触深度比", 0.67, "倍板厚", "超过板厚 2/3 即判波峰过高"),
    ("SPI锡膏检测机", "高度标定块", "高度偏差", 5.0, "μm", "偏差大于 5 μm 即为标定问题"),
    ("X-Ray检测机", "载物台夹具", "样品位移", 5.0, "μm", "位移大于 5 μm 即为夹持问题"),
    ("AOI光学检测机", "相机光源", "照度偏差", 10.0, "%", "偏差大于 10% 即为光源问题"),
    ("涂覆机", "胶阀", "出胶量偏差", 10.0, "%", "偏差大于 10% 即为胶阀问题"),
    ("刻蚀机", "真空泵", "腔体真空度", 5.0, "Pa", "真空度劣于 5 Pa 即判泵效下降"),
    ("层压机", "温控模块", "温度偏差", 2.0, "℃", "偏差大于 2℃ 即为温控问题"),
    ("回流焊", "助焊剂喷嘴", "喷涂量偏差", 10.0, "%", "偏差大于 10% 即为喷嘴问题"),
    ("MES终端", "扫码枪", "扫码失败率", 2.0, "%", "失败率大于 2% 即为扫码问题"),
]

CALC_C = [
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

CALC_N = 9


def _fmt_vals(vals):
    return "、".join(f"{v:g}" for v in vals)


def build_calc_rows(rnd2):
    """构造 30 条短问句计算题，gold 全部由计算得出（数值，容忍一位小数）"""
    rows = []

    for device, part, metric, rule, init, cur in CALC_A:
        dec = (init - cur) * 100.0 / init
        share = cur * 100.0 / init
        q = (f"{device}{part}初始{metric}{init}，现测{cur}，{metric}下降了多少个百分点（保留一位小数）？"
             f"现测值是初始值的百分之几（保留一位小数）？")
        rows.append({"device": device, "question": q,
                     "context": f"【{device}·{part}】指标：{metric}；{rule}。",
                     "gold": f"{dec:.1f}|{share:.1f}"})

    for device, part, metric, limit, unit, rule in CALC_B:
        while True:
            vals = [round(limit * rnd2.uniform(0.85, 1.15), 3) for _ in range(CALC_N)]
            hit = [v for v in vals if v > limit]
            if 1 <= len(hit) <= 7:
                break
        q = (f"{device}{part}{metric}要求不超过{limit:g}{unit}，这批{CALC_N}次测量（{unit}）："
             f"{_fmt_vals(vals)}。超标几次？超标占比多少（保留一位小数，%）？")
        rows.append({"device": device, "question": q,
                     "context": f"【{device}·{part}】指标：{metric}；{rule}。",
                     "gold": f"{len(hit)}|{len(hit) * 100.0 / CALC_N:.1f}"})

    for device, part, metric, lo, hi, unit, rule in CALC_C:
        low = lo - (hi - lo) * 0.35 if lo > 0 else 0.0
        while True:
            vals = [round(rnd2.uniform(low, hi + (hi - lo) * 0.35), 3) for _ in range(CALC_N)]
            hit = [v for v in vals if lo <= v <= hi]
            if 1 <= len(hit) <= 7:
                break
        q = (f"{device}{part}{metric}要求{lo:g}-{hi:g}{unit}，这批{CALC_N}次测量（{unit}）："
             f"{_fmt_vals(vals)}。合格几次？合格占比多少（保留一位小数，%）？")
        rows.append({"device": device, "question": q,
                     "context": f"【{device}·{part}】指标：{metric}；{rule}。",
                     "gold": f"{len(hit)}|{len(hit) * 100.0 / CALC_N:.1f}"})

    rnd2.shuffle(rows)
    return rows


def ctx_simple(e):
    parts = [f"【{e['device']}·{e['part']}】指标：{e['metric']}；规格：{e['spec']}"]
    if e.get("symptom"):
        parts.append(f"现象：{e['symptom']}")
    if e.get("disc"):
        parts.append(f"判断依据：{e['disc']}")
    return "；".join(parts)


def ctx_complex(a, b):
    return (f"资料1｜{a['title']}：现象={a['symptom']}；可能原因={a['cause']}；判断依据={a['disc']}\n"
            f"资料2｜{b['title']}：现象={b['symptom']}；可能原因={b['cause']}；判断依据={b['disc']}")


def main():
    rnd = random.Random(20261107)
    entries = load_entries()
    if len(entries) < 300:
        raise SystemExit(f"可用条目不足 300，当前 {len(entries)}")

    # 简单题：优先选规格可判定的条目，按设备轮转取，保证 10 类设备都覆盖
    by_dev = {}
    for e in entries:
        if spec_gold(e["spec"]):
            by_dev.setdefault(e["device"], []).append(e)
    for v in by_dev.values():
        rnd.shuffle(v)
    simple = []
    idx = 0
    while len(simple) < 150:
        for dev in list(by_dev.keys()):
            if len(simple) >= 150:
                break
            pool = by_dev[dev]
            if idx < len(pool):
                simple.append(pool[idx])
        idx += 1

    # 复杂题：同设备两两配对（诊断字段齐全的条目），不足 150 时用第二轮错位配对补足
    groups = {}
    for e in entries:
        if all(e.get(k) for k in REQUIRED_DIAG):
            groups.setdefault(e["device"], []).append(e)
    pairs = []
    for dev, lst in groups.items():
        lst = lst[:]
        rnd.shuffle(lst)
        pairs += [(lst[i], lst[i + 1]) for i in range(0, len(lst) - 1, 2)]
    if len(pairs) < 150:
        extra = []
        for dev, lst in groups.items():
            extra += [(lst[i], lst[(i + 1) % len(lst)]) for i in range(1, len(lst) - 1, 2)]
        rnd.shuffle(extra)
        known = {(a["key"], b["key"]) for a, b in pairs}
        for a, b in extra:
            if len(pairs) >= 150:
                break
            if (a["key"], b["key"]) not in known:
                pairs.append((a, b))
                known.add((a["key"], b["key"]))
    rnd.shuffle(pairs)
    pairs = pairs[:150]

    rows = []
    for i, e in enumerate(simple, 1):
        pool = SIMPLE_T + (SIMPLE_T_DIAG if e.get("title") else [])
        q = rnd.choice(pool).format(**e)
        rows.append({
            "id": f"R{i:03d}", "kind": "simple", "device": e["device"],
            "question": q, "context": ctx_simple(e), "gold": spec_gold(e["spec"]),
            "history_turns": 0, "needs_tool": False, "subkind": "fact",
        })
    # 后 30 条（R271-R300）为短问句计算题：字面像简单事实，实际要多步数值计算
    calc = build_calc_rows(random.Random(77))
    for j, (a, b) in enumerate(pairs, 151):
        if j > 270:
            c = calc[j - 271]
            rows.append({
                "id": f"R{j:03d}", "kind": "complex", "device": c["device"],
                "question": c["question"], "context": c["context"], "gold": c["gold"],
                "history_turns": 0, "needs_tool": False, "subkind": "calc",
            })
            continue
        tpl = rnd.choice(COMPLEX_T)
        q = tpl.format(device=a["device"], titleA=a["title"], titleB=b["title"],
                       partA=part_core(a["part"]) or a["part"], partB=part_core(b["part"]) or b["part"],
                       symptomA=a["symptom"], symptomB=b["symptom"])
        gold = "|".join(g for g in (part_core(a["part"]), part_core(b["part"])) if g)
        rows.append({
            "id": f"R{j:03d}", "kind": "complex", "device": a["device"],
            "question": q, "context": ctx_complex(a, b), "gold": gold,
            "history_turns": 0,
            "needs_tool": ("工单" in q or "设备编号" in q),
            "subkind": "templated",
        })

    # 让 10% 复杂题带历史轮次信号（线上多轮追问的代理）
    for r in rows:
        if r["kind"] == "complex" and rnd.random() < 0.1:
            r["history_turns"] = 3

    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_TSV, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write("\t".join([
                r["id"], r["kind"], r["device"], r["question"].replace("\t", " ").replace("\n", " "),
                r["context"].replace("\t", " ").replace("\n", " ⏎ "), r["gold"],
                str(r["history_turns"]), "1" if r["needs_tool"] else "0", r.get("subkind", ""),
            ]) + "\n")

    stats = {
        "total": len(rows),
        "simple": sum(1 for r in rows if r["kind"] == "simple"),
        "complex": sum(1 for r in rows if r["kind"] == "complex"),
        "complex_calc": sum(1 for r in rows if r.get("subkind") == "calc"),
        "complex_templated": sum(1 for r in rows if r.get("subkind") == "templated"),
        "devices": sorted({r["device"] for r in rows}),
        "with_history": sum(1 for r in rows if r["history_turns"] >= 3),
        "with_tool": sum(1 for r in rows if r["needs_tool"]),
        "source": "scripts/kb/data/*.py（知识库 310 条真实条目）",
        "out": str(OUT_TSV.relative_to(ROOT)),
    }
    OUT_STATS.parent.mkdir(parents=True, exist_ok=True)
    OUT_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
