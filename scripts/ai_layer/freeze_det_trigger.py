#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结 det-trigger：把规则、阈值、枚举口径与源码哈希写进快照。

冻结范围：det_trigger.py（数字抽取、算子枚举、三档判定、覆盖选择）。
不在冻结范围：det_trigger_eval.py（测量仪器）、tool_calc_eval.py、bare_eval.py。
冻结后不得修改 det_trigger.py；若确需修改，必须升版本号并重做 Holdout。
快照文件名由 det_trigger.VERSION 推导（det-trigger-v2 → det_trigger_v2_freeze.json）。

用法（仓库根目录）：
  python3 scripts/ai_layer/freeze_det_trigger.py            # 写快照
  python3 scripts/ai_layer/freeze_det_trigger.py --verify   # 校验源码哈希未变
  python3 scripts/ai_layer/freeze_det_trigger.py --verify --out docs/paper/ai应用层/det_trigger_v1_freeze.json
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import det_trigger as dt  # noqa: E402

DEFAULT_OUT = ROOT / "docs" / "paper" / "ai应用层" / (
    "det_trigger_%s_freeze.json" % dt.VERSION.replace("det-trigger-", "").replace("-", "_"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    out = Path(args.out)
    src_sha = sha(HERE / "det_trigger.py")
    if args.verify:
        old = json.loads(out.read_text(encoding="utf-8"))
        ok = old["det_trigger_sha256"] == src_sha
        print(json.dumps({"freeze": str(out), "version": old.get("version"),
                          "frozen_sha256": old["det_trigger_sha256"],
                          "current_sha256": src_sha, "unchanged": ok},
                         ensure_ascii=False, indent=2))
        return 0 if ok else 1

    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    freeze = {
        "version": dt.VERSION,
        "frozen_at": now,
        "frozen_scope": "det_trigger.py：数字抽取 + 7 算子枚举 + 三档判定 + 覆盖选择",
        "not_in_scope": ["det_trigger_eval.py", "tool_calc_eval.py", "bare_eval.py"],
        "tol": dt.TOL,
        "limits": {"max_src_numbers": dt.MAX_SRC_NUMBERS,
                   "max_candidates": dt.MAX_CANDIDATES,
                   "max_stage1": dt.MAX_STAGE1},
        "ops": ["difference", "delta_percent", "pct_of", "count_over",
                "count_in_range", "ratio", "average"],
        "ops_impl": "直接复用 tool_calc.run_calculation，不另写算术",
        "enumeration_rules": [
            "rank1 带标签数字对（上月/本月、上周/这周、从…调到、原来/现在、计划/实际、下限/上限、上批/这批）："
            "两两枚举 difference / delta_percent / pct_of / ratio",
            "rank2 数值列表（≥4 个数、以、，,和 连接）：average；配合阈值枚举 count_over 与其补集；"
            "配合区间枚举 count_in_range 与其补集；并给出对应的 count/n*100 占比与补集占比",
            "rank3 全部数字两两组合：同上四个算子",
            "rank2 二段复算（正向）：rank≤2 的中间结果（前 40 个）当基数、题面数字当现值，"
            "做 difference / delta_percent / pct_of",
            "rank2 二段复算（反向，v2 新增）：题面数字当基数、中间结果当现值，"
            "做 difference / delta_percent / pct_of；对应「比上一批的 N 个多了百分之几」"
            "（基数在题面、现值是计数结果）这一方向",
            "题面出现「成」时，为每个 delta_percent（正反两向）追加 ×0.1 的成数变体",
            "所有结果按 (op, 四位小数) 去重；候选上限 4000",
        ],
        "judge_rules": [
            "答案中的数字若能在题面/资料原文找到（±0.06）→ 视为事实性回答，accept",
            "答案中的数字若能被候选集解释（±0.06）→ accept（recomputed）",
            "有数字既非原文也非候选，且候选集不完备 → uncomputable（只升级，不覆盖）",
            "有数字既非原文也非候选，且候选集为空 → uncomputable（升级）",
            "有数字既非原文也非候选，且候选集完备 → conflict（v2 只升级；不覆盖）",
        ],
        "incompleteness_rule": (
            "题面每条 CUE_RULES 线索对应的算子族，若在候选集中为空，则判为候选集不完备；"
            "不完备时不给出覆盖值（picked=[]），误覆盖恒为 0"),
        "cue_rules": [[p, list(ops), label] for p, ops, label in dt.CUE_RULES],
        "threshold_patterns": dt.THRESH_PATTERNS,
        "range_patterns": dt.RANGE_PATTERNS,
        "pair_patterns": [[p, label] for p, label in dt.PAIR_PATTERNS],
        "det_trigger_sha256": src_sha,
        "tool_calc_sha256": sha(HERE / "tool_calc.py"),
        "escalation": "glm-5.3-flash；与「全大模型」组同一调用口径（temperature 0.3、max_tokens 8192），"
                      "费用与延迟按该次调用实际用量计",
        "protocol": "冻结之后才生成 Holdout-4；Holdout-4 只跑一次；不回改任何规则；"
                    "机械故障可修脚本重跑，但须注明「工程故障，非口径修改」",
        "change_basis": (
            "两项改动均来自 Holdout-3 的机制分析，不来自逐条结果：(A) 候选集缺口=二段复算缺"
            "「题面数当基数、中间结果当现值」方向，证据是 3 条正确答案被判 conflict 且其复算值"
            "在候选集中 0 命中；(B) 覆盖必须要求候选集完备，否则等于用不完整候选集去改可能"
            "正确的答案，证据是 3 条误覆盖（H3-074/075/080）。未使用 Holdout-3 的任何单条结果"
            "做阈值/线索/模式的增删。"),
    }
    out.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(out), "version": dt.VERSION, "frozen_at": now,
                      "sha256": src_sha}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main() or 0)
