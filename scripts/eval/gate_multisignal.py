#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多信号门控原型：绝对阈值 / 分数间隔(margin) / margin+根因一致性。

核心约束（用户明确要求）：
  所有阈值与权重只在 54/55 快照上选定，原样应用到 310 库，不在 310 上二次调参。
  这正是本实验要回答的问题——门控参数是否可移植。

数据来源（全部为已归档产物，不调用在线服务、不改代码、不重跑检索）：
  54/55 快照：docs/paper/评测/_gate_raw.json（VECTOR 段，门控关闭）
             docs/paper/评测/_leave_out_after_cleanup.tsv（leave-gold-out）
  310 库：    docs/paper/评测/_kb310/_collect.json
             docs/paper/评测/_kb310/_lg_out.tsv
  知识条目：  docs/paper/问题二/kb_310.csv（显式 root_cause/symptom/device）
             docs/paper/问题二/_kb_seed_snapshot.jsonl（旧条目兜底，从 content 解析）

三个配置：
  thr         push if top1 >= T
  margin      push if top1 - top2 >= M
  margin_cons push if (top1 - top2 >= M) and (cons >= C)
  cons = w_sym * Jaccard(query, 候选 symptom)
       + w_rc  * Jaccard(query, 候选 root_cause)
       + w_dev * (query 设备 == 候选设备)
  另附 z（top1 相对同批 5 条候选的 z-score）作为 margin 的替代量，供对照。

用法（VM）：
  python3 scripts/eval/gate_multisignal.py tune     # 在 54 上调参，写 _multisignal_54.json
  python3 scripts/eval/gate_multisignal.py apply    # 冻结参数应用到 310，写 _multisignal_310.json
  python3 scripts/eval/gate_multisignal.py report   # 合并输出 _multisignal_metrics.json
  python3 scripts/eval/gate_multisignal.py all
"""
import argparse
import csv
import json
import os
import re
from statistics import mean, pstdev

REPO = os.environ.get("REPO", "/home/dev/ai-tims")
DOCS = os.path.join(REPO, "docs/paper/评测")
OUT = os.path.join(DOCS, "_multisignal")
TARGET_ERR = 0.10          # 工作点约束：错误推送率 <= 10%
MIN_PUSH = 30              # 防止在极低推送量上“0 错误”造成的假最优
PARTS_N = 100


# ---------------------------------------------------------------- 文本相似
def bigrams(s):
    s = "".join(str(s or "").split())
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else ({s} if s else set())


def jac(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / len(A | B) if (A | B) else 0.0


def extract_hypothesis(q):
    """负例 N1 的 query 形如「…，我怀疑是真空泵膜片老化导致的，怎么处理」，
    其中显式给出了工单侧的根因假设；正例 query 一般没有。"""
    m = re.search(r"我怀疑(?:是|为)?(.{2,40}?)(?:导致|引起|造成|，|,|。|怎么|如何|请|$)", str(q or ""))
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------- 知识条目元数据
def parse_seed_content(content):
    """旧条目 content 形如：故障现象：… 可能原因：… 处理步骤：…，解析出现象与根因。"""
    c = str(content or "")
    sym = rc = ""
    m = re.search(r"故障现象[：:]\s*(.*?)(?:可能原因|处理步骤|【合并来源】|$)", c, re.S)
    if m:
        sym = m.group(1).strip()
    m = re.search(r"可能原因[（(]?根因[）)]?[：:]\s*(.*?)(?:处理步骤|【合并来源】|$)", c, re.S)
    if not m:
        m = re.search(r"可能原因[：:]\s*(.*?)(?:处理步骤|【合并来源】|$)", c, re.S)
    if m:
        rc = m.group(1).strip()
    return sym, rc


def load_meta():
    meta = {}
    path = os.path.join(REPO, "docs/paper/问题二/kb_310.csv")
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            sid = str(r.get("source_id") or "").strip()
            if not sid:
                continue
            meta[sid] = {
                "title": r.get("title") or "",
                "symptom": r.get("symptom") or "",
                "root": r.get("root_cause") or "",
                "device": r.get("device_type") or "",
                "src": "kb310",
            }
    seed = os.path.join(REPO, "docs/paper/问题二/_kb_seed_snapshot.jsonl")
    if os.path.exists(seed):
        with open(seed, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                sid = str(rec.get("id"))
                if sid in meta:
                    continue
                sym, rc = parse_seed_content(rec.get("content"))
                meta[sid] = {"title": rec.get("title") or "", "symptom": sym,
                             "root": rc, "device": rec.get("device") or "",
                             "src": "seed_snapshot"}
    return meta


def device_names(meta):
    ds = {m["device"] for m in meta.values() if m.get("device")}
    # 长名优先，避免 "AOI" 抢先命中 "AOI检测机"
    return sorted(ds, key=len, reverse=True)


def infer_dev(q, names, fallback=None):
    for d in names:
        if d and d in q:
            return d
    return fallback


# ---------------------------------------------------------------- 样本装载
def load_eval():
    rows = []
    with open(os.path.join(DOCS, "eval_set.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({"query": r["query"], "device": r.get("deviceType") or "",
                         "expected": [x for x in (r.get("expectedIds") or "").split(";") if x]})
    return rows


def mk_sample(lib, part, key, query, device, scores, ids, ok, extra=None):
    d = {"lib": lib, "part": part, "key": key, "query": query, "device": device,
         "scores": scores, "ids": ids, "push_ok": bool(ok)}
    if extra:
        d.update(extra)
    return d


def parse_top5(s):
    out = []
    for tok in str(s or "").split(","):
        tok = tok.strip()
        if ":" in tok:
            i, v = tok.rsplit(":", 1)
            try:
                out.append((float(v), str(i)))
            except ValueError:
                pass
    return out


def read_tsv_lg(path, lib, ev, names, accept=("OK",)):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("idx") or line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 7 or p[2] not in accept:
                continue
            sc = parse_top5(p[6])
            if not sc:
                continue
            idx = int(p[0])
            q = ev[idx - 1]["query"] if 0 < idx <= len(ev) else ""
            dev = ev[idx - 1]["device"] if 0 < idx <= len(ev) else ""
            rows.append(mk_sample(lib, "LG", "LG-%03d" % idx, q,
                                  infer_dev(q, names, dev), [x[0] for x in sc],
                                  [x[1] for x in sc], False, {"tier_status": p[2]}))
    return rows


def load_54(meta, names):
    raw = json.load(open(os.path.join(DOCS, "_gate_raw.json"), encoding="utf-8"))["VECTOR"]
    out = []
    for rec in raw["P"]:
        sc = [(float(i["vectorScore"]), str(i["id"])) for i in rec["items"]
              if i.get("vectorScore") is not None]
        if not sc:
            continue
        gold = [str(x) for x in rec.get("expected") or []]
        out.append(mk_sample("54", "P", rec["key"], rec["query"],
                             infer_dev(rec["query"], names), [x[0] for x in sc],
                             [x[1] for x in sc], sc[0][1] in gold, {"gold": gold}))
    for rec in raw["N"]:
        sc = [(float(i["vectorScore"]), str(i["id"])) for i in rec["items"]
              if i.get("vectorScore") is not None]
        if not sc:
            continue
        usable = [str(x) for x in rec.get("usable") or []]
        ok = rec.get("cls") == "missing_noise" and sc[0][1] in usable
        out.append(mk_sample("54", "N", rec["key"], rec["query"],
                             infer_dev(rec["query"], names), [x[0] for x in sc],
                             [x[1] for x in sc], ok,
                             {"cls": rec.get("cls"), "usable": usable}))
    lg = read_tsv_lg(os.path.join(DOCS, "_leave_out_after_cleanup.tsv"),
                     "54", load_eval(), names)
    out.extend(lg)
    return out


def load_310(meta, names):
    col = json.load(open(os.path.join(DOCS, "_kb310/_collect.json"), encoding="utf-8"))
    out = []
    for rec in col["P"]:
        sc = [(float(i["vectorScore"]), str(i["id"])) for i in rec["items"]
              if i.get("vectorScore") is not None]
        if not sc:
            continue
        gold = [str(x) for x in rec.get("expected") or []]
        out.append(mk_sample("310", "P", rec["key"], rec["query"],
                             infer_dev(rec["query"], names), [x[0] for x in sc],
                             [x[1] for x in sc], sc[0][1] in gold, {"gold": gold}))
    for rec in col["N"]:
        sc = [(float(i["vectorScore"]), str(i["id"])) for i in rec["items"]
              if i.get("vectorScore") is not None]
        if not sc:
            continue
        usable = [str(x) for x in rec.get("usable") or []]
        ok = rec.get("cls") == "missing_noise" and sc[0][1] in usable
        out.append(mk_sample("310", "N", rec["key"], rec["query"],
                             infer_dev(rec["query"], names), [x[0] for x in sc],
                             [x[1] for x in sc], ok,
                             {"cls": rec.get("cls"), "usable": usable}))
    lg = read_tsv_lg(os.path.join(DOCS, "_kb310/_lg_out.tsv"),
                     "310", load_eval(), names, accept=("OK", "RESTORE_FAILED"))
    out.extend(lg)
    return out


def valid_neg_keys(lib):
    """310 扩库后失效的负例（根因关键词已被库覆盖），用于第二口径。"""
    if lib == "54":
        return None
    p = os.path.join(DOCS, "_kb310/_negcheck.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    return {x["id"] for x in d["rows"] if x["covered_in_310"]}


# ---------------------------------------------------------------- 信号
def signal_values(s, meta, w):
    sc = s["scores"]
    s1 = sc[0]
    s2 = sc[1] if len(sc) > 1 else 0.0
    margin = s1 - s2
    mu, sd = mean(sc), pstdev(sc)
    z = (s1 - mu) / sd if sd > 1e-9 else 0.0
    top1 = s["ids"][0]
    m = meta.get(top1)
    hypo = extract_hypothesis(s["query"])
    if m:
        dev = 1.0 if (s["device"] and m["device"] and s["device"] == m["device"]) else 0.0
        if hypo:
            # 工单里显式给了根因假设：以「假设 vs 候选根因」为主；
            # 假设与候选根因无交集时应判为不一致，不能靠设备/现象分把分数抬起来。
            cons = 0.8 * jac(hypo, m["root"]) + 0.2 * jac(s["query"], m["symptom"])
        else:
            cons = (w["sym"] * jac(s["query"], m["symptom"])
                    + w["rc"] * jac(s["query"], m["root"]) + w["dev"] * dev)
    else:
        cons = 0.0
    return {"s1": round(s1, 4), "margin": round(margin, 4),
            "rel": round(margin / s1, 4) if s1 > 1e-9 else 0.0,
            "z": round(z, 4),
            "cons": round(cons, 4), "meta": bool(m), "hypo": hypo}


def enrich(samples, meta, w):
    for s in samples:
        s["sig"] = signal_values(s, meta, w)
    return samples


# ---------------------------------------------------------------- 评测
def evaluate(samples, rule):
    pushed = [s for s in samples if rule(s)]
    errs = [s for s in pushed if not s["push_ok"]]
    pp = [s for s in pushed if s["part"] == "P"]
    pc = [s for s in pp if s["push_ok"]]
    nn = [s for s in pushed if s["part"] == "N"]
    lg = [s for s in pushed if s["part"] == "LG"]
    by_cls = {}
    for s in errs:
        k = s.get("cls") or s["part"]
        by_cls[k] = by_cls.get(k, 0) + 1
    return {
        "push": len(pushed), "err": len(errs),
        "err_rate": round(len(errs) / len(pushed), 4) if pushed else None,
        "coverage": round(len(pp) / PARTS_N, 4),
        "P_push": len(pp), "P_correct": len(pc), "P_err": len(pp) - len(pc),
        "N_push": len(nn), "N_err": len(nn) - sum(1 for s in nn if s["push_ok"]),
        "LG_push": len(lg), "err_by_cls": by_cls,
    }


def ok_point(r):
    return (r["err_rate"] is not None and r["err_rate"] <= TARGET_ERR
            and r["push"] >= MIN_PUSH)


def tune_thr(samples):
    best, curve = None, []
    for i in range(500, 951, 5):
        T = i / 1000.0
        r = evaluate(samples, lambda s, T=T: s["sig"]["s1"] >= T)
        curve.append({"param": T, **r})
        if ok_point(r) and (best is None or r["coverage"] > best["coverage"]):
            best = {"param": T, **r}
    return best, curve


def tune_margin(samples, key="margin", hi=301):
    best, curve = None, []
    for i in range(0, hi, 2):
        M = i / 1000.0
        r = evaluate(samples, lambda s, M=M: s["sig"][key] >= M)
        curve.append({"param": M, **r})
        if ok_point(r) and (best is None or r["coverage"] > best["coverage"]):
            best = {"param": M, **r}
    return best, curve


def tune_margin_cons(samples, key, thr, base_cov, budget=0.01):
    """在固定 margin/relmargin 门槛下选一致性门槛 C（54 上定）。
    规则：C 取满足「错误率<=10% 且覆盖相对纯 margin 的损失 <= 1pp」的最大值，
    即一致性过滤必须是“近乎免费”的；若 C=0 已是最优则如实记录不生效。"""
    curve, best = [], None
    for j in range(0, 91):
        C = j / 100.0
        r = evaluate(samples, lambda s, C=C: (s["sig"][key] >= thr
                                              and s["sig"]["cons"] >= C))
        curve.append({"param": [thr, C], **r})
        if (r["err_rate"] is not None and r["err_rate"] <= TARGET_ERR
                and r["coverage"] >= base_cov - budget):
            best = {"param": [thr, C], **r}
    if best is None:
        best = curve[0]
    return best, curve


def sweep_grid(samples, key, values, cons=None):
    """固定一致性门槛 cons 后扫描单信号，用于画「错误率 vs 覆盖率」曲线。
    cons=None 表示纯单信号。"""
    out = []
    for v in values:
        if cons is None:
            r = evaluate(samples, lambda s, v=v: s["sig"][key] >= v)
        else:
            r = evaluate(samples, lambda s, v=v, C=cons: (s["sig"][key] >= v
                                                          and s["sig"]["cons"] >= C))
        out.append({"param": v, **r})
    return out


def fallback_point(curve):
    """无可用工作点时，取错误率最低（同错误率取覆盖最高）的点，仅作参考。"""
    if not curve:
        return None
    return sorted(curve, key=lambda r: (r["err_rate"] if r["err_rate"] is not None else 9,
                                        -r["coverage"]))[0]


def safe_point(curve):
    """54 上的“零错误”保守工作点：err=0 且推送量>=MIN_PUSH 中覆盖最大者。
    这是可移植性的最强候选——如果连零错误点迁到 310 都失效，说明信号本身不可移植。"""
    c = [r for r in curve if r["err_rate"] == 0 and r["push"] >= MIN_PUSH]
    return max(c, key=lambda r: r["coverage"]) if c else None


WEIGHT_GRID = [{"sym": a, "rc": b, "dev": c}
               for a in (0.4, 0.5, 0.6) for b in (0.2, 0.3, 0.4) for c in (0.1, 0.2)]


def norm(w):
    t = w["sym"] + w["rc"] + w["dev"]
    return {k: round(v / t, 4) for k, v in w.items()}


def distribution(samples):
    out = {}
    for part in ("P", "N", "LG"):
        xs = [s for s in samples if s["part"] == part]
        def med(k):
            v = sorted(x["sig"][k] for x in xs)
            return round((v[len(v) // 2] + v[(len(v) - 1) // 2]) / 2, 4) if v else None
        out[part] = {"n": len(xs),
                     "s1_median": med("s1"), "margin_median": med("margin"),
                     "z_median": med("z"), "cons_median": med("cons"),
                     "meta_missing": sum(1 for x in xs if not x["sig"]["meta"])}
    return out


def audit(samples, lib):
    return {"lib": lib, "n": len(samples),
            "P": sum(1 for s in samples if s["part"] == "P"),
            "N": sum(1 for s in samples if s["part"] == "N"),
            "LG": sum(1 for s in samples if s["part"] == "LG"),
            "top1_meta_missing": sum(1 for s in samples if not s["sig"]["meta"])}


# ---------------------------------------------------------------- 主流程
def run_tune():
    os.makedirs(OUT, exist_ok=True)
    meta = load_meta()
    names = device_names(meta)
    s54 = load_54(meta, names)

    # 先定 margin 门槛（与权重无关），再在固定 M 下为每组权重选一致性门槛 C
    default_w = norm({"sym": 0.5, "rc": 0.3, "dev": 0.2})
    enrich(s54, meta, default_w)
    thr_best, thr_curve = tune_thr(s54)
    mar_best, mar_curve = tune_margin(s54, "margin")
    z_best, z_curve = tune_margin(s54, "z")
    if mar_best is None:
        mar_best = fallback_point(mar_curve)
    M = mar_best["param"]

    weight_results = []
    for w0 in WEIGHT_GRID:
        w = norm(w0)
        enrich(s54, meta, w)
        c_best, c_curve = tune_margin_cons(s54, "margin", M, mar_best["coverage"])
        weight_results.append({"w": w, "best": c_best, "curve": c_curve})
    # 54 覆盖最大者胜出；覆盖相同取 C 更大（过滤更强）者
    weight_results.sort(key=lambda x: (-x["best"]["coverage"], -x["best"]["param"][1]))
    chosen = weight_results[0]["w"]
    mc_best, mc_curve = weight_results[0]["best"], weight_results[0]["curve"]

    enrich(s54, meta, chosen)
    b075 = evaluate(s54, lambda s: s["sig"]["s1"] >= 0.75)
    # 重算一次（权重变了，cons 阈值保持 54 上选定的值）
    mc_best, mc_curve = tune_margin_cons(s54, "margin", M, mar_best["coverage"])
    rel_best, rel_curve = tune_margin(s54, "rel")
    relc_best = None
    if rel_best:
        relc_best, _ = tune_margin_cons(s54, "rel", rel_best["param"], rel_best["coverage"])

    thr_safe = safe_point(thr_curve)
    tc_safe = (tune_margin_cons(s54, "s1", thr_safe["param"], thr_safe["coverage"])[0]
               if thr_safe else None)
    tc_best = (tune_margin_cons(s54, "s1", thr_best["param"], thr_best["coverage"])[0]
               if thr_best else None)
    mar_safe = safe_point(mar_curve)
    rel_safe = safe_point(rel_curve)
    mc_safe = (tune_margin_cons(s54, "margin", mar_safe["param"], mar_safe["coverage"])[0]
               if mar_safe else None)
    relc_safe = (tune_margin_cons(s54, "rel", rel_safe["param"], rel_safe["coverage"])[0]
                 if rel_safe else None)

    # 三配置曲线：纯阈值 / margin / margin+cons；另加「阈值+cons」作对照。
    # cons 门槛全部用上面 54 上冻结的值，曲线只扫单信号，不引入新自由度。
    c_mc = mc_best["param"][1]
    c_tc = tc_safe["param"][1] if tc_safe else None
    curve_mc = sweep_grid(s54, "margin", [i / 1000.0 for i in range(0, 301, 2)], c_mc)
    curve_tc = (sweep_grid(s54, "s1", [i / 1000.0 for i in range(500, 951, 5)], c_tc)
                if c_tc is not None else [])

    out = {
        "lib": "54", "target_err": TARGET_ERR, "min_push": MIN_PUSH,
        "weights": chosen,
        "weights_grid": [{"w": x["w"], "best": x["best"]} for x in weight_results],
        "audit": audit(s54, "54"),
        "distribution": distribution(s54),
        "baseline_T075": b075,
        "thr": {"best": thr_best, "best_cons": tc_best, "safe": thr_safe,
                "safe_cons": tc_safe, "curve": thr_curve},
        "margin": {"best": mar_best, "safe": mar_safe, "curve": mar_curve},
        "rel": {"best": rel_best, "safe": rel_safe, "curve": rel_curve},
        "rel_cons": {"best": relc_best, "safe": relc_safe},
        "z": {"best": z_best, "fallback": fallback_point(z_curve), "curve": z_curve},
        "margin_cons": {"best": mc_best, "safe": mc_safe, "curve": mc_curve,
                        "curve_over_margin": curve_mc},
        "thr_cons": {"safe": tc_safe, "best": tc_best, "curve_over_thr": curve_tc},
    }
    json.dump(out, open(os.path.join(OUT, "_multisignal_54.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("[54] weights", chosen)
    for k in ("thr", "margin", "margin_cons", "rel", "rel_cons"):
        print("  %-12s best=%s" % (k, out[k]["best"]))
    print("  z best=%s | fallback=%s" % (z_best, out["z"]["fallback"]))
    print("  baseline T=0.75:", b075)
    print("  dist:", json.dumps(out["distribution"], ensure_ascii=False))
    return out


def run_apply():
    p54 = os.path.join(OUT, "_multisignal_54.json")
    if not os.path.exists(p54):
        raise SystemExit("请先跑 tune")
    tuned = json.load(open(p54, encoding="utf-8"))
    w = tuned["weights"]
    meta = load_meta()
    names = device_names(meta)
    s310 = load_310(meta, names)
    enrich(s310, meta, w)
    bad = valid_neg_keys("310") or set()

    T = tuned["thr"]["best"]["param"]
    M = tuned["margin"]["best"]["param"]
    Z = tuned["z"]["best"]["param"] if tuned["z"]["best"] else None
    MC = tuned["margin_cons"]["best"]["param"]
    R = tuned["rel"]["best"]["param"] if tuned["rel"]["best"] else None
    RC = tuned["rel_cons"]["best"]["param"] if tuned["rel_cons"]["best"] else None

    rules = {
        "thr": lambda s: s["sig"]["s1"] >= T,
        "margin": lambda s: s["sig"]["margin"] >= M,
        "margin_cons": lambda s: (s["sig"]["margin"] >= MC[0] and s["sig"]["cons"] >= MC[1]),
        "baseline_T075": lambda s: s["sig"]["s1"] >= 0.75,
    }
    if Z is not None:
        rules["z"] = lambda s: s["sig"]["z"] >= Z
    if R is not None:
        rules["rel"] = lambda s: s["sig"]["rel"] >= R
    if RC is not None:
        rules["rel_cons"] = lambda s: (s["sig"]["rel"] >= RC[0] and s["sig"]["cons"] >= RC[1])

    # 54 零错误保守点（可移植性的最强候选）
    ts = tuned["thr"].get("safe")
    if ts:
        rules["thr_safe"] = lambda s, T=ts["param"]: s["sig"]["s1"] >= T
    tcs = tuned["thr"].get("safe_cons")
    if tcs:
        rules["thr_cons_safe"] = lambda s, P=tcs["param"]: (s["sig"]["s1"] >= P[0]
                                                            and s["sig"]["cons"] >= P[1])
    tcb = tuned["thr"].get("best_cons")
    if tcb:
        rules["thr_cons_best"] = lambda s, P=tcb["param"]: (s["sig"]["s1"] >= P[0]
                                                            and s["sig"]["cons"] >= P[1])
    ms = tuned["margin"].get("safe")
    if ms:
        rules["margin_safe"] = lambda s, M=ms["param"]: s["sig"]["margin"] >= M
    rs = tuned["rel"].get("safe")
    if rs:
        rules["rel_safe"] = lambda s, R=rs["param"]: s["sig"]["rel"] >= R
    mcs = tuned["margin_cons"].get("safe")
    if mcs:
        rules["margin_cons_safe"] = lambda s, P=mcs["param"]: (s["sig"]["margin"] >= P[0]
                                                               and s["sig"]["cons"] >= P[1])
    rcs = tuned["rel_cons"].get("safe")
    if rcs:
        rules["rel_cons_safe"] = lambda s, P=rcs["param"]: (s["sig"]["rel"] >= P[0]
                                                           and s["sig"]["cons"] >= P[1])
    res = {}
    for k, rule in rules.items():
        r = evaluate(s310, rule)
        r_valid = evaluate([s for s in s310 if not (s["part"] == "N" and s["key"] in bad)], rule)
        res[k] = {"all": r, "valid_neg": r_valid}

    # 曲线：固定权重后扫描；仅用于展示 310 上的形状，不用于选参
    _, thr_curve = tune_thr(s310)
    _, mar_curve = tune_margin(s310, "margin")
    c_mc = MC[1]
    c_tc = tcs["param"][1] if tcs else None
    curve_mc_310 = sweep_grid(s310, "margin", [i / 1000.0 for i in range(0, 301, 2)], c_mc)
    curve_tc_310 = (sweep_grid(s310, "s1", [i / 1000.0 for i in range(500, 951, 5)], c_tc)
                    if c_tc is not None else [])
    out = {"lib": "310", "weights": w, "frozen": {"T": T, "M": M, "Z": Z, "MC": MC},
           "audit": audit(s310, "310"), "distribution": distribution(s310),
           "excluded_neg": sorted(bad), "results": res,
           "curve_thr_310": thr_curve, "curve_margin_310": mar_curve,
           "curve_margin_cons_310": curve_mc_310, "curve_thr_cons_310": curve_tc_310}
    json.dump(out, open(os.path.join(OUT, "_multisignal_310.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("[310] frozen", out["frozen"], "| 失效负例", len(bad))
    for k, v in res.items():
        print("  %-16s all: cov %.1f%% err %s (%s) | valid-neg: cov %.1f%% err %s"
              % (k, 100 * v["all"]["coverage"], v["all"]["err_rate"],
                 v["all"]["err_by_cls"],
                 100 * v["valid_neg"]["coverage"], v["valid_neg"]["err_rate"]))
    return out


def run_report():
    a = json.load(open(os.path.join(OUT, "_multisignal_54.json"), encoding="utf-8"))
    b = json.load(open(os.path.join(OUT, "_multisignal_310.json"), encoding="utf-8"))
    merged = {"tune_54": a, "apply_310": b}
    json.dump(merged, open(os.path.join(OUT, "_multisignal_metrics.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("[ok] ->", os.path.join(OUT, "_multisignal_metrics.json"))


def _at(curve, p):
    c = min(curve, key=lambda r: abs(r["param"] - p))
    return c


def run_show():
    a = json.load(open(os.path.join(OUT, "_multisignal_54.json"), encoding="utf-8"))
    b = json.load(open(os.path.join(OUT, "_multisignal_310.json"), encoding="utf-8"))
    print("== 54 阈值曲线（绝对 top1）==")
    for p in (0.70, 0.72, 0.75, 0.775, 0.78, 0.80, 0.82):
        c = _at(a["thr"]["curve"], p)
        print("  T=%.3f cov %.1f%% push %d err %.1f%%"
              % (c["param"], 100 * c["coverage"], c["push"], 100 * (c["err_rate"] or 0)))
    print("== 54 margin 曲线 ==")
    for p in (0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.086, 0.10):
        c = _at(a["margin"]["curve"], p)
        print("  M=%.3f cov %.1f%% push %d err %.1f%%"
              % (c["param"], 100 * c["coverage"], c["push"], 100 * (c["err_rate"] or 0)))
    print("== 54 margin+cons 曲线（C 冻结）==")
    for p in (0.02, 0.04, 0.05, 0.06, 0.07, 0.086, 0.10):
        c = _at(a["margin_cons"]["curve_over_margin"], p)
        print("  M=%.3f cov %.1f%% push %d err %.1f%%"
              % (c["param"], 100 * c["coverage"], c["push"], 100 * (c["err_rate"] or 0)))
    print("== 54 阈值+cons 曲线（C 冻结）==")
    for p in (0.70, 0.75, 0.775, 0.78, 0.80, 0.82):
        c = _at(a["thr_cons"]["curve_over_thr"], p)
        print("  T=%.3f cov %.1f%% push %d err %.1f%%"
              % (c["param"], 100 * c["coverage"], c["push"], 100 * (c["err_rate"] or 0)))
    print("== 310 阈值曲线（冻结点用于对照，曲线仅展示形状）==")
    for p in (0.70, 0.75, 0.775, 0.78, 0.80, 0.82, 0.85):
        c = _at(b["curve_thr_310"], p)
        print("  T=%.3f cov %.1f%% push %d err %.1f%%"
              % (c["param"], 100 * c["coverage"], c["push"], 100 * (c["err_rate"] or 0)))
    print("== 310 margin 曲线 ==")
    for p in (0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.086):
        c = _at(b["curve_margin_310"], p)
        print("  M=%.3f cov %.1f%% push %d err %.1f%%"
              % (c["param"], 100 * c["coverage"], c["push"], 100 * (c["err_rate"] or 0)))
    print("== 310 margin+cons 曲线（C 冻结）==")
    for p in (0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.086):
        c = _at(b["curve_margin_cons_310"], p)
        print("  M=%.3f cov %.1f%% push %d err %.1f%%"
              % (c["param"], 100 * c["coverage"], c["push"], 100 * (c["err_rate"] or 0)))
    print("== 310 阈值+cons 曲线（C 冻结）==")
    for p in (0.70, 0.75, 0.775, 0.78, 0.80, 0.82, 0.85):
        c = _at(b["curve_thr_cons_310"], p)
        print("  T=%.3f cov %.1f%% push %d err %.1f%%"
              % (c["param"], 100 * c["coverage"], c["push"], 100 * (c["err_rate"] or 0)))
    def oracle(curve, name):
        c = [r for r in curve if r["err_rate"] is not None and r["err_rate"] <= TARGET_ERR
             and r["push"] >= MIN_PUSH]
        if not c:
            print("  %s: 无 err<=10%% 的工作点" % name)
            return
        best = max(c, key=lambda r: r["coverage"])
        print("  %s 310-oracle: p=%.3f cov %.1f%% push %d err %.1f%%"
              % (name, best["param"], 100 * best["coverage"], best["push"],
                 100 * best["err_rate"]))
    print("== 310 上的“重新调参”上限（仅解释差距，不作为方案）==")
    oracle(b["curve_thr_310"], "thr")
    oracle(b["curve_margin_310"], "margin")
    print("== 310 信号分布 ==")
    print(" ", json.dumps(b["distribution"], ensure_ascii=False))
    print("== 54 工作点（best=错误率<=10%且覆盖最大；safe=零错误且覆盖最大）==")
    for k in ("thr", "margin", "rel", "margin_cons", "rel_cons"):
        print("  %-12s best=%s\n               safe=%s"
              % (k, a[k].get("best"), a[k].get("safe")))
    print("  thr.safe_cons=%s" % a["thr"].get("safe_cons"))
    print("  thr.best_cons=%s" % a["thr"].get("best_cons"))
    print("  weights=%s" % a.get("weights"))
    print("  audit54=%s audit310=%s" % (a.get("audit"), b.get("audit")))
    print("== 310 逐规则（含错误构成）==")
    for k, v in b["results"].items():
        x = v["all"]
        print("  %-16s cov %5.1f%% push %3d err %5.1f%% P %d/%d N %d/%d LG %d %s"
              % (k, 100 * x["coverage"], x["push"], 100 * (x["err_rate"] or 0),
                 x["P_push"], x["P_correct"], x["N_push"], x["N_err"], x["LG_push"],
                 x["err_by_cls"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tune", "apply", "report", "show", "all"])
    x = ap.parse_args()
    if x.cmd in ("tune", "all"):
        run_tune()
    if x.cmd in ("apply", "all"):
        run_apply()
    if x.cmd in ("report", "all"):
        run_report()
    if x.cmd == "show":
        run_show()
