#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽样打印 / 列表查看 kb_310.csv。

用法：
  python3 scripts/kb/sample_kb.py                 # 打印默认样例
  python3 scripts/kb/sample_kb.py --list          # 列出成组键
  python3 scripts/kb/sample_kb.py --device MES终端 # 列出该设备全部键
"""
import argparse
import csv

ap = argparse.ArgumentParser()
ap.add_argument("--csv", default="docs/paper/问题二/kb_310.csv")
ap.add_argument("--list", action="store_true")
ap.add_argument("--device", default=None)
ap.add_argument("keys", nargs="*")
args = ap.parse_args()

with open(args.csv, encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
index = {r["kb_key"]: r for r in rows}
print("total=%d" % len(rows))

if args.list:
    print(sorted({r["cluster_key"] for r in rows if r["cluster_key"]}))
    raise SystemExit(0)

if args.device:
    print([r["kb_key"] for r in rows if r["device_type"] == args.device])
    raise SystemExit(0)

for k in args.keys or ["PM-S01", "SIM-PM-01", "SIC-PM-01"]:
    r = index.get(k)
    if not r:
        print("缺失", k)
        continue
    print("=" * 70)
    print(k, "|", r["device_type"], "|", r["source_tier"], "|", r["cluster_type"], r["cluster_key"])
    print("标题:", r["title"])
    print("摘要:", r["summary"])
    print("-" * 70)
    print(r["content"])
