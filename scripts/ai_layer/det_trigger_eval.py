#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""det-trigger-v1 闸门评测：覆盖率预检 + 三组同集对比 + 触发来源统计。

两种用法（都在仓库根目录）：

  # 1) 零费用覆盖率预检：用 gold 当答案喂给闸门，检查候选集能否复算出 gold
  python3 scripts/ai_layer/det_trigger_eval.py --coverage --set scripts/ai_layer/data/holdout2_set.tsv

  # 2) 正式评测：读取已缓存的工具路线与小/大模型裸跑结果，离线套用闸门
  python3 scripts/ai_layer/det_trigger_eval.py --tag holdout3 \
      --set scripts/ai_layer/data/holdout3_set.tsv --big glm-5.3-flash

评测口径：
  - 原始判定：calc 数值 ±0.06 任意位置命中；simple 关键值包含（与 §13/§14 一致）
  - 加严判定：只认结论行（首行；首行无数字时取首个含数字的句子），与 §14 一致
  - 触发来源：自调（模型自己调了工具且闸门接受）/ 强制（闸门触发）/ 未触发（未调且接受）
  - 升级策略复用大模型裸跑缓存：同一 prompt、同一 temperature 0.3、同一 max_tokens，
    因此与「全大模型」组是同一次调用口径，费用与延迟按缓存里的实际用量计。
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from det_trigger import TOL, VERSION, evaluate, numbers, render  # noqa: E402
from route_holdout_eval import load_prices  # noqa: E402
from tool_calc_eval import classify  # noqa: E402

OUT_DIR = ROOT / "docs" / "paper" / "ai应用层"
RAW_DIR = OUT_DIR / "raw"
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def read_set(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = line.split("\t")
        rows.append({"id": p[0], "slice": p[1], "trap": p[2], "template": p[3],
                     "device": p[4], "question": p[5], "context": p[6], "gold": p[7],
                     "gold_type": p[8]})
    return rows


def norm(s):
    s = (s or "").strip().lower()
    for a, b in (("～", "-"), ("~", "-"), ("—", "-"), ("–", "-"), ("－", "-"),
                 ("．", "."), (" ", ""), ("毫秒", "ms"), ("分钟", "min"),
                 ("秒", "s"), ("％", "%")):
        s = s.replace(a, b)
    return s


def strict_text(answer):
    """结论行：首个非空行；首行没有数字时退到首个含数字的句子。"""
    lines = [x.strip() for x in (answer or "").splitlines() if x.strip()]
    if lines and NUM_RE.search(lines[0]):
        return lines[0]
    for seg in re.split(r"[。！？\n]", answer or ""):
        if NUM_RE.search(seg):
            return seg
    return ""


def calc_ok(gold, text, tol=TOL):
    got = [float(x) for x in NUM_RE.findall(norm(text).replace(",", ""))]
    for g in gold.split("|"):
        if not g:
            continue
        if not any(abs(v - float(g)) <= tol for v in got):
            return False
    return True


def graded(gold, text):
    a = norm(text)
    return bool(gold) and all(norm(g) in a for g in gold.split("|") if g)


def judge(row, answer):
    """加严口径只作用于 calc（只认结论行）；simple 是短事实，按全文包含判定。"""
    raw = calc_ok(row["gold"], answer) if row["slice"] == "calc" else graded(row["gold"], answer)
    if row["slice"] == "calc":
        strict = calc_ok(row["gold"], strict_text(answer))
    else:
        strict = raw
    return {"raw": bool(raw), "strict": bool(strict)}


def rate(a, b):
    return round(100.0 * a / b, 2) if b else 0.0


def load_cache(path):
    if not path.exists():
        raise SystemExit("缺少缓存：%s" % path)
    return {x["id"]: x for x in json.loads(path.read_text(encoding="utf-8"))}


def cost_of(res, prices, model):
    pin, pout = prices.get(model, (0.0001, 0.0001))
    u = res.get("usage") if isinstance(res.get("usage"), dict) else res
    prompt = u.get("prompt", u.get("prompt_tokens", 0))
    completion = u.get("completion", u.get("completion_tokens", 0))
    return prompt / 1000.0 * pin + completion / 1000.0 * pout


# ---------------------------------------------------------------- 覆盖率预检
def coverage(args):
    rows = read_set(args.set)
    bad = []
    for r in rows:
        gold_answer = r["gold"].replace("|", "、")
        d = evaluate(r["question"], r["context"], gold_answer)
        ok = d["verdict"] == "accept"
        if not ok:
            bad.append({"id": r["id"], "trap": r["trap"], "gold": r["gold"],
                        "verdict": d["verdict"], "missing": d["missing"],
                        "n_candidates": d["n_candidates"]})
    print(json.dumps({"set": args.set, "n": len(rows), "covered": len(rows) - len(bad),
                      "failed": len(bad), "detail": bad}, ensure_ascii=False, indent=2))
    return 0 if not bad else 1


# ---------------------------------------------------------------- 正式评测
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--tag", default="holdout3")
    ap.add_argument("--out-tag", default=None,
                    help="产物名后缀，默认与 --tag 相同；用于复用旧缓存但另存产物")
    ap.add_argument("--big", default="glm-5.3-flash")
    ap.add_argument("--small", default="glm-4-flash")
    ap.add_argument("--coverage", action="store_true")
    args = ap.parse_args()
    if args.coverage:
        return coverage(args)
    out_tag = args.out_tag or args.tag

    rows = read_set(args.set)
    tool = load_cache(RAW_DIR / ("tool_calc_rows_%s.json" % args.tag))
    big = load_cache(RAW_DIR / ("bare_rows_%s_%s.json" % (args.tag, args.big)))
    small = load_cache(RAW_DIR / ("bare_rows_%s_%s.json" % (args.tag, args.small)))
    prices = load_prices()

    detail = []
    for r in rows:
        t, b = tool[r["id"]], big[r["id"]]
        gate = evaluate(r["question"], r["context"], t["answer"])
        called = bool(t.get("calls"))
        if gate["verdict"] == "accept":
            source = "自调" if called else "未触发"
        else:
            source = "强制"

        override_answer = render(gate["picked"]) if gate["verdict"] == "conflict" else ""
        esc = gate["verdict"] in ("conflict", "uncomputable")
        final_escalate = b["answer"] if esc else t["answer"]
        final_override = (override_answer if (gate["verdict"] == "conflict" and override_answer)
                          else t["answer"])

        base_j = judge(r, t["answer"])
        esc_j = judge(r, final_escalate)
        ovr_j = judge(r, final_override)
        big_j = judge(r, b["answer"])
        sml_j = judge(r, small[r["id"]]["answer"])

        detail.append({
            "id": r["id"], "slice": r["slice"], "trap": r["trap"], "gold": r["gold"],
            "question": r["question"], "tool_answer": t["answer"],
            "tool_correct": base_j, "calls": len(t.get("calls") or []),
            "gate": {"verdict": gate["verdict"], "reason": gate["reason"],
                     "n_candidates": gate["n_candidates"], "missing": gate["missing"],
                     "picked": gate["picked"], "unexplained": gate["unexplained"]},
            "source": source,
            "escalate_answer": b["answer"], "escalate_correct": esc_j,
            "override_answer": override_answer, "override_correct": ovr_j,
            "big_correct": big_j, "small_correct": sml_j,
            "tool_usage": t.get("usage", {}), "tool_rounds": t.get("rounds", 1),
            "tool_latency": t.get("latency_s", 0),
            "big_usage": {"prompt": b.get("prompt_tokens", 0),
                          "completion": b.get("completion_tokens", 0)},
            "big_latency": b.get("latency_s", 0),
            "small_usage": {"prompt": small[r["id"]].get("prompt_tokens", 0),
                            "completion": small[r["id"]].get("completion_tokens", 0)},
            "small_latency": small[r["id"]].get("latency_s", 0),
        })

    def group(key):
        n = len(detail)
        calc = [x for x in detail if x["slice"] == "calc"]
        return {"n": n,
                "acc": rate(sum(1 for x in detail if x[key]["strict"]), n),
                "acc_raw": rate(sum(1 for x in detail if x[key]["raw"]), n),
                "calc": {"n": len(calc), "acc": rate(sum(1 for x in calc if x[key]["strict"]), len(calc)),
                         "acc_raw": rate(sum(1 for x in calc if x[key]["raw"]), len(calc))},
                "simple": {"n": n - len(calc),
                           "acc": rate(sum(1 for x in detail if x["slice"] == "simple" and x[key]["strict"]), n - len(calc))}}

    g_tool = group("tool_correct")
    g_tool["call_rate"] = rate(sum(1 for x in detail if x["calls"] > 0), len(detail))
    g_tool["rounds"] = round(sum(x["tool_rounds"] for x in detail) / len(detail), 2)
    g_tool["latency_s"] = round(sum(x["tool_latency"] for x in detail) / len(detail), 2)
    g_tool["cost_cny"] = round(sum(cost_of(x["tool_usage"], prices, args.small) for x in detail), 4)

    g_esc = group("escalate_correct")
    g_esc["trigger_rate"] = rate(sum(1 for x in detail if x["source"] == "强制"), len(detail))
    g_esc["rounds"] = round(sum(x["tool_rounds"] + (1 if x["source"] == "强制" else 0)
                                for x in detail) / len(detail), 2)
    g_esc["latency_s"] = round(sum(x["tool_latency"] + (x["big_latency"] if x["source"] == "强制" else 0)
                                   for x in detail) / len(detail), 2)
    g_esc["cost_cny"] = round(sum(cost_of(x["tool_usage"], prices, args.small)
                                  + (cost_of({"prompt_tokens": x["big_usage"]["prompt"],
                                              "completion_tokens": x["big_usage"]["completion"]},
                                             prices, args.big)
                                     if x["source"] == "强制" else 0)
                              for x in detail), 4)

    g_ovr = group("override_correct")
    g_ovr["rounds"] = g_tool["rounds"]
    g_ovr["latency_s"] = g_tool["latency_s"]
    g_ovr["cost_cny"] = g_tool["cost_cny"]

    g_big = group("big_correct")
    g_big["latency_s"] = round(sum(x["big_latency"] for x in detail) / len(detail), 2)
    g_big["cost_cny"] = round(sum(cost_of({"prompt_tokens": x["big_usage"]["prompt"],
                                           "completion_tokens": x["big_usage"]["completion"]},
                                          prices, args.big) for x in detail), 4)
    g_big["rounds"] = 1

    g_sml = group("small_correct")
    g_sml["latency_s"] = round(sum(x["small_latency"] for x in detail) / len(detail), 2)
    g_sml["cost_cny"] = round(sum(cost_of(x["small_usage"], prices, args.small) for x in detail), 4)
    g_sml["rounds"] = 1

    def per(n, c):
        return round(c / n, 6) if n else 0.0

    for g in (g_tool, g_esc, g_ovr, g_big, g_sml):
        g["per_row_cost"] = per(len(detail), g["cost_cny"])

    # 触发来源分布 × 正确率
    sources = {}
    for s in ("自调", "强制", "未触发"):
        g = [x for x in detail if x["source"] == s]
        if not g:
            continue
        sources[s] = {"n": len(g), "share": rate(len(g), len(detail)),
                      "acc": rate(sum(1 for x in g if x["escalate_correct"]["strict"]), len(g)),
                      "acc_raw": rate(sum(1 for x in g if x["escalate_correct"]["raw"]), len(g)),
                      "correct": sum(1 for x in g if x["escalate_correct"]["strict"]),
                      "calc_n": sum(1 for x in g if x["slice"] == "calc")}

    # 按题型
    by_trap = {}
    for t in dict.fromkeys(x["trap"] for x in detail):
        g = [x for x in detail if x["trap"] == t]
        by_trap[t] = {"n": len(g),
                      "tool_acc": rate(sum(1 for x in g if x["tool_correct"]["strict"]), len(g)),
                      "tool_call_rate": rate(sum(1 for x in g if x["calls"] > 0), len(g)),
                      "det_acc": rate(sum(1 for x in g if x["escalate_correct"]["strict"]), len(g)),
                      "det_trigger_rate": rate(sum(1 for x in g if x["source"] == "强制"), len(g)),
                      "big_acc": rate(sum(1 for x in g if x["big_correct"]["strict"]), len(g))}

    # 工具路线五类错误（与 §14 的 24/0/4/1/3 同口径）
    tool_rows = []
    for x in detail:
        r = {"question": x["question"], "context": next(y["context"] for y in rows if y["id"] == x["id"]),
             "gold": x["gold"]}
        tool_rows.append((x, r, tool[x["id"]]))
    wrong = [(x, r, t) for x, r, t in tool_rows if not x["tool_correct"]["strict"]]
    err = {"该调没调": 0, "数抽错": 0, "关系抽错": 0, "工具报错": 0, "计算错": 0, "未完成": 0}
    for x, r, t in wrong:
        calls = t.get("calls") or []
        if not (x["tool_answer"] or "").strip():
            err["未完成"] += 1
            continue
        if not calls:
            err["该调没调"] += 1
            continue
        kind = classify(r, calls)
        if kind in ("num", "both"):
            err["数抽错"] += 1
        if kind in ("rel", "both"):
            err["关系抽错"] += 1
        if kind == "ok":
            err["计算错"] += 1
        if any(not c["result"].get("ok") for c in calls):
            err["工具报错"] += 1

    # 闸门组残余错误归因
    det_err = {"闸门漏触发后仍错": 0, "闸门触发且升级": 0, "升级后大模型也错": 0,
               "闸门触发但选错算子（覆盖）": 0, "工具报错": 0}
    for x in detail:
        if x["escalate_correct"]["strict"]:
            continue
        if x["source"] == "强制":
            det_err["闸门触发且升级"] += 1
            det_err["升级后大模型也错"] += 1
        else:
            det_err["闸门漏触发后仍错"] += 1
        if any(not c["result"].get("ok") for c in (tool[x["id"]].get("calls") or [])):
            det_err["工具报错"] += 1

    # 误覆盖：本来对，闸门覆盖后变错（按加严与原始两个口径分别计）
    damaged = [{"id": x["id"], "gold": x["gold"], "tool_answer": x["tool_answer"],
                "override_answer": x["override_answer"], "picked": x["gate"]["picked"]}
               for x in detail
               if x["gate"]["verdict"] == "conflict" and x["tool_correct"]["strict"]
               and not x["override_correct"]["strict"]]
    damaged_raw = [x["id"] for x in detail
                   if x["gate"]["verdict"] == "conflict" and x["tool_correct"]["raw"]
                   and not x["override_correct"]["raw"]]
    saved = [x["id"] for x in detail
             if x["source"] == "强制" and not x["tool_correct"]["strict"]
             and x["escalate_correct"]["strict"]]

    summary = {
        "version": VERSION, "set": args.set, "n": len(detail),
        "groups": {"tool_self_call": g_tool, "det_escalate": g_esc,
                   "det_override": g_ovr, "big_only": g_big, "small_only": g_sml},
        "cost_ratio": {
            "det_vs_big": round(g_esc["per_row_cost"] / g_big["per_row_cost"], 4) if g_big["per_row_cost"] else None,
            "tool_vs_big": round(g_tool["per_row_cost"] / g_big["per_row_cost"], 4) if g_big["per_row_cost"] else None,
            "big_per_row": g_big["per_row_cost"],
        },
        "sources": sources, "by_trap": by_trap,
        "errors_tool_route": err, "errors_det_route": det_err,
        "override_damaged": {"n": len(damaged), "n_raw": len(damaged_raw),
                             "ids": [d["id"] for d in damaged], "rows": damaged},
        "det_saved": {"n": len(saved), "ids": saved},
    }

    out_json = OUT_DIR / ("确定性触发_%s.json" % out_tag)
    out_json.write_text(json.dumps({"summary": summary, "detail": detail},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    with open(RAW_DIR / ("det_trigger_%s.csv" % out_tag), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "trap", "slice", "gold", "verdict", "source", "picked",
                    "tool_ok", "det_ok", "ovr_ok", "big_ok", "n_candidates"])
        for x in detail:
            w.writerow([x["id"], x["trap"], x["slice"], x["gold"],
                        x["gate"]["verdict"], x["source"],
                        "|".join("%s=%s" % (c["op"], c["value"]) for c in x["gate"]["picked"]),
                        x["tool_correct"]["strict"], x["escalate_correct"]["strict"],
                        x["override_correct"]["strict"], x["big_correct"]["strict"],
                        x["gate"]["n_candidates"]])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("wrote", out_json)


if __name__ == "__main__":
    sys.exit(main() or 0)
