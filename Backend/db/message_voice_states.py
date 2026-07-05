from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Iterable

import aiosqlite

from .database import Database
from ..config import logger


VOICE_STATE_FIELDS = (
    "voice_status",
    "voice_id",
    "voice_job_id",
    "voice_cache_key",
    "tts_text",
    "transcript",
    "text_fragments",
    "voice_sentences",
    "voice_error",
)


def normalize_voice_state(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    data = raw or {}
    fragments = data.get("text_fragments") or data.get("textFragments") or []
    if isinstance(fragments, str):
        try:
            parsed = json.loads(fragments)
            fragments = parsed if isinstance(parsed, list) else []
        except Exception:
            fragments = [fragments] if fragments.strip() else []
    if not isinstance(fragments, list):
        fragments = []
    sentences = data.get("voice_sentences") or data.get("voiceSentences") or data.get("sentences") or []
    if isinstance(sentences, str):
        try:
            parsed_sentences = json.loads(sentences)
            sentences = parsed_sentences if isinstance(parsed_sentences, list) else []
        except Exception:
            sentences = []
    if not isinstance(sentences, list):
        sentences = []
    normalized_sentences: list[dict[str, str]] = []
    for item in sentences:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        emotion = str(item.get("emotion_prompt") or item.get("emotionPrompt") or item.get("emotion") or "").strip()
        if text:
            normalized_sentences.append(
                {
                    "text": text,
                    "emotion_prompt": emotion,
                }
            )
    return {
        "voice_status": str(data.get("voice_status") or data.get("status") or "disabled").strip() or "disabled",
        "voice_id": _blank_to_none(data.get("voice_id") or data.get("voiceId")),
        "voice_job_id": _blank_to_none(data.get("voice_job_id") or data.get("voiceJobId")),
        "voice_cache_key": _blank_to_none(data.get("voice_cache_key") or data.get("voiceCacheKey")),
        "tts_text": _blank_to_none(data.get("tts_text") or data.get("ttsText")),
        "transcript": _blank_to_none(data.get("transcript")),
        "text_fragments": [str(x) for x in fragments if str(x or "").strip()],
        "voice_sentences": normalized_sentences,
        "voice_error": _blank_to_none(data.get("voice_error") or data.get("voiceError")),
    }


def attach_voice_state(message: Dict[str, Any], state: Dict[str, Any] | None) -> None:
    if not state:
        return
    normalized = normalize_voice_state(state)
    message["voice_state"] = normalized
    for key in VOICE_STATE_FIELDS:
        value = normalized.get(key)
        if key == "text_fragments":
            if value:
                message[key] = value
        elif value is not None:
            message[key] = value


def _blank_to_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _voice_db_busy_timeout_ms() -> int:
    raw = os.getenv("PONYCHAT_VOICE_DB_BUSY_TIMEOUT_MS") or "1500"
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 1500
    return max(100, min(value, 30000))


async def upsert_voice_state(
    db: Database,
    *,
    conversation_id: str,
    message_id: str,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    normalized = normalize_voice_state(state)
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute(f"PRAGMA busy_timeout = {_voice_db_busy_timeout_ms()}")
        await upsert_voice_state_in_conn(
            conn,
            conversation_id=conversation_id,
            message_id=message_id,
            state=normalized,
        )
        await conn.commit()
    return normalized


async def upsert_voice_state_in_conn(
    conn: aiosqlite.Connection,
    *,
    conversation_id: str,
    message_id: str,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    normalized = normalize_voice_state(state)
    now_ms = int(time.time() * 1000)
    await conn.execute(
        """INSERT INTO message_voice_states
           (conversation_id, message_id, voice_status, voice_id, voice_job_id,
            voice_cache_key, tts_text, transcript, text_fragments_json, voice_sentences_json,
            voice_error, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(conversation_id, message_id) DO UPDATE SET
             voice_status=excluded.voice_status,
             voice_id=excluded.voice_id,
             voice_job_id=excluded.voice_job_id,
             voice_cache_key=excluded.voice_cache_key,
             tts_text=excluded.tts_text,
             transcript=excluded.transcript,
             text_fragments_json=excluded.text_fragments_json,
             voice_sentences_json=excluded.voice_sentences_json,
             voice_error=excluded.voice_error,
             updated_at=excluded.updated_at""",
        (
            conversation_id,
            message_id,
            normalized["voice_status"],
            normalized["voice_id"],
            normalized["voice_job_id"],
            normalized["voice_cache_key"],
            normalized["tts_text"],
            normalized["transcript"],
            json.dumps(normalized["text_fragments"], ensure_ascii=False),
            json.dumps(normalized["voice_sentences"], ensure_ascii=False),
            normalized["voice_error"],
            now_ms,
        ),
    )
    return normalized


async def load_voice_states_for_messages(
    conn: aiosqlite.Connection,
    conversation_id: str,
    message_ids: Iterable[str],
) -> Dict[str, Dict[str, Any]]:
    mids = [str(mid).strip() for mid in message_ids if str(mid or "").strip()]
    if not conversation_id or not mids:
        return {}
    placeholders = ",".join("?" * len(mids))
    try:
        async with conn.execute(
            f"""SELECT message_id, voice_status, voice_id, voice_job_id, voice_cache_key,
                      tts_text, transcript, text_fragments_json, voice_sentences_json, voice_error
               FROM message_voice_states
               WHERE conversation_id = ? AND message_id IN ({placeholders})""",
            (conversation_id, *mids),
        ) as cur:
            rows = await cur.fetchall()
    except Exception as exc:
        logger.warning("⚠️ [VoiceState] load failed conv=%s: %s", conversation_id[:12], exc)
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        fragments: list[str] = []
        try:
            parsed = json.loads(row[7] or "[]")
            if isinstance(parsed, list):
                fragments = [str(x) for x in parsed if str(x or "").strip()]
        except Exception:
            fragments = []
        sentences: list[dict[str, str]] = []
        try:
            parsed_sentences = json.loads(row[8] or "[]")
            if isinstance(parsed_sentences, list):
                for item in parsed_sentences:
                    if isinstance(item, dict) and str(item.get("text") or "").strip():
                        sentences.append(
                            {
                                "text": str(item.get("text") or "").strip(),
                                "emotion_prompt": str(
                                    item.get("emotion_prompt") or item.get("emotionPrompt") or ""
                                ).strip(),
                            }
                        )
        except Exception:
            sentences = []
        out[str(row[0])] = normalize_voice_state(
            {
                "voice_status": row[1],
                "voice_id": row[2],
                "voice_job_id": row[3],
                "voice_cache_key": row[4],
                "tts_text": row[5],
                "transcript": row[6],
                "text_fragments": fragments,
                "voice_sentences": sentences,
                "voice_error": row[9],
            }
        )
    return out


async def load_voice_state(
    db: Database,
    *,
    conversation_id: str,
    message_id: str,
) -> Dict[str, Any] | None:
    mid = str(message_id or "").strip()
    conv_id = str(conversation_id or "").strip()
    if not conv_id or not mid:
        return None
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(f"PRAGMA busy_timeout = {_voice_db_busy_timeout_ms()}")
        states = await load_voice_states_for_messages(conn, conv_id, [mid])
    return states.get(mid)
