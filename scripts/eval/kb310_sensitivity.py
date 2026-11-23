#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""310 条知识库敏感性对照（只跑 VECTOR 单路 + 门控 B0）。

背景：M7 八轮消融与门控 B0 都是 2026-11-04/11-05 在 54/55 条快照上跑的，
2026-11-06 知识库扩到 310 条。本脚本只回答一个问题：
「换到 310 库后，VECTOR 单路的 Hit@1/3、Recall@5 与门控 B0 的覆盖率/错误推送率变了多少」，
不重跑 8 轮全表。

子命令：
  check      校验 100 条 query 的 gold ID 是否仍在 310 库中，列出缺失
  collect    采集 P（100 条正例）与 N（100 条负例）的 VECTOR 返回；要求门控关闭
  lg         跑 leave-gold-out（需门控关闭，脚本内部调用 leave_gold_out.sh）
  summarize  汇总指标并与 54 点快照对比，写 _kb310_metrics.json

用法（VM 上，服务 :8103 已就绪）：
  python3 scripts/eval/kb310_sensitivity.py check
  KB_GATE_ENABLED=false 重启服务后：
  python3 scripts/eval/kb310_sensitivity.py collect
  python3 scripts/eval/kb310_sensitivity.py lg
  python3 scripts/eval/kb310_sensitivity.py summarize
"""
import argparse
import csv
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from statistics import mean

REPO = os.environ.get("REPO", "/home/dev/ai-tims")
DOCS = os.path.join(REPO, "docs/paper/评测")
OUT = os.path.join(DOCS, "_kb310")
BASE = os.environ.get("KB_BASE", "http://127.0.0.1:8103")
T = 0.75


def http_get(path, params, timeout=30, attempts=20, wait=3):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    last = None
    for _ in range(attempts):
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(url, timeout=timeout) as r:
                body = json.load(r)
            return body["data"], round((time.perf_counter() - t0) * 1000.0, 1)
        except Exception as e:
            last = e
            time.sleep(wait)
    raise last


def load_kb():
    cache, page = {}, 1
    while True:
        d, _ = http_get("/api/kb/knowledge/page",
                        {"current": page, "size": 100, "status": "PUBLISHED"})
        for r in d["records"]:
            cache[str(r["id"])] = r
        if len(cache) >= d["total"] or not d["records"]:
            return cache
        page += 1


def load_eval():
    rows = []
    with open(os.path.join(DOCS, "eval_set.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({"query": r["query"],
                         "expected": [x for x in r["expectedIds"].split(";") if x],
                         "device": r["deviceType"], "note": r["note"]})
    return rows


def load_neg():
    rows = []
    with open(os.path.join(DOCS, "negative_set.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({"id": r["id"], "cls": r["class"], "query": r["query"],
                         "usable": [x for x in r["usableIds"].split(";") if x]})
    return rows


def summarize_resp(d, ms):
    items = d.get("items") or []
    return {
        "tier": d.get("tier"), "gateEnabled": d.get("gateEnabled"),
        "maxVectorScore": d.get("maxVectorScore"), "fallback": d.get("fallback"),
        "ms": ms,
        "ids": [str(x["id"]) for x in items],
        "items": [{"id": str(x["id"]), "score": x.get("score"),
                   "vectorScore": x.get("vectorScore")} for x in items],
    }


def check():
    os.makedirs(OUT, exist_ok=True)
    kb = load_kb()
    ev = load_eval()
    missing, queries = {}, []
    for i, r in enumerate(ev, 1):
        miss = [x for x in r["expected"] if x not in kb]
        if miss:
            missing["P-%03d" % i] = {"query": r["query"], "missing": miss,
                                     "surviving": [x for x in r["expected"] if x in kb]}
        queries.append({"idx": i, "query": r["query"], "expected": r["expected"],
                        "all_present": not miss})
    report = {"kb_records": len(kb), "eval_queries": len(ev),
              "queries_with_missing_gold": len(missing),
              "missing_gold_ids": sum(len(v["missing"]) for v in missing.values()),
              "missing": missing, "queries": queries}
    json.dump(report, open(os.path.join(OUT, "_gold_check.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("KB records:", len(kb), "| eval queries:", len(ev),
          "| 缺失 gold 的 query:", len(missing),
          "| 缺失 gold ID:", report["missing_gold_ids"])
    for k, v in missing.items():
        print("  MISSING", k, v["missing"], "| surviving", v["surviving"])
    return report


def collect():
    os.makedirs(OUT, exist_ok=True)
    ev = load_eval()
    ng = load_neg()
    probe, _ = http_get("/api/kb/search", {"query": ev[0]["query"], "mode": "VECTOR", "topK": 5})
    if probe.get("gateEnabled"):
        raise SystemExit("门控仍开启（gateEnabled=true）：C 档会返回空 items，检索指标不可用；"
                         "请以 KB_GATE_ENABLED=false 重启服务后重跑 collect")
    p_rows = []
    for i, r in enumerate(ev, 1):
        d5, ms5 = http_get("/api/kb/search", {"query": r["query"], "mode": "VECTOR", "topK": 5})
        rec = summarize_resp(d5, ms5)
        d10, ms10 = http_get("/api/kb/search", {"query": r["query"], "mode": "VECTOR", "topK": 10})
        rec["vec10"] = summarize_resp(d10, ms10)
        rec.update({"key": "P-%03d" % i, "query": r["query"],
                    "expected": r["expected"], "note": r["note"]})
        p_rows.append(rec)
        if i % 20 == 0:
            print("  P %d/100" % i, flush=True)
    n_rows = []
    for r in ng:
        d, ms = http_get("/api/kb/search", {"query": r["query"], "mode": "VECTOR", "topK": 5})
        rec = summarize_resp(d, ms)
        rec.update({"key": r["id"], "query": r["query"], "cls": r["cls"], "usable": r["usable"]})
        n_rows.append(rec)
    json.dump({"P": p_rows, "N": n_rows},
              open(os.path.join(OUT, "_collect.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("[ok] P=%d N=%d -> %s" % (len(p_rows), len(n_rows),
                                    os.path.join(OUT, "_collect.json")))


def lg():
    os.makedirs(OUT, exist_ok=True)
    inp = os.path.join(OUT, "_lg_in.tsv")
    outp = os.path.join(OUT, "_lg_out.tsv")
    with open(inp, "w", encoding="utf-8") as f:
        f.write("idx\tquery\tgoldIds\n")
        for i, r in enumerate(load_eval(), 1):
            f.write("%d\t%s\t%s\n" % (i, r["query"], ",".join(r["expected"])))
    subprocess.run(["bash", os.path.join(REPO, "scripts/eval/leave_gold_out.sh"), inp, outp],
                   check=True)
    print("[ok] LG ->", outp)


def hit_at(ranked, expected, n):
    return 1 if set(ranked[:n]) & set(expected) else 0


def recall_at(ranked, expected, n):
    return len(set(ranked[:n]) & set(expected)) / len(set(expected)) if expected else 0.0


def mrr(ranked, expected):
    for i, kid in enumerate(ranked, 1):
        if kid in expected:
            return 1.0 / i
    return 0.0


def pctl(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def read_lg():
    rows = []
    path = os.path.join(OUT, "_lg_out.tsv")
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("idx") or line.startswith("#") or not line.strip():
                continue
            p = line.rstrip("\n").split("\t")
            # RESTORE_FAILED 仅出现在「原 gold 有一个 ID 已缺失」的 4 行：删除的是存活 gold，
            # 校验时拿原始 gold 列表回查必然失败，但 #N1 已回到 310，数据无缺失。
            if len(p) < 6 or p[2] not in ("OK", "RESTORE_FAILED") or p[3] == "NA":
                continue
            rows.append({"idx": p[0], "status": p[2],
                         "maxVectorScore": float(p[3]),
                         "top1_id": p[4]})
    return rows


def summarize():
    with open(os.path.join(OUT, "_collect.json"), encoding="utf-8") as f:
        col = json.load(f)
    lg_rows = read_lg()
    p, n = col["P"], col["N"]

    ret = {}
    for key, fn in (("vec5", lambda x: x["ids"]),
                    ("vec10", lambda x: x["vec10"]["ids"][:5])):
        lat = [x["ms"] if key == "vec5" else x["vec10"]["ms"] for x in p]
        ret[key] = {
            "hit@1": round(mean(hit_at(fn(x), x["expected"], 1) for x in p) * 100, 1),
            "hit@3": round(mean(hit_at(fn(x), x["expected"], 3) for x in p) * 100, 1),
            "recall@5": round(mean(recall_at(fn(x), x["expected"], 5) for x in p) * 100, 1),
            "mrr": round(mean(mrr(fn(x), x["expected"]) for x in p), 3),
            "avg_ms": round(mean(lat), 1), "p95_ms": pctl(lat, 95),
        }

    def b0():
        p_push = [x for x in p if (x["maxVectorScore"] or 0) >= T]
        p_ok = [x for x in p_push if x["ids"] and x["ids"][0] in x["expected"]]
        n_push = [x for x in n if (x["maxVectorScore"] or 0) >= T]
        n_err = [x for x in n_push
                 if not (x["cls"] == "missing_noise" and x["ids"] and x["ids"][0] in x["usable"])]
        lg_push = [x for x in lg_rows if (x["maxVectorScore"] or 0) >= T]
        mix_push = len(p_push) + len(n_push) + len(lg_push)
        mix_err = (len(p_push) - len(p_ok)) + len(n_err) + len(lg_push)
        return {
            "T": T,
            "P_push": len(p_push), "P_push_rate": round(len(p_push) / len(p), 4),
            "P_correct": len(p_ok), "P_err": len(p_push) - len(p_ok),
            "push_acc": round(len(p_ok) / len(p_push), 4) if p_push else None,
            "N_push": len(n_push), "N_push_rate": round(len(n_push) / len(n), 4),
            "N_err": len(n_err),
            "N_err_rate": round(len(n_err) / len(n_push), 4) if n_push else None,
            "LG_n": len(lg_rows), "LG_push": len(lg_push),
            "C_rate": round(1 - mix_push / (len(p) + len(n) + len(lg_rows)), 4),
            "mix_push": mix_push, "mix_err": mix_err,
            "mix_err_rate": round(mix_err / mix_push, 4) if mix_push else None,
        }

    out = {"kb": "310", "retrieval": ret, "gate_b0": b0()}
    # 剔除「扩库后根因已被覆盖」的失效负例，给一版可比口径
    ncf = os.path.join(OUT, "_negcheck.json")
    if os.path.exists(ncf):
        nc = json.load(open(ncf, encoding="utf-8"))
        covered = {x["id"] for x in nc["rows"] if x["covered_in_310"]}
        n_valid = [x for x in n if x["key"] not in covered]
        p_push = [x for x in p if (x["maxVectorScore"] or 0) >= T]
        p_ok = [x for x in p_push if x["ids"] and x["ids"][0] in x["expected"]]
        n_push = [x for x in n_valid if (x["maxVectorScore"] or 0) >= T]
        n_err = [x for x in n_push
                 if not (x["cls"] == "missing_noise" and x["ids"] and x["ids"][0] in x["usable"])]
        lg_push = [x for x in lg_rows if (x["maxVectorScore"] or 0) >= T]
        mix_push = len(p_push) + len(n_push) + len(lg_push)
        mix_err = (len(p_push) - len(p_ok)) + len(n_err) + len(lg_push)
        out["gate_b0_valid_neg"] = {
            "excluded_neg": len(covered), "N_valid": len(n_valid),
            "N_push": len(n_push), "N_err": len(n_err),
            "N_err_rate": round(len(n_err) / len(n_push), 4) if n_push else None,
            "mix_push": mix_push, "mix_err": mix_err,
            "mix_err_rate": round(mix_err / mix_push, 4) if mix_push else None,
        }
    json.dump(out, open(os.path.join(OUT, "_kb310_metrics.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    base_ret = {"hit@1": 98.0, "hit@3": 100.0, "recall@5": 100.0}
    base_b0 = {"P_push": 77, "P_push_rate": 0.77, "P_correct": 77, "P_err": 0,
               "N_push": 34, "N_err": 18, "N_err_rate": 0.5294,
               "LG_push": 4, "C_rate": 0.6167, "mix_push": 115, "mix_err": 22,
               "mix_err_rate": 0.1913}
    print("\n=== 310 库 VECTOR 单路 ===")
    for k, v in ret.items():
        print(" %-6s Hit@1 %.1f (Δ%+.1f) | Hit@3 %.1f (Δ%+.1f) | Recall@5 %.1f (Δ%+.1f) | P95 %.1f ms"
              % (k, v["hit@1"], v["hit@1"] - base_ret["hit@1"],
                 v["hit@3"], v["hit@3"] - base_ret["hit@3"],
                 v["recall@5"], v["recall@5"] - base_ret["recall@5"], v["p95_ms"]))
    print("\n=== 310 库门控 B0（VECTOR, T=0.75） ===")
    for k in ("P_push", "P_push_rate", "P_correct", "P_err", "N_push", "N_err",
              "N_err_rate", "LG_push", "C_rate", "mix_push", "mix_err", "mix_err_rate"):
        print(" %-13s %s  (54 点 %s)" % (k, out["gate_b0"][k], base_b0[k]))

    print("\n=== 阈值扫描（310 库，供重标定参考） ===")
    for t in (0.75, 0.78, 0.80, 0.82, 0.85, 0.90):
        pp = [x for x in p if (x["maxVectorScore"] or 0) >= t]
        po = [x for x in pp if x["ids"] and x["ids"][0] in x["expected"]]
        np_ = [x for x in n if (x["maxVectorScore"] or 0) >= t]
        ne = [x for x in np_ if not (x["cls"] == "missing_noise" and x["ids"]
                                     and x["ids"][0] in x["usable"])]
        lp = [x for x in lg_rows if (x["maxVectorScore"] or 0) >= t]
        mp = len(pp) + len(np_) + len(lp)
        me = (len(pp) - len(po)) + len(ne) + len(lp)
        print("  T=%.2f  C 档 %.1f%%  总推送 %d  错误推送率 %.1f%%"
              % (t, 100 * (1 - mp / 300.0), mp, 100.0 * me / mp if mp else 0.0))
    print("\n[ok] ->", os.path.join(OUT, "_kb310_metrics.json"))


def bigrams(s):
    s = "".join(str(s).split())
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def jac(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / len(A | B) if A | B else 0.0


def diagnose():
    """解释 310 库上的排名变化：区分「同题近重复挤出」与「真检索跑偏」。"""
    kb = load_kb()
    col = json.load(open(os.path.join(OUT, "_collect.json"), encoding="utf-8"))
    ev = load_eval()
    rows, buckets = [], {"hit_top1": 0, "near_duplicate": 0,
                         "same_device_other_topic": 0, "other": 0}
    for i, x in enumerate(col["P"]):
        gold = x["expected"]
        top1 = x["ids"][0] if x["ids"] else None
        g_titles = [(kb.get(g) or {}).get("title", "") for g in gold]
        t1 = kb.get(top1) or {}
        sim = max((jac(t1.get("title", ""), gt) for gt in g_titles), default=0.0)
        device = ev[i]["device"]
        same_dev = bool(t1.get("applyDeviceType")) and t1.get("applyDeviceType") == device
        row = {"key": x["key"], "top1": top1, "top1_title": t1.get("title"),
               "gold_titles": g_titles, "title_sim": round(sim, 3),
               "top1_device": t1.get("applyDeviceType"), "device": device}
        if top1 in gold:
            buckets["hit_top1"] += 1
            row["bucket"] = "hit_top1"
        elif sim >= 0.6:
            buckets["near_duplicate"] += 1
            row["bucket"] = "near_duplicate"
        elif same_dev:
            buckets["same_device_other_topic"] += 1
            row["bucket"] = "same_device_other_topic"
        else:
            buckets["other"] += 1
            row["bucket"] = "other"
        rows.append(row)

    # 分数分布：310 库 vs 54 点快照（后者读 _gate_raw.json）
    def med(xs):
        xs = sorted(x for x in xs if x is not None)
        n = len(xs)
        return round((xs[n // 2] + xs[(n - 1) // 2]) / 2, 4) if n else None

    base = json.load(open(os.path.join(DOCS, "_gate_raw.json"), encoding="utf-8"))
    dist = {}
    for tag, data in (("54", {"P": base["VECTOR"]["P"], "N": base["VECTOR"]["N"]}),
                      ("310", {"P": col["P"], "N": col["N"]})):
        dist[tag] = {"P_median": med([z["maxVectorScore"] for z in data["P"]]),
                     "N_median": med([z["maxVectorScore"] for z in data["N"]]),
                     "P_ge_075": sum(1 for z in data["P"] if (z["maxVectorScore"] or 0) >= T),
                     "N_ge_075": sum(1 for z in data["N"] if (z["maxVectorScore"] or 0) >= T)}

    miss_top3 = [r for i, r in enumerate(rows) if r["bucket"] != "hit_top1"
                 and not (set(col["P"][i]["ids"][:3]) & set(col["P"][i]["expected"]))]
    out = {"buckets": buckets, "distribution": dist, "rows": rows,
           "miss_top3": [{"key": r["key"], "top1_title": r["top1_title"],
                          "gold_titles": r["gold_titles"]} for r in miss_top3]}
    json.dump(out, open(os.path.join(OUT, "_diagnose.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("Top1 归因:", buckets)
    print("分数分布:", json.dumps(dist, ensure_ascii=False))
    print("Top1 未命中明细:", len(rows) - buckets["hit_top1"])
    for r in rows:
        if r["bucket"] != "hit_top1":
            print("  %s [%s] top1=%s(%s) | gold=%s (sim=%.2f)"
                  % (r["key"], r["bucket"], r["top1_title"], r["top1_device"],
                     r["gold_titles"], r["title_sim"]))
    print("未进 Top3:", len(miss_top3))
    for r in out["miss_top3"]:
        print("  ", r["key"], "| top1:", r["top1_title"], "| gold:", r["gold_titles"])


def negcheck():
    """310 库扩库后，原负例集「根因关键词全库 0 命中」的前提是否仍成立。"""
    kb = load_kb()
    blob = "\n".join(str(r.get("content", "")) + str(r.get("title", "")) for r in kb.values())
    rows = []
    with open(os.path.join(DOCS, "negative_set.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            basis = r.get("basis", "")
            kw = ""
            if "“" in basis and "”" in basis:
                kw = basis.split("“", 1)[1].split("”", 1)[0]
            rows.append({"id": r["id"], "cls": r["class"], "query": r["query"],
                         "keyword": kw, "covered_in_310": bool(kw) and kw in blob})
    by_cls = {}
    for x in rows:
        s = by_cls.setdefault(x["cls"], {"n": 0, "covered": 0})
        s["n"] += 1
        s["covered"] += 1 if x["covered_in_310"] else 0
    out = {"total": len(rows), "covered": sum(1 for x in rows if x["covered_in_310"]),
           "by_class": by_cls, "rows": rows}
    json.dump(out, open(os.path.join(OUT, "_negcheck.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("负例前提校验：%d/%d 条的根因关键词在 310 库中出现" % (out["covered"], out["total"]))
    for k, v in by_cls.items():
        print("  %-24s %d/%d 已覆盖" % (k, v["covered"], v["n"]))
    for x in rows:
        if x["covered_in_310"]:
            print("  COVERED", x["id"], x["cls"], "kw=", x["keyword"])


def probe():
    """确认接口按 VECTOR 单路执行（避免 shell 引号吞掉 mode 参数）。"""
    for m in ("VECTOR", "HYBRID", "KEYWORD"):
        d, ms = http_get("/api/kb/search",
                         {"query": "MES终端报工接口超时处理", "mode": m, "topK": 3})
        print("%-7s -> mode=%s tier=%s total=%s gateEnabled=%s %sms"
              % (m, d.get("mode"), d.get("tier"), d.get("total"),
                 d.get("gateEnabled"), ms))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "collect", "lg", "summarize",
                                    "diagnose", "negcheck", "probe"])
    a = ap.parse_args()
    {"check": check, "collect": collect, "lg": lg, "summarize": summarize,
     "diagnose": diagnose, "negcheck": negcheck, "probe": probe}[a.cmd]()
