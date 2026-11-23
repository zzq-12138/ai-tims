#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen3-Embedding 门控阈值重标定（单文件、纯标准库，可在公司内网直接跑）。

背景
----
现网门控阈值 0.75 是 2026-11-05 在「智谱 embedding-3 + 55 条知识库」上标定的。
现在 embedding 换成公司 vLLM 的 Qwen/Qwen3-Embedding-8B（1024 维），知识库扩到 310 条，
分数分布整体下移，0.75 会把大量正确命中判成 C 档。本脚本用同一批 query 重扫阈值。

做什么
------
1) 读自包含数据包（310 条知识原文 + 100 条正例 + 100 条负例），不连数据库、不读 Milvus；
2) 文档侧只用原文向量化一次（不加任何前缀）；
3) 查询侧分别产出两组分数：不加 instruction 前缀 / 加 Qwen3 官方检索 instruction 前缀；
   一次运行同时拿到两组，进一次内网即可回传对比数据；
4) leave-gold-out 在内存里把 gold 从候选集中排除后再排序，不删除任何 Milvus / 数据库数据；
5) 输出逐条 CSV、汇总 JSON、0.40→0.85（步长 0.01）的「阈值—覆盖率—错误推送率」曲线表；
6) 单条/单批请求失败只记录并继续，失败明细写入 CSV，便于回传后定位。

外部依赖：仅 http://172.27.26.253:18893/v1/embeddings（OpenAI 兼容 /v1/embeddings）。

用法
----
  python3 -V                      # 需 3.8+，无需安装任何第三方包
  python3 qwen3_gate_eval.py --bundle qwen3_gate_bundle.json --out-dir qwen3_out

可选参数
--------
  --base-url   embedding 地址（默认公司 vLLM）
  --model      模型名（默认 Qwen/Qwen3-Embedding-8B）
  --dimensions 向量维度（默认 1024；传 0 表示不发送该参数）
  --instruction 查询侧前缀的任务描述（默认 Qwen3 官方英文检索指令）
  --batch-size 单次请求条数（默认 16）
  --timeout    单次请求超时秒数（默认 60）
  --retries    失败重试次数（默认 2，指数退避）
  --max-queries 只跑前 N 条正例/负例（冒烟用）
  --no-instruct 只跑不加前缀的一组（一般不用）
  --resume     复用上次的向量缓存（默认开启，缓存文件在 out-dir 下）

口径（与 docs/paper/评测/门控基线B0.md 一致）
------------------------------------------
- 置信度 = 该 query 在 310 条知识上的 top1 余弦（VECTOR 单路口径）；
- 推送 = top1 余弦 >= 阈值；
- 正例 P：top1 ∈ expectedIds 记为可用，否则为错误推送；
- leave-gold-out LG：先在候选集中排除该 query 的 expectedIds，再取 top1；按构造不可用；
- 负例 N：N1/N2/N3 一律不可用；N4（缺字段/噪声）top1 ∈ 原 gold 才算可用（保守口径）；
- 混合等权 = P + LG + N 各 100 条，错误推送率分母为推送量。
"""

import argparse
import csv
import hashlib
import heapq
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from operator import mul

DEFAULT_URL = "http://172.27.26.253:18893/v1/embeddings"
DEFAULT_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"
THRESHOLDS = [round(0.40 + 0.01 * i, 2) for i in range(46)]  # 0.40 .. 0.85
KEY_THRESHOLDS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
MIN_COVERAGE_PCT = 30.0  # 推荐阈值的最低正例覆盖率；低于它等于"把问答功能关掉"，不算可用工作点
CLASS_CN = {
    "same_symptom_diff_cause": "同象异因",
    "out_of_domain": "领域外",
    "same_cause_diff_symptom": "同因异象",
    "missing_noise": "缺字段/噪声",
}


# ----------------------------------------------------------------------------- 基础工具

def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def doc_text(doc):
    """与 VectorSyncService 送 embedding 的文本保持一致：title\\n + summary\\n + content。"""
    title = doc.get("title") or ""
    summary = doc.get("summary")
    content = doc.get("content") or ""
    return title + "\n" + ("" if summary is None else summary + "\n") + content


def query_text(query, instruction):
    """Qwen3-Embedding 检索侧格式：Instruct: {task}\\nQuery: {query}；instruction 为空则原文。"""
    if not instruction:
        return query
    return "Instruct: " + instruction + "\nQuery: " + query


def l2norm(vec):
    return math.sqrt(sum(x * x for x in vec))


def cosine(qv, qn, dv, dn):
    # 维度不一致说明服务端没按 dimensions 返回，直接报错比静默算错更安全
    if len(qv) != len(dv):
        raise ValueError("向量维度不一致: query=%d doc=%d" % (len(qv), len(dv)))
    return sum(map(mul, qv, dv)) / (qn * dn)


# ----------------------------------------------------------------------------- embedding 调用

class Embedder:
    def __init__(self, args, cache, failures):
        self.url = args.base_url
        self.model = args.model
        self.dimensions = args.dimensions
        self.api_key = args.api_key
        self.batch_size = max(1, args.batch_size)
        self.timeout = args.timeout
        self.retries = max(0, args.retries)
        self.cache = cache
        self.failures = failures
        self.calls = 0
        self.embedded = 0
        self.cached = 0

    def _post(self, texts):
        body = {"model": self.model, "input": list(texts)}
        if self.dimensions:
            body["dimensions"] = int(self.dimensions)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)
        self.calls += 1
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.load(resp)
        items = data.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise RuntimeError("返回条数不匹配: %s vs %d" % (
                len(items) if isinstance(items, list) else "null", len(texts)))
        out = [None] * len(texts)
        for i, item in enumerate(items):
            vec = item.get("embedding")
            if vec is None:
                continue
            idx = int(item.get("index", i))
            if idx < 0 or idx >= len(texts):
                idx = i
            out[idx] = [float(x) for x in vec]
        if any(v is None for v in out):
            raise RuntimeError("返回缺少向量: %d/%d" % (sum(v is None for v in out), len(texts)))
        return out

    def _post_with_retry(self, texts):
        last = None
        for attempt in range(self.retries + 1):
            try:
                return self._post(texts)
            except Exception as e:  # 网络/HTTP/解析错误统一重试
                last = e
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8))
        raise last

    def embed(self, texts, tag, progress_prefix=""):
        """返回与 texts 等长的向量列表；失败位置为 None。tag 用于区分缓存用途。"""
        out = [None] * len(texts)
        todo = []
        for i, text in enumerate(texts):
            key = sha1(tag + "\x00" + text)
            vec = self.cache.get(key)
            if vec is not None:
                out[i] = vec
                self.cached += 1
            else:
                todo.append(i)
        if not todo:
            return out
        total = len(todo)
        for start in range(0, total, self.batch_size):
            idxs = todo[start:start + self.batch_size]
            batch = [texts[i] for i in idxs]
            try:
                vecs = self._post_with_retry(batch)
            except Exception as e:
                # 整批失败 → 退回逐条，尽量保住能成功的条目
                print("   [warn] 批量失败(%d 条)，改逐条重试: %s" % (len(batch), e))
                vecs = []
                ok = 0
                for j, one in enumerate(batch):
                    try:
                        vecs.append(self._post_with_retry([one])[0])
                        ok += 1
                    except Exception as e2:
                        vecs.append(None)
                        self._record_failure(idxs[j], texts[idxs[j]], e2)
                print("   [warn] 逐条成功 %d/%d" % (ok, len(batch)))
            for i, vec in zip(idxs, vecs):
                if vec is None:
                    continue
                out[i] = vec
                self.cache[sha1(tag + "\x00" + texts[i])] = vec
                self.embedded += 1
            done = min(start + self.batch_size, total)
            print("   %s%5d/%5d" % (progress_prefix, done, total))
        return out

    def _record_failure(self, idx, text, err):
        self.failures.append({
            "index": idx,
            "text": text.replace("\n", " ")[:200],
            "error": "%s: %s" % (type(err).__name__, err),
        })


# ----------------------------------------------------------------------------- 排序 / 指标

def rank_top2(qv, docs, exclude_ids=None):
    """返回 [(score, doc), ...] 最多 2 条；exclude_ids 用于 leave-gold-out（内存排除，不删数据）。"""
    if not docs or qv is None:
        return []
    exclude_ids = exclude_ids or set()
    qn = l2norm(qv)
    if qn == 0:
        return []
    scored = []
    for d in docs:
        if d["id"] in exclude_ids:
            continue
        try:
            s = cosine(qv, qn, d["vec"], d["norm"])
        except ValueError:
            raise
        scored.append((s, d))
    return heapq.nlargest(2, scored, key=lambda x: x[0])


def pool_metrics(rows, threshold):
    pushed = [r for r in rows if r["score"] is not None and r["score"] >= threshold]
    errors = [r for r in pushed if not r["usable"]]
    return {
        "n": len(rows),
        "pushed": len(pushed),
        "pushed_error": len(errors),
        "coverage_pct": round(len(pushed) / len(rows) * 100, 1) if rows else 0.0,
        "error_rate_pct": round(len(errors) / len(pushed) * 100, 1) if pushed else 0.0,
    }


def auc(pos_scores, neg_scores):
    """Mann-Whitney U 形式的 AUC：正例分数显著高于负例时接近 1。"""
    pos = [x for x in pos_scores if x is not None]
    neg = [x for x in neg_scores if x is not None]
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                wins += 0.5
    return round(wins / (len(pos) * len(neg)), 4)


def distribution(scores):
    vals = sorted(x for x in scores if x is not None)
    if not vals:
        return None

    def q(p):
        k = (len(vals) - 1) * p
        lo, hi = int(math.floor(k)), int(math.ceil(k))
        return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 4)

    return {
        "n": len(vals),
        "mean": round(sum(vals) / len(vals), 4),
        "p10": q(0.10), "median": q(0.50), "p90": q(0.90),
        "min": round(vals[0], 4), "max": round(vals[-1], 4),
    }


# ----------------------------------------------------------------------------- 主流程

def load_bundle(path):
    data = json.load(open(path, encoding="utf-8"))
    kb = data.get("kb") or []
    if not kb:
        raise SystemExit("数据包缺少 kb 字段或为空: " + path)
    positives = data.get("positives") or []
    negatives = data.get("negatives") or []
    if not positives or not negatives:
        raise SystemExit("数据包缺少 positives/negatives: " + path)
    return data, kb, positives, negatives


def build_doc_vectors(kb, embedder):
    texts = [doc_text(d) for d in kb]
    print("[1/4] 文档向量化（原文，不加前缀）: %d 条" % len(texts))
    vecs = embedder.embed(texts, "doc")
    docs = []
    for d, v in zip(kb, vecs):
        if v is None:
            continue
        docs.append({"id": str(d["id"]), "title": d.get("title") or "", "vec": v, "norm": l2norm(v)})
    if len(docs) != len(kb):
        print("[warn] 文档向量失败 %d 条，已从候选集中剔除（结果会偏乐观，请先排查失败原因）"
              % (len(kb) - len(docs)))
    return docs


def build_query_rows(queries, embedder, tag, instruction):
    texts = [query_text(q["query"], instruction) for q in queries]
    print("   查询向量化: %s，%d 条" % (tag, len(texts)))
    vecs = embedder.embed(texts, "query:" + tag)
    return vecs


def evaluate_mode(mode, docs, positives, negatives, embedder, instruction, max_queries):
    print("[2/4] 计算 %s 模式分数（%s）" % (mode, "加 instruction" if instruction else "不加前缀"))
    all_queries = [{"id": p["id"], "query": p["query"]} for p in positives] + \
                  [{"id": n["id"], "query": n["query"]} for n in negatives]
    if max_queries:
        all_queries = all_queries[:max_queries]
    vecs = build_query_rows(all_queries, embedder, mode, instruction)
    vmap = {}
    for q, v in zip(all_queries, vecs):
        vmap[q["id"]] = v

    rows = []

    def add_row(set_name, rid, cls, query, top2, expected, usable, note=""):
        top1 = top2[0] if top2 else None
        rows.append({
            "mode": mode,
            "set": set_name,
            "id": rid,
            "class": cls,
            "query": query,
            "score": None if top1 is None else round(top1[0], 4),
            "top1_id": top1[1]["id"] if top1 else "",
            "top1_title": top1[1]["title"] if top1 else "",
            "top2_score": round(top2[1][0], 4) if len(top2) > 1 else None,
            "margin": round(top1[0] - top2[1][0], 4) if len(top2) > 1 and top1 else None,
            "expected": ";".join(expected),
            "usable": bool(usable),
            "correct_top1": bool(top2 and top2[0][1]["id"] in set(expected)),
            "note": note,
        })

    # 正例 P 与 leave-gold-out LG（同一批 query，LG 在内存里排除 gold）
    for p in positives:
        if max_queries and p["id"] not in vmap:
            continue
        qv = vmap.get(p["id"])
        expected = [str(x) for x in p.get("expectedIds") or []]
        top2 = rank_top2(qv, docs)
        top1_id = top2[0][1]["id"] if top2 else ""
        add_row("P", p["id"], "positive", p["query"], top2, expected, top1_id in expected,
                p.get("note", ""))
        lg_top2 = rank_top2(qv, docs, exclude_ids=set(expected))
        add_row("LG", p["id"], "leave_gold_out", p["query"], lg_top2, expected, False,
                "gold 已在内存中排除，无 gold 可命中")

    # 负例 N
    for n in negatives:
        if max_queries and n["id"] not in vmap:
            continue
        qv = vmap.get(n["id"])
        usable_ids = [str(x) for x in n.get("usableIds") or []]
        top2 = rank_top2(qv, docs)
        top1_id = top2[0][1]["id"] if top2 else ""
        usable = n["class"] == "missing_noise" and top1_id in usable_ids
        add_row("N", n["id"], n["class"], n["query"], top2, usable_ids, usable,
                CLASS_CN.get(n["class"], n["class"]))
    return rows


def summarize_mode(rows, valid_neg_ids=None):
    P = [r for r in rows if r["set"] == "P"]
    LG = [r for r in rows if r["set"] == "LG"]
    N = [r for r in rows if r["set"] == "N"]
    N_valid = [r for r in N if valid_neg_ids is None or r["id"] in valid_neg_ids]
    mixed = P + LG + N
    mixed_valid = P + LG + N_valid
    curve = []
    for t in THRESHOLDS:
        for name, pool in (("正例P", P), ("leave-gold-out", LG), ("负例N", N),
                           ("负例N(有效)", N_valid), ("混合等权", mixed),
                           ("混合等权(有效负例)", mixed_valid)):
            m = pool_metrics(pool, t)
            curve.append({"pool": name, "threshold": t, **m})

    def at(t, name):
        for r in curve:
            if r["pool"] == name and abs(r["threshold"] - t) < 1e-9:
                return r
        return None

    # 推荐点：在错误推送率 ≤3% 的阈值里取覆盖率最高者；若最高覆盖率也 <30%，
    # 说明"低错误率"是靠把绝大多数问题判成 C 档换来的，标为不可用工作点。
    def pick(pool_name):
        ok_rows = [r for r in curve
                   if r["pool"] == pool_name and r["error_rate_pct"] <= 3.0 and r["pushed"] > 0]
        if ok_rows:
            best = max(ok_rows, key=lambda r: (r["coverage_pct"], -r["threshold"]))
            item = dict(best)
            item["usable"] = best["coverage_pct"] >= MIN_COVERAGE_PCT
            if item["usable"]:
                note = "满足错误推送率≤3%% 且覆盖率≥%d%% 的覆盖率最高点" % int(MIN_COVERAGE_PCT)
            else:
                note = ("满足≤3%% 但正例覆盖率仅 %.1f%%（<%d%%），属把问答功能关掉，"
                        "不应当作可用工作点" % (best["coverage_pct"], int(MIN_COVERAGE_PCT)))
            return item, note
        cand = [r for r in curve if r["pool"] == pool_name and r["pushed"] > 0]
        if not cand:
            return None, "无推送样本"
        item = dict(min(cand, key=lambda r: r["error_rate_pct"] / 100.0 - r["coverage_pct"] / 100.0))
        item["usable"] = False
        return item, "不存在 ≤3% 的工作点；给出错误率与覆盖率的折中点，需人工判断"

    rec, rec_note = pick("混合等权")
    rec_valid, rec_valid_note = pick("混合等权(有效负例)")

    p_scores = [r["score"] for r in P]
    n_scores = [r["score"] for r in N]
    hit1 = None
    if P:
        hit1 = round(sum(1 for r in P if r["correct_top1"]) / len(P) * 100, 1)
    pools = ("正例P", "leave-gold-out", "负例N", "负例N(有效)", "混合等权", "混合等权(有效负例)")
    return {
        "curve": curve,
        "key_points": {str(t): {name: at(t, name) for name in pools}
                       for t in KEY_THRESHOLDS},
        "hit1_pct": hit1,
        "dist_positive": distribution(p_scores),
        "dist_negative": distribution(n_scores),
        "auc_positive_vs_negative": auc(p_scores, n_scores),
        "recommended_threshold": rec,
        "recommended_note": rec_note,
        "recommended_threshold_valid_negative": rec_valid,
        "recommended_note_valid_negative": rec_valid_note,
        "negative_by_class": {
            CLASS_CN[c]: {
                "n": len([r for r in N if r["class"] == c]),
                "error_at_0.75": pool_metrics([r for r in N if r["class"] == c], 0.75),
            } for c in CLASS_CN
        },
        "rows": rows,
    }


def write_csv(path, rows, columns):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def fmt_pct(v):
    return "%.1f%%" % v


def main():
    ap = argparse.ArgumentParser(description="Qwen3-Embedding 门控阈值重标定（纯标准库）")
    ap.add_argument("--bundle", default="qwen3_gate_bundle.json", help="自包含数据包路径")
    ap.add_argument("--out-dir", default="qwen3_out", help="输出目录")
    ap.add_argument("--base-url", default=DEFAULT_URL)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dimensions", type=int, default=1024, help="0 表示不发送 dimensions 参数")
    ap.add_argument("--api-key", default="", help="一般不需要；vLLM 未开鉴权则留空")
    ap.add_argument("--instruction", default=DEFAULT_INSTRUCTION, help="留空字符串表示不加前缀")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--max-queries", type=int, default=0, help="只跑前 N 条（冒烟用），0=全部")
    ap.add_argument("--no-instruct", action="store_true", help="只跑不加前缀的一组")
    ap.add_argument("--resume", action="store_true", default=True, help="复用向量缓存（默认开启）")
    ap.add_argument("--no-resume", dest="resume", action="store_false")
    args = ap.parse_args()

    t0 = time.time()
    os.makedirs(args.out_dir, exist_ok=True)
    cache_path = os.path.join(args.out_dir, "_cache_vectors.json")
    cache = {}
    if args.resume and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding="utf-8"))
            print("复用向量缓存: %d 条" % len(cache))
        except Exception as e:
            print("[warn] 缓存损坏，忽略: %s" % e)
            cache = {}

    data, kb, positives, negatives = load_bundle(args.bundle)
    print("数据包: kb=%d 正例=%d 负例=%d" % (len(kb), len(positives), len(negatives)))
    print("目标服务: %s | model=%s | dimensions=%s" % (args.base_url, args.model, args.dimensions))

    failures = []
    embedder = Embedder(args, cache, failures)
    docs = build_doc_vectors(kb, embedder)

    modes = [("raw", "")]
    if not args.no_instruct:
        modes.append(("instruct", args.instruction))

    valid_neg_ids = set(n["id"] for n in negatives if n.get("valid", True))
    results = {}
    for mode, instruction in modes:
        rows = evaluate_mode(mode, docs, positives, negatives, embedder, instruction, args.max_queries)
        results[mode] = summarize_mode(rows, valid_neg_ids)
        if args.resume:
            json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)

    # 自检：与公司环境实测值比对的固定 query（0.6751 是 310 库 + Qwen3-8B 的实测 top1）
    sanity = data.get("sanity") or {}
    sanity_result = None
    if sanity.get("query"):
        print("[3/4] 自检 query: %s" % sanity["query"])
        v = embedder.embed([sanity["query"]], "query:raw")[0]
        top2 = rank_top2(v, docs)
        if top2:
            got = round(top2[0][0], 4)
            exp = sanity.get("expected_top1_score")
            sanity_result = {
                "query": sanity["query"], "top1_score": got, "top1_title": top2[0][1]["title"],
                "company_measured": exp,
                "delta": None if exp is None else round(got - float(exp), 4),
                "consistent": None if exp is None else abs(got - float(exp)) <= 0.02,
            }
            print("   top1=%.4f 《%s》 公司实测=%s" % (got, top2[0][1]["title"], exp))

    if args.resume:
        json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)

    # ------------------------------------------------------------------ 输出
    print("[4/4] 写文件")
    all_rows = []
    for mode in results:
        all_rows.extend(results[mode]["rows"])
    write_csv(os.path.join(args.out_dir, "qwen3_gate_scores.csv"), all_rows,
              ["mode", "set", "id", "class", "query", "score", "top1_id", "top1_title",
               "top2_score", "margin", "expected", "usable", "correct_top1", "note"])

    curve_rows = []
    for mode, res in results.items():
        for r in res["curve"]:
            curve_rows.append({"mode": mode, **r})
    write_csv(os.path.join(args.out_dir, "qwen3_gate_curve.csv"), curve_rows,
              ["mode", "pool", "threshold", "n", "pushed", "pushed_error", "coverage_pct", "error_rate_pct"])

    # 前缀前后逐条对比（正例/负例各一组）+ 汇总统计
    prefix_rows = []
    prefix_effect = None
    if "raw" in results and "instruct" in results:
        raw_map = {r["id"]: r for r in results["raw"]["rows"]}
        for r in results["instruct"]["rows"]:
            base = raw_map.get(r["id"])
            if not base:
                continue
            prefix_rows.append({
                "set": r["set"], "id": r["id"], "class": r["class"], "query": r["query"],
                "raw_score": base["score"], "instruct_score": r["score"],
                "delta": None if (base["score"] is None or r["score"] is None)
                else round(r["score"] - base["score"], 4),
                "raw_top1_id": base["top1_id"], "instruct_top1_id": r["top1_id"],
                "raw_usable": base["usable"], "instruct_usable": r["usable"],
            })
        write_csv(os.path.join(args.out_dir, "qwen3_prefix_compare.csv"), prefix_rows,
                  ["set", "id", "class", "query", "raw_score", "instruct_score", "delta",
                   "raw_top1_id", "instruct_top1_id", "raw_usable", "instruct_usable"])

        def median(vals):
            vals = sorted(vals)
            if not vals:
                return None
            mid = len(vals) // 2
            return round(vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0, 4)

        def delta_stats(set_name):
            ds = [r["delta"] for r in prefix_rows
                  if r["set"] == set_name and r["delta"] is not None]
            if not ds:
                return None
            return {"n": len(ds), "mean_delta": round(sum(ds) / len(ds), 4),
                    "median_delta": median(ds),
                    "pct_score_higher": round(sum(1 for x in ds if x > 0) / len(ds) * 100, 1)}

        changed = [r for r in prefix_rows if r["raw_top1_id"] != r["instruct_top1_id"]]
        prefix_effect = {
            "positive_P": delta_stats("P"),
            "negative_N": delta_stats("N"),
            "leave_gold_out_LG": delta_stats("LG"),
            "top1_changed_num": len(changed),
            "top1_changed_list": [{"id": r["id"], "query": r["query"],
                                   "raw": r["raw_top1_id"], "instruct": r["instruct_top1_id"]}
                                  for r in changed[:30]],
            "hit1_raw_pct": results["raw"]["hit1_pct"],
            "hit1_instruct_pct": results["instruct"]["hit1_pct"],
            "auc_raw": results["raw"]["auc_positive_vs_negative"],
            "auc_instruct": results["instruct"]["auc_positive_vs_negative"],
        }

    if failures:
        write_csv(os.path.join(args.out_dir, "qwen3_failures.csv"), failures, ["index", "text", "error"])
    else:
        write_csv(os.path.join(args.out_dir, "qwen3_failures.csv"), [], ["index", "text", "error"])

    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 1),
        "config": {
            "base_url": args.base_url, "model": args.model, "dimensions": args.dimensions,
            "instruction": args.instruction if not args.no_instruct else "(skipped)",
            "batch_size": args.batch_size, "max_queries": args.max_queries,
            "kb_docs_in_bundle": len(kb), "positives": len(positives), "negatives": len(negatives),
            "kb_docs_embedded": len(docs),
        },
        "embedding_stats": {"calls": embedder.calls, "embedded": embedder.embedded,
                            "cache_hits": embedder.cached, "failures": len(failures)},
        "sanity_check": sanity_result,
        "prefix_effect": prefix_effect,
        "modes": {mode: {k: v for k, v in res.items() if k != "rows"} for mode, res in results.items()},
    }
    json.dump(summary, open(os.path.join(args.out_dir, "qwen3_gate_summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ------------------------------------------------------------------ 控制台报告
    print("\n================ 结果摘要 ================")
    for mode, res in results.items():
        label = "加 instruction" if mode == "instruct" else "不加前缀"
        print("\n[%s] Hit@1=%.1f%%  AUC(正/负)=%s" % (label, res["hit1_pct"] or 0,
                                                     res["auc_positive_vs_negative"]))
        print("阈值 | 正例覆盖 | 正例错误率 | 负例错误率 | 负例(有效) | LG错误率 | 混合错误率 | 混合(有效)")
        for t in KEY_THRESHOLDS:
            kp = res["key_points"][str(t)]
            print("%.2f | %6s | %8s | %8s | %9s | %7s | %8s | %8s" % (
                t, fmt_pct(kp["正例P"]["coverage_pct"]),
                fmt_pct(kp["正例P"]["error_rate_pct"]),
                fmt_pct(kp["负例N"]["error_rate_pct"]),
                fmt_pct(kp["负例N(有效)"]["error_rate_pct"]),
                fmt_pct(kp["leave-gold-out"]["error_rate_pct"]),
                fmt_pct(kp["混合等权"]["error_rate_pct"]),
                fmt_pct(kp["混合等权(有效负例)"]["error_rate_pct"])))
        rec = res["recommended_threshold"]
        if rec:
            print("建议阈值: %.2f（%s；此时正例覆盖 %.1f%%，混合错误推送率 %.1f%%）" %
                  (rec["threshold"], res["recommended_note"], rec["coverage_pct"], rec["error_rate_pct"]))
        print("分布: 正例 %s" % res["dist_positive"])
        print("      负例 %s" % res["dist_negative"])

    if prefix_effect:
        pp = prefix_effect["positive_P"] or {}
        nn = prefix_effect["negative_N"] or {}
        print("\n[前缀效果] 正例Δ中位数=%s（抬高比例 %s%%）｜负例Δ中位数=%s｜top1 改变 %d 条"
              % (pp.get("median_delta"), pp.get("pct_score_higher"),
                 nn.get("median_delta"), prefix_effect["top1_changed_num"]))
        print("           Hit@1: %.1f%% → %.1f%% ｜ AUC: %s → %s" % (
            prefix_effect["hit1_raw_pct"] or 0, prefix_effect["hit1_instruct_pct"] or 0,
            prefix_effect["auc_raw"], prefix_effect["auc_instruct"]))

    print("\n失败条数: %d（明细 %s）" % (len(failures), os.path.join(args.out_dir, "qwen3_failures.csv")))
    print("耗时: %.1fs" % (time.time() - t0))
    print("\n需要回传的文件（都在 %s 下）：" % os.path.abspath(args.out_dir))
    for name in ("qwen3_gate_scores.csv", "qwen3_gate_curve.csv", "qwen3_gate_summary.json",
                 "qwen3_prefix_compare.csv", "qwen3_failures.csv"):
        print("  - " + name)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断")
        sys.exit(130)
