#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 外部验证（只测不训）：外部工单集 → 五元组抽取评测。

数据不进训练、不进 KB；样本固定存 /tmp/ext-eval/。

子命令：
  build   三个外部集 → 统一评测格式 /tmp/ext-eval/eval_{dataset}.jsonl
  run     S1 零样本（glm-4-flash, temperature=0）逐条抽取
  score   与规则构造的 gold 比对，输出 metrics.json 与 markdown 片段

口径：外部集 gold 由「原文字段规则映射」构造（强/中），不是人工标注；
      指标只能称「与规则构造 gold 的一致性」，禁止写成人工标注一致率。
"""
import argparse
import csv
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXT = "/tmp/ext-eval"
KEY_PATH = "/home/dev/secrets/zhipu_api_key"
GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-4-flash"
INSTRUCTION = (
    "你是设备维修工单知识抽取器。请从工单文本中抽取维修知识，只输出一个 JSON 对象，字段："
    "symptom(现象)、symptom_evidence(现象原文依据)、root_cause(根因，没有则空串)、"
    "root_cause_evidence(根因依据)、measures(处理措施，字符串数组)、verification(验证结果)、"
    "verification_evidence(验证依据)、conditions(适用条件数组，元素为 {type,value}，"
    "type 取值 device_model/process_stage/material_or_batch/param_range/precondition)、"
    "excluded_hypotheses(被排除的假设数组，元素为 {hypothesis,evidence})、"
    "is_excluded_hypothesis(是否有排除假设，0/1)、unverified_hypotheses(未验证假设，数组)、"
    "has_final_root_cause(是否有最终根因，0/1)、uncertain(是否无法判断，0/1)。"
    "禁止编造文本中不存在的信息。"
)
FIELDS = ["symptom", "root_cause", "measures", "verification", "conditions", "excluded_hypotheses"]


# ---------------- build ----------------
def clean(s):
    s = str(s or "").replace("<br>", "; ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip().strip(";").strip()
    return s


def split_items(s):
    s = clean(s)
    parts = [p.strip(" -;\t'\"\u2019\u2018") for p in re.split(r"[;\n、]", s)]
    return [p for p in parts if len(p) >= 4]


def usable_measure(s):
    """过滤「待更换：」「已处理」这类占位状态，不作为措施 gold。"""
    s = clean(s)
    if len(s) < 4 or s.endswith(("：", ":")):
        return False
    return s not in {"待更换", "待处理", "已处理", "已恢复", "处理中", "已完成", "已解决",
                     "修复恢复", "修复", "恢复正常", "处理完成", "已修复", "恢复运行"}


def build(args=None):
    os.makedirs(EXT, exist_ok=True)
    info = {}

    # MaintNet：PROBLEM/ACTION 两列拼接为叙述文本（抽取=在叙述里定位现象与措施）
    mrows = [json.loads(l) for l in open(os.path.join(EXT, "maintnet_300.jsonl"), encoding="utf-8")]
    with open(os.path.join(EXT, "eval_maintnet.jsonl"), "w", encoding="utf-8") as f:
        for r in mrows:
            f.write(json.dumps({
                "id": r["id"], "dataset": "MaintNet", "lang": "en",
                "text": clean(r["problem"]) + "\n" + clean(r["action"]),
                "gold": {"symptom": clean(r["problem"]), "measures": [clean(r["action"])], "root_cause": ""},
                "strength": {"symptom": "强", "measures": "强", "root_cause": "不可得"},
            }, ensure_ascii=False) + "\n")
    info["MaintNet"] = {"n": len(mrows), "file": "maintnet_aviation.csv",
                        "subset_md5": md5(os.path.join(EXT, "maintnet_300.jsonl"))}

    # Fujitsu：Summary+Detailed = 叙述；Cause / 两级 Countermeasure = gold
    frows = list(csv.DictReader(open(os.path.join(EXT, "fujitsu.csv"), encoding="utf-8-sig")))
    with open(os.path.join(EXT, "eval_fujitsu.jsonl"), "w", encoding="utf-8") as f:
        for r in frows:
            meas = split_items(r["Immediate_Countermeasure"]) + split_items(r["Permanent_Countermeasure"])
            f.write(json.dumps({
                "id": r["Incident_ID"], "dataset": "Fujitsu", "lang": "en",
                "text": clean(r["Incident_Summary"]) + "\n" + clean(r["Detailed"]),
                "gold": {"symptom": clean(r["Incident_Summary"]),
                         "measures": meas, "root_cause": clean(r["Cause"])},
                "strength": {"symptom": "强", "measures": "强", "root_cause": "强"},
            }, ensure_ascii=False) + "\n")
    info["Fujitsu"] = {"n": len(frows), "file": "ManufacturingRCA_doc.csv",
                       "md5": md5(os.path.join(EXT, "fujitsu.csv"))}

    # 电梯：content 原文；method 优先（强），否则 resolution/note 规则拼接（中）
    erows = [json.loads(l) for l in open(os.path.join(EXT, "elevator_200.jsonl"), encoding="utf-8")]
    cnt = {"method": 0, "resolution": 0, "note": 0, "cause": 0, "none": 0}
    with open(os.path.join(EXT, "eval_elevator.jsonl"), "w", encoding="utf-8") as f:
        for r in erows:
            meas, ms = [], "不可得"
            if usable_measure(r.get("method")):
                meas, ms = split_items(r["method"]), "强"
                cnt["method"] += 1
            elif usable_measure(r.get("resolution")):
                meas, ms = split_items(r["resolution"]), "中"
                cnt["resolution"] += 1
            elif usable_measure(r.get("note")):
                meas, ms = split_items(r["note"]), "中"
                cnt["note"] += 1
            else:
                cnt["none"] += 1
            cause = clean(r.get("cause"))
            if cause:
                cnt["cause"] += 1
            f.write(json.dumps({
                "id": r["id"], "dataset": "Elevator", "lang": "zh",
                "text": clean(r["content"]),
                "gold": {"symptom": clean(r["content"]), "measures": meas, "root_cause": cause},
                "strength": {"symptom": "强", "measures": ms, "root_cause": "强" if cause else "不可得"},
            }, ensure_ascii=False) + "\n")
    info["Elevator"] = {"n": len(erows), "subset_md5": md5(os.path.join(EXT, "elevator_200.jsonl")), **cnt}

    json.dump(info, open(os.path.join(EXT, "build_info.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False, indent=1))


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------- run ----------------
_lock = threading.Lock()
USAGE = {"prompt": 0, "completion": 0, "ok": 0, "bad": 0}


def api_key():
    if os.environ.get("ZHIPU_API_KEY"):
        return os.environ["ZHIPU_API_KEY"].strip()
    return open(KEY_PATH, encoding="utf-8").read().strip()


def call(text, key, model=MODEL, retry=3):
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": INSTRUCTION},
                         {"role": "user", "content": "工单：\n" + text}]}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    for a in range(retry):
        req = urllib.request.Request(GLM_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + key)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                obj = json.loads(r.read().decode("utf-8"))
            c = obj["choices"][0]["message"]["content"]
            u = obj.get("usage") or {}
            i, j = c.find("{"), c.rfind("}")
            parsed = json.loads(c[i:j + 1]) if i >= 0 and j > i else None
            return {"_raw": c, "_json_ok": parsed is not None, "_parsed": parsed or {},
                    "_usage": [u.get("prompt_tokens", 0), u.get("completion_tokens", 0)]}
        except Exception as e:
            if a == retry - 1:
                return {"_error": str(e)[:200], "_json_ok": False, "_parsed": {},
                        "_usage": [0, 0]}
            time.sleep(2 + 2 * a)
    return {"_error": "unknown", "_json_ok": False, "_parsed": {}, "_usage": [0, 0]}


def norm_out(o):
    out = {}
    for f in FIELDS:
        v = o.get(f)
        if f == "measures":
            out[f] = [str(x).strip() for x in v] if isinstance(v, list) else ([str(v)] if v else [])
            out[f] = [x for x in out[f] if x]
        elif f in ("conditions", "excluded_hypotheses"):
            out[f] = v if isinstance(v, list) else []
        else:
            out[f] = "" if v is None else str(v).strip()
    out["_keys"] = [k for k in FIELDS if k in o]
    return out


def run(args):
    key = api_key()
    files = args.files or ["eval_maintnet.jsonl", "eval_fujitsu.jsonl", "eval_elevator.jsonl"]
    rows = []
    for fn in files:
        rows += [json.loads(l) for l in open(os.path.join(EXT, fn), encoding="utf-8")]
    out_path = os.path.join(EXT, "pred_%s.jsonl" % args.tag)
    done = set()
    if os.path.exists(out_path) and not args.fresh:
        for l in open(out_path, encoding="utf-8"):
            try:
                done.add(json.loads(l)["id"])
            except Exception:
                pass
    todo = [r for r in rows if r["id"] not in done]
    print(f"[run] 总 {len(rows)}，已完成 {len(done)}，本次 {len(todo)}，模型 {args.model} temp=0", flush=True)

    def one(r):
        p = call(r["text"], key, args.model)
        rec = dict(id=r["id"], dataset=r["dataset"], json_ok=p["_json_ok"],
                   pred=norm_out(p["_parsed"]), raw=p.get("_raw", ""), error=p.get("_error", ""))
        with _lock:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            USAGE["prompt"] += p["_usage"][0]
            USAGE["completion"] += p["_usage"][1]
            USAGE["ok" if p["_json_ok"] else "bad"] += 1
        return rec

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for n, _ in enumerate(ex.map(one, todo), 1):
            if n % 50 == 0:
                print(f"[run] {n}/{len(todo)} ok={USAGE['ok']} bad={USAGE['bad']} "
                      f"{time.time() - t0:.0f}s tok={USAGE['prompt'] + USAGE['completion']}", flush=True)
    print(f"[run] 完成 ok={USAGE['ok']} bad={USAGE['bad']} 用时 {time.time() - t0:.0f}s "
          f"prompt={USAGE['prompt']} completion={USAGE['completion']}", flush=True)


# ---------------- score ----------------
def bigrams(s):
    s = "".join(str(s).split())
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def soft(a, b):
    if not a or not b:
        return 0.0
    sa = "".join(str(a).split())
    sb = "".join(str(b).split())
    if sa in sb or sb in sa:
        return 1.0
    A, B = bigrams(a), bigrams(b)
    jac = len(A & B) / len(A | B)
    sm = SequenceMatcher(None, sa, sb).ratio()
    ta, tb = set(str(a).lower().split()), set(str(b).lower().split())
    wj = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return max(jac, sm, wj)


def list_metrics(gold, pred, thr=0.6):
    """measures：coverage(召回) / precision / F1（best-match）+ 关键词覆盖率（辅助）。"""
    g = [x for x in gold if str(x).strip()]
    p = [x for x in pred if str(x).strip()]
    if not g:
        return None
    hit_g = sum(1 for x in g if any(soft(x, y) >= thr for y in p))
    hit_p = sum(1 for y in p if any(soft(x, y) >= thr for x in g))
    rec = hit_g / len(g)
    pre = hit_p / len(p) if p else 0.0
    f1 = 2 * pre * rec / (pre + rec) if (pre + rec) else 0.0
    kg = sum(1 for x in g if any(kw_match(x, y) for y in p))
    kp = sum(1 for y in p if any(kw_match(x, y) for x in g))
    krec = kg / len(g)
    kpre = kp / len(p) if p else 0.0
    kf1 = 2 * kpre * krec / (kpre + krec) if (kpre + krec) else 0.0
    return rec, pre, f1, krec, kpre, kf1


STOP = set("the a an and or of to for with in on at is are was were be been by from as it its "
           "this that these those then than into during after before we i you".split())


def kw_match(g, p, thr=0.5):
    G = {w for w in re.findall(r"[a-z0-9]{4,}", str(g).lower()) if w not in STOP}
    P = {w for w in re.findall(r"[a-z0-9]{4,}", str(p).lower()) if w not in STOP}
    if not G:
        return soft(g, p) >= 0.6
    return len(G & P) / len(G) >= thr


def score(args):
    rows = {}
    for fn in ["eval_maintnet.jsonl", "eval_fujitsu.jsonl", "eval_elevator.jsonl"]:
        for l in open(os.path.join(EXT, fn), encoding="utf-8"):
            r = json.loads(l)
            rows[r["id"]] = r
    preds = [json.loads(l) for l in open(os.path.join(EXT, "pred_%s.jsonl" % args.tag), encoding="utf-8")]
    pred = {p["id"]: p for p in preds}

    res = {}
    for ds in ["MaintNet", "Fujitsu", "Elevator"]:
        ids = [i for i in rows if rows[i]["dataset"] == ds and i in pred]
        d = {"n": len(ids), "json_ok": sum(1 for i in ids if pred[i]["json_ok"]) / len(ids)}
        d["schema"] = sum(1 for i in ids if len(pred[i]["pred"]["_keys"]) == len(FIELDS)) / len(ids)
        d["core_nonempty"] = sum(1 for i in ids
                                 if pred[i]["pred"]["symptom"] and pred[i]["pred"]["measures"]) / len(ids)
        # symptom
        sym = [(rows[i]["gold"]["symptom"], pred[i]["pred"]["symptom"]) for i in ids
               if rows[i]["gold"]["symptom"]]
        d["symptom"] = {"n": len(sym),
                        "strict": sum(1 for a, b in sym if a.strip() == b.strip()) / len(sym),
                        "soft": sum(soft(a, b) for a, b in sym) / len(sym)}
        cjk = lambda s: bool(re.search(r"[\u4e00-\u9fff]", str(s)))
        d["lang_follow"] = sum(1 for i in ids
                               if cjk(rows[i]["gold"]["symptom"]) == cjk(pred[i]["pred"]["symptom"])) / len(ids)
        # measures
        ms, by_str = [], {}
        for i in ids:
            g = rows[i]["gold"]["measures"]
            if not g:
                continue
            m = list_metrics(g, pred[i]["pred"]["measures"])
            ms.append(m)
            by_str.setdefault(rows[i]["strength"]["measures"], []).append(m)
        d["measures"] = {"n": len(ms),
                         "hit1": sum(1 for x in ms if x[0] > 0) / len(ms),
                         "recall": sum(x[0] for x in ms) / len(ms),
                         "precision": sum(x[1] for x in ms) / len(ms),
                         "f1": sum(x[2] for x in ms) / len(ms),
                         "kw_recall": sum(x[3] for x in ms) / len(ms),
                         "kw_precision": sum(x[4] for x in ms) / len(ms),
                         "kw_f1": sum(x[5] for x in ms) / len(ms),
                         "by_strength": {k: {"n": len(v), "hit1": sum(1 for x in v if x[0] > 0) / len(v),
                                             "recall": sum(x[0] for x in v) / len(v),
                                             "precision": sum(x[1] for x in v) / len(v),
                                             "f1": sum(x[2] for x in v) / len(v),
                                             "kw_recall": sum(x[3] for x in v) / len(v),
                                             "kw_f1": sum(x[5] for x in v) / len(v)}
                                         for k, v in by_str.items()}}
        # root cause：gold 可能是「多条根因并列」，取任一命中（max），并保留整串口径
        rc = [(rows[i]["gold"]["root_cause"], pred[i]["pred"]["root_cause"]) for i in ids
              if rows[i]["gold"]["root_cause"]]
        d["root_cause"] = {"n": len(rc),
                           "any_soft": sum(max([soft(x, b) for x in (split_items(a) or [a])])
                                           for a, b in rc) / len(rc) if rc else None,
                           "whole_soft": sum(soft(a, b) for a, b in rc) / len(rc) if rc else None,
                           "strict": sum(1 for a, b in rc if a.strip() == b.strip()) / len(rc) if rc else None}
        res[ds] = d

    json.dump(res, open(os.path.join(EXT, "metrics_%s.json" % args.tag), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 失败样例：按「现象相似度 + 措施 F1」升序取前 5
    fails = {}
    for ds in ["MaintNet", "Fujitsu", "Elevator"]:
        ids = [i for i in rows if rows[i]["dataset"] == ds and i in pred]
        scored = []
        for i in ids:
            g, p = rows[i]["gold"], pred[i]["pred"]
            ss = soft(g["symptom"], p["symptom"]) if g["symptom"] else 0.0
            m = list_metrics(g["measures"], p["measures"]) if g["measures"] else None
            mf1 = m[2] if m else -1
            scored.append((ss + max(mf1, 0), i, ss, mf1))
        scored.sort()
        fails[ds] = [{"id": i, "symptom_soft": round(ss, 3),
                      "measures_f1": round(mf1, 3) if mf1 >= 0 else None,
                      "text": rows[i]["text"][:300],
                      "gold": rows[i]["gold"],
                      "pred": {"symptom": pred[i]["pred"]["symptom"],
                               "root_cause": pred[i]["pred"]["root_cause"],
                               "measures": pred[i]["pred"]["measures"]}}
                     for _, i, ss, mf1 in scored[:5]]
    json.dump(fails, open(os.path.join(EXT, "failures_%s.json" % args.tag), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))

    # markdown 片段
    L = ["| 数据集 | n | JSON 合法率 | 字段齐全率 | 核心字段非空率 | 现象语义一致率 | 措施 Recall | 措施 Precision | 措施 F1 | 根因语义一致率 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for ds, d in res.items():
        rc = d["root_cause"]["any_soft"]
        L.append("| %s | %d | %.1f%% | %.1f%% | %.1f%% | %.1f%% (n=%d) | %.1f%% (n=%d) | %.1f%% | %.1f%% | %s (n=%d) |"
                 % (ds, d["n"], d["json_ok"] * 100, d["schema"] * 100, d["core_nonempty"] * 100,
                    d["symptom"]["soft"] * 100, d["symptom"]["n"],
                    d["measures"]["recall"] * 100, d["measures"]["n"],
                    d["measures"]["precision"] * 100, d["measures"]["f1"] * 100,
                    ("%.1f%%" % (rc * 100)) if rc is not None else "—",
                    d["root_cause"]["n"]))
    open(os.path.join(EXT, "metrics_%s.md" % args.tag), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    r = sub.add_parser("run")
    r.add_argument("--workers", type=int, default=5)
    r.add_argument("--files", nargs="*", default=[])
    r.add_argument("--fresh", action="store_true")
    r.add_argument("--model", default=MODEL)
    r.add_argument("--tag", default="glm", help="输出文件名后缀，如 glm / glm53")
    s = sub.add_parser("score")
    s.add_argument("--tag", default="glm")
    a = ap.parse_args()
    {"build": build, "run": run, "score": score}[a.cmd](a)


if __name__ == "__main__":
    main()
