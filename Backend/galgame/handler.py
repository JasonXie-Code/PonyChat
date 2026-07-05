"""
handler.py
Galgame / 锁分模式 AI 响应解析与状态持久化层。

从 routes/chat.py 提取，包含 _handle_galgame_response 核心处理器。
其余逻辑见同包内 constants / vitals / utils / retry / history。

正文后处理原则：仅对 think/thinking 等标签块做剥离（否则会污染 JSON 与展示）；
其它格式问题由提示词约束，与 chat_modules.galgame_payload._strip_think_tag_blocks 一致。
"""

from __future__ import annotations

import copy
import json
import random
import re
import time
from typing import Any, Dict, Optional

from .constants import (
    _DEFAULT_CHAR_MOOD,
    _DEFAULT_CHAR_VITALS,
    _DEFAULT_ORGAN_FILL,
    _clamp_vitals_dict,
    _required_event_flag_keys,
)
from .utils import (
    _preview_text,
    _sanitize_scene_fields,
    generate_message_id,
    try_fix_json,
)
from .vitals import (
    _apply_lock_side_effects,
    _check_lock_death_conditions,
)

from ..config import logger
from ..context_usage import CONTEXT_LIMIT_TOKENS as BACKEND_CONTEXT_LIMIT_TOKENS
from ..utils import (
    ChatRequest,
    load_galgame_state_async,
    save_galgame_state_async,
)
from ..websocket import galgame_locker, manager
from .memory import schedule_char_memory_update_after_turn


async def _handle_galgame_response(
    request: ChatRequest,
    raw_content: str,
    messages: list,
    x_client_id: Optional[str] = None,
    request_tokens: int = 0,
    generation_duration_ms: Optional[int] = None,
    generated_text_fields: Optional[frozenset] = None,
):
    """解析 AI 返回的 JSON，更新分数和时间，保存状态并广播同步

    generated_text_fields: 导演本轮实际生成的 scene 文本字段集合（env/body_state/thoughts/response）。
    传入时校验严格依据该集合；未传入时退回到保守默认（仅要求 env/response）。
    """
    galgame_saved = True
    try:
        # 1. 提取并保存标签内的思维链文本（用于后续去重）
        think_content_match = re.search(r'<(?:think|thinking)>(.*?)</(?:think|thinking)>', raw_content, flags=re.DOTALL)
        think_text = think_content_match.group(1).strip() if think_content_match else ""

        # 2. 移除所有思维链标签及其内容
        clean_content = re.sub(r'<(?:think|thinking)>.*?</(?:think|thinking)>', '', raw_content, flags=re.DOTALL).strip()

        # 3. DeepSeek-R1 特殊处理 - 如果标签外还有重复的思维链文本，一并移除
        if think_text and len(think_text) > 50 and think_text in clean_content:
            clean_content = clean_content.replace(think_text, '', 1).strip()
            logger.info(f"🔧 [Galgame] 检测到重复思维链文本 ({len(think_text)} 字符)，已清除")

        # 4. 正则提取 JSON 块
        json_match = re.search(r'\{(?:.*)\}', clean_content, re.DOTALL)
        if not clean_content:
            logger.warning(
                "❌ [Galgame-Parse] 清洗后内容为空，触发重试 (raw_len=%s, preview=%s)",
                len(raw_content or ""),
                _preview_text(raw_content),
            )
            return {
                "status": "retry",
                "error": "清洗后内容为空，未提取到可解析正文",
                "raw": raw_content,
                "retry_code": "empty_after_clean",
                "retry_preview": _preview_text(raw_content),
            }

        if not json_match:
            logger.warning(
                "❌ [Galgame-Parse] 未提取到 JSON 对象，触发重试 (clean_len=%s, preview=%s)",
                len(clean_content),
                _preview_text(clean_content),
            )
            return {
                "status": "retry",
                "error": "未提取到 JSON 对象",
                "raw": raw_content,
                "retry_code": "no_json_object",
                "retry_preview": _preview_text(clean_content),
            }

        json_str = json_match.group(0) if json_match else clean_content

        # 5. 执行强力修复
        fixed_json = try_fix_json(json_str)

        try:
            game_data = json.loads(fixed_json, strict=False)
            if not isinstance(game_data, dict):
                logger.warning(
                    "❌ [Galgame-Parse] JSON 顶层不是对象，触发重试 (type=%s, preview=%s)",
                    type(game_data).__name__,
                    _preview_text(fixed_json),
                )
                return {
                    "status": "retry",
                    "error": "JSON 顶层不是对象",
                    "raw": raw_content,
                    "retry_code": "json_not_object",
                    "retry_preview": _preview_text(fixed_json),
                }

            # 严格字段完整性校验
            required_top_fields = [
                "score", "scene", "relationship_stage", "mood",
                "character_pose", "player_pose",
                "character_position", "player_position",
                "character_gender", "player_gender",
                "character_race", "player_race", "character_outfit", "player_outfit",
                "memory_tags", "event_flags", "score_delta_reason", "suggested_options"
            ]
            missing_paths = []

            for field in required_top_fields:
                if field not in game_data:
                    missing_paths.append(field)

            score_obj = game_data.get("score")
            if not isinstance(score_obj, dict):
                missing_paths.append("score(object)")
                score_obj = {}
            else:
                for k in ("current", "change", "status"):
                    if k not in score_obj:
                        missing_paths.append(f"score.{k}")

            scene_obj = game_data.get("scene")
            if not isinstance(scene_obj, dict):
                missing_paths.append("scene(object)")
                scene_obj = {}
            else:
                required_scene_fields = [
                    "time", "location", "env", "thoughts",
                    "body_state", "third_party_dialogue", "response"
                ]
                for k in required_scene_fields:
                    if k not in scene_obj:
                        missing_paths.append(f"scene.{k}")

            options_obj = game_data.get("suggested_options")
            if not isinstance(options_obj, list) or len(options_obj) == 0:
                missing_paths.append("suggested_options(list>=1)")
                options_obj = []
            else:
                _normalized = []
                for opt in options_obj:
                    if isinstance(opt, str):
                        s = opt.strip()
                        if s in ("_options_perspective", "") or s.startswith("⚠"):
                            _normalized.append({"_options_perspective": s or "视角提醒"})
                        else:
                            _normalized.append({"label": s, "type": "dialogue", "tone": "neutral"})
                    elif isinstance(opt, dict):
                        if "_options_perspective" in opt and "label" not in opt:
                            _normalized.append(opt)
                        else:
                            if "type" not in opt or str(opt.get("type", "")).strip().lower() not in ("dialogue", "action", "speech", "text"):
                                opt["type"] = "dialogue"
                            if "tone" not in opt or not str(opt.get("tone", "")).strip():
                                opt["tone"] = "neutral"
                            _normalized.append(opt)
                    else:
                        continue
                options_obj = _normalized
                game_data["suggested_options"] = options_obj

                for i, opt in enumerate(options_obj):
                    if not isinstance(opt, dict):
                        missing_paths.append(f"suggested_options[{i}](object)")
                        continue
                    if "_options_perspective" in opt and "label" not in opt:
                        continue
                    for k in ("label", "type", "tone"):
                        if k not in opt:
                            missing_paths.append(f"suggested_options[{i}].{k}")

            event_flags_obj = game_data.get("event_flags")
            required_event_flags = _required_event_flag_keys(getattr(request, "mode", "galgame"))
            if not isinstance(event_flags_obj, dict):
                missing_paths.append("event_flags(object)")
            else:
                for k in required_event_flags:
                    if k not in event_flags_obj:
                        missing_paths.append(f"event_flags.{k}")

            # 锁分模式：严格校验 char_vitals / char_mood / organ_fill
            # womb/testicles/vaginal_plug 按性别补全；器具四键小模型常漏，不强制首轮必出，由下方补全
            _GENDER_EXCLUSIVE_ORGAN_KEYS = {
                "womb", "testicles", "vaginal_plug",
                "urethral_plug", "anal_plug", "mouth_plug",
            }
            if getattr(request, "mode", "galgame") == "galgame_lock":
                for _block_name, _defaults in [
                    ("char_vitals", _DEFAULT_CHAR_VITALS),
                    ("char_mood", _DEFAULT_CHAR_MOOD),
                    ("organ_fill", _DEFAULT_ORGAN_FILL),
                ]:
                    _block = game_data.get(_block_name)
                    if not isinstance(_block, dict):
                        missing_paths.append(f"{_block_name}(object)")
                    else:
                        _skip = _GENDER_EXCLUSIVE_ORGAN_KEYS if _block_name == "organ_fill" else set()
                        for _k in _defaults:
                            if _k in _skip:
                                continue
                            if _k not in _block:
                                missing_paths.append(f"{_block_name}.{_k}")

                # 性别器官字段：自动补全（小模型经常漏掉，不触发重试）
                _of_block = game_data.get("organ_fill")
                if isinstance(_of_block, dict):
                    _state_for_gender = None
                    try:
                        _state_for_gender = await load_galgame_state_async(
                            request.username, request.character_id, game_type="galgame_lock"
                        )
                    except Exception:
                        pass
                    _known_gender = ""
                    if _state_for_gender:
                        _known_gender = str(_state_for_gender.get("character_gender", "") or "").strip().lower()
                    if not _known_gender:
                        _known_gender = str(game_data.get("character_gender", "") or "").strip().lower()
                    _prev_organ = (_state_for_gender or {}).get("organ_fill") or {}
                    if _known_gender in ("female", "女", "女性", "雌", "雌性"):
                        if "womb" not in _of_block:
                            _of_block["womb"] = _prev_organ.get("womb", _DEFAULT_ORGAN_FILL.get("womb", 0))
                    elif _known_gender in ("male", "男", "男性", "雄", "雄性"):
                        if "testicles" not in _of_block:
                            _of_block["testicles"] = _prev_organ.get("testicles", _DEFAULT_ORGAN_FILL.get("testicles", 0))
                    # 器具四键：缺失时沿用存档，避免第8步 JSON 因漏键重试
                    for _pk in ("urethral_plug", "anal_plug", "mouth_plug", "vaginal_plug"):
                        if _pk not in _of_block:
                            _of_block[_pk] = _prev_organ.get(_pk, _DEFAULT_ORGAN_FILL.get(_pk, 0))
                    # 仅雌性保留阴道塞；雄性 / 性别未判明 恒为 0
                    if _known_gender not in ("female", "女", "女性", "雌", "雌性"):
                        _of_block["vaginal_plug"] = 0

            if missing_paths:
                missing_paths = sorted(set(missing_paths))
                logger.warning(
                    "⚠️ [Galgame-Parse] 严格字段校验失败，缺失字段: %s, preview=%s",
                    ", ".join(missing_paths),
                    _preview_text(fixed_json),
                )
                return {
                    "status": "retry",
                    "error": f"字段不完整，缺失: {', '.join(missing_paths)}",
                    "raw": raw_content,
                    "retry_code": "json_incomplete_schema",
                    "retry_preview": _preview_text(fixed_json),
                }

            # memory_tags：小模型常输出 [] 或全空串，触发无意义的第8步重试；与 organ_fill 类似在此归一化
            _mt_raw = game_data.get("memory_tags")
            _mt_list = _mt_raw if isinstance(_mt_raw, list) else []
            _mt_clean = [str(t).strip() for t in _mt_list if str(t or "").strip()]
            if not _mt_clean:
                _mt_clean = ["日常互动"]
            game_data["memory_tags"] = _mt_clean

            # 非空校验
            non_empty_paths = []
            if str(game_data.get("relationship_stage", "")).strip() == "":
                non_empty_paths.append("relationship_stage")
            if str(game_data.get("mood", "")).strip() == "":
                non_empty_paths.append("mood")
            if str(game_data.get("character_pose", "")).strip() == "":
                non_empty_paths.append("character_pose")
            if str(game_data.get("player_pose", "")).strip() == "":
                non_empty_paths.append("player_pose")
            if str(game_data.get("character_position", "")).strip() == "":
                non_empty_paths.append("character_position")
            if str(game_data.get("player_position", "")).strip() == "":
                non_empty_paths.append("player_position")
            if str(game_data.get("character_gender", "")).strip() == "":
                non_empty_paths.append("character_gender")
            if str(game_data.get("player_gender", "")).strip() == "":
                non_empty_paths.append("player_gender")
            if str(game_data.get("character_race", "")).strip() == "":
                non_empty_paths.append("character_race")
            if str(game_data.get("player_race", "")).strip() == "":
                non_empty_paths.append("player_race")
            if str(game_data.get("character_outfit", "")).strip() == "":
                non_empty_paths.append("character_outfit")
            if str(game_data.get("player_outfit", "")).strip() == "":
                non_empty_paths.append("player_outfit")
            if str(game_data.get("score_delta_reason", "")).strip() == "":
                non_empty_paths.append("score_delta_reason")

            _scene_text_candidates = ("env", "body_state", "thoughts", "response")
            if generated_text_fields is not None:
                scene_non_empty_fields = ["time", "location"] + [
                    k for k in _scene_text_candidates if k in generated_text_fields
                ]
            else:
                scene_non_empty_fields = ["time", "location", "env", "response"]
            for k in scene_non_empty_fields:
                if str(scene_obj.get(k, "")).strip() == "":
                    non_empty_paths.append(f"scene.{k}")

            if not isinstance(game_data.get("memory_tags"), list) or len(game_data.get("memory_tags") or []) == 0:
                non_empty_paths.append("memory_tags(list>=1)")
            else:
                for i, tag in enumerate(game_data.get("memory_tags") or []):
                    if str(tag or "").strip() == "":
                        non_empty_paths.append(f"memory_tags[{i}]")

            for i, opt in enumerate(options_obj):
                if "_options_perspective" in opt and "label" not in opt:
                    continue
                label = str(opt.get("label", "")).strip()
                opt_type = str(opt.get("type", "")).strip().lower()
                tone = str(opt.get("tone", "")).strip()
                if not label:
                    non_empty_paths.append(f"suggested_options[{i}].label")
                if opt_type not in ("dialogue", "action", "speech", "text"):
                    non_empty_paths.append(f"suggested_options[{i}].type")
                if not tone:
                    non_empty_paths.append(f"suggested_options[{i}].tone")

            # 姿势字段限制为 10 字以内（去空白后计数）
            compact_character_pose_len = len(re.sub(r"\s+", "", str(game_data.get("character_pose", "") or "").strip()))
            compact_player_pose_len = len(re.sub(r"\s+", "", str(game_data.get("player_pose", "") or "").strip()))
            if compact_character_pose_len > 10:
                non_empty_paths.append("character_pose(len<=10)")
            if compact_player_pose_len > 10:
                non_empty_paths.append("player_pose(len<=10)")
            compact_character_position_len = len(re.sub(r"\s+", "", str(game_data.get("character_position", "") or "").strip()))
            compact_player_position_len = len(re.sub(r"\s+", "", str(game_data.get("player_position", "") or "").strip()))
            if compact_character_position_len > 16:
                non_empty_paths.append("character_position(len<=16)")
            if compact_player_position_len > 16:
                non_empty_paths.append("player_position(len<=16)")

            if non_empty_paths:
                non_empty_paths = sorted(set(non_empty_paths))
                logger.warning(
                    "⚠️ [Galgame-Parse] 严格字段非空校验失败: %s, preview=%s",
                    ", ".join(non_empty_paths),
                    _preview_text(fixed_json),
                )
                return {
                    "status": "retry",
                    "error": f"字段为空或非法: {', '.join(non_empty_paths)}",
                    "raw": raw_content,
                    "retry_code": "json_incomplete_schema",
                    "retry_preview": _preview_text(fixed_json),
                }

        except Exception as json_err:
            logger.warning(
                "❌ [Galgame-Parse] JSON 解析失败，需要重新生成: %s (raw_len=%s, clean_len=%s, preview=%s)",
                json_err,
                len(raw_content or ""),
                len(clean_content or ""),
                _preview_text(clean_content or raw_content),
            )
            return {
                "status": "retry",
                "error": f"JSON 解析失败: {str(json_err)}",
                "raw": raw_content,
                "retry_code": "json_decode_error",
                "retry_preview": _preview_text(clean_content or raw_content),
            }

        scene = game_data.get("scene", {})

        # 3.5 后处理：清洗场景文本（移除非法Markdown + 合并换行为单段）
        _sanitize_scene_fields(scene)

        # 3.6 后处理：验证 score.status 为合法字符串值
        _score_for_validate = game_data.get("score")
        if isinstance(_score_for_validate, dict):
            _raw_status = _score_for_validate.get("status")
            if _raw_status not in ("playing", "win", "lose"):
                _inferred = "playing"
                try:
                    _sc = int(_score_for_validate.get("current", 50))
                    if _sc >= 100:
                        _inferred = "win"
                    elif _sc <= 0:
                        _inferred = "lose"
                except (TypeError, ValueError):
                    pass
                logger.warning("⚠️ [Galgame] score.status 值无效 (%s)，已修正为 %s", _raw_status, _inferred)
                _score_for_validate["status"] = _inferred

        # 4. 选项规范化与清洗
        raw_options = game_data.get("suggested_options") or []
        normalized_options = []
        if isinstance(raw_options, list):
            for opt in raw_options:
                if not isinstance(opt, dict):
                    continue
                if "_options_perspective" in opt:
                    opt.pop("_options_perspective", None)
                    if "label" not in opt:
                        continue
                label = str(opt.get("label", "")).strip()
                if not label:
                    continue
                label = label.replace('\\"', '"')
                label = re.sub(r"'([^']*)'", r'"\1"', label)
                opt["label"] = label
                ai_type = str(opt.get("type", "")).lower().strip()
                if ai_type == "action":
                    opt["type"] = "action"
                elif ai_type in ["dialogue", "speech", "text"]:
                    opt["type"] = "dialogue"
                else:
                    opt["type"] = "dialogue"
                    logger.debug(f"⚠️ 选项类型未指定或无效 ('{ai_type}')，使用默认值 dialogue")
                normalized_options.append(opt)

        # 5. 智能随机抽取
        selected_options = []
        if len(normalized_options) >= 5:
            original_dialogue = [opt for opt in normalized_options if opt.get("type") == "dialogue"]
            original_action = [opt for opt in normalized_options if opt.get("type") == "action"]
            target_count = random.randint(2, 4)
            if target_count == 2:
                if original_dialogue and original_action:
                    selected_options = [random.choice(original_dialogue), random.choice(original_action)]
                else:
                    selected_options = random.sample(normalized_options, min(2, len(normalized_options)))
            elif target_count == 3:
                if len(original_dialogue) >= 2 and len(original_action) >= 2:
                    if random.random() < 0.6:
                        selected_options = random.sample(original_dialogue, 2) + [random.choice(original_action)]
                    else:
                        selected_options = [random.choice(original_dialogue)] + random.sample(original_action, 2)
                elif len(original_dialogue) >= 2 and len(original_action) >= 1:
                    selected_options = random.sample(original_dialogue, 2) + [random.choice(original_action)]
                elif len(original_dialogue) >= 1 and len(original_action) >= 2:
                    selected_options = [random.choice(original_dialogue)] + random.sample(original_action, 2)
                else:
                    selected_options = random.sample(normalized_options, min(3, len(normalized_options)))
            elif target_count == 4:
                if len(original_dialogue) >= 2 and len(original_action) >= 2:
                    selected_options = random.sample(original_dialogue, 2) + random.sample(original_action, 2)
                else:
                    selected_options = random.sample(normalized_options, min(4, len(normalized_options)))
            random.shuffle(selected_options)
        else:
            selected_options = normalized_options

        if not selected_options:
            return {
                "status": "retry",
                "error": "suggested_options 为空或不可用",
                "raw": raw_content,
                "retry_code": "json_incomplete_schema",
                "retry_preview": _preview_text(fixed_json),
            }

        # 获取状态
        game_type = "galgame_lock" if getattr(request, "mode", "galgame") == "galgame_lock" else "galgame"
        state = await load_galgame_state_async(request.username, request.character_id, game_type=game_type)
        current_score = int(state.get("score", 40))

        # 锁分模式：加载上一轮生命体征（首轮使用默认值）
        is_lock_mode_early = getattr(request, "mode", "galgame") == "galgame_lock"
        if is_lock_mode_early:
            char_vitals = {**_DEFAULT_CHAR_VITALS, **(state.get("char_vitals") or {})}
            char_vitals = _clamp_vitals_dict(char_vitals, _DEFAULT_CHAR_VITALS)
            char_mood = {**_DEFAULT_CHAR_MOOD, **(state.get("char_mood") or {})}
            char_mood = _clamp_vitals_dict(char_mood, _DEFAULT_CHAR_MOOD)
            # 首轮开场情绪扰动：generate.py 已将扰动注入 hints，此处同步叠加到基准值
            _init_mood_delta = state.get("_init_mood_delta") or {}
            if _init_mood_delta and not state.get("char_mood"):
                for _mk, _dv in _init_mood_delta.items():
                    if _mk in char_mood:
                        char_mood[_mk] = max(0, min(100, char_mood[_mk] + _dv))
                logger.debug("🎲 [Galgame] 应用开场情绪扰动: %s", _init_mood_delta)
            organ_fill = {**_DEFAULT_ORGAN_FILL, **(state.get("organ_fill") or {})}
            organ_fill = _clamp_vitals_dict(organ_fill, _DEFAULT_ORGAN_FILL)
        else:
            char_vitals: dict = {}
            char_mood: dict = {}
            organ_fill: dict = {}

        relationship_stage = str(game_data.get("relationship_stage", "") or "").strip()
        mood = str(game_data.get("mood", "") or "").strip()

        memory_tags = game_data.get("memory_tags", [])
        if not isinstance(memory_tags, list):
            memory_tags = []
        memory_tags = [str(tag).strip() for tag in memory_tags if str(tag).strip()]

        event_flags = game_data.get("event_flags", {})
        if not isinstance(event_flags, dict):
            event_flags = {}

        score_delta_reason = str(game_data.get("score_delta_reason", "") or "").strip()
        actual_character_pose = str(game_data.get("character_pose", "") or "").strip()
        actual_player_pose = str(game_data.get("player_pose", "") or "").strip()
        actual_character_position = str(game_data.get("character_position", "") or "").strip()
        actual_player_position = str(game_data.get("player_position", "") or "").strip()
        actual_character_action = str(game_data.get("character_action", "") or "").strip()
        actual_player_action = str(game_data.get("player_action", "") or "").strip()
        actual_character_gender = str(game_data.get("character_gender", "") or "").strip()
        actual_player_gender = str(game_data.get("player_gender", "") or "").strip()
        actual_character_race = str(game_data.get("character_race", "") or "").strip()
        actual_player_race = str(game_data.get("player_race", "") or "").strip()
        actual_character_outfit = str(game_data.get("character_outfit", "") or "").strip()
        actual_player_outfit = str(game_data.get("player_outfit", "") or "").strip()

        new_env = (scene.get("env") or "").strip()
        new_thoughts = (scene.get("thoughts") or "").strip()
        new_body_state = (scene.get("body_state") or "").strip()
        new_response = str(scene.get("response") or "").strip()

        # 分数计算与状态判定
        score_data = game_data.get("score", {})
        model_current_val = None
        if isinstance(score_data, dict):
            change = int(score_data.get("change", 0))
            try:
                if score_data.get("current") is not None:
                    model_current_val = int(score_data.get("current"))
            except (TypeError, ValueError):
                model_current_val = None
        elif isinstance(score_data, (int, float)):
            change = int(score_data)
        else:
            change = 0

        # 用 request._galgame_ai_turns_count 判断是否首轮，避免隐藏初始消息被过滤后 user_count=1 的误判
        _prior_ai_turns = getattr(request, '_galgame_ai_turns_count', None)
        if _prior_ai_turns is not None:
            is_initial = _prior_ai_turns == 0
        else:
            user_msg_count = len([m for m in messages if m["role"] == "user"])
            is_initial = user_msg_count <= 1

        if is_initial:
            change = 0

        change = min(max(change, -40), 2)
        is_lock_mode = getattr(request, "mode", "galgame") == "galgame_lock"
        model_status = None
        current_val = model_current_val
        if isinstance(game_data.get("score"), dict):
            score_obj_for_sync = game_data.get("score") or {}
            model_status = score_obj_for_sync.get("status")
            model_current_raw = score_obj_for_sync.get("current")
            try:
                if model_current_raw is not None:
                    current_val = int(model_current_raw)
            except (TypeError, ValueError):
                pass
        is_death_from_model = bool(is_lock_mode and model_status == "lose" and (current_val is not None and current_val <= 0))

        if not is_initial:
            if model_current_val is not None and model_current_val > current_score:
                sync_target_score = min(100, model_current_val)
                sync_delta = min(2, sync_target_score - current_score)
                if sync_delta > 0:
                    if change < sync_delta:
                        logger.info(
                            "🔄 [Galgame] 应用分数上行同步: db=%s model_current=%s 原change=%s -> 同步change=%s",
                            current_score, model_current_val, change, sync_delta
                        )
                    change = max(change, sync_delta)

            if model_current_val is not None and model_current_val < current_score:
                min_survival_score = 0 if not is_lock_mode else 1
                if is_death_from_model:
                    min_survival_score = 0
                sync_target_score = max(min_survival_score, model_current_val)
                sync_delta = max(-40, sync_target_score - current_score)
                if sync_delta < 0:
                    if change > sync_delta:
                        logger.info(
                            "🔄 [Galgame] 应用分数下行同步: db=%s model_current=%s 原change=%s -> 同步change=%s",
                            current_score, model_current_val, change, sync_delta
                        )
                    change = min(change, sync_delta)

        new_score = max(0, min(100, current_score + change))
        if is_lock_mode:
            score_data = game_data.get("score") or {}
            model_status = score_data.get("status")
            model_current = score_data.get("current")
            try:
                current_val = int(model_current) if model_current is not None else None
            except (TypeError, ValueError):
                current_val = None
            is_death = model_status == "lose" and (new_score <= 0 or (current_val is not None and current_val <= 0))
            if is_death:
                new_score = 0
                new_status = "lose"
            else:
                new_score = max(1, new_score)
                new_status = "win" if new_score >= 100 else "playing"
        else:
            new_status = "win" if new_score >= 100 else ("lose" if new_score <= 0 else "playing")

        # 锁分模式：合并模型输出的体征增量更新，执行副作用与服务端死亡兜底检测
        if is_lock_mode:
            # 合并模型提供的增量更新（只接受已知键，范围 clamp 到 [0,100]）
            _model_vitals = game_data.get("char_vitals") or {}
            _model_mood = game_data.get("char_mood") or {}
            _model_organ = game_data.get("organ_fill") or {}
            # 合并前保存胃部旧值，用于计算进食→直肠联动
            _prev_stomach = organ_fill.get("stomach", 0)
            if isinstance(_model_vitals, dict):
                for _k, _v in _model_vitals.items():
                    if _k in _DEFAULT_CHAR_VITALS:
                        try:
                            char_vitals[_k] = max(0, min(100, int(_v)))
                        except (TypeError, ValueError):
                            pass
            if isinstance(_model_mood, dict):
                for _k, _v in _model_mood.items():
                    if _k in _DEFAULT_CHAR_MOOD:
                        try:
                            char_mood[_k] = max(0, min(100, int(_v)))
                        except (TypeError, ValueError):
                            pass
            if isinstance(_model_organ, dict):
                for _k, _v in _model_organ.items():
                    if _k in _DEFAULT_ORGAN_FILL:
                        try:
                            organ_fill[_k] = max(0, min(100, int(_v)))
                        except (TypeError, ValueError):
                            pass

            # 胃部增加 → 直肠联动（进食消化传导：胃增量的 1/3 四舍五入，仅正向有效）
            _stomach_delta = organ_fill.get("stomach", 0) - _prev_stomach
            if _stomach_delta > 0:
                _rectum_add = round(_stomach_delta / 3)
                if _rectum_add > 0:
                    organ_fill["rectum"] = min(100, organ_fill.get("rectum", 0) + _rectum_add)

            # 应用联动副作用（lung_fill → oxygen，pain → consciousness）
            _apply_lock_side_effects(char_vitals, char_mood, organ_fill)

            # 服务端兜底：对所有死亡条件做二次强制校验，不依赖模型自觉
            _vitals_death, _vitals_reason = _check_lock_death_conditions(char_vitals, char_mood, organ_fill)
            if _vitals_death and new_status != "lose":
                logger.info("💀 [锁分死亡] 服务端体征检测触发死亡覆盖: %s", _vitals_reason)
                new_score = 0
                new_status = "lose"

        has_numeric_delta = bool(re.search(r'([+-]?\d+)\s*分|[+-]\d+', score_delta_reason))
        if not has_numeric_delta:
            if change > 0:
                score_delta_reason = f"{score_delta_reason}（本轮+{change}分）"
            elif change < 0:
                score_delta_reason = f"{score_delta_reason}（本轮{change}分）"
            else:
                score_delta_reason = f"{score_delta_reason}（本轮+0分）"

        # 首轮：统一覆写分数变化理由（与默认起始分 40 一致，避免模型编造）
        if is_initial and getattr(request, "mode", "") in ("galgame", "galgame_lock"):
            score_delta_reason = "游戏开场，分值为默认40"

        normalized_game_data = copy.deepcopy(game_data)
        normalized_game_data["score"] = {
            "current": int(new_score),
            "change": int(change),
            "status": new_status,
        }
        normalized_game_data["score_delta_reason"] = score_delta_reason
        normalized_game_data["suggested_options"] = selected_options
        # 游戏/锁分模式不输出思维链，即使模型输出了也要移除
        # 清理 scene 中无意义的 third_party_dialogue（null/"null"/"无" 等 → 空字符串）
        _norm_scene = normalized_game_data.get("scene")
        if isinstance(_norm_scene, dict):
            _tp_val = _norm_scene.get("third_party_dialogue")
            _tp_stripped = str(_tp_val).strip("「」（）() ").strip().lower() if _tp_val is not None else ""
            if _tp_val is None or _tp_stripped in ("null", "none", "无", "暂无", "nan", ""):
                _norm_scene["third_party_dialogue"] = ""
        normalized_raw_content = json.dumps(normalized_game_data, ensure_ascii=False)

        # 构造对话 HTML
        scene = game_data.get("scene", {})
        response_text = str(scene.get('response', '') or '')
        _raw_tp = scene.get('third_party_dialogue')
        if _raw_tp is None or str(_raw_tp).strip("「」（）() ").strip().lower() in ("", "null", "none", "无", "暂无", "nan"):
            third_party = ""
        else:
            third_party = str(_raw_tp).strip()

        response_text = re.sub(r"'([^']*)'", r'"\1"', response_text)
        response_text = re.sub(r'"([^"]*)"', lambda m: '\u201c' + m.group(1) + '\u201d', response_text)
        third_party = re.sub(r'"([^"]*)"', lambda m: '\u201c' + m.group(1) + '\u201d', third_party)

        third_party_block = f'<div class="gal-scene-third-party">{third_party}</div>' if third_party else ''
        scene_time = str(scene.get("time", "") or "").strip()
        scene_location = str(scene.get("location", "") or "").strip()
        tags_block = ""
        if scene_time or scene_location:
            tags = []
            if scene_time:
                tags.append(f'<span class="gal-time-tag"><ion-icon name="time-outline"></ion-icon>{scene_time}</span>')
            if scene_location:
                tags.append(f'<span class="gal-loc-tag"><ion-icon name="location-outline"></ion-icon>{scene_location}</span>')
            tags_block = f'<div class="gal-tags-container">{"".join(tags)}</div>'
        display_html = f"""
        <div class="galgame-scene-container">
            <div class="gal-scene-env">{scene.get('env', '')}</div>
            <div class="gal-scene-thought">{scene.get('thoughts', '')}</div>
            {third_party_block}
            <div class="gal-scene-speech">{response_text}</div>
            {tags_block}
        </div>
        """.strip()

        async with galgame_locker.acquire(request.username, request.character_id):
            fresh_state = await load_galgame_state_async(request.username, request.character_id, game_type=game_type)
            if "messages" not in fresh_state:
                fresh_state["messages"] = []

            current_ts = int(time.time() * 1000)

            last_user_content = ""
            last_user_image = None
            last_user_msg_id = None
            last_msg_req = None
            if request.messages:
                last_msg_req = request.messages[-1]
                if last_msg_req.role == "user":
                    last_user_content = last_msg_req.content
                    last_user_image = last_msg_req.image_url
                    last_user_msg_id = getattr(last_msg_req, 'message_id', None)

            if isinstance(last_user_content, str) and "（记住：请以此刻的角色身份" in last_user_content:
                last_user_content = last_user_content.split("（记住：请以此刻的角色身份")[0].strip()

            should_add_user = True
            if last_user_msg_id:
                existing_user = next((m for m in fresh_state["messages"] if m.get("message_id") == last_user_msg_id), None)
                if existing_user:
                    should_add_user = False
                    logger.info(f"🔒 [Galgame校验] 用户消息已存在: {last_user_msg_id}")

            if should_add_user:
                user_seq_num = len(fresh_state["messages"])
                user_prev_id = fresh_state["messages"][-1].get("message_id") if fresh_state["messages"] else None
                user_msg_id = last_user_msg_id or generate_message_id()
                last_msg_is_hidden = bool(getattr(last_msg_req, 'isHidden', False)) if last_msg_req else False
                is_hidden = getattr(request, 'isHidden', False) or last_msg_is_hidden or (not last_user_content and not last_user_image)

                fresh_state["messages"].append({
                    "role": "user",
                    "content": last_user_content if last_user_content else "...",
                    "image_url": last_user_image,
                    "timestamp": current_ts,
                    "isHidden": is_hidden,
                    "message_id": user_msg_id,
                    "sequence_number": user_seq_num,
                    "previous_message_id": user_prev_id
                })
                logger.info(f"🔒 [Galgame校验] 添加用户消息: ID={user_msg_id}, 序号={user_seq_num}, isHidden={is_hidden}")

            ai_msg_id = generate_message_id()
            ai_seq_num = len(fresh_state["messages"])
            ai_prev_id = fresh_state["messages"][-1].get("message_id") if fresh_state["messages"] else None

            ai_msg = {
                "role": "assistant",
                "content": display_html,
                "rawContent": normalized_raw_content,
                "galgameOptions": selected_options,
                "timestamp": current_ts + 1,
                "message_id": ai_msg_id,
                "sequence_number": ai_seq_num,
                "previous_message_id": ai_prev_id,
            }
            if generation_duration_ms is not None:
                ai_msg["generation_duration_ms"] = int(generation_duration_ms)
            fresh_state["messages"].append(ai_msg)
            logger.info(f"🔒 [Galgame校验] 添加AI消息: ID={ai_msg_id}, 序号={ai_seq_num}")

            fresh_state["version"] = fresh_state.get("version", 0) + 1

            _save_payload = {
                "score": new_score,
                "status": new_status,
                "time": scene.get("time", state.get("time", "午后")),
                "relationship_stage": relationship_stage,
                "mood": mood,
                "memory_tags": memory_tags,
                "event_flags": event_flags,
                "score_delta_reason": score_delta_reason,
                "contextSummary": fresh_state.get("contextSummary") or state.get("contextSummary") or "",
                "contextSummaryTime": fresh_state.get("contextSummaryTime") or state.get("contextSummaryTime"),
                "contextSummaryCutoffMessageId": fresh_state.get("contextSummaryCutoffMessageId") or state.get("contextSummaryCutoffMessageId"),
                "contextSummaryCutoffTimestamp": fresh_state.get("contextSummaryCutoffTimestamp") or state.get("contextSummaryCutoffTimestamp"),
                "contextSummaryCutoffSequence": fresh_state.get("contextSummaryCutoffSequence") or state.get("contextSummaryCutoffSequence"),
                "char_memory": fresh_state.get("char_memory")
                if isinstance(fresh_state.get("char_memory"), dict)
                else (state.get("char_memory") if isinstance(state.get("char_memory"), dict) else {"entries": []}),
                "repetition_profile": fresh_state.get("repetition_profile")
                if isinstance(fresh_state.get("repetition_profile"), dict)
                else (state.get("repetition_profile") if isinstance(state.get("repetition_profile"), dict) else {}),
                "messages": fresh_state["messages"],
                "version": fresh_state["version"],
                "last_update": __import__('datetime').datetime.now().isoformat()
            }
            # 锁分模式：持久化三个体征对象及角色性别（每轮覆盖写入，供下一轮作为上下文注入）
            if is_lock_mode:
                _save_payload["char_vitals"] = char_vitals
                _save_payload["char_mood"] = char_mood
                _save_payload["organ_fill"] = organ_fill
                if actual_character_gender:
                    _save_payload["character_gender"] = actual_character_gender
            galgame_saved = await save_galgame_state_async(
                request.username, request.character_id, _save_payload, game_type=game_type
            )

            if galgame_saved:
                try:
                    schedule_char_memory_update_after_turn(
                        username=request.username,
                        character_id=request.character_id,
                        game_type=game_type,
                    )
                except Exception as _mem_sched_err:
                    logger.debug("[CharMemory] 调度异步记忆更新失败（忽略）: %s", _mem_sched_err)

            await manager.broadcast_sync(request.username, "galgame_update", source=x_client_id or "server", character_id=request.character_id)

            # 通知后台/锁屏的系统通知（与普通对话路径保持一致）
            if galgame_saved:
                try:
                    from ..delivery_outbox import enqueue_chat_complete
                    _notif_preview = response_text.strip()[:500]
                    _mode = getattr(request, "mode", "normal") or "normal"
                    _notif_scene = None
                    if str(_mode).startswith("galgame"):

                        def _notif_trim(val: Any, n: int = 500) -> str:
                            s = str(val or "").strip()
                            return s[:n] if s else ""

                        _scene_map: Dict[str, Any] = {}
                        rt = _notif_trim(response_text)
                        if rt:
                            _scene_map["response"] = rt
                        for _k, _src in (
                            ("body_state", scene.get("body_state")),
                            ("thoughts", scene.get("thoughts")),
                            ("third_party_dialogue", third_party),
                            ("time", scene.get("time")),
                            ("location", scene.get("location")),
                            ("env", scene.get("env")),
                        ):
                            _v = _notif_trim(_src)
                            if not _v:
                                continue
                            if _k == "third_party_dialogue" and _v.lower() in ("null", "none"):
                                continue
                            _scene_map[_k] = _v
                        _notif_scene = _scene_map or None
                    _sdr = str(score_delta_reason or "").strip()
                    await enqueue_chat_complete(
                        request.username,
                        request.character_id,
                        fresh_state.get("conversation_id", f"gal_{request.character_id}"),
                        ai_msg_id,
                        _notif_preview,
                        mode=_mode,
                        scene=_notif_scene,
                        score_delta_reason=_sdr if _sdr else None,
                        completed_at_ms=int(ai_msg.get("timestamp") or (current_ts + 1)),
                    )
                except Exception as _notif_err:
                    logger.debug("[outbox] galgame chat_complete 跳过: %s", _notif_err)

        return {
            "status": "success",
            "assistant_message_id": ai_msg_id,
            "db_saved": galgame_saved,
            "usage": {
                "total_tokens": request_tokens,
                "limit_tokens": BACKEND_CONTEXT_LIMIT_TOKENS,
                "source": "chat_response"
            },
            "message": {
                "role": "assistant",
                "content": display_html,
                "rawContent": normalized_raw_content,
                "galgameOptions": selected_options,
                "timestamp": int(time.time() * 1000),
                **({"generation_duration_ms": int(generation_duration_ms)} if generation_duration_ms is not None else {}),
            },
            "data": {
                "scene": scene,
                "score": {"current": new_score, "change": change, "status": new_status},
                "suggested_options": selected_options,
                "relationship_stage": relationship_stage,
                "mood": mood,
                "character_pose": actual_character_pose,
                "player_pose": actual_player_pose,
                "character_position": actual_character_position,
                "player_position": actual_player_position,
                "character_action": actual_character_action,
                "player_action": actual_player_action,
                "character_gender": actual_character_gender,
                "player_gender": actual_player_gender,
                "character_race": actual_character_race,
                "player_race": actual_player_race,
                "character_outfit": actual_character_outfit,
                "player_outfit": actual_player_outfit,
                "memory_tags": memory_tags,
                "event_flags": event_flags,
                "score_delta_reason": score_delta_reason,
                # 锁分模式专属体征字段（非锁分模式为 None）
                "char_vitals": char_vitals if is_lock_mode else None,
                "char_mood": char_mood if is_lock_mode else None,
                "organ_fill": organ_fill if is_lock_mode else None,
            },
            "score": new_score,
            "change": change
        }
    except Exception as e:
        import traceback
        err_detail = f"{type(e).__name__}: {e}"
        logger.error(f"Galgame 响应解析失败: {err_detail}\n{traceback.format_exc()}")
        return {"status": "error", "error": err_detail, "raw": raw_content}
