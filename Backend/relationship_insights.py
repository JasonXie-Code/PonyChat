from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

import aiosqlite

from .config import logger, model_manager
from .db import get_database
from .providers.llm_call import call_llm_payload
from .reasoning_config import apply_llm_task_payload_config, llm_task_float
from .reasoning_policy import resolve_software_reasoning_policy
from .relationship_stages import RELATIONSHIP_STAGE_KEYS, normalize_relationship_stage
from .utils import save_chat_debug_log

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore


RELATIONSHIP_PAGE_VERSION = 1
GENERATE_TIMEOUT_SECONDS = 60
MAX_RAW_MESSAGES = int(os.getenv("PONYCHAT_RELATIONSHIP_RAW_MESSAGES") or "80")
MAX_MEMORY_ROWS = int(os.getenv("PONYCHAT_RELATIONSHIP_MEMORY_ROWS") or "60")
MAX_DAILY_PAIRS = int(os.getenv("PONYCHAT_RELATIONSHIP_DAILY_LIMIT") or "50")

PAGE_FIELD_LIMITS = {
    "overview": 90,
    "mood": 72,
    "chip": 4,
    "portrait": 40,
    "item": 48,
    "suggestion": 14,
}
RELATIONSHIP_PAGE_CHIP_LIMIT = 4
RELATIONSHIP_PAGE_FOUR_CHAR_CHIP_LIMIT = 2

RELATIONSHIP_STAGE_LABELS: Dict[str, str] = {
    "new_contact": "新朋友",
    "uncertain": "未知",
    "familiar": "好朋友",
    "mentor_student": "师生",
    "trusted_companion": "可信同伴",
    "family_like": "家人般",
    "flirting": "暧昧对象",
    "committed_partner": "伴侣",
    "intimate_partner": "亲密伴侣",
    "broken_up": "已分手",
    "in_conflict": "吵架中",
    "mutual_dislike": "互相看不爽",
    "hurtful_dynamic": "互相伤害",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _local_timezone():
    if ZoneInfo is not None:
        try:
            return ZoneInfo(os.getenv("PONYCHAT_LOCAL_TIMEZONE") or "Asia/Shanghai")
        except Exception:
            pass
    return timezone(timedelta(hours=8))


def _seconds_until_next_midnight() -> float:
    tz = _local_timezone()
    now = datetime.now(tz)
    target = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1.0, (target - now).total_seconds())


def _compact_text(value: Any, limit: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _coerce_string_list(value: Any, *, limit: int, item_limit: int) -> List[str]:
    if isinstance(value, str):
        candidates = [
            part.strip(" -\t\r\n")
            for part in re.split(r"[\n；;]", value)
            if part.strip(" -\t\r\n")
        ]
    elif isinstance(value, Iterable):
        candidates = [str(item or "").strip() for item in value]
    else:
        candidates = []

    result: List[str] = []
    for item in candidates:
        text = _compact_text(item, item_limit)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _coerce_relationship_chips(value: Any) -> List[str]:
    if isinstance(value, str):
        candidates = [
            part.strip(" -\t\r\n")
            for part in re.split(r"[\n；;]", value)
            if part.strip(" -\t\r\n")
        ]
    elif isinstance(value, Iterable):
        candidates = [str(item or "").strip() for item in value]
    else:
        candidates = []

    result: List[str] = []
    four_char_count = 0
    for item in candidates:
        text = _compact_text(item, PAGE_FIELD_LIMITS["chip"])
        if not text or text in result:
            continue
        is_four_char = len(text) >= PAGE_FIELD_LIMITS["chip"]
        if is_four_char and four_char_count >= RELATIONSHIP_PAGE_FOUR_CHAR_CHIP_LIMIT:
            continue
        result.append(text)
        if is_four_char:
            four_char_count += 1
        if len(result) >= RELATIONSHIP_PAGE_CHIP_LIMIT:
            break
    return result


def default_relationship_page(stage: str = "uncertain") -> Dict[str, Any]:
    normalized = normalize_relationship_stage(stage)
    return {
        "version": RELATIONSHIP_PAGE_VERSION,
        "stage_label": RELATIONSHIP_STAGE_LABELS.get(normalized, "未知"),
        "overview": "",
        "mood": "",
        "chips": [],
        "self_portrait": "",
        "between_portrait": "",
        "remembered_items": [],
        "timeline_items": [],
        "suggestions": [],
    }


def normalize_relationship_page_content(value: Any, *, stage: str = "uncertain") -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None

    normalized_stage = normalize_relationship_stage(stage)
    content = default_relationship_page(normalized_stage)
    content["stage_label"] = _compact_text(
        value.get("stage_label") or RELATIONSHIP_STAGE_LABELS.get(normalized_stage, "未知"),
        16,
    )
    content["overview"] = _compact_text(value.get("overview"), PAGE_FIELD_LIMITS["overview"])
    content["mood"] = _compact_text(value.get("mood"), PAGE_FIELD_LIMITS["mood"])
    content["chips"] = _coerce_relationship_chips(value.get("chips"))
    content["self_portrait"] = _compact_text(
        value.get("self_portrait"),
        PAGE_FIELD_LIMITS["portrait"],
    )
    content["between_portrait"] = _compact_text(
        value.get("between_portrait"),
        PAGE_FIELD_LIMITS["portrait"],
    )
    content["remembered_items"] = _coerce_string_list(
        value.get("remembered_items"),
        limit=4,
        item_limit=PAGE_FIELD_LIMITS["item"],
    )
    content["timeline_items"] = _coerce_string_list(
        value.get("timeline_items"),
        limit=4,
        item_limit=PAGE_FIELD_LIMITS["item"],
    )
    content["suggestions"] = _coerce_string_list(
        value.get("suggestions"),
        limit=4,
        item_limit=PAGE_FIELD_LIMITS["suggestion"],
    )

    has_content = any(
        [
            content["overview"],
            content["mood"],
            content["self_portrait"],
            content["between_portrait"],
            content["remembered_items"],
            content["timeline_items"],
            content["suggestions"],
        ]
    )
    return content if has_content else None


def parse_relationship_page_json(raw: Any, *, stage: str = "uncertain") -> Optional[Dict[str, Any]]:
    if isinstance(raw, Mapping):
        return normalize_relationship_page_content(raw, stage=stage)
    text = str(raw or "").strip()
    if not text or text == "{}":
        return None
    try:
        return normalize_relationship_page_content(json.loads(text), stage=stage)
    except Exception:
        return None


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


async def ensure_relationship_page_storage() -> None:
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS relationship_presence_states (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'active_chatting',
                relationship_stage TEXT NOT NULL DEFAULT 'uncertain',
                relationship_page_json TEXT NOT NULL DEFAULT '{}',
                relationship_page_updated_at_ms INTEGER NOT NULL DEFAULT 0,
                relationship_page_source_json TEXT NOT NULL DEFAULT '{}',
                character_initiative INTEGER NOT NULL DEFAULT 45,
                user_proactive_frequency TEXT NOT NULL DEFAULT 'normal',
                last_user_message_id TEXT DEFAULT '',
                last_user_at_ms INTEGER DEFAULT 0,
                last_assistant_message_id TEXT DEFAULT '',
                last_assistant_at_ms INTEGER DEFAULT 0,
                last_proactive_message_id TEXT DEFAULT '',
                last_proactive_at_ms INTEGER DEFAULT 0,
                absence_started_at_ms INTEGER DEFAULT 0,
                silence_hours REAL DEFAULT 0,
                consecutive_proactive_days INTEGER NOT NULL DEFAULT 0,
                total_proactive_in_absence INTEGER NOT NULL DEFAULT 0,
                last_motivation TEXT DEFAULT '',
                motivation_history_json TEXT NOT NULL DEFAULT '[]',
                content_signature_history_json TEXT NOT NULL DEFAULT '[]',
                cooldown_until_ms INTEGER DEFAULT 0,
                next_evaluation_at_ms INTEGER DEFAULT 0,
                user_ended_conversation INTEGER NOT NULL DEFAULT 0,
                user_do_not_disturb_until_ms INTEGER DEFAULT 0,
                disabled_reason TEXT DEFAULT '',
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_presence_pair
                ON relationship_presence_states(username, character_id);
            """
        )
        async with conn.execute("PRAGMA table_info(relationship_presence_states)") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        migrations = [
            ("relationship_stage", "TEXT NOT NULL DEFAULT 'uncertain'"),
            ("relationship_page_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("relationship_page_updated_at_ms", "INTEGER NOT NULL DEFAULT 0"),
            ("relationship_page_source_json", "TEXT NOT NULL DEFAULT '{}'"),
        ]
        for column, definition in migrations:
            if columns and column not in columns:
                await conn.execute(
                    f"ALTER TABLE relationship_presence_states ADD COLUMN {column} {definition}"
                )
        await conn.commit()


async def load_relationship_state(username: str, character_id: str) -> Optional[Dict[str, Any]]:
    await ensure_relationship_page_storage()
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (
            await conn.execute(
                """
                SELECT username, character_id, conversation_id, relationship_stage,
                       relationship_page_json, relationship_page_updated_at_ms,
                       relationship_page_source_json, updated_at_ms
                  FROM relationship_presence_states
                 WHERE username=? AND character_id=?
                 LIMIT 1
                """,
                (username, character_id),
            )
        ).fetchone()
    if not row:
        return None
    stage = normalize_relationship_stage(str(row["relationship_stage"] or ""))
    return {
        "username": str(row["username"] or username),
        "character_id": str(row["character_id"] or character_id),
        "conversation_id": str(row["conversation_id"] or ""),
        "relationship_stage": stage,
        "relationship_page": parse_relationship_page_json(
            row["relationship_page_json"],
            stage=stage,
        ),
        "relationship_page_updated_at_ms": int(row["relationship_page_updated_at_ms"] or 0),
        "relationship_page_source": _safe_json_loads(row["relationship_page_source_json"]),
        "updated_at_ms": int(row["updated_at_ms"] or 0),
    }


def _safe_json_loads(raw: Any) -> Dict[str, Any]:
    try:
        parsed = json.loads(str(raw or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _profile_pronoun(profile_gender: Any) -> str:
    gender = str(profile_gender or "").strip()
    normalized = gender.lower()
    if not gender:
        return "TA"
    female_markers = ("female", "woman", "girl", "feminine", "mare", "女", "女性", "女生", "雌", "母")
    if any(marker in normalized or marker in gender for marker in female_markers):
        return "她"
    male_markers = ("male", "man", "boy", "masculine", "stallion", "男", "男性", "男生", "雄", "公")
    if any(marker in normalized or marker in gender for marker in male_markers):
        return "他"
    return "TA"


_GUEST_GROUP_MARKERS = (
    "临时群聊",
    "群聊现场",
    "主聊天里被用户 @",
    "被用户 @ 临时加入发言",
    "被 @ 拉进",
    "normal_guest_group",
    "【@ 临时群聊事件】",
)


def _contains_guest_group_marker(value: Any) -> bool:
    text = str(value or "")
    return any(marker in text for marker in _GUEST_GROUP_MARKERS)


def _same_character_name(left: Any, right: Any) -> bool:
    left_text = re.sub(r"\s+", "", str(left or "")).strip().lower()
    right_text = re.sub(r"\s+", "", str(right or "")).strip().lower()
    return bool(left_text and right_text and left_text == right_text)


def _strip_guest_group_marker(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"^【临时群聊发言｜[^】]+】\s*", "", text)
    return text


def _guest_group_actual_speaker(value: Any) -> str:
    text = str(value or "")
    match = re.match(r"^【临时群聊发言｜实际发言者=([^｜】]+)", text)
    return str(match.group(1) or "").strip() if match else ""


def _is_primary_character_speaker(
    message: Mapping[str, Any],
    *,
    character_id: str,
    character_name: str,
    allow_unknown_speaker: bool,
) -> bool:
    speaker_id = str(message.get("speaker_character_id") or "").strip()
    if speaker_id:
        return speaker_id == str(character_id or "").strip()

    speaker_name = str(message.get("speaker_name") or "").strip()
    if speaker_name:
        return _same_character_name(speaker_name, character_name)

    return allow_unknown_speaker


def _filter_raw_messages_for_primary_relationship(
    messages: List[Dict[str, Any]],
    *,
    character_id: str,
    character_name: str,
) -> List[Dict[str, Any]]:
    if not messages:
        return []

    has_non_primary_speaker = any(
        msg.get("role") == "assistant"
        and not _is_primary_character_speaker(
            msg,
            character_id=character_id,
            character_name=character_name,
            allow_unknown_speaker=True,
        )
        for msg in messages
    )
    has_guest_group_marker = any(
        bool(msg.get("had_guest_group_marker"))
        or _contains_guest_group_marker(msg.get("content"))
        for msg in messages
        if msg.get("role") == "assistant"
    )
    if not has_non_primary_speaker and not has_guest_group_marker:
        return messages[-MAX_RAW_MESSAGES:]

    primary_indices = {
        index
        for index, msg in enumerate(messages)
        if msg.get("role") == "assistant"
        and _is_primary_character_speaker(
            msg,
            character_id=character_id,
            character_name=character_name,
            allow_unknown_speaker=False,
        )
    }
    if not primary_indices:
        return []

    filtered: List[Dict[str, Any]] = []
    for index, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant":
            if index in primary_indices:
                filtered.append(msg)
            continue
        if role != "user":
            continue
        text = str(msg.get("content") or "")
        mentions_primary = bool(character_name and character_name in text)
        near_primary_reply = any(abs(index - primary_index) <= 2 for primary_index in primary_indices)
        if mentions_primary or near_primary_reply:
            filtered.append(msg)

    return filtered[-MAX_RAW_MESSAGES:]


async def _fetch_character_profile(
    conn: aiosqlite.Connection,
    *,
    username: str,
    character_id: str,
) -> Dict[str, Any]:
    conn.row_factory = aiosqlite.Row
    row = await (
        await conn.execute(
            """
            SELECT c.id, c.name, c.prompt, c.bio, c.data, c.avatar, u.username AS owner_username
              FROM characters c
              LEFT JOIN users u ON c.user_id = u.id
             WHERE c.id=?
             ORDER BY CASE WHEN u.username=? THEN 0 ELSE 1 END
             LIMIT 1
            """,
            (character_id, username),
        )
    ).fetchone()
    if not row:
        return {"id": character_id, "name": "角色", "prompt": "", "bio": "", "data": {}}

    data: Dict[str, Any] = {}
    try:
        parsed = json.loads(str(row["data"] or "{}"))
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        data = {}

    return {
        "id": str(row["id"] or character_id),
        "name": str(row["name"] or data.get("name") or "角色"),
        "prompt": _compact_text(row["prompt"], 5000),
        "bio": _compact_text(row["bio"], 1200),
        "profile_gender": _compact_text(
            data.get("profileGender")
            or data.get("profile_gender")
            or data.get("gender")
            or "",
            80,
        ),
        "data": data,
    }


async def _fetch_memories(
    conn: aiosqlite.Connection,
    *,
    username: str,
    character_id: str,
) -> List[Dict[str, Any]]:
    conn.row_factory = aiosqlite.Row
    rows = await (
        await conn.execute(
            """
            SELECT m.memory_type, m.content, m.source, m.importance, m.layer, m.period,
                   m.created_at
             FROM character_memories m
              JOIN users u ON m.user_id = u.id
             WHERE u.username=? AND m.character_id=? AND COALESCE(m.is_active, 1)=1
               AND COALESCE(m.source, '') <> 'normal_guest_group'
             ORDER BY COALESCE(m.layer, 0) DESC,
                      COALESCE(m.importance, 5) DESC,
                      COALESCE(m.created_at, '') DESC
             LIMIT ?
            """,
            (username, character_id, MAX_MEMORY_ROWS),
        )
    ).fetchall()
    return [
        {
            "type": str(row["memory_type"] or "episode"),
            "content": _compact_text(row["content"], 700),
            "source": str(row["source"] or ""),
            "importance": int(row["importance"] or 5),
            "layer": int(row["layer"] or 0),
            "period": str(row["period"] or ""),
            "created_at": str(row["created_at"] or ""),
        }
        for row in rows
        if _compact_text(row["content"], 10)
        and not _contains_guest_group_marker(row["content"])
    ]


async def _fetch_context_memories(
    conn: aiosqlite.Connection,
    *,
    username: str,
    character_id: str,
    preferred_conversation_id: str = "",
) -> List[Dict[str, Any]]:
    conn.row_factory = aiosqlite.Row
    rows = await (
        await conn.execute(
            """
            SELECT conversation_id, char_memory_json, short_term_memory, long_term_memory,
                   entries_covered_count, lt_covered_count, updated_at
              FROM normal_chat_memory
             WHERE username=? AND character_id=?
             ORDER BY CASE WHEN conversation_id=? THEN 0 ELSE 1 END,
                      COALESCE(updated_at, 0) DESC
             LIMIT 8
            """,
            (username, character_id, preferred_conversation_id),
        )
    ).fetchall()
    result: List[Dict[str, Any]] = []
    for row in rows:
        entries: List[Any] = []
        try:
            parsed = json.loads(str(row["char_memory_json"] or "[]"))
            if isinstance(parsed, list):
                entries = parsed[-12:]
        except Exception:
            entries = []
        compact_entries: List[str] = []
        for entry in entries:
            if isinstance(entry, Mapping):
                text = (
                    entry.get("summary")
                    or entry.get("content")
                    or entry.get("text")
                    or json.dumps(entry, ensure_ascii=False)
                )
            else:
                text = entry
            if _contains_guest_group_marker(text):
                continue
            compact = _compact_text(text, 260)
            if compact:
                compact_entries.append(compact)
        raw_short_term = row["short_term_memory"]
        raw_mid_term = row["long_term_memory"]
        item = {
            "conversation_id": str(row["conversation_id"] or ""),
            "recent_entries": compact_entries,
            "short_term_memory": ""
            if _contains_guest_group_marker(raw_short_term)
            else _compact_text(raw_short_term, 1200),
            "mid_term_memory": ""
            if _contains_guest_group_marker(raw_mid_term)
            else _compact_text(raw_mid_term, 1600),
            "entries_covered_count": int(row["entries_covered_count"] or 0),
            "lt_covered_count": int(row["lt_covered_count"] or 0),
            "updated_at": int(row["updated_at"] or 0),
        }
        if (
            item["recent_entries"]
            or item["short_term_memory"]
            or item["mid_term_memory"]
        ):
            result.append(item)
    return result


async def _fetch_conversation_summaries(
    conn: aiosqlite.Connection,
    *,
    username: str,
    character_id: str,
    preferred_conversation_id: str = "",
) -> List[Dict[str, Any]]:
    conn.row_factory = aiosqlite.Row
    rows = await (
        await conn.execute(
            """
            SELECT c.id, c.title, c.summary, c.context_summary_cutoff_timestamp,
                   c.context_summary_cutoff_sequence, c.timestamp, c.updated_at
              FROM conversations c
              JOIN users u ON c.user_id = u.id
             WHERE u.username=?
               AND c.character_id=?
               AND COALESCE(c.is_hidden, 0)=0
               AND COALESCE(c.summary, '') <> ''
             ORDER BY CASE WHEN c.id=? THEN 0 ELSE 1 END,
                      COALESCE(c.timestamp, 0) DESC
             LIMIT 8
            """,
            (username, character_id, preferred_conversation_id),
        )
    ).fetchall()
    return [
        {
            "conversation_id": str(row["id"] or ""),
            "title": _compact_text(row["title"], 80),
            "summary": _compact_text(row["summary"], 1400),
            "timestamp": int(row["timestamp"] or 0),
            "cutoff_timestamp": int(row["context_summary_cutoff_timestamp"] or 0),
            "cutoff_sequence": int(row["context_summary_cutoff_sequence"] or 0),
            "updated_at": str(row["updated_at"] or ""),
        }
        for row in rows
        if _compact_text(row["summary"], 10)
        and not _contains_guest_group_marker(row["summary"])
    ]


async def _fetch_raw_messages(
    conn: aiosqlite.Connection,
    *,
    username: str,
    character_id: str,
    primary_character_name: str = "",
    preferred_conversation_id: str = "",
) -> List[Dict[str, Any]]:
    conn.row_factory = aiosqlite.Row
    params: List[Any] = [username, character_id]
    conversation_filter = ""
    if preferred_conversation_id:
        conversation_filter = " AND c.id=?"
        params.append(preferred_conversation_id)
    params.append(max(MAX_RAW_MESSAGES, MAX_RAW_MESSAGES * 3))
    rows = await (
        await conn.execute(
            f"""
            SELECT c.id AS conversation_id, m.role, m.content, m.timestamp,
                   COALESCE(m.sequence_number, 0) AS sequence_number,
                   COALESCE(m.speaker_character_id, '') AS speaker_character_id,
                   COALESCE(m.speaker_name, '') AS speaker_name
              FROM messages m
              JOIN conversations c ON m.conversation_id = c.id
              JOIN users u ON c.user_id = u.id
             WHERE u.username=?
               AND c.character_id=?
               {conversation_filter}
               AND COALESCE(c.is_hidden, 0)=0
               AND COALESCE(m.is_hidden, 0)=0
               AND m.deleted_at IS NULL
               AND m.role IN ('user', 'assistant')
             ORDER BY COALESCE(m.timestamp, 0) DESC, COALESCE(m.sequence_number, 0) DESC
             LIMIT ?
            """,
            tuple(params),
        )
    ).fetchall()
    result = []
    for row in rows:
        raw_content = str(row["content"] or "")
        clean_content = _strip_guest_group_marker(raw_content)
        if not _compact_text(clean_content, 10):
            continue
        marker_speaker_name = _guest_group_actual_speaker(raw_content)
        result.append(
            {
                "conversation_id": str(row["conversation_id"] or ""),
                "role": str(row["role"] or ""),
                "content": _compact_text(clean_content, 600),
                "timestamp": int(row["timestamp"] or 0),
                "sequence_number": int(row["sequence_number"] or 0),
                "speaker_character_id": str(row["speaker_character_id"] or ""),
                "speaker_name": str(row["speaker_name"] or marker_speaker_name or ""),
                "had_guest_group_marker": _contains_guest_group_marker(raw_content),
            }
        )
    return _filter_raw_messages_for_primary_relationship(
        list(reversed(result)),
        character_id=character_id,
        character_name=primary_character_name,
    )


async def _fetch_source_bundle(
    *,
    username: str,
    character_id: str,
    conversation_id: str = "",
) -> Dict[str, Any]:
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        profile = await _fetch_character_profile(
            conn,
            username=username,
            character_id=character_id,
        )
        memories = await _fetch_memories(
            conn,
            username=username,
            character_id=character_id,
        )
        raw_messages = await _fetch_raw_messages(
            conn,
            username=username,
            character_id=character_id,
            primary_character_name=str(profile.get("name") or ""),
            preferred_conversation_id=conversation_id,
        )
        if conversation_id and not raw_messages:
            raw_messages = await _fetch_raw_messages(
                conn,
                username=username,
                character_id=character_id,
                primary_character_name=str(profile.get("name") or ""),
                preferred_conversation_id="",
            )
        context_memories = await _fetch_context_memories(
            conn,
            username=username,
            character_id=character_id,
            preferred_conversation_id=conversation_id,
        )
        conversation_summaries = await _fetch_conversation_summaries(
            conn,
            username=username,
            character_id=character_id,
            preferred_conversation_id=conversation_id,
        )
    return {
        "username": username,
        "profile": profile,
        "memories": memories,
        "context_memories": context_memories,
        "conversation_summaries": conversation_summaries,
        "raw_messages": raw_messages,
    }


def _format_source_bundle(source: Mapping[str, Any]) -> str:
    username = str(source.get("username") or "").strip()
    profile = source.get("profile") if isinstance(source.get("profile"), Mapping) else {}
    char_id = str(profile.get("id") or "").strip()
    char_name = str(profile.get("name") or "角色").strip() or "角色"
    char_pronoun = _profile_pronoun(profile.get("profile_gender"))
    memories = source.get("memories") if isinstance(source.get("memories"), list) else []
    context_memories = (
        source.get("context_memories")
        if isinstance(source.get("context_memories"), list)
        else []
    )
    conversation_summaries = (
        source.get("conversation_summaries")
        if isinstance(source.get("conversation_summaries"), list)
        else []
    )
    raw_messages = source.get("raw_messages") if isinstance(source.get("raw_messages"), list) else []

    profile_data = profile.get("data") if isinstance(profile, Mapping) else {}
    compact_profile_data = {}
    if isinstance(profile_data, Mapping):
        for key in (
            "name",
            "description",
            "personality",
            "background",
            "scenario",
            "firstMessage",
            "setting",
            "role",
            "occupation",
            "job",
            "profession",
            "character_role",
            "creator_notes",
            "tags",
            "profileGender",
            "profile_gender",
            "gender",
        ):
            if key in profile_data and profile_data.get(key):
                compact_profile_data[key] = profile_data.get(key)

    memory_lines = []
    for memory in memories:
        if not isinstance(memory, Mapping):
            continue
        layer = int(memory.get("layer") or 0)
        period = str(memory.get("period") or "")
        memory_lines.append(
            f"- [layer={layer}{('/' + period) if period else ''}]"
            f"[{memory.get('type') or 'episode'}] {memory.get('content') or ''}"
        )

    context_lines = []
    for memory in context_memories:
        if not isinstance(memory, Mapping):
            continue
        conv = str(memory.get("conversation_id") or "")
        short_term = str(memory.get("short_term_memory") or "").strip()
        mid_term = str(memory.get("mid_term_memory") or "").strip()
        entries = memory.get("recent_entries") if isinstance(memory.get("recent_entries"), list) else []
        if short_term:
            context_lines.append(f"- [conversation={conv}][短期折叠] {short_term}")
        if mid_term:
            context_lines.append(f"- [conversation={conv}][中期折叠] {mid_term}")
        for entry in entries:
            context_lines.append(f"- [conversation={conv}][近期条目] {entry}")

    summary_lines = []
    for summary in conversation_summaries:
        if not isinstance(summary, Mapping):
            continue
        title = str(summary.get("title") or "").strip()
        conv = str(summary.get("conversation_id") or "")
        summary_lines.append(
            f"- [conversation={conv}{('/' + title) if title else ''}] "
            f"{summary.get('summary') or ''}"
        )

    dialogue_lines = []
    for msg in raw_messages:
        if not isinstance(msg, Mapping):
            continue
        if msg.get("role") == "assistant" and not _is_primary_character_speaker(
            msg,
            character_id=char_id,
            character_name=char_name,
            allow_unknown_speaker=True,
        ):
            continue
        role = (
            "USER_TO_CHARACTER｜当前用户对角色说/做"
            if msg.get("role") == "user"
            else f"CHARACTER_TO_USER｜{char_name}（主角色）对当前用户说/做"
        )
        ts = int(msg.get("timestamp") or 0)
        time_label = ""
        if ts > 0:
            try:
                time_label = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            except Exception:
                time_label = ""
        dialogue_lines.append(f"- [{time_label}][{role}] {msg.get('content') or ''}")

    return (
        "[人称与主体规则]\n"
        + "\n".join(
            [
                f"- 当前用户 username={username or '未知'}；页面输出里的“你”只指当前用户。",
                f"- 当前角色是 {char_name}；页面输出里的“对方 / 角色名 / {char_pronoun}”只指角色。",
                "- 原始对话标记 USER_TO_CHARACTER 的内容，是用户对角色说的话或做的动作。",
                "- 原始对话标记 CHARACTER_TO_USER 的内容，是角色对用户说的话或做的动作。",
                "- 普通模式可能含临时群聊；本关系页只允许使用当前用户与当前角色之间的互动。",
                "- 其他角色只能作为背景事实，不能写进关系摘要、共同经历、被记住的小事或建议话题。",
                "- 不能交换主体：谁称呼谁、谁服务谁、谁做饭、谁拥抱、谁是某个职业，都必须按素材方向保留。",
                f"- 如果用户喊 {char_name} “老婆/老公”，应写成“你喊{char_pronoun}老婆/老公”或“你这样称呼{char_name}”，不要反写成角色喊你。",
                f"- 如果 {char_name} 的档案或发言说明{char_pronoun}是水疗师、美容师、老师等职业，职业属于角色，不属于用户。",
                "- 长期记忆中的 {{USER}}、USER、“用户”也都指当前用户。",
            ]
        )
        + "\n\n"
        "[角色档案]\n"
        + json.dumps(
            {
                "name": char_name,
                "bio": profile.get("bio") or "",
                "prompt": profile.get("prompt") or "",
                "profile_gender": profile.get("profile_gender") or "",
                "data": compact_profile_data,
            },
            ensure_ascii=False,
        )[:9000]
        + "\n\n[长期记忆与摘要]\n"
        + ("\n".join(memory_lines) if memory_lines else "（暂无长期记忆）")
        + "\n\n[中短期上下文记忆]\n"
        + ("\n".join(context_lines) if context_lines else "（暂无中短期上下文记忆）")
        + "\n\n[对话上下文摘要]\n"
        + ("\n".join(summary_lines) if summary_lines else "（暂无对话上下文摘要）")
        + "\n\n[最近原始对话节选]\n"
        + ("\n".join(dialogue_lines) if dialogue_lines else "（暂无原始对话）")
    )


async def _call_relationship_llm(
    *,
    username: str,
    character_id: str,
    character_name: str,
    source_text: str,
    current_stage: str,
) -> Optional[Dict[str, Any]]:
    model = model_manager.get_model_for_task("memory") or model_manager.get_active_model()
    if not model:
        logger.warning("⚠️ [RelationshipPage] 无可用模型，跳过生成")
        return None

    stage_options = "\n".join(
        f"- {key}: {RELATIONSHIP_STAGE_LABELS.get(key, key)}"
        for key in sorted(RELATIONSHIP_STAGE_KEYS)
    )
    model_name = model.get("model_name", "")
    reasoning_policy = resolve_software_reasoning_policy(
        "relationship_page",
        model_name=model_name,
        mode="relationship_page",
        active_model=model,
        endpoint=model.get("endpoint", ""),
    )
    system_prompt = (
        "你是 PonyChat 的关系页面内容分析器。你的任务是根据角色设定、长期记忆、"
        "以及一部分原始对话，生成给用户看的关系页面内容。\n"
        "必须客观、具体、温和，不要扮演角色说话，也不要站在系统或模型角度解释。\n"
        "不要暴露内部运行情况：禁止提到系统提示词、数据库、后台任务、模型、记忆条数、消息条数、字段名、JSON、算法。\n"
        "关系阶段必须基于材料判断；证据不足时选 uncertain 或 new_contact，不要为了戏剧性夸大。\n"
        "普通模式素材可能包含临时群聊；关系页只描述当前用户和当前主角色之间的情况。\n"
        "不要把用户与其他角色的称呼、亲密关系、冲突、服务关系或共同经历写成用户与主角色的关系。\n"
        "第三方角色只可作为必要背景，不能成为页面项目的主体，也不能出现在建议话题里。\n"
        "new_contact / uncertain / familiar 不得写成恋爱、暧昧、心动、爱意或伴侣关系，也不要出现爱情符号含义的描述。\n"
        "负面关系可以如实描述冲突、距离和互相伤害，但不要煽动报复；要强调边界、冷静、是否修复等现实状态。\n"
        "非恋爱正向关系可以写师生、可信同伴、家人般照顾，但不要混成恋爱。\n"
        "尽量使用角色名、'对方'、'你们'，不要凭空猜测性别代词。\n"
        "主体归属是最高优先级：USER_TO_CHARACTER 永远是用户对角色，CHARACTER_TO_USER 永远是角色对用户。\n"
        "称呼、职业、服务关系、动作和情绪承接不能互换主体；不确定时宁可写成中性描述，不要猜。\n"
        "self_portrait 只能写角色眼中的用户，不能把角色的职业、身份或设定写成用户的身份。\n"
        "between_portrait 要写双方互动模式，并保留主动/被动方向，例如“你喊角色老婆”不能写成“角色喊你老婆”。\n"
        "只能输出一个 JSON 对象，不能输出 Markdown 或解释。"
    )
    user_prompt = (
        f"当前已知关系阶段（可被证据修正）：{current_stage} / "
        f"{RELATIONSHIP_STAGE_LABELS.get(current_stage, '未知')}\n\n"
        f"允许的关系阶段：\n{stage_options}\n\n"
        "请输出严格 JSON，字段如下：\n"
        "{\n"
        '  "relationship_stage": "允许阶段之一",\n'
        '  "overview": "关系动态摘要，最多90个中文字符；不要写阶段定义",\n'
        '  "mood": "此刻的感觉，最多72个中文字符",\n'
        '  "chips": ["2到4个短标签；每个必须是4个中文字符以内；其中4字标签最多2个；可用“信任”“亲密”“活力四射”“亲密默契”这类组合，不要输出长短语"],\n'
        '  "self_portrait": "角色眼中的用户，最多40个中文字符；只能描述用户，不能写角色职业",\n'
        '  "between_portrait": "你们之间的互动模式，最多40个中文字符；必须保留谁主动",\n'
        '  "remembered_items": ["2到4条小事，每条最多48个中文字符；谁喊谁、谁做什么不能反"],\n'
        '  "timeline_items": ["2到4条共同经历，每条最多48个中文字符；按素材方向写"],\n'
        '  "suggestions": ["2到4个话题，每个最多14个中文字符"]\n'
        "}\n\n"
        "所有字段可以短于上限，但绝对不能超过上限；如果素材很多，只保留最能说明关系的核心信息。\n\n"
        f"素材：\n{source_text}"
    )
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "memory_layer")
    payload["max_completion_tokens"] = int(
        llm_task_float("relationship_page", "max_completion_tokens", 4096) or 4096
    )
    debug_params = {
        "primary_character_id": character_id,
        "primary_character_name": character_name,
    }
    try:
        result = await call_llm_payload(
            payload,
            model,
            task="memory",
            timeout=llm_task_float(
                "relationship_page",
                "timeout_seconds",
                float(GENERATE_TIMEOUT_SECONDS),
            )
            or float(GENERATE_TIMEOUT_SECONDS),
            chat_debug_request={
                "username": username,
                "character_id": character_id,
                "mode": "relationship_page",
                "model_name": model_name,
                "stage": "REQUEST",
                "params": debug_params,
            },
            record_usage="main",
            usage_meter_username=username or None,
            reasoning_policy=reasoning_policy,
        )
    except Exception as exc:
        logger.warning(
            f"⚠️ [RelationshipPage] LLM 调用失败 {username}/{character_id[:8]}: {exc}"
        )
        await save_chat_debug_log(
            username or None,
            character_id or None,
            "relationship_page",
            model_name,
            str(exc),
            "ERROR",
            params=debug_params,
        )
        return None

    parsed = _extract_json_object(result.text or "")
    if not parsed:
        logger.warning(
            f"⚠️ [RelationshipPage] LLM 输出无法解析 {username}/{character_id[:8]}"
        )
        return None
    return parsed


async def refresh_relationship_page(
    *,
    username: str,
    character_id: str,
    conversation_id: str = "",
) -> Dict[str, Any]:
    clean_username = str(username or "").strip()
    clean_character_id = str(character_id or "").strip()
    clean_conversation_id = str(conversation_id or "").strip()
    if not clean_username or not clean_character_id:
        raise ValueError("username and character_id are required")

    await ensure_relationship_page_storage()
    current = await load_relationship_state(clean_username, clean_character_id)
    current_stage = normalize_relationship_stage(
        (current or {}).get("relationship_stage") if current else ""
    )
    source = await _fetch_source_bundle(
        username=clean_username,
        character_id=clean_character_id,
        conversation_id=clean_conversation_id,
    )
    profile = source.get("profile") if isinstance(source.get("profile"), Mapping) else {}
    character_name = str(profile.get("name") or "角色")
    raw_messages = source.get("raw_messages") if isinstance(source.get("raw_messages"), list) else []
    memories = source.get("memories") if isinstance(source.get("memories"), list) else []
    context_memories = (
        source.get("context_memories")
        if isinstance(source.get("context_memories"), list)
        else []
    )
    conversation_summaries = (
        source.get("conversation_summaries")
        if isinstance(source.get("conversation_summaries"), list)
        else []
    )
    generated = await _call_relationship_llm(
        username=clean_username,
        character_id=clean_character_id,
        character_name=character_name,
        source_text=_format_source_bundle(source),
        current_stage=current_stage,
    )

    if not generated:
        if current:
            return current
        generated = {
            "relationship_stage": current_stage,
            "overview": "",
            "mood": "",
            "chips": [],
            "self_portrait": "",
            "between_portrait": "",
            "remembered_items": [],
            "timeline_items": [],
            "suggestions": [],
        }

    generated_stage = normalize_relationship_stage(
        str(generated.get("relationship_stage") or current_stage)
    )
    content = normalize_relationship_page_content(generated, stage=generated_stage)
    if content is None:
        content = default_relationship_page(generated_stage)

    ts = _now_ms()
    source_summary = {
        "version": RELATIONSHIP_PAGE_VERSION,
        "generated_at_ms": ts,
        "raw_message_count": len(raw_messages),
        "memory_count": len(memories),
        "context_memory_count": len(context_memories),
        "conversation_summary_count": len(conversation_summaries),
        "preferred_conversation_id": clean_conversation_id,
    }

    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            INSERT INTO relationship_presence_states (
                id, username, character_id, conversation_id, relationship_stage,
                relationship_page_json, relationship_page_updated_at_ms,
                relationship_page_source_json, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, character_id) DO UPDATE SET
                conversation_id=CASE
                    WHEN excluded.conversation_id <> '' THEN excluded.conversation_id
                    ELSE relationship_presence_states.conversation_id
                END,
                relationship_stage=excluded.relationship_stage,
                relationship_page_json=excluded.relationship_page_json,
                relationship_page_updated_at_ms=excluded.relationship_page_updated_at_ms,
                relationship_page_source_json=excluded.relationship_page_source_json,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                f"rps_{uuid.uuid4().hex}",
                clean_username,
                clean_character_id,
                clean_conversation_id,
                generated_stage,
                json.dumps(content, ensure_ascii=False),
                ts,
                json.dumps(source_summary, ensure_ascii=False),
                ts,
                ts,
            ),
        )
        await conn.commit()

    return (await load_relationship_state(clean_username, clean_character_id)) or {
        "username": clean_username,
        "character_id": clean_character_id,
        "conversation_id": clean_conversation_id,
        "relationship_stage": generated_stage,
        "relationship_page": content,
        "relationship_page_updated_at_ms": ts,
        "relationship_page_source": source_summary,
        "updated_at_ms": ts,
    }


async def _fetch_daily_pairs(limit: int) -> List[Dict[str, str]]:
    await ensure_relationship_page_storage()
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (
            await conn.execute(
                """
                SELECT u.username,
                       c.character_id,
                       (
                           SELECT c2.id
                             FROM conversations c2
                            WHERE c2.user_id = c.user_id
                              AND c2.character_id = c.character_id
                              AND COALESCE(c2.is_hidden, 0)=0
                            ORDER BY COALESCE(c2.timestamp, 0) DESC
                            LIMIT 1
                       ) AS conversation_id,
                       MAX(COALESCE(c.timestamp, 0)) AS latest_at
                  FROM conversations c
                  JOIN users u ON c.user_id = u.id
                 WHERE COALESCE(c.is_hidden, 0)=0
                   AND COALESCE(c.character_id, '') <> ''
                 GROUP BY u.username, c.character_id
                 ORDER BY latest_at DESC
                 LIMIT ?
                """,
                (limit,),
            )
        ).fetchall()
    return [
        {
            "username": str(row["username"] or ""),
            "character_id": str(row["character_id"] or ""),
            "conversation_id": str(row["conversation_id"] or ""),
        }
        for row in rows
        if str(row["username"] or "") and str(row["character_id"] or "")
    ]


async def run_relationship_page_cycle_once(max_pairs: int = MAX_DAILY_PAIRS) -> int:
    pairs = await _fetch_daily_pairs(max_pairs)
    if not pairs:
        logger.info("[RelationshipPage] 无可刷新的关系页面")
        return 0

    logger.info(f"[RelationshipPage] 开始刷新 {len(pairs)} 个关系页面")
    refreshed = 0
    for pair in pairs:
        try:
            await refresh_relationship_page(
                username=pair["username"],
                character_id=pair["character_id"],
                conversation_id=pair.get("conversation_id") or "",
            )
            refreshed += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                f"⚠️ [RelationshipPage] 刷新失败 "
                f"{pair['username']}/{pair['character_id'][:8]}: {exc}"
            )
    logger.info(f"[RelationshipPage] 本轮完成 {refreshed}/{len(pairs)}")
    return refreshed


async def daily_relationship_page_loop() -> None:
    await ensure_relationship_page_storage()
    while True:
        delay = _seconds_until_next_midnight()
        logger.info(
            f"[RelationshipPage] 每日 00:00 自动刷新已注册，"
            f"{delay / 3600:.2f} 小时后运行"
        )
        await asyncio.sleep(delay)
        try:
            await run_relationship_page_cycle_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"⚠️ [RelationshipPage] 每日刷新周期异常: {exc}")
