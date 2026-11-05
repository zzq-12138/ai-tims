#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阈值评估负例集生成（100 条，四类各 25）。

构造规则全部写在脚本内的确定性表，便于复核：
- same_symptom_diff_cause（同象异因）：症状短语逐字取自库内条目，但所陈述的根因是
  同设备族内库未覆盖的根因（构造后自动校验：症状词在库内出现、根因关键词在库内不出现）。
- out_of_domain（领域外）：知识库未覆盖的设备/工艺，构造后自动校验关键词零命中。
- same_cause_diff_symptom（同因异象）：根因逐字取自库内条目的“可能原因”，表现换成该条目
  未描述的另一种现象（锚点条目字段记录来源条目，构造后校验根因短语确在锚点条目内）。
- missing_noise（缺字段/噪声）：对 eval_set 前 25 条 formal query 做确定性降级
  （去设备字段 / 截半句 / 错别字噪声），usableIds 保留原始 gold。

用法: python3 gen_negative_set.py --eval docs/paper/评测/eval_set.csv --kb /tmp/kb_dump.json \
        --out docs/paper/评测/negative_set.csv
"""
import argparse
import csv
import json
import re

DEVICES = ["MES终端", "SPI锡膏检测机", "AOI检测机", "回流焊", "涂布机", "蚀刻机", "贴合机", "贴片机"]

# (设备, 症状(逐字取自库内), 陈述根因(库未覆盖), 根因校验关键词)
SAME_SYMPTOM = [
    ("贴片机", "吸嘴无法吸取元件", "真空泵膜片老化", "真空泵"),
    ("贴片机", "贴装后元器件位置偏离目标位置", "伺服驱动器编码器零位丢失", "编码器"),
    ("贴片机", "供料器出现卡料", "压带轮轴承磨损", "轴承"),
    ("贴片机", "传送轨道上卡板", "轨道宽度伺服电机丢步", "伺服电机"),
    ("贴片机", "视觉系统无法正确识别元件位置", "千兆网卡丢包", "网卡"),
    ("贴片机", "贴装头在运行过程中突然撞击工作台面", "Z轴刹车片磨损", "刹车片"),
    ("贴片机", "元器件出现立碑现象", "贴片针加热棒可控硅击穿", "可控硅"),
    ("贴片机", "气路压力异常，表现为喷嘴无力", "车间储气罐泄漏", "储气罐"),
    ("AOI检测机", "拍摄出的图像模糊不清", "相机CMOS靶面结露", "CMOS"),
    ("AOI检测机", "条码识别失败", "读码器偏振滤光片老化", "偏振"),
    ("AOI检测机", "误报率过高", "GPU显存ECC报错", "GPU"),
    ("AOI检测机", "无法与其他设备或系统进行通讯", "交换机VLAN配置漂移", "VLAN"),
    ("AOI检测机", "光源亮度衰减", "恒流源采样电阻温漂", "恒流源"),
    ("AOI检测机", "过板过程中出现卡板现象", "传送皮带张紧轮碎裂", "张紧轮"),
    ("蚀刻机", "蚀刻机喷嘴堵塞", "供液泵单向阀卡死", "单向阀"),
    ("蚀刻机", "蚀刻速率与设定值存在较大偏差", "整流器输出纹波过大", "纹波"),
    ("蚀刻机", "腔体压力异常波动", "真空规管灯丝老化", "真空规"),
    ("蚀刻机", "废液排放过程中出现报警", "液位浮球开关失效", "浮球"),
    ("蚀刻机", "蚀刻后的表面出现不均匀的蚀刻痕迹", "喷淋摆臂同步带打滑", "同步带"),
    ("涂布机", "涂布厚度不均匀", "模头唇口微调螺栓松动", "模头"),
    ("涂布机", "纠偏系统无法正常工作", "光电边缘传感器镜片污染", "光电边缘"),
    ("涂布机", "涂层出现不规则气泡", "供料过滤器堵塞析气", "过滤器"),
    ("涂布机", "出现张力波动", "磁粉制动器线圈老化", "磁粉"),
    ("涂布机", "烘干段温度异常波动", "热风风机变频器过流", "变频器"),
    ("贴合机", "贴合过程中出现气泡", "真空腔体密封圈老化", "密封圈"),
]

# (设备, 根因(逐字取自库内), 另一种表现, 锚点条目标题, 根因校验短语)
SAME_CAUSE = [
    ("贴片机", "供料器胶带老化", "取料时料带轻微抖动，贴装后元件极性反贴", "贴片机供料器卡料维修", "胶带老化"),
    ("贴片机", "吸嘴内部污垢", "元件吸附后偶发掉落，吸嘴外观无明显异常", "贴片机吸嘴堵塞处理", "吸嘴内部污垢"),
    ("贴片机", "贴片针压力不足", "焊点高度偏低、偶发虚焊", "贴片机元器件立碑故障", "贴片针压力不足"),
    ("贴片机", "传送带速度不稳定", "板间距忽大忽小，出板节拍抖动", "贴片机抛料故障", "传送带速度不稳定"),
    ("贴片机", "视觉系统误差", "同一程序反复贴装，偏移量随机变化", "贴片机贴装偏移处理", "视觉系统误差"),
    ("AOI检测机", "照明系统损坏", "检测图像局部过曝，边缘元件判定不稳", "AOI漏检故障处理", "照明系统损坏"),
    ("AOI检测机", "镜头脏污", "元件中心定位漂移，重复检测结果不一致", "AOI图像模糊故障处理", "镜头脏污"),
    ("AOI检测机", "对焦马达故障", "图像时清晰时模糊，随温度变化", "AOI相机对焦异常", "对焦马达故障"),
    ("AOI检测机", "算法阈值设置不合理", "同一批板前后判定结果不一致", "AOI检测机算法阈值漂移处理", "算法阈值设置不合理"),
    ("AOI检测机", "接口卡故障", "检测数据偶发丢包，重连后恢复", "AOI检测机通讯中断", "接口卡故障"),
    ("蚀刻机", "蚀刻液浓度过高", "板面发白，线路边缘出现锯齿", "蚀刻机过蚀刻处理", "蚀刻液浓度过高"),
    ("蚀刻机", "腔体密封不良", "抽真空时间明显变长", "蚀刻机腔体压力异常处理", "腔体密封不良"),
    ("蚀刻机", "温控系统异常", "蚀刻深度随批次缓慢变浅", "蚀刻机腔体温度漂移处理", "温控系统异常"),
    ("蚀刻机", "水洗系统过滤网堵塞", "板面出现细颗粒残留", "蚀刻机水洗残留处理", "过滤网堵塞"),
    ("蚀刻机", "传送轮表面油脂", "板底出现规律性油印", "蚀刻机传送轮污染处理", "油脂"),
    ("涂布机", "涂布辊压力不均", "收卷时料带跑偏", "涂布机涂布厚度不均", "涂布辊压力不均"),
    ("涂布机", "背辊表面润滑不良", "涂布面出现周期性条纹", "涂布机背辊粘胶处理", "润滑不良"),
    ("涂布机", "张力传感器故障", "断带报警偶发误触发", "涂布机张力波动故障", "张力传感器故障"),
    ("涂布机", "涂料搅拌不均匀", "涂层出现云状色差", "涂布机涂层气泡处理", "涂料搅拌不均匀"),
    ("贴合机", "气缸压力不足", "贴合后产品边缘翘曲", "贴合机压力不均故障", "气缸压力不足"),
    ("贴合机", "温控传感器损坏", "贴合胶固化时间变长", "贴合机温控异常处理", "温控传感器损坏"),
    ("贴合机", "静电发生器损坏", "薄料吸附后位置漂移", "贴合机静电吸附不良", "静电发生器损坏"),
    ("贴合机", "导轨清洁度不够", "贴合面出现细碎压痕", "贴合机材料褶皱处理", "导轨清洁度不够"),
    ("MES终端", "本地缓存队列", "客户端按钮点不动，界面卡死", "MES终端报工接口超时处理", "缓存队列"),
    ("回流焊", "校准热电偶", "各温区实测温度与设定偏差不一致", "e2e回流焊炉温失控处理", "校准热电偶"),
]

# (设备/主题, 故障表现, 关键词)
OUT_OF_DOMAIN = [
    ("空压机", "排气温度过高频繁跳机", "空压机"),
    ("真空泵", "油品乳化、极限真空度下降", "真空泵"),
    ("冷却塔", "风机振动超标、轴承温度偏高", "冷却塔"),
    ("注塑机", "料筒加热圈烧毁", "注塑机"),
    ("CNC加工中心", "主轴高速运转异响", "CNC"),
    ("激光打标机", "打标深度忽深忽浅", "激光打标"),
    ("超声波清洗机", "换能器失效、清洗无力", "超声波"),
    ("点胶机", "胶点直径不稳定", "点胶"),
    ("X-Ray检测机", "球管老化、成像对比度下降", "X-Ray"),
    ("ICT测试机", "探针接触不良、测试误判", "ICT"),
    ("老化房", "温湿度失控", "老化房"),
    ("立体仓库堆垛机", "行走机构异响", "堆垛机"),
    ("AGV小车", "导航丢失、原地打转", "AGV"),
    ("车间电梯", "困人、门机不闭合", "电梯"),
    ("锅炉", "水位低报警", "锅炉"),
    ("中央空调", "冷媒泄漏、制冷量下降", "冷媒"),
    ("消防喷淋", "无火情误动作", "喷淋"),
    ("机房UPS", "电池鼓包、后备时间骤降", "UPS"),
    ("除尘器", "布袋破损、出口含尘超标", "除尘"),
    ("污水泵", "叶轮缠绕、流量下降", "污水"),
    ("行车", "大车行走啃轨", "行车"),
    ("皮带输送线", "输送带跑偏", "皮带"),
    ("自动锁螺丝机", "扭力不足、滑牙", "锁螺丝"),
    ("灌胶机", "出胶量不稳", "灌胶"),
    ("锡膏搅拌机", "搅拌温升异常", "锡膏搅拌"),
]

NOISE_SWAP = [("堵塞", "堵搴"), ("偏移", "偏依"), ("报警", "报井"), ("温度", "温渡"),
              ("压力", "压立"), ("异常", "异长"), ("故障", "故张"), ("识别", "识剐")]


def build(eval_csv, kb_path):
    rows = list(csv.DictReader(open(eval_csv, encoding="utf-8")))
    kb = json.load(open(kb_path, encoding="utf-8"))
    kb_text = "\n".join((x.get("title") or "") + (x.get("summary") or "") + (x.get("content") or "")
                        + (x.get("tags") or "") for x in kb)
    # 去掉 dump 时对换行的替换，便于症状子串校验
    kb_text = kb_text.replace(" / ", " ")

    out = []

    # 1) 同象异因
    for i, (dev, sym, cause, kw) in enumerate(SAME_SYMPTOM, 1):
        ok_sym = sym in kb_text
        ok_cause = kw not in kb_text
        out.append({"id": f"N1-{i:02d}", "class": "same_symptom_diff_cause",
                    "query": f"{dev}{sym}，我怀疑是{cause}导致的，怎么处理",
                    "usableIds": "", "source": "规则生成（库内症状 × 同族未覆盖根因）+人工复核",
                    "basis": f"症状在库内可匹配，但根因关键词“{kw}”全库 0 命中；库内同症状条目的根因不同，推送即误导",
                    "check": f"symptom_in_kb={int(ok_sym)};cause_absent={int(ok_cause)}"})

    # 2) 领域外
    for i, (topic, fault, kw) in enumerate(OUT_OF_DOMAIN, 1):
        absent = kw not in kb_text
        out.append({"id": f"N2-{i:02d}", "class": "out_of_domain",
                    "query": f"{topic}{fault}，怎么排查",
                    "usableIds": "", "source": "规则生成（领域清单）+人工复核",
                    "basis": f"主题关键词“{kw}”全库 0 命中，知识库未覆盖该设备/工艺",
                    "check": f"topic_absent={int(absent)}"})

    # 3) 同因异象
    by_title = {x["title"].strip(): x for x in kb}
    for i, (dev, cause, alt, anchor, cause_phrase) in enumerate(SAME_CAUSE, 1):
        rec = by_title.get(anchor)
        ok_anchor = bool(rec) and cause_phrase in (rec.get("content") or "").replace("\n", " / ")
        out.append({"id": f"N3-{i:02d}", "class": "same_cause_diff_symptom",
                    "query": f"{dev}出现{alt}，我们怀疑根因是{cause}，该怎么验证",
                    "usableIds": "", "source": "规则生成（库内根因 × 库内未描述表现）+人工复核",
                    "basis": f"根因取自锚点条目《{anchor}》，但该表现未在该条目或同族条目中描述；按症状推送会给出错位排查路径",
                    "check": f"anchor_cause_in_kb={int(ok_anchor)}"})

    # 4) 缺字段/噪声（取前 25 条 formal）
    formal = [r for r in rows if r["note"].startswith("formal")][:25]
    for i, r in enumerate(formal, 1):
        q = r["query"]
        mode = i % 3
        if mode == 1:  # 去设备字段
            q2 = q
            for d in sorted(DEVICES, key=len, reverse=True):
                q2 = q2.replace(d, "")
            src, basis = "规则生成（去设备字段）", "缺设备型号，系统应追问设备而不是直接推送"
        elif mode == 0:  # 截半句
            q2 = re.sub(r"(的)?(解决方法|怎么处理|如何处理|如何排查|怎么排查)$", "", q)
            src, basis = "规则生成（截断半句）", "半句输入，缺少处理意图"
        else:  # 错别字/噪声
            q2 = q
            swapped = False
            for a, b in NOISE_SWAP:
                if a in q2:
                    q2 = q2.replace(a, b, 1)
                    swapped = True
                    break
            q2 = q2 + "？？急"
            src = "规则生成（错别字+噪声）" if swapped else "规则生成（追加噪声）"
            basis = "含错别字与噪声，输入质量差" if swapped else "仅追加口语噪声，输入不完整"
        out.append({"id": f"N4-{i:02d}", "class": "missing_noise", "query": q2,
                    "usableIds": r["expectedIds"], "source": src + "+人工复核",
                    "basis": basis + "；若 top1 仍为原始 gold，则保守计为可用，不计错误推送",
                    "check": "usable=source_gold"})

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default="docs/paper/评测/eval_set.csv")
    ap.add_argument("--kb", default="/tmp/kb_dump.json")
    ap.add_argument("--out", default="docs/paper/评测/negative_set.csv")
    args = ap.parse_args()
    rows = build(args.eval, args.kb)
    cols = ["id", "class", "query", "usableIds", "source", "basis", "check"]
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print("negatives:", len(rows), dict(Counter(r["class"] for r in rows)))
    bad = [r for r in rows if "=0" in r["check"]]
    print("check_failed:", len(bad))
    for r in bad:
        print("  ", r["id"], r["check"], r["query"])


if __name__ == "__main__":
    main()
