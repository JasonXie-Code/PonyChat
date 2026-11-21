from __future__ import annotations

import sqlite3
from typing import Any

import aiosqlite


AUTO_REPLY_CLIENT_ID = "scheduled_followup"
MAX_CONSECUTIVE_PROACTIVE_REPLY_GROUPS = 5
AUTO_REPLY_GROUP_MERGE_WINDOW_MS = 2_000


async def count_consecutive_proactive_reply_groups(
    conn: aiosqlite.Connection,
    conversation_id: str,
    *,
    client_id: str = AUTO_REPLY_CLIENT_ID,
    merge_window_ms: int = AUTO_REPLY_GROUP_MERGE_WINDOW_MS,
) -> int:
    """Count proactive reply rounds since the latest visible user message.

    Proactive replies may be split into multiple bubble rows. Those rows are
    inserted in one transaction with near-identical timestamps, so a short time
    window lets us count the whole split reply as one round without changing the
    message schema.
    """
    conversation_id = str(conversation_id or "").strip()
    if not conversation_id:
        return 0

    try:
        async with conn.execute(
            """
            SELECT COALESCE(sequence_number, 0) AS sequence_number,
                   COALESCE(timestamp, 0) AS timestamp
              FROM messages
             WHERE conversation_id=?
               AND role='user'
               AND deleted_at IS NULL
               AND COALESCE(is_hidden, 0)=0
             ORDER BY COALESCE(sequence_number, 0) DESC,
                      COALESCE(timestamp, 0) DESC,
                      rowid DESC
             LIMIT 1
            """,
            (conversation_id,),
        ) as cur:
            latest_user = await cur.fetchone()

        params: list[Any] = [conversation_id, client_id]
        after_latest_user_sql = ""
        if latest_user:
            user_seq = int(latest_user[0] or 0)
            user_ts = int(latest_user[1] or 0)
            after_latest_user_sql = """
               AND (
                    COALESCE(sequence_number, 0) > ?
                    OR (COALESCE(sequence_number, 0)=? AND COALESCE(timestamp, 0) > ?)
               )
            """
            params.extend([user_seq, user_seq, user_ts])

        async with conn.execute(
            f"""
            SELECT COALESCE(timestamp, 0) AS timestamp
              FROM messages
             WHERE conversation_id=?
               AND role='assistant'
               AND client_id=?
               AND deleted_at IS NULL
               AND COALESCE(is_hidden, 0)=0
               {after_latest_user_sql}
             ORDER BY COALESCE(sequence_number, 0) ASC,
                      COALESCE(timestamp, 0) ASC,
                      rowid ASC
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()
    except sqlite3.OperationalError as exc:
        text = str(exc).lower()
        if "no such table" in text or "no such column" in text:
            return 0
        raise

    groups = 0
    previous_ts: int | None = None
    merge_window_ms = max(0, int(merge_window_ms or 0))
    for row in rows:
        current_ts = int(row[0] or 0)
        if previous_ts is None or current_ts - previous_ts > merge_window_ms:
            groups += 1
        previous_ts = current_ts
    return groups


async def proactive_reply_limit_reached(
    conn: aiosqlite.Connection,
    conversation_id: str,
    *,
    max_groups: int = MAX_CONSECUTIVE_PROACTIVE_REPLY_GROUPS,
) -> dict[str, Any]:
    count = await count_consecutive_proactive_reply_groups(conn, conversation_id)
    limit = max(1, int(max_groups or MAX_CONSECUTIVE_PROACTIVE_REPLY_GROUPS))
    return {
        "reached": count >= limit,
        "count": count,
        "limit": limit,
        "reason": "consecutive_proactive_limit",
    }
