"""
galgame 子包：Galgame / 锁分模式解析、体征、重试与提示词。

外部推荐：`from Backend.galgame import ...`（或 `from ..galgame import ...`）。

子模块：
  generate   — 分步生成主逻辑（_sequential_galgame_generate）
  hints      — 锁分体征叙事提示构建（_build_lock_vitals_hints）
  payload    — 分步 payload 构建、精简 system（build_galgame_step_system_prompt）等
  seq_prompts — 分步提示词常量
  steps      — 各步骤执行函数（导演/元数据/选项）
"""

from .constants import (
    DEFAULT_SCENE_TIME,
    EVENT_FLAG_KEYS,
    LOCK_EVENT_FLAG_KEYS,
    _DEFAULT_CHAR_MOOD,
    _DEFAULT_CHAR_VITALS,
    _DEFAULT_ORGAN_FILL,
    _clamp_vitals_dict,
    _required_event_flag_keys,
)
from .handler import _handle_galgame_response
from .payload import build_galgame_step_system_prompt
from .history import (
    _GALGAME_HISTORY_DEFAULTS,
    _normalize_galgame_assistant_history,
)
from .retry import (
    _build_anti_duplicate_instruction,
    _build_retry_payload_with_instruction,
    _build_schema_instruction,
)
from .utils import (
    _compute_char_ngram_similarity,
    _extract_galgame_json_from_raw,
    _extract_json_object_text,
    _extract_scene_env_thoughts_from_raw,
    _extract_scene_response_from_raw,
    _normalize_non_tag_payload,
    _preview_text,
    _sanitize_scene_fields,
    generate_message_id,
    try_fix_json,
)
from .vitals import (
    _apply_lock_side_effects,
    _check_lock_death_conditions,
)

__all__ = [
    "EVENT_FLAG_KEYS",
    "LOCK_EVENT_FLAG_KEYS",
    "_DEFAULT_CHAR_MOOD",
    "_DEFAULT_CHAR_VITALS",
    "_DEFAULT_ORGAN_FILL",
    "_GALGAME_HISTORY_DEFAULTS",
    "_apply_lock_side_effects",
    "_build_anti_duplicate_instruction",
    "_build_retry_payload_with_instruction",
    "_build_schema_instruction",
    "_check_lock_death_conditions",
    "_clamp_vitals_dict",
    "_compute_char_ngram_similarity",
    "_extract_galgame_json_from_raw",
    "_extract_json_object_text",
    "_extract_scene_env_thoughts_from_raw",
    "_extract_scene_response_from_raw",
    "_handle_galgame_response",
    "_normalize_galgame_assistant_history",
    "_normalize_non_tag_payload",
    "_preview_text",
    "_required_event_flag_keys",
    "_sanitize_scene_fields",
    "build_galgame_step_system_prompt",
    "DEFAULT_SCENE_TIME",
    "generate_message_id",
    "try_fix_json",
]
