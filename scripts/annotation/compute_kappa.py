#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
标注一致性（Cohen's κ）与抽检报告。

输入：两份独立标注（用户 / 第二标注者，或用户 / _gold_draft 复核），
支持 .jsonl（工作台导出）与 .csv（工作台导出/原始集）。

输出：Markdown 表（默认写到 stdout，可 --out 落文件），含
- 逐槽位存在性 κ（是否填写）
- 根因标签多分类 κ、设备类型多分类 κ
- 关系四分类 κ 与 conflict 二分类 κ（关系对文件自动识别）
- 切片：含/不含排除假设、长文本、缺字段、逐设备
- κ<0.6 时的处置建议（改手册哪条、重标哪批），不只报数字

用法：
  python3 scripts/annotation/compute_kappa.py --a user.jsonl --b b.jsonl --out report.md
  python3 scripts/annotation/compute_kappa.py --a user.jsonl --b b.jsonl \
      --data docs/paper/问题二/annotation_set_v1.csv --meta docs/paper/问题二/_gold_draft.jsonl
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

SLOT_KEYS = [
    ("device_type", "设备类型"),
    ("symptom", "现象"),
    ("root_cause", "根因"),
    ("measures", "措施"),
    ("verification", "验证结果"),
    ("conditions", "适用条件"),
    ("excluded_hypotheses", "排除假设"),
    ("has_final_root_cause", "有无最终根因"),
    ("is_excluded_hypothesis", "是否含排除假设"),
]
PAIR_KEYS = [("relation", "关系"), ("condition_overlap", "条件重叠"), ("uncertain", "存疑")]


def load(path):
    """返回 {id: record}；支持 jsonl / csv。"""
    if not path or not os.path.exists(path):
        sys.exit(f"文件不存在：{path}")
    recs = []
    if path.endswith(".csv"):
        with open(path, encoding="utf-8-sig", newline="") as f:
            recs = list(csv.DictReader(f))
    else:
        with open(path, encoding="utf-8") as f:
            t = f.read().strip()
        if t.startswith("["):
            recs = json.loads(t)
        else:
            recs = [json.loads(l) for l in t.splitlines() if l.strip()]
    out = {}
    for r in recs:
        rid = r.get("ticket_id") or r.get("pair_id") or r.get("id")
        if rid:
            out[str(rid)] = r
    return out


def norm(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        if not v:
            return ""
        parts = []
        for x in v:
            if isinstance(x, dict):
                parts.append("|".join(str(x.get(k, "")) for k in ("type", "value")) if "type" in x
                             else "|".join(str(x.get(k, "")) for k in ("hypothesis", "evidence")))
            else:
                parts.append(str(x))
        return " ; ".join(sorted(parts))
    return str(v).strip()


def exists(v):
    """槽位是否填写（1/0）"""
    if isinstance(v, (list, tuple)):
        return 1 if len(v) else 0
    s = norm(v)
    return 1 if s not in ("", "0", "[]", "null", "None") else 0


def cohen_kappa(pairs):
    """pairs: [(a, b)]，返回 (kappa, p_o, p_e, n)"""
    n = len(pairs)
    if n == 0:
        return 0.0, 0.0, 0.0, 0
    labels = sorted({x for p in pairs for x in p})
    idx = {l: i for i, l in enumerate(labels)}
    m = len(labels)
    cm = [[0] * m for _ in range(m)]
    for a, b in pairs:
        cm[idx[a]][idx[b]] += 1
    po = sum(cm[i][i] for i in range(m)) / n
    ra = [sum(cm[i]) / n for i in range(m)]
    cb = [sum(cm[i][j] for i in range(m)) / n for j in range(m)]
    pe = sum(ra[i] * cb[i] for i in range(m))
    k = 1.0 if pe == 1 else (po - pe) / (1 - pe)
    return k, po, pe, n


def band(k):
    if k < 0:
        return "差（低于随机）"
    if k < 0.21:
        return "轻微"
    if k < 0.41:
        return "一般"
    if k < 0.61:
        return "中等（需返修）"
    if k < 0.81:
        return "较高"
    return "很高"


def fmt(k, po, pe, n):
    return f"{k:.3f}", f"{po:.3f}", f"{pe:.3f}", str(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="标注者 A（用户）")
    ap.add_argument("--b", required=True, help="标注者 B / gold 复核")
    ap.add_argument("--data", default="", help="原始标注集 CSV，用于长文本切片")
    ap.add_argument("--meta", default="", help="_gold_draft.jsonl，用于结构/风格切片")
    ap.add_argument("--out", default="", help="Markdown 输出路径；留空则打印")
    args = ap.parse_args()

    A, B = load(args.a), load(args.b)
    common = sorted(set(A) & set(B))
    if not common:
        sys.exit("两份标注没有共同的 id，检查是否同一数据集")

    meta, textlen = {}, {}
    if args.meta:
        for k, v in load(args.meta).items():
            meta[k] = v
    if args.data:
        for k, v in load(args.data).items():
            textlen[k] = len(v.get("ticket_text") or v.get("text") or "")

    is_pair = any("relation" in A[i] or "relation" in B[i] for i in common)
    keys = PAIR_KEYS if is_pair else SLOT_KEYS

    lines = []
    w = lines.append
    w("# 标注一致性报告（Cohen's κ）\n")
    w(f"- 标注 A：`{args.a}`（{len(A)} 条）")
    w(f"- 标注 B：`{args.b}`（{len(B)} 条）")
    w(f"- 共同样本：**{len(common)}** 条；模式：**{'关系对' if is_pair else '工单槽位'}**")
    w("")
    w("## 1. 总表\n")
    w("| 字段 | κ | 一致率 p_o | 期望 p_e | n | 强度 | 结论 |")
    w("|---|---:|---:|---:|---:|---|---|")
    bad = []
    for key, name in keys:
        if is_pair:
            pairs = [(norm(A[i].get(key)), norm(B[i].get(key))) for i in common
                     if norm(A[i].get(key)) and norm(B[i].get(key))]
        elif key in ("device_type", "root_cause"):
            pairs = [(norm(A[i].get(key)), norm(B[i].get(key))) for i in common
                     if norm(A[i].get(key)) and norm(B[i].get(key))]
        else:
            pairs = [(str(exists(A[i].get(key))), str(exists(B[i].get(key)))) for i in common]
        k, po, pe, n = cohen_kappa(pairs)
        verdict = "达标" if k >= 0.6 else "**未达标，需处置**"
        if k < 0.6:
            bad.append((key, name, k))
        w(f"| {name} `{key}` | {k:.3f} | {po:.3f} | {pe:.3f} | {n} | {band(k)} | {verdict} |")
    w("")

    # 关系对专项
    if is_pair:
        w("## 2. 关系专项\n")
        pairs = [(norm(A[i].get("relation")), norm(B[i].get("relation"))) for i in common
                 if norm(A[i].get("relation")) and norm(B[i].get("relation"))]
        k, po, pe, n = cohen_kappa(pairs)
        w(f"- 四分类（duplicate/variant/conflict/unrelated）：κ = **{k:.3f}**，p_o={po:.3f}，n={n}")
        cb = [("conflict" if (norm(A[i].get("relation")) == "conflict") else "other",
               "conflict" if (norm(B[i].get("relation")) == "conflict") else "other")
              for i in common if norm(A[i].get("relation")) and norm(B[i].get("relation"))]
        k2, _, _, n2 = cohen_kappa(cb)
        w(f"- conflict 二分类：κ = **{k2:.3f}**，n={n2}")
        # 混淆
        cm = Counter((norm(A[i].get("relation")), norm(B[i].get("relation"))) for i in common
                     if norm(A[i].get("relation")) and norm(B[i].get("relation")))
        w("\n| A \\ B | duplicate | variant | conflict | unrelated |")
        w("|---|---:|---:|---:|---:|")
        for r1 in ("duplicate", "variant", "conflict", "unrelated"):
            cells = [cm.get((r1, r2), 0) for r2 in ("duplicate", "variant", "conflict", "unrelated")]
            w(f"| {r1} | " + " | ".join(str(c) for c in cells) + " |")
        w("")

    # 切片
    if not is_pair:
        w("## 3. 切片报告\n")
        slices = defaultdict(list)
        for i in common:
            st = (meta.get(i) or {}).get("structure")
            style = (meta.get(i) or {}).get("style")
            dev = norm(A[i].get("device_type")) or (meta.get(i) or {}).get("device_type", "")
            if st in ("excluded", "no_final"):
                slices["含排除假设"].append(i)
            elif st == "normal":
                slices["不含排除假设"].append(i)
            if style:
                slices["风格:" + style].append(i)
            n = textlen.get(i, 0)
            if n:
                slices["长文本(>500)" if n > 500 else "短文本(<=500)"].append(i)
            if dev:
                slices["设备:" + dev].append(i)

        w("| 切片 | n | 根因存在性 κ | 根因标签 κ | 排除假设 κ |")
        w("|---|---:|---:|---:|---:|")
        for name, ids in sorted(slices.items(), key=lambda x: (-len(x[1]), x[0])):
            p1 = [(str(exists(A[i].get("root_cause"))), str(exists(B[i].get("root_cause")))) for i in ids]
            p2 = [(norm(A[i].get("root_cause")), norm(B[i].get("root_cause"))) for i in ids
                  if norm(A[i].get("root_cause")) and norm(B[i].get("root_cause"))]
            p3 = [(str(exists(A[i].get("excluded_hypotheses"))),
                   str(exists(B[i].get("excluded_hypotheses")))) for i in ids]
            k1 = cohen_kappa(p1)[0]
            k2 = cohen_kappa(p2)[0] if len(p2) >= 10 else float("nan")
            k3 = cohen_kappa(p3)[0]
            k2s = "—" if k2 != k2 else f"{k2:.3f}"
            flag = " ⚠" if (k1 < 0.6 or k3 < 0.6) else ""
            w(f"| {name} | {len(ids)} | {k1:.3f}{flag} | {k2s} | {k3:.3f}{flag} |")
        w("")

    # 处置建议
    w("## 4. κ<0.6 的处置\n")
    if not bad:
        w("全部字段 κ ≥ 0.6，无需返修；可进入下一批标注或开始训练。")
    else:
        guide = {
            "symptom": "手册 §3.1：现象不得含原因/动作。改法：在手册补 3 条「现象 vs 根因」对照句，"
                       "并把本批所有把根因写进现象的样本重标。",
            "root_cause": "手册 §3.2/§4：根因必须是「经处置或验证确认」，排除假设与未验证猜测不得写入。"
                          "改法：强化「排除假设 → excluded_hypotheses」唯一出口，重标本批所有含排查过程的长文本样本。",
            "measures": "手册 §3.3：措施只写实际做过的动作、一条一个动作。改法：给出「动作 vs 结果」正反例各 2 条，重标本批 short/formal 样本。",
            "verification": "手册 §3.4：验证必须「方法+结果」，只有「已修复」须标存疑。"
                            "改法：规定无复测数据的样本一律 uncertain=1，重标本批 missing 风格样本。",
            "conditions": "手册 §3.5：条件分五类、无依据不得泛化。改法：先冻结条件词表再重标，"
                          "优先重标含参数区间的样本；本项历史覆盖率仅 0/56，预期最弱。",
            "excluded_hypotheses": "手册 §4：三信号（否定词/处置后无效/检测数据否定）。"
                                   "改法：把「怀疑/待查」与「已排除」做成对照卡，整批含排查叙述的样本重标。",
            "is_excluded_hypothesis": "同上，且需与 excluded_hypotheses 非空保持一致："
                                      "填了列表必须勾「有」，重标不一致样本。",
            "has_final_root_cause": "手册 §4.3 困难条：只有排除假设、无最终结论时根因留空且标 0。"
                                    "改法：单列 20 条困难条做二次校准，再重标本批 no_final 结构样本。",
            "device_type": "手册 §2 词表：设备类型只取 8 类受控词表。改法：改为下拉选择，重标写法不一致的样本。",
            "relation": "手册 §5：按「同因同条件→重复；同现象不同因且条件打架→冲突；同族但条件/措施分家→变体；"
                        "都不是→无关」顺序判。改法：用 §5.2 七个边界案例做 1 小时校准，重标本批 conflict/variant 混淆对。",
            "condition_overlap": "手册 §5.1：先判条件重叠再判关系。改法：明确「重叠/互斥/不适用」的判定依据，重标全部 conflict 对。",
            "uncertain": "存疑标注本身不一致，说明口径未收敛。改法：先对齐 uncertain 的触发条件（无复测数据/多故障/需仲裁），再重标。",
        }
        w("| 字段 | κ | 处置动作 |")
        w("|---|---:|---|")
        for key, name, k in bad:
            w(f"| {name} `{key}` | {k:.3f} | {guide.get(key, '回炉校准该字段口径后再重标。')} |")
        w("")
        w("**返修门槛**：单字段 κ<0.6 时，先改手册并做 20 条校准；改后 κ 仍<0.6，则该字段降级为"
          "「仅记录不训练」（例如条件字段），并在论文 Limitations 说明。")
        w("")
        w("**重标批次**：优先重标 κ 最低切片（上表 ⚠ 行）的全部样本，而不是随机抽 10%；"
          "切片样本量 <30 时补标到 30 再算 κ，避免小样本波动误判。")
    w("")
    w("## 5. 说明\n")
    w("- 存在性 κ 用「是否填写」的二分类；根因/设备/关系用标签原值多分类（未做语义归一，"
      "同义不同写法会被判为不一致，这本身也是口径问题）。")
    w("- 只统计两边都非空的样本；单边为空会在存在性 κ 中体现为不一致。")
    w("- n<30 的切片 κ 仅供定位问题，不作为达标依据。")

    text = "\n".join(lines) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入 {args.out}（{len(common)} 条，{len(bad)} 个字段未达标）")
    else:
        print(text)


if __name__ == "__main__":
    main()
