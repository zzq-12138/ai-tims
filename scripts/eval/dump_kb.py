#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 PUBLISHED 知识清单（阈值评估的负例校验底稿）。

用法: python3 dump_kb.py --out /tmp/kb_dump.json
"""
import argparse
import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8103"
TEST = ("[角色矩阵]", "[合并取舍E2E]")


def get(path, params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)["data"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/kb_dump.json")
    args = ap.parse_args()

    recs, page = [], 1
    while True:
        d = get("/api/kb/knowledge/page", {"current": page, "size": 100, "status": "PUBLISHED"})
        recs += d["records"]
        if len(recs) >= d["total"] or not d["records"]:
            break
        page += 1

    keep = [r for r in recs if not any(str(r.get("title", "") or "").strip().startswith(t) for t in TEST)]
    keep.sort(key=lambda r: (r.get("applyDeviceType") or "未标注", r["title"]))
    print("PUBLISHED总:", len(recs), "剔除测试条目后:", len(keep))

    out = []
    for r in keep:
        c = (r.get("content") or "").replace("\n", " / ")
        out.append({"id": str(r["id"]), "device": r.get("applyDeviceType"),
                    "title": r["title"], "tags": r.get("tags"),
                    "summary": r.get("summary"), "content": c[:260]})
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("写出:", args.out, len(out), "条")


if __name__ == "__main__":
    main()
