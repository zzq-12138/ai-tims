#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建知识库 310 条数据集（10 类设备 × 31 主题）。

输入：docs/paper/问题二/_kb_seed_snapshot.jsonl（现有 53 条 PUBLISHED 快照）
输出：docs/paper/问题二/kb_310.csv
      docs/paper/问题二/kb_310_stats.json
      docs/paper/问题二/kb_310_clusters.json

不连数据库、不依赖第三方库，可重复执行。CSV 即入库单一事实源。
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from kb_common import (DEVICE_PARAMS, DEFAULT_DISCRIMINATION, check_safety,
                       render_content, render_prevention, render_steps,
                       render_verification)
from data import pm, aoi, coat, lam, etch, reflow, mes, spi, wave, xray

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(ROOT, "docs", "paper", "问题二")
SNAPSHOT = os.path.join(OUT_DIR, "_kb_seed_snapshot.jsonl")

DEVICES = [pm, aoi, coat, lam, etch, reflow, mes, spi, wave, xray]

# 原文缺少“原因/预防”的种子，按设备机理补写（不改变原有处置动作）
SEED_FILL = {
    2117518330221625345: {
        "cause": "热电偶漂移或炉温曲线参数设置错误，叠加风道积尘导致热风循环不足，实际炉温高于设定值",
        "disc": "先比对炉温测试仪与设备显示值：偏差 >2℃ 查热电偶与补偿导线；一致则查温区参数与风机风道。",
    },
    2117984477438107650: {
        "cause": "交换机上行端口丢包与客户端缓存队列积压，报工请求超时后被重试，造成超时告警与重复提交",
        "disc": "先看网关超时率与链路错包率：链路异常查网络；链路正常则查服务端慢 SQL 与缓存水位。",
    },
    2117918536058552322: {
        "cause": "3D 光源散热风道积尘导致结温升高，光源亮度基准漂移，高度重建偏差增大",
        "disc": "先测光源温度与亮度基准：结温 >45℃ 或亮度 <初始 85% 查散热与光源；正常则查标定与算法。",
    },
}

SECTION_RE = re.compile(
    r"(故障现象|可能原因|可能的原因|根本原因|原因|处理步骤|解决步骤|排查步骤|处理|预防措施|预防|关键要点|验证结果)[:：]")
MARK_RE = re.compile(r"【[^】]*】")


def parse_seed(content):
    text = MARK_RE.sub("\n", content or "")
    text = text.replace("\\n", "\n")
    pieces = SECTION_RE.split(text)
    sections = {}
    for i in range(1, len(pieces) - 1, 2):
        key = pieces[i]
        val = pieces[i + 1].strip(" \n；;")
        if val:
            sections.setdefault(key, val)
    symptom = sections.get("故障现象", "")
    cause = sections.get("可能原因") or sections.get("可能的原因") or sections.get("根本原因") or sections.get("原因", "")
    steps = (sections.get("处理步骤") or sections.get("解决步骤")
             or sections.get("排查步骤") or sections.get("处理") or sections.get("关键要点", ""))
    prevention = sections.get("预防措施") or sections.get("预防", "")
    return {"symptom": symptom, "cause": cause, "steps": steps, "prevention": prevention}


def split_steps(steps_text):
    """把原文步骤拆成列表，保留原有动作。"""
    if not steps_text:
        return []
    t = steps_text.replace("\n", " ")
    parts = re.split(r"(?:^|[；;])\s*(?:\d+[).、]|[①-⑩])", t)
    items = [p.strip(" ；;。") for p in parts if p and len(p.strip(" ；;。")) >= 4]
    if len(items) <= 1:
        items = [p.strip() for p in re.split(r"[；;]", t) if len(p.strip()) >= 4]
    return items[:6]


def clean_title(title):
    return re.sub(r"^(e2e|E2E)[-_ ]*", "", title).strip()


def main():
    seeds = {}
    with open(SNAPSHOT, encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                seeds[int(row["id"])] = row

    out_rows = []
    clusters_out = []
    used_seed_ids = set()
    next_new_id = 3100000000000000001

    for mod in DEVICES:
        dev = mod.DEVICE
        name = dev["name"]
        params = DEVICE_PARAMS[name]
        entries = dev["entries"]
        assert len(entries) == 31, "%s 条目数=%d，应为 31" % (name, len(entries))

        by_key = {}
        for e in entries:
            e = dict(e)
            e["device"] = name
            e["category_id"] = dev["category_id"]
            e["params"] = params
            if "seed_id" in e:
                sid = int(e["seed_id"])
                used_seed_ids.add(sid)
                snap = seeds[sid]
                parsed = parse_seed(snap["content"])
                fill = SEED_FILL.get(sid, {})
                e["title"] = clean_title(snap["title"])
                e["symptom"] = fill.get("symptom") or parsed["symptom"] or (e["title"] + "的典型现象")
                e["cause"] = fill.get("cause") or parsed["cause"] or (e["title"] + "对应部件的机理失效")
                e["disc"] = fill.get("disc") or DEFAULT_DISCRIMINATION.format(**e)
                steps = split_steps(parsed["steps"])
                if steps:
                    e["steps"] = steps
                e["prevention"] = parsed["prevention"] or ""
                e["source_id"] = sid
            else:
                e["source_id"] = None
                e.setdefault("disc", DEFAULT_DISCRIMINATION.format(**e))

            # 来源标注
            tier = e.get("tier", "SYNTHETIC")
            assert tier in ("SEED", "HANDBOOK", "SYNTHETIC"), tier
            if e["source_id"]:
                tier = "SEED"
            e["tier"] = tier
            if tier == "SEED":
                e["source_ref"] = "原库记录 ID %s（原文保留，补写验证结果与适用条件）" % e["source_id"]
            elif tier == "HANDBOOK":
                e["source_ref"] = "公开标准/设备手册通用条款改写（未逐条核对版本）"
            else:
                e["source_ref"] = "模板化合成（设备机理 + 通用工艺窗口），无真实工单来源"
            by_key[e["key"]] = e

        # 成组关系
        sim_groups = [c for c in dev["clusters"] if c["type"] == "same_symptom_diff_cause"]
        sic_groups = [c for c in dev["clusters"] if c["type"] == "same_cause_diff_symptom"]
        assert len(sim_groups) == 5 and len(sic_groups) == 5, name
        assert sorted(len(c["members"]) for c in sim_groups) == [2, 2, 3, 3, 3], name
        assert sorted(len(c["members"]) for c in sic_groups) == [2, 2, 3, 3, 3], name

        clustered = set()
        for c in dev["clusters"]:
            members = c["members"]
            for k in members:
                assert k in by_key, "%s 缺少成员 %s" % (name, k)
                assert k not in clustered, "%s 成员 %s 重复成组" % (name, k)
                clustered.add(k)
                e = by_key[k]
                e["cluster_key"] = c["key"]
                e["cluster_type"] = c["type"]
                if c["type"] == "same_symptom_diff_cause":
                    e["symptom"] = c["symptom"]
                else:
                    e["cause"] = c["cause"]
            clusters_out.append({
                "cluster_key": c["key"],
                "cluster_type": c["type"],
                "device_type": name,
                "shared_symptom": c.get("symptom", ""),
                "shared_cause": c.get("cause", ""),
                "members": members,
                "member_titles": [by_key[k]["title"] for k in members],
            })

        # 渲染
        for e in entries:
            e = by_key[e["key"]]
            assert e["key"] in clustered or len(clustered) == 26, e["key"]
            e.setdefault("cluster_key", "")
            e.setdefault("cluster_type", "")
            e["steps_text"] = render_steps(e)
            e["prevention"] = render_prevention(e)
            e["verification"] = render_verification(e)
            e["content"] = render_content(e, params)
            e["summary"] = ("%s：%s。以 %s 复测（%s）确认修复。" % (
                e["title"], e["cause"].rstrip("。"), e["metric"], e["spec"]))[:200]
            e["tags"] = [name, e["subsystem"], "tier:" + e["tier"]]
            if e["cluster_key"]:
                e["tags"].append("cluster:" + e["cluster_key"])
            e["tags"].append("theme:" + e["theme"])
            if not e["source_id"]:
                e["source_id"] = next_new_id
                next_new_id += 1
            out_rows.append(e)

        # 每条设备的主题号唯一
        themes = [e["theme"] for e in entries]
        assert len(set(themes)) == 31, "%s 主题重复" % name

    # ---------- 校验 ----------
    assert len(used_seed_ids) == 53, "种子使用数=%d" % len(used_seed_ids)
    assert len(out_rows) == 310, len(out_rows)
    keys = [r["key"] for r in out_rows]
    assert len(set(keys)) == 310
    titles = [(r["device"], r["title"]) for r in out_rows]
    assert len(set(titles)) == 310, "同设备标题重复"
    assert len({r["source_id"] for r in out_rows}) == 310, "ID 重复"

    fields = ["symptom", "cause", "disc", "steps_text", "prevention",
              "verification", "conditions" if False else "content", "tier", "source_ref"]
    for r in out_rows:
        for f in ["symptom", "cause", "disc", "steps_text", "prevention", "verification", "content", "tier"]:
            assert str(r.get(f, "")).strip(), "%s 字段 %s 为空" % (r["key"], f)
        assert r["content"].count("适用条件：") == 1
        assert "适用机型：" in r["content"] and "软件/固件：" in r["content"]
        assert "来料/工艺批次：" in r["content"] and "工况：" in r["content"]
        assert 250 <= len(r["content"]) <= 900, "%s 内容长度=%d" % (r["key"], len(r["content"]))
        hits = check_safety(r["content"] + r["title"])
        assert not hits, "%s 命中禁用词：%s" % (r["key"], hits)

    sim_count = len([c for c in clusters_out if c["cluster_type"] == "same_symptom_diff_cause"])
    sic_count = len([c for c in clusters_out if c["cluster_type"] == "same_cause_diff_symptom"])
    assert sim_count >= 40 and sic_count >= 40, (sim_count, sic_count)

    # ---------- 输出 CSV ----------
    csv_path = os.path.join(OUT_DIR, "kb_310.csv")
    cols = ["kb_key", "source_id", "device_type", "subsystem", "theme", "title",
            "symptom", "root_cause", "discrimination", "steps", "prevention",
            "verification", "conditions", "source_tier", "source_ref",
            "cluster_key", "cluster_type", "tags", "summary", "category_id", "content"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in out_rows:
            w.writerow({
                "kb_key": r["key"],
                "source_id": r["source_id"],
                "device_type": r["device"],
                "subsystem": r["subsystem"],
                "theme": r["theme"],
                "title": r["title"],
                "symptom": r["symptom"],
                "root_cause": r["cause"],
                "discrimination": r["disc"],
                "steps": r["steps_text"],
                "prevention": r["prevention"],
                "verification": r["verification"],
                "conditions": r["content"].split("适用条件：", 1)[1].strip(),
                "source_tier": r["tier"],
                "source_ref": r["source_ref"],
                "cluster_key": r["cluster_key"],
                "cluster_type": r["cluster_type"],
                "tags": json.dumps(r["tags"], ensure_ascii=False),
                "summary": r["summary"],
                "category_id": r["category_id"],
                "content": r["content"],
            })

    # ---------- 统计 ----------
    by_device = {}
    by_subsystem = {}
    by_tier = {}
    for r in out_rows:
        by_device[r["device"]] = by_device.get(r["device"], 0) + 1
        by_subsystem[r["subsystem"]] = by_subsystem.get(r["subsystem"], 0) + 1
        by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
    lens = [len(r["content"]) for r in out_rows]
    stats = {
        "total": len(out_rows),
        "device_distribution": by_device,
        "subsystem_distribution": by_subsystem,
        "source_tier_distribution": by_tier,
        "field_non_empty_rate": {
            "symptom": 1.0, "root_cause": 1.0, "discrimination": 1.0,
            "steps": 1.0, "prevention": 1.0, "verification": 1.0,
            "conditions": 1.0, "source_tier": 1.0, "source_ref": 1.0,
        },
        "content_length": {"min": min(lens), "max": max(lens),
                           "avg": round(sum(lens) / len(lens), 1)},
        "clusters": {
            "same_symptom_diff_cause_groups": sim_count,
            "same_cause_diff_symptom_groups": sic_count,
            "clustered_entries": len([r for r in out_rows if r["cluster_key"]]),
            "standalone_entries": len([r for r in out_rows if not r["cluster_key"]]),
            "sim_group_sizes": sorted([len(c["members"]) for c in clusters_out
                                       if c["cluster_type"] == "same_symptom_diff_cause"]),
            "sic_group_sizes": sorted([len(c["members"]) for c in clusters_out
                                       if c["cluster_type"] == "same_cause_diff_symptom"]),
        },
    }

    with open(os.path.join(OUT_DIR, "kb_310_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "kb_310_clusters.json"), "w", encoding="utf-8") as f:
        json.dump(clusters_out, f, ensure_ascii=False, indent=2)

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("\nCSV:", csv_path)


if __name__ == "__main__":
    main()
