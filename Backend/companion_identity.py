"""Identity scoping shared by Companion chat and phone-agent routes."""
from __future__ import annotations

from typing import Any

PERSONALITY_STYLE_INSTRUCTIONS = {
    "canonical": "",
    "gentle": "表达风格微调：比角色原设更温柔、耐心，但不得改变身份、经历、关系和既有记忆。",
    "lively": "表达风格微调：比角色原设更活泼、有感染力，但不得改变身份、经历、关系和既有记忆。",
    "calm": "表达风格微调：比角色原设更沉稳、简洁，但不得改变身份、经历、关系和既有记忆。",
    "playful": "表达风格微调：比角色原设更俏皮、轻松，但不得改变身份、经历、关系和既有记忆。",
}


def normalize_personality_style(style: str) -> str:
    clean = str(style or "").strip().lower()
    return clean if clean in PERSONALITY_STYLE_INSTRUCTIONS else "canonical"


def apply_personality_style(prompt: str, style: str) -> str:
    instruction = PERSONALITY_STYLE_INSTRUCTIONS[normalize_personality_style(style)]
    if not instruction:
        return prompt
    return f"{prompt}\n\n{instruction}" if prompt else instruction


def identity_session_key(
    username: str,
    character_id: str,
    conversation_id: str = "",
) -> str:
    """Scope transient context to a role and, when supplied, its source conversation."""
    base = f"{username}:{character_id}"
    scope = str(conversation_id or "").strip()
    return f"{base}:{scope}" if scope else base


def character_identity_summary(character_id: str, data: dict[str, Any], fallback_name: str = "") -> dict[str, Any]:
    personality = str(data.get("profilePersonality") or data.get("personality") or "").strip()
    intro = str(data.get("profileIntro") or data.get("bio") or data.get("preview") or "").strip()
    return {
        "id": character_id,
        "name": str(data.get("name") or fallback_name or "未命名角色").strip(),
        "avatar": str(data.get("avatar") or "").strip(),
        "personality": personality,
        "intro": intro,
        "mbti": str(data.get("profileMbti") or "").strip(),
    }
