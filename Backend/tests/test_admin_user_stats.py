from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from Backend.routes.admin import users as admin_users


async def _init_stats_db(db_path: Path) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL
            );
            CREATE TABLE characters (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT,
                is_hidden INTEGER DEFAULT 0
            );
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                character_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                title TEXT,
                timestamp INTEGER,
                is_hidden INTEGER DEFAULT 0
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp INTEGER,
                is_hidden INTEGER DEFAULT 0,
                deleted_at TIMESTAMP
            );
            CREATE TABLE galgame_data (
                character_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                active_session_id TEXT,
                PRIMARY KEY (character_id, user_id)
            );
            CREATE TABLE galgame_messages (
                id TEXT PRIMARY KEY,
                character_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp INTEGER,
                session_id TEXT,
                is_hidden INTEGER DEFAULT 0,
                deleted_at TIMESTAMP
            );
            CREATE TABLE galgame_lock_data (
                character_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                active_session_id TEXT,
                PRIMARY KEY (character_id, user_id)
            );
            CREATE TABLE galgame_lock_messages (
                id TEXT PRIMARY KEY,
                character_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp INTEGER,
                session_id TEXT,
                is_hidden INTEGER DEFAULT 0,
                deleted_at TIMESTAMP
            );
            """
        )

        await conn.executemany(
            "INSERT INTO users (id, username) VALUES (?, ?)",
            [(1, "alice"), (2, "bob")],
        )
        await conn.executemany(
            "INSERT INTO characters (id, user_id, name, is_hidden) VALUES (?, ?, ?, ?)",
            [
                ("normal_char", 1, "normal", 0),
                ("game_char", 1, "game", 0),
                ("lock_char", 1, "lock", 0),
                ("hidden_char", 1, "hidden", 1),
                ("bob_char", 2, "bob", 0),
            ],
        )

        await conn.executemany(
            "INSERT INTO conversations (id, character_id, user_id, title, timestamp, is_hidden) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("conv_visible", "normal_char", 1, "visible", 1, 0),
                ("conv_hidden", "normal_char", 1, "hidden", 2, 1),
                ("conv_hidden_char", "hidden_char", 1, "hidden char", 3, 0),
            ],
        )
        await conn.executemany(
            "INSERT INTO messages (id, conversation_id, role, content, timestamp, is_hidden, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("m1", "conv_visible", "user", "hello", 1, 0, None),
                ("m2", "conv_visible", "assistant", "hi", 2, 0, None),
                ("m_hidden", "conv_visible", "assistant", "hidden", 3, 1, None),
                ("m_deleted", "conv_visible", "assistant", "deleted", 4, 0, "2026-01-01"),
                ("m_hidden_conv", "conv_hidden", "user", "hidden conv", 5, 0, None),
                ("m_hidden_char", "conv_hidden_char", "user", "hidden char", 6, 0, None),
            ],
        )

        await conn.execute(
            "INSERT INTO galgame_data (character_id, user_id, active_session_id) VALUES (?, ?, ?)",
            ("game_char", 1, "gal_active"),
        )
        await conn.executemany(
            "INSERT INTO galgame_messages (id, character_id, user_id, role, content, timestamp, session_id, is_hidden, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("g1", "game_char", 1, "user", "choice", 10, "gal_active", 0, None),
                ("g2", "game_char", 1, "assistant", "scene", 11, "gal_active", 0, None),
                ("g_old", "game_char", 1, "assistant", "old scene", 12, "gal_old", 0, None),
                ("g_hidden", "game_char", 1, "assistant", "hidden", 13, "gal_active", 1, None),
                ("g_deleted", "game_char", 1, "assistant", "deleted", 14, "gal_active", 0, "2026-01-01"),
            ],
        )

        await conn.execute(
            "INSERT INTO galgame_data (character_id, user_id, active_session_id) VALUES (?, ?, ?)",
            ("hidden_char", 1, "hidden_active"),
        )
        await conn.execute(
            "INSERT INTO galgame_messages (id, character_id, user_id, role, content, timestamp, session_id, is_hidden, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("g_hidden_char", "hidden_char", 1, "assistant", "hidden char", 15, "hidden_active", 0, None),
        )

        await conn.execute(
            "INSERT INTO galgame_lock_data (character_id, user_id, active_session_id) VALUES (?, ?, ?)",
            ("lock_char", 1, "lock_active"),
        )
        await conn.executemany(
            "INSERT INTO galgame_lock_messages (id, character_id, user_id, role, content, timestamp, session_id, is_hidden, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("l1", "lock_char", 1, "user", "lock choice", 20, "lock_active", 0, None),
                ("l_hidden", "lock_char", 1, "assistant", "hidden", 21, "lock_active", 1, None),
            ],
        )
        await conn.commit()


def test_batch_user_stats_counts_visible_roles_and_all_visible_message_modes(tmp_path, monkeypatch):
    db_path = tmp_path / "stats.sqlite3"
    asyncio.run(_init_stats_db(db_path))
    monkeypatch.setattr(admin_users, "_DB_PATH", str(db_path))

    stats = asyncio.run(admin_users._batch_user_stats())

    assert stats["alice"]["char_count"] == 3
    assert stats["alice"]["conv_count"] == 1
    assert stats["alice"]["message_count"] == 5
    assert stats["bob"]["char_count"] == 1
    assert stats["bob"]["conv_count"] == 0
    assert stats["bob"]["message_count"] == 0
