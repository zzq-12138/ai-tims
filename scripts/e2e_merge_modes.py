#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M6 合并正文取舍 E2E（KEEP_ORIGINAL / REPLACE 实际落库验证）。
用一条历史抽取记录克隆出两条待审记录，指向同一已发布条目，
分别以 KEEP_ORIGINAL / REPLACE 合并，校验正文、版本与 change_type 留痕。
"""
import json
import subprocess
from datetime import datetime

import requests

BASE = "http://127.0.0.1:8080"
SOURCE_EXTRACTED = 2117918238237802498   # 历史 MERGED 记录，仅作为克隆模板
CLONE_KEEP = SOURCE_EXTRACTED + 1000000
CLONE_REPLACE = SOURCE_EXTRACTED + 2000000


def db(sql):
    pwd = open("/home/dev/secrets/mysql_pwd").read().strip()
    out = subprocess.check_output(
        ["mysql", "-udev", "-h127.0.0.1", "aitims", "--default-character-set=utf8mb4",
         "-N", "-B", "-e", sql],
        env={"MYSQL_PWD": pwd, "PATH": "/usr/bin:/bin"}, text=True)
    rows = []
    for line in out.strip().splitlines():
        if line:
            # mysql -B 会把换行转义成 \n，这里还原后再比对正文
            rows.append([c.replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
                         for c in line.split("\t")])
    return rows


def login(username="admin"):
    s = requests.Session()
    r = s.post(BASE + "/api/auth/login", json={"username": username, "password": "Admin@123"}, timeout=10)
    assert r.status_code == 200, r.text
    s.headers["Authorization"] = r.json()["data"]["token"]
    return s


def api(s, method, path, body=None):
    r = s.request(method, BASE + path, json=body, timeout=30)
    j = r.json()
    return r.status_code, j


def clone(step, new_id, target_id):
    db(f"""insert into ai_extracted
        (id, tenant_id, source_ticket_id, source_ticket_no, source_title, source_device_type,
         title, device_type, fault_phenomenon, troubleshoot_steps, solution_steps, tags, key_points,
         dedup_action, dedup_target_id, dedup_score, dedup_note, status, model)
        select {new_id}, tenant_id, {new_id + 7}, source_ticket_no, source_title, source_device_type,
         title, device_type, fault_phenomenon, troubleshoot_steps, solution_steps, tags, key_points,
         'MERGE', {target_id}, dedup_score, dedup_note, 'PENDING_REVIEW', model
        from ai_extracted where id={SOURCE_EXTRACTED}""")


def main():
    out = {"startedAt": datetime.now().isoformat(), "steps": {}}
    # 每次执行创建一条一次性目标条目，确保原正文与新内容不同，可重复验证取舍行为
    s = login()
    st, kb = api(s, "POST", "/api/kb/knowledge", {
        "title": "[合并取舍E2E] 一次性目标条目",
        "content": "原始正文：设备告警复位后需观察 30 分钟。",
        "summary": "合并取舍验证专用"})
    assert st == 200, kb
    target_id = kb["data"]["id"]
    api(s, "POST", f"/api/kb/knowledge/{target_id}/submit")
    st, _ = api(s, "POST", f"/api/kb/knowledge/{target_id}/publish")
    assert st == 200, "一次性目标条目发布失败"
    db(f"delete from kb_knowledge_history where source_extracted_id in ({CLONE_KEEP},{CLONE_REPLACE})")
    db(f"delete from ai_extracted where id in ({CLONE_KEEP},{CLONE_REPLACE})")
    out["targetKb"] = target_id

    before = db(f"select version,content from kb_knowledge where id={target_id}")[0]
    out["steps"]["before"] = {"version": int(before[0]), "content": before[1]}

    for name, clone_id, mode in (("keepOriginal", CLONE_KEEP, "KEEP_ORIGINAL"),
                                 ("replace", CLONE_REPLACE, "REPLACE")):
        clone(name, clone_id, target_id)
        pv_status, pv = api(s, "GET", f"/api/kb/extraction/preview/{clone_id}?targetId={target_id}")
        assert pv_status == 200 and [o["mode"] for o in pv["data"]["options"]] == ["CONCAT", "KEEP_ORIGINAL", "REPLACE"]
        mg_status, mg = api(s, "POST", f"/api/kb/extraction/{clone_id}/merge",
                            {"targetId": target_id, "mode": mode})
        assert mg_status == 200, mg
        after = db(f"select version,content from kb_knowledge where id={target_id}")[0]
        hist = db(f"select version,change_type,source_extracted_id from kb_knowledge_history "
                  f"where source_extracted_id={clone_id}")
        row = db(f"select status,knowledge_id from ai_extracted where id={clone_id}")[0]
        out["steps"][name] = {
            "mode": mode,
            "httpStatus": mg_status,
            "previewModes": [o["mode"] for o in pv["data"]["options"]],
            "versionBefore": int(before[0]),
            "versionAfter": int(after[0]),
            "contentChanged": after[1] != before[1],
            "content": after[1],
            "history": hist,
            "extracted": {"status": row[0], "knowledgeId": int(row[1])},
        }
        if mode == "KEEP_ORIGINAL":
            assert after[1] == before[1], "KEEP_ORIGINAL 不应改写正文"
            assert int(after[0]) == int(before[0]) + 1, "KEEP_ORIGINAL 应版本 +1"
            assert hist[0][1] == "KEEP_ORIGINAL", "change_type 未记录 KEEP_ORIGINAL"
        else:
            assert after[1] != before[1], "REPLACE 应替换正文"
            if not (pv["data"]["newContent"] in after[1] or after[1] == pv["data"]["newContent"]):
                raise AssertionError(json.dumps({
                    "previewNew": pv["data"]["newContent"], "after": after[1],
                    "previewLen": len(pv["data"]["newContent"]), "afterLen": len(after[1])},
                    ensure_ascii=False))
            assert int(after[0]) == int(before[0]) + 1, "REPLACE 应版本 +1"
            assert hist[0][1] == "REPLACE", "change_type 未记录 REPLACE"
        before = after

    out["result"] = "PASS"
    out["finishedAt"] = datetime.now().isoformat()
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
