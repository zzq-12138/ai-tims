#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI-TIMS M6 提炼闭环 E2E 验收脚本（在 VM 上执行）。
链路：建单 → 受理/处理/解决/确认关闭 → RabbitMQ ticket.closed → GLM 抽取 → 审核通过写 KB
      → 30s 内向量同步并可检索命中 → 重复投递消息幂等 → 人工确认合并留痕。
仅用于本地验收，所有中间态直接查 aitims 库做证据留档。
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import requests

BASE = "http://127.0.0.1:8080"
MYSQL_PWD = open("/home/dev/secrets/mysql_pwd").read().strip()
RABBIT_PWD = open("/home/dev/secrets/rabbit_pwd").read().strip()
RABBIT_API = "http://127.0.0.1:15672/api"
TENANT = 1

s = requests.Session()
s.headers["Content-Type"] = "application/json"


def db(sql):
    env = dict(os.environ, MYSQL_PWD=MYSQL_PWD)
    r = subprocess.run(["mysql", "-udev", "-h127.0.0.1", "aitims", "-N", "-B", "-e", sql],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError("mysql failed: " + r.stderr)
    return [line.split("\t") for line in r.stdout.strip().split("\n") if line.strip()]


def api(method, path, body=None, expect=0):
    url = BASE + path
    resp = s.request(method, url, data=json.dumps(body) if body is not None else None, timeout=30)
    try:
        j = resp.json()
    except Exception:
        raise RuntimeError(f"{method} {path} 非 JSON 响应: {resp.status_code} {resp.text[:200]}")
    if expect is not None and j.get("code") != expect:
        raise RuntimeError(f"{method} {path} 失败: {j}")
    return j.get("data")


def wait_extraction(ticket_id, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        rows = db(f"select id,status,title,dedup_action,ifnull(dedup_score,''),"
                  f"ifnull(dedup_target_id,''),ifnull(dedup_note,''),ifnull(error_msg,''),ifnull(model,'') "
                  f"from ai_extracted where tenant_id={TENANT} and source_ticket_id={ticket_id} limit 1")
        if rows:
            return rows[0]
        time.sleep(2)
    raise RuntimeError(f"工单 {ticket_id} 抽取超时（{timeout}s）")


def wait_hit(query, kb_id, timeout=45):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        data = api("GET", f"/api/kb/search?query={requests.utils.quote(query)}&mode=HYBRID&topK=5")
        last = data
        for item in data.get("items", []):
            if item.get("id") == kb_id:
                return time.time() - t0, data
        time.sleep(2)
    raise RuntimeError(f"审核通过后 {timeout}s 内未检索命中 kb_id={kb_id}，最后一次={last}")


def close_ticket(title, description, resolve_note, device_type="MES终端"):
    t = api("POST", "/api/order/ticket", {
        "title": title, "ticketType": "设备异常", "factory": "F1", "plant": "P1",
        "deviceType": device_type, "urgency": 2, "description": description, "draft": False})
    tid = t["id"]
    api("POST", f"/api/order/ticket/{tid}/accept")
    api("POST", f"/api/order/ticket/{tid}/start")
    api("POST", f"/api/order/ticket/{tid}/resolve", {"resolveNote": resolve_note})
    api("POST", f"/api/order/ticket/{tid}/confirm")
    return tid, t["ticketNo"]


def main():
    out = {"startedAt": datetime.now().isoformat(), "steps": {}}

    # 0. 登录管理员
    login = api("POST", "/api/auth/login", {"username": "admin", "password": "Admin@123"})
    s.headers["Authorization"] = login["token"]
    out["admin"] = login.get("nickname")

    # 1. 关闭工单（主链路）
    desc1 = ("产线 MES 终端在整点报工高峰期频繁弹窗“接口调用超时”，重复提交后出现重复报工记录，"
             "影响工单进度统计。排查发现终端本地缓存队列堆积，交换机上行端口丢包率升高。"
             "清空本地缓存并重启客户端后恢复；更换交换机上行光模块后观察 2 小时未再复现。")
    resolve1 = ("1) 停止 MES 客户端并清空本地缓存队列；2) 重启 MES 客户端服务；"
                "3) 更换交换机上行光模块，观察 2 小时；4) 在 MES 后台清理重复报工记录并补录正确数据。")
    tid1, no1 = close_ticket("MES终端整点报工接口超时", desc1, resolve1)
    out["steps"]["ticket1"] = {"id": tid1, "ticketNo": no1, "status": db(
        f"select status,ai_extracted from wo_ticket where id={tid1}")[0]}

    # 2. 等待抽取落库
    t0 = time.time()
    row = wait_extraction(tid1)
    out["steps"]["extract1"] = {
        "costSec": round(time.time() - t0, 1),
        "row": {"id": row[0], "status": row[1], "title": row[2], "suggest": row[3],
                "score": row[4], "targetId": row[5], "note": row[6], "error": row[7], "model": row[8]}
    }
    if row[1] != "PENDING_REVIEW":
        raise RuntimeError("抽取未进入待审核: " + row[1] + " error=" + row[7])

    # 3. 人工确认通过（写入 KB）
    kb = api("POST", f"/api/kb/extraction/{row[0]}/approve")
    kb_id = kb["id"]
    approve_at = time.time()
    out["steps"]["approve1"] = {"aiExtractedId": row[0], "kbId": kb_id, "kbTitle": kb["title"],
                                "kbStatus": kb["status"], "version": kb["version"]}

    # 4. 30s 内可检索命中
    cost, data = wait_hit("MES终端 报工接口超时", kb_id)
    item = next(i for i in data["items"] if i["id"] == kb_id)
    out["steps"]["search1"] = {"hitAfterSec": round(cost, 1), "mode": data["mode"],
                               "fallback": data["fallback"], "total": data["total"],
                               "score": item["score"], "title": item["title"]}
    if cost > 30:
        raise RuntimeError(f"检索命中耗时 {cost:.1f}s 超过 30s 验收线")
    out["steps"]["approveToHitSec"] = round(time.time() - approve_at, 1)

    # 5. 重复消息幂等（同一 ticketId 再投递一次 ticket.closed）
    event = {"eventType": "ticket.closed", "tenantId": TENANT, "ticketId": tid1,
             "ticketNo": no1, "deviceType": "MES终端", "handlerId": None,
             "tCreated": datetime.now().isoformat()}
    r = requests.post(RABBIT_API + "/exchanges/%2F/tims.ticket.event/publish",
                      auth=("tims", RABBIT_PWD), timeout=10,
                      json={"properties": {}, "routing_key": "ticket.closed",
                            "payload": json.dumps(event, ensure_ascii=False),
                            "payload_encoding": "string"})
    r.raise_for_status()
    time.sleep(8)
    cnt = int(db(f"select count(*) from ai_extracted where tenant_id={TENANT} "
                 f"and source_ticket_id={tid1}")[0][0])
    out["steps"]["idempotent"] = {"delivered": r.json().get("routed"), "aiExtractedRows": cnt}
    if cnt != 1:
        raise RuntimeError(f"重复消息产生重复条目: {cnt}")

    # 6. 人工确认合并（第二条近似工单）——验证不自动合并、合并留痕
    desc2 = desc1.replace("整点", "半点").replace("2 小时", "1 小时")
    resolve2 = resolve1.replace("2 小时", "1 小时")
    tid2, no2 = close_ticket("MES终端半点报工接口超时", desc2, resolve2)
    row2 = wait_extraction(tid2)
    kb_before = db(f"select version,content from kb_knowledge where id={kb_id}")[0]
    out["steps"]["extract2"] = {"id": row2[0], "status": row2[1], "suggest": row2[3],
                                "score": row2[4], "targetId": row2[5], "note": row2[6],
                                "kbVersionBeforeMerge": kb_before[0]}
    if kb_before[0] != "1":
        raise RuntimeError("审核前知识条目版本已变化，疑似自动合并: " + kb_before[0])

    merged = api("POST", f"/api/kb/extraction/{row2[0]}/merge", {"targetId": kb_id})
    kb_after = db(f"select version,content from kb_knowledge where id={kb_id}")[0]
    hist = db(f"select version,change_type,source_extracted_id from kb_knowledge_history "
              f"where knowledge_id={kb_id} order by create_time desc")
    out["steps"]["merge"] = {"kbVersionBefore": kb_before[0], "kbVersionAfter": kb_after[0],
                             "contentAppended": "工单补充" in kb_after[1],
                             "historyRows": hist, "extractedStatus": db(
                                 f"select status,knowledge_id from ai_extracted where id={row2[0]}")[0]}
    if len(hist) != 1 or hist[0][1] != "MERGE":
        raise RuntimeError("合并未留历史快照: " + str(hist))
    if kb_after[0] != "2":
        raise RuntimeError("合并后版本号异常: " + kb_after[0])

    # 7. AI 调用日志与 adoptionRate
    logs = db(f"select scene,model,status,total_tokens,latency_ms from ai_call_log "
              f"where tenant_id={TENANT} and scene='EXTRACT' order by create_time desc limit 5")
    overview = api("GET", "/api/order/stat/overview")
    out["steps"]["aiCallLog"] = logs
    out["steps"]["overview"] = overview
    out["finishedAt"] = datetime.now().isoformat()
    out["result"] = "PASS"
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"result": "FAIL", "error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)
