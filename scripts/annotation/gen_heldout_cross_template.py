#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨模板留出集（任务 3）：用与训练集不重叠的模板族 + 不同随机种子生成 200 条工单。

用途：只做测试，**不进训练**。检验模型学的是「能力」还是「模板」。
- 训练集（`gen_seed_1000.py`）模板族：formal / colloquial / missing / typo / long
- 留出集（本脚本）模板族：dispatch / wechat / logbook（三套全新框架，句式不共用）
- 随机种子：20261107（训练集 20261106）；上下文索引整体偏移 137，打散 线别/班次/责任人 组合
- 故障事实（现象/根因/措施/验证/条件）与训练集共用同一份场景表，保证标签体系一致

产出（默认 docs/paper/问题二/）：
- heldout_cross_template.csv     测试用工单（含 style/structure 元信息，不含答案）
- _heldout_gold_draft.jsonl      构造真值（与训练集同 schema）
- _heldout_stats.json            分层统计

用法：
  python3 scripts/annotation/gen_heldout_cross_template.py
  python3 scripts/annotation/gen_heldout_cross_template.py --n 200 --seed 20261107
"""
import argparse
import csv
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_seed_1000 import (ALT2_POOL, DEVICES, LINE_POOL, OP_POOL, SCEN,  # noqa: E402
                           SHIFT_POOL, apply_phrase_fixes, assert_no_banned, sync_evidence)

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE, "docs", "paper", "问题二")
STYLES = ["dispatch", "wechat", "logbook"]
OFFSET = 137


def ctx(i):
    j = i + OFFSET
    return LINE_POOL[j % len(LINE_POOL)], SHIFT_POOL[(j // 3) % 3], OP_POOL[(j // 5) % 5]


def build_dispatch(s, i, struct):
    line, shift, op = ctx(i)
    alt2 = ALT2_POOL[(i + OFFSET) % len(ALT2_POOL)]
    code = f" / 错误码 {s['code']}" if s["code"] else ""
    head = (f"维修派工单 WO-2026-{i + 1:04d}\n"
            f"设备：{line}{s['device']}（{s['model']}）{code}\n"
            f"故障现象：{s['symptom']}\n")
    if struct == "normal":
        return (head
                + f"初步方向：按{s['cause']}方向排查。\n"
                + f"现场核对：{op}到场后核对相关部件，{s['evidence']}，确认{s['cause']}。\n"
                + f"处置：1) {s['m1']}；2) {s['m2']}。\n"
                + f"复验：{s['verify']}。\n"
                + f"关闭：{shift}归档，产线恢复。")
    if struct == "excluded":
        return (head
                + f"初步方向：按{s['alt']}方向排查，拆检并更换备件后复测无改善，排除{s['alt']}。\n"
                + f"续查：{op}重新核对，{s['evidence']}。\n"
                + f"判定：{s['cause']}。\n"
                + f"处置：1) {s['m1']}；2) {s['m2']}。\n"
                + f"复验：{s['verify']}。\n"
                + f"关闭：{shift}归档，异常方向已回填工单。")
    return (head
            + f"初步方向：按{s['alt']}方向排查，更换备件后复测无改善，排除{s['alt']}；"
            + f"按{alt2}方向复核，调取批次与环境记录后仍无改善，排除{alt2}。\n"
            + f"续查：{op}已执行{s['m1']}、{s['m2']}，出现频次下降但未消除。\n"
            + f"复验：{s['verify']}（间歇复现，无稳定复测数据）。\n"
            + f"关闭：暂未定位，转厂家工程师，设备降速运行，{shift}归档。")


def build_wechat(s, i, struct):
    line, shift, op = ctx(i)
    alt2 = ALT2_POOL[(i + OFFSET) % len(ALT2_POOL)]
    head = f"群里报：{line}{s['device']}出问题了，{s['symptom']}，{op}你去看下。\n"
    if struct == "normal":
        return (head
                + f"{op}：到了，查了相关部件，{s['evidence']}，就是{s['cause']}。\n"
                + f"{op}：{s['m1']}，{s['m2']}，都弄完了。\n"
                + f"{op}：{s['verify']}，先这样。")
    if struct == "excluded":
        return (head
                + f"{op}：先按{s['alt']}弄的，拆了换了还是那样，排除{s['alt']}。\n"
                + f"{op}：后来接着查，{s['evidence']}，才确定是{s['cause']}。\n"
                + f"{op}：{s['m1']}，{s['m2']}。\n"
                + f"{op}：{s['verify']}，可以复线了。")
    return (head
            + f"{op}：先怀疑{s['alt']}，换了试了没用，排除{s['alt']}；又猜{alt2}，查了批次还是那样，{alt2}也排除。\n"
            + f"{op}：{s['m1']}、{s['m2']}都做了，好点但没断根。\n"
            + f"{op}：先降速跑着，等厂家来看。{shift}的记一下。")


def build_logbook(s, i, struct):
    line, shift, op = ctx(i)
    alt2 = ALT2_POOL[(i + OFFSET) % len(ALT2_POOL)]
    head = (f"设备维修履历\n"
            f"时间：2026-{(i % 12) + 1:02d}-{(i % 27) + 1:02d} {shift}\n"
            f"设备：{line}{s['device']} / {s['model']}\n"
            f"记录人：{op}\n"
            f"故障现象：{s['symptom']}\n")
    if struct == "normal":
        return (head
                + f"处理经过：到场后逐项核对，{s['evidence']}，判定为{s['cause']}。\n"
                + f"维修动作：{s['m1']}；{s['m2']}。\n"
                + f"结果验证：{s['verify']}。\n"
                + f"归档说明：本条已归档，纳入下一版点检表。")
    if struct == "excluded":
        return (head
                + f"处理经过：先按{s['alt']}方向处置，更换备件后复测无改善，排除{s['alt']}；"
                + f"随后继续核查，{s['evidence']}，判定为{s['cause']}。\n"
                + f"维修动作：{s['m1']}；{s['m2']}。\n"
                + f"结果验证：{s['verify']}。\n"
                + f"归档说明：排除项已登记，供同类故障检索。")
    return (head
            + f"处理经过：先按{s['alt']}方向处置，复测无改善，排除{s['alt']}；"
            + f"再按{alt2}方向复核，仍无改善，排除{alt2}。\n"
            + f"维修动作：已执行{s['m1']}、{s['m2']}。\n"
            + f"结果验证：{s['verify']}（间歇复现）。\n"
            + f"归档说明：根因未定，转厂家工程师，持续跟踪。")


BUILDERS = {"dispatch": build_dispatch, "wechat": build_wechat, "logbook": build_logbook}


def make_plan(seed, n):
    """5 设备 × 40 条；每设备 24 正常 / 12 含排除 / 4 仅排除无根因；风格轮转。"""
    rnd = random.Random(seed)
    per_dev = n // len(DEVICES)
    plan = []
    k = 0
    for d in DEVICES:
        cells = ["normal"] * int(per_dev * 0.6) + ["excluded"] * int(per_dev * 0.3)
        cells += ["no_final"] * (per_dev - len(cells))
        rnd.shuffle(cells)
        for c in cells:
            plan.append(dict(device=d, struct=c, style=STYLES[k % len(STYLES)], idx=k))
            k += 1
    rnd.shuffle(plan)
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--seed", type=int, default=20261107)
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    plan = make_plan(args.seed, args.n)
    by_device = {d: [s for s in SCEN if s["device"] == d] for d in DEVICES}
    rows, gold = [], []
    for k, p in enumerate(plan):
        pool = by_device[p["device"]]
        s = pool[(k * 3 + OFFSET) % len(pool)]      # 与训练集取场景的顺序错开
        text = apply_phrase_fixes(BUILDERS[p["style"]](s, p["idx"], p["struct"]))
        tid = f"H{k + 1:04d}"
        line, shift, op = ctx(p["idx"])
        rows.append(dict(ticket_id=tid, device_type=s["device"], device_model=s["model"],
                         error_code=s["code"], ticket_text=text,
                         style=p["style"], structure=p["struct"]))
        g = dict(ticket_id=tid, device_type=s["device"], device_model=s["model"],
                 error_code=s["code"], topic=s["topic"], style=p["style"], structure=p["struct"],
                 has_final_root_cause=0 if p["struct"] == "no_final" else 1,
                 symptom=s["symptom"],
                 root_cause="" if p["struct"] == "no_final" else s["cause"],
                 root_cause_evidence="" if p["struct"] == "no_final" else s["evidence"],
                 measures=[s["m1"], s["m2"]],
                 verification=s["verify"],
                 conditions=[dict(type=t, value=v) for t, v in s["cond"]],
                 excluded_hypotheses=(
                     [dict(hypothesis=s["alt"], evidence="更换备件后复测，现象未改善")]
                     + ([] if p["struct"] != "no_final" else
                        [dict(hypothesis=ALT2_POOL[(p["idx"] + OFFSET) % len(ALT2_POOL)],
                              evidence="核对批次与环境记录并调整，复测未改善")])
                     if p["struct"] in ("excluded", "no_final") else []),
                 unverified_hypotheses=[], line=line, shift=shift, operator=op)
        g["excluded_hypotheses"] = sync_evidence(text, g["excluded_hypotheses"])
        gold.append(g)

    with open(os.path.join(args.out_dir, "heldout_cross_template.csv"), "w",
              encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(args.out_dir, "_heldout_gold_draft.jsonl"), "w", encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    stats = dict(total=len(gold), seed=args.seed,
                 by_device={d: sum(1 for g in gold if g["device_type"] == d) for d in DEVICES},
                 by_style={st: sum(1 for g in gold if g["style"] == st) for st in STYLES},
                 by_structure={st: sum(1 for g in gold if g["structure"] == st)
                               for st in ("normal", "excluded", "no_final")},
                 min_text_len=min(len(r["ticket_text"]) for r in rows),
                 max_text_len=max(len(r["ticket_text"]) for r in rows),
                 avg_text_len=round(sum(len(r["ticket_text"]) for r in rows) / len(rows), 1))
    with open(os.path.join(args.out_dir, "_heldout_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    assert_no_banned([r["ticket_text"] for r in rows])
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
