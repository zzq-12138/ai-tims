import json
import sys

sys.path.insert(0, "/tmp")
from score_eval import GOLD, parse_json, same  # noqa: E402

S1 = {json.loads(l)["id"]: json.loads(l) for l in open("/tmp/pred_s1_base.jsonl", encoding="utf-8")}
S3 = {json.loads(l)["id"]: json.loads(l) for l in open("/tmp/pred_s3_lora.jsonl", encoding="utf-8")}
try:
    S2 = {json.loads(l)["id"]: json.loads(l) for l in open("/tmp/pred_s2_rules.jsonl", encoding="utf-8")}
except FileNotFoundError:
    S2 = None

GROUPS = [("S1", S1)]
if S2:
    GROUPS.append(("S2", S2))
GROUPS.append(("S3", S3))

for tag, M in GROUPS:
    print("===", tag)
    for st in ["normal", "excluded", "no_final"]:
        ids = [r for r in GOLD if GOLD[r]["structure"] == st]
        ok = 0
        empty_root = 0
        flag_ok = 0
        for rid in ids:
            o, _ = parse_json(M[rid]["raw"])
            o = o or {}
            g = GOLD[rid]["gold"]
            ok += int(same(o.get("root_cause", ""), g.get("root_cause") or "")[0])
            empty_root += int(not str(o.get("root_cause", "")).strip())
            gf = int(g.get("has_final_root_cause") or 0)
            flag_ok += int(int(o.get("has_final_root_cause") or 0) == gf)
        print("  %-9s n=%3d root_match=%.1f%% empty_root=%.1f%% has_final_acc=%.1f%%" % (
            st, len(ids), ok / len(ids) * 100, empty_root / len(ids) * 100, flag_ok / len(ids) * 100))

# excluded 子集：S3 条目是否逐字命中
print("=== excluded 80 条 ===")
for tag, M in GROUPS:
    hit = tot = 0
    for rid, g in GOLD.items():
        gp = g["gold"].get("excluded_hypotheses") or []
        if not gp:
            continue
        o, _ = parse_json(M[rid]["raw"])
        pp = (o or {}).get("excluded_hypotheses") or []
        tot += len(gp)
        for x in gp:
            t = x.get("hypothesis", "")
            if any(same(t, p.get("hypothesis", "") if isinstance(p, dict) else p)[0] for p in pp):
                hit += 1
    print(tag, "excluded item recall %.1f%% (%d/%d)" % (hit / tot * 100, hit, tot))
