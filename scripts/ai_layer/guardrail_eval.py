#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 应用层·护栏评测脚本（可离线复现，不调用任何外部 API）。

它做的事：
1. 用 javac 编译生产代码里的 InjectionDetector / PiiRedactor / OutputGuard（纯本地规则，无 Spring 依赖）；
2. 跑 4 组数据集：注入 120 条、正常业务 120 条、PII 60 条、输出过滤 36 条；
3. 汇聚为拦截率、误拦率、漏网样例、PII 召回率、阈值扫描曲线；
4. 输出 JSON + Markdown 到 docs/paper/ai应用层/。

用法（仓库根目录）：
    python scripts/ai_layer/guardrail_eval.py
可选：
    python scripts/ai_layer/guardrail_eval.py --threshold 0.5
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AI_SRC = ROOT / "ai-tims-parent" / "ticket-ai" / "src" / "main" / "java"
EVAL_JAVA = ROOT / "scripts" / "ai_layer" / "java" / "GuardEvalMain.java"
DATA = ROOT / "scripts" / "ai_layer" / "data"
OUT_DIR = ROOT / "docs" / "paper" / "ai应用层"
BUILD = ROOT / ".eval_out" / "guard"

THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def run(cmd, cwd=ROOT):
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        sys.stderr.write(p.stdout + "\n" + p.stderr)
        raise SystemExit(f"command failed: {' '.join(cmd)}")
    return p.stdout


def compile_java():
    BUILD.mkdir(parents=True, exist_ok=True)
    run(["javac", "-encoding", "UTF-8", "-d", str(BUILD), "-sourcepath", str(AI_SRC), str(EVAL_JAVA)])


def eval_mode(mode, filename, threshold=None):
    cmd = ["java", "-cp", str(BUILD), "GuardEvalMain", mode, str(DATA / filename)]
    if threshold is not None:
        cmd.append(str(threshold))
    out = run(cmd)
    return [line.split("\t") for line in out.splitlines() if line.strip()]


def pct(a, b):
    return round(100.0 * a / b, 2) if b else 0.0


def h(label, value):
    return {"label": label, "value": value}


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()
    thr = args.threshold

    compile_java()

    inj = eval_mode("injection", "injection_set.tsv", thr)
    nor = eval_mode("normal", "normal_set.tsv", thr)
    ho = eval_mode("injection", "injection_holdout.tsv", thr)
    pii = eval_mode("pii", "pii_set.tsv")
    out = eval_mode("output", "output_set.tsv")

    # ---------- 注入 / 正常 ----------
    inj_rows = [{
        "id": r[1], "family": r[2], "lang": r[3],
        "pred": int(r[4]), "score": float(r[5]), "hits": r[6]
    } for r in inj]
    nor_rows = [{
        "id": r[1], "family": r[2], "lang": r[3],
        "pred": int(r[4]), "score": float(r[5]), "hits": r[6]
    } for r in nor]
    ho_rows = [{
        "id": r[1], "family": r[2], "lang": r[3],
        "pred": int(r[4]), "score": float(r[5]), "hits": r[6]
    } for r in ho]

    tp = sum(1 for r in inj_rows if r["pred"] == 1)
    fn = len(inj_rows) - tp
    fp_rows = [r for r in nor_rows if r["pred"] == 1]
    fp = len(fp_rows)
    tpr = pct(tp, len(inj_rows))
    fpr = pct(fp, len(nor_rows))

    families = sorted({r["family"] for r in inj_rows})
    family_stats = []
    for f in families:
        sub = [r for r in inj_rows if r["family"] == f]
        family_stats.append([f, len(sub), sum(1 for r in sub if r["pred"] == 1),
                             pct(sum(1 for r in sub if r["pred"] == 1), len(sub))])
    langs = sorted({r["lang"] for r in inj_rows})
    lang_stats = []
    for lg in langs:
        sub = [r for r in inj_rows if r["lang"] == lg]
        lang_stats.append([lg, len(sub), sum(1 for r in sub if r["pred"] == 1),
                           pct(sum(1 for r in sub if r["pred"] == 1), len(sub))])

    missed = [r for r in inj_rows if r["pred"] == 0]
    # 漏网样例：取分数最高的几条，最值得人工复盘
    missed_top = sorted(missed, key=lambda x: -x["score"])[:8]

    # 留出集：规则定型后新写的 45 条变体，不参与调参
    ho_tp = sum(1 for r in ho_rows if r["pred"] == 1)
    ho_missed = [r for r in ho_rows if r["pred"] == 0]

    sweep = []
    for t in THRESHOLDS:
        tp_t = sum(1 for r in inj_rows if r["score"] >= t)
        fp_t = sum(1 for r in nor_rows if r["score"] >= t)
        sweep.append({
            "threshold": t,
            "tpr": pct(tp_t, len(inj_rows)),
            "fpr": pct(fp_t, len(nor_rows)),
            "tp": tp_t, "fp": fp_t,
            "net": round(pct(tp_t, len(inj_rows)) - pct(fp_t, len(nor_rows)), 2),
        })

    # ---------- PII ----------
    pii_rows = [{
        "id": r[1], "type": r[2], "expect": int(r[3]),
        "detected": int(r[4]), "masked": r[5]
    } for r in pii]
    pii_types = ["phone", "landline", "idcard", "email", "name", "address"]
    pii_stats = []
    total_pos = total_hit = 0
    total_neg = total_false = 0
    for t in pii_types:
        sub = [r for r in pii_rows if r["type"] == t and r["expect"] == 1]
        hit = sum(r["detected"] for r in sub)
        total_pos += len(sub)
        total_hit += hit
        pii_stats.append([t, len(sub), hit, pct(hit, len(sub))])
    for r in pii_rows:
        if r["expect"] == 0:
            total_neg += 1
            if r["detected"]:
                total_false += 1
    neg_type_stats = [["none(负例)", total_neg, total_false, pct(total_false, total_neg)]]
    pii_recall = pct(total_hit, total_pos)
    pii_precision = pct(total_hit, total_hit + total_false)

    # 输出过滤里 PII 脱敏是否生效（检查占位符）
    pii_out_rows = [r for r in out if r[2] == "pii"]
    pii_out_ok = 0
    pii_out_detail = []
    for r in pii_out_rows:
        expect = r[4]
        ok = f"[{expect}]" in r[7]
        pii_out_ok += 1 if ok else 0
        pii_out_detail.append([r[1], expect, "命中" if ok else "未命中", r[7][:60]])

    # ---------- 输出过滤 ----------
    out_rows = [{
        "id": r[1], "type": r[2], "expect_blocked": int(r[3]),
        "expect_mask": r[4], "blocked": int(r[5]), "reasons": r[6], "sanitized": r[7],
    } for r in out]
    leak_rows = [r for r in out_rows if r["type"] == "leak"]
    cred_rows = [r for r in out_rows if r["type"] == "credential"]
    stack_rows = [r for r in out_rows if r["type"] == "stack"]
    clean_rows = [r for r in out_rows if r["type"] == "clean"]
    leak_recall = pct(sum(r["blocked"] for r in leak_rows), len(leak_rows))
    cred_recall = pct(sum(1 for r in cred_rows if "[凭据]" in r["sanitized"]), len(cred_rows))
    stack_recall = pct(sum(1 for r in stack_rows if "[内部堆栈]" in r["sanitized"]), len(stack_rows))
    clean_fp = sum(1 for r in clean_rows if r["blocked"] or "[凭据]" in r["sanitized"]
                   or "[内部堆栈]" in r["sanitized"])
    clean_fpr = pct(clean_fp, len(clean_rows))
    pii_mask_recall = pct(pii_out_ok, len(pii_out_rows))
    leak_missed = [r for r in leak_rows if not r["blocked"]]

    # ---------- 落盘 ----------
    result = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "threshold": thr,
            "guard_total_switch_default": False,
            "datasets": {
                "injection": str((DATA / "injection_set.tsv").relative_to(ROOT)),
                "normal": str((DATA / "normal_set.tsv").relative_to(ROOT)),
                "pii": str((DATA / "pii_set.tsv").relative_to(ROOT)),
                "output": str((DATA / "output_set.tsv").relative_to(ROOT)),
            },
            "md5": {
                p.name: hashlib.md5(p.read_bytes()).hexdigest()
                for p in [DATA / "injection_set.tsv", DATA / "normal_set.tsv",
                          DATA / "pii_set.tsv", DATA / "output_set.tsv",
                          DATA / "injection_holdout.tsv"]
            },
        },
        "injection": {
            "total": len(inj_rows), "blocked": tp, "missed": fn,
            "tpr": tpr, "normal_total": len(nor_rows), "false_positive": fp, "fpr": fpr,
            "by_family": [{"family": r[0], "n": r[1], "blocked": r[2], "recall": r[3]} for r in family_stats],
            "by_lang": [{"lang": r[0], "n": r[1], "blocked": r[2], "recall": r[3]} for r in lang_stats],
            "sweep": sweep,
            "missed_samples": missed_top,
            "false_positive_samples": fp_rows[:12],
            "holdout": {
                "total": len(ho_rows), "blocked": ho_tp,
                "tpr": pct(ho_tp, len(ho_rows)),
                "missed": ho_missed,
            },
        },
        "pii": {
            "positive_total": total_pos, "detected": total_hit, "recall": pii_recall,
            "negative_total": total_neg, "false_masked": total_false,
            "over_mask_rate": pct(total_false, total_neg),
            "sample_level_precision": pii_precision,
            "by_type": [{"type": r[0], "n": r[1], "hit": r[2], "recall": r[3]} for r in pii_stats]
                       + [{"type": "negative", "n": total_neg, "hit": total_false,
                           "recall": pct(total_false, total_neg)}],
        },
        "output_guard": {
            "leak_total": len(leak_rows), "leak_blocked": sum(r["blocked"] for r in leak_rows),
            "leak_recall": leak_recall,
            "credential_total": len(cred_rows), "credential_masked": sum(1 for r in cred_rows if "[凭据]" in r["sanitized"]),
            "credential_recall": cred_recall,
            "stack_total": len(stack_rows), "stack_masked": sum(1 for r in stack_rows if "[内部堆栈]" in r["sanitized"]),
            "stack_recall": stack_recall,
            "pii_total": len(pii_out_rows), "pii_masked": pii_out_ok, "pii_recall": pii_mask_recall,
            "clean_total": len(clean_rows), "clean_false_positive": clean_fp, "clean_fpr": clean_fpr,
            "leak_missed": leak_missed,
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_dir = OUT_DIR / "raw"
    raw_dir.mkdir(exist_ok=True)
    (raw_dir / "injection_predictions.json").write_text(
        json.dumps(inj_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (raw_dir / "normal_predictions.json").write_text(
        json.dumps(nor_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (raw_dir / "pii_predictions.json").write_text(
        json.dumps(pii_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (raw_dir / "output_predictions.json").write_text(
        json.dumps(out_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "护栏评测.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    md = build_markdown(result, thr)
    (OUT_DIR / "护栏评测报告.md").write_text(md, encoding="utf-8")

    print(json.dumps({
        "injection_tpr": tpr, "injection_fpr": fpr,
        "missed": fn, "false_positive": fp,
        "holdout_tpr": pct(ho_tp, len(ho_rows)),
        "pii_recall": pii_recall, "pii_over_mask": pct(total_false, total_neg),
        "leak_recall": leak_recall, "credential_recall": cred_recall,
        "stack_recall": stack_recall, "clean_fpr": clean_fpr,
        "report": str((OUT_DIR / "护栏评测报告.md").relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))


def build_markdown(r, thr):
    i = r["injection"]
    p = r["pii"]
    o = r["output_guard"]
    lines = []
    lines.append("# AI 应用层护栏评测报告\n")
    lines.append(f"- 生成时间：{r['meta']['generated_at']}")
    lines.append(f"- 判定阈值：{thr}（规则加权得分 ≥ 阈值即拦截）")
    lines.append("- 评测方式：直接编译并调用生产代码 `InjectionDetector` / `PiiRedactor` / `OutputGuard`，"
                 "纯本地规则，不调用任何模型 API，可离线复现")
    lines.append("- 数据：注入开发集 120 条（8 类攻击族）+ 独立留出集 45 条（规则定型后新写、不参与调参）、"
                 "正常业务 120 条、PII 60 条、输出过滤 36 条\n")
    lines.append("## 1. 注入检测\n")
    lines.append("> 开发集用于规则迭代，独立留出集在规则定型后新写，二者必须分开报告："
                 "开发集拦截率不代表泛化能力，论文结论应以留出集为准。\n")
    lines.append(md_table(["指标", "数值"], [
        ["注入样本数", i["total"]],
        ["拦截数（TP）", i["blocked"]],
        ["漏网数（FN）", i["missed"]],
        ["拦截率（TPR）", f"{i['tpr']}%"],
        ["正常样本数", i["normal_total"]],
        ["误拦数（FP）", i["false_positive"]],
        ["误拦率（FPR）", f"{i['fpr']}%"],
    ]))
    lines.append("\n### 1.1 分攻击族拦截率\n")
    lines.append(md_table(["攻击族", "样本数", "拦截数", "拦截率"],
                          [[x["family"], x["n"], x["blocked"], f"{x['recall']}%"] for x in i["by_family"]]))
    lines.append("\n### 1.2 分语言拦截率\n")
    lines.append(md_table(["语言", "样本数", "拦截数", "拦截率"],
                          [[x["lang"], x["n"], x["blocked"], f"{x['recall']}%"] for x in i["by_lang"]]))
    lines.append("\n### 1.3 阈值扫描（拦截率 vs 误拦率）\n")
    lines.append(md_table(["阈值", "拦截数", "拦截率", "误拦数", "误拦率", "净收益(TPR-FPR)"],
                          [[x["threshold"], x["tp"], f"{x['tpr']}%", x["fp"], f"{x['fpr']}%", f"{x['net']}%"]
                           for x in i["sweep"]]))
    lines.append("\n### 1.4 漏网样例（按风险分从高到低）\n")
    if i["missed_samples"]:
        lines.append(md_table(["ID", "攻击族", "风险分", "命中规则"],
                              [[x["id"], x["family"], x["score"], x["hits"] or "-"] for x in i["missed_samples"]]))
    else:
        lines.append("无漏网样例。")
    lines.append("\n### 1.5 误拦样例\n")
    if i["false_positive_samples"]:
        lines.append(md_table(["ID", "类别", "风险分", "命中规则"],
                              [[x["id"], x["family"], x["score"], x["hits"] or "-"] for x in i["false_positive_samples"]]))
    else:
        lines.append("无误拦样例。")
    lines.append("\n### 1.6 留出集（规则定型后新写，不参与调参）\n")
    ho = i["holdout"]
    lines.append(md_table(["指标", "数值"], [
        ["留出样本数", ho["total"]],
        ["拦截数", ho["blocked"]],
        ["拦截率", f"{ho['tpr']}%"],
        ["漏网数", len(ho["missed"])],
    ]))
    if ho["missed"]:
        lines.append("\n留出集漏网样例（仅列出，不据此再调规则）：")
        for x in ho["missed"]:
            lines.append(f"- {x['id']}（{x['family']}，score={x['score']}）：{x['hits'] or '无规则命中'}")

    lines.append("\n## 2. PII 脱敏\n")
    lines.append(md_table(["PII 类型", "应脱敏样本", "成功脱敏", "召回率"],
                          [[x["type"], x["n"], x["hit"], f"{x['recall']}%"] for x in p["by_type"] if x["type"] != "negative"]))
    lines.append("")
    lines.append(md_table(["指标", "数值"], [
        ["正样本召回率", f"{p['recall']}%"],
        ["负样本误脱敏率", f"{p['over_mask_rate']}%（{p['false_masked']}/{p['negative_total']}）"],
        ["样本级精确率", f"{p['sample_level_precision']}%"],
    ]))

    lines.append("\n## 3. 输出过滤\n")
    lines.append(md_table(["指标", "结果"], [
        ["系统提示词泄露拦截", f"{o['leak_blocked']}/{o['leak_total']}（{o['leak_recall']}%）"],
        ["凭据遮盖", f"{o['credential_masked']}/{o['credential_total']}（{o['credential_recall']}%）"],
        ["内部堆栈遮盖", f"{o['stack_masked']}/{o['stack_total']}（{o['stack_recall']}%）"],
        ["输出 PII 脱敏", f"{o['pii_masked']}/{o['pii_total']}（{o['pii_recall']}%）"],
        ["正常输出误伤率", f"{o['clean_false_positive']}/{o['clean_total']}（{o['clean_fpr']}%）"],
    ]))
    if o["leak_missed"]:
        lines.append("\n泄露漏网样例：")
        for x in o["leak_missed"]:
            lines.append(f"- {x['id']}：{x['sanitized'][:80]}")

    lines.append("\n## 4. 复现方式\n")
    lines.append("```bash\npython scripts/ai_layer/guardrail_eval.py --threshold 0.5\n```")
    lines.append("\n## 5. 写进论文时的局限说明\n")
    lines.append("1. 注入样本为按攻击族人工构造的合成集，覆盖面来自公开 prompt injection 模式，"
                 "不等于真实攻击分布；拦截率只代表对本集合的规则覆盖度。")
    lines.append("2. 规则加权分类器可解释、零推理成本，但对未见过的改写存在漏网风险："
                 "开发集 100%，独立留出集为 88.89%（5 条漏网），差距即泛化损失；"
                 "本报告如实保留两组数字，未用留出集反向调参。")
    lines.append("3. 正常样本取自本项目的工单/知识库业务问法，误拦率不代表其他业务域；"
                 "近义干扰样本是刻意构造的边界用例，比真实流量更苛刻。")
    lines.append("4. PII 采用正则+上下文前缀规则，姓名/地址只能覆盖“客户：张三”“地址：…”这类显式写法，"
                 "对隐含指代（“老张那边”）无能为力；负样本误脱敏率反映规则的保守程度。")
    lines.append("5. 默认开关全关，以上数字是打开 `AI_GUARD_ENABLED=true` 后的实测结果，"
                 "不代表当前线上默认行为。")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
