#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原型评测：把算术交给确定性工具，而不是交给路由。

被测对象：glm-4-flash + 单个 function calling 工具 run_calculation（见 tool_calc.py）。
评测集：scripts/ai_layer/data/holdout_set.tsv（120 条，与 A1-v1 留出集完全同一批）。

指标：
  - 总准确率（calc 分片按数值容差 ±0.06，simple 分片按关键值包含）
  - 工具调用率（至少调用一次）
  - 漏算：calc 分片（85 条，本该算）却一次也没调用
  - 误调用：simple 分片（35 条，不该算）却调用了
  - 参数抽取错误：数抽错 / 关系抽错（含单位换错），二者分开统计
  - 计算错误：抽取正确但最终答案错（工具链或抄写问题）
  - 单条延迟、总费用

用法（仓库根目录）：
  python3 scripts/ai_layer/tool_calc_eval.py --limit 5     # 试跑 5 条，校准 schema
  python3 scripts/ai_layer/tool_calc_eval.py               # 全量 120 条
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from tool_calc import TOOL_SCHEMA, run_calculation  # noqa: E402

HOLDOUT = HERE / "data" / "holdout_set.tsv"
OUT_DIR = ROOT / "docs" / "paper" / "ai应用层"
RAW_DIR = OUT_DIR / "raw"
CACHE = RAW_DIR / "tool_calc_rows.json"
OUT_JSON = OUT_DIR / "工具计算原型.json"
OUT_CSV = RAW_DIR / "tool_calc_detail.csv"
PILOT_JSON = OUT_DIR / "工具计算原型_pilot.json"
PILOT_CSV = RAW_DIR / "tool_calc_pilot.csv"

API = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
KEY_FILE = Path(os.environ.get("LLM_API_KEY_FILE", "/home/dev/secrets/zhipu_api_key"))
MODEL = "glm-4-flash"
PRICE_IN = PRICE_OUT = 0.0001  # 元/千 token（application.yml 口径）

SYSTEM_PROMPT = (
    "你是 AI-TIMS 工业设备运维助手。只依据给定参考资料回答。"
    "只要题目涉及任何数值计算（差值、百分比变化、计数、占比、均值、区间判断），"
    "你必须调用 run_calculation 工具，把题面里的数字与关系作为参数传入；"
    "禁止自己心算或估算，也不能用文字描述计算过程来代替实际调用。"
    "一次只算一个结果；多个互不依赖的结果可以在同一轮里同时发起多个调用。"
    "参数缺失时先补齐再调用，不要用默认值猜。"
    "最终回答先给结论，再给关键依据，控制在 150 字以内。"
)
MAX_ROUNDS = 6
MAX_TOKENS = 1024
WORKERS = 6
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
META_NUM = re.compile(r"(?:保留\s*一?位小数)|(?:\d+\s*次测量)|(?:\d+\s*个读数)|(?:\d+\s*个测量值)"
                      r"|(?:这批\s*\d+\s*件)|(?:WO-[0-9A-Za-z\-]+)|(?:\d+\s*号线)"
                      r"|(?:\d+\s*号工位)|(?:第\s*\d+\s*版)")


# ---------------------------------------------------------------- 基础
def load_key():
    return KEY_FILE.read_text(encoding="utf-8").strip()


def post(key, body, timeout=180, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                API, data=json.dumps(body).encode(),
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def norm(s):
    s = (s or "").strip().lower()
    for a, b in (("～", "-"), ("~", "-"), ("—", "-"), ("–", "-"), ("－", "-"),
                 ("．", "."), (" ", ""), ("毫秒", "ms"), ("分钟", "min"),
                 ("秒", "s"), ("％", "%")):
        s = s.replace(a, b)
    return s


def graded(gold, answer):
    a = norm(answer)
    return bool(gold) and all(norm(g) in a for g in gold.split("|") if g)


def calc_ok(gold, answer):
    got = [float(x) for x in NUM_RE.findall((answer or "").replace(",", ""))]
    for g in gold.split("|"):
        if not g:
            continue
        if not any(abs(v - float(g)) <= 0.06 for v in got):
            return False
    return True


def qhash(row):
    return hashlib.md5((row["question"] + "\x00" + row["context"]).encode()).hexdigest()[:12]


def read_holdout(path=None):
    rows = []
    for line in Path(path or HOLDOUT).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = line.split("\t")
        rows.append({"id": p[0], "slice": p[1], "trap": p[2], "template": p[3],
                     "device": p[4], "question": p[5], "context": p[6], "gold": p[7],
                     "gold_type": p[8], "history_turns": int(p[9]),
                     "needs_tool": p[10] == "True", "qh": qhash({"question": p[5], "context": p[6]})})
    return rows


# ---------------------------------------------------------------- 模型 + 工具回路
def run_one(key, row):
    """一次问答；模型可多轮调用工具。返回回答、调用轨迹与用量。"""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "参考资料：\n%s\n\n问题：%s" % (row["context"], row["question"])}]
    calls, usage, t0, answer = [], {"prompt": 0, "completion": 0}, time.time(), ""
    rounds = 0
    for _ in range(MAX_ROUNDS):
        rounds += 1
        d = post(key, {"model": MODEL, "messages": msgs, "tools": [TOOL_SCHEMA],
                       "tool_choice": "auto", "max_tokens": MAX_TOKENS, "temperature": 0.0})
        u = d.get("usage") or {}
        usage["prompt"] += int(u.get("prompt_tokens") or 0)
        usage["completion"] += int(u.get("completion_tokens") or 0)
        msg = d["choices"][0]["message"]
        tcs = msg.get("tool_calls") or []
        if not tcs:
            answer = (msg.get("content") or "").strip()
            break
        msgs.append({"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": tcs})
        for tc in tcs:
            fn = tc["function"]["name"]
            raw = tc["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {}
            if fn != "run_calculation":
                res = {"ok": False, "error": "未知工具 " + fn}
            else:
                try:
                    res = run_calculation(**args)
                except Exception as e:
                    # 模型可能传入 schema 之外的字段名，工具签名会抛 TypeError；
                    # 这类调用属于「参数不合法」，按工具报错计入，不能让整批判测崩掉
                    res = {"ok": False, "error": "参数不合法：%s: %s" % (type(e).__name__, e)}
                    print("bad_args %s %s" % (row["id"], json.dumps(args, ensure_ascii=False)))
            calls.append({"op": args.get("op"), "args": args, "result": res})
            msgs.append({"role": "tool", "tool_call_id": tc["id"],
                         "content": json.dumps(res, ensure_ascii=False)})
    return {"answer": answer, "calls": calls, "usage": usage, "rounds": rounds,
            "latency_s": round(time.time() - t0, 2)}


# ---------------------------------------------------------------- 抽取质量判定
def expected_ops(q):
    """题面要求哪些运算（独立于工具与 gold，仅用于给模型的抽取打标签）。"""
    ops = []
    if "下降了多少个百分点" in q or "跌了几个百分点" in q:
        ops.append("delta_percent")
    if "百分之几" in q or "百分之多少" in q:
        ops.append("pct_of")
    if "超标几次" in q or "超了几回" in q or "超了几次" in q or "算超标" in q:
        ops.append("count_over")
    if "越线" in q or "越过" in q or "几回超过" in q or "有几回超过" in q:
        ops.append("count_over")
    if "合格几次" in q or "合格的有几" in q:
        ops.append("count_in_range")
    if "占比" in q or "占多少" in q or "比例" in q or "占百分之" in q:
        ops.append("ratio")
    if "平均" in q or "均值" in q:
        ops.append("average")
    if "相差" in q or "高多少" in q or "差多少" in q:
        ops.append("difference")
    if "多几成" in q or "多百分之几" in q or "少了百分之几" in q or "多用了几成" in q:
        ops.append("delta_percent")
    return list(dict.fromkeys(ops))


def _nums(text):
    text = META_NUM.sub(" ", text)
    out = []
    for x in NUM_RE.findall(text):
        try:
            out.append(Decimal(x))
        except InvalidOperation:
            pass
    return out


def data_numbers(q, ctx=""):
    """题面/资料里的数据数字。

    优先取题面最后一个「：」之后的数据列表；其次取题面里的数字；最后回落到资料。
    「几成」「比上月多」这类隐含基数的题，数字在资料里，因此必须带 ctx。
    """
    body = ""
    if "：" in q:
        body = q.rsplit("：", 1)[1]
        body = re.split(r"[。？?]", body)[0]
    if not _nums(body):
        body = q
    out = _nums(body)
    if not out:
        out = _nums(ctx)
    return out


def model_numbers(calls):
    """模型传入的题面数字（不含 scale 与 numerator/denominator 这类派生量）。"""
    out = []
    for c in calls:
        a = c["args"]
        for k in ("initial", "current", "lower", "upper"):
            if isinstance(a.get(k), (int, float)):
                out.append(Decimal(str(a[k])))
        for v in a.get("values") or []:
            if isinstance(v, (int, float)):
                out.append(Decimal(str(v)))
    return out


def derived_numbers(calls):
    """前序工具调用返回过的值（含模型四舍五入后的复述）。

    这类数字不是「凭空造数」，而是中间结果，判数抽错时应予放行。
    """
    out = []
    for c in calls:
        r = c.get("result") or {}
        if r.get("ok") and isinstance(r.get("result"), (int, float)):
            out.append(Decimal(str(r["result"])))
    return out


OP_FAMILY = {"ratio": "share", "pct_of": "share"}
# 同一语义的不同写法（占比/百分之几）视为等价；其余运算各自独立


def classify(row, calls):
    """返回 ok / num / rel / both / none；none 表示没有调用。

    数抽错的判据：模型传入的数字必须全部出现在题面/资料中（不得凭空造数），
    且题面「：」之后的数据列表必须全部被传入（不得漏数）。
    资料里未被问到的阈值类数字不要求传入，避免把「没用到」误判成抽错。
    """
    if not calls:
        return "none"
    q, ctx = row["question"], row["context"]
    allowed = {x for x in _nums(q) + _nums(ctx)}
    required = _nums(q.rsplit("：", 1)[1].split("？")[0]) if "：" in q else []
    got = {x for x in model_numbers(calls)}
    # 前序工具结果的复述（允许四舍五入）不算造数；但「数据必须全部传入」仍按原始 got 校验
    derived = derived_numbers(calls)
    got_no_derived = ({g for g in got if not any(abs(g - d) <= Decimal("0.06") for d in derived)}
                      if derived else got)
    num_ok = got_no_derived <= allowed and all(n in got for n in required)
    exp, got_ops = expected_ops(q), [c["op"] for c in calls]
    got_fam = {OP_FAMILY.get(o, o) for o in got_ops}
    rel_ok = all(OP_FAMILY.get(o, o) in got_fam for o in exp)
    # 「成」必须用 scale=0.1 换算，否则算关系（单位）抽错
    if "几成" in q:
        rel_ok = rel_ok and any(abs(float(c["args"].get("scale", 1)) - 0.1) < 1e-9 for c in calls)
    if num_ok and rel_ok:
        return "ok"
    if not num_ok and not rel_ok:
        return "both"
    return "rel" if num_ok else "num"


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--set", default="", help="题目 TSV 路径；默认用 holdout_set.tsv")
    ap.add_argument("--tag", default="", help="产物后缀，如 holdout2")
    args = ap.parse_args()
    pilot = args.limit > 0
    tsv = Path(args.set) if args.set else HOLDOUT
    tag = args.tag
    if pilot:
        out_json, out_csv = PILOT_JSON, PILOT_CSV
        cache_path = CACHE
    elif tag:
        out_json = OUT_DIR / ("工具计算原型_%s.json" % tag)
        out_csv = RAW_DIR / ("tool_calc_%s.csv" % tag)
        cache_path = RAW_DIR / ("tool_calc_rows_%s.json" % tag)
    else:
        out_json, out_csv, cache_path = OUT_JSON, OUT_CSV, CACHE

    rows = read_holdout(tsv)
    if pilot:
        rows = rows[:args.limit]
    key = load_key()
    cache = {}
    if not pilot and cache_path.exists():
        for x in json.loads(cache_path.read_text(encoding="utf-8")):
            cache[x["id"]] = x

    results = []
    todo = [r for r in rows if not (cache.get(r["id"]) and cache[r["id"]].get("qh") == r["qh"])]
    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(run_one, key, r): r for r in todo}
            for k, f in enumerate(as_completed(futs), 1):
                r = futs[f]
                res = f.result()
                res["id"], res["qh"] = r["id"], r["qh"]
                cache[r["id"]] = res
                print("done %d/%d %s %.2fs" % (k, len(todo), r["id"], res["latency_s"]))
        if not pilot:
            cache_path.write_text(json.dumps(list(cache.values()), ensure_ascii=False), encoding="utf-8")

    for i, r in enumerate(rows, 1):
        res = cache[r["id"]]
        ok = calc_ok(r["gold"], res["answer"]) if r["slice"] == "calc" else graded(r["gold"], res["answer"])
        kind = classify(r, res["calls"])
        bad_calls = sum(1 for x in res["calls"] if not x["result"].get("ok"))
        unfinished = not (res["answer"] or "").strip()
        results.append({"row": r, "res": res, "correct": ok, "extract": kind,
                        "tool_error": bad_calls > 0, "bad_calls": bad_calls,
                        "unfinished": unfinished})
        print("%3d/%d %s slice=%s calls=%d extract=%s correct=%s %.2fs" % (
            i, len(rows), r["id"], r["slice"], len(res["calls"]), kind, ok, res["latency_s"]))

    n = len(results)
    calc = [x for x in results if x["row"]["slice"] == "calc"]
    simple = [x for x in results if x["row"]["slice"] == "simple"]
    pure_fact = [x for x in simple if x["row"]["template"] != "trap_colloquial_single"]
    single_step = [x for x in simple if x["row"]["template"] == "trap_colloquial_single"]
    called = [x for x in results if x["res"]["calls"]]
    cost = sum(x["res"]["usage"]["prompt"] * PRICE_IN / 1000.0
               + x["res"]["usage"]["completion"] * PRICE_OUT / 1000.0 for x in results)

    def rate(a, b):
        return round(100.0 * a / b, 2) if b else 0.0

    def calls_in(group):
        return sum(1 for x in group if x["res"]["calls"])

    summary = {
        "model": MODEL,
        "n": n,
        "acc": rate(sum(1 for x in results if x["correct"]), n),
        "by_slice": {
            "calc": {"n": len(calc), "acc": rate(sum(1 for x in calc if x["correct"]), len(calc))},
            "simple": {"n": len(simple), "acc": rate(sum(1 for x in simple if x["correct"]), len(simple))},
        },
        "by_trap": {},
        "tool_call_rate": rate(len(called), n),
        "missed_calc": {"n": sum(1 for x in calc if not x["res"]["calls"]),
                        "rate": rate(sum(1 for x in calc if not x["res"]["calls"]), len(calc))},
        "false_call_simple": {"n": calls_in(simple), "rate": rate(calls_in(simple), len(simple)),
                              "pure_fact": {"n": calls_in(pure_fact), "rate": rate(calls_in(pure_fact), len(pure_fact))},
                              "single_step": {"n": calls_in(single_step),
                                              "rate": rate(calls_in(single_step), len(single_step))}},
        "extract": {
            "ok": sum(1 for x in called if x["extract"] == "ok"),
            "num_wrong": sum(1 for x in called if x["extract"] in ("num", "both")),
            "rel_wrong": sum(1 for x in called if x["extract"] in ("rel", "both")),
            "both_wrong": sum(1 for x in called if x["extract"] == "both"),
            "base": len(called),
        },
        # 计算错误：抽取正确、模型也确实给出了答案，但答案数值错
        "calc_error": sum(1 for x in called if x["extract"] == "ok" and not x["correct"]
                          and not x["unfinished"]),
        # 未完成：跑完轮次仍没有最终回答（不能算计算错误，单列）
        "unfinished": {"n": sum(1 for x in results if x["unfinished"]),
                       "rate": rate(sum(1 for x in results if x["unfinished"]), n)},
        "tool_error": {"rows": sum(1 for x in results if x["tool_error"]),
                       "rows_rate": rate(sum(1 for x in results if x["tool_error"]), n),
                       "calls": sum(x["bad_calls"] for x in results),
                       "calls_rate": rate(sum(x["bad_calls"] for x in results),
                                          sum(len(x["res"]["calls"]) for x in results))},
        "avg_latency_s": round(sum(x["res"]["latency_s"] for x in results) / n, 2),
        "avg_calls": round(sum(len(x["res"]["calls"]) for x in results) / n, 2),
        "avg_rounds": round(sum(x["res"].get("rounds", 0) for x in results) / n, 2),
        "cost_cny": round(cost, 4),
    }
    # 原始 100 条同构题 = N1 + N2 + T1 + T2；T3 口语化为另加的 20 条
    groups = {"orig100": ("N1", "N2", "T1", "T2")}
    for gname, traps in groups.items():
        g = [x for x in results if x["row"]["trap"] in traps]
        if not g:
            continue
        gc = [x for x in g if x["row"]["slice"] == "calc"]
        summary[gname] = {"n": len(g), "acc": rate(sum(1 for x in g if x["correct"]), len(g)),
                          "call_rate": rate(calls_in(g), len(g)),
                          "calc": {"n": len(gc), "acc": rate(sum(1 for x in gc if x["correct"]), len(gc)),
                                   "call_rate": rate(calls_in(gc), len(gc))}}
    for t in dict.fromkeys(x["row"]["trap"] for x in results):
        g = [x for x in results if x["row"]["trap"] == t]
        summary["by_trap"][t] = {
            "n": len(g),
            "acc": rate(sum(1 for x in g if x["correct"]), len(g)),
            "call_rate": rate(calls_in(g), len(g)),
            "extract_ok": sum(1 for x in g if x["extract"] == "ok"),
        }

    out_json.write_text(json.dumps({"summary": summary,
                                    "detail": [{"id": x["row"]["id"], "slice": x["row"]["slice"],
                                                "trap": x["row"]["trap"], "question": x["row"]["question"],
                                                "gold": x["row"]["gold"], "answer": x["res"]["answer"],
                                                "calls": x["res"]["calls"], "correct": x["correct"],
                                                "extract": x["extract"],
                                                "latency_s": x["res"]["latency_s"],
                                                "usage": x["res"]["usage"]} for x in results]},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "trap", "slice", "gold", "answer", "n_calls", "ops", "extract",
                    "correct", "tool_error", "latency_s"])
        for x in results:
            w.writerow([x["row"]["id"], x["row"]["trap"], x["row"]["slice"], x["row"]["gold"],
                        x["res"]["answer"].replace("\n", " "),
                        len(x["res"]["calls"]),
                        "|".join(str(c["op"]) for c in x["res"]["calls"]),
                        x["extract"], x["correct"], x["tool_error"], x["res"]["latency_s"]])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
