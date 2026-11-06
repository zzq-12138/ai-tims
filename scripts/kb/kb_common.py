#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库扩容公共模块（问题二）。

- 七字段：现象 / 根因 / 处置步骤 / 预防 / 验证结果 / 适用条件 / 来源标注
- 内容结构：全部写进现有 kb_knowledge.content（不改表结构，DEC-11）
- 成组关系：cluster_key + cluster_type（同象异因 / 同因异象）
- 合成语料：设备名与型号均为通用描述，不含真实企业/客户/产线标识
"""

SUBSYSTEMS = [
    "机械传动", "真空气路", "视觉光学", "电气传感",
    "工艺参数", "温控热工", "软件通讯", "清洁保养",
]

# 每类设备的适用条件口径（通用描述，不指向真实厂商）
DEVICE_PARAMS = {
    "贴片机": {
        "models": "多轴拱架式贴片机（通用机型，0305/0402 元件平台）",
        "fw": "设备软件 V6.x 及以上、贴装头固件 V2.x",
        "batch": "0402–QFP 44×44 mm 元件批次，锡膏 Type4",
        "env": "车间 23±3℃、RH 40–60%，线速 ≤60 s/片",
    },
    "AOI检测机": {
        "models": "3D 离线/在线 AOI（通用机型，5 MP 以上相机）",
        "fw": "检测软件 V4.x 及以上、算法库 V3.x",
        "batch": "PCB 板厚 0.4–3.2 mm，最小焊盘 0.2 mm",
        "env": "产线节拍 ≤45 s/片，环境照度 ≤800 lx",
    },
    "涂布机": {
        "models": "狭缝/微凹辊涂布机（通用机型，幅宽 ≤650 mm）",
        "fw": "PLC 程序 V2.x、张力控制固件 V1.x",
        "batch": "箔材 8–20 μm 涂层、浆料黏度 2000–6000 mPa·s",
        "env": "洁净度 Class 1000、温度 23±2℃",
    },
    "贴合机": {
        "models": "辊式/片式贴合机（通用机型，贴合宽度 ≤600 mm）",
        "fw": "控制软件 V3.x、伺服固件 V1.x",
        "batch": "光学胶 25–100 μm、离型膜批次",
        "env": "环境 23±2℃、RH 45–55%，无尘 Class 1000",
    },
    "蚀刻机": {
        "models": "水平线蚀刻机（通用机型，单/双面喷淋）",
        "fw": "PLC 程序 V2.x、药液控制模块 V1.x",
        "batch": "药液批次（酸性/碱性体系按现场工艺卡）、铜厚 8–35 μm",
        "env": "线速 1.2–3.0 m/min、槽液温度按工艺卡 ±2℃",
    },
    "回流焊": {
        "models": "十温区热风回流焊（通用机型，双通道网带）",
        "fw": "温控软件 V5.x、链条传动固件 V1.x",
        "batch": "SAC305 锡膏批次、PCB 板厚 0.6–3.2 mm",
        "env": "氮气模式 O2 ≤1000 ppm、链速 60–100 cm/min",
    },
    "MES终端": {
        "models": "MES 客户端/产线网关（通用部署，浏览器+客户端双模式）",
        "fw": "服务端 2.x、客户端 1.8.x、网关固件 V1.x",
        "batch": "单厂区 ≤200 终端、报工峰值 ≤500 次/min",
        "env": "厂区局域网、链路丢包率 ≤0.1%",
    },
    "SPI锡膏检测机": {
        "models": "3D SPI 锡膏检测机（通用机型，结构光/激光三角）",
        "fw": "检测软件 V4.x、标定库 V2.x",
        "batch": "锡膏 Type4/5、钢板厚度 0.10–0.15 mm",
        "env": "产线节拍 ≤30 s/片、环境温度 23±3℃",
    },
    "波峰焊": {
        "models": "全程/选择性波峰焊（通用机型，双波峰）",
        "fw": "控制软件 V3.x、锡炉温控固件 V1.x",
        "batch": "SAC305 焊料批次、助焊剂固体含量 3–5%",
        "env": "预热 90–120℃、锡炉 255±5℃、链速 0.8–1.5 m/min",
    },
    "X-Ray检测机": {
        "models": "微焦点 X-Ray 检测机（通用机型，闭管 90–130 kV）",
        "fw": "成像软件 V3.x、运动控制固件 V1.x",
        "batch": "BGA/CSP 焊点、板厚 ≤4 mm、铜厚 8–35 μm",
        "env": "管电压 80–130 kV、管电流 100–300 μA、环境 23±3℃",
    },
}

# 子系统级处置步骤模板（{part}/{metric}/{spec}/{symptom}）
STEP_TEMPLATES = {
    "机械传动": [
        "停机并断开动力源，执行上锁挂牌；记录“{symptom}”首次出现的工位、批次与累计次数",
        "清洁 {part} 并检查磨损、间隙与紧固状态，用 {metric} 实测，超出 {spec} 即更换或调整",
        "按手册扭矩复紧连接件，执行原点回归与空载 3 个循环，确认无爬行、无卡滞",
        "带料运行 20 件，复测 {metric} 并记入设备点检表",
    ],
    "真空气路": [
        "停止取放动作，关闭气源并泄压，确认压力表回落至 0",
        "检查 {part} 的滤芯、接头与管路，排水排油后用 {metric} 实测，低于 {spec} 时按“滤芯→密封→真空发生器”顺序排查",
        "更换堵塞滤芯或破损密封圈，做 5 min 保压测试，压降不超过 0.01 MPa",
        "空载吸取 30 次、带料 20 件，统计吸取失败次数并记录",
    ],
    "视觉光学": [
        "暂停检测并保留当班原图与判定日志，避免覆盖现场",
        "清洁 {part} 的镜头、光源窗口与保护玻璃，检查有无划伤或雾化",
        "用标准件重做标定，使 {metric} 回到 {spec} 范围内",
        "用 20 片标准板复测，误判与漏判均应为 0 后再恢复生产",
    ],
    "电气传感": [
        "断电挂牌，记录报警代码、发生时刻与复位次数",
        "检查 {part} 的接线、屏蔽与供电，测量 {metric}，偏离 {spec} 即更换或重新压接",
        "更换后执行回零与自检，确认无间歇性报警与信号抖动",
        "连续运行 2 h，观察报警记录与信号波形",
    ],
    "工艺参数": [
        "冻结当前配方并导出参数快照，记录配方号与生效时间",
        "核对 {part} 的设定值与实际值，按 {metric} 与 {spec} 比对，偏差超过 5% 先查执行机构",
        "小批量试产 20 件，按 5% 步进回调参数，禁止一次性大幅修改",
        "连续 3 批检测 {metric}，确认落在 {spec} 且过程能力 Cpk≥1.33",
    ],
    "温控热工": [
        "降温至安全温度后作业，拆装加热部件前必须断电并挂牌确认无残压",
        "用校准过的测温仪核对 {part} 显示值与实测值，偏差超出 {spec} 即校准或更换",
        "检查加热器、热电偶、风道/水路与保温层，清理积尘与结垢",
        "空载升温至设定值保温 20 min，再带料测 3 点温度曲线",
    ],
    "软件通讯": [
        "保存日志与配置快照，记录发生时间窗、影响终端数与错误码",
        "检查 {part} 的连接、版本与配置一致性，核对 {metric}",
        "按“网络→服务→客户端”顺序重启相关组件，并回放一次完整业务流程",
        "观察 2 h 或 3 个报工周期，确认无超时、无重复提交",
    ],
    "清洁保养": [
        "停机并做防污染隔离，准备无尘布与专用清洁剂",
        "按保养卡清洁 {part}，检查 {metric} 是否回到 {spec}",
        "更换到期耗材/滤材，记录耗材批次与安装寿命",
        "运行 30 min 确认无异常，更新点检记录并签字",
    ],
}

PREVENTION_TEMPLATES = {
    "机械传动": "每 500 h 或每月对 {part} 做润滑、紧固与间隙点检；传动件按 8000 h 寿命强制更换。",
    "真空气路": "每班排水、每周查滤芯压差，压差 >0.05 MPa 即更换；气源露点控制在 -20℃ 以下。",
    "视觉光学": "每班用无尘布清洁光学窗口，每月用标准件标定一次并留存标定记录。",
    "电气传感": "每季度紧固端子、检查屏蔽接地（接地电阻 <4Ω）；备件按批次抽检后入库。",
    "工艺参数": "配方变更走审批与首件确认；每批记录关键参数，连续 3 点偏离 3σ 即停线复核。",
    "温控热工": "每月校准热电偶、每季度清理风道/水路；超温保护每月点检一次。",
    "软件通讯": "变更前备份配置并灰度发布；监控接口 P95 与错误率，超阈值自动告警。",
    "清洁保养": "按保养卡执行日/周/月清洁，洁净度与耗材寿命纳入班组长点检。",
}

VERIFY_TEMPLATES = {
    "机械传动": "{metric} 复测落在 {spec}；连续 3 个批次（不少于 60 min）未再出现“{symptom}”，点检表连续 5 点无超差。",
    "真空气路": "保压 5 min 压降 ≤0.01 MPa；空载吸取 30 次失败 ≤1 次、带料 20 件抛料为 0，{metric} 稳定在 {spec}。",
    "视觉光学": "标准件标定后 {metric} 落在 {spec}；20 片标准板复测误判与漏判均为 0。",
    "电气传感": "连续运行 2 h 无同类报警，{metric} 处于 {spec}，报警日志与波形无异常尖峰。",
    "工艺参数": "连续 3 批 {metric} 落在 {spec} 且 Cpk≥1.33；首件与末件差值不超过规格的 20%。",
    "温控热工": "空载保温 20 min 后实测温度与设定值偏差在 {spec}；带料 3 点曲线连续 3 批无超温。",
    "软件通讯": "2 h 或 3 个报工周期内超时为 0、重复记录为 0；接口 P95 回到基线范围内。",
    "清洁保养": "清洁后 {metric} 回到 {spec}；连续运行 30 min 无异常，抽检 5 件外观合格。",
}

DEFAULT_DISCRIMINATION = (
    "先确认 {metric} 是否在 {spec}：正常则查上游来料与工艺参数，"
    "异常则按“{part} 污染/磨损 → 执行机构 → 传感反馈”顺序逐项排除，"
    "每排除一项记录一次实测值，避免同时改动多个变量。"
)

FORBIDDEN_WORDS = [
    "富士", "西门子", "松下", "雅马哈", "欧姆龙", "三星电机", "ASM", "Fuji",
    "Siemens", "Panasonic", "Yamaha", "Omron", "Koh Young", "Mirtec", "Saki",
    "CyberOptics", "Nordson", "Desen", "客户", "产线A", "某公司", "有限公司",
]

DANGEROUS_PATTERNS = ["带电拆", "短接", "旁路急停", "屏蔽联锁", "拆除安全", "强制短接", "绕过安全"]


def render_steps(entry):
    """返回 1)..4) 的步骤串；条目可显式给 steps 覆盖。"""
    if entry.get("steps"):
        items = entry["steps"]
        if isinstance(items, str):
            return items
        return "；".join("%d) %s" % (i + 1, s) for i, s in enumerate(items))
    tpl = STEP_TEMPLATES[entry["subsystem"]]
    return "；".join("%d) %s" % (i + 1, s.format(**entry)) for i, s in enumerate(tpl))


def render_prevention(entry):
    if entry.get("prevention"):
        return entry["prevention"]
    return PREVENTION_TEMPLATES[entry["subsystem"]].format(**entry)


def render_verification(entry):
    if entry.get("verification"):
        return entry["verification"]
    return VERIFY_TEMPLATES[entry["subsystem"]].format(**entry)


def render_conditions(entry, device_params):
    if entry.get("conditions"):
        return entry["conditions"]
    p = device_params
    extra = entry.get("condition_extra", "")
    base = "适用机型：%s；软件/固件：%s；来料/工艺批次：%s；工况：%s" % (
        p["models"], p["fw"], p["batch"], p["env"])
    return base + ("；" + extra if extra else "") + "。"


def render_content(entry, device_params):
    parts = [
        "故障现象：" + entry["symptom"],
        "可能原因（根因）：" + entry["cause"],
        "区分依据：" + entry["disc"],
        "处理步骤：" + render_steps(entry),
        "预防措施：" + render_prevention(entry),
        "验证结果：" + render_verification(entry),
        "适用条件：" + render_conditions(entry, device_params),
    ]
    return "\n".join(parts)


def check_safety(text):
    # “客户端”是通用技术名词，不构成企业标识，匹配前剔除
    norm = text.replace("客户端", "")
    hits = []
    for w in FORBIDDEN_WORDS:
        if w in norm:
            hits.append(w)
    for w in DANGEROUS_PATTERNS:
        if w in norm:
            hits.append(w)
    return hits
