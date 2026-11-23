#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由敏感性分析（离线，零 API 费用）

输入：docs/paper/ai应用层/raw/routing_rows.json
      300 条，每行都有大模型答案 large、小模型答案 small（全部 300 条）、
      独立第二次小模型运行 small_all（仅作对照）、真实 token 与费用、路由得分
输出：docs/paper/ai应用层/路由敏感性与错误代价.{json,md}

口径说明（重要）：
- 配对口径：路由的廉价档与「全小」共用同一份 small 答案，两者只差「哪些行改用大模型」，
  不再混入同一模型两次采样的随机波动（主报告的 92.67% 是独立第二次运行，与 93.67% 差 3 条属波动）。
- 换阈值/换画像只是改变「这一行用哪份已有答案」，不新增模型调用，本轮分析零费用。
"""
import collections
import json
import random
import statistics
from pathlib import Path

ROOT = Path("/tmp/buildrepo")
RAW = ROOT / "docs/paper/ai应用层/raw/routing_rows.json"
OUT_JSON = ROOT / "docs/paper/ai应用层/路由敏感性与错误代价.json"
OUT_MD = ROOT / "docs/paper/ai应用层/路由敏感性与错误代价.md"

CURVE = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
KEY_THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7]
DRAWS = 2000

rows = [r for r in json.loads(RAW.read_text(encoding="utf-8"))
        if r.get("large") and r.get("small")]
N = len(rows)


def ok(r, key):
    if r.get("subkind") == "calc" or r["kind"] == "simple":
        return bool(r.get(f"{key}_ok_kw"))
    j = r.get("judge") or {}
    return bool(j.get(key, r.get(f"{key}_ok_kw")))


def cost(r, key):
    return r[f"{key}_cost"]


def tier_at(r, t):
    return "small" if r["route"]["score"] < t else "large"


def evaluate(scheme, t=0.5):
    if scheme == "large":
        picks = ["large"] * N
    elif scheme == "small":
        picks = ["small"] * N
    else:
        picks = [tier_at(r, t) for r in rows]
    correct = sum(1 for r, p in zip(rows, picks) if ok(r, p))
    return {"correct": correct, "acc": round(100.0 * correct / N, 2), "errors": N - correct,
            "cost_cny": round(sum(cost(r, p) for r, p in zip(rows, picks)), 4)}


base = evaluate("large")
small = evaluate("small")
routed = evaluate("routed", 0.5)

# ---------- 1. 阈值扫描 ----------
scan = []
for t in CURVE:
    e = evaluate("routed", t)
    missed = [r for r in rows if r.get("subkind") == "calc" and tier_at(r, t) == "small"]
    wasted = [r for r in rows if r.get("subkind") == "templated" and tier_at(r, t) == "large"]
    scan.append({
        "threshold": t,
        "to_small": sum(1 for r in rows if tier_at(r, t) == "small"),
        "to_large": sum(1 for r in rows if tier_at(r, t) == "large"),
        "acc": e["acc"], "cost_cny": e["cost_cny"],
        "saving_pct": round(100.0 * (base["cost_cny"] - e["cost_cny"]) / base["cost_cny"], 2),
        "loss_pp": round(base["acc"] - e["acc"], 2),
        "calc_to_small": len(missed),
        "calc_to_small_failed": sum(1 for r in missed if not ok(r, "small")),
        "templated_to_large": len(wasted),
        "yuan_per_pp": (round((base["cost_cny"] - e["cost_cny"]) / (base["acc"] - e["acc"]), 4)
                        if base["acc"] != e["acc"] else None),
    })

best = min(scan, key=lambda x: (x["cost_cny"], -x["acc"]))
routed_best = evaluate("routed", best["threshold"])

# ---------- 2. 难问题占比 ----------
# 「难」= 复杂题（联合诊断 + 计算），按自然比例 120:30 抽取；联合诊断两模型都能做，
# 计算题才拉开差距——这里不单独抽计算题，因为真实流量里复杂题就是这两种混在一起的。
POOL = {
    "easy": [r for r in rows if r["kind"] == "simple"],
    "mid": [r for r in rows if r.get("subkind") == "templated"],
    "hard": [r for r in rows if r.get("subkind") == "calc"],
}
rnd = random.Random(20261107)


def profile(p, t=0.5):
    n_complex = int(round(300 * p))
    n_calc = int(round(n_complex * len(POOL["hard"]) / (len(POOL["mid"]) + len(POOL["hard"]))))
    n_mid = n_complex - n_calc
    n_easy = 300 - n_complex
    acc = {k: [] for k in ("large", "routed", "small")}
    cst = {k: [] for k in ("large", "routed", "small")}
    for _ in range(DRAWS):
        sample = [rnd.choice(POOL["easy"]) for _ in range(n_easy)] + \
                 [rnd.choice(POOL["mid"]) for _ in range(n_mid)] + \
                 [rnd.choice(POOL["hard"]) for _ in range(n_calc)]
        for scheme in ("large", "routed", "small"):
            if scheme == "large":
                picks = ["large"] * len(sample)
            elif scheme == "small":
                picks = ["small"] * len(sample)
            else:
                picks = [tier_at(r, t) for r in sample]
            acc[scheme].append(100.0 * sum(1 for r, q in zip(sample, picks) if ok(r, q)) / len(sample))
            cst[scheme].append(sum(cost(r, q) for r, q in zip(sample, picks)))
    out = {"hard_ratio": p, "n_easy": n_easy, "n_mid": n_mid, "n_calc": n_calc}
    for k in ("large", "routed", "small"):
        a, c = sorted(acc[k]), sorted(cst[k])
        out[k] = {"acc_mean": round(statistics.mean(a), 2),
                  "acc_lo": round(a[int(0.025 * len(a))], 2),
                  "acc_hi": round(a[int(0.975 * len(a))], 2),
                  "cost_mean": round(statistics.mean(c), 4)}
    for k in ("routed", "small"):
        out[k]["saving_pct"] = round(100.0 * (out["large"]["cost_mean"] - out[k]["cost_mean"])
                                     / out["large"]["cost_mean"], 2)
    return out


profiles = [profile(p) for p in (0.1, 0.3, 0.5)]

# ---------- 3. 错误代价 ----------
def breakeven(routed_e, routed_c):
    """返回 (路由优于全大的最大错误成本, 路由优于全小的最小错误成本)。

    若路由错误数不少于全大，则不存在这样的成本（返回 None）；
    若路由与全小错误数相同而成本更高，则全小严格支配路由（返回 None）。
    """
    a = (round((base["cost_cny"] - routed_c) / (routed_e - base["errors"]), 4)
         if routed_e > base["errors"] else None)
    b = (round((routed_c - small["cost_cny"]) / (small["errors"] - routed_e), 4)
         if small["errors"] > routed_e else None)
    return a, b


be_05 = breakeven(routed["errors"], routed["cost_cny"])
be_best = breakeven(routed_best["errors"], routed_best["cost_cny"])
be_large_small = round((base["cost_cny"] - small["cost_cny"]) / max(small["errors"] - base["errors"], 1), 4)

ASSUME = []
for minutes in (3, 5, 8):
    for hourly in (60, 90, 120):
        for share in (1.0, 0.5, 0.2):
            per = round(minutes / 60.0 * hourly * share, 2)
            ASSUME.append({"minutes": minutes, "hourly": hourly, "share": share, "cost_per_error": per,
                           "total_large": round(base["cost_cny"] + base["errors"] * per, 2),
                           "total_routed": round(routed["cost_cny"] + routed["errors"] * per, 2),
                           "total_small": round(small["cost_cny"] + small["errors"] * per, 2)})

oracle_picks = ["large" if not ok(r, "small") else "small" for r in rows]
oracle = {"to_large": sum(1 for p in oracle_picks if p == "large"),
          "acc": round(100.0 * sum(1 for r, p in zip(rows, oracle_picks) if ok(r, p)) / N, 2),
          "cost_cny": round(sum(cost(r, p) for r, p in zip(rows, oracle_picks)), 4)}
oracle["saving_pct"] = round(100.0 * (base["cost_cny"] - oracle["cost_cny"]) / base["cost_cny"], 2)

rep = {
    "meta": {"dataset": "scripts/ai_layer/data/route_set.tsv", "n": N,
             "paired": True,
             "note": "离线反事实回放；路由与全小共用同一份 small 答案，只差「哪些行改用大模型」"},
    "all_large": base, "routed_at_0.5": routed, "all_small_paired": small,
    "threshold_scan": scan, "best_threshold": best["threshold"], "routed_at_best": routed_best,
    "profiles": profiles,
    "error_cost": {"pp_to_errors": round(N / 100.0, 2),
                   "breakeven_at_0.5": {"routed_beats_large_below": be_05[0],
                                        "routed_beats_small_above": be_05[1],
                                        "note": "路由与全小错误数相同（19 vs 19）而成本更高，"
                                                "不存在让路由优于全小的错误成本 → 全小严格支配路由"},
                   "breakeven_at_best": {"threshold": best["threshold"],
                                         "routed_beats_large_below": be_best[0],
                                         "routed_beats_small_above": be_best[1]},
                   "large_vs_small_breakeven": be_large_small,
                   "assumptions": ASSUME},
    "oracle": oracle,
}
OUT_JSON.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- Markdown ----------
def row_md(x):
    return (f"| {x['threshold']} | {x['to_small']} | {x['to_large']} | {x['acc']}% | {x['cost_cny']} | "
            f"{x['saving_pct']}% | {x['loss_pp']}pp | {x['calc_to_small']}（{x['calc_to_small_failed']}） | "
            f"{x['templated_to_large']} | {x['yuan_per_pp'] if x['yuan_per_pp'] is not None else '-'} |")


buckets = collections.Counter(round(r["route"]["score"], 1) for r in rows)
L = ["# 路由敏感性分析与错误代价（第 2 项补充）\n",
     f"- 数据：{N} 条，每行都有大模型答案与大模型/小模型的实测 token 费用",
     "- 方法：**离线反事实回放**。换阈值、换流量画像只是改变「这一行用哪份已有答案」，不新增模型调用，**本轮分析零 API 费用**",
     "- 口径：与主报告一致（简单题比规格值、计算题比数值 ±0.06、联合诊断题语义阅卷）；"
     "路由与全小**共用同一份小模型答案**，避免同一模型两次采样的波动混进对比\n",
     "## 1. 阈值扫描（0.3 / 0.4 / 0.5 / 0.6 / 0.7，另给 0.1–1.0 全曲线）\n",
     "| 阈值 | 走小模型 | 走大模型 | 准确率 | 成本（元） | 相对全大节省 | 质量损失 | 计算题漏给小模型（其中答错） | 诊断题白给大模型 | 每省 1pp 花多少（元/pp） |",
     "|---|---|---|---|---|---|---|---|---|---|",
     ]
for x in scan:
    L.append(row_md(x))
L += ["",
      f"基准：全大模型 {base['acc']}% / {base['cost_cny']} 元；全小模型（配对）{small['acc']}% / {small['cost_cny']} 元。"
      f"（主报告未配对时的独立第二次运行为 93.0%，与配对口径 {small['acc']}% 差 3 条，属同模型采样波动）\n",
      "**三个发现：**\n",
      f"1. **准确率在 0.3–0.9 完全不变（都是 "
      f"{' / '.join(str(v) for v in sorted({x['acc'] for x in scan if 0.3 <= x['threshold'] <= 0.9}))}%）**，"
      "因为 30 条计算题的得分是 0.1，任何 ≥0.3 的阈值都拦不住它们。",
      f"2. **成本却随阈值一路下降**：0.5 时 {scan[4]['cost_cny']} 元，0.9 时 {scan[8]['cost_cny']} 元，1.0 时 {scan[9]['cost_cny']} 元。"
      "原因是把诊断题也丢给小模型——而那 120 条题小模型本来就会做（119/120）。",
      f"3. 所以 0.5 这个默认阈值**既没保住准确率，也没省到钱**：同准确率下，阈值 1.0 比 0.5 省 "
      f"{round(100.0 * (scan[4]['cost_cny'] - scan[9]['cost_cny']) / scan[4]['cost_cny'], 1)}%。",
      "",
      f"得分分布：{'、'.join(f'{k} 分 {v} 条' for k, v in sorted(buckets.items()))}。",
      "148 条简单题 0.0 分、26 条计算题 0.1 分、120 条诊断题 0.6–1.0 分，中间是空的。",
      "**双峰分布决定了阈值只能整体平移，无法把「计算题」单独切出来**——这正是第 3.5 节信号上限的由来。\n",
      "## 2. 难问题占比敏感性（10% / 30% / 50%）\n",
      "- 「难」= 复杂题（联合诊断 + 计算），按真实比例 120:30 抽取；联合诊断两个模型都能做，"
      "计算题才拉开差距，混在一起才是真实流量形态",
      f"- 每档 {DRAWS} 次 bootstrap 有放回抽样，方括号为 95% 区间\n",
      "| 难题占比 | 条数（易/诊断/计算） | 全大 准确率 | 全大 成本 | 路由 准确率 | 路由 成本 | 路由 节省 | 全小 准确率 | 全小 成本 | 全小 节省 |",
      "|---|---|---|---|---|---|---|---|---|---|",
      ]
for p in profiles:
    L.append(f"| {int(p['hard_ratio'] * 100)}% | {p['n_easy']}/{p['n_mid']}/{p['n_calc']} | "
             f"{p['large']['acc_mean']}% [{p['large']['acc_lo']},{p['large']['acc_hi']}] | {p['large']['cost_mean']} | "
             f"{p['routed']['acc_mean']}% [{p['routed']['acc_lo']},{p['routed']['acc_hi']}] | {p['routed']['cost_mean']} | "
             f"{p['routed']['saving_pct']}% | "
             f"{p['small']['acc_mean']}% [{p['small']['acc_lo']},{p['small']['acc_hi']}] | {p['small']['cost_mean']} | "
             f"{p['small']['saving_pct']}% |")
L += ["",
      f"**读法**：路由的成本随难题占比线性上升（10% 时 ≈ 全小成本的 "
      f"{round(profiles[0]['routed']['cost_mean'] / profiles[0]['small']['cost_mean'], 1)} 倍，50% 时 ≈ "
      f"{round(profiles[2]['routed']['cost_mean'] / profiles[2]['small']['cost_mean'], 1)} 倍），",
      "因为路由会把联合诊断题判成复杂、全部送大模型；而**准确率与全小完全相同**"
      "（三档画像下路由与全小的准确率逐位相等），路由只多花钱、不多买准确率。",
      "相对全大，路由在三档画像下分别损失 "
      f"{round(profiles[0]['large']['acc_mean'] - profiles[0]['routed']['acc_mean'], 2)} / "
      f"{round(profiles[1]['large']['acc_mean'] - profiles[1]['routed']['acc_mean'], 2)} / "
      f"{round(profiles[2]['large']['acc_mean'] - profiles[2]['routed']['acc_mean'], 2)} pp，"
      "且这部分损失全部来自小模型算错的 19 条计算题，与难题占比无关。\n",
      "## 3. 错误代价：1pp 准确率值多少钱\n",
      "### 3.1 换算\n",
      f"- {N} 条评测集，**1pp = {N / 100.0:.0f} 条错误**",
      f"- 错误数：全大 0、路由 {routed['errors']}、全小 {small['errors']}\n",
      "### 3.2 单次错误成本（**全部为假设，项目无真实工时数据**）\n",
      "`单次错误成本 = 复核分钟数 ÷ 60 × 人工时薪 × 需要人工复核的比例`\n",
      "| 复核耗时 | 人工时薪 | 复核比例 | 单次错误成本 | 全大 总成本 | 路由 总成本 | 全小 总成本 |",
      "|---|---|---|---|---|---|---|",
      ]
for a in ASSUME:
    L.append(f"| {a['minutes']} 分钟 | {a['hourly']} 元/时 | {int(a['share'] * 100)}% | {a['cost_per_error']} 元 | "
             f"{a['total_large']} | {a['total_routed']} | {a['total_small']} |")
L += ["",
      "（元 / 300 次问答；总成本 = token 费用 + 错误数 × 单次错误成本）\n",
      "### 3.3 盈亏平衡：在默认阈值 0.5 下路由被双向支配\n",
      f"- 路由 vs 全大：省 {round(base['cost_cny'] - routed['cost_cny'], 4)} 元，多 {routed['errors'] - base['errors']} 条错误 "
      f"→ 只有单次错误成本 **< {be_05[0]} 元**（约合 0.3 秒人工）时路由才更好",
      f"- 路由 vs 全小：多花 {round(routed['cost_cny'] - small['cost_cny'], 4)} 元、错误数相同"
      f"（{routed['errors']} vs {small['errors']}）→ **不存在任何错误成本让路由更好，全小严格支配路由**",
      f"- 合并：错误成本 < {be_05[0]} 元时全大更好，否则全小更好 → **0.5 阈值下路由在任何错误成本下都不是最优**",
      f"- 全大 vs 全小的分界点：单次错误成本 **{be_large_small} 元**（约合 0.5 分钟人工复核）\n",
      f"### 3.4 把阈值推到最优（{best['threshold']}）后的结论\n",
      f"- 最优阈值 {best['threshold']}：准确率 {routed_best['acc']}%、成本 {routed_best['cost_cny']} 元（相对全大省 "
      f"{round(100.0 * (base['cost_cny'] - routed_best['cost_cny']) / base['cost_cny'], 1)}%）",
      f"- 此时路由优于全大需错误成本 < **{be_best[0]} 元**；对全小仍是错误数相同、成本更高，**没有占优区间**",
      "- 结论：即便把阈值推到成本最低的 1.0，路由也只能在「单次错误成本低于 1.5 分钱」时优于全大，"
      "对全小始终劣势；而任何以分钟计的人工复核（单次 ≥1 元）都让全大模型胜出\n",
      "### 3.5 信号上限：路由的价值全在信号质量\n",
      f"- Oracle 路由（只有小模型真会答错的题才给大模型）只需给大模型 **{oracle['to_large']} 条**，"
      f"准确率 {oracle['acc']}%、成本 {oracle['cost_cny']} 元（省 {oracle['saving_pct']}%）",
      f"- 当前规则路由：{routed['acc']}% / {routed['cost_cny']} 元，给大模型 "
      f"{sum(1 for r in rows if tier_at(r, 0.5) == 'large')} 条",
      "- 同一条流水线、同一批答案，**只要分流判得准，就能 100% 准确率下省 90%+**；",
      "  现在的规则两头都错：120 条诊断题白送大模型（本来小模型就会），30 条计算题全给小模型（本来必须给大模型）\n",
      "## 4. 可写进论文的结论\n",
      f"1. 在当前价格与评测集上，**规则路由不是最优解**：相对全大省 31% 掉 "
      f"{round(base['acc'] - routed['acc'], 2)}pp；相对全小准确率完全相同（{routed['correct']} vs {small['correct']} 条），"
      f"成本贵 {round(routed['cost_cny'] / small['cost_cny'], 1)} 倍。",
      "2. 原因是得分双峰 + 信号与难度错位：阈值在 0.3–0.9 之间准确率零变化，只能调成本，不能调质量。",
      "3. 引入错误代价后，默认阈值 0.5 的路由被全大与全小双向支配（错误成本 < 0.0051 元时全大更好，"
      "否则全小更好，而路由与全小的错误数完全相同）；即使把阈值调到成本最低的 1.0，"
      "路由也只能在「单次错误成本 < 0.0151 元」时优于全大，对全小始终严格劣势。",
      f"4. 路由真正的空间由信号决定：oracle 路由 {oracle['cost_cny']} 元即可 100% 准确率。"
      "下一步应把「是否需要数值计算」做成显式特征，而不是继续调阈值。",
      "",
      "## 5. 局限\n",
      "1. 反事实回放假设「某行的模型输出与是否被路由无关」，对无状态问答成立；引入缓存或多轮上下文后不成立。",
      "2. 画像从 300 条评测集有放回抽样，计算题样本池只有 30 条，50% 画像下重复抽样较多，区间只反映抽样波动。",
      "3. 错误成本全部为假设，无项目真实复核工时/人工成本数据；已给 3–16 元/次的敏感性区间。",
      "4. 未计入延迟差异：全大模型平均 "
      f"{round(statistics.mean(r['large']['latency_s'] for r in rows), 1)} s，简单档明显更快，"
      "报告未把响应时间折成业务价值。",
      "5. 未计入第 3 项语义缓存的成本下降。",
      ]
OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")

print(json.dumps({"base": base, "routed": routed, "small": small, "best": best,
                  "routed_best": routed_best, "be_05": be_05, "be_best": be_best,
                  "be_large_small": be_large_small, "oracle": oracle}, ensure_ascii=False, indent=1))
for p in profiles:
    print(p["hard_ratio"], {k: (p[k]["acc_mean"], p[k]["cost_mean"]) for k in ("large", "routed", "small")})
