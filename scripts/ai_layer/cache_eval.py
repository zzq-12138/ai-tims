#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语义缓存评测：命中率 vs 质量损失。

流程：
1. 300 条评测集全部走一次模型（glm-5.3-flash），得到「无缓存」答案与实测 token/延迟；
2. 300 条问题全部取 embedding（embedding-3），得到向量与实测向量延迟；
3. 50 条标准问法作为缓存种子，其余 250 条（150 同义改写 + 50 近邻负例 + 50 无关对照）做回放：
   - 精确 hash：归一化后完全一致才命中（同义改写按定义为 0）；
   - 语义命中：与同族标准问法的余弦 ≥ 阈值即命中，直接返回标准问法的答案；
4. 阈值扫描 0.80–0.99，输出每个阈值的命中率、误命中率、准确率、质量损失、省下的调用与费用；
5. 「命中但答错」逐条列出（问题、命中的标准问法、相似度、缺失的规格值、缓存答案片段）。

用法（仓库根目录）：
    python3 scripts/ai_layer/cache_eval.py              # 全量
    python3 scripts/ai_layer/cache_eval.py --limit 12   # 冒烟（按族截断）
    python3 scripts/ai_layer/cache_eval.py --offline    # 只做阈值回放，不调 API
"""
import argparse
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "scripts" / "ai_layer" / "data" / "cache_set.tsv"
OUT_DIR = ROOT / "docs" / "paper" / "ai应用层"
RAW = OUT_DIR / "raw" / "cache_rows.json"
YML = ROOT / "ai-tims-parent" / "ticket-ai" / "src" / "main" / "resources" / "application.yml"

API = "https://open.bigmodel.cn/api/paas/v4"
CHAT = API + "/chat/completions"
EMBED = API + "/embeddings"
KEY_FILE = Path(os.environ.get("LLM_API_KEY_FILE", "/home/dev/secrets/zhipu_api_key"))
MODEL = "glm-5.3-flash"
EMBED_MODEL = "embedding-3"
SYSTEM_PROMPT = ("你是 AI-TIMS 工业设备运维助手。只依据给定参考资料回答；先给结论，再给关键依据；"
                 "资料不足时明确说明。回答控制在 150 字以内。")
MAX_TOKENS = 4096
WORKERS = 6
DEFAULT_THRESHOLD = 0.92
THRESHOLDS = [round(x / 100, 2) for x in range(80, 99, 2)] + [0.99]


def load_prices():
    text = YML.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^\s+([\w.\-]+):\s*\{\s*input-per-1k:\s*([\d.]+),\s*output-per-1k:\s*([\d.]+)\s*\}",
                         text, re.M):
        out[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    if not out:
        raise SystemExit("未能从 application.yml 解析 model-prices")
    return out


def post(path, key, body, timeout=300):
    req = urllib.request.Request(
        path, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def qhash(row):
    return hashlib.md5((row["question"] + "\x00" + row["context"]).encode()).hexdigest()[:12]


def call_model(key, row):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"参考资料：\n{row['context']}\n\n问题：{row['question']}"},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.3,
    }
    t0 = time.time()
    d = post(CHAT, key, body)
    u = d.get("usage") or {}
    msg = d["choices"][0]["message"]
    return {
        "model": MODEL,
        "latency_s": round(time.time() - t0, 2),
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "answer": (msg.get("content") or "").strip(),
    }


def embed(key, text):
    t0 = time.time()
    d = post(EMBED, key, {"model": EMBED_MODEL, "input": [text]}, timeout=30)
    vec = (d.get("data") or [{}])[0].get("embedding") or []
    return {"vector": vec, "embed_ms": int((time.time() - t0) * 1000)}


def norm(s):
    s = (s or "").strip().lower()
    s = s.replace("～", "-").replace("~", "-").replace("—", "-").replace("–", "-").replace("－", "-")
    return s.replace("．", ".").replace(" ", "")


def contains_value(answer, value):
    """数值边界匹配：'50' 不能命中 '150'，'8' 不能命中 '0.8'"""
    a = norm(answer)
    v = norm(value)
    if not v:
        return False
    return re.search(r"(?<![\d.])" + re.escape(v) + r"(?![\d.])", a) is not None


def gold_ok(gold, answer):
    if not gold:
        return False
    return all(contains_value(answer, g) for g in gold.split("|") if g)


def norm_question(q):
    s = (q or "").lower().replace("，", ",").replace("。", ".").replace("？", "?").replace("！", "!")
    s = s.replace("：", ":").replace("；", ";").replace("、", ",").replace("（", "(").replace("）", ")")
    return re.sub(r"[\W_]+", "", s)


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else -1.0


def cost_of(call, prices):
    pin, pout = prices.get(call["model"], (0.0008, 0.0028))
    return call["prompt_tokens"] / 1000.0 * pin + call["completion_tokens"] / 1000.0 * pout


def read_rows(limit_families=0):
    rows = []
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = line.split("\t")
        if len(r) < 10:
            continue
        rows.append({"id": r[0], "family": r[1], "role": r[2], "device": r[3], "key": r[4],
                     "part": r[5], "metric": r[6], "question": r[7], "context": r[8], "gold": r[9]})
    if limit_families:
        keep = sorted({r["family"] for r in rows})[:limit_families]
        rows = [r for r in rows if r["family"] in keep]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个族（冒烟）")
    ap.add_argument("--offline", action="store_true", help="只做阈值回放，不调用 API")
    args = ap.parse_args()

    rows = read_rows(args.limit)
    RAW.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if RAW.exists():
        try:
            done = {x["id"]: x for x in json.loads(RAW.read_text(encoding="utf-8"))}
        except Exception:
            done = {}
    by_id = {r["id"]: r for r in rows}
    for i in list(done):
        if i in by_id and done[i].get("qh") != qhash(by_id[i]):
            done.pop(i, None)

    lock = threading.Lock()
    prices = load_prices()

    if not args.offline:
        key = KEY_FILE.read_text().strip()
        todo = [r for r in rows if not (done.get(r["id"], {}).get("answer")
                                        and done.get(r["id"], {}).get("vector"))]
        print(f"[cache] rows={len(rows)} todo={len(todo)}", flush=True)

        def work(row):
            rid = row["id"]
            prev = done.get(rid) or {}
            rec = dict(prev)
            rec.update({"id": rid, "qh": qhash(row), "role": row["role"], "family": row["family"]})
            if not rec.get("answer"):
                rec["chat"] = call_model(key, row)
                rec["answer"] = rec["chat"]["answer"]
            if not rec.get("vector"):
                rec["embed"] = embed(key, row["question"])
                rec["vector"] = rec["embed"]["vector"]
            with lock:
                done[rid] = rec
                RAW.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=2),
                               encoding="utf-8")
            return rec

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(work, r): r["id"] for r in todo}
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    f.result()
                except Exception as e:
                    print(f"[cache] {futs[f]} failed: {e!r}", flush=True)
                if i % 20 == 0:
                    print(f"[cache] progress {i}/{len(todo)} elapsed={int(time.time() - t0)}s", flush=True)

    records = []
    for r in rows:
        rec = done.get(r["id"])
        if not rec or not rec.get("answer") or not rec.get("vector"):
            continue
        records.append({**r, **rec})

    report = aggregate(records, prices)
    (OUT_DIR / "缓存评测.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    (OUT_DIR / "缓存评测报告.md").write_text(build_md(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


def aggregate(records, prices):
    canon = {r["family"]: r for r in records if r["role"] == "canonical"}
    queries = [r for r in records if r["role"] != "canonical" and r["family"] in canon]
    n = len(queries)

    for r in records:
        r["ok"] = gold_ok(r["gold"], r["answer"])
        r["cost"] = cost_of(r["chat"], prices) if r.get("chat") else 0.0
        r["chat_ms"] = int((r.get("chat") or {}).get("latency_s", 0) * 1000)
        r["embed_ms"] = int((r.get("embed") or {}).get("embed_ms", 0))
        r["norm_q"] = norm_question(r["question"])

    no_cache_ok = sum(1 for r in queries if r["ok"])
    no_cache_cost = sum(r["cost"] for r in queries)
    no_cache_latency = [r["embed_ms"] + r["chat_ms"] for r in queries]

    sweep = []
    for thr in [None] + THRESHOLDS + ["oracle"]:
        hits = []
        for q in queries:
            c = canon[q["family"]]
            if thr is None:  # 精确 hash 基线
                hit = q["norm_q"] == c["norm_q"]
                sim = 1.0 if hit else 0.0
            elif thr == "oracle":  # 理想上界：只有同义改写命中，负例绝不命中
                hit = q["role"] == "paraphrase"
                sim = 1.0 if hit else 0.0
            else:
                sim = cosine(q["vector"], c["vector"])
                hit = sim >= thr
            hits.append((q, c, hit, sim))

        hit_par = sum(1 for q, c, h, s in hits if h and q["role"] == "paraphrase")
        hit_neg = sum(1 for q, c, h, s in hits if h and q["role"] in ("hard_neg", "unrelated"))
        correct = 0
        wrong_hits = []
        for q, c, h, s in hits:
            ok = gold_ok(q["gold"], c["answer"]) if h else q["ok"]
            correct += 1 if ok else 0
            if h and not ok:
                wrong_hits.append({
                    "id": q["id"], "role": q["role"], "family": q["family"],
                    "device": q["device"], "question": q["question"],
                    "matched_question": c["question"], "similarity": round(s, 4),
                    "gold": q["gold"],
                    "missing": [g for g in q["gold"].split("|") if not contains_value(c["answer"], g)],
                    "cached_answer": c["answer"][:260],
                })
        saved_calls = sum(1 for q, c, h, s in hits if h)
        saved_cost = sum(q["cost"] for q, c, h, s in hits if h)
        if thr is None:
            # 精确命中不走向量；其余命中仍有向量化开销（生产链路如此）
            lat = [0 if h else q["embed_ms"] + q["chat_ms"] for q, c, h, s in hits]
        else:
            lat = [q["embed_ms"] if h else q["embed_ms"] + q["chat_ms"] for q, c, h, s in hits]
        hit_lat = [q["embed_ms"] for q, c, h, s in hits if h]
        miss_lat = [q["embed_ms"] + q["chat_ms"] for q, c, h, s in hits if not h]
        sweep.append({
            "threshold": thr,
            "hits": saved_calls,
            "hit_paraphrase": hit_par,
            "hit_negative": hit_neg,
            "hit_rate_paraphrase_pct": pct(hit_par, sum(1 for q in queries if q["role"] == "paraphrase")),
            "false_hit_rate_negative_pct": pct(hit_neg, sum(1 for q in queries
                                                           if q["role"] in ("hard_neg", "unrelated"))),
            "accuracy_pct": pct(correct, n),
            "no_cache_accuracy_pct": pct(no_cache_ok, n),
            "quality_loss_pp": round(pct(no_cache_ok, n) - pct(correct, n), 2),
            "saved_calls": saved_calls,
            "saved_cost_cny": round(saved_cost, 4),
            "avg_latency_ms": int(sum(lat) / len(lat)) if lat else 0,
            "avg_hit_latency_ms": int(sum(hit_lat) / len(hit_lat)) if hit_lat else 0,
            "avg_miss_latency_ms": int(sum(miss_lat) / len(miss_lat)) if miss_lat else 0,
            "wrong_hits": wrong_hits if isinstance(thr, float) else [],
            "wrong_hit_count": len(wrong_hits),
            "wrong_hit_negative": sum(1 for w in wrong_hits
                                      if w["role"] in ("hard_neg", "unrelated")),
        })

    # 汇总：所有在 ≥0.80 的阈值上曾命中的错误样例，逐条可查
    index = {}
    for x in sweep:
        if not isinstance(x["threshold"], float):
            continue
        for w in x["wrong_hits"]:
            cur = index.get(w["id"])
            if cur is None:
                cur = dict(w)
                cur["thresholds"] = []
                index[w["id"]] = cur
            cur["thresholds"].append(x["threshold"])
    for cur in index.values():
        cur["thresholds"] = sorted(cur["thresholds"])
        cur["lowest_hit_threshold"] = cur["thresholds"][0]
    wrong_hit_index = sorted(index.values(), key=lambda x: -x["similarity"])

    default = next(x for x in sweep if x["threshold"] == DEFAULT_THRESHOLD)
    exact = sweep[0]
    oracle = sweep[-1]
    safe = [x for x in sweep if isinstance(x["threshold"], float) and x["wrong_hit_count"] == 0]
    best_safe = max(safe, key=lambda x: x["hits"]) if safe else None
    first_wrong = next((x["threshold"] for x in sweep
                        if isinstance(x["threshold"], float) and x["wrong_hit_count"] > 0), None)

    # 负例相似度分布：用于解释阈值上限
    neg = []
    for q in queries:
        if q["role"] not in ("hard_neg", "unrelated"):
            continue
        c = canon[q["family"]]
        sim = cosine(q["vector"], c["vector"])
        neg.append({"id": q["id"], "role": q["role"], "device": q["device"],
                    "question": q["question"], "similarity": round(sim, 4),
                    "would_hit": [t for t in THRESHOLDS if sim >= t]})
    neg.sort(key=lambda x: -x["similarity"])

    par_sims = [cosine(q["vector"], canon[q["family"]]["vector"])
                for q in queries if q["role"] == "paraphrase"]

    canon_correct = sum(1 for c in canon.values() if c["ok"])
    total_cost = sum(r["cost"] for r in records)
    summary = {
        "n_rows": len(records),
        "n_families": len(canon),
        "n_queries": n,
        "actual_calls": len([r for r in records if r.get("chat")]),
        "actual_cost_cny": round(total_cost, 4),
        "query_roles": {
            "paraphrase": sum(1 for q in queries if q["role"] == "paraphrase"),
            "hard_neg": sum(1 for q in queries if q["role"] == "hard_neg"),
            "unrelated": sum(1 for q in queries if q["role"] == "unrelated"),
        },
        "canonical_correct": canon_correct,
        "canonical_accuracy_pct": pct(canon_correct, len(canon)),
        "no_cache_accuracy_pct": pct(no_cache_ok, n),
        "no_cache_cost_cny": round(no_cache_cost, 4),
        "no_cache_avg_latency_ms": int(sum(no_cache_latency) / len(no_cache_latency)) if no_cache_latency else 0,
        "default_threshold": DEFAULT_THRESHOLD,
        "default": {k: v for k, v in default.items() if k != "wrong_hits"},
        "best_zero_error_threshold": best_safe["threshold"] if best_safe else None,
        "best_zero_error_hit_rate_pct": best_safe["hit_rate_paraphrase_pct"] if best_safe else None,
        "first_wrong_threshold": first_wrong,
        "exact": {k: v for k, v in exact.items() if k != "wrong_hits"},
        "oracle": {k: v for k, v in oracle.items() if k != "wrong_hits"},
        "paraphrase_similarity": {
            "min": round(min(par_sims), 4) if par_sims else 0,
            "p10": round(sorted(par_sims)[len(par_sims) // 10], 4) if par_sims else 0,
            "median": round(sorted(par_sims)[len(par_sims) // 2], 4) if par_sims else 0,
            "max": round(max(par_sims), 4) if par_sims else 0,
        },
        "negative_similarity": {
            "max": neg[0]["similarity"] if neg else 0,
            "p90": neg[len(neg) // 10]["similarity"] if neg else 0,
            "median": neg[len(neg) // 2]["similarity"] if neg else 0,
        },
        "embedding_cost_note": "embedding-3 已购 5000 万专属包，application.yml 单价记 0，本轮向量费用按 0 计",
        "model": MODEL,
        "embedding_model": EMBED_MODEL,
    }
    return {
        "meta": {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "dataset": str(DATA.relative_to(ROOT)), "prices": prices,
                 "thresholds": THRESHOLDS},
        "summary": summary,
        "threshold_sweep": [{k: v for k, v in x.items() if k != "wrong_hits"} for x in sweep],
        "wrong_hits": default["wrong_hits"],
        "wrong_hit_index": wrong_hit_index,
        "wrong_hits_by_threshold": {str(x["threshold"]): x["wrong_hits"]
                                    for x in sweep if isinstance(x["threshold"], float)},
        "false_hit_candidates": neg[:30],
        "thresholds": THRESHOLDS,
    }


def pct(a, b):
    return round(100.0 * a / b, 2) if b else 0.0


def build_md(rep):
    s = rep["summary"]
    d = s["default"]
    first_wrong = next((x["threshold"] for x in rep["threshold_sweep"]
                        if isinstance(x["threshold"], float) and x["wrong_hit_count"] > 0), None)
    first_wrong_txt = (f"阈值降到 {first_wrong:.2f} 时开始出现错误命中，详见下表。"
                       if first_wrong is not None else "所有扫描阈值下均无错误命中。")
    L = ["# AI 应用层·语义缓存评测报告\n",
         f"- 生成时间：{rep['meta']['generated_at']}",
         f"- 数据：`{rep['meta']['dataset']}`，{s['n_families']} 族 × 6 行 = {s['n_rows']} 条；"
         f"回放查询 {s['n_queries']} 条（同义改写 {s['query_roles']['paraphrase']}、"
         f"近邻负例 {s['query_roles']['hard_neg']}、无关对照 {s['query_roles']['unrelated']}）",
         f"- 答案模型：`{s['model']}`；向量模型：`{s['embedding_model']}`；"
         "计价来自 `application.yml` 的 `tims.ai.model-prices`",
         f"- 本轮实跑 {s['actual_calls']} 次模型调用，实测费用 **{s['actual_cost_cny']} 元**（含 50 条预热）",
         "- 判分：规格里的数值片段必须全部出现在答案中；缓存命中时返回的是**同族标准问法的答案**\n",
         "## 1. 结论\n",
         f"- 默认阈值 `{s['default_threshold']}`：同义改写命中 **{d['hit_rate_paraphrase_pct']}%**，"
         f"负例误命中 **{d['false_hit_rate_negative_pct']}%**，准确率 {d['accuracy_pct']}%（无缓存 {d['no_cache_accuracy_pct']}%），"
         f"质量损失 **{d['quality_loss_pp']} pp**",
         f"- 零错误命中的阈值里，`{s['best_zero_error_threshold']}` 命中率最高（"
         f"{s['best_zero_error_hit_rate_pct']}%）；首次出现错误命中的阈值是 `{s['first_wrong_threshold']}`。"
         f"默认值仍取更保守的 `{s['default_threshold']}`，把安全边际留在 0.92 与负例最大值之间",
         f"- 预热阶段 50 条标准问法的答案本身正确 {s['canonical_correct']}/{s['n_families']}"
         f"（{s['canonical_accuracy_pct']}%）；这一项是缓存质量的天花板",
         f"- 精确 hash 基线：命中 {s['exact']['hits']} 条（同义改写按定义为 0），质量损失 {s['exact']['quality_loss_pp']} pp",
         f"- 理想上界（只命中改写、不命中负例）：质量损失 {s['oracle']['quality_loss_pp']} pp，"
         f"省 {s['oracle']['saved_calls']} 次调用 / {s['oracle']['saved_cost_cny']} 元\n",
         "## 2. 阈值扫描（0.80–0.99）\n",
         "| 阈值 | 改写命中率 | 负例误命中率 | 命中数 | 准确率 | 无缓存准确率 | 质量损失 | 省下调用 | 省下费用（元） | 命中延迟（ms） | 未命中延迟（ms） |",
         "|---|---|---|---|---|---|---|---|---|---|---|",
         ]
    for x in rep["threshold_sweep"]:
        thr = "精确 hash" if x["threshold"] is None else ("oracle" if x["threshold"] == "oracle" else f"{x['threshold']:.2f}")
        L.append(f"| {thr} | {x['hit_rate_paraphrase_pct']}% | {x['false_hit_rate_negative_pct']}% | "
                 f"{x['hits']} | {x['accuracy_pct']}% | {x['no_cache_accuracy_pct']}% | "
                 f"{x['quality_loss_pp']} pp | {x['saved_calls']} | {x['saved_cost_cny']} | "
                 f"{x['avg_hit_latency_ms']} | {x['avg_miss_latency_ms']} |")
    L += ["",
          f"**相似度分布**：同义改写 min {s['paraphrase_similarity']['min']} / p10 {s['paraphrase_similarity']['p10']} / "
          f"中位 {s['paraphrase_similarity']['median']} / max {s['paraphrase_similarity']['max']}；"
          f"负例 max {s['negative_similarity']['max']} / p90 {s['negative_similarity']['p90']} / "
          f"中位 {s['negative_similarity']['median']}。",
          "两条分布的重叠区决定了阈值上限：把阈值压到改写 min 以下，必然开始误命中负例。\n",
          "## 3. 命中但答错（逐条可查）\n",
          f"默认阈值 `{s['default_threshold']}` 下共 **{d['wrong_hit_count']} 条**；"
          f"{first_wrong_txt}\n",
          "### 3.1 各阈值错误命中计数\n",
          "| 阈值 | 命中但答错 | 其中负例误命中 | 质量损失 |",
          "|---|---|---|---|",
          ]
    for x in rep["threshold_sweep"]:
        if not isinstance(x["threshold"], float):
            continue
        L.append(f"| {x['threshold']:.2f} | {x['wrong_hit_count']} | {x['wrong_hit_negative']} | "
                 f"{x['quality_loss_pp']} pp |")
    L += ["",
          f"### 3.2 默认阈值 {s['default_threshold']} 的逐条明细\n"]
    if rep["wrong_hits"]:
        L += ["| 行 | 类型 | 设备 | 问题 | 命中的标准问法 | 相似度 | 缺失规格值 | 缓存答案（截断） |",
              "|---|---|---|---|---|---|---|---|"]
        for w in rep["wrong_hits"]:
            L.append(f"| {w['id']} | {w['role']} | {w['device']} | {w['question']} | "
                     f"{w['matched_question']} | {w['similarity']} | {'/'.join(w['missing'])} | "
                     f"{w['cached_answer'].replace('|', '/')} |")
    else:
        L.append("无（0 条）。")
    L += ["",
          "### 3.3 全量错误命中（任意阈值 ≥0.80 曾命中，逐条可查）\n",
          "| 行 | 类型 | 设备 | 问题 | 命中的标准问法 | 最高相似度 | 命中阈值 | 缺失规格值 | 缓存答案（截断） |",
          "|---|---|---|---|---|---|---|---|---|",
          ]
    for w in rep.get("wrong_hit_index", []):
        L.append(f"| {w['id']} | {w['role']} | {w['device']} | {w['question']} | "
                 f"{w['matched_question']} | {w['similarity']} | "
                 f"{'/'.join(f'{t:.2f}' for t in w['thresholds'])} | {'/'.join(w['missing'])} | "
                 f"{w['cached_answer'].replace('|', '/')} |")
    if not rep.get("wrong_hit_index"):
        L.append("| - | - | - | 本轮无 | - | - | - | - | - |")
    L += ["",
          "相似度最高的负例（即使未命中，也列出供核查）：\n",
          "| 行 | 类型 | 相似度 | 问题 | 会在哪些阈值命中 |", "|---|---|---|---|---|"]
    for n in rep["false_hit_candidates"][:10]:
        L.append(f"| {n['id']} | {n['role']} | {n['similarity']} | {n['question']} | "
                 f"{'/'.join(str(t) for t in n['would_hit']) or '无'} |")
    L += ["",
          "完整逐条明细（每个阈值的错误命中、全部负例相似度）见 `缓存评测.json` 的 "
          "`wrong_hits_by_threshold`、`wrong_hit_index` 与 `false_hit_candidates`。\n",
          "## 4. 成本与延迟\n",
          f"- 无缓存：{s['n_queries']} 次模型调用，实测 {s['no_cache_cost_cny']} 元，平均 "
          f"{s['no_cache_avg_latency_ms']} ms（含向量化）",
          f"- 默认阈值：省下 {d['saved_calls']} 次调用 / {d['saved_cost_cny']} 元；"
          f"命中平均 {d['avg_hit_latency_ms']} ms，未命中平均 {d['avg_miss_latency_ms']} ms",
          f"- 向量费用：{s['embedding_cost_note']}；若按标准价另算，embedding-3 单价需以账单为准，本报告不计\n",
          "## 5. 局限\n",
          "1. 评测只回放了「标准问法预热 + 单次查询」，没有模拟多轮里缓存条目持续增长后的相互干扰；"
          "线上条目上限与 TTL 见配置。",
          "2. 生产实现的缓存桶还带「检索上下文指纹」（租户 + 工单 + 知识引用 + 历史）；"
          "本评测按同桶处理，因此负例误命中率是**上界**，线上会更低。",
          "3. 命中直接复用旧答案，若知识库在 TTL 内更新，用户会看到旧结论；这是缓存的固有代价，"
          "需要靠 TTL 与知识发布时的失效策略控制。",
          "4. 单实例进程内缓存；多实例部署时各实例独立命中，命中率按实例计，不共享。",
          "5. 质量判定只看规格数值是否出现，不判表述是否完整、是否存在额外错误信息。\n",
          "## 6. 接口与开关\n",
          "- 开关：`AI_CACHE_ENABLED=true`（默认 false）；阈值 `AI_CACHE_THRESHOLD`（默认 0.92）；"
          "TTL `AI_CACHE_TTL_SECONDS`；容量 `AI_CACHE_MAX_ENTRIES`",
          "- 同步响应新增可选字段 `cache`：命中 `{hit:true, similarity, exact, matchedQuestion, ageSeconds, threshold}`，"
          "未命中 `{hit:false, threshold}`；关闭时不返回该字段",
          "- 流式 SSE：`meta` 事件带同一个 `cache` 对象；`usage` 事件带 `cacheHit` 与 `cacheSimilarity`",
          "- 观测：命中调用在 `ai_call_log` 落一行 `status=CACHE_HIT`、token 计 0，可直接算命中率与省下的费用\n",
          ]
    return "\n".join(L)


if __name__ == "__main__":
    main()
