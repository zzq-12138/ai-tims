#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测集生成（M7）：基于 PUBLISHED 知识反推 100 条 query。

构成：
- 54 条 formal：按“设备+故障短语+处理意图”直接提问（覆盖全部知识点）；
- 46 条 hard：按车间口语/带噪声/缺失设备字段改写，且尽量不使用标题里的原故障词，
  改用“现象描述”（人工撰写的 SYMPTOM 词表），用于检验语义检索泛化能力。

用法: python3 gen_eval_set.py [--out docs/paper/评测/eval_set.csv] [--dry]
仅读取现有 HTTP 接口，不写库、不调用 LLM。
"""
import argparse
import csv
import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter, OrderedDict

BASE = os.environ.get("KB_BASE", "http://127.0.0.1:8103")
TEST_PAT = re.compile(r"^\[角色矩阵\]|^\[合并取舍E2E\]")
SUFFIXES = ["故障处理", "处理方法", "处理SOP", "处理", "故障排除", "故障", "维修", "修复", "SOP"]

# 故障短语 -> (口语现象描述, 是否可在“缺失设备字段”场景下唯一指向本知识)
SYMPTOM = {
    "报工接口超时": ("整点报工一直转圈，还重复生成记录", False),
    "3D光源亮度漂移": ("3D光源越用越暗，测出来的数值偏了", True),
    "程序调用错误": ("一跑检测程序就报错，调不起来", True),
    "传送轨道卡板": ("板子进到传送轨道就卡住不走", True),
    "废液排放报警": ("废液排不出去，一直报警", True),
    "压力不均": ("贴合时有的地方压得实、有的压不实", False),
    "辊筒磨损": ("辊筒表面磨秃了，贴出来有印痕", True),
    "定位标记识别": ("板上的定位标记认不出来，对不准", True),
    "温控异常": ("温度忽高忽低，控制不住", False),
    "送料偏斜": ("料送进来是歪的，走不正", True),
    "静电吸附不良": ("静电吸不住料，老是掉", True),
    "蚀刻速率偏差": ("刻出来的深度跟设定值对不上", True),
    "药水浓度异常": ("蚀刻药水浓度不对，刻出来偏", False),
    "喷嘴堵塞": ("喷头喷不出来，喷得很不均匀", True),
    "过蚀刻": ("刻过头了，线路都刻细了", True),
    "蚀刻不均": ("整板刻得深浅不一", True),
    "传送轮污染": ("传送轮上全是脏污，把板子弄脏了", True),
    "腔体温度漂移": ("腔体温度稳不住，老上下飘", True),
    "水洗残留": ("洗完板子上还有水渍和残留", True),
    "腔体压力异常": ("腔体压力上不去，老掉压", True),
    "贴合偏移": ("贴的位置整体偏了，对不齐", False),
    "脱胶": ("贴完胶片翘边、脱开", True),
    "材料褶皱": ("料贴上去起皱了", True),
    "气泡": ("贴完之后胶片里面鼓包", False),
    "算法阈值漂移": ("判定标准变了，良品也被判成不良", True),
    "通讯中断": ("跟上位机断联了，数据传不过去", True),
    "涂布厚度不均": ("涂出来厚薄不一样", False),
    "涂层气泡": ("涂层表面冒泡", False),
    "边缘漏涂": ("板子边上一圈没涂上", True),
    "张力波动": ("走料时松时紧，张力不稳", False),
    "烘干温度异常": ("烘干温度不对，板子烘不干", False),
    "涂布头堵塞": ("涂布头出料不顺，堵住了", True),
    "纠偏失灵": ("料跑偏了纠不回来", True),
    "背辊粘胶": ("背辊上粘了一层胶", True),
    "速度同步异常": ("速度跟线体不同步，忽快忽慢", True),
    "料卷接头断带": ("料卷接头那里断了", True),
    "抛料": ("元件到处乱飞，被甩掉了", True),
    "吸嘴堵塞": ("吸嘴吸不住元件，像是堵了", True),
    "贴装偏移": ("贴出来的位置整体偏", False),
    "供料器卡料": ("供料器卡住不出料", True),
    "元件视觉识别失败": ("相机认不出元件，识别不了", True),
    "贴装头撞击": ("贴装头撞到板子上了", True),
    "锡膏印刷偏移": ("锡膏印偏了位置", True),
    "元器件立碑": ("元件一端翘起来立着", True),
    "气路压力异常": ("气路压力不够，吸力弱", True),
    "误报率过高": ("总把好板判成坏的，误报太多", True),
    "漏检": ("有不良品没检出来", True),
    "图像模糊": ("拍出来的图像是糊的", True),
    "光源亮度衰减": ("光源明显变暗了", True),
    "条码识别失败": ("条码扫不出来", True),
    "过板卡板": ("过板的时候卡住了", True),
    "相机对焦异常": ("相机对不上焦", True),
    "炉温失控": ("炉温曲线失控，板子烤变色了", True),
}


def get(path, params=None):
    if params:
        path += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.load(r)


def fetch_published():
    recs, page = [], 1
    while True:
        d = get("/api/kb/knowledge/page", {"current": page, "size": 100, "status": "PUBLISHED"})["data"]
        recs += d["records"]
        if len(recs) >= d["total"] or not d["records"]:
            return recs
        page += 1


def fault_of(title, device):
    """从标题剥离设备名前缀与通用后缀，得到故障短语（只剥离一次前缀，避免误伤故障词）。"""
    t = title.strip()
    while t.startswith("e2e") and len(t) > 3:
        t = t[3:].strip()
    cands = sorted({device, device.replace("检测机", ""), device.replace("机", ""), "SPI", "AOI", "MES"} - {""},
                   key=len, reverse=True)
    for p in cands:
        if t.startswith(p) and len(t) - len(p) >= 4:
            t = t[len(p):].strip()
            break
    changed = True
    while changed:
        changed = False
        for s in SUFFIXES:
            if t.endswith(s) and len(t) > len(s):
                t = t[: -len(s)]
                changed = True
    return t


def colloquial(device, symptom, idx):
    forms = [
        "车间那台{d}，{s}，咋整啊",
        "{d}最近{s}，师傅们一般怎么处理",
    ]
    return forms[idx % len(forms)].format(d=device, s=symptom)


def noisy(device, symptom, idx):
    forms = [
        "{d}{s}！！！在线等，挺急的",
        "{d} {s}，有没有人遇到过，求个解决方案",
    ]
    return forms[idx % len(forms)].format(d=device, s=symptom)


def missing(symptom, idx):
    forms = ["{s}，是什么原因，咋排查", "最近{s}，咋解决"]
    return forms[idx % len(forms)].format(s=symptom)


def stratify(groups):
    """按设备类型轮转取样，保证 46 条 hard query 覆盖各设备。"""
    buckets = OrderedDict()
    for g in groups:
        buckets.setdefault(g["device"] or "其他", []).append(g)
    picked, i = [], 0
    while len(picked) < 46:
        added = False
        for dev in list(buckets):
            if i < len(buckets[dev]) and len(picked) < 46:
                picked.append(buckets[dev][i])
                added = True
        if not added:
            break
        i += 1
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/paper/评测/eval_set.csv")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    recs = fetch_published()
    real = [r for r in recs if not TEST_PAT.search((r["title"] or "").strip())]
    groups = OrderedDict()
    for r in real:
        key = (r["title"] or "").strip()
        g = groups.setdefault(key, {"title": key, "device": r["applyDeviceType"], "ids": []})
        g["ids"].append(str(r["id"]))
        g["device"] = g["device"] or r["applyDeviceType"]
    groups = list(groups.values())
    for g in groups:
        g["fault"] = fault_of(g["title"], g["device"] or "")
        g["symptom"], g["uniq"] = SYMPTOM.get(g["fault"], (g["fault"], False))

    rows = []
    for i, g in enumerate(groups):
        rows.append({
            "query": ["{d}{f}怎么处理", "{d}出现{f}应该如何排查", "{d}{f}的解决方法"][i % 3].format(
                d=g["device"], f=g["fault"]),
            "expectedIds": ";".join(g["ids"]),
            "deviceType": g["device"] or "",
            "note": "formal|" + g["title"],
            "style": "formal", "group": g["title"],
        })

    for i, g in enumerate(stratify(groups)):
        style = ["colloquial", "noisy", "missing"][i % 3]
        if style == "missing" and not g["uniq"]:
            style = "noisy"
        if style == "colloquial":
            q = colloquial(g["device"], g["symptom"], i)
        elif style == "noisy":
            q = noisy(g["device"], g["symptom"], i)
        else:
            q = missing(g["symptom"], i)
        rows.append({
            "query": q,
            "expectedIds": ";".join(g["ids"]),
            "deviceType": "" if style == "missing" else (g["device"] or ""),
            "note": style + "|" + g["title"],
            "style": style, "group": g["title"],
        })

    assert len(rows) == 100, len(rows)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["query", "expectedIds", "deviceType", "note"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in ("query", "expectedIds", "deviceType", "note")})

    print("知识记录:", len(recs), "有效知识:", len(real), "知识组(同标题合并):", len(groups))
    print("query 总数:", len(rows))
    print("风格分布:", dict(Counter(r["style"] for r in rows)))
    print("设备分布:", dict(Counter(r["deviceType"] or "(未提及设备)" for r in rows)))
    print("未收录口语现象的故障短语:", [g["fault"] for g in groups if g["fault"] not in SYMPTOM])
    print("每条知识 query 数:", dict(Counter(Counter(r["group"] for r in rows).values())))
    if args.dry:
        for r in rows[54:]:
            print(r["style"], "|", r["query"], "|", r["expectedIds"])
    print("写出:", args.out)


if __name__ == "__main__":
    main()
