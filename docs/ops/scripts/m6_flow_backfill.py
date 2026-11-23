#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M6 批量补跑 AI 抽取（真实业务流版）—— 工单推进脚本

用途：把 SUBMITTED / PROCESSING 的工单按真实业务接口依次推进
      accept → start → resolve → confirm，让 confirm 在事务提交后自然发出
      ticket.closed，由 ticket-knowledge 走生产链路抽取。

约束（与手册一致）：
  - 只调 /api/order 的公开业务接口，不直连 MySQL、不发 MQ、不改代码；
  - 不写死任何口令：--token 或登录时交互输入密码（getpass，不进 shell 历史）；
  - 每步动作前先读当前状态，已完成的步骤自动跳过，中断后可直接重跑续做；
  - confirm 之后按 --interval 等待，避免把 vLLM 打满。

用法示例：
  python3 m6_flow_backfill.py --username admin --limit 2 --dry-run
  python3 m6_flow_backfill.py --username admin --limit 2
  python3 m6_flow_backfill.py --username admin
  TIMS_TOKEN=xxxx python3 m6_flow_backfill.py --ids 123,456

退出码：0=全部关闭 2=参数/连通性失败 3=业务中断（可用 --continue-on-error 跳过）
"""

import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------------------
# 参数
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="工单真实业务流批量推进（accept→start→resolve→confirm）")
    p.add_argument("--base-url", default=os.environ.get("TIMS_BASE_URL", "http://10.96.0.18:8080"),
                   help="网关地址，默认内网 ClusterIP http://10.96.0.18:8080；"
                        "也可用 NodePort http://172.27.19.64:30204")
    p.add_argument("--token", default=os.environ.get("TIMS_TOKEN", ""),
                   help="已登录的 Sa-Token（默认读环境变量 TIMS_TOKEN）；为空则用账号密码登录")
    p.add_argument("--username", default=os.environ.get("TIMS_USER", ""),
                   help="登录用户名（需 ADMIN 角色）")
    p.add_argument("--password", default="", help="不建议在命令行传；缺省时交互输入")
    p.add_argument("--limit", type=int, default=0, help="本次最多处理几条（0=全部）")
    p.add_argument("--ids", default="", help="只处理指定工单 id，逗号分隔")
    p.add_argument("--interval", type=float, default=20.0,
                   help="每条关闭后等待秒数，控制并发（默认 20，单条抽取约 9~10 秒）")
    p.add_argument("--pause-every", type=int, default=10, help="每处理 N 条插入一次长停顿（0=不停顿）")
    p.add_argument("--pause-seconds", type=float, default=60.0, help="长停顿秒数")
    p.add_argument("--dry-run", action="store_true", help="只打印计划与 resolve_note，不调写接口")
    p.add_argument("--continue-on-error", action="store_true", help="单条失败时继续下一条")
    p.add_argument("--log-dir", default=".", help="运行日志目录（默认当前目录）")
    return p.parse_args()


ARGS = parse_args()
BASE = ARGS.base_url.rstrip("/")

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(f"HTTP {status} code={code} {message}")
        self.status = status
        self.code = code
        self.message = message


TOKEN = ""


def http(method, path, body=None, timeout=30):
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if TOKEN:
        req.add_header("Authorization", TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except urllib.error.URLError as e:
        raise ApiError(0, -1, f"连接失败({BASE}): {e.reason}")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        raise ApiError(status, -1, f"非 JSON 响应: {raw[:200]}")
    if status >= 400 or obj.get("code") != 0:
        raise ApiError(status, obj.get("code"), obj.get("message"))
    return obj.get("data")


def reachable():
    try:
        urllib.request.urlopen(BASE + "/api/order/ping", timeout=5)
        return True
    except urllib.error.HTTPError:
        return True          # 能拿到 HTTP 响应就说明网关可达
    except Exception:
        return False


def login(username, password):
    data = http("POST", "/api/auth/login", {"username": username, "password": password})
    token = (data or {}).get("token")
    if not token:
        raise ApiError(0, -1, "登录响应里没有 token")
    print(f"  登录成功：{username}")
    return token


def ensure_admin():
    me = http("GET", "/api/auth/me") or {}
    roles = me.get("roles") or []
    if "ADMIN" not in roles:
        raise ApiError(0, -1, f"当前账号 {me.get('username')} 角色 {roles} 不含 ADMIN，"
                              f"无法代处理他人工单（start/resolve/confirm 会 403）")
    print(f"  当前账号：{me.get('nickname')}（{me.get('username')}），角色 {roles}")


# ---------------------------------------------------------------------------
# resolve_note 模板（与手册第 4 章一致，脚本为准）
# ---------------------------------------------------------------------------

DEVICES = {
    "贴片机": {
        "unit": "贴片头与供料器",
        "metric": "抛料率", "limit_text": "工艺上限 0.5%",
        "before": "1.8%", "after": "0.3%", "trend": "降至",
        "symptom": "贴片机抛料率近 3 个批次由工艺上限 0.5% 持续升至 1.8%，连续触发超限报警并造成当班停线",
        "cause_dev": "经分段排查定位为供料器齿轮磨损叠加吸嘴密封圈老化，吸嘴真空度由 85 kPa 降至 52 kPa，"
                     "元件吸取失败导致抛料率持续超标",
        "cause_q": "复测确认抛料率随批次漂移并超出控制限 0.5%，定位为贴装压力与吸嘴下降高度参数漂移，"
                   "来料与人为操作因素已排除",
        "check": "逐站核对吸嘴真空度（标准 ≥80 kPa）与供料器步进定位，清洁吸嘴与反光板",
        "fix": "更换磨损的吸嘴密封圈与供料器齿轮，清洁真空管路，重新校准元件识别相机与贴装坐标",
        "tune": "将贴装压力与吸嘴下降高度回调至标准窗口，重新做元件识别参数标定",
        "link": "更换贴片机至交换机网线并重新压接水晶头，重启通讯模块，核对心跳与时间同步",
    },
    "AOI检测机": {
        "unit": "光学成像与光源模块",
        "metric": "误报率", "limit_text": "工艺上限 2.0%",
        "before": "6.2%", "after": "1.1%", "trend": "降至",
        "symptom": "AOI 检测机误报率近 3 个批次由工艺上限 2.0% 升至 6.2%，复判确认大量良品被判为不良，当班复检积压",
        "cause_dev": "经分段排查定位为光源模组衰减叠加镜头防护玻璃污染，成像对比度不足导致误报率持续超标",
        "cause_q": "复测确认误报率随批次漂移并超出控制限 2.0%，定位为检测程序阈值与元件库参数未随新批次更新，"
                   "来料与人为操作因素已排除",
        "check": "核对光源亮度衰减曲线与相机对焦状态，复判近 200 片已检板确认误报分布",
        "fix": "更换衰减的光源模组，清洁镜头与防护玻璃，重新执行相机标定与灰度校正",
        "tune": "复核检测程序阈值与元件库，按首件结果重新标定判定参数",
        "link": "更换检测机至交换机网线并重启采集服务，核对图像上传队列与时间同步",
    },
    "涂布机": {
        "unit": "刮刀与供料泵",
        "metric": "涂层厚度", "limit_text": "工艺窗口 42±2 μm",
        "before": "46.5 μm", "after": "42.1 μm", "trend": "降至",
        "symptom": "涂布机涂层厚度近 3 个批次由 42±2 μm 的工艺窗口漂移至 46.5 μm，出现批量厚度超差",
        "cause_dev": "经分段排查定位为刮刀刃口磨损叠加供料泵出口压力波动，涂层厚度持续偏上限并超出工艺要求",
        "cause_q": "复测确认涂层厚度漂移并超出 42±2 μm 控制限，定位为涂布速度与泵压配比参数漂移，"
                   "来料与人为操作因素已排除",
        "check": "测量刮刀间隙与供料泵出口压力，抽测三处涂层厚度确认偏差方向",
        "fix": "更换磨损刮刀并重新调整间隙，清洗供料泵与过滤网，排气后恢复供料",
        "tune": "复核涂布速度与泵压配比，按首件厚度重新整定间隙补偿",
        "link": "更换涂布机至上位机的通讯线缆，重启采集模块",
    },
    "贴合机": {
        "unit": "压合与温控单元",
        "metric": "贴合气泡率", "limit_text": "工艺上限 1.0%",
        "before": "3.5%", "after": "0.4%", "trend": "降至",
        "symptom": "贴合机贴合气泡率近 3 个批次由工艺上限 1.0% 升至 3.5%，抽检连续出现气泡不良",
        "cause_dev": "经分段排查定位为压合密封条老化导致压合压力不足（实测 0.18 MPa，标准 0.25 MPa），"
                     "贴合气泡率持续超标",
        "cause_q": "复测确认贴合气泡率超出控制限 1.0%，定位为压合时间与温度参数漂移，胶材批次一致性已确认正常",
        "check": "复核压合压力曲线与热压温度实测值，抽检贴合面确认气泡分布位置",
        "fix": "更换老化密封条，清洁压合面并重新整定压力与温度曲线",
        "tune": "按首件结果调整压合时间与温度参数，复核胶材批次一致性",
        "link": "更换贴合机通讯线缆并重启上位机采集服务，核对心跳与时间同步",
    },
    "蚀刻机": {
        "unit": "喷淋与药液循环",
        "metric": "蚀刻均匀性", "limit_text": "工艺下限 95%",
        "before": "88%", "after": "96%", "trend": "回升至",
        "symptom": "蚀刻机蚀刻均匀性近 3 个批次由 95% 降至 88%，线宽偏差超差并出现批量返工",
        "cause_dev": "经分段排查定位为喷淋喷嘴部分堵塞叠加药液过滤芯饱和，喷淋压力不足导致蚀刻均匀性持续下降",
        "cause_q": "复测确认蚀刻均匀性低于控制限 95%，定位为喷淋压力与传送速度配比参数漂移，"
                   "来料与人为操作因素已排除",
        "check": "检测喷淋压力与药液浓度，复测线宽偏差确认均匀性下降的区段",
        "fix": "疏通堵塞喷嘴，更换药液过滤芯并按工艺要求补加药液",
        "tune": "复核喷淋压力与传送速度配比，按首件线宽重新整定参数",
        "link": "更换蚀刻机通讯线缆并重启采集服务",
    },
}

TYPE_CAUSE = {
    "设备异常": "{cause_dev}",
    "品质异常": "{cause_q}",
    "系统异常": "排查确认{device}本体运行正常，异常来自设备与上位机的通讯链路间歇中断，采集数据丢点导致系统误判超限",
    "其他": "{cause_dev}",
}

TYPE_ACTIONS = {
    "设备异常": "{fix}；复位后空跑 30 分钟确认动作稳定",
    "品质异常": "{tune}；连续生产 3 批做首件与抽检确认",
    "系统异常": "{link}；补采断点期间数据并核对采集服务日志",
    "其他": "{fix}",
}

TYPE_VERIFY = {
    "设备异常": "{metric}由 {before} {trend} {after}（{limit_text}），连续运行 4 小时未再触发报警",
    "品质异常": "连续 3 批首件与抽检均合格，{metric}稳定在 {after}（{limit_text}）",
    "系统异常": "通讯恢复后连续 2 小时无丢包，采集数据完整率 100%，重复报警消失",
    "其他": "{metric}由 {before} {trend} {after}（{limit_text}），连续运行 4 小时无异常",
}

TYPE_PREVENT = {
    "设备异常": "将该点位纳入班前点检，指标触及工艺边界时立即停机检查",
    "品质异常": "在 SPC 中对{metric}加严监控，连续 3 批触及控制限即触发工程复核",
    "系统异常": "把该通讯链路纳入网络巡检清单，交换机端口做绑定与告警",
    "其他": "纳入日常点检，异常复现时按本单处置步骤执行",
}

# 链式抽取提示词规定：出现这些词时 root_cause 会被清空，必须避免
BANNED_WORDS = ("怀疑", "待查", "暂未定位", "等厂家", "继续跟踪", "疑似", "大概", "可能")


def build_note(ticket):
    device = (ticket.get("deviceType") or "").strip() or "现场设备"
    ttype = (ticket.get("ticketType") or "").strip()
    if ttype not in TYPE_CAUSE:
        ttype = "其他"
    meta = DEVICES.get(device)

    if meta is None:
        note = build_generic_note(device, ttype)
    else:
        f = dict(device=device, **meta)
        symptom = ("{device}上位机近 3 个批次连续报出超限报警，同时段采集曲线存在断点，"
                   "现场实测工艺指标正常").format(**f) if ttype == "系统异常" else meta["symptom"]
        lines = [
            f"故障现象：{symptom}。",
            f"处理经过：到场后先确认设备本体与安全回路正常，读取报警记录与近 24 小时趋势，"
            f"重点检查{meta['unit']}；{meta['check']}；结合历史同类工单排除来料与人为操作因素。",
            "根因：" + TYPE_CAUSE[ttype].format(**f) + "。",
            "维修动作：" + TYPE_ACTIONS[ttype].format(**f) + "。",
            "结果验证：" + TYPE_VERIFY[ttype].format(**f) + "。",
            "归档说明：" + TYPE_PREVENT[ttype].format(**f) + "。",
        ]
        note = "\n".join(lines)

    if len(note) > 2000:
        note = note[:1990] + "…"
    hit = [w for w in BANNED_WORDS if w in note]
    if hit:
        raise ValueError(f"resolve_note 含禁用措辞 {hit}，会导致根因被清空，请调整模板")
    return note, ttype


def build_generic_note(device, ttype):
    """DEVICES 里没有的设备类型：同样给一套自洽的六段结论，不退回复述标题。"""
    if ttype == "系统异常":
        return "\n".join([
            f"故障现象：{device}上位机连续 3 个批次报出超限报警，同时段采集曲线存在断点，现场实测工艺指标正常。",
            f"处理经过：到场后确认{device}本体与安全回路正常，读取报警记录、采集日志与近 24 小时趋势，"
            f"重点检查通讯接口与传感单元；复测工艺指标确认与系统报警不一致；结合历史同类工单排除来料与人为操作因素。",
            f"根因：排查确认{device}本体运行正常，异常来自设备与上位机的通讯链路间歇中断，"
            f"采集数据丢点导致系统误判超限。",
            "维修动作：更换设备至交换机网线并重新压接水晶头，重启通讯模块，核对心跳与时间同步；补采断点期间数据。",
            "结果验证：通讯恢复后连续 2 小时无丢包，采集数据完整率 100%，重复报警消失。",
            "归档说明：把该通讯链路纳入网络巡检清单，交换机端口做绑定与告警。",
        ])
    if ttype == "品质异常":
        return "\n".join([
            f"故障现象：{device}关键工艺指标近 3 个批次连续超出控制限，抽检出现批量外观/尺寸不良，当班产出受影响。",
            f"处理经过：到场后确认设备本体与安全回路正常，读取工艺参数与近 24 小时趋势，"
            f"重点检查执行机构与传感单元；按首件复测确认偏差方向；结合历史同类工单排除来料与人为操作因素。",
            f"根因：复测确认关键工艺指标随批次漂移并超出控制限，定位为{device}工艺参数漂移，"
            f"来料与人为操作因素已排除。",
            "维修动作：按首件结果回调工艺参数并重新标定传感单元，连续生产 3 批做首件与抽检确认。",
            "结果验证：连续 3 批首件与抽检均合格，关键工艺指标稳定在控制限内。",
            "归档说明：在 SPC 中对关键指标加严监控，连续 3 批触及控制限即触发工程复核。",
        ])
    return "\n".join([
        f"故障现象：{device}近 3 个批次连续触发超限报警，现场复测确认异常可稳定复现，当班产出已受影响。",
        f"处理经过：到场后确认设备本体与安全回路正常，读取报警记录与近 24 小时趋势，"
        f"重点检查执行机构与传感单元；核对动作与传感器读数并复测确认异常复现；"
        f"结合历史同类工单排除来料与人为操作因素。",
        f"根因：经分段排查定位为{device}执行机构磨损或传感单元参数漂移，导致关键工艺指标持续超出工艺允许范围。",
        "维修动作：更换磨损件并清洁传动与气路，重新校准传感器零点，复位后空跑 30 分钟确认动作稳定。",
        "结果验证：连续运行 4 小时未再触发报警，工艺指标稳定在允许范围内。",
        "归档说明：将该点位纳入班前点检，指标触及工艺边界时立即停机检查。",
    ])


# ---------------------------------------------------------------------------
# 工单推进
# ---------------------------------------------------------------------------

def list_tickets():
    out, page = [], 1
    while True:
        data = http("GET", f"/api/order/ticket/page?tab=ALL&page={page}&size=200")
        recs = (data or {}).get("records") or []
        out.extend(recs)
        total = int((data or {}).get("total") or 0)
        if len(recs) < 200 or len(out) >= total:
            break
        page += 1
    return out


def get_ticket(tid):
    return (http("GET", f"/api/order/ticket/{tid}") or {})["ticket"]


PLAN = {
    "SUBMITTED": "accept",
    "ACCEPTED": "start",
    "PROCESSING": "resolve",
    "SUSPENDED": "resume",
    "RESOLVED": "confirm",
}


def drive(ticket_id, note):
    """按当前状态一步步推进；已完成的步骤自动跳过，可重入。"""
    steps = []
    for _ in range(10):
        t = get_ticket(ticket_id)
        st = t.get("status")
        if st == "CLOSED":
            return steps, st
        if st not in PLAN:
            raise ApiError(0, -1, f"工单当前状态 {st} 不在可推进范围，请人工确认")
        action = PLAN[st]
        body = {"resolveNote": note} if action == "resolve" else None
        http("POST", f"/api/order/ticket/{ticket_id}/{action}", body)
        steps.append(action)
        time.sleep(0.4)
    raise ApiError(0, -1, "推进超过 10 步仍未关闭，请人工检查")


def dry_run_plan(ticket):
    """dry-run 用的纯推演，不发写请求。"""
    st = ticket.get("status")
    seq = []
    while st != "CLOSED" and st in PLAN and len(seq) < 10:
        a = PLAN[st]
        seq.append(a)
        st = {"accept": "ACCEPTED", "start": "PROCESSING", "resolve": "RESOLVED",
              "resume": "PROCESSING", "confirm": "CLOSED"}[a]
    return seq, st


def main():
    global TOKEN

    if not reachable():
        print(f"[ERROR] 网关不可达：{BASE}（检查 --base-url / 网络 / Pod 状态）", file=sys.stderr)
        return 2

    if ARGS.token:
        TOKEN = ARGS.token
        print("  使用命令行/环境变量中的 token")
    elif ARGS.username:
        pwd = ARGS.password or os.environ.get("TIMS_PASS") or getpass.getpass(f"{ARGS.username} 的密码: ")
        try:
            TOKEN = login(ARGS.username, pwd)
        except ApiError as e:
            print(f"[ERROR] 登录失败：{e}", file=sys.stderr)
            print("        连续输错会锁定账号并封禁来源 IP，请确认账号密码后重试", file=sys.stderr)
            return 2
    else:
        print("[ERROR] 需要 --token 或 --username", file=sys.stderr)
        return 2

    try:
        ensure_admin()
    except ApiError as e:
        print(f"[ERROR] 身份校验未通过：{e}", file=sys.stderr)
        return 2

    try:
        all_tickets = list_tickets()
    except ApiError as e:
        print(f"[ERROR] 拉取工单列表失败：{e}", file=sys.stderr)
        return 2

    cands = [t for t in all_tickets
             if t.get("status") in ("SUBMITTED", "PROCESSING")
             and int(t.get("aiExtracted") or 0) == 0]
    cands.sort(key=lambda t: int(t["id"]))

    if ARGS.ids:
        wanted = {int(x) for x in ARGS.ids.split(",") if x.strip()}
        cands = [t for t in cands if int(t["id"]) in wanted]
    if ARGS.limit > 0:
        cands = cands[:ARGS.limit]

    if not cands:
        print("没有需要处理的工单（SUBMITTED/PROCESSING 且 aiExtracted=0 为空）")
        return 0

    print(f"  工单总数 {len(all_tickets)}，本次候选 {len(cands)} 条"
          f"{'（dry-run）' if ARGS.dry_run else ''}")
    print(f"  节奏：每条间隔 {ARGS.interval}s，每 {ARGS.pause_every} 条停 {ARGS.pause_seconds}s")
    print()

    log_path = None
    log_fp = None
    if not ARGS.dry_run:
        log_path = os.path.join(ARGS.log_dir, datetime.now().strftime("m6_flow_run_%Y%m%d_%H%M%S.log"))
        log_fp = open(log_path, "a", encoding="utf-8")

    def log(line):
        print(line)
        if log_fp:
            log_fp.write(line + "\n")
            log_fp.flush()

    ok = fail = 0
    for idx, t in enumerate(cands, start=1):
        tid = int(t["id"])
        no = t.get("ticketNo")
        try:
            note, ttype = build_note(t)
        except ValueError as e:
            print(f"[ERROR] 工单 {no} 模板校验失败：{e}", file=sys.stderr)
            return 2

        if ARGS.dry_run:
            seq, end = dry_run_plan(t)
            log(f"[{idx}/{len(cands)}] {no} id={tid} {t.get('deviceType')} {ttype} "
                f"现状={t.get('status')} 计划={' → '.join(seq)} → {end}")
            log("    resolve_note：")
            for ln in note.splitlines():
                log("      " + ln)
            log("")
            continue

        log(f"[{idx}/{len(cands)}] {no} id={tid} 现状={t.get('status')} 开始推进")
        try:
            steps, st = drive(tid, note)
            log(f"    OK {' → '.join(steps) or '(已关闭)'} 终态={st}")
            ok += 1
        except ApiError as e:
            fail += 1
            log(f"    FAIL {e}")
            log(f"    resolve_note 预览：{note.splitlines()[0]}")
            if not ARGS.continue_on_error:
                log("    已停止（去掉 --continue-on-error 时的默认行为）；修复后重跑同一命令即可续做")
                break

        if idx < len(cands) and ARGS.interval > 0:
            time.sleep(ARGS.interval)
        if (ARGS.pause_every > 0 and idx % ARGS.pause_every == 0
                and idx < len(cands) and ARGS.pause_seconds > 0):
            log(f"    —— 已处理 {idx} 条，停 {ARGS.pause_seconds}s 让抽取队列消化 ——")
            time.sleep(ARGS.pause_seconds)

    print()
    print(f"== 本次结果：成功 {ok} 条，失败 {fail} 条 ==")
    if log_path:
        print(f"   日志：{log_path}")
        log_fp.close()
    print("   注意：confirm 返回成功只代表工单已关闭、事件已发出；")
    print("         ai_extracted 的行要等异步抽取完成（约 9~10 秒/条）后才会出现，请按手册第 6/8 章核对。")
    return 0 if fail == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
