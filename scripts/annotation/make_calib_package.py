#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 30 条校准包 + 外行复核表（问题二标注流水线，任务 1/2）。

产出：
  docs/paper/问题二/校准包_30条.md        给标注者：id + 摘要 + 分层类型（不含答案）
  docs/paper/问题二/外行复核表_C30.md     给外行：完整原文 + 3 个是/否/不确定问题
  docs/paper/问题二/外行复核表_C30.csv    同上，可用 Excel / 记事本填写
  annotation_set_v1.csv                   追加 calib_batch 列（这 30 条为 C30）
  annotation_data.js                      同步 calib 字段，供工作台筛选用

分层口径（合计 30）：
  含排除假设 10 · 正常单因单果 10 · 仅排除无最终根因 5 · 长文本 3 · 缺字段 1 · 错别字 1
选样：先按结构三层抽 25 条，再从余下样本补 长/缺字段/错别字 5 条；每层内按设备轮转，尽量均衡。
"""
import argparse
import csv
import json
import os
import random
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE, "docs", "paper", "问题二")
CSV_PATH = os.path.join(OUT_DIR, "annotation_set_v1.csv")
GOLD_PATH = os.path.join(OUT_DIR, "_gold_draft.jsonl")

HINTS = [
    "请只看文字，不需要判断修得好不好。",
    "按字面理解即可，不用猜现场实际情况。",
    "不确定就选「不确定」，不要勉强作答。",
    "只看这份记录写了什么，不用管你自己的工作经历。",
]

Q1 = "这段记录里，有没有说某个原因「检查过是好的」或「已排除」？"
Q2 = "最后有没有明确说「就是某个原因造成的」？"
Q3 = "最后认定的那个原因，前面有没有被说过「检查正常」？"


def load_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return list(r), r.fieldnames


def load_gold(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                g = json.loads(line)
                out[g["ticket_id"]] = g
    return out


def pick(rows, n, rng):
    """按设备轮转抽样，尽量均衡"""
    by_dev = defaultdict(list)
    for r in rows:
        by_dev[r["device_type"]].append(r)
    for d in by_dev:
        rng.shuffle(by_dev[d])
    out = []
    while len(out) < n:
        progressed = False
        for d in sorted(by_dev):
            if by_dev[d] and len(out) < n:
                out.append(by_dev[d].pop())
                progressed = True
        if not progressed:
            break
    return out


def short(text, limit=180):
    t = text.replace("\n", " ").strip()
    return t if len(t) <= limit else t[:limit] + f"……（共 {len(text)} 字，已截断，全文见外行复核表/工作台）"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261106)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    rows, fields = load_csv(CSV_PATH)
    gold = load_gold(GOLD_PATH)
    for r in rows:
        r["_st"] = (gold.get(r["ticket_id"]) or {}).get("structure", "")
        r["_sy"] = (gold.get(r["ticket_id"]) or {}).get("style", "")

    plan = [("含排除假设", lambda r: r["_st"] == "excluded", 10),
            ("正常单因单果", lambda r: r["_st"] == "normal", 10),
            ("仅排除无最终根因", lambda r: r["_st"] == "no_final", 5),
            ("长文本（>500 字）", lambda r: r["_sy"] == "long", 3),
            ("缺字段", lambda r: r["_sy"] == "missing", 1),
            ("错别字", lambda r: r["_sy"] == "typo", 1)]

    picked, used = [], set()
    for label, cond, n in plan:
        pool = [r for r in rows if cond(r) and r["ticket_id"] not in used]
        got = pick(pool, n, rng)
        for r in got:
            used.add(r["ticket_id"])
        if len(got) < n:
            print(f"[warn] {label} 只凑到 {len(got)}/{n} 条")
        picked.append((label, got))

    picked_ids = {r["ticket_id"] for _, g in picked for r in g}
    assert len(picked_ids) == sum(len(g) for _, g in picked), "抽样出现重复"

    # 1) CSV 追加 calib_batch
    for r in rows:
        r["calib_batch"] = "C30" if r["ticket_id"] in picked_ids else ""
    cols = [c for c in fields if c != "calib_batch"] + ["calib_batch"]
    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})

    # 2) annotation_data.js 同步 calib 字段
    data = [{"id": r["ticket_id"], "device": r["device_type"], "model": r["device_model"],
             "code": r["error_code"], "text": r["ticket_text"],
             "calib": r["calib_batch"]} for r in rows]
    meta = {"name": "问题二标注集 v1", "kind": "ticket", "count": len(data),
            "generated_by": "gen_seed_1000.py + make_calib_package.py", "seed": args.seed}
    with open(os.path.join(OUT_DIR, "annotation_data.js"), "w", encoding="utf-8") as f:
        f.write("window.ANNOTATION_META = " + json.dumps(meta, ensure_ascii=False) + ";\n")
        f.write("window.ANNOTATION_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n")

    # 3) 校准包_30条.md
    lines = ["# 校准包 30 条（C30）\n",
             "> 用途：今天先标这 30 条，只校准**「排除假设的证据」**与**「适用条件」**两个新槽位的口径。",
             "> 这里只告诉你每条属于哪一类，**不给答案**；答案在 `_gold_draft.jsonl`，不要提前看。",
             "> 标完后把 30 条导出 JSONL，用 `compute_kappa.py` 与真值比对。\n",
             "| 分层 | 条数 |", "|---|---|"]
    for label, g in picked:
        lines.append(f"| {label} | {len(g)} |")
    lines.append(f"| **合计** | **{len(picked_ids)}** |\n")
    dev = Counter(r["device_type"] for _, g in picked for r in g)
    lines.append("- 设备分布：" + " · ".join(f"{k} {v}" for k, v in dev.most_common()))
    lines.append("- 注意：长文本 / 缺字段 / 错别字三类是从前三类之外的样本里补的，"
                 "因此同一条既可能是「含排除假设」也可能是「长文本」，表里只标它的抽样归属。\n")

    n = 0
    for label, g in picked:
        lines.append(f"## {label}（{len(g)} 条）\n")
        lines.append("| # | ticket_id | 设备 | 型号 | 原文摘要 |")
        lines.append("|---|---|---|---|---|")
        for r in g:
            n += 1
            lines.append(f"| {n} | `{r['ticket_id']}` | {r['device_type']} | {r['device_model']} "
                         f"| {short(r['ticket_text']).replace('|', '｜')} |")
        lines.append("")
    with open(os.path.join(OUT_DIR, "校准包_30条.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # 4) 外行复核表（MD + CSV）
    order = [r for _, g in picked for r in g]
    md = ["# 外行复核表（30 条）\n",
          "## 这份表是做什么的\n",
          "我们有一批「设备维修记录」，想请两位不同的人各自独立判断同一件事，"
          "看看两个人的判断是不是一致。你是第二位判断人。\n",
          "- 你**不需要懂设备、不需要懂维修**，也不需要判断修得好不好，只回答「文字里有没有这么说」。",
          "- 每题只有三个选项：**是 / 否 / 不确定**。拿不准就选「不确定」，这不会扣分，"
          "硬猜反而会让结果失真。",
          "- 请不要参考任何人的答案，也不要和出题人讨论具体条目。\n",
          "## 怎么填\n",
          "1. 打开同目录的 `外行复核表_C30.csv`（Excel 或记事本都能开），或在打印出来的本页上打勾。",
          "2. 每条先读「工单原文」，再回答 1/2/3 三题。",
          "3. 全部填完把文件发回即可，不需要写理由。\n",
          "## 三道题在问什么（举例说明）\n",
          "> 例：「先怀疑是吸嘴堵了，拆下来吹通、复测仍偏移，排除吸嘴；最后查是导轨滑块磨损。」\n",
          f"1. {Q1} → 这里答**是**（说了吸嘴“排除”）。",
          f"2. {Q2} → 这里答**是**（明确说了“最后查是导轨滑块磨损”）。",
          f"3. {Q3} → 这里答**否**（最后认定的“导轨滑块磨损”前面没被说过正常）。\n",
          "---\n"]
    for i, r in enumerate(order, 1):
        body = "\n".join("> " + x for x in r["ticket_text"].splitlines())
        md += [f"### 第 {i} 条（编号 {r['ticket_id']}）\n", body, "",
               f"1. {Q1}　□ 是　□ 否　□ 不确定",
               f"2. {Q2}　□ 是　□ 否　□ 不确定",
               f"3. {Q3}　□ 是　□ 否　□ 不确定", "",
               f"> 提示：{HINTS[(i - 1) % len(HINTS)]}\n", "---\n"]
    with open(os.path.join(OUT_DIR, "外行复核表_C30.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    with open(os.path.join(OUT_DIR, "外行复核表_C30.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["编号", "工单原文", "问题1_有没有说检查过是好的或已排除",
                    "问题2_最后有没有明确说就是某个原因造成的",
                    "问题3_最后认定的原因前面是否被说过正常", "作答提示"])
        for i, r in enumerate(order, 1):
            w.writerow([r["ticket_id"], r["ticket_text"], "", "", "",
                        HINTS[(i - 1) % len(HINTS)]])

    print(f"[ok] 30 条：{', '.join(sorted(picked_ids))}")
    print(f"[ok] 结构分布：{dict(Counter(g['_st'] for g in order))}")
    print(f"[ok] 设备分布：{dict(dev)}")
    print(f"[ok] 已写入 校准包_30条.md / 外行复核表_C30.md / 外行复核表_C30.csv，CSV 已加 calib_batch 列")


if __name__ == "__main__":
    main()
