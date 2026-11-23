#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Holdout-3（100 条：80 calc / 20 simple）。

协议要求：本脚本必须在 det-trigger-v1 冻结之后才运行；题目与 gold 由代码确定性生成，
不调用模型；gold 另由 verify_holdout3_gold.py 只读题面/资料独立重算复核。

与既有两套题集的关系：
  - 不得复用 holdout_set.tsv（120 条迭代集）与 holdout2_set.tsv（100 条）的题干；
  - 数字签名（题面+资料里按出现顺序的数字序列）也不得与之相同；
  - 设备、指标、数据表达另起一套（如「工艺窗口」「制令」「越过上限」）。

题型（calc）：
  G1 达成率 + 缺口（比例 + 差值，含上月同期干扰）
  G2 环比成数（隐含基数，数字只在资料，含季度目标干扰）
  G3 工艺窗口合格数 + 合格占比（区间计数 + 占比）
  G4 均值 + 比下限高多少（多结果 + 制令/号线/班次/批量干扰）
  G5 越过上限个数 + 比上一批多百分之几（计数 + 变化率）
simple：
  G6 有数字但不必算（点检周期 / 保修期 / 额定功率 / 负责人 / 备件库位）
"""
import random
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
ORIG = DATA / "holdout_set.tsv"
H2 = DATA / "holdout2_set.tsv"
OUT = DATA / "holdout3_set.tsv"

RNG = random.Random(20261110)


def q(x, n):
    return Decimal(str(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)


def fmt(d):
    s = format(Decimal(d).normalize(), "f")
    return s if s != "-0" else "0"


def existing():
    qs, sigs = set(), set()
    for p in (ORIG, H2):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = line.split("\t")
            qs.add(c[5])
            sigs.add(tuple(re.findall(r"\d+(?:\.\d+)?", c[5] + c[6])))
    return qs, sigs


# ---------------------------------------------------------------- G1 达成率 + 缺口
G1 = [("回流炉", "过板量", "片"), ("波峰炉", "过板量", "片"), ("贴片机", "贴装点数", "点"),
      ("AOI", "检出板数", "片"), ("X-Ray", "检测批数", "批"), ("分板机", "分板片数", "片"),
      ("点胶机", "点胶点数", "点"), ("灌胶机", "灌胶件数", "件"), ("老化柜", "老化板数", "片"),
      ("清洗机", "清洗篮数", "篮"), ("镀膜机", "镀膜片数", "片"), ("划片机", "划片片数", "片"),
      ("编带机", "编带盘数", "盘"), ("烧录机", "烧录颗数", "颗"), ("印刷机", "印刷板数", "片"),
      ("波峰焊", "焊接件数", "件")]


def gen_g1():
    out = []
    for dev, metric, unit in G1:
        plan = RNG.randint(1800, 9800)
        done = int(plan * RNG.uniform(0.62, 0.97))
        prev = int(plan * RNG.uniform(0.55, 1.02))
        ratio = q(Decimal(done) / Decimal(plan) * 100, 1)
        gap = plan - done
        qs = ("%s这周%s，完成了计划的百分之几（保留一位小数）？离计划还差多少%s？"
              % (dev, metric, unit))
        ctx = "【%s·%s】本周计划 %d %s，实际完成 %d %s；上月同期 %d %s。" % (
            dev, metric, plan, unit, done, unit, prev, unit)
        out.append(("calc", "G1_达成率", "g1_attain_gap", dev, qs, ctx,
                    "%s|%d" % (fmt(ratio), gap), "numeric", 0, "True"))
    return out


# ---------------------------------------------------------------- G2 环比成数
G2 = [("空压站", "电耗", "kWh"), ("纯水站", "水耗", "t"), ("锅炉房", "蒸汽量", "t"),
      ("氮气站", "氮气量", "m³"), ("维修组", "耗材成本", "元"), ("产线", "加班工时", "h"),
      ("设备组", "维修次数", "次"), ("模具组", "换模次数", "次"), ("质检组", "检验批次", "批"),
      ("包装组", "包装材料", "kg"), ("清洗站", "清洗剂用量", "L"), ("润滑组", "润滑油用量", "L"),
      ("滤材组", "滤芯消耗", "个"), ("打磨组", "砂纸消耗", "张"), ("焊接组", "焊锡丝用量", "kg"),
      ("装配组", "胶带用量", "卷")]


def gen_g2():
    out = []
    forms = [
        "这个月%s的%s比上个月%s几成（保留一位小数）？",
        "和上月比，本月%s%s了几成（保留一位小数）？",
        "本月%s%s较上月%s了几成（保留一位小数）？",
        "跟上月相比，这月%s的%s%s了几成（保留一位小数）？",
    ]
    up_words = [("多", "多"), ("增加", "增加"), ("涨", "涨"), ("多", "多")]
    down_words = [("少", "少"), ("减少", "减少"), ("降", "降"), ("少", "少")]
    for i, (dev, metric, unit) in enumerate(G2):
        a = RNG.randint(40, 900)
        up = i % 4 != 3          # 3/4 增加、1/4 减少，避免「多几成」千篇一律
        b = int(a * RNG.uniform(1.08, 1.75)) if up else int(a * RNG.uniform(0.55, 0.92))
        target = int(max(a, b) * RNG.uniform(1.05, 1.4))
        gold = q(abs(Decimal(b - a)) / Decimal(a) * 10, 1)
        words = up_words if up else down_words
        w = words[i % 4][0]
        k = i % 4
        if k == 0:
            qs = "这个月%s的%s比上个月%s几成（保留一位小数）？" % (dev, metric, w)
        elif k == 1:
            qs = "和上月比，本月%s%s了几成（保留一位小数）？" % (metric, w)
        elif k == 2:
            qs = "本月%s%s较上月%s了几成（保留一位小数）？" % (dev, metric, w)
        else:
            qs = "跟上月相比，这月%s的%s%s了几成（保留一位小数）？" % (dev, metric, w)
        ctx = "【%s·%s台账】上月 %d %s，本月 %d %s；季度目标 %d %s。" % (
            dev, metric, a, unit, b, unit, target, unit)
        out.append(("calc", "G2_成数", "g2_month_cheng", dev, qs, ctx,
                    fmt(gold), "numeric", 0, "True"))
    return out


# ---------------------------------------------------------------- G3 区间合格数 + 占比
G3 = [("回流炉", "炉温", "℃"), ("波峰炉", "锡温", "℃"), ("贴片机", "贴装压力", "N"),
      ("AOI", "曝光时间", "ms"), ("X-Ray", "管电流", "mA"), ("分板机", "主轴电流", "A"),
      ("点胶机", "胶点重量", "mg"), ("灌胶机", "出胶量", "g"), ("老化柜", "老化电压", "V"),
      ("清洗机", "超声频率", "kHz"), ("镀膜机", "膜厚", "μm"), ("划片机", "进刀压力", "MPa"),
      ("编带机", "热封温度", "℃"), ("烧录机", "烧录电压", "V"), ("印刷机", "刮刀压力", "kg"),
      ("波峰焊", "预热温度", "℃")]


def gen_g3():
    out = []
    for dev, metric, unit in G3:
        n = RNG.choice([6, 7, 8, 9])
        lo = q(RNG.uniform(0.8, 7.5), 1)
        hi = q(lo + Decimal(str(RNG.uniform(0.6, 2.4))), 1)
        vals = []
        for _ in range(n):
            while True:
                v = q(lo - Decimal("0.4") + (hi - lo + Decimal("0.8")) * Decimal(str(RNG.random())), 1)
                if lo <= v <= hi:
                    break
            vals.append(v)
        hit = sum(1 for v in vals if lo <= v <= hi)
        if hit == n:                      # 保证至少一个不合格
            vals[0] = q(hi + Decimal("0.3"), 1)
            hit -= 1
        if hit == 0:
            vals[0] = q(lo + Decimal("0.1"), 1)
            hit = 1
        pct = q(Decimal(hit) / Decimal(n) * 100, 1)
        qs = ("这 %d 个%s读数：%s。落在工艺窗口内的有几个？合格占比多少（保留一位小数，%%）？"
              % (n, metric, "、".join(fmt(v) for v in vals)))
        ctx = "【%s·%s】工艺窗口 %s～%s %s；超出窗口即判废。" % (
            dev, metric, fmt(lo), fmt(hi), unit)
        out.append(("calc", "G3_区间", "g3_window_count", dev, qs, ctx,
                    "%d|%s" % (hit, fmt(pct)), "numeric", 0, "True"))
    return out


# ---------------------------------------------------------------- G4 均值 + 比下限高多少
G4 = [("回流炉", "各区温度", "℃", 1), ("贴片机", "吸嘴真空", "kPa", 1),
      ("AOI", "光源亮度", "lx", 1), ("X-Ray", "管电压", "kV", 1),
      ("分板机", "分板应力", "MPa", 2), ("点胶机", "胶量", "mg", 2),
      ("灌胶机", "灌胶时间", "s", 1), ("老化柜", "老化电流", "A", 2),
      ("清洗机", "漂洗压力", "MPa", 2), ("镀膜机", "真空度", "Pa", 1),
      ("划片机", "主轴转速", "rpm", 0), ("编带机", "编带张力", "N", 1),
      ("烧录机", "烧录电流", "mA", 1), ("印刷机", "印刷压力", "kg", 1),
      ("波峰焊", "波峰高度", "mm", 1), ("冷却塔", "回水温度", "℃", 1)]


def gen_g4():
    out = []
    for dev, metric, unit, dec in G4:
        n = RNG.choice([6, 7, 8])
        lo = q(RNG.uniform(0.9, 6.0), dec)
        span = Decimal(str(RNG.uniform(0.5, 2.2)))
        vals = [q(lo + span * Decimal(str(RNG.uniform(0.15, 1.1))), dec) for _ in range(n)]
        avg = q(sum(vals) / Decimal(n), 2)
        diff = q(avg - lo, 2)
        wo = "MO-202611%02d-%03d" % (RNG.randint(1, 28), RNG.randint(1, 200))
        qs = ("制令 %s，%d 号线第 %d 班，这批 %d 片%s依次为 %s %s。"
              "均值多少（保留两位小数）？比工艺下限 %s 高多少（保留两位小数）？"
              % (wo, RNG.randint(1, 6), RNG.randint(1, 3), n, metric,
                 "、".join(fmt(v) for v in vals), unit, fmt(lo)))
        ctx = "【%s·%s】工艺下限 %s %s，上限 %s %s；低于下限判返工。" % (
            dev, metric, fmt(lo), unit, fmt(q(lo + span + Decimal("1.5"), dec)), unit)
        out.append(("calc", "G4_均值差", "g4_mean_diff", dev, qs, ctx,
                    "%s|%s" % (fmt(avg), fmt(diff)), "numeric", 0, "True"))
    return out


# ---------------------------------------------------------------- G5 越限个数 + 环比
G5 = [("回流炉", "炉温", "℃"), ("波峰炉", "锡温", "℃"), ("贴片机", "贴装偏移", "mm"),
      ("AOI", "误判次数", "次"), ("X-Ray", "管电压", "kV"), ("分板机", "主轴振动", "μm"),
      ("点胶机", "胶量偏差", "mg"), ("灌胶机", "出胶偏差", "g"), ("老化柜", "老化电流", "A"),
      ("清洗机", "漂洗压力", "MPa"), ("镀膜机", "膜厚偏差", "μm"), ("划片机", "进刀偏差", "μm"),
      ("编带机", "热封偏差", "℃"), ("烧录机", "烧录电流", "mA"), ("印刷机", "刮刀压力", "kg"),
      ("波峰焊", "预热温度", "℃")]


def gen_g5():
    out = []
    for dev, metric, unit in G5:
        while True:
            n = RNG.choice([7, 8, 9])
            lim = q(RNG.uniform(0.9, 8.0), 1)
            vals = [q(lim * Decimal(str(RNG.uniform(0.80, 1.22))), 1) for _ in range(n)]
            over = [i for i, v in enumerate(vals) if v > lim]
            if 2 <= len(over) <= n - 1:
                break
        prev = RNG.randint(1, len(over) - 1)
        delta = q(Decimal(len(over) - prev) / Decimal(prev) * 100, 1)
        qs = ("这批 %d 个%s实测：%s。越过上限的有几个？比上一批的 %d 个多了百分之几（保留一位小数）？"
              % (n, metric, "、".join(fmt(v) for v in vals), prev))
        ctx = "【%s·%s】工艺上限 %s %s；越限即停机复检。" % (dev, metric, fmt(lim), unit)
        out.append(("calc", "G5_超限环比", "g5_over_delta", dev, qs, ctx,
                    "%d|%s" % (len(over), fmt(delta)), "numeric", 0, "True"))
    return out


# ---------------------------------------------------------------- G6 不必算
G6_DEV = [("点胶机", 1), ("激光打标机", 2), ("分板机", 3), ("老化测试柜", 4),
          ("超声波清洗槽", 5), ("贴片机", 6), ("回流炉", 7), ("X-Ray检测机", 8),
          ("灌胶机", 9), ("划片机", 10)]
NAMES = ["邓思远", "程书宁", "贺嘉禾", "骆知秋", "聂云舟"]

simple_q = [
    ("这台%s的点检周期是几天？", "【%s·点检卡】每 %d 天点检一次；本月已点检 %d 次。",
     lambda k: str(k), lambda d: (d % 20) + 5),
    ("%s的整机保修期是几个月？", "【%s·商务】整机保修 %d 个月，核心部件 %d 个月。",
     lambda k: str(k), lambda d: (d % 12) + 6),
    ("%s的额定功率是多少 kW？", "【%s·铭牌】额定功率 %d kW；待机功率 %d kW。",
     lambda k: str(k), lambda d: (d % 7) + 2),
]


def gen_g6():
    out = []
    idx = 0
    for dev, k in G6_DEV:
        idx += 1
        kind = (idx - 1) % 5
        if kind < 3:
            tpl_q, tpl_c, mk_gold, mk_val = simple_q[kind]
            val = mk_val(k)
            gold = mk_gold(val)
            other = val + RNG.randint(1, 9)
            ctx = tpl_c % (dev, val, other)
            qs = tpl_q % dev
        elif kind == 3:
            name = NAMES[idx % len(NAMES)]
            qs = "谁负责%s的日常点检？" % dev
            ctx = "【%s·责任表】负责人：%s；备件库位 C%d-%02d。" % (
                dev, name, RNG.randint(1, 5), RNG.randint(1, 30))
            gold = name
        else:
            qs = "%s的备件放在哪个库位？" % dev
            loc = "C%d-%02d" % (RNG.randint(1, 5), RNG.randint(1, 30))
            ctx = "【%s·备件】库位 %s；最低库存 %d 件。" % (dev, loc, RNG.randint(2, 9))
            gold = loc
        out.append(("simple", "G6_不必算", "g6_no_calc", dev, qs, ctx,
                    gold, "text", 0, "False"))
        idx2 = idx + 2
        kind2 = (idx2 - 1) % 5
        if kind2 < 3:
            tpl_q, tpl_c, mk_gold, mk_val = simple_q[kind2]
            val = mk_val(idx2)
            gold = mk_gold(val)
            ctx = tpl_c % (dev, val, val + RNG.randint(1, 9))
            qs = tpl_q % dev
        elif kind2 == 3:
            name = NAMES[(idx + 2) % len(NAMES)]
            qs = "谁负责%s的日常点检？" % dev
            ctx = "【%s·责任表】负责人：%s；备件库位 C%d-%02d。" % (
                dev, name, RNG.randint(1, 5), RNG.randint(1, 30))
            gold = name
        else:
            qs = "%s的备件放在哪个库位？" % dev
            loc = "C%d-%02d" % (RNG.randint(1, 5), RNG.randint(1, 30))
            ctx = "【%s·备件】库位 %s；最低库存 %d 件。" % (dev, loc, RNG.randint(2, 9))
            gold = loc
        out.append(("simple", "G6_不必算", "g6_no_calc", dev, qs, ctx,
                    gold, "text", 0, "False"))
    return out


def main():
    calc = gen_g1() + gen_g2() + gen_g3() + gen_g4() + gen_g5()
    simple = gen_g6()
    rows = [("H3-%03d" % (i + 1),) + r for i, r in enumerate(calc + simple)]

    qs, sigs = existing()
    for r in rows:
        assert r[5] not in qs, "题干复用: " + r[0]
        sig = tuple(re.findall(r"\d+(?:\.\d+)?", r[5] + r[6]))
        assert sig not in sigs, "数字签名复用: " + r[0]
    assert len(rows) == 100, len(rows)
    assert len({r[0] for r in rows}) == 100
    assert len({r[5] for r in rows}) == 100, "题干预重复"
    assert sum(1 for r in rows if r[1] == "calc") == 80
    assert sum(1 for r in rows if r[1] == "simple") == 20
    OUT.write_text("\n".join("\t".join(map(str, r)) for r in rows) + "\n", encoding="utf-8")
    print("wrote", OUT, len(rows))


if __name__ == "__main__":
    main()
