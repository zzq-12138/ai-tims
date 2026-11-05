#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
问题二关系判别集构造（300 对）：duplicate 90 / variant 90 / conflict 80 / unrelated 40。

要点：
- conflict 定向构造：同一现象 + 不同根因（如 E102 供料器 vs 吸嘴），文本相似度需落在
  0.85–0.95。脚本先造候选，用 BGE-M3 实测余弦，逐对挑选落入区间的变体（共享上下文 0/1/2 句），
  并输出实际分布；若本机无 sentence-transformers，回退字符 n-gram 估计并明确标注 mode=approx。
- 标签不写进标注文件：annotation_relation_v1.csv 的 relation 列为空，真值只写 _gold_draft。
- 全部合成语料，不含真实企业信息。

用法：
  /home/dev/venvs/bge/bin/python scripts/annotation/gen_relation_pairs.py
  python3 scripts/annotation/gen_relation_pairs.py --embed hash      # 无依赖回退
"""
import argparse
import csv
import json
import math
import os
import random
import re
from collections import Counter, defaultdict

DEVICES = ["贴片机", "AOI检测机", "涂布机", "贴合机", "蚀刻机"]
CONTEXT = [
    "设备型号：{model}；产线：2 号线；工艺段：{topic}。",
    "本知识由设备维修班组整理，适用于常规量产条件，异常处置需挂牌上锁。",
    "历史同类记录：近 3 个月出现 2 次，均在换型后首件阶段。",
]

SYN = [
    ("导致", "引起"), ("检查", "排查"), ("复测", "复检"), ("更换", "换新"),
    ("偏移", "偏位"), ("异常", "不正常"), ("确认", "核实"), ("处理", "处置"),
    ("间歇", "断续"), ("要求", "标准为"), ("实测", "现场测量"),
]


def sc(device, topic, model, code, symptom, cause, alt, evidence, m1, m2, verify, cond):
    return dict(device=device, topic=topic, model=model, code=code, symptom=symptom,
                cause=cause, alt=alt, evidence=evidence, m1=m1, m2=m2,
                verify=verify, cond=cond)


def load_scenarios():
    """复用 gen_seed_1000.py 的 50 条设备-故障主题表。"""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen_seed_1000.py")
    spec = importlib.util.spec_from_file_location("gen_seed", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SCEN


def kn_text(s, cause=None, measures=None):
    cause = cause or s["cause"]
    ms = measures or [s["m1"], s["m2"]]
    return (f"现象：{s['symptom']}。\n原因：{cause}。\n"
            f"处理：{'；'.join(ms)}。\n验证：{s['verify']}。")


def paraphrase(text, rnd):
    out = text
    for a, b in SYN:
        if a in out and rnd.random() < 0.7:
            out = out.replace(a, b, 1)
    # 调整语序：把「验证」段提前
    lines = out.split("\n")
    if len(lines) >= 4 and rnd.random() < 0.5:
        out = "\n".join([lines[0], lines[3], lines[1], lines[2]])
    return out


def char_ngrams(text, n=3):
    t = re.sub(r"\s+", "", text)
    return Counter(t[i:i + n] for i in range(max(1, len(t) - n + 1)))


def hash_cos(a, b):
    va, vb = char_ngrams(a), char_ngrams(b)
    dot = sum(v * vb.get(k, 0) for k, v in va.items())
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


CACHE_PATH = "/tmp/tims_embed_cache.pkl"


class Embedder:
    def __init__(self, mode):
        self.mode = mode
        self.model = None
        self.cache = {}
        if os.path.exists(CACHE_PATH):
            try:
                import pickle
                with open(CACHE_PATH, "rb") as f:
                    self.cache = pickle.load(f)
                print(f"[embed] 复用缓存 {len(self.cache)} 条", flush=True)
            except Exception:
                self.cache = {}
        if mode == "bge":
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer("BAAI/bge-m3", device="cpu")
                self.model.max_seq_length = 512
            except Exception as e:  # 回退，不静默
                print(f"[embed] BGE 加载失败（{e}），回退近似模式", flush=True)
                self.mode = "approx"

    def encode_many(self, texts):
        if self.model is None:
            return None
        import numpy as np
        todo = [t for t in dict.fromkeys(texts) if t not in self.cache]
        if todo:
            print(f"[embed] 待编码新文本 {len(todo)} 条（缓存命中 {len(texts) - len(todo)}）", flush=True)
            vecs = self.model.encode(todo, normalize_embeddings=True, batch_size=32,
                                     show_progress_bar=len(todo) > 200)
            for t, v in zip(todo, vecs):
                self.cache[t] = v
            import pickle
            with open(CACHE_PATH, "wb") as f:
                pickle.dump(self.cache, f)
        return np.array([self.cache[t] for t in texts])

    def sim(self, a, b):
        if self.model is None:
            return hash_cos(a, b)
        import numpy as np
        v = self.encode_many([a, b])
        return float(np.dot(v[0], v[1]))

    def sims(self, pairs):
        if self.model is None:
            return [hash_cos(a, b) for a, b in pairs]
        import numpy as np
        texts = [x for p in pairs for x in p]
        v = self.encode_many(texts)
        v = v.reshape(len(pairs), 2, -1)
        return [float(np.dot(v[i][0], v[i][1])) for i in range(len(pairs))]


def build_duplicates(scen, rnd, n=90):
    out = []
    for i in range(n):
        s = scen[i % len(scen)]
        a = kn_text(s)
        b = paraphrase(a, rnd)
        if i % 3 == 0:
            b = b.replace("现象：", "故障现象：").replace("处理：", "处置过程：")
        out.append((a, b, s["device"], f"dup-{i + 1:03d}"))
    return out


def build_variants(scen, rnd, n=90):
    out = []
    by_dev = defaultdict(list)
    for s in scen:
        by_dev[s["device"]].append(s)
    for i in range(n):
        s = scen[i % len(scen)]
        peers = [x for x in by_dev[s["device"]] if x is not s]
        other = peers[i % len(peers)]
        a = kn_text(s)
        # 同设备相近故障族，但措施与条件不同（变体：不合并，建 variant 边）
        b = (f"现象：{s['symptom']}。\n原因：{other['cause']}。\n"
             f"处理：{other['m1']}。\n验证：{other['verify']}。\n"
             f"适用条件：{other['cond'][0][1]}。")
        out.append((a, b, s["device"], f"var-{i + 1:03d}"))
    return out


def build_unrelated(scen, rnd, n=40):
    out = []
    for i in range(n):
        a_s = scen[i % len(scen)]
        cands = [x for x in scen if x["device"] != a_s["device"]]
        b_s = cands[(i * 7 + 3) % len(cands)]
        out.append((kn_text(a_s), kn_text(b_s), f"{a_s['device']}->{b_s['device']}",
                    f"unr-{i + 1:03d}"))
    return out


def conflict_candidates(scen):
    """同设备、同现象、不同根因的候选对（含 3 种共享上下文变体）。"""
    cands = []
    by_dev = defaultdict(list)
    for s in scen:
        by_dev[s["device"]].append(s)
    for dev, lst in by_dev.items():
        for i, a in enumerate(lst):
            for j, b in enumerate(lst):
                if i == j:
                    continue
                for k in range(3):
                    ctx = "\n".join(CONTEXT[x].format(model=a["model"], topic=a["topic"])
                                    for x in range(k))
                    ta = kn_text(a) + (("\n" + ctx) if ctx else "")
                    tb = kn_text(b, cause=b["cause"]) + (("\n" + ctx) if ctx else "")
                    # 保证现象一致
                    tb = tb.replace("现象：" + b["symptom"], "现象：" + a["symptom"])
                    cands.append(dict(dev=dev, a=a, b=b, k=k, text_a=ta, text_b=tb))
    return cands


def build_conflicts(scen, emb, n=80):
    cands = conflict_candidates(scen)
    # 粗排预筛：字符 n-gram 相似度成本极低，每个（设备, 现象）保留 top 8 再送 BGE 精算，
    # 否则 1350 条候选在 CPU 上要编码 1500+ 条文本。
    for c in cands:
        c["pre"] = hash_cos(c["text_a"], c["text_b"])
    grouped = defaultdict(list)
    for c in cands:
        grouped[(c["dev"], c["a"]["topic"])].append(c)
    shortlist = []
    for key in sorted(grouped):
        shortlist.extend(sorted(grouped[key], key=lambda x: -x["pre"])[:8])
    print(f"[conflict] 候选 {len(cands)} 条 -> 粗排保留 {len(shortlist)} 条送 BGE 精算", flush=True)
    cos = emb.sims([(c["text_a"], c["text_b"]) for c in shortlist])
    for c, v in zip(shortlist, cos):
        c["cos"] = v
    in_band = sorted([c for c in shortlist if 0.85 <= c["cos"] <= 0.95],
                     key=lambda x: -x["cos"])
    print(f"[conflict] BGE 精算后落入 0.85–0.95 区间: {len(in_band)} 条", flush=True)

    used = Counter()
    picked, by_dev = [], defaultdict(list)
    for c in in_band:
        by_dev[c["dev"]].append(c)
    # 每（设备, 现象）最多 2 对，按设备轮转取高分；加 progressed 守卫，避免配额卡死空转
    while len(picked) < n:
        progressed = False
        for d in DEVICES:
            for c in by_dev[d]:
                if used[(c["dev"], c["a"]["topic"])] >= 2:
                    continue
                picked.append(c)
                used[(c["dev"], c["a"]["topic"])] += 1
                by_dev[d].remove(c)
                progressed = True
                break
            if len(picked) >= n:
                break
        if not progressed:
            break
    # 区间内不足 80 对时按最接近 0.90 补足，并在真值/统计里标记 band=False
    if len(picked) < n:
        rest = [c for c in shortlist if c not in picked]
        rest.sort(key=lambda x: abs(x["cos"] - 0.90))
        picked.extend(rest[:n - len(picked)])
    picked = picked[:n]
    for c in picked:
        c["band"] = 0.85 <= c["cos"] <= 0.95
    out = [(c["text_a"], c["text_b"], c["dev"], f"con-{i + 1:03d}") for i, c in enumerate(picked)]
    print(f"[conflict] 选定 {len(picked)} 对，区间内 {sum(c['band'] for c in picked)} 对", flush=True)
    return out, picked, shortlist, len(cands)


def dist(vals):
    if not vals:
        return {}
    v = sorted(vals)
    def q(p):
        return round(v[min(len(v) - 1, int(p * (len(v) - 1)))], 4)
    return dict(n=len(v), min=round(v[0], 4), p25=q(.25), median=q(.5),
                p75=q(.75), max=round(v[-1], 4), mean=round(sum(v) / len(v), 4))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="docs/paper/问题二")
    ap.add_argument("--seed", type=int, default=20261106)
    ap.add_argument("--embed", choices=["bge", "hash"], default="bge")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    rnd = random.Random(args.seed)
    scen = load_scenarios()
    emb = Embedder(args.embed)

    dups = build_duplicates(scen, rnd, 90)
    vars_ = build_variants(scen, rnd, 90)
    cons, con_picked, con_pool, n_cand = build_conflicts(scen, emb, 80)
    unrs = build_unrelated(scen, rnd, 40)
    con_cos = [c["cos"] for c in con_picked]
    con_meta = {f"con-{i + 1:03d}": dict(cos=round(c["cos"], 4), shared_context_lines=c["k"],
                                        in_band=bool(c["band"]))
                for i, c in enumerate(con_picked)}

    rows, gold = [], []
    for tag, group, rel in (("dup", dups, "duplicate"), ("var", vars_, "variant"),
                            ("con", cons, "conflict"), ("unr", unrs, "unrelated")):
        for i, (a, b, dev, sid) in enumerate(group):
            pid = f"P-{rel[:3].upper()}-{i + 1:03d}"
            hint = {
                "duplicate": "先看两者是否同设备、同现象、同根因，再看条件是否等价。",
                "variant": "注意措施与适用条件是否不同；同因不同措施不应合并。",
                "conflict": "注意两条的现象是否相同而结论是否互斥，且条件是否重叠。",
                "unrelated": "先确认设备与工序是否相同，再判断是否存在共享根因。",
            }[rel]
            rows.append(dict(pair_id=pid, text_a=a, text_b=b, evidence_hint=hint,
                             relation="", confidence="", condition_overlap="",
                             evidence="", uncertain=""))
            gold.append(dict(pair_id=pid, relation=rel, source_group=sid, device=dev,
                             **con_meta.get(sid, {})))

    rnd.shuffle(rows)
    with open(os.path.join(args.out_dir, "annotation_relation_v1.csv"), "w",
              encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(args.out_dir, "_gold_relation_draft.jsonl"), "w",
              encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    # 各关系类型相似度分布（供论文报告）
    stats = dict(mode=emb.mode, counts={r: len([g for g in gold if g["relation"] == r])
                                        for r in ("duplicate", "variant", "conflict", "unrelated")},
                 conflict_band=dict(low=0.85, high=0.95, **dist(con_cos)),
                 conflict_in_band=sum(1 for c in con_picked if c["band"]),
                 conflict_out_of_band=sum(1 for c in con_picked if not c["band"]),
                 conflict_candidate_pool=n_cand,
                 conflict_encoded=len(con_pool),
                 conflict_candidate_dist=dist([c["cos"] for c in con_pool]),
                 conflict_per_device={d: sum(1 for c in con_picked if c["dev"] == d)
                                      for d in DEVICES})
    for rel, group in (("duplicate", dups), ("variant", vars_), ("unrelated", unrs)):
        vals = emb.sims([(a, b) for a, b, _, _ in group[:30]])
        stats[f"{rel}_sample_dist"] = dist(vals)
    with open(os.path.join(args.out_dir, "_relation_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
