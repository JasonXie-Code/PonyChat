"""
message_outbox：客户端推送送达确认与离线补推
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List

import aiosqlite

from .database import Database
from ..config import logger


class OutboxDAO:
    def __init__(self, db: Database):
        self._db = db

    async def enqueue(self, user_id: int, msg_type: str, payload: Dict[str, Any]) -> str:
        oid = str(uuid.uuid4())
        now = time.time()
        payload_json = json.dumps(payload, ensure_ascii=False)
        async with aiosqlite.connect(self._db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute(
                """INSERT INTO message_outbox (id, user_id, msg_type, payload_json, created_at, delivered_at, retry_count)
                   VALUES (?, ?, ?, ?, ?, NULL, 0)""",
                (oid, user_id, msg_type, payload_json, now),
            )
            await conn.commit()
        return oid

    async def ack(self, user_id: int, outbox_ids: List[str]) -> int:
        if not outbox_ids:
            return 0
        now = time.time()
        placeholders = ",".join("?" * len(outbox_ids))
        sql = (
            f"UPDATE message_outbox SET delivered_at=? "
            f"WHERE user_id=? AND delivered_at IS NULL AND id IN ({placeholders})"
        )
        params = [now, user_id] + list(outbox_ids)
        async with aiosqlite.connect(self._db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            cur = await conn.execute(sql, params)
            await conn.commit()
            try:
                return cur.rowcount if cur.rowcount is not None else 0
            except Exception:
                return len(outbox_ids)

    async def list_undelivered(self, user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self._db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            async with conn.execute(
                """SELECT id, msg_type, payload_json, created_at FROM message_outbox
                   WHERE user_id=? AND delivered_at IS NULL ORDER BY created_at ASC LIMIT ?""",
                (user_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r[2]) if r[2] else {}
            except Exception:
                payload = {}
            out.append(
                {
                    "outbox_id": r[0],
                    "msg_type": r[1],
                    "payload": payload,
                    "created_at": r[3],
                }
            )
        return out
