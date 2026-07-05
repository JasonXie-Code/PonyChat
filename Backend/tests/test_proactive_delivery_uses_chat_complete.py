from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiosqlite

from Backend import delivery_outbox
from Backend import scheduled_followup


class _TestDb:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self):
        return None


async def _seed_db(db_path: Path) -> None:
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT,
                gender TEXT,
                theme TEXT,
                role TEXT,
                avatar TEXT,
                created_at TEXT,
                last_active TEXT,
                updated_at TEXT
            );
            CREATE TABLE characters (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                raw_content TEXT,
                image_url TEXT,
                timestamp INTEGER,
                message_id TEXT NOT NULL,
                sequence_number INTEGER,
                previous_message_id TEXT,
                deleted_at TIMESTAMP,
                is_hidden INTEGER DEFAULT 0
            );
            CREATE TABLE proactive_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                character_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                content TEXT NOT NULL,
                message_id TEXT,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read_at TIMESTAMP
            );
            CREATE TABLE message_outbox (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                msg_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                delivered_at REAL,
                retry_count INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        await conn.execute(
            """INSERT INTO users
               (id, username, password, gender, theme, role, avatar, created_at, last_active, updated_at)
               VALUES (1, 'tester', '', 'other', 'dark', 'developer', NULL, '', '', '')"""
        )
        await conn.execute("INSERT INTO characters (id, name) VALUES ('char1', '紫悦')")
        await conn.execute(
            """INSERT INTO messages
               (id, conversation_id, role, content, raw_content, timestamp, message_id, sequence_number)
               VALUES ('conv1_msg1', 'conv1', 'assistant', '我想起刚才那件事。', '我想起刚才那件事。',
                       1760000000123, 'msg1', 7)"""
        )
        await conn.commit()


def test_proactive_delivery_records_audit_but_pushes_chat_complete(tmp_path: Path, monkeypatch):
    async def run():
        db_path = tmp_path / "proactive_delivery.db"
        await _seed_db(db_path)
        db = _TestDb(str(db_path))
        monkeypatch.setattr(scheduled_followup, "get_database", lambda: db)
        monkeypatch.setattr(delivery_outbox, "get_database", lambda: db)

        proactive_id = await scheduled_followup._record_proactive_and_push_chat_complete(
            {
                "id": "sf1",
                "username": "tester",
                "character_id": "char1",
                "conversation_id": "conv1",
                "reason": "scheduled_followup",
            },
            "我想起刚才那件事。",
            "msg1",
            voice_result={
                "voice_state": {"voice_status": "ready"},
                "audio_transfer": {"kind": "bytes"},
            },
        )

        assert proactive_id == 1

        async with aiosqlite.connect(str(db_path)) as conn:
            proactive = await (
                await conn.execute(
                    """SELECT trigger_type, content, message_id, is_read, read_at
                       FROM proactive_messages WHERE id=1"""
                )
            ).fetchone()
            rows = await (
                await conn.execute("SELECT msg_type, payload_json FROM message_outbox")
            ).fetchall()

        assert proactive[0] == "scheduled_followup"
        assert proactive[1] == "我想起刚才那件事。"
        assert proactive[2] == "msg1"
        assert proactive[3] == 1
        assert proactive[4] is not None
        assert len(rows) == 1
        assert rows[0][0] == "chat_complete"
        payload = json.loads(rows[0][1])
        assert payload["character_id"] == "char1"
        assert payload["conversation_id"] == "conv1"
        assert payload["message_id"] == "msg1"
        assert payload["preview"] == "我想起刚才那件事。"
        assert payload["mode"] == "normal"
        assert payload["completed_at_ms"] == 1760000000123
        assert payload["message_count"] == 1
        assert payload["assistant_message_ids"] == ["msg1"]
        assert payload["voice_state"] == {"voice_status": "ready"}
        assert payload["audio_transfer"] == {"kind": "bytes"}

    asyncio.run(run())
