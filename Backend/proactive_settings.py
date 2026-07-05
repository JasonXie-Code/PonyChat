from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import logger
from .db import get_database
from .db.settings_dao import SettingsDAO


@dataclass(frozen=True)
class ProactiveSettings:
    enabled: bool = True
    frequency: str = "normal"
    memory_enabled: bool = True


def normalize_proactive_frequency(value: Any) -> str:
    freq = str(value or "normal").strip().lower()
    return freq if freq in {"low", "normal", "high"} else "normal"


async def load_proactive_settings(username: str) -> ProactiveSettings:
    username = (username or "").strip()
    if not username:
        return ProactiveSettings()
    try:
        settings = await SettingsDAO(get_database()).load_settings(username) or {}
    except Exception as exc:
        logger.debug("[ProactiveSettings] load failed username=%s: %s", username, exc)
        return ProactiveSettings()
    if not isinstance(settings, dict):
        return ProactiveSettings()
    enabled = settings.get("proactive_messages_enabled")
    memory_enabled = settings.get("memory_enabled")
    effective_memory_enabled = memory_enabled is not False
    return ProactiveSettings(
        enabled=(enabled is not False) and effective_memory_enabled,
        frequency=normalize_proactive_frequency(settings.get("proactive_frequency")),
        memory_enabled=effective_memory_enabled,
    )


def apply_frequency_to_delay_seconds(delay_seconds: int, frequency: str) -> int:
    delay = max(1, int(delay_seconds or 0))
    freq = normalize_proactive_frequency(frequency)
    if freq == "low":
        return delay * 2
    if freq == "high":
        return max(1, delay // 2)
    return delay
