# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from character_source import ensure_system_characters
from schemas import CharacterProfile, WorkingState

RUNS_DIR = Path(__file__).resolve().parent / "runs"


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": True,
    }


def agent_tools_manifest() -> list[dict[str, Any]]:
    return [
        {
            "name": "load_system_characters",
            "description": "Load visible System-owned character profiles for local agent testing.",
            "inputSchema": _schema(
                {
                    "username": {"type": "string", "default": "System"},
                    "limit": {"type": "integer", "default": 10},
                    "refresh": {"type": "boolean", "default": False},
                    "remote_url": {"type": "string", "default": ""},
                }
            ),
        },
        {
            "name": "get_character_profile",
            "description": "Return one cached System character profile including persona text for Goose-written replies.",
            "inputSchema": _schema(
                {
                    "character_id": {"type": "string"},
                    "character_index": {"type": "integer", "default": 0},
                    "username": {"type": "string", "default": "System"},
                    "max_persona_chars": {"type": "integer", "default": 16000},
                }
            ),
        },
        {
            "name": "search_character_setting",
            "description": "Search one cached character setting and return only relevant raw profile/persona excerpts.",
            "inputSchema": _schema(
                {
                    "character_id": {"type": "string"},
                    "query": {"type": "string"},
                    "username": {"type": "string", "default": "System"},
                    "max_chunks": {"type": "integer", "default": 5},
                    "max_chunk_chars": {"type": "integer", "default": 900},
                },
                ["character_id", "query"],
            ),
        },
        {
            "name": "read_dialogue_context",
            "description": "Read raw dialogue context for the current turn from a local material context id.",
            "inputSchema": _schema(
                {
                    "context_id": {"type": "string"},
                    "query": {"type": "string"},
                    "recent_limit": {"type": "integer", "default": 8},
                    "max_matches": {"type": "integer", "default": 8},
                },
                ["context_id"],
            ),
        },
        {
            "name": "normal_chat_turn",
            "description": "Run one PonyChat normal-chat agent turn with tool-loop tracing.",
            "inputSchema": _schema(
                {
                    "character_id": {"type": "string"},
                    "character_index": {"type": "integer", "default": 0},
                    "messages": {"type": "array", "items": {"type": "object"}},
                    "latest_user_input": {"type": "string"},
                    "memory_fragments": {"type": "array", "items": {"type": "string"}},
                    "summaries": {"type": "object"},
                    "working_state": {"type": "object"},
                }
            ),
        },
        {
            "name": "search_memory_fragments",
            "description": "Search caller-provided memory fragments without short/mid-term memory.",
            "inputSchema": _schema(
                {
                    "query": {"type": "string"},
                    "memory_fragments": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "default": 5},
                },
                ["query"],
            ),
        },
        {
            "name": "read_summaries",
            "description": "Read day/week/month/year summaries supplied by the caller.",
            "inputSchema": _schema({"summaries": {"type": "object"}}),
        },
        {
            "name": "update_working_state",
            "description": "Infer the current user intent and temporary state from the latest input.",
            "inputSchema": _schema(
                {
                    "working_state": {"type": "object"},
                    "latest_user_input": {"type": "string"},
                },
                ["latest_user_input"],
            ),
        },
        {
            "name": "export_conversation_document",
            "description": "Create a Markdown document from the current conversation.",
            "inputSchema": _schema(
                {
                    "title": {"type": "string"},
                    "messages": {"type": "array", "items": {"type": "object"}},
                }
            ),
        },
        {
            "name": "describe_pose_image_prompt",
            "description": "Create an image prompt describing the character's current pose.",
            "inputSchema": _schema(
                {
                    "character": {"type": "object"},
                    "latest_user_input": {"type": "string"},
                    "pose_hint": {"type": "string"},
                }
            ),
        },
    ]


def load_system_characters_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    characters = ensure_system_characters(
        username=str(arguments.get("username") or "System"),
        limit=int(arguments.get("limit") or 0),
        refresh=bool(arguments.get("refresh")),
        remote_url=str(arguments.get("remote_url") or ""),
        token=str(arguments.get("token") or ""),
    )
    return {
        "count": len(characters),
        "characters": [
            {
                "id": item.id,
                "name": item.name,
                "is_official_source": item.is_official_source,
                "source": item.source,
                "persona_chars": len(item.persona_prompt),
            }
            for item in characters
        ],
    }


def select_character(
    character_id: str = "",
    character_index: int = 0,
    username: str = "System",
    refresh: bool = False,
    remote_url: str = "",
) -> CharacterProfile:
    characters = ensure_system_characters(
        username=username,
        refresh=refresh,
        remote_url=remote_url,
    )
    if not characters:
        raise RuntimeError(f"no visible characters for username={username}")
    if character_id:
        for item in characters:
            if item.id == character_id:
                return item
        raise KeyError(f"character_id not found: {character_id}")
    index = max(0, min(int(character_index or 0), len(characters) - 1))
    return characters[index]


def get_character_profile_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    character = select_character(
        character_id=str(arguments.get("character_id") or ""),
        character_index=int(arguments.get("character_index") or 0),
        username=str(arguments.get("username") or "System"),
        refresh=bool(arguments.get("refresh_roles")),
        remote_url=str(arguments.get("remote_url") or ""),
    )
    max_chars = int(arguments.get("max_persona_chars") or 16000)
    persona = character.persona_prompt or ""
    public_profile = {
        key: character.raw_data.get(key)
        for key in (
            "name",
            "preview",
            "profileGender",
            "profileSpecies",
            "profileAge",
            "profileMbti",
            "profilePersonality",
            "profileInterests",
            "profileIntro",
            "bio",
            "description",
            "tags",
            "exampleDialogue",
        )
        if character.raw_data.get(key)
    }
    return {
        "id": character.id,
        "name": character.name,
        "owner_username": character.owner_username,
        "is_official_source": character.is_official_source,
        "source": character.source,
        "profile": public_profile,
        "persona_prompt": persona[:max_chars],
        "persona_chars": len(persona),
        "persona_truncated": len(persona) > max_chars,
    }


def search_character_setting_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    character = select_character(
        character_id=str(arguments.get("character_id") or ""),
        username=str(arguments.get("username") or "System"),
        refresh=bool(arguments.get("refresh_roles")),
        remote_url=str(arguments.get("remote_url") or ""),
    )
    query = str(arguments.get("query") or "").strip()
    max_chunks = max(1, int(arguments.get("max_chunks") or 5))
    max_chunk_chars = max(200, int(arguments.get("max_chunk_chars") or 900))
    chunks = _character_setting_chunks(character, max_chunk_chars=max_chunk_chars)
    matches = _rank_text_items(query, chunks, max_items=max_chunks)
    return {
        "id": character.id,
        "name": character.name,
        "source": character.source,
        "query": query,
        "matches": matches,
        "total_chunks": len(chunks),
    }


def read_dialogue_context_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    context_id = str(arguments.get("context_id") or "").strip()
    material = _load_material_context(context_id)
    messages = material.get("messages") if isinstance(material.get("messages"), list) else []
    query = str(arguments.get("query") or "").strip()
    recent_limit = max(0, int(arguments.get("recent_limit") or 8))
    max_matches = max(0, int(arguments.get("max_matches") or 8))
    raw_items = []
    for index, message in enumerate(messages, 1):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "unknown")
        content = str(message.get("content") or message.get("text") or "")
        raw_items.append({"index": index, "role": role, "content": content})
    searchable = [
        {"index": item["index"], "role": item["role"], "text": f"{item['role']}: {item['content']}"}
        for item in raw_items
    ]
    matches = _rank_struct_items(query, searchable, max_items=max_matches)
    recent = raw_items[-recent_limit:] if recent_limit else []
    return {
        "context_id": context_id,
        "purpose": str(material.get("purpose") or ""),
        "latest_user_input": str(material.get("latest_user_input") or ""),
        "message_count": len(raw_items),
        "recent_messages": recent,
        "matches": matches,
    }


def search_memory_fragments_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip().lower()
    fragments = arguments.get("memory_fragments")
    if not isinstance(fragments, list):
        fragments = []
    terms = [item for item in query.replace("，", " ").replace("。", " ").split() if item]
    scored: list[tuple[int, str]] = []
    for fragment in fragments:
        text = str(fragment or "").strip()
        if not text:
            continue
        lowered = text.lower()
        score = sum(1 for term in terms if term in lowered)
        if query and query in lowered:
            score += 3
        if score > 0 or not terms:
            scored.append((score, text))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    limit = int(arguments.get("limit") or 5)
    return {"matches": [text for _score, text in scored[:limit]], "searched": len(fragments)}


def read_summaries_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    summaries = arguments.get("summaries")
    if not isinstance(summaries, dict):
        summaries = {}
    ordered = {}
    for key in ("day", "week", "month", "year"):
        value = str(summaries.get(key) or "").strip()
        if value:
            ordered[key] = value
    for key, value in summaries.items():
        if key not in ordered and str(value).strip():
            ordered[str(key)] = str(value).strip()
    return {"summaries": ordered, "count": len(ordered)}


def update_working_state_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    state = WorkingState.from_dict(arguments.get("working_state"))
    text = str(arguments.get("latest_user_input") or "").strip()
    lowered = text.lower()

    if any(word in text for word in ("文档", "整理成", "导出", "生成文件")):
        state.intent = "create_document"
        _append_once(state.goals, "export_conversation_document")
    elif any(word in text for word in ("图片", "画", "姿势", "照片", "image")):
        state.intent = "create_image_prompt"
        _append_once(state.goals, "describe_pose_image")
    else:
        state.intent = "ordinary_chat"

    if any(word in text for word in ("累", "烦", "难受", "压力", "崩", "委屈", "tired", "sad", "stress")):
        state.user_mood = "needs_support"
        _append_once(state.goals, "supportive_reply")
    elif any(word in lowered for word in ("thanks", "thank you")) or "谢谢" in text:
        state.user_mood = "grateful"
    else:
        state.user_mood = "neutral"

    if text:
        _append_once(state.recent_facts, f"latest_user_input: {text[:180]}")
    state.recent_facts = state.recent_facts[-8:]
    return state.to_dict()


def export_conversation_document_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    title = str(arguments.get("title") or "PonyChat Conversation").strip()
    messages = arguments.get("messages")
    if not isinstance(messages, list):
        messages = []
    lines = [f"# {title}", ""]
    for index, message in enumerate(messages, 1):
        role = str(message.get("role") or "unknown") if isinstance(message, dict) else "unknown"
        content = str(message.get("content") or message.get("text") or "") if isinstance(message, dict) else str(message)
        lines.append(f"## {index}. {role}")
        lines.append("")
        lines.append(content.strip())
        lines.append("")
    return {"document_markdown": "\n".join(lines).strip() + "\n", "message_count": len(messages)}


def describe_pose_image_prompt_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    character = arguments.get("character")
    if isinstance(character, CharacterProfile):
        profile = character
    elif isinstance(character, dict):
        profile = CharacterProfile.from_dict(character)
    else:
        profile = CharacterProfile(id="", name="角色")
    data = profile.raw_data
    species = str(data.get("profileSpecies") or data.get("species") or "character")
    personality = str(data.get("profilePersonality") or data.get("personality") or "")
    pose_hint = str(arguments.get("pose_hint") or arguments.get("latest_user_input") or "current relaxed pose")
    prompt = (
        f"{profile.name}, {species}, full-body character illustration, current pose: {pose_hint}. "
        f"Personality cues: {personality[:160]}. Keep the design faithful to the character profile, "
        "clear readable pose, no text overlay."
    )
    return {"image_prompt": prompt}


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _safe_context_id(context_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]", "_", context_id.strip())
    if not value:
        raise ValueError("context_id is required")
    return value[:120]


def _load_material_context(context_id: str) -> dict[str, Any]:
    safe_id = _safe_context_id(context_id)
    path = RUNS_DIR / f"{safe_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"material context not found: {safe_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"material context must be a JSON object: {safe_id}")
    return payload


def _terms(query: str) -> list[str]:
    raw = re.split(r"[\s,，。！？、；;:：/|]+", str(query or "").strip().lower())
    terms = [item for item in raw if item]
    if terms:
        return terms
    compact = str(query or "").strip().lower()
    return [compact] if compact else []


def _score_text(query: str, text: str) -> int:
    lowered = text.lower()
    score = 0
    for term in _terms(query):
        if term and term in lowered:
            score += 3 + min(5, lowered.count(term))
    if query and query.lower() in lowered:
        score += 8
    return score


def _rank_text_items(query: str, items: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    ranked = []
    for item in items:
        text = str(item.get("text") or "")
        score = _score_text(query, text)
        if score > 0 or not query:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: (-pair[0], int(pair[1].get("index") or 0)))
    return [{**item, "score": score} for score, item in ranked[:max_items]]


def _rank_struct_items(query: str, items: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    ranked = []
    for item in items:
        text = str(item.get("text") or "")
        score = _score_text(query, text)
        if score > 0 or not query:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: (-pair[0], int(pair[1].get("index") or 0)))
    return [
        {"index": item.get("index"), "role": item.get("role"), "content": item.get("text"), "score": score}
        for score, item in ranked[:max_items]
    ]


def _character_setting_chunks(character: CharacterProfile, max_chunk_chars: int = 900) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    fields = {
        "name": character.raw_data.get("name") or character.name,
        "preview": character.raw_data.get("preview"),
        "profileGender": character.raw_data.get("profileGender"),
        "profileSpecies": character.raw_data.get("profileSpecies"),
        "profilePersonality": character.raw_data.get("profilePersonality"),
        "profileInterests": character.raw_data.get("profileInterests"),
        "profileIntro": character.raw_data.get("profileIntro"),
        "bio": character.raw_data.get("bio"),
        "description": character.raw_data.get("description"),
        "exampleDialogue": character.raw_data.get("exampleDialogue"),
        "tags": character.raw_data.get("tags"),
    }
    index = 1
    for key, value in fields.items():
        if value:
            chunks.append({"index": index, "section": key, "text": f"{key}: {value}"[:max_chunk_chars]})
            index += 1
    persona = character.persona_prompt or ""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", persona) if part.strip()]
    for paragraph in paragraphs:
        while paragraph:
            chunks.append({"index": index, "section": "persona_prompt", "text": paragraph[:max_chunk_chars]})
            paragraph = paragraph[max_chunk_chars:]
            index += 1
    return chunks
