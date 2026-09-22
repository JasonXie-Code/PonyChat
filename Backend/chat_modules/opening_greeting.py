from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional
from types import SimpleNamespace

import aiosqlite

from ..config import logger
from ..db import get_database
from .opening_agent import generate_opening_greeting
from .normal_delivery import DeliveryCancelled, NormalDeliverySession, normal_text_bubble_delay_seconds


_OPENING_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def _opening_lock(username: str, character_id: str) -> asyncio.Lock:
    key = (str(username or ""), str(character_id or ""))
    if key not in _OPENING_LOCKS:
        _OPENING_LOCKS[key] = asyncio.Lock()
    return _OPENING_LOCKS[key]


async def _find_existing_visible_conversation(
    conn: aiosqlite.Connection,
    user_id: int,
    character_id: str,
    conversation_id: Optional[str],
) -> Optional[str]:
    if conversation_id:
        async with conn.execute(
            """SELECT id
               FROM conversations
               WHERE id = ? AND user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0""",
            (conversation_id, user_id, character_id),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return str(row[0])

    async with conn.execute(
        """SELECT id
           FROM conversations
           WHERE user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0
           ORDER BY timestamp DESC
           LIMIT 1""",
        (user_id, character_id),
    ) as cur:
        row = await cur.fetchone()
        return str(row[0]) if row else None


async def _visible_message_count(conn: aiosqlite.Connection, conversation_id: str) -> int:
    async with conn.execute(
        """SELECT COUNT(*)
           FROM messages
           WHERE conversation_id = ?
             AND deleted_at IS NULL
             AND COALESCE(is_hidden, 0) = 0""",
        (conversation_id,),
    ) as cur:
        row = await cur.fetchone()
        return int(row[0] or 0) if row else 0


async def _conversation_id_exists(conn: aiosqlite.Connection, conversation_id: str) -> bool:
    async with conn.execute(
        "SELECT 1 FROM conversations WHERE id = ? LIMIT 1",
        (conversation_id,),
    ) as cur:
        return bool(await cur.fetchone())


async def persist_opening_greeting_bubbles(
    username: str,
    character_id: str,
    bubbles: list[str],
    *,
    conversation_id: Optional[str] = None,
    delivery_session: Optional[NormalDeliverySession] = None,
) -> Optional[str]:
    clean_bubbles = [str(item or "").strip() for item in bubbles if str(item or "").strip()]
    if not clean_bubbles:
        return None

    db = get_database()
    await db.init()
    now_ms = int(time.time() * 1000)

    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        user_id = await db._get_user_id(conn, username)
        conv_id = await _find_existing_visible_conversation(conn, int(user_id), character_id, conversation_id)
        if conv_id and await _visible_message_count(conn, conv_id) > 0:
            return None

        if not conv_id:
            conv_id = conversation_id or f"conv_{now_ms}_{uuid.uuid4().hex[:8]}"
            while await _conversation_id_exists(conn, conv_id):
                conv_id = f"conv_{now_ms}_{uuid.uuid4().hex[:8]}"
            await conn.execute(
                """INSERT OR IGNORE INTO conversations
                   (id, character_id, user_id, title, timestamp, version, summary, is_hidden, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, '', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (conv_id, character_id, user_id, "新对话", now_ms),
            )
        else:
            await conn.execute(
                """UPDATE conversations
                   SET timestamp = ?, is_hidden = 0, hidden_at = NULL, hidden_reason = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (now_ms, conv_id),
            )

        message_ids: list[str] = []
        previous_message_id: Optional[str] = None
        for index, content in enumerate(clean_bubbles):
            message_id = f"opening_{now_ms}_{index}_{uuid.uuid4().hex[:8]}"
            await conn.execute(
                """INSERT INTO messages
                   (id, conversation_id, role, content, raw_content, image_url, timestamp, message_id,
                    sequence_number, previous_message_id, client_id, generation_duration_ms, is_hidden, created_at)
                   VALUES (?, ?, 'assistant', ?, ?, NULL, ?, ?, ?, ?, 'system_opening_greeting', 0, 0, CURRENT_TIMESTAMP)""",
                (
                    message_id,
                    conv_id,
                    content,
                    content,
                    now_ms + index,
                    message_id,
                    index,
                    previous_message_id,
                ),
            )
            message_ids.append(message_id)
            previous_message_id = message_id

        await conn.execute(
            """UPDATE conversations
               SET timestamp = ?, version = COALESCE(version, 0) + 1, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (now_ms + len(clean_bubbles), conv_id),
        )
        if delivery_session is not None:
            request = SimpleNamespace(username=username, character_id=character_id, conversation_id=conv_id)
            # Gate all rows before commit so history refreshes cannot reveal the tail.
            delivery_session.register(request, message_ids, db.db_path)
        await conn.commit()
        return conv_id


async def _opening_message_ids(conversation_id: str) -> list[str]:
    conv_id = str(conversation_id or "").strip()
    if not conv_id:
        return []

    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        async with conn.execute(
            """SELECT message_id
               FROM messages
               WHERE conversation_id = ?
                 AND client_id = 'system_opening_greeting'
                 AND deleted_at IS NULL
                 AND COALESCE(is_hidden, 0) = 0
               ORDER BY timestamp ASC, sequence_number ASC""",
            (conv_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [str(row[0]).strip() for row in rows if row and str(row[0] or "").strip()]


async def _notify_opening_greeting_created(
    username: str,
    character_id: str,
    conversation_id: str,
    bubbles: list[str],
    *,
    delivery_session: NormalDeliverySession,
) -> bool:
    clean_bubbles = [str(item or "").strip() for item in bubbles if str(item or "").strip()]
    if not username or not character_id or not conversation_id or not clean_bubbles:
        return False

    try:
        message_ids = await _opening_message_ids(conversation_id)
        if len(message_ids) != len(clean_bubbles):
            delivery_session.cancelled = True
            return False
        for index, (message_id, bubble) in enumerate(zip(message_ids, clean_bubbles)):
            request = delivery_session.sources[message_id]
            request._deferred_chat_complete_payloads = [{
                "username": username, "character_id": character_id,
                "conversation_id": conversation_id, "message_id": message_id,
                "preview": bubble[:500], "mode": "normal",
                "message_count": 1, "assistant_message_ids": [message_id],
            }]
            delay = normal_text_bubble_delay_seconds(bubble) if index else 0.0
            await delivery_session.release(
                {"type": "assistant_message", "message_id": message_id, "content": bubble},
                request, delay_seconds=delay,
            )
        return True
    except DeliveryCancelled:
        return False
    except Exception as exc:
        logger.warning("[OpeningGreeting] paced delivery failed for %s/%s: %s", username, character_id[:8], exc)
        return False


async def ensure_opening_greeting(
    username: str,
    character_id: str,
    *,
    conversation_id: Optional[str] = None,
) -> dict[str, Any]:
    if not username or not character_id:
        return {"created": False, "reason": "missing_identity"}

    async with _opening_lock(username, character_id):
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            user_id = await db._get_user_id(conn, username)
            existing_conv_id = await _find_existing_visible_conversation(conn, int(user_id), character_id, conversation_id)
            if existing_conv_id and await _visible_message_count(conn, existing_conv_id) > 0:
                return {"created": False, "reason": "conversation_already_has_messages", "conversation_id": existing_conv_id}

        result = await generate_opening_greeting(username, character_id)
        bubbles = result['bubbles']
        if not bubbles:
            return {"created": False, "reason": result["reason"], "bubble_count": 0, "policy_source": "main_agent"}

        delivery_session = NormalDeliverySession()
        try:
            conv_id = await persist_opening_greeting_bubbles(
                username,
                character_id,
                bubbles,
                conversation_id=conversation_id,
                delivery_session=delivery_session,
            )
            notified = False
            if conv_id:
                notified = await _notify_opening_greeting_created(
                    username, character_id, conv_id, bubbles, delivery_session=delivery_session,
                )
        finally:
            await delivery_session.finish()
        return {
            "created": bool(conv_id),
            "reason": result["reason"] if conv_id else "conversation_changed_before_persist",
            "conversation_id": conv_id,
            "bubble_count": len(bubbles) if conv_id else 0,
            "bubbles": bubbles if conv_id else [],
            "notified": notified,
            "policy_reason": result["reason"],
            "policy_source": "main_agent",
        }


def schedule_opening_greeting(
    username: str,
    character_id: str,
    *,
    conversation_id: Optional[str] = None,
    source: str = "unknown",
) -> Optional[asyncio.Task]:
    if not username or not character_id:
        return None

    async def _runner() -> None:
        try:
            result = await ensure_opening_greeting(
                username,
                character_id,
                conversation_id=conversation_id,
            )
            logger.info(
                "[OpeningGreeting] source=%s user=%s char=%s created=%s count=%s reason=%s",
                source,
                username,
                character_id[:8],
                result.get("created"),
                result.get("bubble_count", 0),
                result.get("reason"),
            )
        except Exception as exc:
            logger.warning(
                "[OpeningGreeting] source=%s user=%s char=%s failed: %s",
                source,
                username,
                character_id[:8],
                exc,
            )

    return asyncio.create_task(_runner())
