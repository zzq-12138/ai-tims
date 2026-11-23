#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断用：把 det_trigger 换成年化 v1 副本后，复用已有缓存离线复算（0 元、0 API）。

用法（仓库根目录）：
  python3 scripts/ai_layer/_run_v1eq.py holdout3 h3_v1eq
  python3 scripts/ai_layer/_run_v1eq.py holdout4 h4_v1eq
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import det_trigger_v1eq as v1  # noqa: E402

sys.modules["det_trigger"] = v1

tag, out_tag = sys.argv[1], sys.argv[2]
sys.argv = ["det_trigger_eval.py",
            "--set", "scripts/ai_layer/data/%s_set.tsv" % tag,
            "--tag", tag, "--out-tag", out_tag]

import det_trigger_eval  # noqa: E402

det_trigger_eval.main()
