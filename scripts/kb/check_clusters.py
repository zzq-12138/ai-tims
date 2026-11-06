#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成组规模自检（构建前置校验）。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from data import pm, aoi, coat, lam, etch, reflow, mes, spi, wave, xray

MODS = [pm, aoi, coat, lam, etch, reflow, mes, spi, wave, xray]

for m in MODS:
    d = m.DEVICE
    sim = [c for c in d["clusters"] if c["type"] == "same_symptom_diff_cause"]
    sic = [c for c in d["clusters"] if c["type"] == "same_cause_diff_symptom"]
    print(d["name"], "entries=%d" % len(d["entries"]), "SIM=%d" % len(sim), "SIC=%d" % len(sic),
          sorted(len(c["members"]) for c in sim), sorted(len(c["members"]) for c in sic))
