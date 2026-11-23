#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型路由评测：300 条 query，全大模型 vs 路由（简单走 glm-4-flash、复杂走 glm-5.3-flash）。

流程：
1. javac 编译生产代码 ModelRouter，离线得到每条 query 的分流结果（可解释信号）；
2. 逐条调用模型：baseline 全走大模型；路由为 simple 的额外走小模型（复杂题复用大模型答案）；
3. 判分：
   - 简单题：答案必须包含知识库规格里的数值片段（精确、客观）；
   - 复杂题：用独立阅卷调用判断是否同时指出两个现象的原因（同义表述算对）；
   同时保留「严格关键词」口径（复杂题要求逐字出现两条条目的部件名）作为保守下界；
4. 按项目 application.yml 的 model-prices 计价；
5. 输出总体成本/准确率对照、误判样本（重点：判成简单但小模型答错）、逐条明细。

用法（仓库根目录）：
    python3 scripts/ai_layer/route_eval.py            # 全量 300 条
    python3 scripts/ai_layer/route_eval.py --dry-run  # 只跑路由器分流，免费
    python3 scripts/ai_layer/route_eval.py --limit 6  # 冒烟
"""
import argparse
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

ROOT = Path(__file__).resolve().parents[2]
AI_SRC = ROOT / "ai-tims-parent" / "ticket-ai" / "src" / "main" / "java"
EVAL_JAVA = ROOT / "scripts" / "ai_layer" / "java" / "RouteEvalMain.java"
DATA = ROOT / "scripts" / "ai_layer" / "data" / "route_set.tsv"
OUT_DIR = ROOT / "docs" / "paper" / "ai应用层"
RAW = OUT_DIR / "raw" / "routing_rows.json"
BUILD = ROOT / ".eval_out" / "route"
YML = ROOT / "ai-tims-parent" / "ticket-ai" / "src" / "main" / "resources" / "application.yml"

API = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
KEY_FILE = Path(os.environ.get("LLM_API_KEY_FILE", "/home/dev/secrets/zhipu_api_key"))
SYSTEM_PROMPT = ("你是 AI-TIMS 工业设备运维助手。只依据给定参考资料回答；先给结论，再给关键依据；"
                 "资料不足时明确说明。回答控制在 150 字以内。")
JUDGE_PROMPT = ("你是严格的阅卷员。根据题目、参考资料和待评答案判断：答案是否同时指出了两个现象各自最可能的原因"
                "或处置方向（允许同义表述、允许细节不完整）。只输出一行：VERDICT=YES 或 VERDICT=NO。")
MAX_TOKENS = 4096
WORKERS = 6


def load_prices():
    """从 application.yml 的 model-prices 读取单价（元/千 tokens）"""
    text = YML.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^\s+([\w.\-]+):\s*\{\s*input-per-1k:\s*([\d.]+),\s*output-per-1k:\s*([\d.]+)\s*\}",
                         text, re.M):
        out[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    if not out:
        raise SystemExit("未能从 application.yml 解析 model-prices")
    return out


def compile_java():
    BUILD.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(BUILD), "-sourcepath", str(AI_SRC),
                        str(EVAL_JAVA)], capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        sys.stderr.write(p.stdout + p.stderr)
        raise SystemExit("javac 失败")


def route_all(threshold, simple_model, complex_model):
    out = subprocess.run(["java", "-cp", str(BUILD), "RouteEvalMain", str(DATA), str(threshold),
                          simple_model, complex_model], capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        sys.stderr.write(out.stdout + out.stderr)
        raise SystemExit("RouteEvalMain 失败")
    res = {}
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        res[parts[0]] = {"tier": parts[1], "score": float(parts[2]),
                         "model": parts[3], "signals": parts[4]}
    return res


def norm(s):
    s = (s or "").strip().lower()
    s = s.replace("～", "-").replace("~", "-").replace("—", "-").replace("–", "-").replace("－", "-")
    s = s.replace("．", ".").replace(" ", "")
    # 单位统一：模型常把 s 写成「秒」
    s = s.replace("毫秒", "ms").replace("分钟", "min").replace("秒", "s").replace("％", "%")
    return s


def graded(gold, answer):
    if not gold:
        return False
    a = norm(answer)
    return all(norm(g) in a for g in gold.split("|") if g)


NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def calc_ok(gold, answer):
    """计算题判分：gold 为 | 分隔的数值，答案里每个数值都要出现（±0.06 容差，覆盖一位小数四舍五入）"""
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


def score(row, answer):
    """按题型选择判分口径：calc=数值容差；简单题=规格片段；其余走关键词"""
    if row.get("subkind") == "calc":
        return calc_ok(row["gold"], answer)
    return graded(row["gold"], answer)


def qhash(row):
    return hashlib.md5((row["question"] + "\x00" + row["context"]).encode()).hexdigest()[:12]


def post(key, body):
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode())


def call_model(key, model, question, context):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"参考资料：\n{context}\n\n问题：{question}"},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.3,
    }
    t0 = time.time()
    d = post(key, body)
    u = d.get("usage") or {}
    msg = d["choices"][0]["message"]
    return {
        "model": model,
        "latency_s": round(time.time() - t0, 1),
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "reasoning_tokens": int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
        "answer": (msg.get("content") or "").strip(),
    }


def judge_answer(key, row, answer):
    body = {
        "model": "glm-4-flash",
        "messages": [
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": f"题目：{row['question']}\n\n参考资料：\n{row['context']}\n\n待评答案：{answer}"},
        ],
        "max_tokens": 32,
        "temperature": 0.0,
    }
    d = post(key, body)
    u = d.get("usage") or {}
    txt = (d["choices"][0]["message"].get("content") or "").upper()
    return "YES" in txt, {"model": "glm-4-flash",
                          "prompt_tokens": int(u.get("prompt_tokens") or 0),
                          "completion_tokens": int(u.get("completion_tokens") or 0)}


def tok_sum(calls):
    return {"prompt": sum(c.get("prompt_tokens", 0) for c in calls),
            "completion": sum(c.get("completion_tokens", 0) for c in calls),
            "reasoning": sum(c.get("reasoning_tokens", 0) for c in calls),
            "total": sum(c.get("prompt_tokens", 0) + c.get("completion_tokens", 0) for c in calls)}


def cost_of(call, prices):
    pin, pout = prices.get(call["model"], (0.0008, 0.0028))
    return call["prompt_tokens"] / 1000.0 * pin + call["completion_tokens"] / 1000.0 * pout


def read_rows(limit=0):
    rows = []
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = line.split("\t")
        rows.append({"id": r[0], "kind": r[1], "device": r[2], "question": r[3],
                     "context": r[4], "gold": r[5], "history_turns": int(r[6]),
                     "needs_tool": r[7] == "1", "subkind": r[8] if len(r) > 8 else ""})
    return rows[:limit] if limit else rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--simple-model", default="glm-4-flash")
    ap.add_argument("--complex-model", default="glm-5.3-flash")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="只跑路由器分流，不调用模型（免费）")
    ap.add_argument("--no-judge", action="store_true", help="复杂题不做语义判分，只用严格关键词口径")
    ap.add_argument("--no-all-small", action="store_true", help="不跑「全小模型」对照列")
    ap.add_argument("--all-small-answers", action="store_true",
                    help="对所有行都补齐小模型答案（供阈值扫描/流量画像做离线反事实回放，单条约 0.00002 元）")
    args = ap.parse_args()

    if args.dry_run:
        compile_java()
        routes = route_all(args.threshold, args.simple_model, args.complex_model)
        kinds = {}
        for line in DATA.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = line.split("\t")
            kinds[r[0]] = r[1]
        tp = sum(1 for i, k in kinds.items() if k == "complex" and routes.get(i, {}).get("tier") == "complex")
        fn = sum(1 for i, k in kinds.items() if k == "complex" and routes.get(i, {}).get("tier") == "simple")
        tn = sum(1 for i, k in kinds.items() if k == "simple" and routes.get(i, {}).get("tier") == "simple")
        fp = sum(1 for i, k in kinds.items() if k == "simple" and routes.get(i, {}).get("tier") == "complex")
        print(json.dumps({
            "n": len(kinds), "complex_recall": pct(tp, tp + fn), "simple_recall": pct(tn, tn + fp),
            "complex_total": tp + fn, "simple_total": tn + fp,
            "misroute_complex_to_simple": fn, "misroute_simple_to_complex": fp,
            "misroute_ids": [i for i, k in kinds.items()
                             if (k == "complex" and routes.get(i, {}).get("tier") == "simple")
                             or (k == "simple" and routes.get(i, {}).get("tier") == "complex")],
        }, ensure_ascii=False, indent=2))
        return

    key = KEY_FILE.read_text().strip()
    prices = load_prices()
    compile_java()
    routes = route_all(args.threshold, args.simple_model, args.complex_model)
    rows = read_rows(args.limit)

    RAW.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if RAW.exists():
        try:
            done = {x["id"]: x for x in json.loads(RAW.read_text(encoding="utf-8"))}
        except Exception:
            done = {}
    # 题目/资料变了（qhash 不同）就丢弃旧结果，避免复用错答案
    by_id = {r["id"]: r for r in rows}
    stale = [i for i, rec in done.items()
             if i in by_id and rec.get("qh") != qhash(by_id[i])]
    for i in stale:
        done.pop(i, None)
    if stale:
        print(f"[route] drop stale cache {len(stale)} 条（题目已变）：{stale[:8]}", flush=True)
    # 分流是本地免费计算：缓存行也按当前路由器结果刷新（阈值/词表可能已调整）
    for i, rec in done.items():
        if i in routes:
            rec["route"] = routes[i]
    # 兼容旧缓存字段名，并按当前归一化规则重算判分（判分规则可改，不必重跑模型）
    for rec in done.values():
        row = by_id.get(rec["id"], rec)
        for k, field in (("large", "large_ok_kw"), ("small", "small_ok_kw"), ("small_all", "small_all_ok_kw")):
            if rec.get(k):
                rec[field] = score(row, rec[k]["answer"])
    lock = threading.Lock()

    def work(row):
        rid = row["id"]
        rt = routes.get(rid, {"tier": "complex", "score": 0.0, "model": args.complex_model, "signals": ""})
        with lock:
            prev = done.get(rid)
        if prev and prev.get("large") and ((rt["tier"] != "simple" and not args.all_small_answers)
                                           or prev.get("small")):
            return prev
        large = call_model(key, args.complex_model, row["question"], row["context"])
        small = None
        if rt["tier"] == "simple" or args.all_small_answers:
            small = call_model(key, args.simple_model, row["question"], row["context"])
        rec = dict(row)
        rec.update({"qh": qhash(row), "route": rt,
                    "large": large, "large_cost": cost_of(large, prices),
                    "large_ok_kw": score(row, large["answer"]),
                    "small": small, "small_cost": cost_of(small, prices) if small else 0.0,
                    "small_ok_kw": score(row, small["answer"]) if small else None})
        with lock:
            done[rid] = rec
            RAW.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    def _needs(r):
        d = done.get(r["id"])
        if not d or not d.get("large"):
            return True
        return bool(args.all_small_answers and not d.get("small"))

    t0 = time.time()
    todo = [r for r in rows if _needs(r)]
    print(f"[route] rows={len(rows)} todo={len(todo)} workers={WORKERS}", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(work, r): r["id"] for r in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                f.result()
            except Exception as e:
                print(f"[route] {futs[f]} failed: {e!r}", flush=True)
            if i % 20 == 0:
                print(f"[route] progress {i}/{len(todo)} elapsed={int(time.time() - t0)}s", flush=True)

    records = [done[r["id"]] for r in rows if r["id"] in done and done[r["id"]].get("large")]

    # 第三条对照：全小模型（用于说明“路由到底省了多少钱、丢了什么”）
    if not args.no_all_small:
        need_small = [r for r in records if not r.get("small_all")]
        print(f"[route] all-small todo={len(need_small)}", flush=True)

        def do_small_all(r):
            s = call_model(key, args.simple_model, r["question"], r["context"])
            with lock:
                r["small_all"] = s
                r["small_all_cost"] = cost_of(s, prices)
                r["small_all_ok_kw"] = score(r, s["answer"])
                RAW.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=2), encoding="utf-8")
            return s

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(do_small_all, r) for r in need_small]
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    f.result()
                except Exception as e:
                    print(f"[route] all-small failed: {e!r}", flush=True)
                if i % 50 == 0:
                    print(f"[route] all-small progress {i}/{len(need_small)}", flush=True)

    # 语义判分：只判 templated 复杂题（联合诊断题）；计算题用数值容差判分，无需阅卷
    if not args.no_judge:
        need = [r for r in records
                if r["kind"] == "complex" and r.get("subkind") != "calc" and _missing_judge(r)]
        print(f"[route] judge todo={len(need)}", flush=True)

        def do_judge(r):
            j = r.get("judge") or {}
            ju = r.get("judge_usage") or {}
            for k in ("large", "small", "small_all"):
                if r.get(k) and k not in j:
                    verdict, usage = judge_answer(key, r, r[k]["answer"])
                    j[k] = verdict
                    ju[k] = usage
            with lock:
                r["judge"] = j
                r["judge_usage"] = ju
                RAW.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=2), encoding="utf-8")
            return j

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(do_judge, r) for r in need]
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    f.result()
                except Exception as e:
                    print(f"[route] judge failed: {e!r}", flush=True)
                if i % 50 == 0:
                    print(f"[route] judge progress {i}/{len(need)}", flush=True)

    report = aggregate(records, prices, args)
    (OUT_DIR / "路由评测.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "路由评测报告.md").write_text(build_md(report, records, args), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


def ok_of(r, key_name):
    """判分口径：计算题用数值容差结果；复杂诊断题用语义判分；简单题用规格值关键词"""
    if r.get("subkind") == "calc":
        field = {"large": "large_ok_kw", "small": "small_ok_kw", "small_all": "small_all_ok_kw"}[key_name]
        return bool(r.get(field))
    if r["kind"] == "complex" and r.get("judge") and key_name in r["judge"]:
        return bool(r["judge"][key_name])
    field = {"large": "large_ok_kw", "small": "small_ok_kw", "small_all": "small_all_ok_kw"}[key_name]
    if field in r:
        return bool(r[field])
    legacy = {"large": "large_ok", "small": "small_ok"}.get(key_name)
    return bool(r.get(legacy)) if legacy else False


def _missing_judge(r):
    j = r.get("judge") or {}
    ju = r.get("judge_usage") or {}
    return any(r.get(k) and (k not in j or k not in ju) for k in ("large", "small", "small_all"))


def aggregate(rows, prices, args):
    n = len(rows)
    large_ok = sum(1 for r in rows if ok_of(r, "large"))
    large_ok_kw = sum(1 for r in rows if r.get("large_ok_kw"))
    large_cost = sum(r["large_cost"] for r in rows)

    def routed_ok(r):
        return ok_of(r, "small") if r["route"]["tier"] == "simple" else ok_of(r, "large")

    routed_ok_n = sum(1 for r in rows if routed_ok(r))
    routed_ok_kw = sum(1 for r in rows
                       if (r.get("small_ok_kw") if r["route"]["tier"] == "simple" else r.get("large_ok_kw")))
    routed_cost = sum((r["small_cost"] if r["route"]["tier"] == "simple" else r["large_cost"]) for r in rows)
    # 全小模型对照：优先用与路由共用同一份调用的 small 答案（配对口径，排除同模型两次采样的波动）；
    # 未补齐 small 时回退到独立第二次运行 small_all
    PAIRED_SMALL = all(r.get("small") for r in rows)
    small_key = "small" if PAIRED_SMALL else "small_all"
    small_all_ok = sum(1 for r in rows if ok_of(r, small_key))
    small_all_ok_kw = sum(1 for r in rows if r.get(f"{small_key}_ok_kw"))
    small_all_cost = sum(r.get(f"{small_key}_cost", 0.0) for r in rows)

    by_kind = {}
    for k in ("simple", "complex"):
        sub = [r for r in rows if r["kind"] == k]
        by_kind[k] = {
            "n": len(sub),
            "baseline_acc": pct(sum(1 for r in sub if ok_of(r, "large")), len(sub)),
            "routed_acc": pct(sum(1 for r in sub if routed_ok(r)), len(sub)),
            "all_small_acc": pct(sum(1 for r in sub if ok_of(r, small_key)), len(sub)),
            "baseline_acc_kw": pct(sum(1 for r in sub if r.get("large_ok_kw")), len(sub)),
            "routed_acc_kw": pct(sum(1 for r in sub
                                     if (r.get("small_ok_kw") if r["route"]["tier"] == "simple"
                                         else r.get("large_ok_kw"))), len(sub)),
            "routed_to_small": sum(1 for r in sub if r["route"]["tier"] == "simple"),
        }

    wrong_simple = [r for r in rows if r["kind"] == "complex" and r["route"]["tier"] == "simple"]
    wrong_simple_fail = [r for r in wrong_simple if ok_of(r, "small") is False]
    wrong_complex = [r for r in rows if r["kind"] == "simple" and r["route"]["tier"] == "complex"]
    calc = [r for r in rows if r.get("subkind") == "calc"]
    calc_miss = [r for r in calc if r["route"]["tier"] == "simple"]
    templated = [r for r in rows if r.get("subkind") == "templated"]

    def sub_stat(sub):
        return {
            "n": len(sub),
            "misrouted_to_small": sum(1 for r in sub if r["route"]["tier"] == "simple"),
            "misrouted_failed": sum(1 for r in sub if r["route"]["tier"] == "simple" and ok_of(r, "small") is False),
            "baseline_acc": pct(sum(1 for r in sub if ok_of(r, "large")), len(sub)),
            "routed_acc": pct(sum(1 for r in sub if routed_ok(r)), len(sub)),
            "all_small_acc": pct(sum(1 for r in sub if ok_of(r, small_key)), len(sub)),
        }

    def brief(r, ans_key):
        return {
            "id": r["id"], "kind": r["kind"], "subkind": r.get("subkind", ""),
            "device": r["device"], "question": r["question"],
            "gold": r["gold"], "score": r["route"]["score"], "signals": r["route"]["signals"],
            "answered_by": r["route"]["model"],
            "correct": ok_of(r, "small") if r["route"]["tier"] == "simple" else ok_of(r, "large"),
            "answer": (r.get(ans_key) or {}).get("answer", "")[:220],
        }

    judge_n = sum(1 for r in rows if r.get("judge"))
    summary = {
        "n": n,
        "baseline": {"model": args.complex_model, "acc": pct(large_ok, n), "correct": large_ok,
                     "acc_kw": pct(large_ok_kw, n), "cost_cny": round(large_cost, 4)},
        "routed": {"acc": pct(routed_ok_n, n), "correct": routed_ok_n, "acc_kw": pct(routed_ok_kw, n),
                   "cost_cny": round(routed_cost, 4),
                   "saving_pct": round(100.0 * (large_cost - routed_cost) / large_cost, 2) if large_cost else 0.0},
        "all_small": {"model": args.simple_model, "acc": pct(small_all_ok, n), "correct": small_all_ok,
                      "acc_kw": pct(small_all_ok_kw, n), "cost_cny": round(small_all_cost, 4),
                      "acc_large_complex": by_kind["complex"]["all_small_acc"]},
        "quality_loss_pp": round(pct(large_ok, n) - pct(routed_ok_n, n), 2),
        "quality_loss_pp_kw": round(pct(large_ok_kw, n) - pct(routed_ok_kw, n), 2),
        "judged_rows": judge_n,
        "routed_simple": sum(1 for r in rows if r["route"]["tier"] == "simple"),
        "routed_complex": sum(1 for r in rows if r["route"]["tier"] == "complex"),
        "misroute_complex_as_simple": len(wrong_simple),
        "misroute_complex_as_simple_failed": len(wrong_simple_fail),
        "misroute_simple_as_complex": len(wrong_complex),
        "by_subkind": {
            "templated": sub_stat(templated),
            "calc": sub_stat(calc),
        },
        "hard_complex": sub_stat(calc),
        "avg_large_latency_s": round(sum(r["large"]["latency_s"] for r in rows) / n, 1) if n else 0,
        "tokens": {
            "baseline": tok_sum([r["large"] for r in rows if r.get("large")]),
            "routed": tok_sum([r["small"] if r["route"]["tier"] == "simple" else r["large"] for r in rows
                               if (r.get("small") if r["route"]["tier"] == "simple" else r.get("large"))]),
            "all_small": tok_sum([r[small_key] for r in rows if r.get(small_key)]),
            "judge": tok_sum([r["judge_usage"][k] for r in rows for k in (r.get("judge_usage") or {})]),
        },
        "threshold": args.threshold,
        "prices_source": "application.yml tims.ai.model-prices",
    }
    return {
        "meta": {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "dataset": str(DATA.relative_to(ROOT)), "n": n,
                 "simple_model": args.simple_model, "complex_model": args.complex_model,
                 "judge_model": "glm-4-flash（复杂题语义判分）" if not args.no_judge else "未启用",
                 "threshold": args.threshold, "prices": prices},
        "summary": summary,
        "by_kind": by_kind,
        "misroute_failures": [brief(r, "small") for r in wrong_simple_fail],
        "small_tier_failures": [brief(r, "small") for r in rows
                                if r["kind"] == "simple" and r["route"]["tier"] == "simple"
                                and ok_of(r, "small") is False],
        "misroute_to_complex": [brief(r, "large") for r in wrong_complex],
        "all_small_failures": [brief(r, small_key) for r in rows if ok_of(r, small_key) is False],
    }


def pct(a, b):
    return round(100.0 * a / b, 2) if b else 0.0


def build_md(rep, rows, args):
    s = rep["summary"]
    L = ["# AI 应用层·模型路由评测报告\n",
         f"- 生成时间：{rep['meta']['generated_at']}",
         f"- 数据：{rep['meta']['dataset']}（{s['n']} 条：150 简单 + 120 联合诊断复杂 + 30 短问句计算复杂）",
         f"- 路由：得分 ≥ {s['threshold']} 判复杂走 `{args.complex_model}`，否则走 `{args.simple_model}`；信号全部可解释",
         f"- 判分：简单题比对规格数值片段；联合诊断题由 `{rep['meta']['judge_model']}` 语义阅卷；"
         "计算题比对数值（±0.06 容差），并同时给出严格关键词口径作为保守下界",
         "- 计价：`application.yml` 的 `tims.ai.model-prices`（元/千 tokens），成本为本次实测 token 逐条累加\n",
         "## 1. 总体：全大模型 vs 路由\n",
         "| 方案 | 准确率（主口径） | 准确率（严格关键词） | 成本（元） | 相对节省 |",
         "|---|---|---|---|---|",
         f"| 全大模型（{args.complex_model}） | {s['baseline']['acc']}% | {s['baseline']['acc_kw']}% | {s['baseline']['cost_cny']} | - |",
         f"| 路由 | {s['routed']['acc']}% | {s['routed']['acc_kw']}% | {s['routed']['cost_cny']} | {s['routed']['saving_pct']}% |",
         f"| 全小模型（配对口径，{args.simple_model}） | {s['all_small']['acc']}% | {s['all_small']['acc_kw']}% | {s['all_small']['cost_cny']} | "
         f"{round(100.0 * (s['baseline']['cost_cny'] - s['all_small']['cost_cny']) / s['baseline']['cost_cny'], 2) if s['baseline']['cost_cny'] else 0}% |",
         "",
         f"- 路由相对全大模型的质量损失：主口径 {s['quality_loss_pp']} 个百分点，严格关键词口径 {s['quality_loss_pp_kw']} 个百分点",
         f"- 全小模型相对全大模型的质量损失：{round(s['baseline']['acc'] - s['all_small']['acc'], 2)} 个百分点"
         f"（复杂题上 {round(rep['by_kind']['complex']['baseline_acc'] - rep['by_kind']['complex']['all_small_acc'], 2)} 个百分点）",
         f"- 分流结果：简单档 {s['routed_simple']} 条，复杂档 {s['routed_complex']} 条",
         f"- 语义判分覆盖：{s['judged_rows']} 条联合诊断题（计算题用数值判分，不送阅卷）",
         f"- 大模型平均延迟：{s['avg_large_latency_s']} s\n",
         "### 1.1 实测 token 与费用\n",
         "| 方案 | 输入 tokens | 输出 tokens | 其中 reasoning | 合计 | 费用（元） |",
         "|---|---|---|---|---|---|",
         ]
    tk = s.get("tokens") or {}
    for name, label, cost in (("baseline", f"全大模型（{args.complex_model}）", s["baseline"]["cost_cny"]),
                              ("routed", "路由", s["routed"]["cost_cny"]),
                              ("all_small", f"全小模型（配对口径，{args.simple_model}）", s["all_small"]["cost_cny"])):
        t = tk.get(name) or {}
        L.append(f"| {label} | {t.get('prompt', 0)} | {t.get('completion', 0)} | {t.get('reasoning', 0)} | "
                 f"{t.get('total', 0)} | {cost} |")
    jt = tk.get("judge") or {}
    L.append(f"| 阅卷（glm-4-flash，不计入上表方案） | {jt.get('prompt', 0)} | {jt.get('completion', 0)} | 0 | "
             f"{jt.get('total', 0)} | 约 {round(jt.get('prompt', 0) / 1000 * 0.0001 + jt.get('completion', 0) / 1000 * 0.0001, 4)} |")
    L.append("")
    L += ["## 2. 分题型准确率\n",
         "| 题型 | 条数 | 全大模型 | 路由 | 全小模型（配对） | 其中分流到小模型 |",
         "|---|---|---|---|---|---|",
         f"| 简单（单条目事实） | {rep['by_kind']['simple']['n']} | {rep['by_kind']['simple']['baseline_acc']}% | {rep['by_kind']['simple']['routed_acc']}% | {rep['by_kind']['simple']['all_small_acc']}% | {rep['by_kind']['simple']['routed_to_small']} |",
         f"| 复杂（合计） | {rep['by_kind']['complex']['n']} | {rep['by_kind']['complex']['baseline_acc']}% | {rep['by_kind']['complex']['routed_acc']}% | {rep['by_kind']['complex']['all_small_acc']}% | {rep['by_kind']['complex']['routed_to_small']} |",
         "",
         "按子类型拆分：\n",
         "| 子类型 | 条数 | 全大模型 | 路由 | 全小模型（配对） | 被判成简单 | 其中小模型答错 |",
         "|---|---|---|---|---|---|---|",
         ]
    bs = s.get("by_subkind") or {}
    for key, label in (("templated", "联合诊断（长问句）"), ("calc", "短问句计算")):
        x = bs.get(key) or {}
        L.append(f"| {label} | {x.get('n', 0)} | {x.get('baseline_acc', 0)}% | {x.get('routed_acc', 0)}% | "
                 f"{x.get('all_small_acc', 0)}% | {x.get('misrouted_to_small', 0)} | {x.get('misrouted_failed', 0)} |")
    L += ["",
         "## 3. 误判分析\n",
         f"- 复杂题被判成简单（风险项）：{s['misroute_complex_as_simple']} 条，其中小模型答错 **{s['misroute_complex_as_simple_failed']} 条**",
         f"- 简单题被判成复杂（仅多花钱）：{s['misroute_simple_as_complex']} 条",
         f"- 短问句计算题（复杂但字面像简单，共 {s['hard_complex']['n']} 条）：被误判成简单 {s['hard_complex']['misrouted_to_small']} 条，"
         f"其中小模型答错 {s['hard_complex']['misrouted_failed']} 条；该子集准确率 全大模型 {s['hard_complex']['baseline_acc']}% → 路由 {s['hard_complex']['routed_acc']}%\n"]

    if rep["misroute_failures"]:
        L.append("### 3.1 判成简单但答错的样本（逐条）\n")
        L.append("| ID | 问题 | 正确要点 | 路由分 | 命中信号 | 小模型答案（截断） |")
        L.append("|---|---|---|---|---|---|")
        for x in rep["misroute_failures"]:
            L.append(f"| {x['id']} | {x['question'][:70]} | {x['gold'].replace('|', ' / ')} | {x['score']} | {x['signals'].replace('|', ' + ')} | "
                     f"{x['answer'][:120].replace('|', '/').replace(chr(10), ' ')} |")
        L.append("")
    else:
        L.append("### 3.1 判成简单但答错的样本\n\n无。\n")

    if rep["misroute_to_complex"]:
        L.append("### 3.2 简单题被判成复杂（保守误判）\n")
        L.append("| ID | 问题 | 路由分 | 命中信号 | 大模型是否正确 |")
        L.append("|---|---|---|---|---|")
        for x in rep["misroute_to_complex"][:20]:
            L.append(f"| {x['id']} | {x['question'][:40]} | {x['score']} | {x['signals'].replace('|', ' + ')} | "
                     f"{'是' if x['correct'] else '否'} |")
        L.append("")

    if rep.get("small_tier_failures"):
        L.append("### 3.3 路由正确但小模型答错的样本（能力不足，不是分流失误）\n")
        L.append("| ID | 问题 | 正确要点 | 小模型答案（截断） |")
        L.append("|---|---|---|---|")
        for x in rep["small_tier_failures"]:
            L.append(f"| {x['id']} | {x['question'][:40]} | {x['gold']} | {x['answer'][:80].replace('|', '/')} |")
        L.append("")

    if rep.get("all_small_failures"):
        L.append("### 3.4 全小模型方案的全部错题（用于说明「小模型能力边界」，与路由无关）\n")
        L.append("| ID | 子类型 | 问题 | 正确要点 | 小模型答案（截断） |")
        L.append("|---|---|---|---|---|")
        for x in rep["all_small_failures"]:
            L.append(f"| {x['id']} | {x['subkind']} | {x['question'][:60]} | {x['gold'].replace('|', ' / ')} | "
                     f"{x['answer'][:110].replace('|', '/').replace(chr(10), ' ')} |")
        L.append("")

    L.append("## 4. 复现方式\n")
    L.append("```bash\npython3 scripts/ai_layer/gen_route_set.py\npython3 scripts/ai_layer/route_eval.py\n```")
    L.append("\n## 5. 写进论文时的局限说明\n")
    L.append("1. 评测集从项目知识库 310 条条目派生，题目与「参考资料」同源，衡量的是「有资料时两种模型的作答质量」，"
             "不代表开放域问答；简单/复杂标签由构造方式决定，不是人工难度评分。")
    L.append("2. 联合诊断题的判分由 glm-4-flash 语义阅卷，与被测小模型同族，存在偏袒可能；"
             "已同时给出严格关键词口径（要求逐字出现两条条目的部件名）作为保守下界。"
             "实测该口径偏松：小模型只要复述资料里的「可能原因」即判对，因此 120 条联合诊断题上三种方案差距被抹平。")
    L.append("3. 30 条短问句计算题的测量值是按知识库规格区间合成的，不来自现场采集；"
             "其价值在于客观可判（gold 由代码计算，±0.06 容差），用于暴露路由的失败模式，而非估计线上数值分布。")
    L.append("4. 路由是纯规则加权，信号（长度/多跳/推理词/工具/历史轮次）在中文上靠词表覆盖，"
             "换业务域需重配词表；阈值 0.5 未做交叉验证寻优，离线回放的阈值扫描（0.1–1.0）见"
             "《路由敏感性与错误代价》：本批样本得分双峰，0.3–0.9 准确率不变、成本随阈值单调下降。")
    L.append("5. 成本按标准价折算，未计缓存与资源包折扣；glm-5.3-flash 有专属资源包，实际现金支出低于报告值。")
    L.append("6. 判成简单后小模型答错的样本已逐条列出，但计算题仅 30 条，失败率置信区间较宽。")
    L.append("7. 「全小模型」列为配对口径：与路由共用同一份小模型调用，只改变「哪些行走大模型」，"
             "以排除同模型两次采样的波动（独立第二次运行的结果为 93.0%，与配对口径差 3 条）。")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
