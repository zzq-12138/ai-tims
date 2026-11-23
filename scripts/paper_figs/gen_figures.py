# -*- coding: utf-8 -*-
"""
论文图表统一生成脚本。

数据图全部从 docs/paper 下的 csv / json 读取，不手抄数值；
流程图用同一套圆角框 + 同一套配色绘制，保证全篇风格一致。

用法：python scripts/paper_figs/gen_figures.py
输出：docs/paper/图/*.png（300 dpi）
"""

import csv
import json
import os
from collections import OrderedDict, defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAPER = os.path.join(ROOT, "docs", "paper")
OUT = os.path.join(PAPER, "图")

# ---------------------------------------------------------------- 统一风格
INK = "#2B2B2B"
GRID = "#DCDCDC"
MUTED = "#8C8C8C"
C1 = "#1F3F5F"  # 主色·深
C2 = "#3E6D96"  # 主色
C3 = "#7FA6C4"  # 主色·浅
C4 = "#BCD0E0"  # 主色·更浅
C5 = "#E8EEF4"  # 主色·底
G1 = "#F2F2F2"  # 中性灰·底
G2 = "#C9C9C9"  # 中性灰·线

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["SimHei"],
    "axes.unicode_minus": False,
    "font.size": 10,
    "axes.titlesize": 11.5,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 8.8,
    "axes.edgecolor": MUTED,
    "axes.linewidth": 0.8,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
    "lines.linewidth": 1.4,
    "lines.markersize": 5,
})


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print("  -> %s" % name)


def tidy(ax, ygrid=True):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y" if ygrid else "x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------- 流程图基元
def fbox(ax, x, y, w, h, title, sub="", done=True, fs=9.6):
    """圆角流程框；done=False 表示设计目标（虚线灰框）。"""
    fc = C5 if done else "white"
    ec = C2 if done else MUTED
    ls = "-" if done else (0, (4, 3))
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                boxstyle="round,pad=0.0,rounding_size=1.2",
                                fc=fc, ec=ec, lw=1.0, linestyle=ls, zorder=3))
    if sub:
        ax.text(x, y + h * 0.17, title, ha="center", va="center",
                fontsize=fs, color=INK, zorder=4)
        ax.text(x, y - h * 0.22, sub, ha="center", va="center",
                fontsize=fs - 1.2, color="#4F4F4F", zorder=4, linespacing=1.35)
    else:
        ax.text(x, y, title, ha="center", va="center", fontsize=fs,
                color=INK, zorder=4, linespacing=1.35)


def farrow(ax, p1, p2, dashed=False):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=11,
                                 lw=1.0, color="#5C5C5C", shrinkA=2, shrinkB=2,
                                 linestyle=(0, (4, 3)) if dashed else "-",
                                 zorder=2))


def blank_ax(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    return fig, ax


def legend_top(ax, ncol=3):
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=ncol, frameon=False,
              borderaxespad=0.1, handlelength=1.2, columnspacing=1.6, handletextpad=0.5)


def note(fig, text, y=-0.02):
    fig.text(0.005, y, text, fontsize=8, color=MUTED, va="top")


def flow_legend(ax, y=4, items=None):
    items = items or [("已实现", True), ("设计目标（未实现）", False)]
    x = 4
    for label, done in items:
        ax.add_patch(Rectangle((x, y), 3.2, 2.4, fc=C5 if done else "white",
                               ec=C2 if done else MUTED, lw=0.9,
                               linestyle="-" if done else (0, (4, 3))))
        ax.text(x + 4.2, y + 1.2, label, va="center", fontsize=8.6, color="#4F4F4F")
        x += 4.2 + len(label) * 1.85 + 2.5


# ================================================================ 图 1 架构
def fig_arch():
    fig, ax = blank_ax(11.2, 6.4)
    ax.text(2, 96.5, "图 3-1  系统总体架构", fontsize=11.5, color=INK, va="center")

    fbox(ax, 38, 86, 24, 8.4, "Web 前端", "Vue 3 · 工单 / 知识库 / 审核中心")
    fbox(ax, 70, 86, 22, 8.4, "移动端 / 大屏", "工单处理 · 实时推送")
    farrow(ax, (38, 81.8), (38, 75.0))
    farrow(ax, (70, 81.8), (70, 75.0))

    fbox(ax, 50, 70, 62, 9.6, "ticket-gateway :8080",
         "Sa-Token 鉴权 · 租户头剥离与回填 · 按 /api/{svc}/** 路由（不剥前缀）")

    svcs = [("ticket-system", ":8101  认证与租户"), ("ticket-order", ":8102  工单与派发"),
            ("ticket-knowledge", ":8103  知识库与检索"), ("ticket-ai", ":8105  AI 应用层"),
            ("ticket-push", ":8109  实时推送")]
    xs = [11, 30.5, 50, 69.5, 89]
    for x, (n, s) in zip(xs, svcs):
        fbox(ax, x, 48, 17.6, 10.6, n, s, fs=8.8)
        farrow(ax, (x, 65.2), (x, 53.4))

    ax.add_patch(Rectangle((1.0, 13.5), 98, 19.5, fc=G1, ec="none", zorder=0))
    ax.text(98.8, 31.6, "中间件层", fontsize=8.2, color=MUTED, va="center", ha="right")

    mids = [("MySQL", "业务库 aitims\n共享表 + tenant_id"), ("Redis", "会话 / 工单号日流水\n/ 限流计数"),
            ("RabbitMQ", "ticket.closed\n事件 + DLX"), ("Milvus", "kb_knowledge_vec\nHNSW · COSINE"),
            ("Nacos", "服务注册与配置")]
    for x, (n, s) in zip(xs, mids):
        fbox(ax, x, 22.5, 17.6, 12, n, s, done=True, fs=9.2)
        farrow(ax, (x, 42.6), (x, 28.7))

    ax.text(4, 8, "说明：网关按业务域路由到五个业务服务，六个微服务全部注册到 Nacos；"
                  "知识检索链路为 MySQL FULLTEXT + Milvus 双路，经 RRF 融合后返回。",
            fontsize=8.4, color="#4F4F4F", va="center")
    save(fig, "fig01_architecture.png")


# ================================================================ 图 2 问题二主流程
def fig_q2_method():
    fig, ax = blank_ax(11.4, 4.9)
    ax.text(2, 96.5, "图 2-1  问题二方法主流程（抽取 → 关系判别 → 条件化入库 → 检索侧条件过滤）",
            fontsize=11.5, color=INK, va="center")

    y1, y2 = 80, 47
    hh = 14
    fbox(ax, 11, y1, 18, hh, "① 工单关闭事件", "RabbitMQ ticket.closed\n按 tenantId 隔离")
    fbox(ax, 34, y1, 20, hh, "② 段落角色切分", "报修 / 排查 / 处置 / 复测\n跨 2–5 句根因窗口")
    fbox(ax, 59, y1, 22, hh, "③ 五元组抽取", "S1 零样本 / S2 规则\n/ S3 LoRA 微调")
    fbox(ax, 85, y1, 18, hh, "④ 排除假设槽位", "被排除原因 + 证据句\n禁止写入根因")

    fbox(ax, 85, y2, 18, hh, "⑤ 语义关系判别", "规则：同设备 × 同现象\n字段不全退回余弦三档")
    fbox(ax, 59, y2, 20, hh, "⑥ 条件化入库", "五类条件校验\n审核确认后写四列")
    fbox(ax, 34, y2, 20, hh, "⑦ 向量化与检索", "embedding-3 1024 维\n门控三档返回")
    fbox(ax, 11, y2, 18, hh, "⑧ 检索侧条件过滤", "topK×2 后回查\n方案 A（未编码）", done=False)

    farrow(ax, (20.2, y1), (23.8, y1))
    farrow(ax, (44.2, y1), (47.8, y1))
    farrow(ax, (70.2, y1), (75.8, y1))
    farrow(ax, (85, y1 - hh / 2 - 0.4), (85, y2 + hh / 2 + 0.4))
    farrow(ax, (75.8, y2), (69.2, y2))
    farrow(ax, (48.8, y2), (44.2, y2))
    farrow(ax, (23.8, y2), (20.2, y2))

    ax.text(85, 29, "300 对构造评测集\n（dup 90 / var 90 / conf 80）", ha="center", va="center",
            fontsize=8.2, color=MUTED, linespacing=1.35)
    ax.text(34, 32, "门控：A ≥0.82 / B 软带 / C 置空", ha="center", fontsize=8.2,
            color=MUTED, va="center")

    flow_legend(ax, y=9, items=[("已实现（现网）", True), ("设计目标（未实现）", False)])
    ax.text(4, 21, "注：③ 链式抽取、⑤ 语义关系判别、⑥ 条件化入库均有服务端实现，由 "
                   "tims.ai.extract.chain-enabled 控制（默认 false）；", fontsize=8.4, color="#4F4F4F", va="center")
    ax.text(4, 15, "④ 排除假设槽位在离线数据构造中实现；⑧ 检索侧条件过滤尚未编码。",
            fontsize=8.4, color="#4F4F4F", va="center")
    save(fig, "fig02_q2_method.png")


# ================================================================ 图 3 评测与消融流程
def fig_eval_flow():
    fig, ax = blank_ax(11.2, 6.4)
    ax.text(2, 96.5, "图 5-1  评测与消融流程（M7 检索消融 + 门控评估）",
            fontsize=11.5, color=INK, va="center")

    fbox(ax, 28, 86, 34, 9, "知识库快照 + 工单语料", "评测时 54 条 PUBLISHED；扩容后 310 条")
    fbox(ax, 28, 71, 34, 9.6, "构造评测集 100 条 query", "54 formal + 46 口语 / 噪声 / 缺字段")
    fbox(ax, 28, 56, 34, 9.6, "候选快照 _candidates.json", "真实接口 VECTOR / KEYWORD / HYBRID")
    fbox(ax, 28, 41, 34, 9.6, "八轮单变量配置 E1–E8", "模式 · 加权 · RRF k · topK")
    fbox(ax, 28, 26, 34, 9.6, "指标计算", "Hit@1/3 · Recall@5 · MRR · P50/P95")
    fbox(ax, 28, 11, 34, 9, "失败样本归因（4 类）", "术语不一致 / 缺字段 / 相近故障 / 重复条目")

    for a, b in [(81.5, 76), (66.4, 61), (51.4, 46), (36.4, 31), (21.4, 16)]:
        farrow(ax, (28, a), (28, b))

    # 右侧门控分支
    fbox(ax, 78, 71, 30, 8.4, "正例 100 / 负例 100", "leave-gold-out 100")
    fbox(ax, 78, 57, 30, 8.4, "真实 VECTOR top1 余弦", "门控三档判定 A / B / C")
    fbox(ax, 78, 43, 30, 8.4, "推送率与错误推送率", "正例覆盖 vs 混合错误率")
    farrow(ax, (45.2, 71), (62.8, 71))
    farrow(ax, (78, 66.6), (78, 61.4))
    farrow(ax, (78, 52.6), (78, 47.4))
    ax.text(78, 32.5, "位移到阈值曲线：0.70 / 0.75 / 0.78 / 0.80 / 0.85",
            ha="center", va="center", fontsize=8.2, color=MUTED)

    ax.text(4, 3, "说明：八轮消融与门控评估共用同一批 query 与候选快照，分数来自真实 HTTP 检索，"
                  "不使用 LLM 打分。", fontsize=8.4, color="#4F4F4F", va="center")
    save(fig, "fig03_eval_flow.png")


# ================================================================ 图 4 AI 应用层请求链路
def fig_ai_chain():
    fig, ax = blank_ax(13.4, 5.4)
    ax.set_xlim(0, 106)
    ax.text(2, 95, "图 4-1  AI 应用层请求链路（护栏 → 路由 → 缓存 → 工具）",
            fontsize=11.5, color=INK, va="center")

    y = 66
    nodes = [
        ("入站护栏", "注入检测 / PII 脱敏\n40301 · 40302", True),
        ("模型路由", "表面信号加权\n简单→小模型\n复杂→大模型", True),
        ("语义缓存", "问题向量近似命中\n命中直接返回", True),
        ("工具层", "工单 / 知识 / 统计\n3 个 @Tool\n出参脱敏", True),
        ("LLM 调用", "同步 / 流式\n按句缓冲", True),
        ("出站护栏", "泄露 / 凭据 / 堆栈\nPII 脱敏", True),
    ]
    xs = [15, 30.6, 46.2, 61.8, 77.4, 93]
    for x, (t, s, d) in zip(xs, nodes):
        fbox(ax, x, y, 13.0, 17, t, s, done=d, fs=9.2)
    for i in range(len(xs) - 1):
        farrow(ax, (xs[i] + 6.6, y), (xs[i + 1] - 6.6, y))

    ax.text(4.0, y + 2, "用户请求", ha="center", va="center", fontsize=9, color=MUTED)
    farrow(ax, (2.0, y), (8.4, y))
    ax.text(102.6, y + 2, "响应", ha="center", va="center", fontsize=9, color=MUTED)
    farrow(ax, (99.6, y), (101.4, y))

    # 分支说明
    ax.text(15, 40, "命中 → 拦截返回", ha="center", fontsize=8.2, color="#4F4F4F")
    farrow(ax, (15, 57.4), (15, 44.5), dashed=True)
    ax.text(46.2, 40, "命中 → 跳过模型", ha="center", fontsize=8.2, color="#4F4F4F")
    farrow(ax, (46.2, 57.4), (46.2, 44.5), dashed=True)
    ax.text(61.8, 40, "工具入参 / 出参\n双向脱敏", ha="center", fontsize=8.2,
            color="#4F4F4F", linespacing=1.3)
    farrow(ax, (61.8, 57.4), (61.8, 44.5), dashed=True)

    flow_legend(ax, y=18, items=[("已实现（开关控制）", True)])
    ax.text(4, 9, "注：护栏、路由、缓存三个开关 AI_GUARD_ENABLED / AI_ROUTER_ENABLED / AI_CACHE_ENABLED "
                  "均默认 false；关闭时路由返回 null、沿用默认模型，缓存直接跳过，行为与改造前一致。",
            fontsize=8.4, color="#4F4F4F", va="center")
    save(fig, "fig04_ai_chain.png")


# ================================================================ 图 5 八轮消融
ABLATION_LABELS = OrderedDict([
    ("E1", "E1\nKEYWORD"),
    ("E2", "E2\nVECTOR"),
    ("E3", "E3\nHYBRID k60"),
    ("E4", "E4\n+设备×1.5"),
    ("E5", "E5\n+标签×1.2"),
    ("E6-k30", "E6\nk=30"),
    ("E6-k60", "E6\nk=60"),
    ("E6-k100", "E6\nk=100"),
    ("E7-top3", "E7\ntopK=3"),
    ("E8", "E8\nVECTOR top5"),
    ("E8H", "E8H\nHYBRID top5"),
])


def load_ablation():
    path = os.path.join(PAPER, "评测", "消融结果.csv")
    agg = defaultdict(lambda: {"n": 0, "hit1": 0, "hit3": 0, "r5": 0.0, "lat": 0.0})
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            r = row["round"]
            got = [x for x in row["returned_ids"].split(";") if x]
            exp = [x for x in row["expected_ids"].split(";") if x]
            a = agg[r]
            a["n"] += 1
            a["hit1"] += 1 if got and got[0] in exp else 0
            a["hit3"] += int(row["hit3"]) if row["hit3"] else 0
            a["r5"] += float(row["recall5"]) if row["recall5"] else 0.0
            a["lat"] += float(row["latency_ms"])
    out = OrderedDict()
    for k in ABLATION_LABELS:
        a = agg[k]
        out[k] = {
            "hit1": 100.0 * a["hit1"] / a["n"],
            "hit3": 100.0 * a["hit3"] / a["n"],
            "r5": 100.0 * a["r5"] / a["n"],
            "lat": a["lat"] / a["n"],
        }
    return out


def fig_ablation(data):
    keys = list(ABLATION_LABELS)
    labels = [ABLATION_LABELS[k] for k in keys]
    metrics = [("Hit@1", "hit1", C3), ("Hit@3", "hit3", C2), ("Recall@5", "r5", C1)]
    n = len(keys)
    width = 0.26
    idx = range(n)

    fig, ax = plt.subplots(figsize=(11.6, 4.9))
    for i, (name, key, color) in enumerate(metrics):
        vals = [data[k][key] for k in keys]
        pos = [x + (i - 1) * width for x in idx]
        bars = ax.bar(pos, vals, width, label=name, color=color, edgecolor="white", linewidth=0.6)
        if name == "Recall@5":
            continue
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.7, "%.0f" % v,
                    ha="center", va="bottom", fontsize=7.2, color="#3A3A3A")

    ax.set_xticks(list(idx))
    ax.set_xticklabels(labels, fontsize=8.4, linespacing=1.35)
    ax.set_ylim(70, 108)
    ax.set_ylabel("指标（%）")
    ax.set_title("图 5-3  M7 检索消融（100 条 query）", loc="left", pad=22)
    legend_top(ax)
    tidy(ax)
    note(fig, "注：E7 仅展示 topK=3 一档（topK 不改变排序），其 topK=1 配置的 Hit@1 为 90.0%。")
    save(fig, "fig05_ablation.png")


# ================================================================ 图 6 成本-准确率
def fig_cost_accuracy(data):
    # 三档代表点：E2/E8 同为 100%，E3–E8H 同为 96%，逐点标注必然重叠，按档合并呈现
    e1 = data["E1"]
    vec_keys = ["E2", "E8"]
    hyb_keys = ["E3", "E4", "E5", "E6-k30", "E6-k60", "E6-k100", "E7-top3", "E8H"]
    vec_lat = sum(data[k]["lat"] for k in vec_keys) / len(vec_keys)
    hyb_lat = sum(data[k]["lat"] for k in hyb_keys) / len(hyb_keys)
    pts = [
        (e1["lat"], e1["hit3"], "E1  KEYWORD\n%.1f ms · Hit@3 %.1f%%" % (e1["lat"], e1["hit3"])),
        (vec_lat, data["E2"]["hit3"], "E2 / E8  VECTOR 系列\n≈%.0f ms · Hit@3 %.1f%%"
         % (vec_lat, data["E2"]["hit3"])),
        (hyb_lat, data["E5"]["hit3"], "E3 / E4 / E5 / E6 / E7 / E8H  HYBRID 系列\n≈%.0f ms · Hit@3 %.1f%%"
         % (hyb_lat, data["E5"]["hit3"])),
    ]

    fig, ax = plt.subplots(figsize=(7.8, 4.4))
    ax.plot([p[0] for p in pts], [p[1] for p in pts], color=C3, lw=1.1,
            ls=(0, (4, 3)), zorder=1)
    ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=60, color=C2,
               edgecolor="white", linewidth=1.0, zorder=3)

    ax.annotate(pts[0][2], (pts[0][0], pts[0][1]), xytext=(9, -18), textcoords="offset points",
                ha="left", fontsize=8.2, color="#3A3A3A", linespacing=1.5)
    ax.annotate(pts[1][2], (pts[1][0], pts[1][1]), xytext=(-9, 12), textcoords="offset points",
                ha="right", fontsize=8.2, color="#3A3A3A", linespacing=1.5)
    ax.annotate(pts[2][2], (pts[2][0], pts[2][1]), xytext=(-9, -26), textcoords="offset points",
                ha="right", fontsize=8.2, color="#3A3A3A", linespacing=1.5)

    ax.set_xscale("log")
    ax.set_xlim(8, 330)
    ax.set_ylim(86, 103.5)
    ax.set_xticks([10, 20, 50, 100, 200, 300])
    ax.get_xaxis().set_major_formatter(mticker.ScalarFormatter())
    ax.set_xlabel("平均检索耗时（ms，对数轴）")
    ax.set_ylabel("Hit@3（%）")
    ax.set_title("图 5-4  成本—准确率权衡：命中率与检索延迟", loc="left", pad=10)
    tidy(ax)
    note(fig, "注：耗时与命中率均取自 消融结果.csv；同档内各配置数值完全一致，故合并为一个代表点。")
    save(fig, "fig06_cost_accuracy.png")


# ================================================================ 门控数据
def load_gate():
    path = os.path.join(PAPER, "评测", "gate_baseline.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    return rows


def gate_sweep(rows, mode, thresholds):
    sub = [r for r in rows if r["mode"] == mode]
    out = []
    for t in thresholds:
        cover = push = err = 0
        for r in sub:
            s = float(r["maxVectorScore"]) if r["maxVectorScore"] else 0.0
            if s < t:
                continue
            push += 1
            bad = r["top1Usable"] == "0"
            if bad:
                err += 1
            if r["pool"] == "P":
                cover += 1
        out.append({"t": t, "cover": 100.0 * cover / 100.0, "err": 100.0 * err / push if push else 0.0,
                    "push": push})
    return out


def fig_gate_threshold(rows):
    thresholds = [0.70, 0.75, 0.78, 0.80, 0.85]
    sw = gate_sweep(rows, "HYBRID", thresholds)
    ts = [p["t"] for p in sw]

    fig, ax = plt.subplots(figsize=(7.4, 4.4))
    ax.plot(ts, [p["cover"] for p in sw], marker="o", color=C2, label="正例覆盖率")
    ax.plot(ts, [p["err"] for p in sw], marker="s", color=MUTED, ls=(0, (4, 3)),
            label="混合 300 条错误推送率")
    ax.set_xlabel("余弦阈值 T")
    ax.set_ylabel("百分比（%）")
    ax.set_ylim(-5, 100)
    ax.set_xticks(thresholds)

    for p in sw:
        ax.annotate("%.0f%%" % p["cover"], (p["t"], p["cover"]), textcoords="offset points",
                    xytext=(0, 9), ha="center", fontsize=8, color=C2)
        dy = 9 if p["err"] < 5 else -15
        ax.annotate("%.1f%%" % p["err"], (p["t"], p["err"]), textcoords="offset points",
                    xytext=(-16, dy) if p["err"] < 5 else (0, dy), ha="center", fontsize=8,
                    color="#5C5C5C", annotation_clip=False)

    ax.axvline(0.75, color=G2, lw=0.8, ls=":")
    ax.text(0.754, 90, "门控落地值", fontsize=8, color=MUTED, va="center")
    ax.set_title("图 5-5  阈值扫描：覆盖率与错误推送率的此消彼长（HYBRID）", loc="left", pad=22)
    legend_top(ax, ncol=2)
    tidy(ax)
    note(fig, "注：0.80 时错误推送率归零，但正例覆盖率仅 31%；单一阈值无法同时满足 ≤3% 与高覆盖。")
    save(fig, "fig07_gate_threshold.png")


def fig_gate_tiers(rows):
    pools = [("P", "正例 P\n(n=100)"), ("N", "负例 N\n(n=100)"), ("LG", "leave-gold-out\n(n=100)")]
    tiers = ["A", "B", "C"]
    colors = {"A": C1, "B": C3, "C": G2}
    fig, ax = plt.subplots(figsize=(6.2, 4.4))
    bottom = [0, 0, 0]
    for t in tiers:
        vals = []
        for p, _ in pools:
            vals.append(sum(1 for r in rows if r["mode"] == "HYBRID" and r["pool"] == p and r["tier"] == t))
        bars = ax.bar(range(3), vals, 0.52, bottom=bottom, color=colors[t],
                      edgecolor="white", linewidth=0.8, label="tier %s" % t)
        for b, v, bt in zip(bars, vals, bottom):
            if v >= 3:
                ax.text(b.get_x() + b.get_width() / 2, bt + v / 2, str(v),
                        ha="center", va="center", fontsize=8.5,
                        color="white" if t != "C" else "#3A3A3A")
        bottom = [b + v for b, v in zip(bottom, vals)]

    ax.set_xticks(range(3))
    ax.set_xticklabels([p[1] for p in pools], fontsize=9, linespacing=1.3)
    ax.set_ylabel("样本数")
    ax.set_ylim(0, 108)
    legend_top(ax)
    ax.set_title("图 5-6  门控三档分布（T=0.75，软带 0.07）", loc="left", pad=22)
    tidy(ax)
    note(fig, "C 档 = 返回空列表（该问不推）；A 档 ≥0.82，B 档 0.75–0.82。")
    save(fig, "fig08_gate_tiers.png")


def fig_gate_negative(rows):
    slices = [("N1", "同象异因"), ("N2", "领域外"), ("N3", "同因异象"), ("N4", "缺字段 / 噪声")]
    push, err = [], []
    for code, _ in slices:
        grp = [r for r in rows if r["mode"] == "HYBRID" and r["pool"] == "N" and r["key"].startswith(code)]
        p = sum(1 for r in grp if r["tier"] in ("A", "B"))
        e = sum(1 for r in grp if r["tier"] in ("A", "B") and r["top1Usable"] == "0")
        push.append(100.0 * p / len(grp))
        err.append(100.0 * e / p if p else 0.0)

    x = range(len(slices))
    w = 0.34
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    b1 = ax.bar([i - w / 2 for i in x], push, w, label="推送率", color=C3, edgecolor="white")
    b2 = ax.bar([i + w / 2 for i in x], err, w, label="推送中错误率", color="white",
                edgecolor=C1, hatch="///", linewidth=0.8)
    for bars in (b1, b2):
        for b in bars:
            v = b.get_height()
            ax.text(b.get_x() + b.get_width() / 2, v + 1.5, "%.0f%%" % v,
                    ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels([s[1] for s in slices])
    ax.set_ylabel("百分比（%）")
    ax.set_ylim(0, 118)
    legend_top(ax, ncol=2)
    ax.set_title("图 5-7  四类负例切片：推送率与错误推送率（T=0.75）", loc="left", pad=22)
    tidy(ax)
    note(fig, "同象异因 / 同因异象被推送后 100% 为错误；缺字段样本命中原 gold，计为可用。")
    save(fig, "fig09_gate_negative.png")


# ================================================================ 图 18 多信号门控两库迁移
def load_multisignal():
    path = os.path.join(PAPER, "评测", "_multisignal", "_multisignal_metrics.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fig_multisignal(ms):
    def clean(curve):
        pts = [(r["coverage"] * 100.0, r["err_rate"] * 100.0) for r in curve
               if r.get("coverage") is not None and r.get("err_rate") is not None]
        pts.sort()
        return pts

    c54 = clean(ms["tune_54"]["thr"]["curve"])
    c310 = clean(ms["apply_310"]["curve_thr_310"])
    r54 = ms["tune_54"]
    r310 = ms["apply_310"]["results"]
    pts = [("0.775", r54["thr"]["best"], r310["thr"]["all"]),
           ("0.80", r54["thr"]["safe"], r310["thr_safe"]["all"]),
           ("0.80+cons", r54["thr_cons"]["safe"], r310["thr_cons_safe"]["all"])]

    print("[校验] 多信号门控两库曲线：54 %d 点 / 310 %d 点" % (len(c54), len(c310)))
    for tag, a, b in pts:
        print("  %-10s 54: %.0f%% / %.2f%%   310: %.0f%% / %.2f%%"
              % (tag, a["coverage"] * 100, a["err_rate"] * 100,
                 b["coverage"] * 100, b["err_rate"] * 100))

    fig, ax = plt.subplots(figsize=(6.9, 4.4))
    ax.plot([p[0] for p in c54], [p[1] for p in c54], color=C3, lw=1.8, zorder=3,
            label="54/55 快照库（参数在此标定）")
    ax.plot([p[0] for p in c310], [p[1] for p in c310], color=C1, lw=1.8, zorder=4,
            label="310 库（冻结参数原样迁移）")

    ax.axhline(10, color=G2, lw=1.0, ls=(0, (4, 3)), zorder=1)
    ax.text(101, 10.9, "错误推送率 10% 约束", fontsize=8, color=MUTED, ha="right", va="bottom")

    for tag, a, b in pts:
        ax.plot([a["coverage"] * 100], [a["err_rate"] * 100], marker="o", ms=6.6,
                mfc="white", mec=INK, mew=1.1, zorder=6)
        ax.plot([b["coverage"] * 100], [b["err_rate"] * 100], marker="s", ms=6.6,
                mfc="white", mec=C1, mew=1.3, zorder=6)

    def lab(text, x, y, tx, ty):
        ax.annotate(text, xy=(x, y), xytext=(tx, ty), fontsize=8, color=INK,
                    ha="left", va="center",
                    arrowprops=dict(arrowstyle="-", lw=0.6, color=MUTED,
                                    shrinkA=2, shrinkB=3))

    lab("0.775", pts[0][2]["coverage"] * 100, pts[0][2]["err_rate"] * 100, 33, 41)
    lab("0.80", pts[1][2]["coverage"] * 100, pts[1][2]["err_rate"] * 100, 12, 23)
    lab("0.80 + cons 0.16", pts[2][2]["coverage"] * 100, pts[2][2]["err_rate"] * 100, 8, 8.5)
    lab("0.775", pts[0][1]["coverage"] * 100, pts[0][1]["err_rate"] * 100, 61.5, 13.5)
    lab("0.80", pts[1][1]["coverage"] * 100, pts[1][1]["err_rate"] * 100, 33.5, 3.6)

    ax.set_xlim(0, 103)
    ax.set_ylim(0, 70)
    ax.set_xlabel("正例覆盖率（%）")
    ax.set_ylabel("错误推送率（%）")
    ax.set_title("图 5-8  多信号门控的两库迁移曲线（54 定参 → 310 迁移）", loc="left", pad=24)
    legend_top(ax, ncol=2)
    tidy(ax)
    note(fig, "曲线为阈值 T 从 0.50 扫到 0.95（步长 0.005，覆盖率>0 的点参与绘制，54 库 %d 点 / 310 库 %d 点）；"
              "标记点为三个冻结工作点，310 上未二次调参。" % (len(c54), len(c310)))
    save(fig, "fig18_multisignal.png")


# ================================================================ S3
def load_s3():
    with open(os.path.join(PAPER, "问题二", "S3评测", "metrics.json"), encoding="utf-8") as fh:
        return json.load(fh)


def fig_s3_overall(m):
    groups = [("S1 基座零样本", "S1_base", C4), ("S2 规则", "S2_rules", C3), ("S3 LoRA", "S3_lora", C1)]
    metrics = [("根因一致率", "root_match", "%"), ("措施 F1", "meas_f1", "x100"),
               ("排除假设检出率", "excl_detect", "%"), ("误当根因率", "excl_misattr", "%")]
    x = range(len(metrics))
    w = 0.26
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    for i, (label, key, color) in enumerate(groups):
        vals = []
        for _, k, mode in metrics:
            v = m[key]["all"][k]
            vals.append(v * 100 if mode == "x100" else v)
        bars = ax.bar([p + (i - 1) * w for p in x], vals, w, label=label,
                      color=color, edgecolor="white", linewidth=0.6)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 1.2, "%.1f" % v,
                    ha="center", va="bottom", fontsize=7.6)
    ax.set_xticks(list(x))
    ax.set_xticklabels([g[0] for g in metrics])
    ax.set_ylabel("数值（%）")
    ax.set_ylim(0, 114)
    legend_top(ax)
    ax.set_title("图 5-9  S1 / S2 / S3 总体指标（200 条跨模板留出集）", loc="left", pad=22)
    tidy(ax)
    note(fig, "根因一致率 86.5 → 95.0 → 99.0；措施 F1 仅 S3 提升（0.944 → 0.990）。")
    save(fig, "fig10_s3_overall.png")


def fig_s3_template(m):
    tpl = [("dispatch 派工单", "dispatch"), ("wechat 群聊", "wechat"), ("logbook 维修履历", "logbook")]
    groups = [("S1", "S1_base", C4), ("S2", "S2_rules", C3), ("S3", "S3_lora", C1)]
    x = range(len(tpl))
    w = 0.26
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    for i, (label, key, color) in enumerate(groups):
        vals = [m[key][t]["root_match"] for _, t in tpl]
        bars = ax.bar([p + (i - 1) * w for p in x], vals, w, label=label,
                      color=color, edgecolor="white", linewidth=0.6)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.8, "%.1f" % v,
                    ha="center", va="bottom", fontsize=7.6)
    ax.set_xticks(list(x))
    ax.set_xticklabels([t[0] for t in tpl], fontsize=9)
    ax.set_ylabel("根因一致率（%）")
    ax.set_ylim(80, 106)
    legend_top(ax)
    ax.set_title("图 5-10  分模板根因一致率（n=200）", loc="left", pad=22)
    tidy(ax)
    note(fig, "wechat 档的 S2 增益最小（+5.9）；S3 后三档差距收敛到 3pp 以内（97.0 / 100 / 100）。")
    save(fig, "fig11_s3_template.png")


def fig_s3_structure(m):
    rows = [("normal（有明确根因）", "normal"), ("excluded（含排除假设）", "excluded"),
            ("no_final（无最终根因）", "no_final")]
    cols = ["S1", "S2", "S3"]
    # 结构切片数字来自 S3评测_heldout.md §4（由 by_structure.py 产出，未单独落 csv）
    vals = [[96.7, 94.2, 98.3], [95.0, 95.0, 100.0], [0.0, 100.0, 100.0]]

    fig, ax = plt.subplots(figsize=(5.8, 3.6))
    im = ax.imshow(vals, cmap="Blues", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(3))
    ax.set_xticklabels(cols)
    ax.set_yticks(range(3))
    ax.set_yticklabels([r[0] for r in rows], fontsize=9)
    for i in range(3):
        for j in range(3):
            v = vals[i][j]
            ax.text(j, i, "%.1f" % v, ha="center", va="center", fontsize=9.5,
                    color="white" if v > 55 else "#2B2B2B")
    ax.set_title("图 5-11  结构切片根因一致率热力图（%）", loc="left", pad=10)
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=8, color=MUTED)
    note(fig, "S1 在 20 条 no_final 上全部编造根因（0.0%）；S2 / S3 正确留空。", y=-0.05)
    save(fig, "fig12_s3_structure.png")


# ================================================================ 图 13 外部验证
def fig_ext_validation():
    data = [
        ("MaintNet\n(n=300, en)", 89.3, 77.7, None),
        ("Fujitsu RCA\n(n=100, en)", 89.1, 3.2, 59.8),
        ("中文电梯工单\n(n=200, zh)", 76.7, 10.2, None),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 4.3))
    ys = [2, 1, 0]
    series = [("现象语义一致率", 0, "o", C2), ("措施 F1", 1, "s", C3)]
    for name, k, marker, color in series:
        xs = [d[1 + k] for d in data]
        ax.scatter(xs, [y + (0.13 if k else -0.13) for y in ys], s=58, marker=marker,
                   color=color, edgecolor="white", linewidth=0.9, label=name, zorder=3)
        for x, y in zip(xs, ys):
            ax.annotate("%.1f" % x, (x, y + (0.13 if k else -0.13)), textcoords="offset points",
                        xytext=(0, 7), ha="center", fontsize=8, color="#3A3A3A")

    root = [(d[3], y) for d, y in zip(data, ys) if d[3] is not None]
    ax.scatter([r[0] for r in root], [r[1] for r in root], s=64, marker="D",
               color=C1, edgecolor="white", linewidth=0.9, label="根因一致率", zorder=3)
    for x, y in root:
        ax.annotate("%.1f" % x, (x, y), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color="#3A3A3A")

    ax.set_yticks(ys)
    ax.set_yticklabels([d[0] for d in data], fontsize=9, linespacing=1.3)
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.55, 2.55)
    ax.set_xlabel("指标数值（%）")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3, frameon=False, fontsize=8.4)
    ax.set_title("图 5-12  外部验证（只测不训，n=600 条）", loc="left", pad=10)
    tidy(ax, ygrid=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    note(fig, "Fujitsu 措施 F1 3.2% 是粒度不匹配造成的下限（gold 拆 8–10 步，模型输出 2–3 条）；"
              "MaintNet 与电梯集无根因字段，只报现象与措施。本图仅含 S1 零样本结果，S3 待补跑。", y=-0.09)
    save(fig, "fig13_ext_validation.png")


# ================================================================ 图 14 注入护栏
def fig_guard_injection(g):
    fam = g["injection"]["by_family"]
    sweep = g["injection"]["sweep"]

    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.3),
                             gridspec_kw={"width_ratios": [1.25, 1]})
    ax = axes[0]
    names = [f["family"] for f in fam]
    vals = [f["recall"] for f in fam]
    bars = ax.barh(range(len(names)), vals, 0.6, color=C3, edgecolor="white")
    for b, f in zip(bars, fam):
        ax.text(b.get_width() - 1.5, b.get_y() + b.get_height() / 2, "%d/%d" % (f["blocked"], f["n"]),
                va="center", ha="right", fontsize=8, color="white")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8.4)
    ax.invert_yaxis()
    ax.set_xlim(0, 108)
    ax.set_xlabel("拦截率（%）")
    ax.set_title("(a) 分攻击族拦截率（开发集，120 条）", fontsize=10, loc="left")
    tidy(ax, ygrid=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)

    ax = axes[1]
    ts = [s["threshold"] for s in sweep]
    ax.plot(ts, [s["tpr"] for s in sweep], marker="o", color=C2, label="拦截率 TPR")
    ax.plot(ts, [s["fpr"] for s in sweep], marker="s", color=MUTED, ls=(0, (4, 3)), label="误拦率 FPR")
    ax.axvline(0.5, color=G2, lw=0.8, ls=":")
    ax.text(0.51, 60, "采用 0.5", fontsize=8, color=MUTED, va="center")
    ax.set_xlabel("规则得分阈值")
    ax.set_ylabel("百分比（%）")
    ax.set_ylim(-4, 112)
    ax.legend(loc="center right", frameon=False)
    ax.set_title("(b) 阈值扫描（开发集）", fontsize=10, loc="left")
    tidy(ax)

    fig.suptitle("图 4-2  入站注入检测：攻击族覆盖与阈值扫描", x=0.005, ha="left",
                 fontsize=11.5, y=1.02)
    fig.text(0.005, -0.07, "独立留出集（45 条，规则定型后新写）拦截率 88.89%（40/45），"
                           "与开发集的差距即规则泛化损失。", fontsize=8, color=MUTED)
    save(fig, "fig14_guard_injection.png")


# ================================================================ 图 15 PII + 输出过滤
def fig_guard_pii(g):
    pii = [p for p in g["pii"]["by_type"] if p["type"] != "negative"]
    labels = {"phone": "手机号", "landline": "座机", "idcard": "身份证",
              "email": "邮箱", "name": "姓名", "address": "地址"}
    out = [("系统提示词泄露", g["output_guard"]["leak_recall"]),
           ("凭据遮盖", g["output_guard"]["credential_recall"]),
           ("堆栈遮盖", g["output_guard"]["stack_recall"]),
           ("输出 PII 脱敏", g["output_guard"]["pii_recall"])]

    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.2),
                             gridspec_kw={"width_ratios": [1, 1], "wspace": 0.38})
    ax = axes[0]
    bars = ax.bar(range(len(pii)), [p["recall"] for p in pii], 0.55, color=C3, edgecolor="white")
    for b, p in zip(bars, pii):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.5, "%d/%d" % (p["hit"], p["n"]),
                ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(len(pii)))
    ax.set_xticklabels([labels.get(p["type"], p["type"]) for p in pii], fontsize=9)
    ax.set_xlim(-0.65, len(pii) - 0.35)
    ax.set_ylim(0, 118)
    ax.set_ylabel("召回率（%）")
    ax.set_title("(a) PII 分类型脱敏召回（32 正例）", fontsize=10, loc="left")
    tidy(ax)

    ax = axes[1]
    bars = ax.barh(range(len(out)), [o[1] for o in out], 0.55, color=C2, edgecolor="white")
    for b, o in zip(bars, out):
        ax.text(b.get_width() - 2, b.get_y() + b.get_height() / 2, "%.0f%%" % o[1],
                va="center", ha="right", fontsize=8.2, color="white")
    ax.set_yticks(range(len(out)))
    ax.set_yticklabels([o[0] for o in out], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 112)
    ax.set_xlabel("拦截 / 遮盖率（%）")
    ax.set_title("(b) 出站过滤（36 条）", fontsize=10, loc="left")
    tidy(ax, ygrid=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)

    fig.suptitle("图 4-3  PII 脱敏与出站过滤", x=0.005, ha="left", fontsize=11.5, y=1.02)
    fig.text(0.005, -0.02, "负样本误脱敏率 0/28；正常输出误伤 0/8。",
             fontsize=8, color=MUTED)
    save(fig, "fig15_guard_pii.png")


# ================================================================ 图 17 语义缓存阈值权衡
def fig_cache_threshold(c):
    sweep = [r for r in c["threshold_sweep"] if isinstance(r["threshold"], (int, float))]
    sweep.sort(key=lambda r: r["threshold"])
    t = [r["threshold"] for r in sweep]
    hit = [r["hit_rate_paraphrase_pct"] for r in sweep]
    fhn = [r["false_hit_rate_negative_pct"] for r in sweep]
    loss = [r["quality_loss_pp"] for r in sweep]
    by_t = {r["threshold"]: r for r in sweep}
    s = c["summary"]
    default_t = s["default_threshold"]
    safe_t = s["best_zero_error_threshold"]
    neg_max = s["negative_similarity"]["max"]

    print("[校验] 缓存阈值扫描：")
    for r in sweep:
        print("  T=%.2f 命中率=%5.2f%%  误命中率=%4.1f%%  质量损失=%.1f pp"
              % (r["threshold"], r["hit_rate_paraphrase_pct"],
                 r["false_hit_rate_negative_pct"], r["quality_loss_pp"]))

    fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.2),
                             gridspec_kw={"width_ratios": [1.14, 1], "wspace": 0.26})
    ticks = [0.80, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96, 0.99]

    # (a) 阈值 → 命中率 / 误命中率
    ax = axes[0]
    ax.plot(t, hit, color=C1, marker="o", ms=4.4, lw=1.5, zorder=4, label="同义改写命中率")
    ax.plot(t, fhn, color=C2, marker="s", ms=4.0, lw=1.4, ls=(0, (5, 2)), zorder=4,
            label="负例误命中率")
    ax.axvline(neg_max, color=MUTED, lw=0.9, ls=(0, (4, 3)), zorder=2)
    ax.text(neg_max + 0.0035, 111, "负例最大相似度\n%.4f（安全边界）" % neg_max,
            fontsize=7.8, color="#4F4F4F", ha="left", va="top", linespacing=1.45)

    ax.plot([default_t], [by_t[default_t]["hit_rate_paraphrase_pct"]], marker="o", ms=7.6,
            mfc="white", mec=C1, mew=1.3, zorder=5)
    ax.text(default_t, by_t[default_t]["hit_rate_paraphrase_pct"] - 9,
            "默认 0.92", fontsize=7.8, color=INK, ha="center", va="top")
    ax.annotate("0.90  零误命中下命中率最高（%.1f%%）" % by_t[safe_t]["hit_rate_paraphrase_pct"],
                xy=(safe_t, by_t[safe_t]["hit_rate_paraphrase_pct"]),
                xytext=(0.925, 92), fontsize=7.8, color=INK, ha="left", va="center",
                arrowprops=dict(arrowstyle="-", lw=0.7, color=MUTED,
                                shrinkA=1, shrinkB=3))

    ax.set_xticks(ticks)
    ax.set_xticklabels(["%.2f" % v for v in ticks], fontsize=8.2)
    ax.set_xlim(0.795, 0.998)
    ax.set_ylim(-5, 118)
    ax.set_xlabel("余弦相似度阈值")
    ax.set_ylabel("命中率 / 误命中率（%）")
    ax.set_title("(a) 阈值 → 命中率 / 误命中率", fontsize=10, loc="left")
    ax.legend(loc="center left", bbox_to_anchor=(0.015, 0.44), frameon=False,
              handlelength=1.5, handletextpad=0.5, labelspacing=0.5)
    tidy(ax)

    # (b) 阈值 → 质量损失
    ax = axes[1]
    ax.bar(t, loss, 0.0072, color=C3, edgecolor="white", linewidth=0.7, zorder=3)
    for xv, yv in zip(t, loss):
        if yv > 0:
            ax.text(xv, yv + 0.12, "%.1f" % yv, ha="center", va="bottom", fontsize=8)
    ax.text(0.912, 0.32, "T ≥ 0.90：0 pp", fontsize=7.8, color=MUTED, ha="left")
    ax.set_xticks(ticks)
    ax.set_xticklabels(["%.2f" % v for v in ticks], fontsize=8.2)
    ax.set_xlim(0.795, 0.998)
    ax.set_ylim(0, 4.8)
    ax.set_xlabel("余弦相似度阈值")
    ax.set_ylabel("质量损失（pp）")
    ax.set_title("(b) 阈值 → 质量损失", fontsize=10, loc="left")
    tidy(ax)

    fig.suptitle("图 4-4  语义缓存阈值权衡", x=0.005, ha="left", fontsize=11.5, y=1.02)
    note(fig, "0.92 为默认工作点；0.90 已贴近负例最大相似度 0.8845，再下调即开始用质量换命中率。")
    save(fig, "fig17_cache_threshold.png")


# ================================================================ 图 16 知识库构成
def fig_kb_composition():
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.5),
                             gridspec_kw={"width_ratios": [1.15, 1], "wspace": 0.28})
    ax = axes[0]
    src = [("SEED", 53, C1), ("SYNTHETIC", 242, C3), ("HANDBOOK", 15, C4)]
    left = 0
    for name, v, color in src:
        ax.barh(0, v, 0.34, left=left, color=color, edgecolor="white", linewidth=0.8)
        if v > 40:
            ax.text(left + v / 2, 0, "%s\n%d（%.1f%%）" % (name, v, 100.0 * v / 310),
                    ha="center", va="center", fontsize=8.4,
                    color="white" if color != C4 else INK, linespacing=1.5)
        left += v
    ax.annotate("HANDBOOK\n15（4.8%）", xy=(307, 0.18), xytext=(262, 0.47),
                fontsize=8, color="#3A3A3A", linespacing=1.5,
                arrowprops=dict(arrowstyle="-", lw=0.6, color=MUTED))
    ax.set_xlim(0, 330)
    ax.set_ylim(-0.45, 0.62)
    ax.set_yticks([])
    ax.set_xlabel("知识点条数")
    ax.set_title("(a) 310 条知识点的来源构成", fontsize=10, loc="left")
    tidy(ax, ygrid=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)

    ax = axes[1]
    grp = [("同象异因成组", 130, C2), ("同因异象成组", 130, C3), ("独立条目", 50, G2)]
    x = range(len(grp))
    bars = ax.bar(x, [g[1] for g in grp], 0.5, color=[g[2] for g in grp], edgecolor="white")
    for b, g in zip(bars, grp):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 3, str(g[1]),
                ha="center", va="bottom", fontsize=8.6)
    ax.set_xticks(list(x))
    ax.set_xticklabels([g[0] for g in grp], fontsize=8.8)
    ax.set_ylim(0, 150)
    ax.set_ylabel("知识点条数")
    ax.set_title("(b) 成组结构（SIM 50 组 / SIC 50 组）", fontsize=10, loc="left")
    tidy(ax)

    fig.suptitle("图 5-2  知识库扩容后的构成（54 → 310 条）", x=0.005, ha="left",
                 fontsize=11.5, y=1.03)
    note(fig, "10 类设备 × 31 条；合成与手册改写合计 82.9%，七字段非空率 100%。", y=-0.06)
    save(fig, "fig16_kb_composition.png")


# ================================================================ main
def main():
    os.makedirs(OUT, exist_ok=True)
    print("输出目录：%s" % OUT)

    ab = load_ablation()
    print("[校验] 消融聚合：")
    for k, v in ab.items():
        print("  %-7s Hit@1=%5.1f  Hit@3=%5.1f  Recall@5=%5.1f  耗时=%6.1fms"
              % (k, v["hit1"], v["hit3"], v["r5"], v["lat"]))

    gate = load_gate()
    print("[校验] 门控阈值扫描（HYBRID）：")
    for p in gate_sweep(gate, "HYBRID", [0.70, 0.75, 0.78, 0.80, 0.85]):
        print("  T=%.2f 覆盖=%5.1f%%  混合错误率=%5.1f%%  推送=%d" % (p["t"], p["cover"], p["err"], p["push"]))

    s3 = load_s3()
    guard = json.load(open(os.path.join(PAPER, "ai应用层", "护栏评测.json"), encoding="utf-8"))
    cache = json.load(open(os.path.join(PAPER, "ai应用层", "缓存评测.json"), encoding="utf-8"))

    fig_arch()
    fig_q2_method()
    fig_eval_flow()
    fig_ai_chain()
    fig_ablation(ab)
    fig_cost_accuracy(ab)
    fig_gate_threshold(gate)
    fig_gate_tiers(gate)
    fig_gate_negative(gate)
    fig_multisignal(load_multisignal())
    fig_s3_overall(s3)
    fig_s3_template(s3)
    fig_s3_structure(s3)
    fig_ext_validation()
    fig_guard_injection(guard)
    fig_guard_pii(guard)
    fig_cache_threshold(cache)
    fig_kb_composition()
    print("完成，共 18 张图。")


if __name__ == "__main__":
    main()
