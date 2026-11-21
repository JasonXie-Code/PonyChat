"""
Normal-chat temporary speaker helpers.

The main conversation still belongs to request.character_id for persistence and
UI placement.  When the user explicitly @-selects another owned character, that
character becomes the reply owner for this turn: generation should use the
guest's own persona and private normal-chat state, while the main conversation
is exposed only as the temporary group scene.
"""

from __future__ import annotations
from .Prompts import SPEAKER_SELECTION_TEXT

from Backend.chat_modules.Prompts import USER_SPEAKER_INTENT_SYSTEM

import json
import hashlib
import re
import asyncio
from typing import Any

import aiosqlite
from fastapi import HTTPException

from ..config import logger
from ..db import get_database
from ..utils import ChatMessage, ChatRequest
from ..utils import save_chat_debug_log
from .character import load_character_from_db
from .state import is_summary_placeholder_message


_MAX_RECENT_USER_TURNS_FOR_AT = 8
_MAX_RECENT_ASSISTANT_TURNS_FOR_USER_SPEAKER_INTENT = 8
_GUEST_PRIVATE_RECENT_MAX_MESSAGES = 10
_GUEST_SCENE_MAX_CHARS = 3600
_GUEST_GROUP_MEMORY_MAX_PARTICIPANTS = 6
_RECENT_GUEST_GROUP_MEMORY_MAX_CHARS = 3600
call_llm_payload = None
_AT_MENTION_TOKEN_RE = re.compile(r"[@＠]([^\s@＠,，。！？!?;；:：、（）()\[\]【】》」』\"'“”‘’…]+)")


def _clip_guest_group_memory_text(value: Any, limit: int = 900) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        text = text[:limit].rstrip() + "……"
    return text


def _guest_group_memory_priority(item: dict[str, Any]) -> int:
    content = str(item.get("content") or "")
    primary_markers = (
        "我曾在",
        SPEAKER_SELECTION_TEXT['primary_markers_1'],
        "当时可见现场原文摘要",
        "高优先级事实",
    )
    group_markers = ("临时群聊", "群聊现场", "被用户 @", "被 @", "主聊天")
    if any(marker in content for marker in primary_markers):
        rank = 0
    elif any(marker in content for marker in group_markers):
        rank = 1
    else:
        rank = 2
    return rank


def format_recent_guest_group_memory_block(entries: list[dict[str, Any]]) -> str:
    """Format recent temporary group memories as the current character's own recall."""
    clean_entries: list[dict[str, str]] = []
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        content = _clip_guest_group_memory_text(item.get("content"), 1100)
        if not content:
            continue
        clean_entries.append(
            {
                "created_at": _clip_guest_group_memory_text(item.get("created_at"), 40),
                "content": content,
            }
        )
    if not clean_entries:
        return ""
    clean_entries.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    clean_entries.sort(key=_guest_group_memory_priority)
    lines = [
        SPEAKER_SELECTION_TEXT['lines_1'],
        SPEAKER_SELECTION_TEXT['lines_2'],
        SPEAKER_SELECTION_TEXT['lines_3'],
        SPEAKER_SELECTION_TEXT['lines_4'],
        SPEAKER_SELECTION_TEXT['lines_5'],
        SPEAKER_SELECTION_TEXT['lines_6'],
    ]
    for item in clean_entries:
        prefix = f"[{item['created_at']}]" if item.get("created_at") else "[最近]"
        lines.append(f"- {prefix} {item['content']}")
    return "\n".join(lines)[:_RECENT_GUEST_GROUP_MEMORY_MAX_CHARS]


async def load_recent_guest_group_memory_block(
    username: str | None,
    character_id: str | None,
    *,
    limit: int = 4,
) -> str:
    """Load recent normal_guest_group memories for cross-conversation private recall."""
    username = str(username or "").strip()
    character_id = str(character_id or "").strip()
    if not username or not character_id:
        return ""
    db = get_database()
    conn = await db.acquire()
    try:
        cur = await conn.execute(
            """SELECT m.id, m.memory_type, m.content, m.source, m.importance, m.created_at
               FROM character_memories m
               JOIN users u ON u.id = m.user_id
               WHERE u.username = ?
                 AND m.character_id = ?
                 AND m.is_active = 1
                 AND m.source = 'normal_guest_group'
               ORDER BY datetime(m.created_at) DESC, m.importance DESC, m.id DESC
               LIMIT ?""",
            (username, character_id, max(1, min(8, int(limit or 4)))),
        )
        rows = await cur.fetchall()
        if not rows:
            return ""
        entries = [
            {
                "id": row[0],
                "memory_type": row[1],
                "content": row[2],
                "source": row[3],
                "importance": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]
        return format_recent_guest_group_memory_block(entries)
    except Exception as exc:
        logger.debug(
            SPEAKER_SELECTION_TEXT['load_recent_guest_group_memory_block_1'],
            username,
            character_id[:12],
            exc,
        )
        return ""
    finally:
        await db.release(conn)


def _explicit_reply_character_ids(request: ChatRequest) -> list[str]:
    raw_many = getattr(request, "reply_character_ids", None)
    values: list[Any]
    if isinstance(raw_many, str):
        values = [part for part in re.split(r"[,，\s]+", raw_many) if part]
    elif isinstance(raw_many, (list, tuple, set)):
        values = list(raw_many)
    else:
        values = []

    single = str(getattr(request, "reply_character_id", "") or "").strip()
    if single:
        if values:
            values.append(single)
        else:
            values = [single]

    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        cid = str(raw or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


def extract_at_mention_names(text: str) -> list[str]:
    """Return explicit @ tokens from the latest user text, preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for match in _AT_MENTION_TOKEN_RE.finditer(str(text or "")):
        name = str(match.group(1) or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _latest_visible_user_message(request: ChatRequest) -> ChatMessage | None:
    for msg in reversed(getattr(request, "messages", None) or []):
        if getattr(msg, "role", None) == "user" and not getattr(msg, "isHidden", False):
            return msg
    return None


def quoted_reply_character_id(request: ChatRequest) -> str:
    latest = _latest_visible_user_message(request)
    quote = getattr(latest, "quoted_message", None) if latest is not None else None
    if not quote:
        return ""
    q_role = str(getattr(quote, "role", "") or "").strip().lower()
    if q_role != "assistant":
        return ""
    direct = str(
        getattr(quote, "speaker_character_id", None)
        or getattr(quote, "speakerCharacterId", None)
        or ""
    ).strip()
    if direct:
        return direct

    q_mid = str(getattr(quote, "message_id", "") or "").strip()
    if q_mid:
        for msg in reversed(getattr(request, "messages", None) or []):
            if getattr(msg, "role", None) != "assistant":
                continue
            if str(getattr(msg, "message_id", "") or "").strip() != q_mid:
                continue
            found = str(getattr(msg, "speaker_character_id", "") or "").strip()
            return found or main_character_id(request)
    return main_character_id(request)


def requested_reply_character_ids(request: ChatRequest) -> list[str]:
    explicit = _explicit_reply_character_ids(request)
    if explicit:
        return explicit
    quoted_id = quoted_reply_character_id(request)
    return [quoted_id] if quoted_id else []


def _dedupe_character_ids(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        cid = str(raw or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


def mark_normal_forced_reply_characters(request: ChatRequest, values: list[Any]) -> list[str]:
    ids = _dedupe_character_ids(values)
    if ids:
        setattr(request, "_normal_forced_reply_character_ids", ids)
    elif hasattr(request, "_normal_forced_reply_character_ids"):
        try:
            delattr(request, "_normal_forced_reply_character_ids")
        except Exception:
            setattr(request, "_normal_forced_reply_character_ids", [])
    return ids


def normal_forced_reply_character_ids(request: ChatRequest) -> list[str]:
    if getattr(request, "_normal_auto_handoff", False):
        return []
    marked = getattr(request, "_normal_forced_reply_character_ids", None)
    if isinstance(marked, str):
        marked_ids = [part for part in re.split(r"[,，\s]+", marked) if part]
    elif isinstance(marked, (list, tuple, set)):
        marked_ids = list(marked)
    else:
        marked_ids = []
    ids = _dedupe_character_ids(marked_ids)
    if ids:
        return ids
    return _dedupe_character_ids(requested_reply_character_ids(request))


def explicit_user_at_reply_requested(request: ChatRequest, speaker: str) -> bool:
    """A current user @/speaker selection, never an automatic handoff or trigger."""
    if (getattr(request, "_normal_auto_handoff", False)
            or getattr(request, "_normal_internal_proactive_trigger", False)):
        return False
    speaker = str(speaker or "").strip()
    if not speaker or speaker not in normal_forced_reply_character_ids(request):
        return False
    selected = getattr(request, "_normal_user_selected_reply_character_ids", None)
    if selected is None:
        selected = _explicit_reply_character_ids(request)
    return speaker in selected or bool(extract_at_mention_names(_latest_visible_user_text(request)))


def agent_speaker_context(request: ChatRequest) -> str:
    """Explain the live group scene to the current Agent without a legacy router."""
    speaker = effective_speaker_character_id(request)
    main = main_character_id(request)
    guests = [sid for sid in _recent_visible_assistant_speaker_ids(
        request, include_latest_user=True) if sid != main]
    if not is_guest_speaker(request) and not guests:
        return ""
    if getattr(request, "_normal_auto_handoff", False):
        cause = SPEAKER_SELECTION_TEXT['cause_1']
    elif is_guest_speaker(request):
        cause = "用户选择你参与当前话题"
    else:
        cause = SPEAKER_SELECTION_TEXT['cause_2']
    return (
        SPEAKER_SELECTION_TEXT['agent_speaker_context_1'].format(main_display_name(request), main, speaker_display_name(request), speaker, cause)
    )


def requested_reply_character_id(request: ChatRequest) -> str:
    ids = requested_reply_character_ids(request)
    return ids[0] if ids else ""


def _recent_visible_assistant_speaker_ids(
    request: ChatRequest,
    *,
    include_latest_user: bool = False,
) -> list[str]:
    main_id = main_character_id(request)
    ids: list[str] = []
    for msg in _visible_recent_scene_messages(request, include_latest_user=include_latest_user):
        if getattr(msg, "role", None) != "assistant":
            continue
        sid = str(getattr(msg, "speaker_character_id", "") or "").strip() or main_id
        if sid and sid not in ids:
            ids.append(sid)
    return ids


def normal_at_event_context(request: ChatRequest) -> dict[str, Any]:
    """Structured meaning of explicit @ / reply-speaker selection for this turn."""
    latest = _latest_visible_user_text(request)
    if getattr(request, "_normal_auto_handoff", False):
        return {}
    requested_ids = normal_forced_reply_character_ids(request)
    explicit_ids = requested_reply_character_ids(request)
    original_ids_raw = getattr(request, "_normal_multi_original_reply_character_ids", None)
    if isinstance(original_ids_raw, str):
        original_ids = [part for part in re.split(r"[,，\s]+", original_ids_raw) if part]
    elif isinstance(original_ids_raw, (list, tuple, set)):
        original_ids = [str(x or "").strip() for x in original_ids_raw if str(x or "").strip()]
    else:
        original_ids = explicit_ids
    original_ids = _dedupe_character_ids(original_ids)
    speaker_id = effective_speaker_character_id(request)
    main_id = main_character_id(request)
    has_at_marker = bool(re.search(r"[@＠]", latest or ""))
    has_mention_only = _is_mention_only_user_text(latest)
    quoted_id = quoted_reply_character_id(request)
    unresolved_mentions = [
        str(value or "").strip()
        for value in (getattr(request, "_normal_unresolved_at_mentions", None) or [])
        if str(value or "").strip()
    ]
    is_forced = bool(requested_ids or explicit_ids or quoted_id)
    if not is_forced and not has_at_marker:
        return {}

    recent_speaker_ids = _recent_visible_assistant_speaker_ids(request, include_latest_user=False)
    speaker_already_present = bool(
        speaker_id
        and (
            speaker_id in recent_speaker_ids
            or (speaker_id == main_id and not is_guest_speaker(request))
        )
    )
    if unresolved_mentions:
        event_type = "unresolved_mention_only" if has_mention_only else "unresolved_mention_with_instruction"
    elif has_mention_only:
        event_type = "mention_only_turn" if speaker_already_present else "mention_only_entry"
    elif has_at_marker:
        event_type = "mention_with_instruction"
    elif quoted_id:
        event_type = "quoted_reply"
    else:
        event_type = "forced_reply"

    return {
        "enabled": True,
        "event_type": event_type,
        "mention_only": has_mention_only,
        "has_at_marker": has_at_marker,
        "speaker_was_already_present": speaker_already_present,
        "speaker_character_id": speaker_id,
        "speaker_name": speaker_display_name(request),
        "main_character_id": main_id,
        "main_name": main_display_name(request),
        "requested_character_ids": requested_ids,
        "original_requested_character_ids": original_ids,
        "requested_count": len(original_ids or requested_ids),
        "unresolved_at_mentions": unresolved_mentions,
        "recent_speaker_ids": recent_speaker_ids,
        "latest_user_text": latest[:500],
    }


def format_normal_at_event_context(request: ChatRequest) -> str:
    event = normal_at_event_context(request)
    if not event:
        return ""
    lines = [
        "【@ 临时群聊事件】",
        f"event_type={event.get('event_type')}",
        f"current_speaker={event.get('speaker_name')}({event.get('speaker_character_id')})",
        f"main_character={event.get('main_name')}({event.get('main_character_id')})",
        f"mention_only={bool(event.get('mention_only'))}",
        f"speaker_was_already_present={bool(event.get('speaker_was_already_present'))}",
        f"requested_count={event.get('requested_count') or 0}",
    ]
    if event.get("original_requested_character_ids"):
        lines.append(
            "original_requested_character_ids="
            + "、".join(str(x) for x in event.get("original_requested_character_ids") or [])
        )
    unresolved_mentions = [str(x) for x in event.get("unresolved_at_mentions") or [] if str(x)]
    if unresolved_mentions:
        unresolved_text = "、".join(unresolved_mentions)
        lines.append("unresolved_at_mentions=" + unresolved_text)
        lines.append(
            SPEAKER_SELECTION_TEXT['format_normal_at_event_context_2']
        )
        lines.append(
            SPEAKER_SELECTION_TEXT['format_normal_at_event_context_6']
            + unresolved_text
            + SPEAKER_SELECTION_TEXT['format_normal_at_event_context_4']
        )
        lines.append(
            SPEAKER_SELECTION_TEXT['format_normal_at_event_context_3']
        )
    elif event.get("mention_only"):
        if event.get("speaker_was_already_present"):
            lines.append(SPEAKER_SELECTION_TEXT['format_normal_at_event_context_7'])
        else:
            lines.append(SPEAKER_SELECTION_TEXT['format_normal_at_event_context_8'])
    else:
        lines.append(SPEAKER_SELECTION_TEXT['format_normal_at_event_context_5'])
    lines.append(SPEAKER_SELECTION_TEXT['format_normal_at_event_context_1'])
    return "\n".join(lines)


def effective_speaker_character_id(request: ChatRequest) -> str:
    return str(
        getattr(request, "_normal_speaker_character_id", None)
        or getattr(request, "character_id", None)
        or ""
    ).strip()


def main_character_id(request: ChatRequest) -> str:
    return str(getattr(request, "character_id", None) or "").strip()


def is_guest_speaker(request: ChatRequest) -> bool:
    return bool(getattr(request, "_normal_speaker_is_guest", False))


def speaker_context_conversation_id(request: ChatRequest) -> str:
    """Conversation id that owns the current speaker's private normal state."""
    if is_guest_speaker(request):
        return str(getattr(request, "_normal_speaker_private_conversation_id", "") or "").strip()
    return str(getattr(request, "conversation_id", "") or "").strip()


def speaker_display_name(request: ChatRequest) -> str:
    return str(
        getattr(request, "_normal_speaker_character_name", None)
        or getattr(request, "_normal_main_character_name", None)
        or effective_speaker_character_id(request)
        or "角色"
    ).strip()


def main_display_name(request: ChatRequest) -> str:
    return str(
        getattr(request, "_normal_main_character_name", None)
        or main_character_id(request)
        or "主角色"
    ).strip()


def normal_role_debug_params(request: ChatRequest, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Debug metadata for the two role axes in normal chat.

    primary/main is the conversation owner; speaker is the current reply actor.
    """
    main_id = main_character_id(request)
    speaker_id = effective_speaker_character_id(request) or main_id
    out: dict[str, Any] = {
        "primary_character_id": main_id,
        "primary_character_name": main_display_name(request),
        "speaker_character_id": speaker_id,
        "speaker_character_name": speaker_display_name(request),
        "guest_speaker": bool(speaker_id and main_id and speaker_id != main_id) or is_guest_speaker(request),
    }
    out.update(getattr(request, '_agent_log_params', None) or {})
    if extra:
        out.update(extra)
    return out


def speaker_message_fields(request: ChatRequest) -> dict[str, str]:
    """Fields persisted/emitted for assistant messages.

    To keep no-@ normal chat behavior unchanged, only guest speaker turns carry
    explicit message-level speaker metadata.  Missing speaker fields are treated
    by clients and model context as the main conversation character.
    """
    if not is_guest_speaker(request):
        return {}
    sid = effective_speaker_character_id(request)
    if not sid:
        return {}
    out = {
        "speaker_character_id": sid,
        "speaker_name": speaker_display_name(request),
    }
    avatar = str(getattr(request, "_normal_speaker_character_avatar", "") or "").strip()
    if avatar:
        out["speaker_avatar"] = avatar
    return out


def speaker_event_fields(request: ChatRequest) -> dict[str, str]:
    fields = speaker_message_fields(request)
    if not fields:
        return {}
    return {
        **fields,
        "speakerCharacterId": fields.get("speaker_character_id", ""),
        "speakerName": fields.get("speaker_name", ""),
        **({"speakerAvatar": fields["speaker_avatar"]} if fields.get("speaker_avatar") else {}),
    }


def _parse_character_json(data_json: Any) -> dict[str, Any]:
    if isinstance(data_json, dict):
        return dict(data_json)
    try:
        parsed = json.loads(data_json or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


async def load_owned_visible_character(username: str | None, character_id: str | None) -> dict[str, Any] | None:
    username = str(username or "").strip()
    character_id = str(character_id or "").strip()
    if not username or not character_id:
        return None
    try:
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                """
                SELECT c.id, c.name, c.avatar, c.data, c.prompt,
                       COALESCE(c.is_official_source, 0)
                  FROM characters c
                  JOIN users u ON u.id = c.user_id
                 WHERE u.username = ?
                   AND c.id = ?
                   AND COALESCE(c.is_hidden, 0) = 0
                 LIMIT 1
                """,
                (username, character_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        is_official_source = int(row[5] or 0) == 1
        if is_official_source and username.lower() != "system":
            return None
        merged = load_character_from_db(username, character_id) or _parse_character_json(row[3])
        char = dict(merged or {})
        char["id"] = row[0]
        if is_official_source:
            char["isOfficialSource"] = True
        if not str(char.get("name") or "").strip():
            char["name"] = row[1] or row[0]
        if not str(char.get("avatar") or "").strip() and row[2]:
            char["avatar"] = row[2]
        if "prompt" not in char:
            char["prompt"] = "" if row[4] is None else str(row[4])
        return char
    except Exception as exc:
        logger.warning(SPEAKER_SELECTION_TEXT['load_owned_visible_character_1'], username, character_id, exc)
        return None


async def load_owned_visible_characters_for_mentions(username: str | None) -> list[dict[str, Any]]:
    username = str(username or "").strip()
    if not username:
        return []
    try:
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                """
                SELECT c.id, c.name, c.avatar, c.data, c.prompt,
                       COALESCE(c.is_official_source, 0)
                  FROM characters c
                  JOIN users u ON u.id = c.user_id
                 WHERE u.username = ?
                   AND COALESCE(c.is_hidden, 0) = 0
                 ORDER BY c.name ASC, c.id ASC
                """,
                (username,),
            ) as cur:
                rows = await cur.fetchall()
        chars: list[dict[str, Any]] = []
        for row in rows or []:
            is_official_source = int(row[5] or 0) == 1
            if is_official_source and username.lower() != "system":
                continue
            data = _parse_character_json(row[3])
            char = dict(data or {})
            char["id"] = row[0]
            if not str(char.get("name") or "").strip():
                char["name"] = row[1] or row[0]
            if not str(char.get("avatar") or "").strip() and row[2]:
                char["avatar"] = row[2]
            if "prompt" not in char:
                char["prompt"] = "" if row[4] is None else str(row[4])
            if is_official_source:
                char["isOfficialSource"] = True
            chars.append(char)
        return chars
    except Exception as exc:
        logger.warning(SPEAKER_SELECTION_TEXT['load_owned_visible_characters_for_mentions_1'], username, exc)
        return []


def _message_visible(msg: ChatMessage) -> bool:
    if getattr(msg, "isHidden", False):
        return False
    try:
        if is_summary_placeholder_message(msg):
            return False
    except Exception:
        pass
    return getattr(msg, "role", None) in {"user", "assistant"}


def _speaker_label_for_message(msg: ChatMessage, *, main_name: str) -> str:
    if getattr(msg, "role", None) == "user":
        return "用户"
    name = str(getattr(msg, "speaker_name", "") or "").strip()
    return name or main_name or "主角色"


def _visible_recent_scene_messages(request: ChatRequest, *, include_latest_user: bool) -> list[ChatMessage]:
    source = [m for m in (getattr(request, "messages", None) or []) if _message_visible(m)]
    if not include_latest_user:
        latest_user_idx = next(
            (idx for idx in range(len(source) - 1, -1, -1) if getattr(source[idx], "role", None) == "user"),
            -1,
        )
        if latest_user_idx >= 0:
            source = source[:latest_user_idx]

    user_turns = 0
    start = 0
    for idx in range(len(source) - 1, -1, -1):
        if getattr(source[idx], "role", None) == "user":
            user_turns += 1
            if user_turns >= _MAX_RECENT_USER_TURNS_FOR_AT:
                start = idx
                break
    return source[start:]


def _latest_visible_user_text(request: ChatRequest) -> str:
    if getattr(request, '_normal_reply_batch', None) is not None:
        from .service import _latest_visible_user_batch
        return '\n'.join(str(m.content or '').strip() for m in
                         _latest_visible_user_batch(list(request.messages or [])))
    for msg in reversed(getattr(request, "messages", None) or []):
        if getattr(msg, "role", None) == "user" and not getattr(msg, "isHidden", False):
            return str(getattr(msg, "content", "") or "").strip()
    return ""


def _recent_assistant_speaker_candidates(
    request: ChatRequest,
    *,
    recent_assistant_turns: int = _MAX_RECENT_ASSISTANT_TURNS_FOR_USER_SPEAKER_INTENT,
) -> list[dict[str, str]]:
    """Characters visible in the most recent assistant turns, newest evidence wins."""
    main_id = main_character_id(request)
    main_name = main_display_name(request)
    newest_first: list[dict[str, str]] = []
    seen: set[str] = set()
    count = 0
    for msg in reversed(getattr(request, "messages", None) or []):
        if not _message_visible(msg) or getattr(msg, "role", None) != "assistant":
            continue
        count += 1
        sid = str(getattr(msg, "speaker_character_id", "") or "").strip() or main_id
        if sid and sid not in seen:
            seen.add(sid)
            newest_first.append(
                {
                    "reply_character_id": sid,
                    "name": str(getattr(msg, "speaker_name", "") or "").strip()
                    or (main_name if sid == main_id else sid),
                    "role": "main" if sid == main_id else "recent_speaker",
                }
            )
        if count >= max(1, int(recent_assistant_turns or 1)):
            break
    return list(reversed(newest_first))


def user_speaker_intent_candidates(request: ChatRequest) -> list[dict[str, str]]:
    candidates = _recent_assistant_speaker_candidates(request)
    main_id = main_character_id(request)
    if not any(c.get("reply_character_id") == main_id for c in candidates):
        main_name = main_display_name(request)
        candidates.insert(
            0,
            {
                "reply_character_id": main_id,
                "name": main_name or main_id,
                "role": "main",
            },
        )
    return candidates[:8]


async def _ensure_main_character_metadata_for_speaker_intent(
    request: ChatRequest,
    *,
    username: str | None = None,
    character_id: str | None = None,
) -> None:
    if str(getattr(request, "_normal_main_character_name", "") or "").strip():
        return
    uname = str(username or getattr(request, "username", "") or "").strip()
    cid = str(character_id or main_character_id(request) or "").strip()
    if not uname or not cid:
        return
    char = await load_owned_visible_character(uname, cid)
    if not char:
        return
    setattr(request, "_normal_main_character_name", str(char.get("name") or cid).strip())
    avatar = str(char.get("avatar") or "").strip()
    if avatar:
        setattr(request, "_normal_main_character_avatar", avatar)


_DIRECT_CALL_TAIL_RE = re.compile(
    r"^(你|妳|请|麻烦|来|说|讲|聊|回答|告诉|觉得|认为|看|能|可以|要|帮|继续|接着|再|给|用|回复|评价|总结|补充|呢|吧)"
)
_DIRECT_CALL_SEPARATOR_CHARS = set(" \t\r\n,，:：、。！？!?;；")


def _speaker_direct_call_aliases(candidate: dict[str, str]) -> list[str]:
    name = str(candidate.get("name") or "").strip()
    values = [name]
    if len(name) >= 3 and name.endswith("派"):
        values.append(name[:-1])
    aliases: list[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in aliases:
            aliases.append(value)
    aliases.sort(key=len, reverse=True)
    return aliases


def _text_starts_with_direct_call(text: str, alias: str) -> bool:
    text = str(text or "").lstrip()
    alias = str(alias or "").strip()
    if not text or not alias or not text.startswith(alias):
        return False
    tail = text[len(alias):].lstrip()
    if not tail:
        return True
    first = tail[0]
    return first in _DIRECT_CALL_SEPARATOR_CHARS or bool(_DIRECT_CALL_TAIL_RE.match(tail))


def _deterministic_direct_speaker_call_ids(
    latest: str,
    candidates: list[dict[str, str]],
) -> list[str] | None:
    ordered = sorted(candidates or [], key=lambda c: len(str(c.get("name") or "")), reverse=True)
    for candidate in ordered:
        cid = str(candidate.get("reply_character_id") or "").strip()
        if not cid:
            continue
        for alias in _speaker_direct_call_aliases(candidate):
            if _text_starts_with_direct_call(latest, alias):
                return [cid]
    return None


def _has_recent_non_main_speaker_candidate(request: ChatRequest) -> bool:
    main_id = main_character_id(request)
    return any(
        str(c.get("reply_character_id") or "").strip()
        and str(c.get("reply_character_id") or "").strip() != main_id
        for c in _recent_assistant_speaker_candidates(request)
    )


def _speaker_intent_scene_text(request: ChatRequest, *, max_messages: int = 18) -> str:
    main_name = main_display_name(request)
    visible = [m for m in (getattr(request, "messages", None) or []) if _message_visible(m)]
    lines: list[str] = []
    for msg in visible[-max_messages:]:
        content = str(getattr(msg, "content", "") or "").strip()
        if not content:
            continue
        lines.append(f"{_speaker_label_for_message(msg, main_name=main_name)}：{content[:900]}")
    return "\n".join(lines)[-8000:]


def _coerce_user_speaker_intent_result(value: Any, candidates: list[dict[str, str]]) -> list[str]:
    allowed = {str(c.get("reply_character_id") or "").strip() for c in candidates or []}
    allowed.discard("")
    data = value if isinstance(value, dict) else {}
    raw_ids = data.get("reply_character_ids")
    if isinstance(raw_ids, str):
        ids = [part for part in re.split(r"[,，\s]+", raw_ids) if part]
    elif isinstance(raw_ids, (list, tuple)):
        ids = list(raw_ids)
    else:
        single = data.get("reply_character_id") or data.get("target_character_id")
        ids = [single] if single else []
    mode = str(data.get("mode") or data.get("intent") or "").strip().lower()
    if mode in {"none", "stop", "main_only"}:
        return []
    return [cid for cid in _dedupe_character_ids(ids) if cid in allowed][:6]




async def run_normal_user_speaker_intent_router(
    request: ChatRequest,
    router_cfg: dict,
    *,
    username: str | None = None,
    character_id: str | None = None,
    debug_mode: str = "normal",
) -> list[str]:
    """Infer initial speakers from the user's latest utterance when no explicit @ exists."""
    if requested_reply_character_ids(request):
        return []
    if not _has_recent_non_main_speaker_candidate(request):
        return []
    latest = _latest_visible_user_text(request)
    if not latest:
        return []
    await _ensure_main_character_metadata_for_speaker_intent(
        request,
        username=username,
        character_id=character_id,
    )
    candidates = user_speaker_intent_candidates(request)
    if len(candidates) <= 1:
        return []
    deterministic_ids = _deterministic_direct_speaker_call_ids(latest, candidates)
    if deterministic_ids is not None:
        main_id = main_character_id(request)
        return [] if deterministic_ids == [main_id] else deterministic_ids
    if not router_cfg or not router_cfg.get("api_key"):
        return []
    scene = _speaker_intent_scene_text(request)
    if not scene:
        return []
    model_name = router_cfg.get("model_name") or "deepseek-flash"
    candidate_text = json.dumps(
        [
            {
                "reply_character_id": c["reply_character_id"],
                "name": c["name"],
                "role": c["role"],
            }
            for c in candidates
        ],
        ensure_ascii=False,
    )
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": USER_SPEAKER_INTENT_SYSTEM},
            {
                "role": "user",
                "content": (
                    SPEAKER_SELECTION_TEXT['payload_7']
                    + latest[:1200]
                    + SPEAKER_SELECTION_TEXT['payload_6']
                    + candidate_text
                    + "\n\n【近期现场】\n"
                    + scene

                )[:12000],
            },
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    try:
        llm_call = call_llm_payload
        if llm_call is None:
            from ..providers.llm_call import call_llm_payload as llm_call
        res = await llm_call(
            payload,
            router_cfg,
            task="classify",
            timeout=30.0,
            chat_debug_request={
                "username": username,
                "character_id": character_id,
                "mode": (debug_mode or "normal").strip() or "normal",
                "model_name": model_name,
                "stage": "NORMAL_STEP_1_SPEAKER_INTENT_REQUEST",
                "params": {"tool": "normal_user_speaker_intent", "candidate_count": len(candidates)},
            },
            record_usage="main",
            usage_meter_username=username,
            charge_membership_chat_quota=True,
        )
        parsed = json.loads((res.text or "").strip())
        return _coerce_user_speaker_intent_result(parsed, candidates)
    except Exception as exc:
        logger.debug("[NormalSpeakerIntent] failed, fallback to main speaker: %s", exc)
        try:
            await save_chat_debug_log(
                username,
                character_id,
                debug_mode,
                model_name,
                str(exc),
                "NORMAL_STEP_1_SPEAKER_INTENT_ERROR",
            )
        except Exception:
            pass
        return []


def _remove_mention_tokens(text: str) -> str:
    # @ candidates in the app are concrete character names; remove every compact
    # @token and then inspect whether the user wrote any real instruction.
    return re.sub(r"[@＠][^\s@＠,，。！？!?;；:：、（）()\[\]【】》」』\"'“”‘’…]+", "", text or "")


def _is_mention_only_user_text(text: str) -> bool:
    stripped = _remove_mention_tokens(text)
    stripped = re.sub(r"[\s,，。！？!?;；:：、（）()\[\]【】《》「」『』\"'“”‘’…~～·\-—_]+", "", stripped)
    return bool((text or "").strip()) and not stripped


def guest_mention_only_prompt(request: ChatRequest) -> str:
    if not is_guest_speaker(request):
        return ""
    latest = _latest_visible_user_text(request)
    if not _is_mention_only_user_text(latest):
        return ""
    speaker_name = speaker_display_name(request)
    main_name = main_display_name(request)
    return (
        SPEAKER_SELECTION_TEXT['guest_mention_only_prompt_1'].format(speaker_name, main_name)
    )


def recent_at_eligibility_text(request: ChatRequest, *, main_name: str) -> str:
    """Recent context used to verify that B was already in the scene.

    The latest visible user message is included: the mobile client sends the
    selected reply_character_id together with the same text where the user typed
    "@B", so this turn's explicit mention is valid eligibility evidence.  A
    hidden or unmentioned reply id still fails because the character name must
    appear in the visible recent text.
    """
    recent = _visible_recent_scene_messages(request, include_latest_user=True)

    lines: list[str] = []
    for msg in recent:
        content = str(getattr(msg, "content", "") or "").strip()
        if not content:
            continue
        label = _speaker_label_for_message(msg, main_name=main_name)
        lines.append(f"{label}：{content}")
    return "\n".join(lines)


def guest_scene_context_prompt(request: ChatRequest) -> str:
    """Raw recent group-scene context shown to a guest speaker.

    This is deliberately scene-only: it tells the guest what was just said in
    the main conversation without exposing the main character's private memory.
    """
    if not is_guest_speaker(request):
        return ""
    main_name = main_display_name(request)
    speaker_name = speaker_display_name(request)
    recent = _visible_recent_scene_messages(request, include_latest_user=True)
    lines: list[str] = []
    for msg in recent:
        content = str(getattr(msg, "content", "") or "").strip()
        if not content:
            continue
        label = _speaker_label_for_message(msg, main_name=main_name)
        lines.append(f"{label}：{content[:900]}")
    if not lines:
        return ""
    body = "\n".join(lines)
    if len(body) > _GUEST_SCENE_MAX_CHARS:
        body = body[-_GUEST_SCENE_MAX_CHARS:]
    mention_only_block = guest_mention_only_prompt(request)
    return (
        SPEAKER_SELECTION_TEXT['guest_scene_context_prompt_1'].format(speaker_name, main_name, main_name, speaker_name, speaker_name)
        + (mention_only_block + "\n" if mention_only_block else "")
        + body
    )


def _coerce_chat_message(raw: Any) -> ChatMessage | None:
    if isinstance(raw, ChatMessage):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return ChatMessage.model_validate(
            {
                "role": raw.get("role"),
                "content": raw.get("content") or "",
                "timestamp": raw.get("timestamp"),
                "message_id": raw.get("message_id"),
                "sequence_number": raw.get("sequence_number"),
                "isHidden": bool(raw.get("isHidden") or raw.get("is_hidden")),
                "speaker_character_id": raw.get("speaker_character_id"),
                "speaker_name": raw.get("speaker_name"),
                "speaker_avatar": raw.get("speaker_avatar"),
            }
        )
    except Exception:
        return None


async def _stable_normal_conversation_id(username: str, character_id: str) -> str:
    username = str(username or "").strip()
    character_id = str(character_id or "").strip()
    if not username or not character_id:
        return ""
    try:
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            user_id = await db._get_user_id(conn, username)
        digest = hashlib.sha1(f"{user_id}:{character_id}".encode("utf-8")).hexdigest()[:16]
        return f"normal_{user_id}_{digest}"
    except Exception as exc:
        logger.debug(SPEAKER_SELECTION_TEXT['stable_normal_conversation_id_1'], username, character_id, exc)
        return ""


async def ensure_guest_private_context(request: ChatRequest) -> dict[str, Any]:
    """Load/cache the guest's own normal conversation state.

    The returned conversation id is the guest's private normal-chat id.  If the
    guest has never opened a private conversation, the stable id that future
    normal saves will use is returned so memory written now can be found later.
    """
    if not is_guest_speaker(request):
        return {}
    cached = getattr(request, "_normal_speaker_private_context", None)
    if isinstance(cached, dict):
        return cached

    username = str(getattr(request, "username", "") or "").strip()
    speaker_id = effective_speaker_character_id(request)
    context: dict[str, Any] = {"conversation_id": "", "messages": []}
    if not username or not speaker_id:
        setattr(request, "_normal_speaker_private_context", context)
        return context

    try:
        from ..db import ConversationsDAO

        db = get_database()
        await db.init()
        convs = await ConversationsDAO(db).load_conversations(username, speaker_id)
        target = convs[0] if convs else None
        if target:
            context["conversation_id"] = str(target.get("id") or "").strip()
            messages: list[ChatMessage] = []
            for raw in target.get("messages") or []:
                msg = _coerce_chat_message(raw)
                if msg is not None and _message_visible(msg):
                    messages.append(msg)
            context["messages"] = messages
    except Exception as exc:
        logger.debug(SPEAKER_SELECTION_TEXT['ensure_guest_private_context_2'], username, speaker_id, exc)

    if not context.get("conversation_id"):
        context["conversation_id"] = await _stable_normal_conversation_id(username, speaker_id)

    setattr(request, "_normal_speaker_private_context", context)
    setattr(request, "_normal_speaker_private_conversation_id", str(context.get("conversation_id") or "").strip())
    logger.debug(
        SPEAKER_SELECTION_TEXT['ensure_guest_private_context_1'],
        username,
        speaker_id[:12],
        str(context.get("conversation_id") or "")[:12],
        len(context.get("messages") or []),
    )
    return context


def guest_private_recent_raw_turns(request: ChatRequest) -> list[tuple[str, str]]:
    context = getattr(request, "_normal_speaker_private_context", None)
    if not isinstance(context, dict):
        return []
    messages = [
        m for m in (context.get("messages") or [])
        if isinstance(m, ChatMessage) and _message_visible(m)
    ]
    recent = messages[-_GUEST_PRIVATE_RECENT_MAX_MESSAGES:]
    turns: list[tuple[str, str]] = []
    for msg in recent:
        text = str(getattr(msg, "content", "") or "").strip()
        role = str(getattr(msg, "role", "") or "").strip().lower()
        if role in {"user", "assistant"} and text:
            turns.append((role, text))
    return turns


def _compact_for_name_match(value: str) -> str:
    return re.sub(r"[\s@＠:：,，。！？!?.、·•\-—_（）()\[\]【】\"'“”‘’]+", "", value or "").lower()


def _character_mention_name_compacts(character: dict[str, Any]) -> set[str]:
    names = {
        character.get("id"),
        character.get("name"),
        character.get("displayName"),
        character.get("profileName"),
        character.get("profileNickname"),
        character.get("nickname"),
    }
    compacted = {_compact_for_name_match(str(name or "")) for name in names}
    compacted.discard("")
    return compacted


def _resolve_mention_name_to_character_id(
    mention_name: str,
    characters: list[dict[str, Any]],
) -> str:
    token = _compact_for_name_match(mention_name)
    if not token:
        return ""

    exact_ids: list[str] = []
    prefix_ids: list[str] = []
    for character in characters or []:
        cid = str(character.get("id") or "").strip()
        if not cid:
            continue
        names = _character_mention_name_compacts(character)
        if token in names:
            exact_ids.append(cid)
            continue
        if len(token) >= 2 and any(name.startswith(token) for name in names):
            prefix_ids.append(cid)

    exact_ids = _dedupe_character_ids(exact_ids)
    if len(exact_ids) == 1:
        return exact_ids[0]
    if len(exact_ids) > 1:
        return ""
    prefix_ids = _dedupe_character_ids(prefix_ids)
    return prefix_ids[0] if len(prefix_ids) == 1 else ""
