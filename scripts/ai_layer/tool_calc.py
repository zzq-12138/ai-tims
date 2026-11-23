#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性计算工具：原型阶段用 Python，将来落 Java 时按同一口径用 BigDecimal 实现。

所有算术只在这里发生，模型只负责把题面数字与关系抽成参数。
工具不做任何语义理解，参数不对就宁可报错，绝不"猜"。

支持的运算（op）：
  difference     差：initial - current（也可用 values[0] - values[1]）
  delta_percent  相对变化：|initial - current| / initial * 100
  pct_of         占比：current / initial * 100
  count_over     计数：values 中严格大于 upper 的个数（inclusive=true 则 ≥）
  count_in_range 区间合格数：lower ≤ v ≤ upper 的个数
  ratio          占比：numerator / denominator * 100
  average        均值：values 的算术平均

统一用 Decimal 计算，避免二进制浮点误差；输出保留 4 位小数。
scale 为单位换算系数（默认 1），例如「成」传 0.1，把百分数换算成成数。
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

OPS = ("difference", "delta_percent", "pct_of", "count_over",
       "count_in_range", "ratio", "average")

Q4 = Decimal("0.0001")


def _d(x):
    if isinstance(x, Decimal):
        return x
    if isinstance(x, str):
        x = x.strip().replace("，", "").replace(",", "")
    return Decimal(str(x))


def _dec_list(values):
    if not isinstance(values, list) or not values:
        raise ValueError("values 不能为空")
    out = []
    for v in values:
        try:
            out.append(_d(v))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("values 含非数值：%r" % (v,))
    return out


def _finish(raw, scale, detail):
    x = _d(raw) * _d(scale)
    return {"ok": True, "result": float(x.quantize(Q4, rounding=ROUND_HALF_UP)),
            "detail": detail + ("" if _d(scale) == 1 else " ; × %s" % _d(scale))}


def _first(*xs):
    """取第一个非 None 的参数（字段别名归一，不做数值猜测）。"""
    for x in xs:
        if x is not None:
            return x
    return None


def run_calculation(op, values=None, initial=None, current=None,
                    lower=None, upper=None, numerator=None, denominator=None,
                    inclusive=False, scale=1, threshold=None, limit=None,
                    min_value=None, max_value=None):
    """执行一次确定性计算。

    返回 {"ok": True, "result": 数值, "detail": 计算式}；
    参数不合法返回 {"ok": False, "error": 说明}，绝不返回猜测值。

    字段别名只解决「同一个量被叫成不同名字」，不改变运算语义：
      upper      <- threshold / limit / max_value
      lower      <- min_value
      upper      <- current（仅 count_over：该运算里 current 只可能是阈值）
      initial/current <- numerator/denominator（仅 pct_of，语义等同 ratio）
    """
    try:
        if op not in OPS:
            return {"ok": False, "error": "未知运算 %r，可选：%s" % (op, ", ".join(OPS))}

        if op == "pct_of" and initial is None and current is None \
                and numerator is not None and denominator is not None:
            # 模型常把「占比」写成 numerator/denominator，语义与 ratio 相同
            n, d = _d(numerator), _d(denominator)
            if d == 0:
                return {"ok": False, "error": "denominator 为 0"}
            return _finish(n / d * 100, scale, "%s / %s * 100" % (n, d))

        if op in ("difference", "delta_percent", "pct_of"):
            if initial is None or current is None:
                if initial is None and isinstance(values, list) and len(values) >= 2:
                    initial, current = values[0], values[1]
                elif initial is None and current is not None:
                    other = _first(upper, threshold, limit, max_value, lower, min_value)
                    if other is not None:
                        # 模型把「现值 - 阈值」写成 current + upper
                        initial, current = current, other
            if initial is None or current is None:
                return {"ok": False, "error": "%s 需要 initial（基数）与 current（现值）" % op}
            a, b = _d(initial), _d(current)
            if op == "difference":
                return _finish(a - b, scale, "%s - %s" % (a, b))
            if a == 0:
                return {"ok": False, "error": "initial 为 0，无法计算百分比"}
            if op == "delta_percent":
                return _finish(abs(a - b) / a * 100, scale,
                               "|%s - %s| / %s * 100" % (a, b, a))
            return _finish(b / a * 100, scale, "%s / %s * 100" % (b, a))

        if op == "count_over":
            vals = _dec_list(values)
            u = _first(upper, threshold, limit, max_value, current)
            if u is None:
                return {"ok": False,
                        "error": "count_over 需要 upper（阈值），不要只传 current；values 为测量值列表"}
            u = _d(u)
            hit = [v for v in vals if (v >= u if inclusive else v > u)]
            return _finish(len(hit), scale, "共 %d 条，%s %s 的 %d 条" % (
                len(vals), "≥" if inclusive else ">", u, len(hit)))

        if op == "count_in_range":
            vals = _dec_list(values)
            lo = _first(lower, min_value)
            hi = _first(upper, threshold, limit, max_value)
            if lo is None or hi is None:
                return {"ok": False,
                        "error": ("count_in_range 需要 lower 与 upper；"
                                  "若题目是「超过上限的条数」，请改用 count_over（upper=阈值）")}
            lo, hi = _d(lo), _d(hi)
            if lo > hi:
                lo, hi = hi, lo
            hit = [v for v in vals if lo <= v <= hi]
            return _finish(len(hit), scale, "共 %d 条，落在 [%s, %s] 的 %d 条" % (
                len(vals), lo, hi, len(hit)))

        if op == "ratio":
            if numerator is None or denominator is None:
                return {"ok": False, "error": "ratio 需要 numerator 与 denominator"}
            n, d = _d(numerator), _d(denominator)
            if d == 0:
                return {"ok": False, "error": "denominator 为 0"}
            return _finish(n / d * 100, scale, "%s / %s * 100" % (n, d))

        vals = _dec_list(values)
        return _finish(sum(vals) / len(vals), scale, "sum(%d 条) / %d" % (len(vals), len(vals)))
    except (InvalidOperation, TypeError, ValueError, ZeroDivisionError) as e:
        return {"ok": False, "error": str(e)}


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_calculation",
        "description": ("执行确定性算术。只传题面中真实出现的数字，不要自己补数、不要心算。"
                        "一次只做一个运算；需要多个结果时分多次调用。"
                        "各运算必填参数：difference=initial,current；delta_percent=initial,current；"
                        "pct_of=initial,current；count_over=values,upper；"
                        "count_in_range=values,lower,upper；ratio=numerator,denominator；average=values。"),
        "parameters": {
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": list(OPS),
                       "description": ("difference=差; delta_percent=相对初始值的变化百分比; "
                                       "pct_of=占初始值的百分比; count_over=超过上限的条数(阈值放 upper); "
                                       "count_in_range=落在区间内的条数; ratio=占比; average=均值")},
                "values": {"type": "array", "items": {"type": "number"},
                           "description": "测量值列表，按题面顺序；count_over/average 必填"},
                "initial": {"type": "number", "description": "初始值 / 基数"},
                "current": {"type": "number", "description": "现值 / 实测值（不是阈值，阈值放 upper）"},
                "lower": {"type": "number", "description": "区间下限（含）"},
                "upper": {"type": "number", "description": "上限阈值；count_over 用它判断超标"},
                "numerator": {"type": "number", "description": "占比的分子"},
                "denominator": {"type": "number", "description": "占比的分母"},
                "inclusive": {"type": "boolean", "description": "count_over 是否包含等于，默认 false"},
                "scale": {"type": "number",
                          "description": "单位换算系数，默认 1；如把百分数换算成「成」传 0.1"},
            },
            "required": ["op"],
        },
    },
}
