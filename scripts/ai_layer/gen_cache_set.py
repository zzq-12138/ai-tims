#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成语义缓存评测集（300 条 = 50 族 × 6 行）：
  1 条标准问法（canonical，作为缓存种子）
  3 条同义改写（paraphrase，应命中）
  1 条近邻负例（hard_neg，同设备/同子系统、不同部件或指标，不应命中）
  1 条无关对照（unrelated，其他设备的指标，不应命中）

数据全部来自项目知识库条目（part/metric/spec），gold 为规格里的数值片段（| 分隔，答案需全部包含）。

输出（独立文件，不覆盖 route_set.tsv）：
    scripts/ai_layer/data/cache_set.tsv
    docs/paper/ai应用层/cache_set_stats.json

用法：
    python3 scripts/ai_layer/gen_cache_set.py
"""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from data import pm, aoi, coat, lam, etch, reflow, mes, spi, wave, xray  # noqa: E402

OUT_TSV = ROOT / "scripts" / "ai_layer" / "data" / "cache_set.tsv"
OUT_STATS = ROOT / "docs" / "paper" / "ai应用层" / "cache_set_stats.json"

DEVICES = [pm, aoi, coat, lam, etch, reflow, mes, spi, wave, xray]
SEED = 20261107
FAMILIES = 50

NUM_RE = re.compile(r"\d+(?:[.．]\d+)?")


def norm(s):
    s = (s or "").strip()
    s = s.replace("～", "-").replace("~", "-").replace("—", "-").replace("–", "-").replace("－", "-")
    return s.replace("．", ".").replace(" ", "")


def spec_gold(spec):
    """规格 -> 数值片段列表；范围/±/≥ 都拆成独立数字，答案必须全部出现。
    丢弃 1 位数字（如 0、8），避免 '8' 命中 '0.8' 这类子串误判。"""
    nums = [norm(x) for x in NUM_RE.findall(spec or "")]
    nums = [n for n in nums if len(n) >= 2]
    # 去重且保持顺序
    seen, out = set(), []
    for n in nums:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def context_of(e):
    return (f"部件：{e['part']}；指标：{e['metric']}；规格要求：{e['spec']}"
            f"（来源：{e['_device']} / {e['key']}）")


CANON = [
    "「{device}」的{part}{metric}规格要求是多少？",
    "请问{device}的{part}，{metric}标准是多少？",
    "帮我查一下{device}{part}的{metric}指标要求。",
]
PARA = [
    "生产线上{device}的{part}，{metric}要控制在什么范围？",
    "{device}的{part}这项，{metric}一般要求多少？",
    "我想确认{device}{part}的{metric}到底按什么标准执行。",
]
HARD = [
    "「{device}」的{part}{metric}规格要求是多少？",
    "请问{device}的{part}，{metric}标准是多少？",
]
UNREL = [
    "关于{device}，{part}的{metric}有什么要求？",
    "{device}这类设备的{part}，{metric}通常怎么定？",
]


def load_entries():
    rows = []
    for mod in DEVICES:
        device = mod.DEVICE["name"]
        for e in mod.DEVICE["entries"]:
            if not all(e.get(k) for k in ("key", "part", "metric", "spec")):
                continue
            gold = spec_gold(e["spec"])
            if not gold:
                continue
            rows.append({**e, "_device": device, "gold": gold})
    return rows


def main():
    rnd = random.Random(SEED)
    entries = load_entries()
    by_device = {}
    for e in entries:
        by_device.setdefault(e["_device"], []).append(e)

    # 抽 50 族：设备轮流取，避免某一台设备占满
    devices = list(by_device.keys())
    rnd.shuffle(devices)
    picked = []
    idx = 0
    while len(picked) < FAMILIES:
        dev = devices[idx % len(devices)]
        idx += 1
        pool = [e for e in by_device[dev] if e not in picked]
        if not pool:
            continue
        picked.append(rnd.choice(pool))

    rows = []
    stats = {"seed": SEED, "families": FAMILIES, "rows": 0, "devices": {}}
    for i, e in enumerate(picked, 1):
        fam = f"F{i:02d}"
        dev = e["_device"]
        gold = e["gold"]
        ctx = context_of(e)
        canon_q = CANON[i % len(CANON)].format(device=dev, part=e["part"], metric=e["metric"])
        rows.append([f"{fam}-C", fam, "canonical", dev, e["key"], e["part"], e["metric"],
                     canon_q, ctx, "|".join(gold)])

        for j, tpl in enumerate(PARA):
            q = tpl.format(device=dev, part=e["part"], metric=e["metric"])
            rows.append([f"{fam}-P{j + 1}", fam, "paraphrase", dev, e["key"], e["part"], e["metric"],
                         q, ctx, "|".join(gold)])

        # 近邻负例：同设备、优先同子系统，但数值与自己不同
        same = [x for x in by_device[dev]
                if x["key"] != e["key"] and set(x["gold"]).isdisjoint(set(gold))]
        same_sub = [x for x in same if x.get("subsystem") and x.get("subsystem") == e.get("subsystem")]
        neg = rnd.choice(same_sub or same)
        neg_q = HARD[i % len(HARD)].format(device=dev, part=neg["part"], metric=neg["metric"])
        rows.append([f"{fam}-N", fam, "hard_neg", dev, neg["key"], neg["part"], neg["metric"],
                     neg_q, context_of(neg), "|".join(neg["gold"])])

        # 无关对照：换一台设备
        other_devs = [d for d in devices if d != dev]
        other = rnd.choice(other_devs)
        pool = [x for x in by_device[other] if set(x["gold"]).isdisjoint(set(gold))]
        un = rnd.choice(pool)
        un_q = UNREL[i % len(UNREL)].format(device=other, part=un["part"], metric=un["metric"])
        rows.append([f"{fam}-U", fam, "unrelated", other, un["key"], un["part"], un["metric"],
                     un_q, context_of(un), "|".join(un["gold"])])

        stats["devices"][dev] = stats["devices"].get(dev, 0) + 1

    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_TSV.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")

    stats["rows"] = len(rows)
    stats["by_role"] = {
        "canonical": sum(1 for r in rows if r[2] == "canonical"),
        "paraphrase": sum(1 for r in rows if r[2] == "paraphrase"),
        "hard_neg": sum(1 for r in rows if r[2] == "hard_neg"),
        "unrelated": sum(1 for r in rows if r[2] == "unrelated"),
    }
    OUT_STATS.parent.mkdir(parents=True, exist_ok=True)
    OUT_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
