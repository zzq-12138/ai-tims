#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构造真值自检（第一层）：只做可程序判定的自洽性检查，不做语义判断。

五项：
  1. 每条排除假设的证据必须能在工单原文中做子串匹配
  2. has_final_root_cause=0 时 root_cause 必须为空
  3. root_cause 不得等于/包含任何已排除假设（自相矛盾）
  4. 适用条件必须落到五类之一且值非空、非套话
  5. 槽位字段长度下限（防空壳标签）

产出：docs/paper/问题二/构造真值自检报告.md
"""
import argparse
import csv
import json
import os
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE, "docs", "paper", "问题二")
TYPES = {"device_model", "process_stage", "material_or_batch", "param_range", "precondition"}
EMPTY_COND = {"", "一般情况", "常规工况", "无", "全部", "通用", "其他"}
MIN = {"symptom": 8, "root_cause": 4, "measures_item": 4, "verification": 6,
       "excluded_evidence": 6, "excluded_hypothesis": 4}


def norm(s):
    return "".join(str(s).split()).replace("，", ",").replace("。", "").lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=os.path.join(OUT_DIR, "_gold_draft.jsonl"))
    ap.add_argument("--data", default=os.path.join(OUT_DIR, "annotation_set_v1.csv"))
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "构造真值自检报告.md"))
    args = ap.parse_args()

    text = {r["ticket_id"]: r["ticket_text"]
            for r in csv.DictReader(open(args.data, encoding="utf-8-sig"))}
    gold = [json.loads(l) for l in open(args.gold, encoding="utf-8") if l.strip()]

    c1_fail, c1_total, c1_by_style = [], 0, defaultdict(lambda: [0, 0])
    c2_fail = []
    c3_fail = []
    c4_fail, c4_total = [], 0
    c5_fail = []

    for g in gold:
        tid = g["ticket_id"]
        t = text.get(tid, "")
        st = g.get("style", "")

        # 1 证据子串匹配
        for h in g.get("excluded_hypotheses", []):
            c1_total += 1
            c1_by_style[st][1] += 1
            ev = h.get("evidence", "")
            if ev and norm(ev) in norm(t):
                c1_by_style[st][0] += 1
            else:
                c1_fail.append((tid, st, h.get("hypothesis", ""), ev))

        # 2 无根因则空
        if int(g.get("has_final_root_cause", 1)) == 0 and str(g.get("root_cause", "")).strip():
            c2_fail.append((tid, g["root_cause"]))

        # 3 根因不得等于已排除假设
        rc = norm(g.get("root_cause", ""))
        for h in g.get("excluded_hypotheses", []):
            hy = norm(h.get("hypothesis", ""))
            if rc and hy and (rc == hy or rc in hy or hy in rc):
                c3_fail.append((tid, g["root_cause"], h.get("hypothesis", "")))
                break

        # 4 适用条件
        conds = g.get("conditions", []) or []
        c4_total += 1
        bad = []
        if not conds:
            bad.append("无适用条件")
        for c in conds:
            tp, val = c.get("type", ""), str(c.get("value", "")).strip()
            if tp not in TYPES:
                bad.append(f"类型越界({tp})")
            if val in EMPTY_COND or len(val) < 2:
                bad.append(f"值为空或套话({val})")
        if bad:
            c4_fail.append((tid, "；".join(bad)))

        # 5 长度下限
        errs = []
        if len(str(g.get("symptom", "")).strip()) < MIN["symptom"]:
            errs.append("symptom 过短")
        if int(g.get("has_final_root_cause", 1)) == 1 and len(str(g.get("root_cause", "")).strip()) < MIN["root_cause"]:
            errs.append("root_cause 过短")
        ms = g.get("measures", []) or []
        if not ms:
            errs.append("measures 为空")
        elif any(len(str(m).strip()) < MIN["measures_item"] for m in ms):
            errs.append("measures 有过短项")
        if len(str(g.get("verification", "")).strip()) < MIN["verification"]:
            errs.append("verification 过短")
        for h in g.get("excluded_hypotheses", []):
            if len(str(h.get("hypothesis", "")).strip()) < MIN["excluded_hypothesis"]:
                errs.append("排除假设名过短")
            if len(str(h.get("evidence", "")).strip()) < MIN["excluded_evidence"]:
                errs.append("排除证据过短")
        if errs:
            c5_fail.append((tid, "；".join(sorted(set(errs)))))

    n = len(gold)
    r1 = (c1_total - len(c1_fail)) / c1_total if c1_total else 1.0
    r2 = (n - len(c2_fail)) / n
    r3 = (n - len(c3_fail)) / n
    r4 = (c4_total - len(c4_fail)) / c4_total
    r5 = (n - len(c5_fail)) / n

    rows = [("1 排除证据可在原文子串匹配", f"{c1_total - len(c1_fail)}/{c1_total}", r1),
            ("2 无最终根因时 root_cause 为空", f"{n - len(c2_fail)}/{n}", r2),
            ("3 根因不与已排除假设重合", f"{n - len(c3_fail)}/{n}", r3),
            ("4 适用条件属五类且非套话", f"{c4_total - len(c4_fail)}/{c4_total}", r4),
            ("5 槽位长度下限", f"{n - len(c5_fail)}/{n}", r5)]

    L = ["# 构造真值自检报告\n",
         "> 数据来源：`_gold_draft.jsonl`（生成时确定的真值，**不是人工标注**）与 `annotation_set_v1.csv`。",
         "> 本报告只做可程序判定的自洽性检查，不评价语义正确性；语义保真度由独立模型盲评（第二层）与 10 条人工抽检（第三层）承担。\n",
         f"- 样本数：{n}", f"- 检查项：5", "",
         "| # | 检查项 | 通过 | 通过率 | 结论 |", "|---|---|---|---|---|"]
    for name, frac, rate in rows:
        L.append(f"| {name.split(' ')[0]} | {name.split(' ', 1)[1]} | {frac} | **{rate:.2%}** | "
                 f"{'通过' if rate >= 0.95 else '未达标（>5%）'} |")

    L.append("\n## 1. 排除证据子串匹配（分风格）\n")
    L.append("| 风格 | 通过/总数 | 通过率 |\n|---|---|---|")
    for st, (ok, tot) in sorted(c1_by_style.items()):
        L.append(f"| {st} | {ok}/{tot} | {ok / tot:.1%} |")
    if c1_fail:
        L.append("\n不合格清单（最多 25 条）：\n")
        L.append("| ticket_id | 风格 | 假设 | 证据 |\n|---|---|---|---|")
        for tid, st, hy, ev in c1_fail[:25]:
            L.append(f"| {tid} | {st} | {hy} | {ev} |")
        why = Counter(st for _, st, _, _ in c1_fail)
        L.append(f"\n失败按风格分布：{dict(why)}。若集中在 typo/missing，说明**风格扰动只改了正文、没同步改证据**，"
                 f"属于生成器缺陷，不是数据噪声。")

    L.append("\n## 2. 无根因却填了根因\n" + ("无。\n" if not c2_fail else ""))
    for tid, rc in c2_fail[:25]:
        L.append(f"- {tid}：root_cause={rc}")
    L.append("\n## 3. 根因与已排除假设重合\n" + ("无。\n" if not c3_fail else ""))
    for tid, rc, hy in c3_fail[:25]:
        L.append(f"- {tid}：根因「{rc}」vs 已排除「{hy}」")
    L.append("\n## 4. 适用条件不合格\n" + ("无。\n" if not c4_fail else ""))
    for tid, why in c4_fail[:25]:
        L.append(f"- {tid}：{why}")
    L.append("\n## 5. 长度下限不合格\n" + ("无。\n" if not c5_fail else ""))
    for tid, why in c5_fail[:25]:
        L.append(f"- {tid}：{why}")

    bad = [r for r in rows if r[2] < 0.95]
    L.append("\n## 结论与生成器修正项\n")
    if not bad:
        L.append("五项全部 ≥95%，无需回改生成器；真值可直接用于训练与评测。")
    else:
        L.append("以下项未达 95%，**先修生成器再继续下游**：\n")
        fix = {"1": "生成器在做 typo/missing 扰动时，必须同步改写 `excluded_hypotheses[].evidence`，"
                   "或把证据字段限定为不受扰动的固定短语池（推荐后者，扰动只作用于现象/过程叙述）。",
               "2": "no_final 结构下强制清空 root_cause / root_cause_evidence。",
               "3": "生成器需保证 root_cause 与 alt（被排除假设）不在同一语义槽位重复。",
               "4": "条件池需剔除套话，且每条样本至少绑定 1 个具体条件。",
               "5": "对过短字段做生成前校验，不足则换模板或补细节。"}
        for name, frac, rate in bad:
            num = name.split(" ")[0]
            L.append(f"- **{name}**：{rate:.2%} → {fix.get(num, '回改模板')}")
    L.append("\n> 口径提醒：本报告通过率只说明「构造真值自洽」，不等于「语义正确」，"
             "更不等于人工标注一致性。\n")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"[ok] 写入 {args.out}")
    for name, frac, rate in rows:
        print(f"  {name}: {frac} = {rate:.2%}")
    if bad:
        print(f"[warn] {len(bad)} 项未达 95%，需回改生成器")


if __name__ == "__main__":
    main()
