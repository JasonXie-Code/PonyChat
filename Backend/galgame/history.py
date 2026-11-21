"""
history.py
Galgame 历史消息归一化：补全缺失字段、精简旧轮场景、校正后端分数。
"""

from __future__ import annotations

import json
from typing import Optional

from ..config import logger
from .utils import try_fix_json

# ---------------------------------------------------------------------------
# 历史消息 schema 补全默认值表
# 每次 schema 新增字段时，只需在此处添加对应默认值，无需改 prompt 打补丁。
# 规则：仅对"缺失"字段补充默认值，已有字段不覆盖。
# ---------------------------------------------------------------------------
_GALGAME_HISTORY_DEFAULTS: dict = {
    # 顶层字段
    "character_pose": "自然站立",
    "player_pose": "面向角色",
    "character_position": "场景内",
    "player_position": "场景内",
    "character_gender": "",
    "player_gender": "",
    "character_race": "",
    "player_race": "",
    "character_outfit": "",
    "player_outfit": "",
    "mood": "",
    "relationship_stage": "",
    "score_delta_reason": "",
    "memory_tags": [],
}


def _normalize_galgame_assistant_history(
    messages: list,
    backend_score: Optional[int] = None,
) -> list:
    """
    归一化 Galgame 历史 assistant 消息，避免"历史缺字段样本"持续污染下一轮输出。

    - 按 _GALGAME_HISTORY_DEFAULTS 自动补全缺失字段（schema 演进时只需维护该表）
    - 若提供后端分数，则在发送前仅重写最新一条 assistant JSON 的 score.current
    """
    normalized: list = []
    schema_patched_count = 0
    score_patched_count = 0
    scene_truncated_count = 0

    normalized_backend_score: Optional[int] = None
    if backend_score is not None:
        try:
            normalized_backend_score = max(0, min(100, int(backend_score)))
        except Exception:
            normalized_backend_score = None

    # 预扫描：收集所有有效 assistant JSON 的索引
    all_assistant_json_indices: list[int] = []
    for scan_idx in range(len(messages)):
        scan_msg = messages[scan_idx]
        if not isinstance(scan_msg, dict) or scan_msg.get("role") != "assistant":
            continue
        scan_content = scan_msg.get("content")
        if not isinstance(scan_content, str):
            continue
        scan_raw = scan_content.strip()
        if not (scan_raw.startswith("{") and scan_raw.endswith("}")):
            continue
        try:
            json.loads(scan_raw, strict=False)
        except Exception:
            continue
        all_assistant_json_indices.append(scan_idx)

    latest_assistant_json_idx = all_assistant_json_indices[-1] if all_assistant_json_indices else None
    # 只保留最近 2 轮 AI 完整场景描写，更早的做占位符截断
    _KEEP_FULL_SCENE_TURNS = 2
    truncate_scene_indices = set(all_assistant_json_indices[:-_KEEP_FULL_SCENE_TURNS]) if len(all_assistant_json_indices) > _KEEP_FULL_SCENE_TURNS else set()

    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            normalized.append(msg)
            continue

        if msg.get("role") != "assistant":
            normalized.append(msg)
            continue

        content = msg.get("content")
        if not isinstance(content, str):
            normalized.append(msg)
            continue

        raw = content.strip()
        if not (raw.startswith("{") and raw.endswith("}")):
            normalized.append(msg)
            continue

        try:
            parsed = json.loads(raw, strict=False)
        except Exception:
            normalized.append(msg)
            continue

        if not isinstance(parsed, dict):
            normalized.append(msg)
            continue

        patched_payload = dict(parsed)
        changed = False

        # 旧轮精简：保留根级字段骨架（模型需要一致的 JSON 结构），
        # scene 只保留时间/地点/AI回复，大段叙事字段直接删除节省 token
        if idx in truncate_scene_indices:
            scene = patched_payload.get("scene")
            if isinstance(scene, dict):
                new_scene = {}
                for keep_f in ("time", "location", "response"):
                    if keep_f in scene:
                        new_scene[keep_f] = scene[keep_f]
                patched_payload["scene"] = new_scene
            patched_payload.pop("_strategy_analysis", None)
            patched_payload.pop("suggested_options", None)
            scene_truncated_count += 1
            changed = True
        else:
            patched_payload.pop("_strategy_analysis", None)
            patched_payload.pop("suggested_options", None)
            changed = True

        for field, default in _GALGAME_HISTORY_DEFAULTS.items():
            if field not in patched_payload:
                patched_payload[field] = default
                changed = True
                schema_patched_count += 1

        if normalized_backend_score is not None and idx == latest_assistant_json_idx:
            existing_score = patched_payload.get("score")
            target_score = dict(existing_score) if isinstance(existing_score, dict) else {}
            if target_score.get("current") != normalized_backend_score:
                target_score["current"] = normalized_backend_score
                patched_payload["score"] = target_score
                changed = True
                score_patched_count += 1

        if changed:
            patched_msg = dict(msg)
            patched_msg["content"] = json.dumps(patched_payload, ensure_ascii=False)
            normalized.append(patched_msg)
        else:
            normalized.append(msg)

    if schema_patched_count > 0:
        logger.info("🩹 [Galgame] 已按 schema 默认值表补全历史消息缺失字段: %s 处", schema_patched_count)
    if scene_truncated_count > 0:
        logger.info("✂️ [Galgame] 已精简 %s 轮旧历史（scene 仅保留 time/location/response），所有历史轮次均移除 suggested_options", scene_truncated_count)
    if score_patched_count > 0:
        logger.info("🎯 [Galgame] 发送前仅校正最新一条历史 score.current 到后端分数: %s 条", score_patched_count)

    return normalized
