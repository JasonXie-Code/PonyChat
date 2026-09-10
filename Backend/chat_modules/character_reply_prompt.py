"""Shared default style rules for user-visible character replies."""
from __future__ import annotations

from typing import Any

from .Prompts import DEFAULT_CHARACTER_REPLY_STYLE_PROMPT




CHARACTER_REPLY_TASKS = frozenset({
    "normal",
    "galgame",
    "galgame_lock",
    "companion",
    "normal_opening_greeting",
})


def with_character_reply_style_prompt(prompt: str) -> str:
    """Append the shared instruction once to a textual system prompt."""
    text = str(prompt or "")
    if "【角色回复默认表达规则】" in text:
        return text
    return text.rstrip() + "\n\n" + DEFAULT_CHARACTER_REPLY_STYLE_PROMPT


def apply_character_reply_style_prompt(payload: dict[str, Any], task: str) -> None:
    """Inject the shared instruction only for calls that create visible character text."""
    if not isinstance(payload, dict) or task not in CHARACTER_REPLY_TASKS:
        return
    for field, roles in (("messages", {"system"}), ("input", {"system", "developer"})):
        items = payload.get(field)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("role") not in roles:
                continue
            if isinstance(item.get("content"), str):
                item["content"] = with_character_reply_style_prompt(item["content"])
                return
        items.insert(0, {"role": "system", "content": DEFAULT_CHARACTER_REPLY_STYLE_PROMPT})
        return
