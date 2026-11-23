#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由修复离线评测：短问句藏多步计算的结构性失效。

只做离线实验，不改 Java。生产路由决策仍由 ModelRouter 编译后给出（保证基线=线上）。

评测集（400 条，均来自项目知识库口径）：
  - calc        100 条：短问句、多步算术（30 条沿用 route_set，70 条由 gen_calc_set.py 新增）
  - calc_single  30 条：单步减法（简单档），用于测误升级
  - fact        150 条：单条目事实（简单档）
  - templated   120 条：长问句联合诊断（复杂档，回归项）

候选：
  baseline     生产规则路由
  A1           后置级联：小模型先答 → 题面复算验证 → 不符升级
  A2           后置级联：小模型先答 → 小模型结构化自评 → FAIL 升级
  A3           A1 ∪ A2
  B            工具优先：识别多步算术后代码执行，不经模型
  C_*          前置分类器：手工特征 / embedding / 两者拼接 + 逻辑回归（纯 Python）

输出：
  docs/paper/ai应用层/路由修复评测.json
  docs/paper/ai应用层/raw/route_fix_rows.json    新题逐条答案缓存
  docs/paper/ai应用层/raw/route_fix_selfcheck.json
  docs/paper/ai应用层/raw/route_fix_emb.json
  docs/paper/ai应用层/raw/route_fix_detail.csv

用法（仓库根目录）：
  python3 scripts/ai_layer/route_fix_eval.py --probe    # 只测 key/embedding，近零费用
  python3 scripts/ai_layer/route_fix_eval.py            # 全量
"""
import argparse
import csv
import hashlib
import json
import math
import os
import random
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
from verify_calc_gold import recompute  # noqa: E402  独立解析器（只读题面）

BASE_TSV = HERE / "data" / "route_set.tsv"
FIX_TSV = HERE / "data" / "route_fix_set.tsv"
FIX_JAVA = HERE / "data" / "route_fix_java.tsv"
OUT_DIR = ROOT / "docs" / "paper" / "ai应用层"
RAW_DIR = OUT_DIR / "raw"
BASE_CACHE = RAW_DIR / "routing_rows.json"
NEW_CACHE = RAW_DIR / "route_fix_rows.json"
SELF_CACHE = RAW_DIR / "route_fix_selfcheck.json"
EMB_CACHE = RAW_DIR / "route_fix_emb.json"
OUT_JSON = OUT_DIR / "路由修复评测.json"
OUT_CSV = RAW_DIR / "route_fix_detail.csv"
BUILD = ROOT / ".eval_out" / "route"
AI_SRC = ROOT / "ai-tims-parent" / "ticket-ai" / "src" / "main" / "java"
EVAL_JAVA = HERE / "java" / "RouteEvalMain.java"
YML = ROOT / "ai-tims-parent" / "ticket-ai" / "src" / "main" / "resources" / "application.yml"

API = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
EMB_API = "https://open.bigmodel.cn/api/paas/v4/embeddings"
KEY_FILE = Path(os.environ.get("LLM_API_KEY_FILE", "/home/dev/secrets/zhipu_api_key"))
SYSTEM_PROMPT = ("你是 AI-TIMS 工业设备运维助手。只依据给定参考资料回答；先给结论，再给关键依据；"
                 "资料不足时明确说明。回答控制在 150 字以内。")
SELFCHECK_PROMPT = ("你是答案复核员。只检查两件事：答案是否回答了题目要求的全部数量；答案里的数字是否自相矛盾。"
                    "不要重新解题，不要解释。只输出一行：VERDICT=PASS 或 VERDICT=FAIL。")
MAX_TOKENS = 8192
WORKERS = 6
EMB_DIM = 256


# ---------------------------------------------------------------- 基础工具
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
                    "reasoning_tokens": int((u.get("completion_tokens_details") or {})
                                            .get("reasoning_tokens") or 0),
                    "answer": (msg.get("content") or "").strip()}
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def selfcheck(key, row, answer, retries=3):
    body = {"model": "glm-4-flash",
            "messages": [{"role": "system", "content": SELFCHECK_PROMPT},
                         {"role": "user", "content": f"题目：{row['question']}\n\n待复核答案：{answer}"}],
            "max_tokens": 24, "temperature": 0.0}
    last = None
    for i in range(retries):
        try:
            t0 = time.time()
            d = post(API, key, body)
            u = d.get("usage") or {}
            txt = (d["choices"][0]["message"].get("content") or "").upper()
            return {"verdict": "FAIL" if "FAIL" in txt else ("PASS" if "PASS" in txt else "UNKNOWN"),
                    "raw": txt.strip()[:60],
                    "latency_s": round(time.time() - t0, 2),
                    "prompt_tokens": int(u.get("prompt_tokens") or 0),
                    "completion_tokens": int(u.get("completion_tokens") or 0)}
        except Exception as e:
            last = e
            time.sleep(1.0 * (i + 1))
    raise last


def embed(key, texts, retries=3):
    body = {"model": "embedding-3", "input": texts, "dimensions": EMB_DIM}
    last = None
    for i in range(retries):
        try:
            d = post(EMB_API, key, body, timeout=120)
            return [x["embedding"] for x in d["data"]], int((d.get("usage") or {}).get("total_tokens") or 0)
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def cost_of(call, prices):
    pin, pout = prices.get(call["model"], (0.0008, 0.0028))
    return call["prompt_tokens"] / 1000.0 * pin + call["completion_tokens"] / 1000.0 * pout


# ---------------------------------------------------------------- 判分
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def norm(s):
    s = (s or "").strip().lower()
    s = s.replace("～", "-").replace("~", "-").replace("—", "-").replace("–", "-").replace("－", "-")
    s = s.replace("．", ".").replace(" ", "")
    s = s.replace("毫秒", "ms").replace("分钟", "min").replace("秒", "s").replace("％", "%")
    return s


def qhash(row):
    return hashlib.md5((row["question"] + "\x00" + row["context"]).encode()).hexdigest()[:12]


def graded(gold, answer):
    if not gold:
        return False
    a = norm(answer)
    return all(norm(g) in a for g in gold.split("|") if g)


def calc_ok(gold, answer):
    if not gold:
        return False
    got = [float(x) for x in NUM_RE.findall((answer or "").replace(",", ""))]
    for g in gold.split("|"):
        if not g:
            continue
        gv = float(g)
        if not any(abs(v - gv) <= 0.06 for v in got):
            return False
    return True


# ---------------------------------------------------------------- 数据
def read_base():
    rows = []
    for line in BASE_TSV.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = line.split("\t")
        rows.append({"id": r[0], "kind": r[1], "device": r[2], "question": r[3], "context": r[4],
                     "gold": r[5], "history_turns": int(r[6]), "needs_tool": r[7] == "1",
                     "subkind": r[8] if len(r) > 8 else "", "source": "base", "template": ""})
    return rows


def read_fix():
    rows = []
    for line in FIX_TSV.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = line.split("\t")
        rows.append({"id": r[0], "kind": r[1], "subkind": r[2], "device": r[3], "question": r[4],
                     "context": r[5], "gold": r[6], "history_turns": int(r[9]),
                     "needs_tool": r[10] == "1", "source": "fix", "template": r[8]})
    return rows


def all_rows():
    rows = read_base() + read_fix()
    for r in rows:
        r["slice"] = {"fact": "fact", "templated": "templated", "calc": "calc",
                      "calc_single": "calc_single"}[r["subkind"]]
    return rows


def route_new_rows(threshold=0.5, simple_model="glm-4-flash", complex_model="glm-5.3-flash"):
    BUILD.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(BUILD), "-sourcepath", str(AI_SRC),
                        str(EVAL_JAVA)], capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        sys.stderr.write(p.stdout + p.stderr)
        raise SystemExit("javac 失败")
    out = subprocess.run(["java", "-cp", str(BUILD), "RouteEvalMain", str(FIX_JAVA), str(threshold),
                          simple_model, complex_model], capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        sys.stderr.write(out.stdout + out.stderr)
        raise SystemExit("RouteEvalMain 失败")
    res = {}
    for line in out.stdout.splitlines():
        p2 = line.split("\t")
        if len(p2) < 5:
            continue
        res[p2[0]] = {"tier": p2[1], "score": float(p2[2]), "model": p2[3], "signals": p2[4]}
    return res


# ---------------------------------------------------------------- 候选实现
def arithmetic_kind(q, include_single=False):
    """只读题面判断是否算术题；解析失败返回 None"""
    cues = ("几次", "占比", "百分点", "平均")
    if include_single:
        cues = cues + ("相差",)
    if not any(c in q for c in cues):
        return None
    try:
        vals, tmpl, checks = recompute(q)
        return {"values": vals, "template": tmpl, "checks": checks}
    except Exception:
        return None


def verify_small_answer(q, answer):
    """A1：题面复算 + 数值复现检查；返回 (通过, 说明)"""
    kind = arithmetic_kind(q, include_single=True)
    if not kind:
        return True, "no_arithmetic_pattern"
    got = [float(x) for x in NUM_RE.findall((answer or "").replace(",", ""))]
    for gv in kind["values"]:
        if not any(abs(v - gv) <= 0.06 for v in got):
            return False, f"missing:{gv:g}"
    if not all(kind["checks"]):
        return False, "self_inconsistent"
    return True, "ok"


def tool_answer(q):
    """B：代码直接算答案，不经模型"""
    kind = arithmetic_kind(q)
    if not kind:
        return None
    v, t = kind["values"], kind["template"]
    if t == "T1":
        return f"下降 {v[0]:.1f} 个百分点，现测值是初始值的 {v[1]:.1f}%。"
    if t == "T2":
        return f"超标 {v[0]:g} 次，超标占比 {v[1]:.1f}%。"
    if t == "T3":
        return f"合格 {v[0]:g} 次，合格占比 {v[1]:.1f}%。"
    if t == "T4":
        return f"平均值 {v[0]:.1f}，超过上限 {v[1]:g} 次。"
    if t == "T5":
        return f"平均 {v[0]:.1f} ms，超出上限 {v[1]:g} 次。"
    if t == "T6":
        return f"与上限相差 {v[0]:.2f}。"
    return None


# ---- C：手工特征
UNITS = re.compile(r"ms|s|℃|%|mm|μm|MPa|kPa|W|L/min|pcs|倍|次|丝")
COMPARE = re.compile(r"超过|不超过|大于|小于|低于|高于|上限|下限|范围|区间|合格|超标")
AGG = re.compile(r"几次|多少|占比|百分之|百分点|平均|合计|共|折算|保留")
NUMTOK = re.compile(r"\d+(?:\.\d+)?")


def feats(r):
    q = r["question"]
    n = max(len(q), 1)
    nums = NUMTOK.findall(q)
    digits = sum(ch.isdigit() for ch in q)
    unit_hits = UNITS.findall(q)
    return [
        len(q) / 100.0,
        len(nums),
        len(nums) * 10.0 / n,
        digits / n,
        1.0 if unit_hits else 0.0,
        len(unit_hits),
        1.0 if COMPARE.search(q) else 0.0,
        len(COMPARE.findall(q)),
        1.0 if AGG.search(q) else 0.0,
        len(AGG.findall(q)),
        1.0 if re.search(r"\d\s*-\s*\d", q) else 0.0,
        len([x for x in q.split("、") if NUMTOK.search(x)]),
        float(q.count("？") + q.count("?")),
        len(re.findall(r"为什么|原因|根因|分析|判断|排查|定位", q)),
        len(re.findall(r"并且|以及|同时|分别|对比|然后|如果", q)),
        1.0 if re.search(r"是多少|是什么|规格|标准|状态|是否", q) else 0.0,
        1.0 if re.search(r"这批|本次|初始|现测|测得|测量", q) else 0.0,
        1.0 if re.search(r"保留.位", q) else 0.0,
        1.0 if "%" in q or "％" in q else 0.0,
        1.0 if re.search(r"ms|毫秒", q) else 0.0,
        math.log1p(max([float(x) for x in nums], default=0.0)),
        1.0 if re.search(r"要求|规格|标准", q) else 0.0,
        1.0 if re.search(r"几次|有多少|多少个", q) else 0.0,
        1.0 if re.search(r"平均|总计|合计|占比", q) else 0.0,
        len(q) / 25.0,
        len(re.findall(r"[，。；：]", q)),
    ]


def l2norm(v):
    s = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / s for x in v]


def sigmoid(z):
    if z > 40:
        return 1.0
    if z < -40:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def train_lr(X, y, epochs=120, lr=0.05, l2=1e-4):
    d = len(X[0])
    w = [0.0] * d
    pos = sum(y) / len(y)
    b = math.log(pos / (1 - pos))
    idx = list(range(len(X)))
    rnd = random.Random(7)
    for _ in range(epochs):
        rnd.shuffle(idx)
        for i in idx:
            x = X[i]
            g = sigmoid(b + sum(a * c for a, c in zip(w, x))) - y[i]
            w = [wj - lr * (g * xj + l2 * wj) for wj, xj in zip(w, x)]
            b -= lr * g
    return w, b


def predict(w, b, X):
    return [sigmoid(b + sum(a * c for a, c in zip(w, x))) for x in X]


def std_fit(X):
    d = len(X[0])
    n = len(X)
    mu = [sum(x[j] for x in X) / n for j in range(d)]
    sd = [math.sqrt(sum((x[j] - mu[j]) ** 2 for x in X) / n) or 1.0 for j in range(d)]
    return mu, sd


def std_apply(X, mu, sd):
    return [[(x[j] - mu[j]) / sd[j] for j in range(len(x))] for x in X]


def auc(y, p):
    pairs = sorted(zip(p, y))
    pos = sum(y)
    neg = len(y) - pos
    if not pos or not neg:
        return None
    rank_sum = 0.0
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1
        rank_sum += avg_rank * sum(yy for _, yy in pairs[i:j + 1])
        i = j + 1
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-calls", type=int, default=1200)
    args = ap.parse_args()

    key = KEY_FILE.read_text().strip()

    if args.probe:
        d = post(API, key, {"model": "glm-4-flash", "messages": [{"role": "user", "content": "回复OK"}],
                            "max_tokens": 4, "temperature": 0.0})
        print("chat ok:", d["choices"][0]["message"]["content"][:20])
        vecs, tk = embed(key, ["短问句藏多步计算", "设备规格是多少"])
        print("embedding ok:", len(vecs), "x", len(vecs[0]), "tokens", tk)
        return

    prices = load_prices()
    rows = all_rows()
    if args.limit:
        rows = rows[:args.limit]
    by_id = {r["id"]: r for r in rows}
    base_cache = {x["id"]: x for x in json.loads(BASE_CACHE.read_text(encoding="utf-8"))}
    routes = route_new_rows()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    new_cache = {}
    if NEW_CACHE.exists():
        new_cache = {x["id"]: x for x in json.loads(NEW_CACHE.read_text(encoding="utf-8"))}
    self_cache = {}
    if SELF_CACHE.exists():
        self_cache = json.loads(SELF_CACHE.read_text(encoding="utf-8"))
    # 题面变了就作废旧答案（避免复用错缓存）
    stale = [i for i, rec in new_cache.items() if i in by_id and rec.get("qh") != qhash(by_id[i])]
    for i in stale:
        new_cache.pop(i, None)
        self_cache.pop(i, None)
    if stale:
        print(f"[fix] drop stale cache {len(stale)}: {stale[:10]}", flush=True)
    stale_ids = set(stale)
    lock = threading.Lock()
    calls_made = [0]

    def persist(path, obj):
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 1. 补齐新题的小/大模型答案
    todo = []
    for r in rows:
        if r["source"] == "base":
            rec = base_cache.get(r["id"])
            if not rec or not rec.get("large"):
                raise SystemExit("基线缓存缺答案：" + r["id"])
            continue
        rec = new_cache.get(r["id"]) or {}
        if not (rec.get("large") and rec.get("small")):
            todo.append(r)
    print(f"[fix] new rows to call: {len(todo)}", flush=True)

    def work_new(r):
        rt = routes.get(r["id"], {"tier": "complex", "score": 1.0, "model": "glm-5.3-flash", "signals": ""})
        large = call_model(key, "glm-5.3-flash", r["question"], r["context"])
        small = call_model(key, "glm-4-flash", r["question"], r["context"])
        rec = {"id": r["id"], "qh": qhash(r), "route": rt, "large": large, "small": small}
        with lock:
            calls_made[0] += 2
            new_cache[r["id"]] = rec
            persist(NEW_CACHE, list(new_cache.values()))
        return rec

    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(work_new, r) for r in todo]
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    f.result()
                except Exception as e:
                    print("[fix] call failed:", repr(e), flush=True)
                if i % 20 == 0:
                    print(f"[fix] answers {i}/{len(todo)}", flush=True)

    # ---------- 2. 补齐小模型自评（只对简单档需要的题）
    need_self = [r for r in rows if (r["source"] == "fix" or
                                     (base_cache[r["id"]].get("route") or {}).get("tier") == "simple")]
    missing_self = []
    for r in need_self:
        small = (new_cache.get(r["id"]) or {}).get("small") if r["source"] == "fix" else base_cache[r["id"]].get("small")
        if not small:
            continue
        if r["id"] not in self_cache:
            missing_self.append((r, small["answer"]))
    print(f"[fix] selfcheck to call: {len(missing_self)}", flush=True)

    def work_self(item):
        r, ans = item
        res = selfcheck(key, r, ans)
        with lock:
            calls_made[0] += 1
            self_cache[r["id"]] = res
            persist(SELF_CACHE, self_cache)
        return res

    if missing_self:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(work_self, it) for it in missing_self]
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    f.result()
                except Exception as e:
                    print("[fix] selfcheck failed:", repr(e), flush=True)
                if i % 50 == 0:
                    print(f"[fix] selfcheck {i}/{len(missing_self)}", flush=True)

    # ---------- 3. embedding
    emb = {}
    emb_tokens = 0
    if EMB_CACHE.exists():
        obj = json.loads(EMB_CACHE.read_text(encoding="utf-8"))
        emb = {k: v for k, v in obj.get("vectors", {}).items()}
        emb_tokens = int(obj.get("tokens") or 0)
    need_emb = [r for r in rows if r["id"] not in emb or r["id"] in stale_ids]
    print(f"[fix] embedding to call: {len(need_emb)}", flush=True)
    for i in range(0, len(need_emb), 32):
        chunk = need_emb[i:i + 32]
        vecs, tk = embed(key, [c["question"] for c in chunk])
        emb_tokens += tk
        for c, v in zip(chunk, vecs):
            emb[c["id"]] = v
        persist(EMB_CACHE, {"dim": EMB_DIM, "tokens": emb_tokens, "vectors": emb})
        print(f"[fix] embedding {min(i + 32, len(need_emb))}/{len(need_emb)}", flush=True)

    # ---------- 4. 组装逐条上下文
    ctxs = {}
    for r in rows:
        if r["source"] == "base":
            rec = base_cache[r["id"]]
            ctxs[r["id"]] = {"route": rec.get("route") or {"tier": "complex", "score": 1.0},
                             "large": rec["large"], "small": rec.get("small") or rec.get("small_all"),
                             "small_all": rec.get("small_all"), "judge": rec.get("judge") or {},
                             "cost_large": rec.get("large_cost", 0.0),
                             "cost_small": rec.get("small_cost", 0.0),
                             "cost_small_all": rec.get("small_all_cost", 0.0)}
        else:
            rec = new_cache[r["id"]]
            ctxs[r["id"]] = {"route": rec["route"], "large": rec["large"], "small": rec["small"],
                             "small_all": rec["small"], "judge": {},
                             "cost_large": cost_of(rec["large"], prices),
                             "cost_small": cost_of(rec["small"], prices),
                             "cost_small_all": cost_of(rec["small"], prices)}

    # ---------- 5. 判分
    def ok_row(r, call_key, answer):
        if r["slice"] in ("calc", "calc_single"):
            return calc_ok(r["gold"], answer)
        if r["slice"] == "templated":
            j = ctxs[r["id"]]["judge"]
            if call_key in j:
                return bool(j[call_key])
            return graded(r["gold"], answer)
        return graded(r["gold"], answer)

    def mk(r, calls, answer, call_key, extra_lat=0.0, escalated=False, tool=False):
        return {"answer": answer, "calls": calls, "call_key": call_key,
                "cost": sum(costs[(r["id"], c)] for c in calls),
                "latency": sum(lats[(r["id"], c)] for c in calls) + extra_lat,
                "escalated": escalated, "tool": tool, "correct": ok_row(r, call_key, answer)}

    # 每个候选按行决策
    def decide_base(r):
        c = ctxs[r["id"]]
        if c["route"]["tier"] == "simple":
            return mk(r, ["small"], c["small"]["answer"], "small")
        return mk(r, ["large"], c["large"]["answer"], "large")

    def decide_A1(r):
        c = ctxs[r["id"]]
        if c["route"]["tier"] != "simple":
            return mk(r, ["large"], c["large"]["answer"], "large")
        ok, _ = verify_small_answer(r["question"], c["small"]["answer"])
        if ok:
            return mk(r, ["small"], c["small"]["answer"], "small")
        return mk(r, ["small", "large"], c["large"]["answer"], "large", escalated=True)

    def decide_A2(r):
        c = ctxs[r["id"]]
        if c["route"]["tier"] != "simple":
            return mk(r, ["large"], c["large"]["answer"], "large")
        sc = self_cache.get(r["id"]) or {}
        extra = sc.get("latency_s", 0.0)
        if sc.get("verdict") == "FAIL":
            return mk(r, ["small", "large"], c["large"]["answer"], "large", extra_lat=extra, escalated=True)
        return mk(r, ["small"], c["small"]["answer"], "small", extra_lat=extra)

    def decide_A3(r):
        c = ctxs[r["id"]]
        if c["route"]["tier"] != "simple":
            return mk(r, ["large"], c["large"]["answer"], "large")
        ok, _ = verify_small_answer(r["question"], c["small"]["answer"])
        sc = self_cache.get(r["id"]) or {}
        extra = sc.get("latency_s", 0.0)
        if ok and sc.get("verdict") != "FAIL":
            return mk(r, ["small"], c["small"]["answer"], "small", extra_lat=extra)
        return mk(r, ["small", "large"], c["large"]["answer"], "large", extra_lat=extra, escalated=True)

    def decide_B(r):
        c = ctxs[r["id"]]
        if c["route"]["tier"] == "simple":
            ans = tool_answer(r["question"])
            if ans is not None:
                return {"answer": ans, "calls": [], "call_key": "tool", "cost": 0.0,
                        "latency": 0.000023, "escalated": False, "tool": True,
                        "correct": ok_row(r, "small", ans)}
            return mk(r, ["small"], c["small"]["answer"], "small")
        return mk(r, ["large"], c["large"]["answer"], "large")

    # 成本/延迟查表（按实际调用的那次）
    costs = {}
    lats = {}
    for r in rows:
        c = ctxs[r["id"]]
        costs[(r["id"], "large")] = c["cost_large"]
        costs[(r["id"], "small")] = c["cost_small"]
        costs[(r["id"], "small_all")] = c["cost_small_all"]
        lats[(r["id"], "large")] = c["large"]["latency_s"]
        lats[(r["id"], "small")] = c["small"]["latency_s"]
        lats[(r["id"], "small_all")] = c["small_all"]["latency_s"]

    # ---------- 6. 前置分类器
    labels = {r["id"]: (1 if r["slice"] in ("calc", "templated") else 0) for r in rows}
    y = [labels[r["id"]] for r in rows]
    Xf = [feats(r) for r in rows]
    Xe = [l2norm(emb[r["id"]]) for r in rows]
    mu, sd = std_fit(Xf)
    Xfs = std_apply(Xf, mu, sd)
    Xboth = [a + b for a, b in zip(Xfs, Xe)]

    # 分层 5 折：按 slice 轮转
    folds = [[] for _ in range(5)]
    for sl in ("calc", "calc_single", "fact", "templated"):
        idxs = [i for i, r in enumerate(rows) if r["slice"] == sl]
        rnd = random.Random(11)
        rnd.shuffle(idxs)
        for k, i in enumerate(idxs):
            folds[k % 5].append(i)

    def cv(X):
        oof = [0.0] * len(rows)
        for k in range(5):
            tr = [i for f in range(5) if f != k for i in folds[f]]
            te = folds[k]
            w, b = train_lr([X[i] for i in tr], [y[i] for i in tr])
            p = predict(w, b, [X[i] for i in te])
            for i, pv in zip(te, p):
                oof[i] = pv
        return oof

    print("[fix] training C variants (pure-python LR)...", flush=True)
    t0 = time.time()
    oof_f = cv(Xfs)
    oof_e = cv(Xe)
    oof_b = cv(Xboth)
    t_train = time.time() - t0
    # 单条推理耗时（用于延迟口径）
    t1 = time.time()
    _ = predict([0.0] * len(Xboth[0]), 0.0, Xboth)
    infer_ms = (time.time() - t1) * 1000.0 / len(Xboth)  # 单条推理耗时

    def choose_threshold(oof):
        best = None
        detail = []
        for th in [x / 100.0 for x in range(5, 96, 1)]:
            m = metrics_from_probs(oof, th, rows)
            detail.append({"threshold": th, **m})
            if m["simple_fp_rate"] > 0.05:
                continue
            key2 = (m["calc_recall"] + m["templated_recall"]) / 2.0
            if best is None or key2 > best[0]:
                best = (key2, th, m)
        if best is None:
            th = 0.5
            return th, metrics_from_probs(oof, th, rows), detail
        return best[1], best[2], detail

    def metrics_from_probs(probs, th, rows_):
        calc = [i for i, r in enumerate(rows_) if r["slice"] == "calc"]
        single = [i for i, r in enumerate(rows_) if r["slice"] == "calc_single"]
        fact = [i for i, r in enumerate(rows_) if r["slice"] == "fact"]
        tmpl = [i for i, r in enumerate(rows_) if r["slice"] == "templated"]
        return {"calc_recall": sum(1 for i in calc if probs[i] >= th) / max(len(calc), 1),
                "templated_recall": sum(1 for i in tmpl if probs[i] >= th) / max(len(tmpl), 1),
                "simple_fp_rate": sum(1 for i in single + fact if probs[i] >= th) /
                                  max(len(single) + len(fact), 1),
                "calc_single_fp": sum(1 for i in single if probs[i] >= th) / max(len(single), 1),
                "fact_fp": sum(1 for i in fact if probs[i] >= th) / max(len(fact), 1)}

    variants = {}
    for name, oof in (("C_feat", oof_f), ("C_emb", oof_e), ("C_both", oof_b)):
        th, m, detail = choose_threshold(oof)
        variants[name] = {"threshold": th, "pick": m, "sweep": detail,
                          "auc": round(auc(y, oof) or 0.0, 4), "probs": oof}

    def decide_C(name):
        probs = variants[name]["probs"]
        th = variants[name]["threshold"]
        idx = {r["id"]: i for i, r in enumerate(rows)}

        def fn(r):
            p = probs[idx[r["id"]]]
            c = ctxs[r["id"]]
            if p >= th:
                return mk(r, ["large"], c["large"]["answer"], "large", extra_lat=infer_ms / 1000.0)
            return mk(r, ["small"], c["small"]["answer"], "small", extra_lat=infer_ms / 1000.0)
        return fn

    candidates = {
        "base_router": decide_base,
        "all_large": lambda r: mk(r, ["large"], ctxs[r["id"]]["large"]["answer"], "large"),
        "all_small": lambda r: mk(r, ["small_all"], ctxs[r["id"]]["small_all"]["answer"], "small_all"),
        "A1_verify": decide_A1,
        "A2_selfcheck": decide_A2,
        "A3_both": decide_A3,
        "B_tool": decide_B,
        "C_feat": decide_C("C_feat"),
        "C_emb": decide_C("C_emb"),
        "C_both": decide_C("C_both"),
    }

    summary = {}
    detail_rows = []
    for name, fn in candidates.items():
        outs = {}
        for r in rows:
            cur = r
            outs[r["id"]] = fn(r)
        n = len(rows)
        by_slice = {}
        for sl in ("calc", "calc_single", "fact", "templated"):
            sub = [r for r in rows if r["slice"] == sl]
            by_slice[sl] = {"n": len(sub),
                            "acc": round(100.0 * sum(1 for r in sub if outs[r["id"]]["correct"]) / len(sub), 2)}
        simple_ids = [r["id"] for r in rows if r["slice"] in ("fact", "calc_single")]
        falses = [i for i in simple_ids if outs[i]["escalated"] or
                  (outs[i]["call_key"] == "large")]
        summary[name] = {
            "acc": round(100.0 * sum(1 for r in rows if outs[r["id"]]["correct"]) / n, 2),
            "correct": sum(1 for r in rows if outs[r["id"]]["correct"]),
            "n": n,
            "cost_cny": round(sum(o["cost"] for o in outs.values()), 4),
            "avg_latency_s": round(sum(o["latency"] for o in outs.values()) / n, 2),
            "false_escalation_rate": round(100.0 * len(falses) / len(simple_ids), 2),
            "calc_escalation_rate": round(100.0 * sum(1 for r in rows if r["slice"] == "calc"
                                                      and outs[r["id"]]["call_key"] == "large")
                                          / max(sum(1 for r in rows if r["slice"] == "calc"), 1), 2),
            "tool_used": sum(1 for o in outs.values() if o["tool"]),
            "by_slice": by_slice,
            "failures": [{"id": r["id"], "slice": r["slice"], "question": r["question"],
                          "gold": r["gold"], "answer": outs[r["id"]]["answer"][:200]}
                         for r in rows if not outs[r["id"]]["correct"]],
        }
        for r in rows:
            o = outs[r["id"]]
            detail_rows.append({"candidate": name, "id": r["id"], "slice": r["slice"],
                                "question": r["question"], "gold": r["gold"],
                                "answer": o["answer"].replace("\n", " ")[:300],
                                "call_key": o["call_key"], "cost": round(o["cost"], 8),
                                "latency": o["latency"], "correct": o["correct"],
                                "escalated": o["escalated"], "tool": o["tool"]})

    # 对照组：C 的阈值/阈值敏感度、A 的验证命中情况
    a1 = summary["A1_verify"]
    extra = {
        "a1_escalated_ids": [r["id"] for r in rows if r["slice"] == "calc"
                             and candidates["A1_verify"](r)["escalated"]],
        "a2_fail_ids": [i for i, v in self_cache.items() if v.get("verdict") == "FAIL" and i in by_id],
        "c_variants": {k: {"threshold": v["threshold"], "auc": v["auc"],
                           "formal": {kk: round(vv * 100, 2) if isinstance(vv, float) else vv
                                      for kk, vv in v["pick"].items()}} for k, v in variants.items()},
        "train_seconds": round(t_train, 1), "infer_ms_per_sample": round(infer_ms, 2),
        "embedding_tokens": emb_tokens,
    }

    # CSV 明细
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
        w.writeheader()
        w.writerows(detail_rows)

    report = {
        "meta": {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "n": len(rows), "calc": sum(1 for r in rows if r["slice"] == "calc"),
                 "prices": prices, "embedding_model": f"embedding-3(dim={EMB_DIM})",
                 "api_calls_made": calls_made[0]},
        "summary": summary,
        "extra": extra,
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in
                          ("acc", "cost_cny", "avg_latency_s", "false_escalation_rate", "by_slice")}
                      for k, v in summary.items()}, ensure_ascii=False, indent=2))
    print("json ->", OUT_JSON)


if __name__ == "__main__":
    main()
