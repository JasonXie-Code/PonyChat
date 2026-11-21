#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轻量校验：锁分 _apply_lock_side_effects 情绪互链 ±3 限幅与体征直连不受限。

运行（仓库内任意目录）：
  python Backend/scripts/verify_vitals_emotion_chain.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    path = _BACKEND / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    c = _load("gc", "galgame/constants.py")
    v = _load("gv", "galgame/vitals.py")
    DCV, DCM = c._DEFAULT_CHAR_VITALS, c._DEFAULT_CHAR_MOOD
    DOF = c._DEFAULT_ORGAN_FILL
    apply_fx = v._apply_lock_side_effects

    # 1) 极端情绪钉勇气：净压制应钳在 3，decay(0)=+5 → 勇气 +2
    vit = dict(DCV)
    m = dict(DCM)
    m.update(
        courage=0, fear=90, despair=90, submission=90, shyness=90, arousal=90
    )
    o = dict(DOF)
    apply_fx(vit, m, o)
    assert m["courage"] == 2, m["courage"]

    # 2) 中档恐惧压勇气
    vit2 = dict(DCV)
    m2 = dict(DCM)
    m2.update(courage=50, fear=72, despair=60)
    o2 = dict(DOF)
    apply_fx(vit2, m2, o2)
    assert m2["courage"] == 48, m2["courage"]

    # 3) 低血氧 → 恐惧 +5（体征直连，不受情绪互链 3 限幅）
    vit3 = dict(DCV)
    vit3["oxygen"] = 20
    m3 = dict(DCM)
    m3.update(fear=50)
    o3 = dict(DOF)
    apply_fx(vit3, m3, o3)
    assert m3["fear"] == 55, m3["fear"]

    print("verify_vitals_emotion_chain: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
