#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M7 检索消融评测（E1~E8）。

设计：
- 全部取数走现有 HTTP 接口（KEYWORD / VECTOR / HYBRID），不改后端代码；
- 每个 query 采集 5 个快照：vec10 / kw10 / hybrid10 / vec5 / hybrid5，
  带端到端耗时，落 _candidates.json 缓存，支持断点续跑（服务重启不丢进度）；
- E3~E7 的融合权重与 RRF k 在本地按 SearchService.rrfFuse 同一公式复算
  （现有接口只暴露 query/mode/topK，未暴露权重与 k）；
- E2/E5/E8/E8H 指标直接来自真实接口返回；E5 与离线复算的前 3 集合一致率用于校验复算；
- Milvus 未就绪时 VECTOR/HYBRID 会静默降级（fallback=true），前置检查直接中止。

用法: python3 run_eval.py [--eval docs/paper/评测/eval_set.csv] [--out docs/paper/评测]
"""
import argparse
import csv
import json
import os
import statistics
import time
import urllib.parse
import urllib.request

BASE = os.environ.get("KB_BASE", "http://127.0.0.1:8103")


def http_get(path, params, timeout=20, attempts=30, wait=5):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    last = None
    for _ in range(attempts):
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(url, timeout=timeout) as r:
                body = json.load(r)
            return body["data"], (time.perf_counter() - t0) * 1000.0
        except Exception as e:  # 服务被其他会话重启时重试
            last = e
            time.sleep(wait)
    raise last


def search(query, mode, top_k):
    return http_get("/api/kb/search", {"query": query, "mode": mode, "topK": top_k})


def load_kb():
    cache, page = {}, 1
    while True:
        d, _ = http_get("/api/kb/knowledge/page", {"current": page, "size": 100, "status": "PUBLISHED"})
        for r in d["records"]:
            cache[str(r["id"])] = r
        if len(cache) >= d["total"] or not d["records"]:
            return cache
        page += 1


def tag_hit(tags_json, query):
    if not tags_json:
        return False
    t = str(tags_json).replace("[", "").replace("]", "").replace('"', "")
    for tag in t.split(","):
        g = tag.strip()
        if len(g) >= 2 and g in query:
            return True
    return False


def rrf_fuse(vec_ids, kw_ids, k, dev_boost, tag_boost, query, kb):
    """复刻 SearchService.rrfFuse：两路各前 10，1/(k+rank+1) 累加，可选设备/标签加权。"""
    score, order = {}, []
    for ids in (vec_ids, kw_ids):
        for i, kid in enumerate(ids):
            score[kid] = score.get(kid, 0.0) + 1.0 / (k + i + 1)
            if kid not in order:
                order.append(kid)
    boosted = {}
    for kid, s in score.items():
        rec = kb.get(kid) or {}
        dev = rec.get("applyDeviceType")
        if dev_boost and dev and dev in query:
            s *= dev_boost
        if tag_boost and tag_hit(rec.get("tags"), query):
            s *= tag_boost
        boosted[kid] = s
    pos = {kid: i for i, kid in enumerate(order)}
    return sorted(order, key=lambda x: (-boosted[x], pos[x]))


def hit_at(ranked, expected, n):
    return 1 if set(ranked[:n]) & set(expected) else 0


def recall_at(ranked, expected, n):
    if not expected:
        return 0.0
    return len(set(ranked[:n]) & set(expected)) / len(set(expected))


def mrr(ranked, expected):
    for i, kid in enumerate(ranked, 1):
        if kid in expected:
            return 1.0 / i
    return 0.0


def pct(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[idx], 1)


def metrics(data, ranking_fn, latencies):
    hits, h1, h5, rec, mr = [], [], [], [], []
    for d in data:
        ranked = ranking_fn(d)
        hits.append(hit_at(ranked, d["expected"], 3))
        h1.append(hit_at(ranked, d["expected"], 1))
        h5.append(hit_at(ranked, d["expected"], 5))
        rec.append(recall_at(ranked, d["expected"], 5))
        mr.append(mrr(ranked, d["expected"]))
    n = len(data)
    return {
        "hit@1": round(sum(h1) / n * 100, 1),
        "hit@3": round(sum(hits) / n * 100, 1),
        "hit@5": round(sum(h5) / n * 100, 1),
        "recall@5": round(sum(rec) / n * 100, 1),
        "mrr": round(sum(mr) / n, 3),
        "avg_ms": round(statistics.mean(latencies), 1),
        "p95_ms": pct(latencies, 95),
    }


def collect_one(text):
    snap = {}
    for key, mode, topk in (("vec10", "VECTOR", 10), ("kw10", "KEYWORD", 10),
                            ("hyb10", "HYBRID", 10), ("vec5", "VECTOR", 5),
                            ("hyb5", "HYBRID", 5)):
        d, ms = search(text, mode, topk)
        snap[key] = {"ids": [str(x["id"]) for x in d["items"]], "ms": round(ms, 1),
                     "fallback": d["fallback"]}
    return snap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default="docs/paper/评测/eval_set.csv")
    ap.add_argument("--out", default="docs/paper/评测")
    args = ap.parse_args()
    cache_file = os.path.join(args.out, "_candidates.json")

    queries = list(csv.DictReader(open(args.eval, encoding="utf-8")))
    cache = json.load(open(cache_file, encoding="utf-8")) if os.path.exists(cache_file) else {}

    kb = load_kb()
    probe, _ = search(queries[0]["query"], "VECTOR", 1)
    if probe["fallback"]:
        raise SystemExit("VECTOR 检索处于降级（fallback=true），Milvus 未就绪，评测中止")
    print("评测样本:", len(queries), "知识库记录:", len(kb), "缓存已有:", len(cache))

    for i, q in enumerate(queries):
        if q["query"] not in cache:
            cache[q["query"]] = collect_one(q["query"])
            if (i + 1) % 10 == 0:
                json.dump(cache, open(cache_file, "w", encoding="utf-8"), ensure_ascii=False)
                print("  采集", len(cache), "/", len(queries))
    json.dump(cache, open(cache_file, "w", encoding="utf-8"), ensure_ascii=False)

    data = []
    for q in queries:
        snap = cache[q["query"]]
        data.append({
            "q": q, "text": q["query"],
            "expected": [x.strip() for x in q["expectedIds"].split(";") if x.strip()],
            "vec": snap["vec10"]["ids"], "kw": snap["kw10"]["ids"], "hybrid": snap["hyb10"]["ids"],
            "lat_vec10": snap["vec10"]["ms"], "lat_kw10": snap["kw10"]["ms"],
            "lat_hyb10": snap["hyb10"]["ms"],
            "vec5": snap["vec5"]["ids"], "hyb5": snap["hyb5"]["ids"],
            "lat_vec5": snap["vec5"]["ms"], "lat_hyb5": snap["hyb5"]["ms"],
            "fallback": any(snap[k]["fallback"] for k in ("vec10", "hyb10", "vec5", "hyb5")),
        })
    fallback_count = sum(1 for d in data if d["fallback"])

    # 校验离线复算与生产接口的前 3 集合一致率
    mismatch = sum(1 for d in data
                   if set(rrf_fuse(d["vec"], d["kw"], 60, 1.5, 1.2, d["text"], kb)[:3]) != set(d["hybrid"][:3]))

    def offline(d, k, dev, tag):
        return rrf_fuse(d["vec"], d["kw"], k, dev, tag, d["text"], kb)

    lat_fuse = []
    for d in data:
        t0 = time.perf_counter()
        offline(d, 60, 1.5, 1.2)
        lat_fuse.append(d["lat_kw10"] + d["lat_vec10"] + (time.perf_counter() - t0) * 1000.0)

    configs = [
        ("E1", "KEYWORD 基线", "KEYWORD", 3, 60, 0, 0, lambda d: d["kw"][:5], [d["lat_kw10"] for d in data]),
        ("E2", "VECTOR 基线", "VECTOR", 3, 60, 0, 0, lambda d: d["vec"][:5], [d["lat_vec10"] for d in data]),
        ("E3", "HYBRID RRF k=60 无加权", "HYBRID", 3, 60, 0, 0, lambda d: offline(d, 60, 0, 0), lat_fuse),
        ("E4", "HYBRID + 设备加权 1.5", "HYBRID", 3, 60, 1.5, 0, lambda d: offline(d, 60, 1.5, 0), lat_fuse),
        ("E5", "HYBRID + 设备 1.5 + 标签 1.2（生产配置）", "HYBRID", 3, 60, 1.5, 1.2,
         lambda d: d["hybrid"][:5], [d["lat_hyb10"] for d in data]),
    ]
    stats = {}
    for rid, name, mode, topk, k, dv, tg, fn, lat in configs:
        st = metrics(data, fn, lat)
        st.update({"round": rid, "name": name, "mode": mode, "topK": topk,
                   "rrf_k": k, "dev_boost": dv, "tag_boost": tg})
        stats[rid] = st
        print(rid, st)

    for k in (30, 60, 100):
        st = metrics(data, lambda d, kk=k: offline(d, kk, 1.5, 1.2), lat_fuse)
        st.update({"round": f"E6-k{k}", "name": f"HYBRID + 双加权, RRF k={k}", "mode": "HYBRID",
                   "topK": 3, "rrf_k": k, "dev_boost": 1.5, "tag_boost": 1.2})
        stats[f"E6-k{k}"] = st
        print(f"E6-k{k}", st)
    best_k = max((30, 60, 100), key=lambda k: (stats[f"E6-k{k}"]["hit@3"], stats[f"E6-k{k}"]["recall@5"],
                                               -abs(k - 60)))
    print("E6 最优 RRF k =", best_k)

    for tk in (1, 3, 5):
        st = metrics(data, lambda d: offline(d, best_k, 1.5, 1.2), lat_fuse)
        st.update({"round": f"E7-top{tk}", "name": f"最优 k={best_k} + 双加权, topK={tk}", "mode": "HYBRID",
                   "topK": tk, "rrf_k": best_k, "dev_boost": 1.5, "tag_boost": 1.2})
        if tk < 3:
            st["hit@3"] = None
        stats[f"E7-top{tk}"] = st
        print(f"E7-top{tk}", st)

    # E8 最优组合：按 Hit@3 取 VECTOR（真实接口 topK=5）
    st = metrics(data, lambda d: d["vec5"], [d["lat_vec5"] for d in data])
    st.update({"round": "E8", "name": "最优组合复跑（VECTOR + topK=5，真实接口）", "mode": "VECTOR",
               "topK": 5, "rrf_k": None, "dev_boost": 0, "tag_boost": 0})
    stats["E8"] = st
    print("E8", st)

    # E8H 补充：生产 HYBRID topK=5 复跑
    st = metrics(data, lambda d: d["hyb5"], [d["lat_hyb5"] for d in data])
    st.update({"round": "E8H", "name": "生产配置复跑（HYBRID k=60+设备1.5+标签1.2+topK=5）", "mode": "HYBRID",
               "topK": 5, "rrf_k": 60, "dev_boost": 1.5, "tag_boost": 1.2})
    stats["E8H"] = st
    print("E8H", st)

    # 按 query 风格细分（生产配置）
    style_stat = {}
    for d in data:
        style = d["q"]["note"].split("|")[0]
        s = style_stat.setdefault(style, {"n": 0, "hit": 0, "h1": 0, "rec": 0.0})
        s["n"] += 1
        s["hit"] += hit_at(d["hyb5"], d["expected"], 3)
        s["h1"] += hit_at(d["hyb5"], d["expected"], 1)
        s["rec"] += recall_at(d["hyb5"], d["expected"], 5)
    for k in style_stat:
        s = style_stat[k]
        s["hit@3"] = round(s["hit"] / s["n"] * 100, 1)
        s["hit@1"] = round(s["h1"] / s["n"] * 100, 1)
        s["recall@5"] = round(s["rec"] / s["n"] * 100, 1)

    def failed_from(ranks):
        out = []
        for d, ranked in zip(data, ranks):
            if not hit_at(ranked, d["expected"], 3):
                out.append({
                    "query": d["text"], "style": d["q"]["note"].split("|")[0],
                    "expected": d["expected"], "returned": ranked[:5],
                    "kw": d["kw"][:5], "vec": d["vec"][:5],
                    "expected_title": (kb.get(d["expected"][0]) or {}).get("title"),
                    "returned_titles": [(kb.get(x) or {}).get("title") for x in ranked[:3]],
                })
        return out

    failed_hybrid = failed_from([d["hyb5"] for d in data])
    failed_kw = failed_from([d["kw"][:5] for d in data])
    failed, seen = [], set()
    for f in failed_hybrid + failed_kw:
        if f["query"] not in seen:
            seen.add(f["query"])
            failed.append(f)
        if len(failed) >= 12:
            break

    # ---------- 写出 ----------
    rows = []
    specs = [(rid, name, mode, topk, k, dv, tg, fn, lat) for rid, name, mode, topk, k, dv, tg, fn, lat in configs]
    specs += [(f"E6-k{k}", "", "HYBRID", 3, k, 1.5, 1.2, lambda d, kk=k: offline(d, kk, 1.5, 1.2), lat_fuse)
              for k in (30, 60, 100)]
    specs += [(f"E7-top{tk}", "", "HYBRID", tk, best_k, 1.5, 1.2, lambda d: offline(d, best_k, 1.5, 1.2), lat_fuse)
              for tk in (1, 3, 5)]
    specs += [("E8", "", "VECTOR", 5, "", 0, 0, lambda d: d["vec5"], [d["lat_vec5"] for d in data])]
    specs += [("E8H", "", "HYBRID", 5, 60, 1.5, 1.2, lambda d: d["hyb5"], [d["lat_hyb5"] for d in data])]
    for rid, name, mode, topk, k, dv, tg, fn, lat in specs:
        for i, d in enumerate(data):
            ranked = fn(d)
            rows.append({
                "round": rid, "mode": mode, "topK": topk, "rrf_k": k,
                "dev_boost": dv, "tag_boost": tg,
                "query": d["text"], "style": d["q"]["note"].split("|")[0],
                "expected_ids": d["q"]["expectedIds"], "returned_ids": ";".join(ranked[:max(topk, 3)]),
                "hit3": hit_at(ranked, d["expected"], 3),
                "recall5": round(recall_at(ranked, d["expected"], 5), 3),
                "mrr": round(mrr(ranked, d["expected"]), 3),
                "latency_ms": round(lat[i], 1),
            })

    with open(os.path.join(args.out, "消融结果.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["round", "mode", "topK", "rrf_k", "dev_boost", "tag_boost",
                                          "query", "style", "expected_ids", "returned_ids",
                                          "hit3", "recall5", "mrr", "latency_ms"])
        w.writeheader()
        w.writerows(rows)

    meta = {
        "samples": len(queries), "kb_records": len(kb), "fallback_queries": fallback_count,
        "fusion_mismatch_vs_api": mismatch, "best_k": best_k,
        "stats": stats, "style_stats": style_stat,
        "failed_e8h": failed_hybrid, "failed_kw": failed_kw, "failed": failed,
    }
    json.dump(meta, open(os.path.join(args.out, "_metrics.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("写出 消融结果.csv / _metrics.json；fallback:", fallback_count,
          "复算前3不一致:", mismatch, "失败样本:", len(failed))


if __name__ == "__main__":
    main()
