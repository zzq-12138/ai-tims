#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M4 批二压测：200 条工单连续建单（并发可控），统计端到端 P50/P95/P99 与分段耗时。
用法：python3 m4_stress.py <run_tag> <concurrency> <total>
摘要落库 pt_stress_run（四时间戳明细已在 ps_push_latency）。"""
import sys, json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

GATEWAY = "http://127.0.0.1:8080"
DEVS = ["贴片机", "AOI检测机", "涂布机", "贴合机", "蚀刻机"]
WEIGHTS = [30, 25, 20, 15, 10]  # 与 M2 模拟器同口径

def http(method, url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def pct(sorted_v, p):
    if not sorted_v:
        return None
    idx = p * (len(sorted_v) - 1)
    lo, hi = int(idx // 1), int(-(-idx // 1))
    return sorted_v[lo] if lo == hi else sorted_v[lo] + (sorted_v[hi] - sorted_v[lo]) * (idx - lo)

def main():
    run_tag, conc, total = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    token = http("POST", GATEWAY + "/api/auth/login",
                 json.dumps({"username": "admin", "password": "Admin@123"}).encode(),
                 {"Content-Type": "application/json"})["data"]["token"]
    hdr = {"Content-Type": "application/json", "Authorization": token}

    t_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[压测] run={run_tag} concurrency={conc} total={total} start={t_start}")

    ok, fail, t0 = 0, 0, time.time()
    def create(i):
        dev = DEVS[i % len(DEVS)]
        body = json.dumps({"title": f"{run_tag}-{i}-{dev}异常", "ticketType": "设备异常",
                           "deviceType": dev, "urgency": (i % 3) + 1,
                           "description": f"压测样本{i}：{dev}报警码 E{i%100:03d}，节拍下降需排查。"}).encode()
        try:
            r = http("POST", GATEWAY + "/api/order/ticket", body, hdr)
            return 1 if r.get("code") == 0 else 0
        except Exception:
            return 0

    with ThreadPoolExecutor(max_workers=conc) as ex:
        results = list(ex.map(create, range(total)))
    ok, fail = sum(results), total - sum(results)
    create_ms = (time.time() - t0) * 1000
    print(f"[建单完成] ok={ok} fail={fail} 建单总耗时={create_ms:.0f}ms 吞吐={total/(create_ms/1000):.1f}/s")

    # 等推送管线消化（MQ 消费 4-8 并发 + 检索）：轮询窗口内 t_push_sent 完成数，最长 90s
    import subprocess
    def run_sql(sql):
        return subprocess.run(["mysql", "-u", "dev", "-N", "-e", sql],
                              capture_output=True, text=True,
                              env={"MYSQL_PWD": open("/home/dev/secrets/mysql_pwd").read().strip(),
                                   "PATH": "/usr/bin:/bin:/usr/local/bin"}).stdout.strip()

    deadline = time.time() + 90
    done = 0
    while time.time() < deadline:
        done = int(run_sql(f"SELECT COUNT(*) FROM aitims.ps_push_latency WHERE t_created >= '{t_start}' AND t_push_sent IS NOT NULL") or 0)
        print(f"[等待推送] 已完成 {done}/{ok}")
        if done >= ok:
            break
        time.sleep(5)
    q = ("SELECT e2e_ms, TIMESTAMPDIFF(MICROSECOND,t_created,t_event_sent)/1000, "
         "TIMESTAMPDIFF(MICROSECOND,t_event_sent,t_retrieve_done)/1000, "
         "TIMESTAMPDIFF(MICROSECOND,t_retrieve_done,t_push_sent)/1000, degraded "
         f"FROM aitims.ps_push_latency WHERE t_created >= '{t_start}' AND t_push_sent IS NOT NULL")
    out = subprocess.run(["mysql", "-u", "dev", "-N", "-e", q],
                         capture_output=True, text=True,
                         env={"MYSQL_PWD": open("/home/dev/secrets/mysql_pwd").read().strip(),
                              "PATH": "/usr/bin:/bin:/usr/local/bin"}).stdout.strip().split("\n")
    rows = [r.split("\t") for r in out if r]
    e2e = sorted(float(r[0]) for r in rows if r[0] != "NULL")
    seg_ev = sorted(float(r[1]) for r in rows if r[1] != "NULL")
    seg_rt = sorted(float(r[2]) for r in rows if r[2] != "NULL")
    seg_ps = sorted(float(r[3]) for r in rows if r[3] != "NULL")
    deg = sum(1 for r in rows if r[4] != "0")
    print(f"[统计样本] n={len(rows)} degraded={deg}")
    if e2e:
        p50, p95, p99 = pct(e2e, .5), pct(e2e, .95), pct(e2e, .99)
        avg = sum(e2e) / len(e2e)
        s_ev = sum(seg_ev) / len(seg_ev) if seg_ev else 0
        s_rt = sum(seg_rt) / len(seg_rt) if seg_rt else 0
        s_ps = sum(seg_ps) / len(seg_ps) if seg_ps else 0
        print(f"[端到端] P50={p50:.0f}ms P95={p95:.0f}ms P99={p99:.0f}ms avg={avg:.0f}ms  (口径: 建单→WS卡片, 硬指标 P95≤1000ms)")
        print(f"[分段均值] 建单→MQ={s_ev:.0f}ms MQ→检索返回={s_rt:.0f}ms 检索→推送={s_ps:.0f}ms")
        verdict = "PASS" if p95 <= 1000 else "FAIL"
        print(f"[验收] {verdict}")
        # 落库摘要
        ins = ("INSERT INTO pt_stress_run (id,tenant_id,run_tag,concurrency,total,ok_count,fail_count,"
               "p50_ms,p95_ms,p99_ms,avg_ms,seg_event_ms,seg_retrieve_ms,seg_push_ms,degraded_count) VALUES ("
               f"{int(time.time()*1000)},1,'{run_tag}',{conc},{total},{ok},{fail},"
               f"{p50:.0f},{p95:.0f},{p99:.0f},{avg:.0f},{s_ev:.0f},{s_rt:.0f},{s_ps:.0f},{deg})")
        subprocess.run(["mysql", "-u", "dev", "aitims", "-e", ins],
                       env={"MYSQL_PWD": open("/home/dev/secrets/mysql_pwd").read().strip(),
                            "PATH": "/usr/bin:/bin:/usr/local/bin"})

if __name__ == "__main__":
    main()
