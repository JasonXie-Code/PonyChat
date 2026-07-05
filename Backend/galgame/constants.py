"""
constants.py
Galgame / 锁分模式共用常量、默认值及范围限制工具。
"""

from __future__ import annotations

from typing import Tuple

# ---------------------------------------------------------------------------
# 事件标志常量
# ---------------------------------------------------------------------------

EVENT_FLAG_KEYS: Tuple[str, ...] = (
    "first_handhold",
    "confessed",
    "first_hug",
    "first_kiss",
    "physical_intimacy",
    "exclusive_confirmed",
    "trust_broken",
    "relationship_public",
)

LOCK_EVENT_FLAG_KEYS: Tuple[str, ...] = (
    "captivity_established",
    "coercion_explicit",
    "violence_inflicted",
    "torture_inflicted",
    "bloodshed_occurred",
    "injury_persistent",
    "corpse_present",
    "escape_attempted",
)


def _required_event_flag_keys(mode: str) -> Tuple[str, ...]:
    if mode == "galgame_lock":
        return EVENT_FLAG_KEYS + LOCK_EVENT_FLAG_KEYS
    return EVENT_FLAG_KEYS


# ---------------------------------------------------------------------------
# 场景占位（无持久化 state["time"] 时仅作默认文案；实际以 state 或模型 scene.time 为准）
# ---------------------------------------------------------------------------

DEFAULT_SCENE_TIME = "午后"


# ---------------------------------------------------------------------------
# 锁分模式专属体征默认值
# ---------------------------------------------------------------------------

_DEFAULT_CHAR_VITALS: dict = {
    "consciousness": 100,   # 意识清晰度（100=完全清醒，0=昏迷）
    "stamina": 100,         # 体力/生命余力（0=彻底虚脱）
    "blood_loss": 0,        # 累计失血量（0=无，100=全身血量流失）
    "oxygen": 100,          # 血氧/气道通畅（0=完全窒息）
    "body_temp": 50,        # 体温偏移（50=正常，0=冻死，100=高热死）
    "thirst": 30,           # 口渴/脱水（0=不渴，100=严重脱水；叙事与级联档位见 galgame_hints / _apply_lock_side_effects）
    "infection": 0,         # 伤口/全身感染程度（0=无，100=败血症）
    "pain": 0,              # 疼痛强度
    "restraint": 0,         # 身体束缚（物理状态，0=完全自由，100=完全固定；不参与情绪衰减）
}

_DEFAULT_CHAR_MOOD: dict = {
    # 所有情绪统一量表：50=正常/中性基准，100=该情绪最高涨，0=该情绪的反面极端
    "arousal":     50,  # 性兴奋（0=性冷淡/厌恶，50=正常，100=极度兴奋）
    "pleasure":    50,  # 愉悦感（0=极度不悦/痛苦，50=正常，100=极度愉悦）
    "fear":        50,  # 恐惧（0=无畏/鲁莽，50=正常警觉，100=极度恐惧瘫痪）
    "anger":       50,  # 愤怒（0=完全压抑/麻木，50=正常平静，100=失控狂怒）
    "sadness":     50,  # 悲伤（0=强行乐观/麻木，50=情绪平稳，100=极度悲痛崩溃）
    "submission":  50,  # 顺从（0=极度抗拒，50=正常独立，100=完全顺从）
    "despair":     50,  # 绝望（0=盲目乐观/否认，50=现实平静，100=彻底绝望）
    "courage":     50,  # 勇气（0=极度胆怯，50=正常，100=无所畏惧）
    "shyness":     50,  # 害羞（0=完全无耻/豁达，50=正常，100=极度害羞无法开口）
    "curiosity":   50,  # 好奇心（0=完全漠然，50=正常，100=极度渴望探索）
    "nervousness": 50,  # 紧张（0=极度迟钝/麻木，50=正常警觉，100=极度焦虑崩溃边缘）
}

_DEFAULT_ORGAN_FILL: dict = {
    "stomach": 30,          # 胃部充盈（0=空腹，100=严重撑胀）
    "bladder": 10,          # 膀胱充盈（0=空，100=急迫难忍）
    "womb": 0,              # 子宫容量（0=空，100=完全充满）【雌性专属】
    "testicles": 0,         # 精巢胀满（0=正常，100=极度胀痛）【雄性专属】
    "rectum": 0,            # 直肠充盈/便意（0=无感，100=便意急迫难忍；自然+1/轮）
    "lung_fill": 0,         # 肺部异物/液体充盈（0=正常，100=肺积液/溺水）
    # 体内器具佩戴度（0=未佩戴/已取出，100=完全佩戴或完全阻塞）；由导演步维护，防叙事遗忘
    "urethral_plug": 0,     # 尿道塞
    "anal_plug": 0,       # 肛塞
    "mouth_plug": 0,      # 口塞（含口球等）
    "vaginal_plug": 0,    # 阴道塞【雌性专属；雄性/性别未判明 恒为 0】
}


def _clamp_vitals_dict(d: dict, defaults: dict) -> dict:
    """将体征字典中所有已知键的值限制在 [0, 100] 范围内。未知键保持不变。"""
    out = dict(d)
    for k in defaults:
        if k in out:
            try:
                out[k] = max(0, min(100, int(out[k])))
            except (TypeError, ValueError):
                out[k] = defaults[k]
    return out
