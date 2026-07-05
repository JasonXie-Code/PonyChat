# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


@dataclass
class CharacterProfile:
    id: str
    name: str
    owner_username: str = "System"
    is_official_source: bool = False
    raw_data: dict[str, Any] = field(default_factory=dict)
    prompt: str = ""
    persona_prompt: str = ""
    source: str = "local-db"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CharacterProfile":
        raw_data = _dict(payload.get("raw_data") or payload.get("data"))
        name = str(payload.get("name") or raw_data.get("name") or payload.get("id") or "").strip()
        return cls(
            id=str(payload.get("id") or "").strip(),
            name=name,
            owner_username=str(payload.get("owner_username") or payload.get("username") or "System"),
            is_official_source=bool(payload.get("is_official_source")),
            raw_data=raw_data,
            prompt=str(payload.get("prompt") or ""),
            persona_prompt=str(payload.get("persona_prompt") or ""),
            source=str(payload.get("source") or "unknown"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatMessage:
    role: str
    content: str
    speaker_name: str = ""
    speaker_character_id: str = ""
    timestamp: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatMessage":
        return cls(
            role=str(payload.get("role") or ""),
            content=str(payload.get("content") or payload.get("text") or ""),
            speaker_name=str(payload.get("speaker_name") or ""),
            speaker_character_id=str(payload.get("speaker_character_id") or ""),
            timestamp=payload.get("timestamp") if isinstance(payload.get("timestamp"), int) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkingState:
    intent: str = "ordinary_chat"
    user_mood: str = "neutral"
    scene: str = "normal_chat"
    goals: list[str] = field(default_factory=list)
    recent_facts: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WorkingState":
        payload = _dict(payload)
        return cls(
            intent=str(payload.get("intent") or "ordinary_chat"),
            user_mood=str(payload.get("user_mood") or "neutral"),
            scene=str(payload.get("scene") or "normal_chat"),
            goals=[str(item) for item in _list(payload.get("goals"))],
            recent_facts=[str(item) for item in _list(payload.get("recent_facts"))],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentDecision:
    step: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    observation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentReply:
    character_id: str
    character_name: str
    mode: str
    reply_units: list[dict[str, str]]
    decisions: list[AgentDecision] = field(default_factory=list)
    working_state: WorkingState = field(default_factory=WorkingState)
    artifacts: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, include_trace: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "character_id": self.character_id,
            "character_name": self.character_name,
            "mode": self.mode,
            "reply_units": self.reply_units,
            "working_state": self.working_state.to_dict(),
            "artifacts": self.artifacts,
            "warnings": self.warnings,
        }
        if include_trace:
            payload["decisions"] = [item.to_dict() for item in self.decisions]
        return payload
