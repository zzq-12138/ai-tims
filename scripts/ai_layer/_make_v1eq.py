#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断用：从冻结的 det-trigger-v2 生成「等价 v1」副本，用于同集对照。

只做两处逆向还原，不触碰 det_trigger.py 本身（冻结哈希不变）：
  1) 删掉二段复算的「反向基数」枚举；
  2) 删掉「候选集不完备 → uncomputable」分支，覆盖恢复为 v1 行为。

产物：scripts/ai_layer/det_trigger_v1eq.py（临时诊断模块，不进论文产物）。
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / "det_trigger.py").read_text(encoding="utf-8")

assert 'VERSION = "det-trigger-v2"' in src
src = src.replace('VERSION = "det-trigger-v2"',
                  'VERSION = "det-trigger-v1-offline"', 1)

start = src.index("            # 反向基数：题面数当基数、中间结果当现值\n")
end_marker = ('            b.add("pct_of", _calc("pct_of", initial=c, current=a),\n'
              '                  "%s/%s*100" % (a, c), 2)\n')
end = src.index(end_marker, start) + len(end_marker)
src = src[:start] + src[end:]

branch = ('    elif incomplete:\n'
          '        verdict, reason = "uncomputable", "candidates_incomplete"\n')
assert branch in src
src = src.replace(branch, "", 1)

assert '"picked": [] if incomplete else pick(cands, question)}' in src
src = src.replace('"picked": [] if incomplete else pick(cands, question)}',
                  '"picked": pick(cands, question)}', 1)

(HERE / "det_trigger_v1eq.py").write_text(src, encoding="utf-8")
print("wrote det_trigger_v1eq.py")
