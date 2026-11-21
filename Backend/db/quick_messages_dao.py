import aiosqlite
from typing import Any, Dict, List, Optional

from .database import Database, get_database


class QuickMessagesDAO:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    async def _get_user_id(self, conn: aiosqlite.Connection, username: str) -> Optional[int]:
        async with conn.execute("SELECT id FROM users WHERE username = ?", (username,)) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else None

    async def list_messages(self, username: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db.db_path) as conn:
            user_id = await self._get_user_id(conn, username)
            if user_id is None:
                return []
            async with conn.execute(
                """
                SELECT id, title, content, sort_order, created_at, updated_at
                FROM quick_messages
                WHERE user_id = ?
                ORDER BY sort_order ASC, id ASC
                """,
                (user_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "id": row[0],
                "title": row[1] or "",
                "content": row[2] or "",
                "sort_order": int(row[3] or 0),
                "created_at": row[4],
                "updated_at": row[5],
            }
            for row in rows
        ]

    async def add_message(self, username: str, title: str, content: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db.db_path) as conn:
            user_id = await self._get_user_id(conn, username)
            if user_id is None:
                return None
            async with conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM quick_messages WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
            sort_order = int(row[0] or 0)
            cur = await conn.execute(
                """
                INSERT INTO quick_messages (user_id, title, content, sort_order)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, title, content, sort_order),
            )
            await conn.commit()
            msg_id = int(cur.lastrowid)
        return {
            "id": msg_id,
            "title": title,
            "content": content,
            "sort_order": sort_order,
            "created_at": None,
            "updated_at": None,
        }

    async def update_message(
        self,
        username: str,
        message_id: int,
        title: str,
        content: str,
        sort_order: Optional[int] = None,
    ) -> bool:
        async with aiosqlite.connect(self.db.db_path) as conn:
            user_id = await self._get_user_id(conn, username)
            if user_id is None:
                return False
            if sort_order is None:
                cur = await conn.execute(
                    """
                    UPDATE quick_messages
                    SET title = ?, content = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ?
                    """,
                    (title, content, message_id, user_id),
                )
            else:
                cur = await conn.execute(
                    """
                    UPDATE quick_messages
                    SET title = ?, content = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ?
                    """,
                    (title, content, sort_order, message_id, user_id),
                )
            await conn.commit()
            return cur.rowcount > 0

    async def delete_message(self, username: str, message_id: int) -> bool:
        async with aiosqlite.connect(self.db.db_path) as conn:
            user_id = await self._get_user_id(conn, username)
            if user_id is None:
                return False
            cur = await conn.execute(
                "DELETE FROM quick_messages WHERE id = ? AND user_id = ?",
                (message_id, user_id),
            )
            await conn.commit()
            return cur.rowcount > 0
