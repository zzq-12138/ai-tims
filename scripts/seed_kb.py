#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3 种子知识生成 + 200 工单关联（在 VM 上执行）。
- 50 条 = 5 设备类型 x 10 故障场景，GLM-4-Flash 生成（普通对话模型：messages+temperature，无 thinking 参数）
- 每条走 create(DRAFT) -> submit(PENDING) -> publish(PUBLISHED) 全流程，自动进入向量同步
- 工单关联：kb_knowledge.source_ticket_id <- 同设备类型随机一条 wo_ticket（供 M7 评测集反推 expectedIds）
- 幂等性：不查重，重复执行会追加新知识；401/429 直接打印响应原文并中止，不做静默重试
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

GATEWAY = "http://127.0.0.1:8080"
GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-4-flash"

SEEDS = [
    ("贴片机", "抛料"), ("贴片机", "吸嘴堵塞"), ("贴片机", "贴装偏移"), ("贴片机", "供料器卡料"),
    ("贴片机", "元件视觉识别失败"), ("贴片机", "贴装头撞击"), ("贴片机", "传送轨道卡板"),
    ("贴片机", "锡膏印刷偏移"), ("贴片机", "元器件立碑"), ("贴片机", "气路压力异常"),
    ("AOI检测机", "误报率过高"), ("AOI检测机", "漏检"), ("AOI检测机", "图像模糊"),
    ("AOI检测机", "光源亮度衰减"), ("AOI检测机", "程序调用错误"), ("AOI检测机", "条码识别失败"),
    ("AOI检测机", "过板卡板"), ("AOI检测机", "相机对焦异常"), ("AOI检测机", "算法阈值漂移"),
    ("AOI检测机", "通讯中断"),
    ("涂布机", "涂布厚度不均"), ("涂布机", "涂层气泡"), ("涂布机", "边缘漏涂"), ("涂布机", "张力波动"),
    ("涂布机", "烘干温度异常"), ("涂布机", "涂布头堵塞"), ("涂布机", "纠偏失灵"),
    ("涂布机", "背辊粘胶"), ("涂布机", "速度同步异常"), ("涂布机", "料卷接头断带"),
    ("贴合机", "贴合气泡"), ("贴合机", "贴合偏移"), ("贴合机", "材料褶皱"), ("贴合机", "脱胶"),
    ("贴合机", "贴合压力不均"), ("贴合机", "辊筒磨损"), ("贴合机", "定位标记识别失败"),
    ("贴合机", "温控异常"), ("贴合机", "送料偏斜"), ("贴合机", "静电吸附不良"),
    ("蚀刻机", "蚀刻速率偏差"), ("蚀刻机", "药水浓度异常"), ("蚀刻机", "喷嘴堵塞"),
    ("蚀刻机", "过蚀刻"), ("蚀刻机", "蚀刻不均"), ("蚀刻机", "传送轮污染"),
    ("蚀刻机", "腔体温度漂移"), ("蚀刻机", "废液排放报警"), ("蚀刻机", "水洗残留"), ("蚀刻机", "腔体压力异常"),
]


def read_secret(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def http(method, url, body=None, token=None, timeout=60):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def glm_generate(api_key, device, fault):
    prompt = (
        f"你是SMT/半导体设备维修知识库专家。设备类型：{device}。故障场景：{fault}。"
        "请生成一条维修知识，严格只输出一个 JSON 对象（禁止 markdown 代码块、禁止解释文字），字段："
        'title（不超过30字，含设备类型与故障关键词）、summary（不超过100字概括）、'
        'content（300-500字，依次含：故障现象、可能原因、处理步骤、预防措施）、'
        'tags（3-5个短标签字符串数组，含设备类型与关键部件词）。'
    )
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.8}
    status, resp = http("POST", GLM_URL, body,
                        token="Bearer " + api_key, timeout=90)
    if status != 200:
        print(f"[GLM] HTTP {status} 响应原文: {resp}", file=sys.stderr)
        sys.exit(2)
    content = resp["choices"][0]["message"]["content"]
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("GLM 返回不含 JSON: " + content[:200])
    obj = json.loads(content[start:end + 1])
    for f in ("title", "summary", "content", "tags"):
        if f not in obj:
            raise ValueError("GLM JSON 缺字段 %s: %s" % (f, obj))
    return obj


def as_text(v):
    """GLM 偶发把字符串字段返回成嵌套对象，统一归一为文本"""
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def main():
    zhipu = read_secret("/home/dev/secrets/zhipu_api_key")
    mysql_pwd = read_secret("/home/dev/secrets/mysql_pwd")

    status, resp = http("POST", GATEWAY + "/api/auth/login",
                        {"username": "admin", "password": "Admin@123"})
    if status != 200 or (isinstance(resp, dict) and resp.get("code") not in (0, 200, None)):
        print(f"[login] HTTP {status}: {resp}", file=sys.stderr)
        sys.exit(1)
    token = resp["data"]["token"]
    print("[login] ok")

    # 工单数量检查，不足则自动补 200 条模拟工单
    cnt = subprocess.run(["mysql", "-u", "dev", "-N", "-e",
                          "SELECT COUNT(*) FROM aitims.wo_ticket WHERE deleted=0"],
                         capture_output=True, text=True,
                         env={**os.environ, "MYSQL_PWD": mysql_pwd})
    ticket_cnt = int(cnt.stdout.strip() or 0)
    if ticket_cnt < 200:
        print(f"[mock] 现有工单 {ticket_cnt} < 200，调 mock/batch 补足")
        s, r = http("POST", GATEWAY + "/api/order/mock/batch", {"count": 200}, token=token, timeout=300)
        print(f"[mock] HTTP {s}: {json.dumps(r, ensure_ascii=False)[:200]}")

    ok, fail = 0, 0
    ids = []
    only = set(sys.argv[1:]) if len(sys.argv) > 1 else None  # 只补跑指定 "设备/场景"
    for device, fault in SEEDS:
        if only and f"{device}/{fault}" not in only:
            continue
        try:
            kb = glm_generate(zhipu, device, fault)
        except SystemExit:
            raise
        except Exception as e:
            print(f"[gen] {device}/{fault} 生成失败: {e}", file=sys.stderr)
            fail += 1
            continue
        body = {
            "title": as_text(kb["title"]), "content": as_text(kb["content"]),
            "summary": as_text(kb["summary"]),
            "tags": json.dumps(kb["tags"], ensure_ascii=False),
            "applyDeviceType": device, "categoryId": 1,
        }
        s, r = http("POST", GATEWAY + "/api/kb/knowledge", body, token=token)
        if s != 200 or (isinstance(r, dict) and r.get("code") not in (0, 200, None)):
            print(f"[create] {device}/{fault} HTTP {s}: {json.dumps(r, ensure_ascii=False)[:200]}", file=sys.stderr)
            fail += 1
            continue
        kid = r["data"]["id"]
        for act in ("submit", "publish"):
            s, r = http("POST", f"{GATEWAY}/api/kb/knowledge/{kid}/{act}", {}, token=token)
            if s != 200:
                print(f"[{act}] {kid} HTTP {s}: {json.dumps(r, ensure_ascii=False)[:200]}", file=sys.stderr)
        ok += 1
        ids.append(kid)
        print(f"[seed {ok}/{len(SEEDS)}] {device}/{fault} -> id={kid}")
        time.sleep(1.2)  # 简单限速

    print(f"[seed] 成功 {ok} 条，失败 {fail} 条")

    # 工单关联：同设备类型随机一条工单写入 source_ticket_id（不同表子查询，MySQL 允许）
    if ids:
        id_list = ",".join(str(i) for i in ids)
        sql = ("UPDATE aitims.kb_knowledge k SET k.source_ticket_id = "
               "(SELECT t.id FROM aitims.wo_ticket t "
               "WHERE t.device_type = k.apply_device_type AND t.deleted = 0 "
               "ORDER BY RAND() LIMIT 1) "
               f"WHERE k.id IN ({id_list}) AND k.source_ticket_id IS NULL")
        p = subprocess.run(["mysql", "-u", "dev", "-e", sql],
                           capture_output=True, text=True,
                           env={**os.environ, "MYSQL_PWD": mysql_pwd})
        if p.returncode != 0:
            print(f"[link] 关联失败: {p.stderr}", file=sys.stderr)
            sys.exit(3)
        chk = subprocess.run(
            ["mysql", "-u", "dev", "-N", "-e",
             f"SELECT COUNT(*) FROM aitims.kb_knowledge WHERE id IN ({id_list}) AND source_ticket_id IS NOT NULL"],
            capture_output=True, text=True,
            env={**os.environ, "MYSQL_PWD": mysql_pwd})
        print(f"[link] 已关联 source_ticket_id 的知识条数: {chk.stdout.strip()}")


if __name__ == "__main__":
    main()
