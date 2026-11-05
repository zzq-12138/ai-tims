#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
问题二标注种子集生成（1000 条工单）+ 关系对辅助数据。

设计取舍（2026-11-06 拍板）：
- 主体来源 = 工单模拟器模板（设备-故障主题表复用 scripts/seed_kb.py 的 5 设备 × 10 主题并扩展），
  知识库反推只作补充、不作主体。理由：反推 query 天然"库里有答案"，会把 M7 的
  VECTOR Hit@3=100% 天花板偏差带进训练集；模拟器文本更接近真实报修叙述（有过程、有排除）。
- 全部为合成语料，不含任何真实企业信息。

产出（默认 docs/paper/问题二/）：
- annotation_set_v1.csv      标注用，标签列为空（人工填），不含真值
- _gold_draft.jsonl          生成真值，供 κ / 错误分析；与标注文件物理隔离
- annotation_data.js         window.ANNOTATION_DATA，供 HTML 工作台直接读取
- _dataset_stats.json        分层统计（聚合数字，无逐条真值）

用法：
  python3 scripts/annotation/gen_seed_1000.py
  python3 scripts/annotation/gen_seed_1000.py --out-dir docs/paper/问题二 --seed 20261106
  python3 scripts/annotation/gen_seed_1000.py --with-s1 --s1-limit 30   # 额外生成 S1 零样本参考值
"""
import argparse
import csv
import json
import os
import random
import re
import sys
import time

DEVICES = ["贴片机", "AOI检测机", "涂布机", "贴合机", "蚀刻机"]
STYLES = ["formal", "colloquial", "missing", "typo", "long"]


def sc(device, topic, model, code, symptom, cause, alt, evidence,
       m1, m2, verify, cond):
    return dict(device=device, topic=topic, model=model, code=code, symptom=symptom,
                cause=cause, alt=alt, evidence=evidence, m1=m1, m2=m2,
                verify=verify, cond=cond)


# ---------------------------------------------------------------- 设备-故障主题表
SCEN = [
    # 贴片机
    sc("贴片机", "抛料", "SIPLACE SX", "E102",
       "2 号贴片机在 0402 电阻工单生产中连续抛料，抛料率由 0.4% 升至 2.1%，取料位置报警频繁",
       "供料器齿轮磨损导致进料不到位", "供料器卡料（异物堵塞）",
       "拆下 3 号供料器，3 号齿轮齿面已磨平，手动盘料有明显旷量",
       "更换同型号供料器并重新标定取料位置", "连续试产 200 片确认取料稳定",
       "连续生产 2 小时抛料率回落至 0.3%，无取料位置报警",
       [("device_model", "SIPLACE SX"), ("process_stage", "0402 电阻贴装"), ("param_range", "抛料率 0.4%-2.1%")]),
    sc("贴片机", "吸嘴堵塞", "SIPLACE SX", "E103",
       "1 号头取料后掉件，真空检测值波动，频繁报真空异常",
       "吸嘴内壁附着锡膏残渣导致真空压力不足", "真空发生器故障",
       "拆检吸嘴可见内壁残渣，实测真空 -45kPa（正常 ≤-70kPa）",
       "更换 0402 吸嘴并用清洗液超声清洗真空通道", "复校真空检测阈值",
       "连续 5 片首件真空值稳定在 -78kPa 至 -82kPa，无掉件",
       [("device_model", "SIPLACE SX"), ("process_stage", "0402 贴装"), ("param_range", "真空 -45kPa")]),
    sc("贴片机", "贴装偏移", "SIPLACE SX", "E104",
       "3 号贴片机 0603 电容贴装出现 X 方向系统性偏移，偏移量 0.12-0.18mm，AOI 判 NG",
       "贴装头零点漂移", "吸嘴磨损",
       "更换新吸嘴后偏移未改善，重新标定贴装头零点后偏移消失",
       "重新标定贴装头零点", "更新贴装程序中的元件坐标补偿",
       "连续 5 片首件 AOI 复判偏移 ≤0.05mm，CPK 1.33",
       [("device_model", "SIPLACE SX"), ("param_range", "偏移 0.12-0.18mm"), ("process_stage", "0603 电容贴装")]),
    sc("贴片机", "供料器卡料", "SIPLACE SX", "E105",
       "8mm 供料器连续卡料，料带在压料区堆叠，抛料率 3.4%",
       "压料盖弹簧疲劳导致压料不到位", "料带接头不良",
       "更换新料卷后仍卡料，拆检压料盖弹簧弹力不足",
       "更换压料盖组件", "调整压料间隙至 0.05mm",
       "连续 2 小时无卡料，抛料率 0.2%",
       [("device_model", "SIPLACE SX"), ("material_or_batch", "8mm 料带"), ("param_range", "抛料率 3.4%")]),
    sc("贴片机", "元件视觉识别失败", "SIPLACE SX", "E106",
       "0402 电感识别失败率 8%，报元件尺寸超差",
       "相机光源偏移导致元件轮廓过曝", "元件来料尺寸超差",
       "取 10 颗标准件复测仍识别失败，实测光源照度 3200lx（标准 1800-2200lx）",
       "重新固定光源支架并调整亮度至 2000lx", "重跑视觉识别标定",
       "连续 100 颗识别成功率 100%",
       [("device_model", "SIPLACE SX"), ("param_range", "照度 3200lx"), ("process_stage", "0402 电感贴装")]),
    sc("贴片机", "贴装头撞击", "SIPLACE SX", "E107",
       "4 号头下行时撞击吸嘴站，设备急停报 Z 轴过载",
       "Z 轴伺服编码器信号线松动导致位置反馈丢失", "吸嘴长度不匹配",
       "更换标准吸嘴后仍撞击，检查编码器线束发现插头松脱",
       "重新插紧并锁固编码器插头", "执行 Z 轴回零与限位复校",
       "空跑 200 次无撞击，Z 轴位置误差 ≤0.02mm",
       [("device_model", "SIPLACE SX"), ("precondition", "更换吸嘴后仍复现")]),
    sc("贴片机", "传送轨道卡板", "SIPLACE SX", "E108",
       "轨道入口卡板，皮带打滑，连续 3 片停在入口",
       "入口皮带张紧轮轴承卡死", "PCB 板厚设置错误",
       "按标准板厚 1.6mm 复测仍卡，手动盘动皮带阻力明显",
       "更换张紧轮轴承", "重新调整皮带张力",
       "连续过板 100 片无卡板",
       [("device_model", "SIPLACE SX"), ("process_stage", "轨道入口")]),
    sc("贴片机", "锡膏印刷偏移", "SIPLACE SX", "E109",
       "印刷与贴片联线后锡膏图形整体偏移 0.2mm，贴装后立碑增多",
       "钢网与 PCB 对位视觉系统标定偏移", "PCB 定位销磨损",
       "更换定位销后偏移未变，用标准标定板实测偏移 0.21mm",
       "重新执行钢网对位视觉标定", "更新印刷机与贴片机联线基准",
       "标准板复测偏移 ≤0.05mm，立碑比例回落至 0.1%",
       [("device_model", "SIPLACE SX"), ("param_range", "偏移 0.2mm"), ("process_stage", "锡膏印刷后")]),
    sc("贴片机", "元器件立碑", "SIPLACE SX", "E110",
       "回流后 0402 电容立碑比例 1.8%，集中在板边",
       "回流焊预热区升温速率过快", "焊盘设计不合理",
       "同批板换到 2 号线慢速曲线后立碑 0.2%，实测预热速率 3.2℃/s（标准 ≤2℃/s）",
       "调整回流曲线，预热速率降至 1.8℃/s", "延长均温区 20s",
       "连续 3 批立碑比例 ≤0.3%",
       [("device_model", "SIPLACE SX"), ("param_range", "升温 3.2℃/s"), ("process_stage", "回流焊")]),
    sc("贴片机", "气路压力异常", "SIPLACE SX", "E111",
       "整线气压报警，贴片机真空值跌至 -40kPa，多台设备掉件",
       "主气路过滤器堵塞导致供气压力不足", "空压机故障",
       "空压机出口压力 0.68MPa 正常，过滤器前后压差 0.12MPa（标准 ≤0.03MPa）",
       "更换主气路过滤器滤芯", "排放储气罐冷凝水",
       "气压恢复 0.65MPa，真空值 -80kPa，连续 4 小时无报警",
       [("device_model", "SIPLACE SX"), ("param_range", "压差 0.12MPa")]),
    # AOI
    sc("AOI检测机", "误报率过高", "VI-5000", "A201",
       "AOI 对 2 号线连续 5 片误报焊点少锡，误报率 12%",
       "检测程序阈值过严（焊点面积下限设 85%）", "焊点实际不良",
       "同批板人工复判 20 片均合格，程序阈值对比标准值 70%",
       "将焊点面积阈值调整为 70%", "重新学习 20 片标准板",
       "复跑 100 片误报率降至 1.5%",
       [("device_model", "VI-5000"), ("param_range", "阈值 85%"), ("process_stage", "焊点检测")]),
    sc("AOI检测机", "漏检", "VI-5000", "A202",
       "AOI 漏检 0603 元件缺件，流出到下一工序",
       "元件库未录入该封装导致检测框缺失", "相机分辨率不足",
       "回放图像清晰可见缺件，程序中无该封装检测框",
       "补充 0603 封装元件库并重新示教", "对全部程序做封装覆盖检查",
       "复跑含缺件样本 30 片全部检出",
       [("device_model", "VI-5000"), ("process_stage", "0603 元件检测")]),
    sc("AOI检测机", "图像模糊", "VI-5000", "A203",
       "AOI 图像整体模糊、边缘发虚，连续 5 片无法识别焊点",
       "镜头表面附着助焊剂雾气", "相机对焦失准",
       "擦拭镜头后图像恢复清晰，对焦标定值未变",
       "用无水乙醇清洁镜头与防护玻璃", "增加每班镜头清洁点检",
       "连续 100 片图像清晰度评分 ≥0.9",
       [("device_model", "VI-5000"), ("precondition", "对焦标定值未变")]),
    sc("AOI检测机", "光源亮度衰减", "VI-5000", "A204",
       "AOI 图像偏暗、焊点反光不足，误报率上升",
       "环形光源 LED 光衰，实测照度降至 1200lx", "相机增益设置过低",
       "调高增益仍偏暗，照度计实测 1200lx（标准 2000±200lx）",
       "更换环形光源模组", "重新标定光源亮度与曝光",
       "照度恢复 2050lx，误报率回落至 2%",
       [("device_model", "VI-5000"), ("param_range", "照度 1200lx")]),
    sc("AOI检测机", "程序调用错误", "VI-5000", "A205",
       "换线后 AOI 调用了上一机型程序，批量误判",
       "换线流程未按机型绑定程序，MES 下发程序号错误", "条码读取错误",
       "扫描条码正确，但 AOI 程序号与 MES 记录不一致",
       "修正 MES 机型-程序映射表", "增加换线首件程序号核对",
       "连续换线 3 次程序号一致，无批量误判",
       [("device_model", "VI-5000"), ("precondition", "换线后首件")]),
    sc("AOI检测机", "条码识别失败", "VI-5000", "A206",
       "AOI 读码失败率 15%，报无条码",
       "条码枪焦距偏移", "标签打印质量差",
       "用标准测试条码复测仍失败，实测读码距离偏离 8mm",
       "重新调整条码枪安装距离与焦距", "校准解码参数",
       "连续 200 片读码成功率 100%",
       [("device_model", "VI-5000"), ("param_range", "读码距离偏离 8mm")]),
    sc("AOI检测机", "过板卡板", "VI-5000", "A207",
       "AOI 入口卡板，轨道皮带空转",
       "轨道宽度调整机构丝杆积尘卡滞", "板厚设置错误",
       "手动调整轨道宽度阻力大，丝杆有明显粉尘结块",
       "清洁并润滑轨道丝杆", "重新标定轨道宽度",
       "连续过板 100 片无卡板",
       [("device_model", "VI-5000"), ("process_stage", "轨道入口")]),
    sc("AOI检测机", "相机对焦异常", "VI-5000", "A208",
       "AOI 局部区域图像失焦，误报 8 片",
       "Z 轴对焦电机皮带松弛", "板面不平",
       "用标准平面板复测仍失焦，皮带张力实测偏低",
       "更换对焦电机皮带并张紧", "重跑全幅面对焦标定",
       "全幅面清晰度 ≥0.9，误报率 1.2%",
       [("device_model", "VI-5000"), ("precondition", "标准平板复测复现")]),
    sc("AOI检测机", "算法阈值漂移", "VI-5000", "A209",
       "AOI 连续 3 天误报率逐日上升，从 2% 涨到 9%",
       "环境温度升高导致相机暗电流增大、灰度基准漂移", "来料质量下降",
       "同批标准板复测误报同样升高，灰度基准值漂移 12",
       "重新执行灰度基准校准", "增加空调温控并设定 23±2℃",
       "连续 3 天误报率稳定在 2% 以内",
       [("device_model", "VI-5000"), ("precondition", "同批标准板复现"), ("param_range", "误报 2%→9%")]),
    sc("AOI检测机", "通讯中断", "VI-5000", "A210",
       "AOI 与 MES 通讯中断，检测数据无法上传",
       "交换机端口协商异常（百兆/千兆频繁切换）", "网线老化",
       "更换网线后仍中断，交换机日志显示端口 up/down 反复",
       "固定端口速率与双工模式", "更换交换机端口",
       "连续 24 小时无断连，数据上传完整",
       [("device_model", "VI-5000"), ("precondition", "更换网线后仍复现")]),
    # 涂布机
    sc("涂布机", "涂布厚度不均", "COAT-800", "C301",
       "涂布厚度实测 12±3μm，超出 ±1μm 要求，横向呈波浪分布",
       "涂布辊与背辊平行度超差（0.08mm）", "浆料黏度波动",
       "同批浆料黏度复测 1200cP 正常，辊间塞尺实测两端差 0.08mm",
       "重新调整两辊平行度至 0.02mm 内", "复跑厚度标定",
       "连续 30m 厚度 12±0.8μm",
       [("device_model", "COAT-800"), ("param_range", "厚度 12±3μm"), ("process_stage", "涂布段")]),
    sc("涂布机", "涂层气泡", "COAT-800", "C302",
       "涂层出现密集微气泡，直径 0.2-0.5mm",
       "供料泵入口吸入空气", "浆料脱泡不充分",
       "更换脱泡后浆料仍起泡，泵入口接头有渗气",
       "更换泵入口密封圈并排气", "增加供料管路排气阀",
       "连续 50m 无气泡",
       [("device_model", "COAT-800"), ("process_stage", "供料段")]),
    sc("涂布机", "边缘漏涂", "COAT-800", "C303",
       "极片边缘 2mm 区域漏涂，宽度不稳定",
       "涂布模头垫片边缘磨损", "浆料流量不足",
       "流量实测正常，拆检垫片边缘有缺口",
       "更换模头垫片", "重新调整模头间隙",
       "边缘涂覆宽度稳定，连续 50m 无漏涂",
       [("device_model", "COAT-800"), ("process_stage", "模头段")]),
    sc("涂布机", "张力波动", "COAT-800", "C304",
       "基材张力在 40-75N 间波动，涂布出现横向条纹",
       "张力传感器零点漂移", "放卷辊制动器故障",
       "用标准砝码校验传感器偏差 6N",
       "重新标定张力传感器零点", "检查并紧固传感器接线",
       "张力稳定 55±3N，条纹消失",
       [("device_model", "COAT-800"), ("param_range", "张力 40-75N")]),
    sc("涂布机", "烘干温度异常", "COAT-800", "C305",
       "烘箱二段温度显示 105℃，实测 88℃",
       "热电偶接线端子氧化导致测温偏低", "加热管损坏",
       "加热管电流正常，端子电阻异常，标准温度计比对偏低 17℃",
       "更换热电偶并清洁端子", "重新整定温控 PID",
       "各段温差 ≤3℃，连续 2 小时稳定",
       [("device_model", "COAT-800"), ("param_range", "二段 105→88℃")]),
    sc("涂布机", "涂布头堵塞", "COAT-800", "C306",
       "涂布出现纵向连续缺料条纹",
       "浆料中颗粒团聚堵塞模头狭缝", "供料压力不足",
       "供料压力正常，拆检狭缝有团聚颗粒",
       "拆洗模头狭缝并更换 100 目过滤网", "增加浆料过滤工序",
       "连续 100m 无纵向缺料",
       [("device_model", "COAT-800"), ("process_stage", "模头狭缝")]),
    sc("涂布机", "纠偏失灵", "COAT-800", "C307",
       "基材跑偏超出 ±3mm，边缘报警停机",
       "纠偏光电传感器被浆料污染", "纠偏电机故障",
       "清洁传感器后恢复正常，电机动作正常",
       "清洁纠偏传感器镜头", "增加防护挡板",
       "连续运行 2 小时跑偏 ≤±1mm",
       [("device_model", "COAT-800"), ("param_range", "跑偏 ±3mm")]),
    sc("涂布机", "背辊粘胶", "COAT-800", "C308",
       "背辊表面粘附浆料，转印到基材背面",
       "背辊表面涂层磨损导致离型性下降", "浆料固含量偏高",
       "固含量复测正常，背辊表面粗糙度 Ra 由 0.4 升至 1.2μm",
       "更换背辊或重新喷涂离型涂层", "调整刮刀压力",
       "连续 100m 背面无粘料",
       [("device_model", "COAT-800"), ("param_range", "Ra 0.4→1.2μm")]),
    sc("涂布机", "速度同步异常", "COAT-800", "C309",
       "涂布与收卷速度不同步，基材出现松弛堆积",
       "编码器联轴器松动导致速度反馈丢失", "变频器参数错误",
       "恢复变频器参数后仍异常，联轴器有明显旷量",
       "更换编码器联轴器", "重新做速度闭环整定",
       "速度同步误差 ≤0.5%，连续 1 小时无松弛",
       [("device_model", "COAT-800"), ("process_stage", "收卷段")]),
    sc("涂布机", "料卷接头断带", "COAT-800", "C310",
       "料卷接头处在涂布时断带，停机 40min",
       "接头胶带耐温不足，烘箱内失效", "基材本身强度不足",
       "断口在接头处，胶带为常温型（耐温 80℃），烘箱 105℃",
       "改用耐高温接头胶带（150℃）", "接头处降低烘箱温度 10℃过渡",
       "连续 3 个接头无断带",
       [("device_model", "COAT-800"), ("material_or_batch", "接头胶带"), ("param_range", "烘箱 105℃")]),
    # 贴合机
    sc("贴合机", "贴合气泡", "LAM-600", "L401",
       "贴合后出现直径 1-3mm 气泡，边缘集中",
       "贴合辊压力不均，两端偏低", "胶层涂布不均",
       "胶层厚度实测均匀，辊面压力两端 0.2MPa（中间 0.45MPa）",
       "调整贴合辊两端压力至 0.45MPa", "更换老化辊面",
       "连续 200 片无气泡",
       [("device_model", "LAM-600"), ("param_range", "两端压力 0.2MPa")]),
    sc("贴合机", "贴合偏移", "LAM-600", "L402",
       "上下片贴合偏移 0.3mm，超出 ±0.1mm",
       "定位视觉相机标定漂移", "定位销磨损",
       "更换定位销后仍偏移，标准标定板实测偏移 0.28mm",
       "重新标定上下相机", "更新贴合补偿参数",
       "连续 100 片偏移 ≤0.05mm",
       [("device_model", "LAM-600"), ("param_range", "偏移 0.3mm")]),
    sc("贴合机", "材料褶皱", "LAM-600", "L403",
       "柔性材料在贴合时起皱，废品率 6%",
       "放卷张力过小导致材料松弛", "材料本身卷曲",
       "更换同批材料仍褶皱，张力实测 15N（工艺要求 30±5N）",
       "调整放卷张力至 30N", "增加展平辊",
       "连续 200 片无褶皱",
       [("device_model", "LAM-600"), ("param_range", "张力 15N"), ("material_or_batch", "柔性基材")]),
    sc("贴合机", "脱胶", "LAM-600", "L404",
       "贴合件边缘脱胶，剥离强度 3N/cm（要求 ≥6N/cm）",
       "贴合温度偏低导致胶层未充分活化", "胶水过期",
       "胶水在保质期内，实测贴合面温度 65℃（要求 85±5℃）",
       "调整加热模块至 85℃", "延长压合时间 2s",
       "剥离强度 7.2N/cm，连续 100 片合格",
       [("device_model", "LAM-600"), ("param_range", "贴合温度 65℃")]),
    sc("贴合机", "贴合压力不均", "LAM-600", "L405",
       "贴合面局部未压合，出现白斑",
       "压合气缸密封圈漏气", "压板变形",
       "压板平面度实测 0.03mm 合格，气缸压力保持不住",
       "更换气缸密封圈", "检查气路接头",
       "压力稳定 0.5MPa，连续 200 片无白斑",
       [("device_model", "LAM-600"), ("param_range", "压力 0.5MPa")]),
    sc("贴合机", "辊筒磨损", "LAM-600", "L406",
       "贴合辊表面有划痕，转印到产品表面",
       "辊面被异物划伤", "材料含硬质颗粒",
       "停机检查发现辊面有 0.1mm 深划痕，异物为金属屑",
       "更换贴合辊", "入口增加除尘与异物拦截",
       "连续 300 片表面无划痕",
       [("device_model", "LAM-600"), ("precondition", "来料含金属屑")]),
    sc("贴合机", "定位标记识别失败", "LAM-600", "L407",
       "Mark 点识别失败率 20%，设备频繁停机",
       "Mark 点周围反光导致对比度不足", "相机光源老化",
       "更换光源后仍失败，加偏振片后识别正常",
       "加装偏振片并调整曝光", "优化 Mark 点识别模板",
       "连续 300 片识别成功率 100%",
       [("device_model", "LAM-600"), ("material_or_batch", "高反光基材")]),
    sc("贴合机", "温控异常", "LAM-600", "L408",
       "贴合温度波动 ±8℃，产品出现气泡与脱胶",
       "加热管固态继电器接触不良", "温度传感器漂移",
       "传感器比对正常，继电器输出断续",
       "更换固态继电器", "重新整定温控参数",
       "温度稳定 85±2℃，连续 4 小时",
       [("device_model", "LAM-600"), ("param_range", "温度 ±8℃")]),
    sc("贴合机", "送料偏斜", "LAM-600", "L409",
       "来料进入贴合工位时偏斜 5°，导致贴合错位",
       "送料导轨宽度比料片宽 1.5mm，导向不足", "机械手取料位置偏差",
       "机械手重复定位精度 0.02mm 合格，导轨实测间隙过大",
       "调整导轨宽度至料片 +0.1mm", "增加侧向导向轮",
       "连续 200 片入料偏斜 ≤0.5°",
       [("device_model", "LAM-600"), ("param_range", "偏斜 5°")]),
    sc("贴合机", "静电吸附不良", "LAM-600", "L410",
       "薄片材料吸附不上平台，频繁掉落",
       "静电消除器失效，材料带电量过高", "真空吸附孔堵塞",
       "真空压力正常，静电电压实测 3.5kV（要求 ≤0.5kV）",
       "更换离子风机", "清洁吸附平台并检查接地",
       "静电电压 ≤0.3kV，连续 200 片无掉落",
       [("device_model", "LAM-600"), ("param_range", "静电 3.5kV")]),
    # 蚀刻机
    sc("蚀刻机", "蚀刻速率偏差", "ETCH-1200", "E501",
       "蚀刻深度 8μm（目标 12±1μm），速率偏低 30%",
       "蚀刻液温度偏低（实测 42℃，设定 50℃）", "蚀刻液浓度不足",
       "浓度滴定 180g/L 正常，温度实测偏低 8℃",
       "更换加热器并校准温控", "复测蚀刻速率",
       "深度 12.2μm，连续 5 批合格",
       [("device_model", "ETCH-1200"), ("param_range", "温度 42℃")]),
    sc("蚀刻机", "药水浓度异常", "ETCH-1200", "E502",
       "蚀刻液浓度持续下降，2 小时需补加 3 次",
       "补液泵计量不准（实际补加量偏少 40%）", "药水自然消耗加快",
       "用标准量杯实测补液 0.6L（设定 1.0L）",
       "校准补液泵流量", "更换泵管",
       "浓度稳定 180±5g/L，连续 8 小时",
       [("device_model", "ETCH-1200"), ("param_range", "浓度 180g/L")]),
    sc("蚀刻机", "喷嘴堵塞", "ETCH-1200", "E503",
       "蚀刻面出现条状未蚀刻区域",
       "喷嘴被结晶盐堵塞", "喷淋压力不足",
       "压力表读数正常，拆检 5 个喷嘴有结晶",
       "拆洗喷嘴并酸洗管路", "增加每班喷淋检查",
       "连续 100 片无未蚀刻区",
       [("device_model", "ETCH-1200"), ("process_stage", "喷淋段")]),
    sc("蚀刻机", "过蚀刻", "ETCH-1200", "E504",
       "蚀刻深度 15μm，超出上限，线路变细",
       "传送速度设定错误（比工艺卡快 15%）", "药水浓度过高",
       "浓度正常，实测传送速度与工艺卡不符",
       "修正传送速度参数", "增加换型首件确认",
       "深度 12±0.8μm，连续 3 批合格",
       [("device_model", "ETCH-1200"), ("param_range", "深度 15μm")]),
    sc("蚀刻机", "蚀刻不均", "ETCH-1200", "E505",
       "同片内蚀刻深度差 3μm（要求 ≤1μm）",
       "喷淋管部分孔位堵塞导致流量分布不均", "板材厚度不均",
       "同批板材厚度实测一致，喷淋流量分布偏差 25%",
       "疏通喷淋管并更换滤芯", "调整喷淋压力",
       "片内深度差 ≤0.8μm",
       [("device_model", "ETCH-1200"), ("param_range", "片内差 3μm")]),
    sc("蚀刻机", "传送轮污染", "ETCH-1200", "E506",
       "板面出现轮印状蚀刻不良",
       "传送轮表面附着蚀刻残渣", "板面清洁不彻底",
       "清洁板面后仍有轮印，轮面有明显残渣",
       "拆洗传送轮", "增加在线清洗周期",
       "连续 100 片无轮印",
       [("device_model", "ETCH-1200"), ("process_stage", "传送段")]),
    sc("蚀刻机", "腔体温度漂移", "ETCH-1200", "E507",
       "腔体温度在 48-54℃ 间波动，蚀刻深度不稳",
       "循环泵流量不足导致换热不均", "温控表故障",
       "温控表比对正常，循环流量实测 8L/min（要求 15L/min）",
       "更换循环泵叶轮", "清洗换热器",
       "温度 50±1℃，连续 8 小时",
       [("device_model", "ETCH-1200"), ("param_range", "流量 8L/min")]),
    sc("蚀刻机", "废液排放报警", "ETCH-1200", "E508",
       "废液液位高报警，设备停机",
       "液位传感器被结晶覆盖", "排放管路堵塞",
       "管路通畅，传感器表面有明显结晶",
       "清洁液位传感器", "增加自动冲洗",
       "连续 7 天无报警",
       [("device_model", "ETCH-1200"), ("process_stage", "废液段")]),
    sc("蚀刻机", "水洗残留", "ETCH-1200", "E509",
       "水洗后板面残留药水，出现白斑",
       "水洗喷淋压力不足（0.1MPa，要求 0.25MPa）", "水质不达标",
       "水质电导率正常，喷淋压力实测不足",
       "更换喷淋泵", "清理喷嘴",
       "板面残留检测合格，连续 5 批",
       [("device_model", "ETCH-1200"), ("param_range", "压力 0.1MPa")]),
    sc("蚀刻机", "腔体压力异常", "ETCH-1200", "E510",
       "腔体负压报警，抽风量不足",
       "抽风管路过滤器堵塞", "风机故障",
       "风机电流正常，过滤器压差 800Pa（要求 ≤300Pa）",
       "更换抽风过滤器", "清洁管路",
       "压差 ≤250Pa，连续 7 天正常",
       [("device_model", "ETCH-1200"), ("param_range", "压差 800Pa")]),
]

ALT2_POOL = ["来料批次差异", "车间温湿度波动", "上游工序参数偏移", "设备老化"]
LINE_POOL = ["1 号线", "2 号线", "3 号线", "5 号线"]
SHIFT_POOL = ["早班", "中班", "夜班"]
OP_POOL = ["张工", "李工", "王工", "赵工", "刘工"]

TYPO_MAP = [
    ("贴片机", "帖片机"), ("吸嘴", "吸咀"), ("锡膏", "锡高"), ("复测", "复侧"),
    ("校准", "校整"), ("参数", "参树"), ("异常", "异长"), ("供料器", "供料器"),
    ("传感器", "传感嚣"), ("偏移", "偏宜"), ("喷嘴", "喷咀"), ("报警", "报井"),
]


def _ctx(i):
    return LINE_POOL[i % len(LINE_POOL)], SHIFT_POOL[(i // 3) % 3], OP_POOL[(i // 5) % 5]


def build_formal(s, i, struct):
    line, shift, op = _ctx(i)
    alt2 = ALT2_POOL[i % len(ALT2_POOL)]
    code = f"（错误码 {s['code']}）" if s["code"] else ""
    if struct == "normal":
        return (
            f"报修描述：{line}{s['device']}（型号 {s['model']}）{s['symptom']}{code}。\n"
            f"排查记录：{op}接单后按点检表逐项检查，重点核查{s['cause']}相关部件；"
            f"{s['evidence']}，据此判定为{s['cause']}。\n"
            f"处理过程：①{s['m1']}；②{s['m2']}。\n"
            f"复测结论：{s['verify']}。\n"
            f"备注：{shift}记录，设备已恢复正常生产。"
        )
    if struct == "excluded":
        return (
            f"报修描述：{line}{s['device']}（型号 {s['model']}）{s['symptom']}{code}。\n"
            f"排查记录：{op}接单后先怀疑{s['alt']}，拆检并更换备件后复测，现象无任何改善，"
            f"排除{s['alt']}。随后继续排查，{s['evidence']}，定位为{s['cause']}。\n"
            f"处理过程：①{s['m1']}；②{s['m2']}。\n"
            f"复测结论：{s['verify']}。\n"
            f"备注：{shift}记录，已排除的假设在交接班记录中同步。"
        )
    # no_final
    return (
        f"报修描述：{line}{s['device']}（型号 {s['model']}）{s['symptom']}{code}，现象间歇出现。\n"
        f"排查记录：{op}接单后先怀疑{s['alt']}，更换备件并复测，现象未改善，排除{s['alt']}；"
        f"又怀疑{alt2}，核对批次与环境记录、调整后复测，现象同样未改善，排除{alt2}。\n"
        f"处理过程：已执行{s['m1']}与{s['m2']}，现象出现频率下降但未能完全消除。\n"
        f"复测结论：{s['verify']}（间歇复现，未取得可判定的复测数据）。\n"
        f"备注：暂未定位根因，已转厂家工程师跟进，设备降速运行观察，{shift}记录。"
    )


def build_colloquial(s, i, struct):
    line, shift, op = _ctx(i)
    head = f"{shift}交接班的时候，{line}{s['device']}又闹脾气了，{s['symptom']}，把{op}叫过去了。"
    if struct == "normal":
        return (head + f"过去一查，就是{s['cause']}。{s['m1']}，{s['m2']}，弄完再跑，"
                f"{s['verify']}，这才算完事。")
    if struct == "excluded":
        return (head + f"一开始都以为是{s['alt']}，拆了换了还是老样子，那就不关它事。"
                f"接着往下查，{s['evidence']}，才知道是{s['cause']}。{s['m1']}，{s['m2']}，"
                f"再跑起来{s['verify']}，收工。")
    alt2 = ALT2_POOL[i % len(ALT2_POOL)]
    return (head + f"先按{s['alt']}弄了一遍，没用；又猜是{alt2}，调了还是那样，两个都排除掉。"
            f"{s['m1']}、{s['m2']}也做了，好一点但没断根，后面还得叫厂家来看，先这么跑着。")


def build_missing(s, i, struct):
    line, shift, op = _ctx(i)
    text = build_formal(s, i, struct)
    # 去掉错误码、型号、具体数值与复测数据
    text = re.sub(r"（错误码 [A-Z]\d+）", "", text)
    text = re.sub(r"（型号 [^）]+）", "", text)
    text = re.sub(r"\d+(\.\d+)?\s*(kPa|lx|μm|mm|℃|MPa|N|%|°|g/L|L/min|Pa|cP|h)", "某数值", text)
    text = text.replace("复测结论：", "复测结论：已恢复生产，具体数据未记录，")
    if struct == "normal":
        text = text.replace("据此判定为", "估计是")
    return text.replace("备注：", "备注：现场记录不全，")


def build_typo(s, i, struct):
    text = build_formal(s, i, struct)
    k = 0
    for src, dst in TYPO_MAP:
        if src in text and (i + k) % 3 == 0:
            text = text.replace(src, dst, 1)
            k += 1
        if k >= 4:
            break
    return text


def build_long(s, i, struct):
    line, shift, op = _ctx(i)
    base = build_formal(s, i, struct)
    extra = (
        f"\n\n补充背景：该{line}近 3 天同类报警共 2 次，均在{shift}交接班前后出现，"
        f"本次为第 3 次。产线当日排产 4 个机型，{s['device']}承担其中 3 个机型的加工，"
        f"停线 1 小时影响产出约 600 片。\n"
        f"过程补充：{op}到场后先确认安全联锁与急停状态正常，再按《设备点检表》逐项核对："
        f"电控柜无报警、气路压力在范围内、润滑位正常、传动部件无异响；随后调阅设备运行日志，"
        f"对比报警前后 30 分钟的工艺参数曲线，发现与{s['topic']}相关的参数存在明显偏离。\n"
        f"进一步验证：为排除偶发因素，现场用标准件/标准板复测 3 次，结果一致，"
        f"确认不是测量误差；同时对同批次来料抽检 5 件，未发现来料异常，"
        f"由此把排查范围收敛到设备侧。\n"
        f"处置细节：{s['m1']}，作业前已挂牌上锁并确认能量隔离；{s['m2']}，"
        f"作业后按复位清单逐项复原，包括防护门、光栅、气压与程序版本核对。\n"
        f"效果确认：{s['verify']}；随后安排 2 小时跟线观察，未再复现。"
        f"已将该现象与处置方法记入设备履历，建议纳入下一版点检表。"
    )
    text = base + extra
    while len(text) < 520:
        text += "现场已按要求完成交接与记录，后续持续跟线观察。"
    return text


BUILDERS = {
    "formal": build_formal,
    "colloquial": build_colloquial,
    "missing": build_missing,
    "typo": build_typo,
    "long": build_long,
}


def make_plan(seed):
    """按 (设备, 风格) 单元格均衡分配结构：每格 40 条 = 12 含排除 / 4 仅排除 / 24 正常。"""
    rnd = random.Random(seed)
    plan = []
    idx = 0
    for d in DEVICES:
        for st in STYLES:
            cells = [("excluded", 12), ("no_final", 4), ("normal", 24)]
            structs = [x for x, n in cells for _ in range(n)]
            rnd.shuffle(structs)
            for sf in structs:
                plan.append(dict(device=d, style=st, struct=sf, idx=idx))
                idx += 1
    rnd.shuffle(plan)
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="docs/paper/问题二")
    ap.add_argument("--seed", type=int, default=20261106)
    ap.add_argument("--with-s1", action="store_true", help="额外调用 glm-4-flash 生成 S1 参考值")
    ap.add_argument("--s1-limit", type=int, default=0, help="S1 参考值条数上限，0=全部")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    plan = make_plan(args.seed)
    rnd = random.Random(args.seed + 1)

    by_device = {d: [s for s in SCEN if s["device"] == d] for d in DEVICES}
    rows, gold = [], []
    for k, p in enumerate(plan):
        pool = by_device[p["device"]]
        s = pool[k % len(pool)]
        builder = BUILDERS[p["style"]]
        text = builder(s, p["idx"], p["struct"])
        tid = f"T{k + 1:04d}"
        line, shift, op = _ctx(p["idx"])
        model = "" if p["style"] == "missing" else s["model"]
        code = "" if p["style"] == "missing" else s["code"]
        rows.append(dict(
            ticket_id=tid, device_type=s["device"], device_model=model,
            error_code=code, ticket_text=text,
            has_final_root_cause="", symptom="", symptom_evidence="",
            root_cause="", root_cause_evidence="", measures="",
            verification="", verification_evidence="", conditions="",
            excluded_hypotheses="", is_excluded_hypothesis="",
            unverified_hypotheses="", uncertain="", note="", label="",
        ))
        g = dict(
            ticket_id=tid, device_type=s["device"], device_model=model, error_code=code,
            topic=s["topic"], style=p["style"], structure=p["struct"],
            has_final_root_cause=0 if p["struct"] == "no_final" else 1,
            symptom=s["symptom"],
            root_cause="" if p["struct"] == "no_final" else s["cause"],
            root_cause_evidence="" if p["struct"] == "no_final" else s["evidence"],
            measures=[s["m1"], s["m2"]],
            verification=s["verify"],
            conditions=[dict(type=t, value=v) for t, v in s["cond"]],
            excluded_hypotheses=(
                [dict(hypothesis=s["alt"], evidence="更换备件后复测，现象未改善")]
                + ([] if p["struct"] != "no_final" else
                   [dict(hypothesis=ALT2_POOL[p["idx"] % len(ALT2_POOL)],
                         evidence="核对批次与环境记录并调整，复测未改善")])
                if p["struct"] in ("excluded", "no_final") else []),
            unverified_hypotheses=[],
            line=line, shift=shift, operator=op,
        )
        gold.append(g)

    csv_path = os.path.join(args.out_dir, "annotation_set_v1.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    gold_path = os.path.join(args.out_dir, "_gold_draft.jsonl")
    with open(gold_path, "w", encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    data = [dict(id=r["ticket_id"], device=r["device_type"], model=r["device_model"],
                 code=r["error_code"], text=r["ticket_text"]) for r in rows]
    with open(os.path.join(args.out_dir, "annotation_data.js"), "w", encoding="utf-8") as f:
        f.write("window.ANNOTATION_META = " + json.dumps(
            {"name": "问题二标注集 v1", "kind": "ticket", "count": len(data),
             "generated_by": "gen_seed_1000.py", "seed": args.seed}, ensure_ascii=False) + ";\n")
        f.write("window.ANNOTATION_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n")

    def cnt(key, val):
        return sum(1 for g in gold if g[key] == val)

    stats = dict(
        total=len(gold),
        by_device={d: cnt("device_type", d) for d in DEVICES},
        by_style={st: cnt("style", st) for st in STYLES},
        by_structure={
            "normal": cnt("structure", "normal"),
            "excluded": cnt("structure", "excluded"),
            "no_final": cnt("structure", "no_final"),
        },
        long_text_over_500=sum(1 for r in rows if len(r["ticket_text"]) > 500),
        min_text_len=min(len(r["ticket_text"]) for r in rows),
        max_text_len=max(len(r["ticket_text"]) for r in rows),
        avg_text_len=round(sum(len(r["ticket_text"]) for r in rows) / len(rows), 1),
        device_x_style={d: {st: sum(1 for g in gold if g["device_type"] == d and g["style"] == st)
                            for st in STYLES} for d in DEVICES},
    )
    with open(os.path.join(args.out_dir, "_dataset_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(json.dumps(stats, ensure_ascii=False, indent=2))

    if args.with_s1:
        gen_s1(rows, args.out_dir, args.s1_limit)


def gen_s1(rows, out_dir, limit):
    """调用 glm-4-flash 零样本抽取，产出 S1 参考值（工作台可选加载，默认关闭）。"""
    import urllib.request
    import urllib.error

    key = os.environ.get("ZHIPU_API_KEY", "")
    if not key and os.path.exists("/home/dev/secrets/zhipu_api_key"):
        key = open("/home/dev/secrets/zhipu_api_key", encoding="utf-8").read().strip()
    if not key:
        print("[s1] 未找到 ZHIPU_API_KEY，跳过", file=sys.stderr)
        return
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    prompt_tpl = (
        "你是SMT/精密电子设备维修专家。从下面的工单文本中抽取结构化信息，严格只输出 JSON："
        '{"symptom":"","root_cause":"","measures":[],"verification":"","conditions":[],'
        '"excluded_hypotheses":[],"has_final_root_cause":0}\n工单：\n'
    )
    out, n = [], len(rows) if limit <= 0 else min(limit, len(rows))
    for r in rows[:n]:
        body = json.dumps({"model": "glm-4-flash",
                           "messages": [{"role": "user", "content": prompt_tpl + r["ticket_text"]}],
                           "temperature": 0.1}, ensure_ascii=False).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + key)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                obj = json.loads(resp.read().decode())
            c = obj["choices"][0]["message"]["content"]
            a, b = c.find("{"), c.rfind("}")
            out.append({"ticket_id": r["ticket_id"],
                        "suggestion": json.loads(c[a:b + 1]) if a >= 0 else {}})
        except Exception as e:
            print(f"[s1] {r['ticket_id']} 失败: {e}", file=sys.stderr)
        time.sleep(0.2)
    with open(os.path.join(out_dir, "s1_suggestions.jsonl"), "w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(f"[s1] 已生成 {len(out)} 条参考值 -> s1_suggestions.jsonl")


if __name__ == "__main__":
    main()
