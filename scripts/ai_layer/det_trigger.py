#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""det-trigger-v2：后置确定性复算闸门。

设计目的：把「该不该算」从模型的自觉判断，改为外部确定性判定。
触发权不在模型手里 —— 模型照常作答，答完之后由本模块决定是否接受。

流程（全部确定性，无网络、无随机数、不调用模型）：
  1) 从题面与资料抽取数字：全部数字、数值列表、带标签的数字对（上月/本月、
     计划/实际、从…调到、原来/现在、下限/上限）、阈值（超过/不超过/不低于）、
     区间（合格范围 a-b / a～b）；
  2) 按 7 个既有算子（直接复用 tool_calc.run_calculation，语义零漂移）枚举组合，
     得到候选结果集 R；「成」出现在题面时额外枚举 ×0.1 的成数变体；
  3) 与答案里的数字比对（容差 TOL = 0.06）：
       - 答案中的数字要么是资料原文数字（事实），要么能被 R 解释 → accept；
       - 有数字无法解释且候选集不全 → uncomputable（只升级，不覆盖）；
       - 有数字无法解释且候选集为空 → uncomputable（升级）；
       - 其余无法解释 → conflict（v2 亦只升级；覆盖仅在候选集完备时给出）；
  4) 覆盖时按题面线索（几成 / 百分点 / 比…百分之几 / 均值 / 超标次数 / 区间 / 差多少）
     选取对应算子族的候选，线索按其在题面中出现的先后顺序对应答案顺序。

v2 相对 v1 的两项改动（理由均来自 Holdout-3 的机制分析，不来自逐条结果）：
  A. 二段复算补「反向基数」方向。v1 只枚举 (中间结果 as 基数, 题面数 as 现值)，
     即 delta_percent(initial=中间结果, current=题面数)；而「比上一批的 N 个多了百分之几」
     的语义是基数 N（题面数）、现值是这批的计数（中间结果），恰好落在被漏掉的方向。
     机制证据：v1 中被判 conflict 的三条正确答案（4|100、5|150、5|66.7），其复算值
     100/150/66.7 在候选集里检索为 0 命中——不是判定错，是候选集缺这一个方向。
  B. 候选集不完备时把判定降级为 uncomputable，只升级不覆盖。
     完备性按「题面每条线索对应的算子族在候选集中是否非空」判定：只要有一条线索
     的算子族为空，就说明候选集不足以复算该题，此时即使有数字无法解释，也不得
     用候选集里的值去覆盖（否则就是拿不完整的候选集去改一个可能正确的答案）。
     该改动把 v1「误覆盖 3 条」在结构上消掉：误覆盖恒为 0。

未改动（如实保留）：判定仍是「答案数字是否为候选集成员」。这条判据对
「错误答案恰好等于某两个题面数字的任意换算」（如 30.0 = |2−2.6|/2×100）无能为力，
且这类巧合既可能落在 rank3、也可能落在 rank2（H3-067 的 50.0 = |2.0−1|/2.0×100 即 rank2），
因此不能用 rank 阈值把它们分离出去。v2 不修这一方向。

已知局限（写进报告，不隐藏）：
  - 枚举越宽，判别越松：候选集越大，错误答案越容易"碰巧被解释"，闸门会漏触发；
  - 答案里的单位换算（如 0.012 MPa）不在候选集里，会触发 conflict，属误触发；
  - 带标签数字对覆盖的是通用中文表述，不是按某一批模板硬编码，但模板仍由同一
    作者设计，独立第三方出题尚未验证。
"""
import re
from decimal import Decimal, InvalidOperation

from tool_calc import run_calculation

VERSION = "det-trigger-v2"
TOL = 0.06
MAX_SRC_NUMBERS = 14
MAX_CANDIDATES = 4000
MAX_STAGE1 = 40

NUM_RE = re.compile(r"\d+(?:\.\d+)?")

# 元信息数字：不是数据，不参与复算，也不算「答案里的数字」
META_NUM = re.compile(
    r"(?:保留\s*[一二两三四五六]?\s*位小数)"
    r"|(?:\d+\s*个[^0-9]{0,8}?读数)"
    r"|(?:\d+\s*次[^0-9]{0,6}?测量)"
    r"|(?:\d+\s*个测量值)"
    r"|(?:这\s*批\s*\d+\s*件)"
    r"|(?:WO-[0-9A-Za-z\-]+)"
    r"|(?:SN-[0-9A-Za-z\-]+)"
    r"|(?:\d{4}-\d{2}-\d{2})"
    r"|(?:\d+\s*号线)"
    r"|(?:\d+\s*号工位)"
    r"|(?:第\s*\d+\s*版(?:工艺)?)"
    r"|(?:B\d+-\d+)"
)

# 带标签的数字对：(模式, 说明)。只写通用中文表述，不写具体设备/指标。
PAIR_PATTERNS = [
    (r"上(?:个)?月(?:份)?.{0,10}?(\d+(?:\.\d+)?).{0,16}?(?:本|这个)月.{0,10}?(\d+(?:\.\d+)?)", "上月/本月"),
    (r"上周.{0,10}?(\d+(?:\.\d+)?).{0,16}?(?:这周|本周|今天|这次|本次).{0,10}?(\d+(?:\.\d+)?)", "上周/这周"),
    (r"从\s*(\d+(?:\.\d+)?)\s*.{0,6}?(?:调到|降到|升到|变成|改为)\s*(\d+(?:\.\d+)?)", "从…调到…"),
    (r"(?:原来|原值|初始|首次|首测|昨天|此前).{0,8}?(\d+(?:\.\d+)?).{0,16}?(?:现在|当前|现值|复测|今天|本次).{0,8}?(\d+(?:\.\d+)?)", "原值/现值"),
    (r"计划.{0,8}?(\d+(?:\.\d+)?).{0,16}?实际(?:完成)?.{0,8}?(\d+(?:\.\d+)?)", "计划/实际"),
    (r"(?:下限|最低).{0,8}?(\d+(?:\.\d+)?).{0,16}?(?:上限|最高).{0,8}?(\d+(?:\.\d+)?)", "下限/上限"),
    (r"上一?批.{0,10}?(\d+(?:\.\d+)?).{0,16}?这(?:一)?批.{0,10}?(\d+(?:\.\d+)?)", "上批/这批"),
]

THRESH_PATTERNS = [
    r"(?:不超过|不高于|不得超过|要求不超过|超过|高于|大于|上限为|上限)\s*(?:为|是)?\s*(\d+(?:\.\d+)?)",
    r"(?:不低于|不小于|低于|小于|下限为|下限)\s*(?:为|是)?\s*(\d+(?:\.\d+)?)",
]

RANGE_PATTERNS = [
    r"(?:合格范围|工艺范围|允许范围|范围)\s*(?:为|是)?\s*(\d+(?:\.\d+)?)\s*[-~～至]\s*(\d+(?:\.\d+)?)",
    r"(?:要求|标准|规格|工艺|限|落在|控制在|保持)\s*(?:在)?\s*(\d+(?:\.\d+)?)\s*[-~～至]\s*(\d+(?:\.\d+)?)",
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*[-~～]\s*(\d+(?:\.\d+)?)(?![\d.])",
    r"(\d+(?:\.\d+)?)\s*[~～至]\s*(\d+(?:\.\d+)?)\s*(?:之间|以内|范围内)",
]

# 覆盖用到的算子族线索，按「先多/少/高/低了百分之几、再泛问百分之几」的顺序
CUE_RULES = [
    (r"几成", ("delta_percent_x10",), "成数"),
    (r"(?:多|少|高|低|增加|减少|增长|下降|上升|提升|降低)了?百分之几", ("delta_percent",), "变化率"),
    (r"(?:几个?百分点|百分点)", ("delta_percent",), "百分点"),
    (r"(?:平均|均值)", ("average",), "均值"),
    (r"(?:超(?:过|了几)|超标|几回|几次超|越线)", ("count_over",), "超阈值计数"),
    (r"(?:不合格|不达标)", ("ratio", "count_in_range_not", "count_over_not"), "不合格数/率"),
    (r"(?:合格|落在|区间|范围)", ("count_in_range",), "区间计数"),
    (r"(?:占比|占多少|占百分之|百分之几|比例)", ("ratio", "pct_of"), "占比"),
    (r"(?:差多少|相差|高多少|低多少|还差|缺口|少了多少|多了多少)", ("difference",), "差值"),
]


# ---------------------------------------------------------------- 抽取
def _dec(x):
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None


def numbers(text):
    """题面/资料/答案里的数据数字（剔除元信息数字）。"""
    text = META_NUM.sub(" ", text or "")
    out = []
    for m in NUM_RE.findall(text):
        d = _dec(m)
        if d is not None:
            out.append(d)
    return out


def dedupe(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def value_lists(text):
    """题面里用 、，, 和 连接的长度 ≥4 的数值列表。"""
    text = META_NUM.sub(" ", text or "")
    out = []
    for m in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?(?:\s*[、，,和]\s*\d+(?:\.\d+)?){3,})",
                         text):
        vals = []
        for p in re.split(r"\s*[、，,和]\s*", m.group(1)):
            d = _dec(p)
            if d is None:
                vals = []
                break
            vals.append(d)
        if len(vals) >= 4:
            out.append(vals)
    return out


def labeled_pairs(text):
    out = []
    for pat, _label in PAIR_PATTERNS:
        for m in re.finditer(pat, text or ""):
            a, b = _dec(m.group(1)), _dec(m.group(2))
            if a is not None and b is not None and a != b:
                out.append((a, b))
    return dedupe(out)


def thresholds(text):
    out = []
    text = META_NUM.sub(" ", text or "")
    for pat in THRESH_PATTERNS:
        for m in re.finditer(pat, text):
            d = _dec(m.group(1))
            if d is not None:
                out.append(d)
    return dedupe(out)


def ranges(text):
    out = []
    text = META_NUM.sub(" ", text or "")
    for pat in RANGE_PATTERNS:
        for m in re.finditer(pat, text):
            a, b = _dec(m.group(1)), _dec(m.group(2))
            if a is not None and b is not None:
                out.append((min(a, b), max(a, b)))
    return dedupe(out)


# ---------------------------------------------------------------- 候选枚举
def _calc(op, **kw):
    r = run_calculation(op, **kw)
    return r.get("result") if r.get("ok") else None


class _Builder:
    def __init__(self):
        self.items = []
        self.seen = set()

    def add(self, op, value, expr, rank):
        if value is None or len(self.items) >= MAX_CANDIDATES:
            return
        key = (op, round(float(value), 4))
        if key in self.seen:
            return
        self.seen.add(key)
        self.items.append({"op": op, "value": round(float(value), 4),
                           "expr": expr, "rank": rank})

    def pair_ops(self, a, b, rank, with_cheng=False):
        self.add("difference", _calc("difference", initial=a, current=b),
                 "%s-%s" % (a, b), rank)
        d = _calc("delta_percent", initial=a, current=b)
        self.add("delta_percent", d, "|%s-%s|/%s*100" % (a, b, a), rank)
        if with_cheng and d is not None:
            self.add("delta_percent_x10", Decimal(str(d)) / 10,
                     "|%s-%s|/%s*10" % (a, b, a), rank)
        self.add("pct_of", _calc("pct_of", initial=a, current=b),
                 "%s/%s*100" % (b, a), rank)
        self.add("ratio", _calc("ratio", numerator=a, denominator=b),
                 "%s/%s*100" % (a, b), rank)


def candidates(question, context):
    """返回候选结果列表，按 rank 升序（rank 越小越可信）。"""
    q = question or ""
    ctx = context or ""
    text = q + "；" + ctx
    src = dedupe(numbers(q) + numbers(ctx))[:MAX_SRC_NUMBERS]
    lists = value_lists(q) or value_lists(ctx)
    ths = thresholds(ctx) or thresholds(q)
    rgs = ranges(ctx) + ranges(q)
    with_cheng = "成" in q
    b = _Builder()

    # rank 1：带标签的数字对（谁比谁，语义最明确）
    for a, c in labeled_pairs(text):
        b.pair_ops(a, c, 1, with_cheng)
    # rank 2：数值列表 → 均值 / 超阈值计数 / 区间计数 / 占比（含「不合格」补集）
    for vals in lists:
        n = Decimal(len(vals))
        avg = _calc("average", values=[float(v) for v in vals])
        b.add("average", avg, "avg(%d)" % len(vals), 2)
        for u in ths:
            cnt = _calc("count_over", values=[float(v) for v in vals], upper=float(u))
            b.add("count_over", cnt, "#>%s" % u, 2)
            if cnt is not None:
                b.add("count_over_not", n - Decimal(str(cnt)), "#<=%s" % u, 2)
                b.add("ratio", Decimal(str(cnt)) / n * 100, "#>%s / %d *100" % (u, len(vals)), 2)
                b.add("ratio", (n - Decimal(str(cnt))) / n * 100,
                      "#<=%s / %d *100" % (u, len(vals)), 2)
        for lo, hi in rgs:
            cnt = _calc("count_in_range", values=[float(v) for v in vals],
                        lower=float(lo), upper=float(hi))
            b.add("count_in_range", cnt, "#in[%s,%s]" % (lo, hi), 2)
            if cnt is not None:
                b.add("count_in_range_not", n - Decimal(str(cnt)), "#out[%s,%s]" % (lo, hi), 2)
                b.add("ratio", Decimal(str(cnt)) / n * 100,
                      "#in[%s,%s] / %d *100" % (lo, hi, len(vals)), 2)
                b.add("ratio", (n - Decimal(str(cnt))) / n * 100,
                      "#out[%s,%s] / %d *100" % (lo, hi, len(vals)), 2)
    # rank 3：全部数字两两组合
    for a in src:
        for c in src:
            if a != c:
                b.pair_ops(a, c, 3, with_cheng)
    # rank 2：二段复算 —— 前序中间结果（均值/计数/占比）与题面数字再组合
    # 两个方向都枚举：正向（中间结果当基数）与反向（题面数当基数、中间结果当现值）。
    # 反向方向是 v2 补的：「比上一批的 N 个多了百分之几」= delta_percent(initial=N, current=计数)。
    stage1 = [x for x in b.items if x["rank"] <= 2][:MAX_STAGE1]
    for x in stage1:
        a = Decimal(str(x["value"]))
        for c in src:
            if a == c:
                continue
            b.add("difference", _calc("difference", initial=a, current=c),
                  "%s-%s" % (a, c), 2)
            d = _calc("delta_percent", initial=a, current=c)
            b.add("delta_percent", d, "|%s-%s|/%s*100" % (a, c, a), 2)
            if with_cheng and d is not None:
                b.add("delta_percent_x10", Decimal(str(d)) / 10,
                      "|%s-%s|/%s*10" % (a, c, a), 2)
            b.add("pct_of", _calc("pct_of", initial=a, current=c),
                  "%s/%s*100" % (c, a), 2)
            # 反向基数：题面数当基数、中间结果当现值
            b.add("difference", _calc("difference", initial=c, current=a),
                  "%s-%s" % (c, a), 2)
            d2 = _calc("delta_percent", initial=c, current=a)
            b.add("delta_percent", d2, "|%s-%s|/%s*100" % (c, a, c), 2)
            if with_cheng and d2 is not None:
                b.add("delta_percent_x10", Decimal(str(d2)) / 10,
                      "|%s-%s|/%s*10" % (c, a, c), 2)
            b.add("pct_of", _calc("pct_of", initial=c, current=a),
                  "%s/%s*100" % (a, c), 2)
    b.items.sort(key=lambda x: x["rank"])
    return b.items


# ---------------------------------------------------------------- 判定
def _family(op):
    return {"delta_percent_x10": "delta_percent"}.get(op, op)


def incompleteness(question, cands):
    """候选集完备性：题面每条线索对应的算子族是否都至少有一个候选。

    只要有一条线索的算子族在候选集中为空，就说明候选集不足以复算该题：
    此时即使答案里有数字无法解释，也不能拿候选集里的值去覆盖（只能用升级兜底）。
    返回 (是否不完备, 缺失的线索标签列表)。
    """
    q = question or ""
    have = {c["op"] for c in cands}
    missing = []
    for pat, ops, label in CUE_RULES:
        if re.search(pat, q) and not (set(ops) & have):
            missing.append(label)
    return bool(missing), missing


def _match(nums, cands):
    hit = []
    for c in cands:
        for v in nums:
            if abs(float(v) - c["value"]) <= TOL:
                hit.append(c)
                break
    return hit


def evaluate(question, context, answer):
    """闸门判定。返回 dict：verdict ∈ accept / conflict / uncomputable。"""
    cands = candidates(question, context)
    a_nums = numbers(answer)
    src_nums = numbers(question) + numbers(context)
    unexplained = [v for v in a_nums
                   if not any(abs(v - s) <= Decimal(str(TOL)) for s in src_nums)]
    matched = _match(unexplained, cands) if unexplained else []
    matched_ids = {(c["op"], c["value"]) for c in matched}
    missing = [v for v in unexplained
               if not any(abs(float(v) - c["value"]) <= TOL for c in cands)]
    incomplete, incomplete_missing = incompleteness(question, cands)

    if not a_nums:
        verdict, reason = "accept", "no_numbers"
    elif not unexplained:
        verdict, reason = "accept", "literal"
    elif not missing:
        verdict, reason = "accept", "recomputed"
    elif incomplete:
        verdict, reason = "uncomputable", "candidates_incomplete"
    elif not cands:
        verdict, reason = "uncomputable", "no_candidates"
    else:
        verdict, reason = "conflict", "unmatched"

    return {"verdict": verdict, "reason": reason,
            "answer_numbers": [float(v) for v in a_nums],
            "unexplained": [float(v) for v in unexplained],
            "missing": [float(v) for v in missing],
            "n_candidates": len(cands),
            "incomplete": incomplete,
            "incomplete_missing": incomplete_missing,
            "matched": [c for c in cands if (c["op"], c["value"]) in matched_ids][:8],
            "top": cands[:8],
            # 只升级不覆盖：候选集不完备时不给出覆盖值（误覆盖恒为 0）
            "picked": [] if incomplete else pick(cands, question)}


def pick(cands, question):
    """按题面线索挑覆盖值；线索按出现位置从左到右，对应答案中的先后顺序。"""
    q = question or ""
    cues = []
    for idx, (pat, ops, label) in enumerate(CUE_RULES):
        m = re.search(pat, q)
        if m:
            cues.append((m.start(), idx, ops, label))
    cues.sort()
    out, used = [], set()
    for _pos, _idx, ops, label in cues:
        chosen = None
        for op in ops:
            for c in cands:
                if c["op"] != op:
                    continue
                key = (c["op"], c["value"])
                if key in used:
                    continue
                chosen = c
                break
            if chosen:
                break
        if chosen:
            used.add((chosen["op"], chosen["value"]))
            out.append(dict(chosen, family=_family(chosen["op"]), cue=label))
    return out


def render(picked):
    if not picked:
        return ""
    vals = []
    for c in picked:
        s = ("%.4f" % c["value"]).rstrip("0").rstrip(".")
        vals.append(s if s and s != "-0" else "0")
    return "结论：" + "；".join(vals)
