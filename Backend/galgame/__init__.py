"""Game and score-lock state, validation, and Agent delivery helpers."""

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
from .history import (
    _GALGAME_HISTORY_DEFAULTS,
    _normalize_galgame_assistant_history,
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
    "DEFAULT_SCENE_TIME",
    "generate_message_id",
    "try_fix_json",
]
