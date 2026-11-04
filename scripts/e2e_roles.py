#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI-TIMS M6 角色矩阵 E2E 验收（在 VM 上执行，网关 8080）。
覆盖四类断言，输出每次请求的真实 HTTP 状态码与业务 code：
  1) 报障人越权访问他人工单 → 403
  2) 工程师无审核权限（抽取审核/知识发布） → 403
  3) 审核员可发布知识，但不可删用户 → 200 / 403
  4) 管理员全通 → 200
"""
import json
import sys
from datetime import datetime

import requests

BASE = "http://127.0.0.1:8080"

ROLE_CASES = []


def session_for(username, password="Admin@123"):
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    r = s.post(BASE + "/api/auth/login", data=json.dumps({"username": username, "password": password}), timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"登录失败 {username}: {r.status_code} {r.text[:200]}")
    s.headers["Authorization"] = r.json()["data"]["token"]
    return s


def call(s, method, path, body=None, label="", actor=""):
    r = s.request(method, BASE + path, data=json.dumps(body) if body is not None else None, timeout=30)
    try:
        j = r.json()
    except Exception:
        j = {}
    item = {"case": label, "actor": actor, "method": method, "path": path,
            "httpStatus": r.status_code, "code": j.get("code"), "message": j.get("message")}
    ROLE_CASES.append(item)
    return r.status_code, j, item


def expect(item, status, label):
    ok = item["httpStatus"] == status
    item["expected"] = status
    item["pass"] = ok
    if not ok:
        raise RuntimeError(f"{label} 期望 HTTP {status}，实际 {item['httpStatus']} / code={item['code']}")


def main():
    out = {"startedAt": datetime.now().isoformat(), "cases": ROLE_CASES}

    admin = session_for("admin")
    engineer = session_for("engineer")
    reporter = session_for("reporter")
    reviewer = session_for("reviewer")

    for name, s in (("admin", admin), ("engineer", engineer), ("reporter", reporter), ("reviewer", reviewer)):
        _, me, _ = call(s, "GET", "/api/auth/me", label="登录角色核对", actor=name)
        out.setdefault("roles", {})[name] = me.get("data", {}).get("roles")

    # ---------- 1. 报障人只能看自己的工单 ----------
    reporter_ticket = call(reporter, "POST", "/api/order/ticket", {
        "title": " [角色矩阵] 报障人自建工单", "ticketType": "设备异常", "factory": "F1",
        "deviceType": "MES终端", "description": "报障人自建，仅本人可见", "draft": False},
        label="报障人建单", actor="reporter")[1]["data"]["id"]
    own = call(reporter, "GET", f"/api/order/ticket/{reporter_ticket}", label="报障人访问自己的工单", actor="reporter")
    expect(own[2], 200, "报障人访问自己的工单")

    engineer_ticket = call(engineer, "POST", "/api/order/ticket", {
        "title": " [角色矩阵] 工程师自建工单", "ticketType": "设备异常", "factory": "F1",
        "deviceType": "MES终端", "description": "他人工单，用于越权校验", "draft": False},
        label="工程师建单", actor="engineer")[1]["data"]["id"]
    cross = call(reporter, "GET", f"/api/order/ticket/{engineer_ticket}", label="报障人越权访问他人工单", actor="reporter")
    expect(cross[2], 403, "报障人越权访问他人工单")

    page = call(reporter, "GET", "/api/order/ticket/page?tab=ALL&page=1&size=50",
                label="报障人列表仅返回本人", actor="reporter")[1]["data"]
    records = page.get("records", [])
    out["reporterPage"] = {"total": page.get("total"),
                           "titles": [r.get("title") for r in records]}
    if page.get("total", 0) < 1:
        raise RuntimeError("报障人列表应至少包含本人刚创建的工单")
    if any(r.get("createBy") != records[0].get("createBy") for r in records):
        raise RuntimeError("报障人列表返回了他人创建的工单")
    if any("工程师自建工单" in (r.get("title") or "") for r in records):
        raise RuntimeError("报障人列表越权返回工程师工单")

    # 审核员不是工单处理岗，看他人工单同样 403
    rev_cross = call(reviewer, "GET", f"/api/order/ticket/{engineer_ticket}", label="审核员访问他人工单", actor="reviewer")
    expect(rev_cross[2], 403, "审核员访问他人工单")

    # 工程师可看可受理（工单处理）
    eng_view = call(engineer, "GET", f"/api/order/ticket/{reporter_ticket}", label="工程师查看全量工单", actor="engineer")
    expect(eng_view[2], 200, "工程师查看全量工单")
    eng_accept = call(engineer, "POST", f"/api/order/ticket/{reporter_ticket}/accept",
                      label="工程师受理工单", actor="engineer")
    expect(eng_accept[2], 200, "工程师受理工单")

    # ---------- 2. 工程师无审核权限 ----------
    eng_extract = call(engineer, "GET", "/api/kb/extraction/page?page=1&size=10",
                       label="工程师访问抽取审核（网关拦截）", actor="engineer")
    expect(eng_extract[2], 403, "工程师访问抽取审核")

    kb = call(engineer, "POST", "/api/kb/knowledge", {
        "title": " [角色矩阵] 工程师知识", "content": "工程师创建待审知识", "summary": "角色矩阵用例"},
        label="工程师创建知识", actor="engineer")[1]["data"]["id"]
    call(engineer, "POST", f"/api/kb/knowledge/{kb}/submit", label="工程师提交审核", actor="engineer")
    eng_pub = call(engineer, "POST", f"/api/kb/knowledge/{kb}/publish",
                   label="工程师发布知识（接口级拒绝）", actor="engineer")
    expect(eng_pub[2], 403, "工程师发布知识")

    # ---------- 3. 审核员可发布知识，不可删用户 ----------
    rev_extract = call(reviewer, "GET", "/api/kb/extraction/page?page=1&size=10",
                       label="审核员访问抽取审核", actor="reviewer")
    expect(rev_extract[2], 200, "审核员访问抽取审核")

    kb2 = call(reviewer, "POST", "/api/kb/knowledge", {
        "title": " [角色矩阵] 审核员知识", "content": "审核员创建并发布", "summary": "角色矩阵用例"},
        label="审核员创建知识", actor="reviewer")[1]["data"]["id"]
    call(reviewer, "POST", f"/api/kb/knowledge/{kb2}/submit", label="审核员提交审核", actor="reviewer")
    rev_pub = call(reviewer, "POST", f"/api/kb/knowledge/{kb2}/publish",
                   label="审核员发布知识", actor="reviewer")
    expect(rev_pub[2], 200, "审核员发布知识")
    out["reviewerPublishedKb"] = kb2

    rev_del = call(reviewer, "DELETE", "/api/system/user/999999",
                   label="审核员删除用户（网关拦截）", actor="reviewer")
    expect(rev_del[2], 403, "审核员删除用户")

    # ---------- 4. 管理员全通 ----------
    admin_users = call(admin, "GET", "/api/system/user/page?page=1&size=10",
                       label="管理员访问用户管理", actor="admin")
    expect(admin_users[2], 200, "管理员访问用户管理")
    admin_extract = call(admin, "GET", "/api/kb/extraction/page?page=1&size=10",
                         label="管理员访问抽取审核", actor="admin")
    expect(admin_extract[2], 200, "管理员访问抽取审核")
    admin_ticket = call(admin, "GET", f"/api/order/ticket/{engineer_ticket}",
                        label="管理员访问任意工单", actor="admin")
    expect(admin_ticket[2], 200, "管理员访问任意工单")

    out["finishedAt"] = datetime.now().isoformat()
    out["result"] = "PASS"
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"result": "FAIL", "error": str(e), "cases": ROLE_CASES},
                         ensure_ascii=False, indent=2))
        sys.exit(1)
