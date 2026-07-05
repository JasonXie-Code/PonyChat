from __future__ import annotations

import base64
import os
import time
from typing import Any, Dict

import aiosqlite

from .database import Database
from ..config import logger


def _now_ms() -> int:
    return int(time.time() * 1000)


def _cache_ttl_ms() -> int:
    raw = os.getenv("PONYCHAT_CHAT_VOICE_SERVER_CACHE_TTL_SECONDS") or str(7 * 86400)
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        seconds = 7 * 86400
    return max(seconds, 3600) * 1000


def _voice_db_busy_timeout_ms() -> int:
    raw = os.getenv("PONYCHAT_VOICE_DB_BUSY_TIMEOUT_MS") or "1500"
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 1500
    return max(100, min(value, 30000))


def _server_voice_audio_cache_enabled() -> bool:
    raw = os.getenv("PONYCHAT_CHAT_VOICE_SERVER_CACHE_ENABLED") or ""
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def audio_cache_to_transfer(cached: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not cached:
        return None
    audio = cached.get("audio_data") or b""
    if not isinstance(audio, (bytes, bytearray)) or not audio:
        return None
    return {
        "kind": "bytes",
        "mime": cached.get("mime_type") or "audio/mpeg",
        "variant": cached.get("variant") or "default",
        "data_base64": base64.b64encode(bytes(audio)).decode("ascii"),
        "expires_hint_seconds": max(int(_cache_ttl_ms() / 1000), 3600),
    }


async def store_voice_audio_cache(
    db: Database,
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    message_id: str,
    voice_cache_key: str,
    audio_bytes: bytes,
    mime_type: str,
    variant: str | None = None,
) -> None:
    if not _server_voice_audio_cache_enabled():
        return
    key = str(voice_cache_key or "").strip()
    if not key or not audio_bytes:
        return
    now = _now_ms()
    expires_at = now + _cache_ttl_ms()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute(f"PRAGMA busy_timeout = {_voice_db_busy_timeout_ms()}")
        await conn.execute(
            """INSERT INTO message_voice_audio_cache
               (voice_cache_key, username, character_id, conversation_id, message_id,
                mime_type, variant, audio_data, byte_size, created_at, last_delivered_at,
                delivered_count, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?)
               ON CONFLICT(voice_cache_key) DO UPDATE SET
                 username=excluded.username,
                 character_id=excluded.character_id,
                 conversation_id=excluded.conversation_id,
                 message_id=excluded.message_id,
                 mime_type=excluded.mime_type,
                 variant=excluded.variant,
                 audio_data=excluded.audio_data,
                 byte_size=excluded.byte_size,
                 created_at=excluded.created_at,
                 last_delivered_at=NULL,
                 delivered_count=0,
                 expires_at=excluded.expires_at""",
            (
                key,
                str(username or "").strip(),
                str(character_id or "").strip(),
                str(conversation_id or "").strip(),
                str(message_id or "").strip(),
                mime_type or "audio/mpeg",
                variant or "default",
                bytes(audio_bytes),
                len(audio_bytes),
                now,
                expires_at,
            ),
        )
        await conn.commit()


async def load_voice_audio_cache(
    db: Database,
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    message_id: str,
    voice_cache_key: str | None = None,
    mark_delivered: bool = False,
) -> Dict[str, Any] | None:
    if not _server_voice_audio_cache_enabled():
        return None
    await db.init()
    key = str(voice_cache_key or "").strip()
    where = [
        "username = ?",
        "character_id = ?",
        "conversation_id = ?",
        "message_id = ?",
    ]
    params: list[Any] = [
        str(username or "").strip(),
        str(character_id or "").strip(),
        str(conversation_id or "").strip(),
        str(message_id or "").strip(),
    ]
    if key:
        where.append("voice_cache_key = ?")
        params.append(key)
    sql = (
        "SELECT voice_cache_key, mime_type, variant, audio_data, byte_size, "
        "created_at, last_delivered_at, delivered_count, expires_at "
        "FROM message_voice_audio_cache "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY created_at DESC LIMIT 1"
    )
    now = _now_ms()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute(f"PRAGMA busy_timeout = {_voice_db_busy_timeout_ms()}")
            async with conn.execute(sql, tuple(params)) as cur:
                row = await cur.fetchone()
            if not row:
                return None
            expires_at = int(row[8] or 0)
            if expires_at and expires_at < now:
                await conn.execute("DELETE FROM message_voice_audio_cache WHERE voice_cache_key = ?", (row[0],))
                await conn.commit()
                return None
            if mark_delivered:
                await conn.execute(
                    """UPDATE message_voice_audio_cache
                       SET last_delivered_at = ?, delivered_count = delivered_count + 1
                       WHERE voice_cache_key = ?""",
                    (now, row[0]),
                )
                await conn.commit()
            return {
                "voice_cache_key": row[0],
                "mime_type": row[1] or "audio/mpeg",
                "variant": row[2] or "default",
                "audio_data": row[3] or b"",
                "byte_size": int(row[4] or 0),
                "created_at": int(row[5] or 0),
                "last_delivered_at": int(row[6] or 0) if row[6] is not None else None,
                "delivered_count": int(row[7] or 0),
                "expires_at": expires_at or None,
            }
    except Exception as exc:
        logger.warning("[VoiceAudioCache] load failed conv=%s mid=%s: %s", str(conversation_id)[:12], str(message_id)[:12], exc)
        return None


async def acknowledge_voice_audio_cache(
    db: Database,
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    message_id: str,
    voice_cache_key: str,
) -> int:
    if not _server_voice_audio_cache_enabled():
        return 0
    key = str(voice_cache_key or "").strip()
    if not key:
        return 0
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(f"PRAGMA busy_timeout = {_voice_db_busy_timeout_ms()}")
        cur = await conn.execute(
            """DELETE FROM message_voice_audio_cache
               WHERE voice_cache_key = ?
                 AND username = ?
                 AND character_id = ?
                 AND conversation_id = ?
                 AND message_id = ?""",
            (
                key,
                str(username or "").strip(),
                str(character_id or "").strip(),
                str(conversation_id or "").strip(),
                str(message_id or "").strip(),
            ),
        )
        await conn.commit()
        return int(cur.rowcount or 0)


async def purge_expired_voice_audio_cache(db: Database) -> int:
    if not _server_voice_audio_cache_enabled():
        return 0
    await db.init()
    now = _now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(f"PRAGMA busy_timeout = {_voice_db_busy_timeout_ms()}")
        cur = await conn.execute(
            "DELETE FROM message_voice_audio_cache WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        await conn.commit()
        return int(cur.rowcount or 0)
