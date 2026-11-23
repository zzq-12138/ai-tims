#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A1-v1 留出集评测：检测规则来自生产 ModelRouter.calcVerifiable（同一份实现），
验证器沿用开发集冻结的题面复算（verify_calc_gold.recompute），不做任何回改。

口径：
  升级率        = calc 分片中被升级的比例
  漏升级率      = 小模型答错却没有升级的比例（越低越好）
  误升级率      = simple 分片（有数字但不计算 / 单步）被升级的比例（越低越好）
  升级后正确率  = 升级子集的最终正确率
  总准确率      = 全部分片最终正确率

同时用 --dev 复算开发集 400 条在 A1-v1 下的指标（复用已有缓存，不产生 API 费用），
与留出集并列。

输出：
  docs/paper/ai应用层/路由修复留出集.json
  docs/paper/ai应用层/raw/holdout_detail.csv
  docs/paper/ai应用层/raw/holdout_rows.json      （答案缓存，题面指纹失效）

用法（仓库根目录）：
  python3 scripts/ai_layer/route_holdout_eval.py --probe
  python3 scripts/ai_layer/route_holdout_eval.py
"""
import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from verify_calc_gold import recompute  # noqa: E402  冻结的 A1 验证器

HOLDOUT = HERE / "data" / "holdout_set.tsv"
HOLDOUT_JAVA = HERE / "data" / "holdout_java.tsv"
BASE_TSV = HERE / "data" / "route_set.tsv"
FIX_TSV = HERE / "data" / "route_fix_set.tsv"
OUT_DIR = ROOT / "docs" / "paper" / "ai应用层"
RAW = OUT_DIR / "raw"
CACHE = RAW / "holdout_rows.json"
BASE_CACHE = RAW / "routing_rows.json"
FIX_CACHE = RAW / "route_fix_rows.json"
OLD_JSON = OUT_DIR / "路由修复评测.json"
OUT_JSON = OUT_DIR / "路由修复留出集.json"
OUT_CSV = RAW / "holdout_detail.csv"
BUILD = ROOT / ".eval_out" / "route"
AI_SRC = ROOT / "ai-tims-parent" / "ticket-ai" / "src" / "main" / "java"
EVAL_JAVA = HERE / "java" / "RouteEvalMain.java"
PROBE_JAVA = HERE / "java" / "CalcProbeMain.java"
YML = ROOT / "ai-tims-parent" / "ticket-ai" / "src" / "main" / "resources" / "application.yml"

API = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
KEY_FILE = Path(os.environ.get("LLM_API_KEY_FILE", "/home/dev/secrets/zhipu_api_key"))
SYSTEM_PROMPT = ("你是 AI-TIMS 工业设备运维助手。只依据给定参考资料回答；先给结论，再给关键依据；"
                 "资料不足时明确说明。回答控制在 150 字以内。")
MAX_TOKENS = 8192
WORKERS = 6
TOL = 0.06
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


# ---------------------------------------------------------------- 基础
def load_prices():
    text = YML.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^\s+([\w.\-]+):\s*\{\s*input-per-1k:\s*([\d.]+),\s*output-per-1k:\s*([\d.]+)\s*\}",
                         text, re.M):
        out[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    if not out:
        raise SystemExit("未能从 application.yml 解析 model-prices")
    return out


def post(url, key, body, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def call_model(key, model, question, context, retries=3):
    body = {"model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": f"参考资料：\n{context}\n\n问题：{question}"}],
            "max_tokens": MAX_TOKENS, "temperature": 0.3}
    last = None
    for i in range(retries):
        try:
            t0 = time.time()
            d = post(API, key, body)
            u = d.get("usage") or {}
            msg = d["choices"][0]["message"]
            return {"model": model, "latency_s": round(time.time() - t0, 2),
                    "prompt_tokens": int(u.get("prompt_tokens") or 0),
                    "completion_tokens": int(u.get("completion_tokens") or 0),
                    "answer": (msg.get("content") or "").strip()}
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def cost_of(call, prices):
    pin, pout = prices.get(call["model"], (0.0008, 0.0028))
    return call["prompt_tokens"] / 1000.0 * pin + call["completion_tokens"] / 1000.0 * pout


def qhash(r):
    return hashlib.md5((r["question"] + "\x00" + r["context"]).encode()).hexdigest()[:12]


def nums(text):
    return [float(x) for x in NUM_RE.findall((text or "").replace(",", ""))]


def norm(s):
    s = (s or "").strip().lower()
    s = s.replace("～", "-").replace("~", "-").replace("—", "-").replace("–", "-").replace("－", "-")
    s = s.replace("．", ".").replace(" ", "").replace("％", "%")
    s = s.replace("毫秒", "ms").replace("分钟", "min").replace("秒", "s")
    return s


def graded(gold, answer):
    a = norm(answer)
    return all(norm(g) in a for g in gold.split("|") if g)


def calc_ok(gold, answer):
    got = nums(answer)
    for g in gold.split("|"):
        if not g:
            continue
        if not any(abs(v - float(g)) <= TOL for v in got):
            return False
    return True


def dev_ok(r, src, key, answer):
    """开发集判分口径与旧评测一致：计算题数值、templated 盲评优先、其余关键词"""
    if r["slice"] in ("calc", "calc_single"):
        return calc_ok(r["gold"], answer)
    if r["slice"] == "templated":
        j = src.get("judge") or {}
        if key in j:
            return bool(j[key])
    return graded(r["gold"], answer)


def verify(q, answer):
    """A1 验证器（冻结）：题面复算 + 数值复现；无法解析时放行"""
    try:
        vals, _, checks = recompute(q)
    except Exception:
        return True, "unparseable"
    got = nums(answer)
    for gv in vals:
        if not any(abs(v - gv) <= TOL for v in got):
            return False, f"missing:{gv:g}"
    if not all(checks):
        return False, "self_inconsistent"
    return True, "ok"


# ---------------------------------------------------------------- Java
def build_java():
    BUILD.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(BUILD), "-sourcepath", str(AI_SRC),
                        str(PROBE_JAVA), str(EVAL_JAVA)], capture_output=True, text=True,
                       encoding="utf-8")
    if p.returncode != 0:
        sys.stderr.write(p.stdout + p.stderr)
        raise SystemExit("javac 失败")


def probe_must(tsv, col):
    out = subprocess.run(["java", "-cp", str(BUILD), "CalcProbeMain", str(tsv), str(col)],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        sys.stderr.write(out.stdout + out.stderr)
        raise SystemExit("CalcProbeMain 失败")
    res = {}
    for line in out.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 2:
            res[p[0]] = p[1] == "1"
    return res


def route_tiers(tsv):
    out = subprocess.run(["java", "-cp", str(BUILD), "RouteEvalMain", str(tsv), "0.5",
                          "glm-4-flash", "glm-5.3-flash"], capture_output=True, text=True,
                         encoding="utf-8")
    if out.returncode != 0:
        sys.stderr.write(out.stdout + out.stderr)
        raise SystemExit("RouteEvalMain 失败")
    res = {}
    for line in out.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 5:
            res[p[0]] = {"tier": p[1], "score": float(p[2]), "signals": p[4]}
    return res


# ---------------------------------------------------------------- 数据
def read_holdout():
    cols = ("id", "slice", "trap", "template", "device", "question", "context", "gold",
            "gold_type", "history_turns", "needs_tool")
    rows = []
    for line in HOLDOUT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = dict(zip(cols, line.split("\t")))
            r["history_turns"] = int(r["history_turns"])
            rows.append(r)
    return rows


def read_dev():
    base = []
    for line in BASE_TSV.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = line.split("\t")
        base.append({"id": p[0], "question": p[3], "context": p[4], "gold": p[5],
                     "slice": p[8] if len(p) > 8 else "fact", "source": "base"})
    fix = []
    for line in FIX_TSV.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = line.split("\t")
        fix.append({"id": p[0], "question": p[4], "context": p[5], "gold": p[6],
                    "slice": p[2], "source": "fix"})
    return base + fix


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    key = KEY_FILE.read_text().strip()
    build_java()

    if args.probe:
        d = post(API, key, {"model": "glm-4-flash", "messages": [{"role": "user", "content": "回复OK"}],
                            "max_tokens": 4, "temperature": 0.0})
        print("chat ok:", d["choices"][0]["message"]["content"][:20])
        print("calc ok:", probe_must(HOLDOUT, 5).get("H001"))
        return

    prices = load_prices()
    rows = read_holdout()
    must = probe_must(HOLDOUT, 5)
    tiers = route_tiers(HOLDOUT_JAVA)
    for r in rows:
        r["must"] = must.get(r["id"], False)
        r["new_tier"] = tiers.get(r["id"], {}).get("tier", "simple")

    # ---------- 模型答案（缓存）
    RAW.mkdir(parents=True, exist_ok=True)
    cache = {}
    if CACHE.exists():
        cache = {x["id"]: x for x in json.loads(CACHE.read_text(encoding="utf-8"))}
    for i in list(cache):
        if i in {r["id"] for r in rows} and cache[i].get("qh") != qhash(
                next(r for r in rows if r["id"] == i)):
            cache.pop(i, None)
    todo = [r for r in rows if not (cache.get(r["id"], {}).get("small")
                                    and cache.get(r["id"], {}).get("large"))]
    print(f"[holdout] model calls: {len(todo) * 2}", flush=True)
    lock = threading.Lock()

    def work(r):
        large = call_model(key, "glm-5.3-flash", r["question"], r["context"])
        small = call_model(key, "glm-4-flash", r["question"], r["context"])
        rec = {"id": r["id"], "qh": qhash(r), "small": small, "large": large}
        with lock:
            cache[r["id"]] = rec
            CACHE.write_text(json.dumps(list(cache.values()), ensure_ascii=False, indent=2),
                             encoding="utf-8")
        return rec

    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(work, r) for r in todo]
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    f.result()
                except Exception as e:
                    print("[holdout] call failed:", repr(e), flush=True)
                if i % 20 == 0:
                    print(f"[holdout] answers {i}/{len(todo)}", flush=True)

    # ---------- 决策
    for r in rows:
        c = cache[r["id"]]
        r["small"] = c["small"]["answer"]
        r["large"] = c["large"]["answer"]
        r["c_small"] = cost_of(c["small"], prices)
        r["c_large"] = cost_of(c["large"], prices)
        r["l_small"] = c["small"]["latency_s"]
        r["l_large"] = c["large"]["latency_s"]
        r["small_ok"] = calc_ok(r["gold"], r["small"])
        r["large_ok"] = calc_ok(r["gold"], r["large"])

    def mk(r, answer, use_large, escalated=False):
        return {"answer": answer, "cost": r["c_large"] if use_large else r["c_small"],
                "latency": r["l_large"] if use_large else r["l_small"],
                "escalated": escalated,
                "correct": r["large_ok"] if use_large else r["small_ok"]}

    def decide_a1(r):
        if not r["must"]:
            return mk(r, r["small"], False)
        ok, _ = verify(r["question"], r["small"])
        if ok:
            return mk(r, r["small"], False)
        return mk(r, r["large"], True, escalated=True)

    def decide_router(r):
        if r["new_tier"] == "complex":
            return mk(r, r["large"], True)
        return mk(r, r["small"], False)

    def decide(name):
        return decide_a1 if name == "A1_v1" else decide_router

    candidates = {"A1_v1": decide("A1_v1"), "router_v1": decide("router_v1")}

    def summary(outs, rows_):
        n = len(rows_)
        correct = sum(1 for r in rows_ if outs[r["id"]]["correct"])
        calc = [r for r in rows_ if r["slice"] == "calc"]
        simple = [r for r in rows_ if r["slice"] == "simple"]
        esc = [r for r in rows_ if outs[r["id"]]["escalated"]]
        small_wrong = [r for r in rows_ if not r["small_ok"]]
        calc_wrong = [r for r in calc if not r["small_ok"]]
        missed = [r for r in calc_wrong if not outs[r["id"]]["escalated"]]
        by_trap = {}
        for t in sorted({r["trap"] for r in rows_}):
            sub = [r for r in rows_ if r["trap"] == t]
            by_trap[t] = {
                "n": len(sub),
                "must_rate": round(100.0 * sum(1 for r in sub if r["must"]) / len(sub), 2),
                "escalation_rate": round(100.0 * sum(1 for r in sub if outs[r["id"]]["escalated"])
                                         / len(sub), 2),
                "acc": round(100.0 * sum(1 for r in sub if outs[r["id"]]["correct"]) / len(sub), 2),
            }
        return {
            "n": n,
            "acc": round(100.0 * correct / n, 2),
            "correct": correct,
            "cost_cny": round(sum(o["cost"] for o in outs.values()), 4),
            "avg_latency_s": round(sum(o["latency"] for o in outs.values()) / n, 2),
            "escalation_rate_calc": round(100.0 * sum(1 for r in calc
                                                      if outs[r["id"]]["escalated"]) / len(calc), 2),
            "miss_escalation_rate": round(100.0 * len(missed) / max(len(calc_wrong), 1), 2),
            "calc_wrong": len(calc_wrong),
            "false_escalation_rate": round(100.0 * sum(1 for r in simple
                                                       if outs[r["id"]]["escalated"])
                                           / max(len(simple), 1), 2),
            "post_escalation_acc": round(100.0 * sum(1 for r in esc if outs[r["id"]]["correct"])
                                         / max(len(esc), 1), 2),
            "escalated": len(esc),
            "small_wrong": len(small_wrong),
            "by_trap": by_trap,
            "failures": [{"id": r["id"], "trap": r["trap"], "question": r["question"],
                          "gold": r["gold"], "answer": outs[r["id"]]["answer"][:200],
                          "escalated": outs[r["id"]]["escalated"]}
                         for r in rows_ if not outs[r["id"]]["correct"]],
        }

    report = {"meta": {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "rule": "A1-v1", "tolerance": TOL,
                       "prices": prices, "n_holdout": len(rows)},
              "holdout": {}, "dev": {}}
    detail = []
    for name, fn in candidates.items():
        outs = {r["id"]: fn(r) for r in rows}
        report["holdout"][name] = summary(outs, rows)
        for r in rows:
            o = outs[r["id"]]
            detail.append({"set": "holdout", "candidate": name, "id": r["id"], "slice": r["slice"],
                           "trap": r["trap"], "question": r["question"], "gold": r["gold"],
                           "answer": o["answer"].replace("\n", " ")[:300], "must": r["must"],
                           "escalated": o["escalated"], "correct": o["correct"],
                           "cost": round(o["cost"], 8)})

    # ---------- 开发集复算（A1-v1，复用缓存，无 API 费用）
    if BASE_CACHE.exists() and FIX_CACHE.exists():
        dev = read_dev()
        ids = {r["id"] for r in dev}
        base = {x["id"]: x for x in json.loads(BASE_CACHE.read_text(encoding="utf-8"))}
        fix = {x["id"]: x for x in json.loads(FIX_CACHE.read_text(encoding="utf-8"))}
        qtmp = BUILD / "dev_q.tsv"
        qtmp.write_text("\n".join(f"{r['id']}\t{r['question']}" for r in dev), encoding="utf-8")
        dmust = probe_must(qtmp, 1)
        for r in dev:
            src = base.get(r["id"]) if r["source"] == "base" else fix.get(r["id"])
            r["must"] = dmust.get(r["id"], False)
            if not src:
                r["missing"] = True
                continue
            s = src.get("small") or src.get("small_all")
            r["small"] = (s or {}).get("answer", "")
            r["large"] = (src.get("large") or {}).get("answer", "")
            r["small_ok"] = dev_ok(r, src, "small", r["small"])
            r["large_ok"] = dev_ok(r, src, "large", r["large"])
            r["c_small"] = (src.get("small_cost") or src.get("small_all_cost")
                            or (cost_of(s, prices) if s else 0.0))
            r["c_large"] = src.get("large_cost") or cost_of(src["large"], prices)
            r["l_small"] = (s or {}).get("latency_s", 0.0)
            r["l_large"] = (src.get("large") or {}).get("latency_s", 0.0)
            r["old_tier"] = (src.get("route") or {}).get("tier", "complex")
        dev = [r for r in dev if not r.get("missing")]
        for r in dev:
            r["trap"] = r["slice"]
            r["new_tier"] = "complex" if r.get("old_tier") == "complex" else "simple"

        def dev_a1(r):
            if r.get("old_tier") == "complex":
                return mk(r, r["large"], True)
            if not r["must"]:
                return mk(r, r["small"], False)
            ok, _ = verify(r["question"], r["small"])
            return mk(r, r["small"], False) if ok else mk(r, r["large"], True, escalated=True)

        outs = {r["id"]: dev_a1(r) for r in dev}
        report["dev"]["A1_v1"] = summary(outs, dev)
        esc_ids = sorted(r["id"] for r in dev if outs[r["id"]]["escalated"])
        report["dev"]["A1_v1"]["escalated_ids"] = esc_ids
        if OLD_JSON.exists():
            old = json.loads(OLD_JSON.read_text(encoding="utf-8"))
            old_ids = sorted(old.get("extra", {}).get("a1_escalated_ids", []))
            report["dev"]["A1_v1"]["old_escalated_ids"] = old_ids
            report["dev"]["A1_v1"]["escalation_set_identical"] = esc_ids == old_ids
        for r in dev:
            o = outs[r["id"]]
            detail.append({"set": "dev", "candidate": "A1_v1", "id": r["id"], "slice": r["slice"],
                           "trap": r["slice"], "question": r["question"], "gold": r["gold"],
                           "answer": o["answer"].replace("\n", " ")[:300], "must": r["must"],
                           "escalated": o["escalated"], "correct": o["correct"],
                           "cost": round(o["cost"], 8)})

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        w.writeheader()
        w.writerows(detail)

    brief = {k: {kk: vv for kk, vv in v.items()
                 if kk in ("acc", "cost_cny", "avg_latency_s", "escalation_rate_calc",
                           "miss_escalation_rate", "false_escalation_rate", "post_escalation_acc",
                           "escalated", "small_wrong", "escalation_set_identical")}
             for k, v in {**{"holdout_" + k: v for k, v in report["holdout"].items()},
                          **{"dev_" + k: v for k, v in report["dev"].items()}}.items()}
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    print("json ->", OUT_JSON)


if __name__ == "__main__":
    main()
