#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Holdout-2：与 holdout_set.tsv 完全独立的新题（100 条）。

约束：
  - 不复用原 120 条的题干；设备/指标/数值/句式全部另起一套；
  - gold 由代码确定性计算，不调用模型；
  - 句式覆盖：新双结果、隐含基数（成数）、口语化多结果、多结果+干扰数字、有数字不必算。

列格式与 holdout_set.tsv 一致：
  id / slice / trap / template / device / question / context / gold / gold_type / history_turns / needs_tool
"""
import random
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG = HERE / "data" / "holdout_set.tsv"
OUT = HERE / "data" / "holdout2_set.tsv"

RNG = random.Random(20261107)


def q(x, n):
    return Decimal(str(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)


def fmt(d):
    s = format(d.normalize(), "f")
    return s if s != "-0" else "0"


def orig_rows():
    rows = []
    for line in ORIG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(line.split("\t"))
    return rows


# ---------------------------------------------------------------- W1 双结果（新句式）
POOL1 = [
    ("点胶机", "胶枪气压", "kPa"), ("激光打标机", "打标功率", "W"),
    ("超声波清洗槽", "清洗液温度", "℃"), ("真空镀膜机", "靶材电流", "A"),
    ("分板机", "主轴转速", "rpm"), ("植球机", "植球直径", "μm"),
    ("老化测试柜", "柜内温度", "℃"), ("锡膏搅拌机", "搅拌转速", "rpm"),
    ("氮气柜", "柜内湿度", "%RH"), ("传送带电机", "工作电流", "A"),
    ("冷却水机", "出水温度", "℃"), ("排风机", "运行频率", "Hz"),
    ("皮带张紧轮", "皮带张力", "N"), ("UV固化炉", "UV能量", "mJ/cm²"),
    ("镀层测厚仪", "镀层厚度", "μm"), ("分板机", "分板应力", "MPa"),
    ("点胶机", "出胶时间", "ms"), ("激光打标机", "打标对比度", "%"),
    ("清洗槽", "清洗液浓度", "%"), ("老化柜", "柜内湿度", "%RH"),
]
Q1 = ["上周点检记的是{d}{i} {x}{u}，这次复测 {y}{u}。掉了几个百分点（保留一位小数）？还剩原来的百分之几（保留一位小数）？",
      "把{d}的{i}从 {x} 调到 {y}（{u}）之后：掉了几个百分点（保留一位小数）？现在占原来的百分之几（保留一位小数）？",
      "昨天{d}{i}还是 {x}{u}，今天只有 {y}{u} 了。掉了几个百分点（保留一位小数）？还剩百分之几（保留一位小数）？"]


def gen_w1():
    out = []
    for k, (dev, ind, unit) in enumerate(POOL1):
        x = q(RNG.uniform(620, 3200), 1)
        drop = RNG.uniform(0.09, 0.31)
        y = q(x * Decimal(str(1 - drop)), 1)
        if y == x:
            y = x - Decimal("1.0")
        delta = q(abs(x - y) / x * 100, 1)
        pct = q(y / x * 100, 1)
        spec = int(q(pct, 0)) - 4
        qs = Q1[k % 3].format(d=dev, i=ind, x=fmt(x), y=fmt(y), u=unit)
        ctx = "【%s·%s】指标：%s；低于初始值 %d%% 即需检修。" % (dev, ind, ind, spec)
        out.append(("", "calc", "W1", "w1_new_pair", dev, qs, ctx,
                    "%s|%s" % (fmt(delta), fmt(pct)), "numeric", 0, "True"))
    return out


# ---------------------------------------------------------------- W2 隐含基数（成数）
POOL2 = [
    ("空压机", "耗电量", "kWh"), ("纯水机", "纯水用量", "L"),
    ("清洗槽", "清洗液补加量", "L"), ("氮气柜", "氮气消耗量", "m³"),
    ("老化柜", "耗电量", "kWh"), ("分板机", "刀具消耗量", "把"),
    ("点胶机", "胶水用量", "g"), ("打标机", "保护镜片消耗量", "片"),
    ("冷却水机", "补水量", "L"), ("空压机", "保养工时", "h"),
    ("产线", "停机分钟数", "min"), ("产线", "返修数量", "件"),
    ("产线", "报废数量", "件"), ("仓库", "领料次数", "次"),
    ("产线", "换线次数", "次"), ("分板机", "换刀次数", "次"),
    ("清洗槽", "换液次数", "次"), ("老化柜", "报警次数", "次"),
    ("点胶机", "清洗次数", "次"), ("打标机", "调机次数", "次"),
    ("空压机", "排水次数", "次"), ("纯水机", "换芯次数", "次"),
    ("产线", "加急单数", "件"), ("仓库", "盘点次数", "次"),
    ("产线", "抽检批次数", "批"),
]
Q2 = ["跟上个月比，这个月{d}的{m}多几成（保留一位小数）？",
      "和上一批比，这批的{m}多用了几成（保留一位小数）？",
      "这个月{m}跟去年同期比多几成（保留一位小数）？"]


def gen_w2():
    out = []
    for k, (dev, metric, unit) in enumerate(POOL2):
        a = q(RNG.uniform(8, 90), 1)
        b = q(a * Decimal(str(1 + RNG.uniform(0.10, 0.75))), 1)
        c = q((a + b) / 2, 1)
        gold = q(abs(b - a) / a * 10, 1)
        qs = Q2[k % 3].format(d=dev, m=metric)
        ctx = "【%s·%s台账】上个月 %s %s，这个月 %s %s；近三月均值 %s %s。" % (
            dev, metric, fmt(a), unit, fmt(b), unit, fmt(c), unit)
        out.append(("", "calc", "W2", "w2_implicit_base", dev, qs, ctx,
                    fmt(gold), "numeric", 0, "True"))
    return out


# ---------------------------------------------------------------- W3 口语化多结果
POOL3 = [
    ("涂布机", "烘箱温度", "℃"), ("清洗机", "漂洗压力", "MPa"),
    ("点胶机", "点胶量", "mg"), ("打标机", "打标深度", "μm"),
    ("分板机", "分板间隙", "mm"), ("植球机", "植球高度", "μm"),
    ("老化柜", "柜内温差", "℃"), ("冷却水机", "回水温度", "℃"),
    ("排风机", "风压", "Pa"), ("传送带", "跑偏量", "mm"),
    ("锡膏搅拌机", "搅拌扭矩", "N·m"), ("真空泵", "抽气速率", "L/s"),
    ("镀膜机", "真空度", "Pa"), ("UV固化炉", "光强", "mW/cm²"),
    ("贴标机", "贴标压力", "N"), ("清洗槽", "超声功率", "W"),
    ("点胶机", "胶点直径", "mm"), ("分板机", "主轴振动", "μm"),
    ("老化柜", "输入电压", "V"), ("涂布机", "卷绕张力", "N"),
]


def gen_w3():
    out = []
    for k, (dev, metric, unit) in enumerate(POOL3):
        n = RNG.choice([8, 9, 10])
        lim = q(RNG.uniform(0.8, 9.5), 2)
        while True:
            vals = []
            for _ in range(n):
                while True:
                    v = q(lim * Decimal(str(RNG.uniform(0.70, 1.35))), 2)
                    if v != lim:
                        break
                vals.append(v)
            hit = sum(1 for v in vals if v > lim)
            if 0 < hit < n:
                break
        gold = "%d|%s" % (hit, fmt(q(Decimal(hit) / Decimal(n) * 100, 1)))
        qs = "帮着瞅一眼这%d个%s读数：%s。超了几回？占多少（保留一位小数，%%）？" % (
            n, metric, "、".join(fmt(v) for v in vals))
        ctx = "【%s·%s】要求不超过 %s %s；超过即为异常，需停机复检。" % (dev, metric, fmt(lim), unit)
        out.append(("", "calc", "W3", "w3_colloquial_count", dev, qs, ctx,
                    gold, "numeric", 0, "True"))
    return out


# ---------------------------------------------------------------- W4 多结果 + 干扰数字
POOL4 = [
    ("回流炉", "加热区温度", "℃"), ("波峰炉", "锡炉温度", "℃"),
    ("点胶机", "胶量重量", "mg"), ("贴片机", "吸嘴真空", "kPa"),
    ("AOI", "光源亮度", "lx"), ("X-Ray", "管电压", "kV"),
    ("清洗机", "清洗时间", "s"), ("分板机", "进刀速度", "mm/s"),
    ("植球机", "球径", "μm"), ("打标机", "打标频率", "kHz"),
    ("老化柜", "老化电流", "A"), ("冷却水机", "水压", "bar"),
    ("真空泵", "极限真空", "Pa"), ("涂布机", "涂层厚度", "μm"),
    ("锡膏搅拌机", "搅拌时间", "min"),
]


def gen_w4():
    out = []
    for k, (dev, ind, unit) in enumerate(POOL4):
        n = RNG.choice([8, 9])
        lo = q(RNG.uniform(0.5, 6.0), 2)
        hi = q(lo + Decimal(str(RNG.uniform(0.4, 2.0))), 2)
        vals = [q(lo + (hi - lo) * Decimal(str(RNG.uniform(0.5, 1.15))), 2) for _ in range(n)]
        avg = q(sum(vals) / Decimal(n), 4)
        diff = q(avg - lo, 2)
        qs = ("工单 WO-202611%02d-%02d，%d 号线 %d 号工位，第 %d 版工艺，这批 %d 件：%s。"
              "平均是多少（保留两位小数）？比下限 %s 高多少（保留两位小数）？") % (
            RNG.randint(1, 28), RNG.randint(1, 60), RNG.randint(1, 6), RNG.randint(1, 12),
            RNG.randint(1, 8), n, "、".join(fmt(v) for v in vals), fmt(lo))
        ctx = "【%s·%s】合格范围 %s-%s %s；低于 %s 判异常。" % (
            dev, ind, fmt(lo), fmt(hi), unit, fmt(lo))
        gold = "%s|%s" % (fmt(q(avg, 2)), fmt(diff))
        out.append(("", "calc", "W4", "w4_multi_noise", dev, qs, ctx,
                    gold, "numeric", 0, "True"))
    return out


# ---------------------------------------------------------------- W5 有数字不必算
NAMES = ["周立群", "郝明远", "邵文琪", "陈亦航", "林树森"]
POOL5 = [("点胶机", "glue"), ("激光打标机", "laser"), ("分板机", "router"),
         ("老化测试柜", "burnin"), ("超声波清洗槽", "ultra")]


def gen_w5():
    out = []
    i = 0
    for dev, _ in POOL5:
        for kind in range(4):
            i += 1
            if kind == 0:
                days = RNG.choice([7, 10, 14, 21, 30])
                qs = "这台%s多久点检一次（天）？" % dev
                ctx = "【%s·点检卡】每 %d 天点检一次；本月已完成 %d 次。" % (
                    dev, days, RNG.randint(1, 3))
                gold = str(days)
            elif kind == 1:
                name = NAMES[(i - 1) % len(NAMES)]
                qs = "%s由谁负责？" % dev
                ctx = "【%s·责任表】负责人：%s；备件库位 B%d-%02d。" % (
                    dev, name, RNG.randint(1, 4), RNG.randint(1, 20))
                gold = name
            elif kind == 2:
                h = RNG.choice([480, 720, 960, 1200])
                qs = "规格书里写的最长连续运行时长是多少小时？"
                ctx = "【%s·规格书】最长连续运行 %d 小时；建议每 %d 小时保养一次。" % (
                    dev, h, RNG.choice([120, 240, 360]))
                gold = str(h)
            else:
                n = RNG.choice([24, 32, 36, 48])
                qs = "这批一共几件？"
                ctx = "【%s·工单】本批共 %d 件；起始序列号 SN-20261107-%03d。" % (
                    dev, n, RNG.randint(20, 80))
                gold = str(n)
            out.append(("", "simple", "W5", "w5_no_calc", dev, qs, ctx,
                        gold, "text", 0, "False"))
    return out


def main():
    rows = gen_w1() + gen_w2() + gen_w3() + gen_w4() + gen_w5()
    rows = [("H2-%03d" % (i + 1),) + r[1:] for i, r in enumerate(rows)]
    # 唯一性与独立性校验
    import re
    orig = orig_rows()
    oq = {r[5] for r in orig}
    oval = {tuple(re.findall(r"\d+(?:\.\d+)?", r[5] + r[6])) for r in orig}
    for r in rows:
        assert r[5] not in oq, "题干复用: " + r[0]
        sig = tuple(re.findall(r"\d+(?:\.\d+)?", r[5] + r[6]))
        assert not sig or sig not in oval, "数字序列复用: " + r[0]
    assert len(rows) == len({r[0] for r in rows}), "id 重复"
    assert len(rows) == 100, len(rows)
    OUT.write_text("\n".join("\t".join(map(str, r)) for r in rows) + "\n", encoding="utf-8")
    print("wrote", OUT, len(rows))


if __name__ == "__main__":
    main()
