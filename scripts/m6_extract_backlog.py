#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M6 知识抽取吞吐压测：集中关单 N 单，统计“关单→知识抽取落库”的耗时分布与队列积压峰值。

流程：
  1) 预置 N 单（建单→受理→开工→解决），使其全部处于 RESOLVED，可被瞬时集中关闭；
  2) 并发触发 confirm（ticket.closed 事件批量入队），记录每单关单返回时间；
  3) 每秒采样 RabbitMQ q.kb.extract 的 ready+unacked 作为队列积压；
  4) 轮询 ai_extracted 直至全部进入终态（PENDING_REVIEW/MANUAL_REQUIRED），
     用 update_time 作为“知识落库完成”时间点（优化后占位行 create_time 不再是完成时间）。

用法：python3 m6_extract_backlog.py <tag> <N> [confirm_concurrency]
输出：/home/dev/logs/extract_backlog_<tag>.json + 控制台摘要
"""
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

BASE = "http://127.0.0.1:8080"
STATS_API = "http://127.0.0.1:8103"
RABBIT_API = "http://127.0.0.1:15672/api"
QUEUE = "q.kb.extract"
MYSQL_PWD = open("/home/dev/secrets/mysql_pwd").read().strip()
RABBIT_USER, RABBIT_PWD = "tims", open("/home/dev/secrets/rabbit_pwd").read().strip()
DEVS = ["贴片机", "AOI检测机", "涂布机", "贴合机", "蚀刻机"]
FINAL = ("PENDING_REVIEW", "MANUAL_REQUIRED", "APPROVED", "MERGED", "REJECTED")

TOKEN = None
TIMEOUT = 30


def db(sql):
    env = dict(os.environ, MYSQL_PWD=MYSQL_PWD)
    r = subprocess.run(["mysql", "-udev", "-h127.0.0.1", "aitims", "-N", "-B", "-e", sql],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError("mysql failed: " + r.stderr)
    return [line.split("\t") for line in r.stdout.strip().split("\n") if line.strip()]


def api(method, path, body=None):
    hdr = {"Content-Type": "application/json"}
    if TOKEN:
        hdr["Authorization"] = TOKEN
    r = requests.request(method, BASE + path, data=json.dumps(body) if body is not None else None,
                         headers=hdr, timeout=TIMEOUT)
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"{method} {path} 失败: {j}")
    return j.get("data")


def pct(sorted_v, p):
    if not sorted_v:
        return 0.0
    idx = p * (len(sorted_v) - 1)
    lo, hi = int(idx // 1), int(-(-idx // 1))
    return sorted_v[lo] if lo == hi else sorted_v[lo] + (sorted_v[hi] - sorted_v[lo]) * (idx - lo)


def to_ms(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp() * 1000


class QueueSampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.samples = []
        self.exec_samples = []

    def run(self):
        while not self.stop.is_set():
            try:
                d = requests.get(f"{RABBIT_API}/queues/%2F/{QUEUE}", auth=(RABBIT_USER, RABBIT_PWD), timeout=3).json()
                self.samples.append({
                    "t": int(time.time() * 1000),
                    "ready": d.get("messages_ready", 0),
                    "unacked": d.get("messages_unacknowledged", 0),
                })
            except Exception:
                pass
            try:
                # 优化后 ticket-knowledge 暴露的抽取执行器指标（基线版本无此端点，忽略 404）
                e = requests.get(f"{STATS_API}/internal/kb/extract/queue-stats", timeout=3).json()
                if e.get("code") == 0:
                    self.exec_samples.append(e["data"])
            except Exception:
                pass
            self.stop.wait(1.0)

    def peak(self, field):
        return max((s[field] for s in self.samples), default=0)


def main():
    tag, n = sys.argv[1], int(sys.argv[2])
    conc = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    global TOKEN
    TOKEN = api("POST", "/api/auth/login", {"username": "admin", "password": "Admin@123"})["token"]

    print(f"[准备] 预置 {n} 单至 RESOLVED，建单/流转并发={conc}")
    t0 = time.time()

    def stage(i):
        dev = DEVS[i % len(DEVS)]
        title = f"kbbacklog-{tag}-{i}-{dev}异常"
        t = api("POST", "/api/order/ticket", {
            "title": title, "ticketType": "设备异常", "factory": "F1", "plant": "P1",
            "deviceType": dev, "urgency": (i % 3) + 1,
            "description": f"压测样本{i}：{dev}报警码 E{i % 100:03d}，节拍下降；"
                           f"排查发现传感器脏污与气缸行程偏移，清洁并校准后恢复。",
            "draft": False})
        tid = t["id"]
        api("POST", f"/api/order/ticket/{tid}/accept")
        api("POST", f"/api/order/ticket/{tid}/start")
        api("POST", f"/api/order/ticket/{tid}/resolve", {
            "resolveNote": f"1) 清洁{dev}传感器；2) 校准气缸行程；3) 复位报警并观察 30 分钟。"})
        return tid, t["ticketNo"]

    with ThreadPoolExecutor(max_workers=conc) as ex:
        pairs = list(ex.map(stage, range(n)))
    stage_ms = (time.time() - t0) * 1000
    print(f"[准备完成] {len(pairs)}/{n} 单就绪，耗时={stage_ms:.0f}ms")

    sampler = QueueSampler()
    sampler.start()

    fired = {}
    confirm_start = time.time()

    def fire(pair):
        tid, _no = pair
        ts = time.time() * 1000
        api("POST", f"/api/order/ticket/{tid}/confirm")
        return tid, ts

    with ThreadPoolExecutor(max_workers=conc) as ex:
        for tid, ts in ex.map(fire, pairs):
            fired[tid] = ts
    fire_ms = (time.time() - confirm_start) * 1000
    print(f"[集中关单] {len(fired)} 单已投递 ticket.closed，触发耗时={fire_ms:.0f}ms")

    ids = list(fired.keys())
    deadline = time.time() + n * 12 + 240
    rows = {}
    while time.time() < deadline:
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            sql = ("SELECT source_ticket_id,status,error_msg,"
                   "DATE_FORMAT(create_time,'%Y-%m-%d %H:%i:%s.%f'),"
                   "DATE_FORMAT(update_time,'%Y-%m-%d %H:%i:%s.%f') "
                   f"FROM ai_extracted WHERE source_ticket_id IN ({','.join(str(x) for x in chunk)})")
            for r in db(sql):
                rows[int(r[0])] = r
        done = [t for t in ids if t in rows and rows[t][1] in FINAL]
        print(f"[等待落库] {len(done)}/{n}  queue={sampler.samples[-1]['ready'] + sampler.samples[-1]['unacked'] if sampler.samples else -1}")
        if len(done) >= n:
            break
        time.sleep(2)
    sampler.stop.set()

    costs, statuses, errors = [], {}, 0
    for tid in ids:
        if tid not in rows:
            continue
        r = rows[tid]
        status = r[1]
        statuses[status] = statuses.get(status, 0) + 1
        if status == "MANUAL_REQUIRED":
            errors += 1
        if status in FINAL:
            done_ms = to_ms(r[4])
            costs.append(done_ms - fired[tid])
    costs.sort()
    missing = n - len(costs)
    finish = time.time()

    result = {
        "tag": tag, "n": n, "confirmConcurrency": conc,
        "stageMs": round(stage_ms), "fireMs": round(fire_ms),
        "completed": len(costs), "missing": missing,
        "lastMs": round(costs[-1]) if costs else None,
        "avgMs": round(sum(costs) / len(costs)) if costs else None,
        "p95Ms": round(pct(costs, .95)) if costs else None,
        "p99Ms": round(pct(costs, .99)) if costs else None,
        "minMs": round(costs[0]) if costs else None,
        "wallMs": round((finish - confirm_start) * 1000),
        "queuePeakReady": sampler.peak("ready"),
        "queuePeakTotal": max((s["ready"] + s["unacked"] for s in sampler.samples), default=0),
        "statuses": statuses,
        "manualRequired": errors,
        "executorPeakQueue": max((s.get("peakQueueDepth", 0) for s in sampler.exec_samples), default=None),
        "executorPeakActive": max((s.get("peakActive", 0) for s in sampler.exec_samples), default=None),
        "executorFinal": sampler.exec_samples[-1] if sampler.exec_samples else None,
        "samples": sampler.samples,
    }
    out = f"/home/dev/logs/extract_backlog_{tag}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[结果] n={n} 落库={len(costs)} 缺失={missing} 最后一条={result['lastMs']}ms "
          f"avg={result['avgMs']}ms p95={result['p95Ms']}ms p99={result['p99Ms']}ms "
          f"队列峰值={result['queuePeakTotal']} 状态={statuses} 人工补录={errors}")
    if result["executorFinal"]:
        ef = result["executorFinal"]
        print(f"[执行器] 峰值排队={result['executorPeakQueue']} 峰值并发={result['executorPeakActive']} "
              f"avgWait={ef.get('avgWaitMs')}ms maxWait={ef.get('maxWaitMs')}ms "
              f"completed={ef.get('completed')} failed={ef.get('failed')} retried={ef.get('retried')} "
              f"rejected={ef.get('rejected')}")
    print(f"[落盘] {out}")


if __name__ == "__main__":
    main()
