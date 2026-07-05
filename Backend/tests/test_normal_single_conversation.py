from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

import aiosqlite

from Backend.chat_modules.normal_lifecycle import ensure_normal_lifecycle_table_on_connection
from Backend.db.conversations_dao import ConversationsDAO
from Backend.db.database import Database
from Backend.routes import characters as characters_route
from Backend.routes import messages as messages_route


async def _init_normal_test_db(db: Database) -> None:
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT
            );
            CREATE TABLE characters (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT,
                avatar TEXT,
                prompt TEXT,
                bio TEXT,
                data TEXT,
                is_hidden INTEGER DEFAULT 0
            );
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                character_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                version INTEGER DEFAULT 1,
                summary TEXT,
                context_summary_cutoff_message_id TEXT,
                context_summary_cutoff_timestamp INTEGER,
                context_summary_cutoff_sequence INTEGER,
                is_hidden INTEGER DEFAULT 0,
                hidden_at TIMESTAMP,
                hidden_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                raw_content TEXT,
                image_url TEXT,
                image_thumbnail TEXT,
                timestamp INTEGER NOT NULL,
                message_id TEXT UNIQUE,
                sequence_number INTEGER,
                previous_message_id TEXT,
                quoted_message_json TEXT,
                speaker_character_id TEXT,
                speaker_name TEXT,
                speaker_avatar TEXT,
                suggestions TEXT,
                suggestions_status TEXT DEFAULT 'none',
                client_id TEXT,
                think_translations TEXT,
                generation_duration_ms INTEGER,
                is_hidden INTEGER DEFAULT 0,
                hidden_at TIMESTAMP,
                hidden_reason TEXT,
                deleted_at TIMESTAMP,
                delete_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE message_attachments (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'sticker',
                asset_id TEXT,
                user_sticker_id TEXT,
                url TEXT,
                name TEXT DEFAULT '',
                width INTEGER,
                height INTEGER,
                metadata_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE conversation_archives (
                archive_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                message_count INTEGER DEFAULT 0,
                snapshot_json TEXT NOT NULL,
                reason TEXT DEFAULT 'auto_save',
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                restored_at TIMESTAMP
            );
            CREATE TABLE chat_images (
                filename TEXT PRIMARY KEY,
                data BLOB NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE deletion_audits (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL,
                user_id INTEGER,
                username TEXT,
                character_id TEXT,
                conversation_id TEXT,
                message_id TEXT,
                operator TEXT DEFAULT 'system',
                reason TEXT,
                source TEXT DEFAULT 'api',
                details_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE normal_chat_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                char_memory_json TEXT DEFAULT '[]',
                short_term_memory TEXT DEFAULT '',
                long_term_memory TEXT DEFAULT '',
                entries_covered_count INTEGER DEFAULT 0,
                lt_covered_count INTEGER DEFAULT 0,
                updated_at INTEGER DEFAULT 0,
                UNIQUE(username, character_id, conversation_id)
            );
            CREATE TABLE normal_emotion_state (
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                period_key TEXT NOT NULL,
                baseline_json TEXT DEFAULT '{}',
                reactive_json TEXT DEFAULT '{}',
                emotion_blend TEXT DEFAULT '',
                updated_ms INTEGER DEFAULT 0,
                PRIMARY KEY(username, character_id, conversation_id)
            );
            CREATE TABLE normal_scene_state (
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT '',
                scene_json TEXT DEFAULT '{}',
                scene_card TEXT DEFAULT '',
                updated_ms INTEGER DEFAULT 0,
                source TEXT DEFAULT '',
                PRIMARY KEY(username, character_id, conversation_id)
            );
            CREATE TABLE normal_image_contexts (
                entry_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                created_ms INTEGER NOT NULL,
                user_text TEXT DEFAULT '',
                image_count INTEGER DEFAULT 0,
                should_refuse INTEGER DEFAULT 0,
                image_summary TEXT DEFAULT '',
                visible_text TEXT DEFAULT '',
                identified_entities_json TEXT DEFAULT '[]',
                uncertainty TEXT DEFAULT '',
                error TEXT DEFAULT ''
            );
            CREATE TABLE normal_image_context_state (
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                last_reply_based_on_image INTEGER DEFAULT 0,
                updated_ms INTEGER DEFAULT 0,
                PRIMARY KEY(username, character_id, conversation_id)
            );
            CREATE TABLE character_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                character_id TEXT NOT NULL,
                memory_type TEXT NOT NULL DEFAULT 'episode',
                content TEXT NOT NULL,
                source TEXT DEFAULT 'chat',
                importance INTEGER DEFAULT 5,
                is_active INTEGER DEFAULT 1,
                layer INTEGER DEFAULT 0,
                period TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_recalled_at TIMESTAMP,
                recall_count INTEGER DEFAULT 0
            );
            CREATE TABLE companion_sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                character_id TEXT NOT NULL,
                title TEXT DEFAULT '',
                messages TEXT DEFAULT '[]'
            );
            """
        )
        await conn.commit()


def test_normal_save_enforces_one_visible_conversation(tmp_path: Path):
    async def run() -> None:
        db = Database(str(tmp_path / "ponychat_test.db"))
        await _init_normal_test_db(db)
        dao = ConversationsDAO(db)

        assert await dao.save_conversation(
            "tester",
            "char_a",
            {
                "id": "conv_first",
                "timestamp": 1000,
                "messages": [
                    {"role": "user", "content": "第一条", "timestamp": 1000, "message_id": "m1"}
                ],
            },
        )
        assert await dao.save_conversation(
            "tester",
            "char_a",
            {
                "id": "conv_second",
                "timestamp": 2000,
                "messages": [
                    {"role": "user", "content": "第二条", "timestamp": 2000, "message_id": "m2"}
                ],
            },
        )

        conversations = await dao.load_conversations("tester", "char_a")
        assert len(conversations) == 1
        assert conversations[0]["id"] == "conv_first"
        assert [m["content"] for m in conversations[0]["messages"]] == ["第二条"]

        async with aiosqlite.connect(db.db_path) as conn:
            cur = await conn.execute(
                """SELECT COUNT(*)
                   FROM conversations c
                   JOIN users u ON u.id = c.user_id
                   WHERE u.username = ?
                     AND c.character_id = ?
                     AND COALESCE(c.is_hidden, 0) = 0""",
                ("tester", "char_a"),
            )
            row = await cur.fetchone()
            assert row[0] == 1

    asyncio.run(run())


def test_normal_save_discards_user_images_and_skips_snapshots(tmp_path: Path):
    async def run() -> None:
        db = Database(str(tmp_path / "ponychat_test.db"))
        await _init_normal_test_db(db)
        dao = ConversationsDAO(db)
        image_data = "data:image/png;base64," + ("A" * 1200)

        assert await dao.save_conversation(
            "tester",
            "char_img",
            {
                "id": "conv_img",
                "timestamp": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": f"看看这张图 ![]({image_data}) /chat_images/old.png",
                        "rawContent": f"raw {image_data}",
                        "image_url": image_data,
                        "images": [image_data],
                        "timestamp": 1000,
                        "message_id": "user_img",
                    },
                    {
                        "role": "assistant",
                        "content": "我看完了。",
                        "timestamp": 1001,
                        "message_id": "ai_text",
                    },
                ],
            },
        )

        async with aiosqlite.connect(db.db_path) as conn:
            row = await (
                await conn.execute(
                    """SELECT content, raw_content, image_url, image_thumbnail
                       FROM messages
                       WHERE message_id = ?""",
                    ("user_img",),
                )
            ).fetchone()
            assert row is not None
            assert "data:image" not in row[0]
            assert "/chat_images/" not in row[0]
            assert "data:image" not in (row[1] or "")
            assert row[2] is None
            assert row[3] is None

            archive_row = await (await conn.execute("SELECT COUNT(*) FROM conversation_archives")).fetchone()
            chat_image_row = await (await conn.execute("SELECT COUNT(*) FROM chat_images")).fetchone()
            assert archive_row[0] == 0
            assert chat_image_row[0] == 0

    asyncio.run(run())


def test_reset_character_chat_clears_normal_scene_state(tmp_path: Path, monkeypatch):
    async def run() -> None:
        db = Database(str(tmp_path / "ponychat_test.db"))
        await _init_normal_test_db(db)

        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("INSERT INTO users (id, username, password) VALUES (1, 'tester', 'pw')")
            await conn.execute(
                "INSERT INTO characters (id, user_id, name) VALUES ('char_reset', 1, '柔柔')"
            )
            await conn.execute(
                """INSERT INTO conversations
                   (id, character_id, user_id, title, timestamp, summary, context_summary_cutoff_message_id)
                   VALUES ('conv_reset', 'char_reset', 1, 'reset', 1000, 'old summary', 'old_msg')"""
            )
            await conn.execute(
                """INSERT INTO messages
                   (id, conversation_id, role, content, timestamp, message_id)
                   VALUES ('msg_old', 'conv_reset', 'assistant', '我被关在这里。', 1001, 'm_old')"""
            )
            await conn.execute(
                """INSERT INTO normal_chat_memory
                   (username, character_id, conversation_id, short_term_memory, long_term_memory)
                   VALUES ('tester', 'char_reset', 'conv_reset', '旧短期记忆', '旧长期记忆')"""
            )
            await conn.execute(
                """INSERT INTO normal_emotion_state
                   (username, character_id, conversation_id, period_key, emotion_blend)
                   VALUES ('tester', 'char_reset', 'conv_reset', 'p', '害怕')"""
            )
            await conn.execute(
                """INSERT INTO normal_scene_state
                   (username, character_id, conversation_id, scene_json, scene_card, updated_ms, source)
                   VALUES ('tester', 'char_reset', 'conv_reset', '{}', '旧场景：被关在小房间里', 1002, 'test')"""
            )
            await conn.execute(
                """INSERT INTO normal_image_contexts
                   (entry_id, username, character_id, conversation_id, created_ms, image_summary)
                   VALUES ('img1', 'tester', 'char_reset', 'conv_reset', 1003, '旧图片')"""
            )
            await conn.execute(
                """INSERT INTO normal_image_context_state
                   (username, character_id, conversation_id, last_reply_based_on_image, updated_ms)
                   VALUES ('tester', 'char_reset', 'conv_reset', 1, 1004)"""
            )
            await conn.execute(
                """INSERT INTO character_memories
                   (user_id, character_id, content, is_active)
                   VALUES (1, 'char_reset', '用户把角色关起来了', 1)"""
            )
            await conn.execute(
                """INSERT INTO companion_sessions
                   (id, user_id, character_id, title)
                   VALUES ('sess1', 1, 'char_reset', 'old companion')"""
            )
            await ensure_normal_lifecycle_table_on_connection(conn)
            await conn.execute(
                """INSERT INTO normal_character_lifecycle
                   (username, character_id, conversation_id, state, death_message_id, death_reason, created_at_ms, updated_at_ms)
                   VALUES ('tester', 'char_reset', 'conv_reset', 'dead', 'm_old', 'test death', 1005, 1005)"""
            )
            await conn.commit()

        async def fake_init() -> None:
            return None

        class FakeManager:
            async def broadcast_sync(self, *args, **kwargs):
                return None

        scheduled_opening = {}

        def fake_schedule_opening(*args, **kwargs):
            scheduled_opening["args"] = args
            scheduled_opening["kwargs"] = kwargs
            return object()

        import Backend.chat_modules.opening_greeting as opening_greeting

        monkeypatch.setattr(characters_route, "get_database", lambda: db)
        monkeypatch.setattr(db, "init", fake_init)
        monkeypatch.setattr(characters_route, "manager", FakeManager())
        monkeypatch.setattr(opening_greeting, "schedule_opening_greeting", fake_schedule_opening)

        result = await characters_route.reset_character_chat(
            {"username": "tester", "character_id": "char_reset"},
            x_client_id="test",
        )

        assert result["success"] is True
        assert result["conversation_id"] == "conv_reset"
        assert result["hidden_messages"] == 1
        assert result["hidden_memories"] == 1
        assert result["cleared_scene_states"] == 1
        assert result["reset_lifecycle_states"] == 1
        assert result["opening_greeting"]["scheduled"] is True
        assert scheduled_opening["args"][:2] == ("tester", "char_reset")
        assert scheduled_opening["kwargs"]["conversation_id"] == "conv_reset"
        assert scheduled_opening["kwargs"]["source"] == "reset_character_chat"

        async with aiosqlite.connect(db.db_path) as conn:
            for table in (
                "normal_chat_memory",
                "normal_emotion_state",
                "normal_scene_state",
                "normal_image_contexts",
                "normal_image_context_state",
                "companion_sessions",
            ):
                row = await (
                    await conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE character_id='char_reset'"
                    )
                ).fetchone()
                assert row[0] == 0, table

            hidden_row = await (
                await conn.execute(
                    "SELECT is_hidden, hidden_reason FROM messages WHERE id='msg_old'"
                )
            ).fetchone()
            assert hidden_row == (1, "user_reset")

            memory_row = await (
                await conn.execute(
                    "SELECT is_active FROM character_memories WHERE character_id='char_reset'"
                )
            ).fetchone()
            assert memory_row == (0,)

            conv_row = await (
                await conn.execute(
                    """SELECT summary, context_summary_cutoff_message_id
                       FROM conversations WHERE id='conv_reset'"""
                )
            ).fetchone()
            assert conv_row == ("", None)

            lifecycle_row = await (
                await conn.execute(
                    """SELECT state, death_message_id, death_reason
                       FROM normal_character_lifecycle
                      WHERE username='tester'
                        AND character_id='char_reset'
                        AND conversation_id='conv_reset'"""
                )
            ).fetchone()
            assert lifecycle_row == ("alive", "", "")

    asyncio.run(run())


def test_normal_message_speaker_fields_roundtrip(tmp_path: Path):
    async def run() -> None:
        db = Database(str(tmp_path / "ponychat_test.db"))
        await _init_normal_test_db(db)
        dao = ConversationsDAO(db)

        assert await dao.save_conversation(
            "tester",
            "char_a",
            {
                "id": "conv_speaker",
                "timestamp": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": "碧琪你也说一句。",
                        "timestamp": 1000,
                        "message_id": "u1",
                    },
                    {
                        "role": "assistant",
                        "content": "我来啦！",
                        "timestamp": 1001,
                        "message_id": "b1",
                        "speaker_character_id": "char_b",
                        "speaker_name": "碧琪",
                        "speaker_avatar": "b.png",
                    },
                ],
            },
        )

        conversations = await dao.load_conversations("tester", "char_a")
        messages = conversations[0]["messages"]
        assistant = next(m for m in messages if m["role"] == "assistant")
        assert assistant["speaker_character_id"] == "char_b"
        assert assistant["speaker_name"] == "碧琪"
        assert assistant["speaker_avatar"] == "b.png"

    asyncio.run(run())


def test_normal_message_speaker_fields_survive_client_resave_without_speaker(tmp_path: Path):
    async def run() -> None:
        db = Database(str(tmp_path / "ponychat_test.db"))
        await _init_normal_test_db(db)
        dao = ConversationsDAO(db)

        conversation = {
            "id": "conv_speaker_preserve",
            "timestamp": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": "@碧琪 你也说一句。",
                    "timestamp": 1000,
                    "message_id": "u1",
                },
                {
                    "role": "assistant",
                    "content": "我来啦！",
                    "timestamp": 1001,
                    "message_id": "b1",
                    "speaker_character_id": "char_b",
                    "speaker_name": "碧琪",
                    "speaker_avatar": "b.png",
                },
            ],
        }
        assert await dao.save_conversation("tester", "char_a", conversation)

        # Older clients/local refreshes may send the same assistant message without
        # message-level speaker metadata. That must not erase the stored guest speaker.
        assert await dao.save_conversation(
            "tester",
            "char_a",
            {
                "id": "conv_speaker_preserve",
                "timestamp": 1002,
                "messages": [
                    conversation["messages"][0],
                    {
                        "role": "assistant",
                        "content": "我来啦！",
                        "timestamp": 1001,
                        "message_id": "b1",
                    },
                ],
            },
        )

        conversations = await dao.load_conversations("tester", "char_a")
        assistant = next(m for m in conversations[0]["messages"] if m["role"] == "assistant")
        assert assistant["speaker_character_id"] == "char_b"
        assert assistant["speaker_name"] == "碧琪"
        assert assistant["speaker_avatar"] == "b.png"

    asyncio.run(run())


def test_paged_history_preserves_guest_speaker_fields(tmp_path: Path, monkeypatch):
    async def run() -> None:
        db = Database(str(tmp_path / "ponychat_test.db"))
        await _init_normal_test_db(db)
        dao = ConversationsDAO(db)

        assert await dao.save_conversation(
            "tester",
            "char_a",
            {
                "id": "conv_paged_speaker",
                "timestamp": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": "@碧琪 你也说一句。",
                        "timestamp": 1000,
                        "message_id": "u1",
                        "sequence_number": 1,
                    },
                    {
                        "role": "assistant",
                        "content": "我来啦！",
                        "timestamp": 1001,
                        "message_id": "b1",
                        "sequence_number": 2,
                        "speaker_character_id": "char_b",
                        "speaker_name": "碧琪",
                        "speaker_avatar": "b.png",
                    },
                ],
            },
        )

        monkeypatch.setattr(messages_route, "get_database", lambda: db)
        async def fake_init() -> None:
            return None
        monkeypatch.setattr(db, "init", fake_init)
        async def fake_auth(_token: str) -> str:
            return "tester"
        monkeypatch.setattr(messages_route, "auth_token_verify", fake_auth)

        response = await messages_route.get_conversation_messages_paged(
            username="tester",
            character_id="char_a",
            conversation_id="conv_paged_speaker",
            limit=10,
            x_chat_auth="token",
        )

        assistant = next(m for m in response["messages"] if m["role"] == "assistant")
        assert assistant["speaker_character_id"] == "char_b"
        assert assistant["speaker_name"] == "碧琪"
        assert assistant["speaker_avatar"] == "b.png"

    asyncio.run(run())
