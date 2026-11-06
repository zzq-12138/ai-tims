#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立模型盲评（第二层）：用 glm-4-flash 按标注手册规则独立抽取，再与构造真值比对。

M6.1 口径说明：主业务模型已切 glm-5.3-flash（S3 抽取口径），但本盲评脚本刻意固定
glm-4-flash —— 评审模型必须与被评模型不同，否则独立性失效；已有 1000 条结果继续有效。

口径：这是「构造真值 vs 独立模型判定」的一致性，**不是人工 κ**。
模型看不到 _gold_draft.jsonl，只拿到工单原文。

用法：
  python3 blind_eval.py run --limit 3      # 冒烟
  python3 blind_eval.py run                # 全量 1000 条（断点续跑）
  python3 blind_eval.py compare            # 生成报告
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "docs", "paper", "问题二")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_constructed_gold import INSTRUCTION, to_label  # noqa: E402

GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
# 【M6.1 固定不切】盲评评审模型必须与被评模型（glm-5.3-flash）不同，否则独立性消失。
# 该值刻意与 tims.ai.model / tims.ai.extract-model 解耦，禁止跟随主模型切换。
# 另：线上 KB v1 由 glm-4-flash 抽取并冻结，检索类结论口径不变。
MODEL = "glm-4-flash"
KEY_PATH = "/home/dev/secrets/zhipu_api_key"
PRED = os.path.join(OUT, "blind_predictions.jsonl")
FIELDS = ["symptom", "root_cause", "root_cause_evidence", "measures", "verification",
          "conditions", "excluded_hypotheses", "is_excluded_hypothesis",
          "has_final_root_cause", "uncertain"]
_lock = threading.Lock()


def api_key():
    if os.environ.get("ZHIPU_API_KEY"):
        return os.environ["ZHIPU_API_KEY"].strip()
    return open(KEY_PATH, encoding="utf-8").read().strip()


def call(text, key, retry=3):
    body = {"model": MODEL, "temperature": 0,
            "messages": [{"role": "system", "content": INSTRUCTION},
                         {"role": "user", "content": "工单：\n" + text}]}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    for a in range(retry):
        req = urllib.request.Request(GLM_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + key)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                obj = json.loads(r.read().decode("utf-8"))
            c = obj["choices"][0]["message"]["content"]
            i, j = c.find("{"), c.rfind("}")
            return json.loads(c[i:j + 1])
        except Exception as e:
            if a == retry - 1:
                return {"_error": str(e)[:200]}
            time.sleep(2 + 2 * a)
    return {"_error": "unknown"}


def norm_out(o):
    out = {}
    for f in FIELDS:
        v = o.get(f)
        if f in ("measures",):
            out[f] = [str(x).strip() for x in v] if isinstance(v, list) else ([str(v)] if v else [])
        elif f in ("conditions", "excluded_hypotheses"):
            out[f] = v if isinstance(v, list) else []
        elif f in ("is_excluded_hypothesis", "has_final_root_cause", "uncertain"):
            try:
                out[f] = int(v)
            except Exception:
                out[f] = 0
        else:
            out[f] = "" if v is None else str(v).strip()
    return out


def cmd_run(args):
    key = api_key()
    data = args.data or os.path.join(OUT, "annotation_set_v1.csv")
    pred_path = args.pred or PRED
    rows = [r for r in __import__("csv").DictReader(open(data, encoding="utf-8-sig"))]
    done = set()
    if os.path.exists(pred_path):
        for line in open(pred_path, encoding="utf-8"):
            try:
                done.add(json.loads(line)["ticket_id"])
            except Exception:
                pass
    todo = [r for r in rows if r["ticket_id"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"[blind] 总 {len(rows)}，已完成 {len(done)}，本次 {len(todo)}，模型 {MODEL}", flush=True)

    def one(r):
        p = norm_out(call(r["ticket_text"], key))
        rec = dict(ticket_id=r["ticket_id"], device_type=r["device_type"], **p)
        with _lock:
            with open(pred_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    t0, ok, bad = time.time(), 0, 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for n, rec in enumerate(ex.map(one, todo), 1):
            if "_error" in rec:
                bad += 1
            else:
                ok += 1
            if n % 50 == 0:
                print(f"[blind] {n}/{len(todo)} ok={ok} err={bad} {time.time() - t0:.0f}s", flush=True)
    print(f"[blind] 完成 ok={ok} err={bad} 用时 {time.time() - t0:.0f}s -> {pred_path}", flush=True)


def bigrams(s):
    s = "".join(str(s).split())
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def soft(a, b):
    """短标签语义相似度：包含关系直接算 1，否则取 bigram Jaccard 与字符序列相似度的较大者。"""
    if not a or not b:
        return 0.0
    from difflib import SequenceMatcher
    sa = "".join(str(a).split())
    sb = "".join(str(b).split())
    if sa in sb or sb in sa:
        return 1.0
    A, B = bigrams(a), bigrams(b)
    jac = len(A & B) / len(A | B)
    return max(jac, SequenceMatcher(None, sa, sb).ratio())


def kappa(pairs):
    n = len(pairs)
    if not n:
        return 0.0, 0.0, 0.0
    po = sum(1 for a, b in pairs if a == b) / n
    pa = sum(1 for a, _ in pairs if a) / n
    pb = sum(1 for _, b in pairs if b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    k = 0.0 if pe == 1 else (po - pe) / (1 - pe)
    return k, po, pe


def cmd_compare(args):
    pred_path = args.pred or PRED
    pred = {json.loads(l)["ticket_id"]: json.loads(l) for l in open(pred_path, encoding="utf-8")}
    gold_path = args.gold or os.path.join(OUT, "constructed_gold.jsonl")
    raw = {json.loads(l)["ticket_id"]: json.loads(l) for l in open(gold_path, encoding="utf-8")}
    if all("label" in g for g in raw.values()):
        gold = raw
    else:
        gold = {i: {"label": to_label(g)} for i, g in raw.items()}
    meta_path = args.meta or os.path.join(OUT, "_gold_draft.jsonl")
    meta = {json.loads(l)["ticket_id"]: json.loads(l) for l in open(meta_path, encoding="utf-8")}
    ids = [i for i in gold if i in pred]
    print(f"[cmp] 可比对 {len(ids)} 条")

    slots = [("symptom", "现象"), ("root_cause", "根因"), ("verification", "验证结果"),
             ("measures", "处理措施"), ("conditions", "适用条件"), ("excluded_hypotheses", "排除假设")]
    res = []
    cond_type = []
    for key, name in slots:
        ex, sf = [], []
        # 根因 / 排除假设：空值样本（无根因、无排除）会把严格一致率抬高，单独剔除后统计
        sub = ids
        if key == "root_cause":
            sub = [i for i in ids if str(gold[i]["label"].get("root_cause", "")).strip()]
        elif key == "excluded_hypotheses":
            sub = [i for i in ids if gold[i]["label"].get("excluded_hypotheses")]
        for i in sub:
            g, p = gold[i]["label"].get(key), pred[i].get(key)
            if key in ("symptom", "root_cause", "verification"):
                ex.append(1 if str(g).strip() == str(p).strip() else 0)
                sf.append(soft(g, p))
            elif key == "measures":
                gs = [str(x) for x in (g or [])]
                ps = [str(x) for x in (pred[i].get("measures") or [])]
                ex.append(1 if sorted(gs) == sorted(ps) else 0)
                sf.append(sum(1 for x in gs if any(soft(x, y) >= 0.6 for y in ps)) / len(gs) if gs else 0.0)
            elif key == "conditions":
                gs = {f"{c.get('type')}|{str(c.get('value')).strip()}" for c in (g or [])}
                ps = {f"{c.get('type')}|{str(c.get('value')).strip()}" for c in (pred[i].get("conditions") or [])
                      if isinstance(c, dict)}
                ex.append(1 if gs == ps else 0)
                sf.append(len(gs & ps) / len(gs | ps) if (gs | ps) else 0.0)
                gts = {c.get("type") for c in (g or []) if isinstance(c, dict)}
                pts = {c.get("type") for c in (pred[i].get("conditions") or []) if isinstance(c, dict)}
                cond_type.append(len(gts & pts) / len(gts | pts) if (gts | pts) else 0.0)
            else:
                gs = [h.get("hypothesis", "") for h in (g or [])]
                ps = [h.get("hypothesis", "") for h in (pred[i].get("excluded_hypotheses") or [])
                      if isinstance(h, dict)]
                ex.append(1 if sorted(gs) == sorted(ps) else 0)
                sf.append(sum(1 for x in gs if any(soft(x, y) >= 0.6 for y in ps)) / len(gs) if gs else 0.0)
        res.append((name, key, sum(ex) / len(ex), sum(sf) / len(sf), len(sub)))

    bins = []
    for key, name in (("is_excluded_hypothesis", "是否含排除假设"), ("has_final_root_cause", "有无最终根因")):
        pairs = [(int(gold[i]["label"].get(key, 0)), int(pred[i].get(key, 0))) for i in ids]
        k, po, pe = kappa(pairs)
        cm = Counter(pairs)
        bins.append((name, k, po, pe, cm, len(pairs)))

    # 切片：结构 / 风格 / 设备
    slices = defaultdict(list)
    for i in ids:
        m = meta[i]
        for key, name in (("is_excluded_hypothesis", "含排除假设"), ("has_final_root_cause", "有无最终根因")):
            slices[(m["structure"], key)].append((int(gold[i]["label"][key]), int(pred[i][key])))
            slices[(m["style"], key)].append((int(gold[i]["label"][key]), int(pred[i][key])))
            slices[(m["device_type"], key)].append((int(gold[i]["label"][key]), int(pred[i][key])))

    title = args.title or "独立模型盲评一致性报告"
    L = [f"# {title}\n",
         f"> 评委模型：`{MODEL}`（与生成器无关：真值由模板构造，不是模型生成）。",
         "> **口径**：这是「构造真值 vs 独立模型判定」的一致性，**不是人工标注 κ**。"
         "模型只拿到工单原文，未接触构造真值。\n",
         f"- 比对样本：{len(ids)} / {len(gold)}", f"- 调用成本：见 `标注方案变更说明.md` 费用估算一节\n",
         "## 一、逐槽位一致率\n",
         "| 槽位 | 严格一致率 | 语义一致率 | 有效样本 |",
         "|---|---|---|---|"]
    for name, key, ex, sf, n in res:
        L.append(f"| {name} | {ex:.2%} | {sf:.2%} | {n} |")
    L.append(f"\n> 语义一致率：文本字段取 bigram Jaccard；短标签（措施/排除假设）取 best-match（包含关系算 1）；"
             f"条件按 `type|value` 集合重叠。")
    L.append(f"> 根因只在「真值有根因」的样本上统计，排除假设只在「真值非空」的样本上统计，避免空值把一致率抬高。")
    L.append(f"> 条件类型层面（只比 type，不比 value）的平均 Jaccard 为 **{sum(cond_type) / len(cond_type):.2%}**"
             f"——该指标更能反映模型是否理解「条件该写哪一类」。")
    L.append("\n> 自由文本字段（现象/根因/验证）的严格一致率天然偏低，因为措辞不同但语义可能相同；"
             "判断抽取质量看语义一致率与二值字段 κ。\n")
    L.append("## 二、两个二值字段（论文可引用）\n")
    L.append("| 字段 | Cohen's κ | 一致率 | p_e | 样本 | 解释 |\n|---|---|---|---|---|---|")
    for name, k, po, pe, cm, n in bins:
        verdict = "可接受" if k >= 0.6 else ("偏低，需回看" if k >= 0.4 else "不可接受")
        L.append(f"| {name} | **{k:.3f}** | {po:.3f} | {pe:.3f} | {n} | {verdict} |")
    for (name, k, po, pe, cm, n) in bins:
        L.append(f"\n**{name} 混淆矩阵**（行=构造真值，列={MODEL}）\n")
        L.append("| | 模型=0 | 模型=1 |\n|---|---|---|")
        L.append(f"| **真值=0** | {cm[(0, 0)]} | {cm[(0, 1)]} |")
        L.append(f"| **真值=1** | {cm[(1, 0)]} | {cm[(1, 1)]} |")

    L.append("\n## 三、分歧集中在哪里\n")
    L.append("| 切片 | 字段 | κ | n |\n|---|---|---|---|")
    for (sl, key), pairs in sorted(slices.items()):
        if len(pairs) < 20:
            continue
        nm = "含排除" if key == "is_excluded_hypothesis" else "有根因"
        if len({a for a, _ in pairs}) == 1:
            L.append(f"| {sl} | {nm} | —（单类，κ 无定义） | {len(pairs)} |")
            continue
        k, po, pe = kappa(pairs)
        flag = " ⚠" if k < 0.4 else ""
        L.append(f"| {sl} | {nm} | {k:.2f}{flag} | {len(pairs)} |")

    # 典型分歧样本
    L.append("\n## 四、典型分歧样本\n")
    shown = 0
    for i in ids:
        g, p = gold[i]["label"], pred[i]
        if int(g["has_final_root_cause"]) == 1 and int(p.get("has_final_root_cause", 0)) == 0 and shown < 6:
            L.append(f"- `{i}`（{meta[i]['style']}/{meta[i]['structure']}）：真值有根因「{g['root_cause']}」，"
                     f"模型判无根因（模型 root_cause=「{p.get('root_cause', '')}」）")
            shown += 1
    shown = 0
    for i in ids:
        g, p = gold[i]["label"], pred[i]
        if int(g["is_excluded_hypothesis"]) == 0 and int(p.get("is_excluded_hypothesis", 0)) == 1 and shown < 6:
            L.append(f"- `{i}`（{meta[i]['style']}/{meta[i]['structure']}）：真值无排除假设，模型却给出"
                     f"{len(p.get('excluded_hypotheses') or [])} 条（现象被读成排除）")
            shown += 1
    shown = 0
    for i in ids:
        g, p = gold[i]["label"], pred[i]
        gts = [c.get("type") for c in (g.get("conditions") or []) if isinstance(c, dict)]
        pts = [c.get("type") for c in (p.get("conditions") or []) if isinstance(c, dict)]
        if gts and len(set(gts) & set(pts)) / len(set(gts) | set(pts)) < 0.5 and shown < 5:
            L.append(f"- `{i}`（{meta[i]['style']}）：真值条件类型 {gts}，模型 {pts}")
            shown += 1
    if shown == 0:
        L.append("- 未发现条件类型层面的严重分歧（Jaccard ≥0.5）")

    # compute_kappa 交叉核对
    L.append("\n## 五、用 compute_kappa.py 交叉核对\n")
    flat_gold = "/tmp/blind_gold_flat.jsonl"
    with open(flat_gold, "w", encoding="utf-8") as f:
        for i in ids:
            f.write(json.dumps(dict(ticket_id=i, **gold[i]["label"]), ensure_ascii=False) + "\n")
    flat_pred = "/tmp/blind_pred_flat.jsonl"
    with open(flat_pred, "w", encoding="utf-8") as f:
        for i in ids:
            f.write(json.dumps(dict(pred[i], ticket_id=i), ensure_ascii=False) + "\n")
    try:
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                         "compute_kappa.py"),
                            "--a", flat_pred, "--b", flat_gold,
                            "--meta", meta_path],
                           capture_output=True, text=True, timeout=300)
        body = r.stdout.strip().split("\n")
        L.append("```text")
        L.extend(body[:40])
        L.append("```")
    except Exception as e:
        L.append(f"（调用 compute_kappa.py 失败：{e}）")

    L.append("\n## 六、结论\n")
    k1 = bins[0][1]
    k2 = bins[1][1]
    L.append(f"- 两个二值字段 κ 分别为 **{k1:.2f}**（含排除假设）与 **{k2:.2f}**（有无最终根因）。")
    worst = min(res, key=lambda r: r[3])
    L.append(f"- 最容易分歧的槽位是「{worst[0]}」（语义一致率 {worst[3]:.1%}）；"
             f"根因与措施的语义一致率分别为 "
             f"{[r[3] for r in res if r[0] == '根因'][0]:.1%}、{[r[3] for r in res if r[0] == '处理措施'][0]:.1%}。")
    L.append("- 条件的 value 由自然语言描述，模型几乎不可能逐字复现，**应以「条件类型层面 Jaccard」为主要指标**，"
             "value 层面仅作参考。")
    L.append("- 若 κ ≥0.6：说明「构造真值的两个关键判定」能被独立模型按手册复现，"
             "可用于支撑弱监督标签的可学习性；若 <0.6：优先回看 §四 的分歧样本，"
             "判断是手册表述不清还是构造真值本身有歧义。")
    L.append("- **禁止**把本节写成人工标注一致性；正确表述为「构造真值与独立模型判定的一致性」。\n")

    path = args.out or os.path.join(OUT, "盲评一致性报告.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"[cmp] 写入 {path}")
    for name, key, ex, sf, n in res:
        print(f"  {name}: 严格 {ex:.1%} / 语义 {sf:.1%} (n={n})")
    for name, k, po, pe, cm, n in bins:
        print(f"  {name}: κ={k:.3f} p_o={po:.3f} n={n}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--workers", type=int, default=5)
    r.add_argument("--data", default="", help="工单 CSV（默认 annotation_set_v1.csv）")
    r.add_argument("--pred", default="", help="输出 JSONL（默认 blind_predictions.jsonl）")
    c = sub.add_parser("compare")
    c.add_argument("--pred", default="")
    c.add_argument("--gold", default="", help="构造真值 JSONL（支持 gold 原格式或已导出格式）")
    c.add_argument("--meta", default="")
    c.add_argument("--out", default="")
    c.add_argument("--title", default="")
    args = ap.parse_args()
    cmd_run(args) if args.cmd == "run" else cmd_compare(args)


if __name__ == "__main__":
    main()
