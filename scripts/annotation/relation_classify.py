#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四类语义关系判别（P1）：相似度 + 结构化字段规则 + 条件互斥 + LLM 判别。

标签：duplicate / variant / conflict / unrelated
数据：annotation_relation_v1.csv（300 对，relation 列为空）+ _gold_relation_draft.jsonl（构造真值）
输出：docs/paper/问题二/关系判别/relation_pred_{mode}.jsonl、metrics.json、关系判别评测.md

三档模式（同一脚本可复跑，便于论文做消融）：
  sim   只用余弦阈值（现网三分档的等价物）
  rule  余弦 + 现象/根因/措施/条件规则（无 LLM）
  full  规则高置信直接判定；低置信或灰区样本交给 LLM，最后用条件互斥规则收口

口径：真值为 construction-based gold（生成时确定），不是人工标注；
      指标只能写「与构造真值的一致性」，不得写成人工标注 macro-F1。
"""
import argparse
import csv
import importlib.util
import json
import os
import re
import time
import urllib.request
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE, "docs", "paper", "问题二")
REL_DIR = os.path.join(OUT_DIR, "关系判别")
CSV_PATH = os.path.join(OUT_DIR, "annotation_relation_v1.csv")
GOLD_PATH = os.path.join(OUT_DIR, "_gold_relation_draft.jsonl")
KEY_PATH = "/home/dev/secrets/zhipu_api_key"
GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-4-flash"
LABELS = ("duplicate", "variant", "conflict", "unrelated")

LLM_SYSTEM = (
    "你是设备维修知识库的语义关系判别器。给定两条知识条目 A 与 B，判断二者关系，"
    "只能取以下四类之一：\n"
    "duplicate：同一知识的不同表述（现象、根因、措施、条件基本一致，可合并或跳过）；\n"
    "variant：现象相同或相近，但根因/措施/适用条件不同，两条都应保留（建变体边，不合并）；\n"
    "conflict：现象相同且适用条件重叠，但根因结论互斥（同象异因，必须挂冲突队列等人工裁决）；\n"
    "unrelated：设备、工序或故障族不同，不构成可比关系。\n"
    "判定顺序：先看现象是否同一，再看条件是否重叠，最后看根因是否互斥。\n"
    "只输出 JSON：{\"relation\":\"duplicate|variant|conflict|unrelated\","
    "\"condition_overlap\":\"yes|no|unknown\",\"confidence\":0.0-1.0,\"reason\":\"一句话\"}"
)

FIELD_RE = re.compile(r"(故障现象|现象|原因|处理|处置过程|处置|验证|适用条件)[：:]\s*(.+)")
CTX_RE = re.compile(r"(设备型号|产线|工艺段)[：:]\s*([^；;。\n]+)")
CTX_TYPE = {"设备型号": "device_model", "产线": "line", "工艺段": "process_stage"}
ANTI_RE = re.compile(r"^(适用条件|设备型号|产线|工艺段)[：:]")


def strip_artifacts(text):
    """反构造检验：删掉「适用条件」与设备/产线/工艺段上下文行。

    这两类行是构造集里 variant/conflict 的强标签信号（variant 必带适用条件、
    conflict 必共享上下文），删掉后模型只能靠现象/根因/措施语义判断。
    """
    return "\n".join(l for l in (text or "").split("\n") if not ANTI_RE.match(l.strip()))


def norm(s):
    return re.sub(r"[\s，。；：、,.;:!?！？\"'（）()\[\]【】]", "", str(s or "")).lower()


def dice(a, b):
    a, b = norm(a), norm(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    ga = Counter(a[i:i + 2] for i in range(max(1, len(a) - 1)))
    gb = Counter(b[i:i + 2] for i in range(max(1, len(b) - 1)))
    inter = sum((ga & gb).values())
    return 2.0 * inter / (sum(ga.values()) + sum(gb.values()))


def parse_kb(text):
    """把构造语料模板解析为字段：现象/原因/措施/验证/条件。"""
    f = {"symptom": "", "cause": "", "measures": [], "verify": "", "conditions": {}}
    for line in (text or "").split("\n"):
        m = FIELD_RE.match(line.strip())
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key in ("现象", "故障现象"):
                f["symptom"] = val.rstrip("。")
            elif key == "原因":
                f["cause"] = val.rstrip("。")
            elif key in ("处理", "处置过程", "处置"):
                f["measures"] = [x.strip(" 。") for x in re.split(r"[；;]", val) if x.strip(" 。")]
            elif key == "验证":
                f["verify"] = val.rstrip("。")
            elif key == "适用条件":
                f["conditions"]["explicit"] = val.rstrip("。")
        for k, v in CTX_RE.findall(line):
            f["conditions"][CTX_TYPE[k]] = v.strip()
    return f


def cond_state(a, b):
    """返回 overlap / exclusive / one_sided / compatible / unknown。

    缺失条件按 unknown 处理，不臆断互斥；一方有条件、一方无条件 → one_sided（条件不同）。
    """
    ca, cb = a["conditions"], b["conditions"]
    if not ca and not cb:
        return "unknown"
    if bool(ca) != bool(cb):
        return "one_sided"
    shared = set(ca) & set(cb)
    for t in shared:
        if norm(ca[t]) != norm(cb[t]):
            return "exclusive"
    if shared and len(shared) == len(ca) == len(cb):
        return "overlap"
    return "compatible"


def measure_overlap(a, b):
    if not a["measures"] or not b["measures"]:
        return 0.0
    hit, used = 0, set()
    for x in a["measures"]:
        best, bi = 0.0, -1
        for j, y in enumerate(b["measures"]):
            if j in used:
                continue
            d = dice(x, y)
            if d > best:
                best, bi = d, j
        if best >= 0.6:
            used.add(bi)
            hit += 1
    return hit / max(len(a["measures"]), len(b["measures"]))


# ---------------- 规则判别 ----------------
def rule_decide(A, B, sim):
    """返回 (label, confidence, reason)；无法高置信判定时 label=None。"""
    sym_d = dice(A["symptom"], B["symptom"])
    cause_d = dice(A["cause"], B["cause"])
    sym_same = sym_d >= 0.8 or (
        norm(A["symptom"]) and norm(B["symptom"]) and
        (norm(A["symptom"]) in norm(B["symptom"]) or norm(B["symptom"]) in norm(A["symptom"])))
    cause_same = cause_d >= 0.7 or (
        norm(A["cause"]) and norm(B["cause"]) and
        (norm(A["cause"]) in norm(B["cause"]) or norm(B["cause"]) in norm(A["cause"])))
    mov = measure_overlap(A, B)
    ver_d = dice(A["verify"], B["verify"])
    cs = cond_state(A, B)

    if sym_same and cause_same and (mov >= 0.5 or (not A["measures"] and not B["measures"])):
        return "duplicate", 0.95, "现象/根因一致且措施重叠(sym=%.2f,cause=%.2f,meas=%.2f)" % (sym_d, cause_d, mov)

    # 换词改写会拉低现象/根因的字面重合，此时用「高余弦 + 措施/验证同源」兜底
    if sim >= 0.95 and mov >= 0.5 and ver_d >= 0.6:
        return "duplicate", 0.85, "高相似且措施/验证同源(sim=%.2f,meas=%.2f,ver=%.2f)" % (sim, mov, ver_d)

    if sym_same and not cause_same:
        if cs in ("one_sided", "exclusive"):
            return "variant", 0.85, "同现象不同根因且适用条件不同(%s,cause=%.2f)" % (cs, cause_d)
        return "conflict", 0.85, "同现象不同根因且条件不互斥(%s,cause=%.2f)" % (cs, cause_d)

    if not sym_same:
        if sim < 0.75 and not cause_same and mov < 0.2:
            return "unrelated", 0.9, "现象不同且无共享根因/措施(sim=%.2f)" % sim
        return None, 0.5, "灰区(sym=%.2f,cause=%.2f,sim=%.2f)" % (sym_d, cause_d, sim)

    return None, 0.5, "灰区(sym=%.2f,cause=%.2f,sim=%.2f)" % (sym_d, cause_d, sim)


def sim_decide(sim):
    """纯相似度阈值（现网三分档的等价物，不使用任何结构化字段），仅用于消融对照。"""
    if sim >= 0.97:
        return "duplicate", sim, "cos>=0.97"
    if sim >= 0.85:
        return "conflict", sim, "0.85<=cos<0.97"
    if sim >= 0.75:
        return "variant", sim, "0.75<=cos<0.85"
    return "unrelated", sim, "cos<0.75"


# ---------------- LLM ----------------
def api_key(path):
    if os.environ.get("ZHIPU_API_KEY"):
        return os.environ["ZHIPU_API_KEY"].strip()
    return open(path, encoding="utf-8").read().strip()


def llm_judge(text_a, text_b, key, retry=3):
    user = "条目 A：\n%s\n\n条目 B：\n%s" % (text_a, text_b)
    body = {"model": MODEL, "temperature": 0,
            "messages": [{"role": "system", "content": LLM_SYSTEM},
                         {"role": "user", "content": user}]}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last = None
    for a in range(retry):
        try:
            req = urllib.request.Request(GLM_URL, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", "Bearer " + key)
            with urllib.request.urlopen(req, timeout=60) as r:
                obj = json.loads(r.read().decode("utf-8"))
            return parse_llm(obj["choices"][0]["message"]["content"]), None
        except Exception as e:  # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, str(e)[:160])
            time.sleep(2 * (a + 1))
    return None, last


def parse_llm(txt):
    if not txt:
        return None
    s = txt.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    for i, ch in enumerate(s):
        if ch == "{":
            try:
                obj, _ = json.JSONDecoder().raw_decode(s[i:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rel = str(obj.get("relation", "")).strip().lower()
                if rel in LABELS:
                    return {"relation": rel,
                            "condition_overlap": str(obj.get("condition_overlap", "unknown")).lower(),
                            "confidence": float(obj.get("confidence", 0.6) or 0.6),
                            "reason": str(obj.get("reason", ""))[:120]}
    return None


# ---------------- 主流程 ----------------
def load_embedder():
    """复用 gen_relation_pairs.py 的 BGE 封装（带 /tmp 缓存）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen_relation_pairs.py")
    spec = importlib.util.spec_from_file_location("gen_rel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Embedder("bge")


def predict(mode, rows, sims, gold, key):
    out = []
    for i, r in enumerate(rows):
        A, B = parse_kb(r["text_a"]), parse_kb(r["text_b"])
        cs = cond_state(A, B)
        sim = max(0.0, min(1.0, float(sims[i])))
        if mode == "sim":
            label, conf, reason = sim_decide(sim)
        elif mode == "rule":
            label, conf, reason = rule_decide(A, B, sim)
            if label is None:
                label = "variant" if cs in ("one_sided", "exclusive") else "conflict"
                conf = 0.5
        else:
            label, conf, reason = rule_decide(A, B, sim)
            # 条件状态明确时规则优先；只有条件未知的 variant/conflict 与灰区才交 LLM
            need_llm = label is None or (label in ("variant", "conflict") and cs == "unknown")
            if need_llm:
                res, err = llm_judge(r["text_a"], r["text_b"], key)
                if res:
                    label = res["relation"]
                    conf = max(conf, res["confidence"])
                    reason = "LLM: " + res["reason"] + " | 规则: " + reason
                elif label is None:
                    label, conf = sim_decide(sim)[0], 0.4
                    reason = "LLM失败回退相似度: " + (err or "")
                # 条件互斥收口：条件互斥时不允许判 conflict（同象异因但可共存 → variant）
                if label == "conflict" and cs in ("one_sided", "exclusive"):
                    label, conf, reason = "variant", 0.7, "条件互斥收口: " + reason
        out.append({"pair_id": r["pair_id"], "gold": gold.get(r["pair_id"]),
                    "pred": label, "confidence": round(float(conf), 3),
                    "sim": round(sim, 4), "condition_state": cs, "reason": reason})
        if (i + 1) % 50 == 0 or i + 1 == len(rows):
            print("[rel] %s %d/%d" % (mode, i + 1, len(rows)), flush=True)
    return out


def metrics(rows):
    cm = {g: {p: 0 for p in LABELS} for g in LABELS}
    for r in rows:
        cm[r["gold"]][r["pred"]] += 1
    per = {}
    for lab in LABELS:
        tp = cm[lab][lab]
        fp = sum(cm[g][lab] for g in LABELS if g != lab)
        fn = sum(cm[lab][p] for p in LABELS if p != lab)
        p = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
        per[lab] = {"precision": round(p, 4), "recall": round(rc, 4), "f1": round(f1, 4),
                    "support": tp + fn}
    acc = sum(cm[l][l] for l in LABELS) / len(rows) if rows else 0.0
    return {"n": len(rows), "accuracy": round(acc, 4),
            "macro_f1": round(sum(v["f1"] for v in per.values()) / len(LABELS), 4),
            "per_class": per, "confusion_matrix": cm}


def table_lines(res, caption):
    lines = ["### %s" % caption, "",
             "| 模式 | Accuracy | Macro-F1 | duplicate F1 | variant F1 | conflict F1 | unrelated F1 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for mode in ("sim", "rule", "full"):
        if mode not in res:
            lines.append("| %s | — | — | — | — | — | — |" % mode)
            continue
        mm = res[mode]["metrics"]
        pc = mm["per_class"]
        lines.append("| %s | %.4f | %.4f | %.3f | %.3f | %.3f | %.3f |" % (
            mode, mm["accuracy"], mm["macro_f1"],
            pc["duplicate"]["f1"], pc["variant"]["f1"], pc["conflict"]["f1"], pc["unrelated"]["f1"]))
    return lines


def confusion_lines(res, caption):
    mode = "full" if "full" in res else ("rule" if "rule" in res else "sim")
    m = res[mode]["metrics"]["confusion_matrix"]
    lines = ["", "### %s（%s，行=真值，列=预测）" % (caption, mode), "",
             "| 真值\\预测 | duplicate | variant | conflict | unrelated |", "|---|---:|---:|---:|---:|"]
    for g in LABELS:
        lines.append("| %s | %d | %d | %d | %d |" % (
            g, m[g]["duplicate"], m[g]["variant"], m[g]["conflict"], m[g]["unrelated"]))
    return lines


def error_lines(res, caption, k=8):
    mode = "full" if "full" in res else "rule"
    preds = res[mode]["preds"]
    errs = [r for r in preds
            if r["gold"] != r["pred"] and r["gold"] in ("variant", "conflict")]
    lines = ["", "### %s：variant/conflict 错判（%s，最多 %d 条）" % (caption, mode, k), ""]
    if not errs:
        lines.append("无。")
    for r in errs[:k]:
        lines.append("- `%s` 真值=%s 预测=%s（sim=%s, 条件=%s）：%s" % (
            r["pair_id"], r["gold"], r["pred"], r["sim"], r["condition_state"], r["reason"]))
    return lines


def write_report(orig, anti):
    os.makedirs(REL_DIR, exist_ok=True)
    o = orig["full"]["metrics"] if "full" in orig else orig["rule"]["metrics"]
    a = anti["full"]["metrics"] if "full" in anti else anti["rule"]["metrics"]
    drop = round(o["macro_f1"] - a["macro_f1"], 4)
    lines = ["# 四类关系判别评测（P1）", "",
             "> 真值：`_gold_relation_draft.jsonl`，由生成器在造对时确定（construction-based gold，弱监督），**不是人工标注**。",
             "> 指标口径：与构造真值的一致性；样本为跨设备模板合成语料，不外推真实工单能力。", "",
             "## 方法", "",
             "1. **相似度**：BGE-M3 余弦，作为召回特征。",
             "2. **结构化规则**：解析现象/根因/措施/验证/条件，比较现象与根因是否同一、措施是否重叠。",
             "3. **条件互斥**：同类型条件值不同 → 互斥（判 variant）；条件重叠或缺失 → 允许 conflict。",
             "4. **LLM 复核**：仅当条件状态未知（unknown）或规则落入灰区时交 glm-4-flash 判别；",
             "   条件明确（重叠/一侧缺失/互斥）时以结构化规则为准；LLM 判 conflict 但条件互斥时，",
             "   再由条件规则收口为 variant。", "",
             "## A. 构造集（保留条件字段）", ""]
    lines += table_lines(orig, "总体结果")
    lines += confusion_lines(orig, "混淆矩阵")
    lines += error_lines(orig, "构造集")
    lines += ["", "## B. 反构造检验（删除「适用条件」与设备/产线/工艺段上下文行）", "",
              "> 删除的两类行是构造集里 variant/conflict 的强标签信号（variant 必带适用条件、conflict 必共享上下文）。",
              "> 删除后模型只能靠现象/根因/措施的语义判断，这是检验「规则是否真有用」的对照。", ""]
    lines += table_lines(anti, "总体结果")
    lines += confusion_lines(anti, "混淆矩阵")
    lines += error_lines(anti, "反构造集")
    verdict = (
        "- 反构造集掉到 0.9 以下，说明构造集的高分主要由「variant 必带适用条件、conflict 必共享上下文」"
        "这两条构造规律贡献，**不能作为方法能力外推**；论文正文应并列两组，并以反构造组作为保守下界。"
        if a["macro_f1"] < 0.9 else
        "- 反构造集仍在 0.9 以上，说明规则不依赖单一构造痕迹；但两组同受模板语料限制，仍需并列呈现。"
    )
    lines += ["", "## 结论：哪一组数字能外推", "",
              "- 构造集 full macro-F1 = %.4f，反构造集 full macro-F1 = %.4f，落差 **%.4f**。" % (
                  o["macro_f1"], a["macro_f1"], drop),
              verdict,
              "- 反构造检验同时删掉了真实的条件信息，因此它衡量的是「条件字段缺失时」的退化表现；",
              "  真实工单上应先由 P0 链式抽取补出条件，再进入 P1 判别，二者是依赖关系而非替代关系。",
              (("- 反构造集上 sim=%.4f 高于 full=%.4f：条件缺失时规则与 LLM 会引入负收益，"
                "不能把 P1 单独部署在没有条件字段的知识上。" % (
                    anti["sim"]["metrics"]["macro_f1"], a["macro_f1"]))
               if "sim" in anti and anti["sim"]["metrics"]["macro_f1"] > a["macro_f1"] else
               "- 反构造集上规则组未低于纯相似度基线，说明规则本身不依赖单一构造痕迹。"),
              "- 逐对预测与错判理由见 `relation_pred_orig_full.jsonl` / `relation_pred_anti_full.jsonl`（每对一行）。",
              "- 两组都受模板合成语料的限制，不能外推到真实工单；关系集本身仍是 construction-based gold。", "",
              "## 局限", "",
              "1. 关系集由模板定向构造（duplicate 换词、variant 换根因/条件、conflict 选 0.85–0.95 相似带），",
              "   存在构造痕迹；指标只说明方法在该构造集上可分。",
              "2. variant 与 conflict 的相似度分布重叠（见 `_relation_stats.json`），单靠阈值不可分。",
              "3. LLM 判别使用 glm-4-flash，与现网抽取模型同源，不构成独立第三方评审。", ""]
    with open(os.path.join(REL_DIR, "关系判别评测.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def evaluate(rows, gold, emb, key, modes, tag):
    sims = emb.sims([(r["text_a"], r["text_b"]) for r in rows])
    res = {}
    for mode in modes:
        preds = predict(mode, rows, sims, gold, key)
        res[mode] = {"metrics": metrics(preds), "preds": preds}
        with open(os.path.join(REL_DIR, "relation_pred_%s_%s.jsonl" % (tag, mode)), "w",
                  encoding="utf-8") as f:
            for r in preds:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("[rel] %s/%s %s" % (tag, mode, json.dumps(res[mode]["metrics"], ensure_ascii=False)), flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--key", default=KEY_PATH)
    ap.add_argument("--modes", default="sim,rule,full",
                    help="逗号分隔，可只跑 sim,rule 做无 API 的自检")
    args = ap.parse_args()
    os.makedirs(REL_DIR, exist_ok=True)

    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig")))
    if args.limit:
        rows = rows[:args.limit]
    gold = {json.loads(l)["pair_id"]: json.loads(l)["relation"]
            for l in open(GOLD_PATH, encoding="utf-8") if l.strip()}
    anti_rows = [dict(r, text_a=strip_artifacts(r["text_a"]), text_b=strip_artifacts(r["text_b"]))
                 for r in rows]
    modes = [m.strip() for m in args.modes.split(",") if m.strip() in ("sim", "rule", "full")]
    key = api_key(args.key) if "full" in modes else None

    emb = load_embedder()
    print("[rel] == A. 构造集 ==", flush=True)
    orig = evaluate(rows, gold, emb, key, modes, "orig")
    print("[rel] == B. 反构造检验 ==", flush=True)
    anti = evaluate(anti_rows, gold, emb, key, modes, "anti")

    with open(os.path.join(REL_DIR, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump({"orig": {m: v["metrics"] for m, v in orig.items()},
                   "anti": {m: v["metrics"] for m, v in anti.items()}}, f, ensure_ascii=False, indent=2)
    write_report(orig, anti)
    print("[rel] -> %s" % REL_DIR)


if __name__ == "__main__":
    main()
