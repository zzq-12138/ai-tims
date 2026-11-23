#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen3 门控逐条 CSV 就地聚合（只读，无第三方依赖）。

用法：
  python3 门控切片复算_20261123.py /tmp/qwen3_eval/qwen3_out/qwen3_gate_scores.csv

输出：
  mode set thr n hit1 hit@1% pushed cover% err err%

口径：
  - 分数列 score 是该 query 的 top1 余弦；
  - pushed = score >= thr；
  - P：usable=true 表示 top1 命中 expectedIds；err = 推送中 usable=false 的条数；
  - LG：构造上 100% 不可用，err = pushed；
  - N：usable=true 仅 N4 命中原 gold；err = 推送中 usable=false 的条数；
  - hit1/hit@1% 仅 P 有意义，按全量 P 计算，不随阈值变化。
"""

import collections
import csv
import os
import sys

THRESHOLDS = (0.65, 0.70, 0.72, 0.75, 0.77)


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def truth(value):
    return str(value).strip().lower() in ("true", "1", "yes")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "qwen3_gate_scores.csv"
    if not os.path.exists(path):
        raise SystemExit("缺少文件: " + os.path.abspath(path))

    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    groups = collections.defaultdict(list)
    for row in rows:
        groups[(row.get("mode", ""), row.get("set", ""))].append(row)

    print("file=%s rows=%d modes=%s sets=%s" % (
        os.path.abspath(path),
        len(rows),
        ",".join(sorted(set(key[0] for key in groups))),
        ",".join(sorted(set(key[1] for key in groups))),
    ))
    print("%-8s %-3s %5s %4s %5s %7s %6s %7s %4s %6s" % (
        "mode", "set", "thr", "n", "hit1", "hit@1%", "pushed", "cover%", "err", "err%",
    ))

    for key in sorted(groups):
        mode, set_name = key
        subset = groups[key]
        total = len(subset)
        correct = sum(1 for row in subset if truth(row.get("correct_top1")))
        hit1 = str(correct) if set_name == "P" else "-"
        hit1_pct = ("%.1f" % (correct * 100.0 / total)) if (set_name == "P" and total) else "-"

        for threshold in THRESHOLDS:
            pushed = [
                row for row in subset
                if num(row.get("score")) is not None and num(row.get("score")) >= threshold
            ]
            errors = sum(1 for row in pushed if not truth(row.get("usable")))
            coverage = (len(pushed) * 100.0 / total) if total else 0.0
            error_rate = (errors * 100.0 / len(pushed)) if pushed else 0.0
            print("%-8s %-3s %5.2f %4d %5s %7s %6d %7.1f %4d %6.1f" % (
                mode, set_name, threshold, total, hit1, hit1_pct,
                len(pushed), coverage, errors, error_rate,
            ))


if __name__ == "__main__":
    main()
