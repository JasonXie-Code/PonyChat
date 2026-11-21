"""Explicit, user-editable preferences scoped to one character and chat mode."""
from .Prompts import PERSONAL_PREFERENCES_TEXT

MODES = {"normal", "galgame", "galgame_lock"}
MAX_PREFERENCE_LENGTH = 4000
SEXUAL_LANGUAGE_STYLES = {"euphemistic", "default", "direct"}


def sexual_language_style(settings: dict, character_id: str, mode: str) -> str:
    """Read the typed account / character / mode style, defaulting to default."""
    if not isinstance(settings, dict) or not character_id or mode not in MODES:
        return "default"
    value = settings.get("sexual_language_style", {}).get(character_id, {}).get(mode)
    return value if value in SEXUAL_LANGUAGE_STYLES else "default"


def sexual_language_style_prompt(settings: dict, character_id: str, mode: str) -> str:
    if not isinstance(settings, dict) or not character_id or mode not in MODES:
        return ""
    stored = settings.get("sexual_language_style", {}).get(character_id, {}).get(mode)
    if stored not in SEXUAL_LANGUAGE_STYLES:
        return ""
    return PERSONAL_PREFERENCES_TEXT['config_header'] + "\nsexual_language_style: " + stored


def personal_preferences_prompt(settings: dict, character_id: str, mode: str) -> str:
    """完整的偏好注入块（配置行 + 已保存偏好）。调用方各自决定放在哪个提示词槽位。"""
    if not isinstance(settings, dict) or not character_id or mode not in MODES:
        return ""
    style_prompt = sexual_language_style_prompt(settings, character_id, mode)
    characters = settings.get("personal_preferences")
    modes = characters.get(character_id) if isinstance(characters, dict) else None
    value = modes.get(mode) if isinstance(modes, dict) else None
    if not isinstance(value, str) or not value.strip():
        return style_prompt
    blocks = [PERSONAL_PREFERENCES_TEXT['config_header'],
              PERSONAL_PREFERENCES_TEXT['saved_header'] + "\n" + value.strip()[:MAX_PREFERENCE_LENGTH]]
    if style_prompt:
        blocks.append(style_prompt.split("\n", 1)[1])
    return "\n".join(blocks)


async def load_personal_preferences_prompt(username: str, character_id: str, mode: str) -> str:
    """Read the exact saved scope, independently of memory and profile sharing."""
    if not username or not character_id or mode not in MODES:
        return ""
    from ..db.database import get_database
    from ..db.settings_dao import SettingsDAO

    settings = await SettingsDAO(get_database()).load_settings(username)
    return personal_preferences_prompt(settings, character_id, mode)
