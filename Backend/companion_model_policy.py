"""Companion model routing policy.

Text, UI-tree, screenshot, and reasoning tasks use the same DeepSeek vision model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .model_manager import model_manager

DEEPSEEK_FLASH_MODEL_ID = "deepseek-flash"
DEEPSEEK_VISION_MODEL_ID = "deepseek-flash"


@dataclass(frozen=True)
class CompanionModelRoute:
    model_id: str
    reason: str


def choose_companion_route(*, has_image: bool = False, high_difficulty: bool = False) -> CompanionModelRoute:
    if has_image:
        return CompanionModelRoute(DEEPSEEK_VISION_MODEL_ID, "vision")
    if high_difficulty:
        return CompanionModelRoute(DEEPSEEK_VISION_MODEL_ID, "high_difficulty")
    return CompanionModelRoute(DEEPSEEK_FLASH_MODEL_ID, "simple_ui_or_text")


def is_high_difficulty_task(task: str) -> bool:
    normalized = task.strip().lower()
    markers = ("复杂推理", "深度分析", "多方案比较", "high difficulty")
    return any(marker in normalized for marker in markers)


def _find_enabled(models: Iterable[dict[str, Any]], model_id: str) -> dict[str, Any] | None:
    return next(
        (dict(model) for model in models if model.get("id") == model_id and model.get("enabled") is not False),
        None,
    )


def get_companion_model_for(
    *,
    has_image: bool = False,
    high_difficulty: bool = False,
) -> dict[str, Any]:
    route = choose_companion_route(has_image=has_image, high_difficulty=high_difficulty)
    models = model_manager.get_models()
    selected = _find_enabled(models, route.model_id)
    if selected:
        return selected

    if has_image or high_difficulty:
        fallback = model_manager.get_model_for_capability("vision", preferred_task="companion_vision")
        if fallback:
            return dict(fallback)
    fallback = _find_enabled(models, DEEPSEEK_FLASH_MODEL_ID) or model_manager.get_active_model()
    if fallback:
        return dict(fallback)
    raise RuntimeError("No enabled Companion model is configured")
