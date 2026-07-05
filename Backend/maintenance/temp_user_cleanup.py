from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any

import aiosqlite

from ..config import logger
from ..db import get_database


TEMP_USER_RE = re.compile(r"^g_[0-9a-f]{12}$")
TEMP_USER_TTL = timedelta(days=1)
INITIAL_DELAY_SECONDS = 5 * 60
CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60

USERNAME_TABLES: tuple[tuple[str, str], ...] = (
    ("normal_chat_memory", "username"),
    ("normal_emotion_state", "username"),
    ("normal_image_contexts", "username"),
    ("normal_image_context_state", "username"),
    ("scheduled_followups", "username"),
    ("proactive_tasks", "username"),
    ("relationship_presence_states", "username"),
    ("proactive_campaigns", "username"),
    ("proactive_touch_attempts", "username"),
    ("normal_character_lifecycle", "username"),
    ("hall_characters", "publisher_username"),
)


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _table_exists_query(table: str) -> str:
    return "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1"


async def cleanup_temp_users_once(*, older_than: timedelta = TEMP_USER_TTL) -> int:
    """Delete stale guest users like g_c9da41e1db24 and their dependent data."""
    cutoff = datetime.now() - older_than
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT id, username, created_at, last_active
              FROM users
             WHERE username LIKE 'g_%'
            """
        ) as cur:
            rows = await cur.fetchall()

        stale = []
        for row in rows:
            username = str(row["username"] or "")
            if not TEMP_USER_RE.match(username):
                continue
            last_seen = _parse_iso_datetime(row["last_active"]) or _parse_iso_datetime(row["created_at"])
            if last_seen is None or last_seen <= cutoff:
                stale.append((int(row["id"]), username))

        if not stale:
            logger.debug("[TempUserCleanup] no stale guest users")
            return 0

        usernames = [username for _, username in stale]
        placeholders = ",".join("?" for _ in usernames)
        try:
            await conn.execute("BEGIN")
            for table, column in USERNAME_TABLES:
                async with conn.execute(_table_exists_query(table), (table,)) as cur:
                    if not await cur.fetchone():
                        continue
                await conn.execute(
                    f"DELETE FROM {table} WHERE {column} IN ({placeholders})",
                    usernames,
                )
            await conn.execute(
                f"DELETE FROM users WHERE username IN ({placeholders})",
                usernames,
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    logger.info(
        "[TempUserCleanup] deleted %s stale guest users: %s",
        len(usernames),
        ", ".join(usernames[:20]) + (" ..." if len(usernames) > 20 else ""),
    )
    return len(usernames)


async def temp_user_cleanup_loop() -> None:
    await asyncio.sleep(INITIAL_DELAY_SECONDS)
    while True:
        try:
            await cleanup_temp_users_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[TempUserCleanup] cleanup failed: %s", exc)
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
