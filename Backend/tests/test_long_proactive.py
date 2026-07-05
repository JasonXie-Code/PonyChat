import asyncio

import aiosqlite

from Backend.long_proactive import (
    ABSENCE_START_SECONDS,
    PresenceUpdate,
    _build_scheduled_task_from_attempt,
    _evaluate_one_presence,
    _prompt_seed,
    _validate_attempt_sendable,
    ensure_long_proactive_tables,
    now_ms,
    record_conversation_presence,
)
from Backend.proactive_settings import ProactiveSettings


class _FakeDb:
    def __init__(self, path):
        self.db_path = str(path)

    async def init(self):
        return None


def test_presence_update_cancels_active_absence_campaign(tmp_path, monkeypatch):
    async def run():
        db = _FakeDb(tmp_path / "long_proactive.db")
        monkeypatch.setattr("Backend.long_proactive.get_database", lambda: db)
        monkeypatch.setattr(
            "Backend.long_proactive.load_proactive_settings",
            lambda username: _async_value(ProactiveSettings(enabled=True, frequency="normal")),
        )
        await ensure_long_proactive_tables()
        ts = now_ms()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute(
                "INSERT INTO proactive_campaigns (id, username, character_id, conversation_id, status, started_at_ms, created_at_ms, updated_at_ms) VALUES ('pc1','tester','char1','conv1','active',?,?,?)",
                (ts, ts, ts),
            )
            await conn.execute(
                "INSERT INTO proactive_touch_attempts (id, campaign_id, username, character_id, conversation_id, due_at_ms, window_start_ms, window_end_ms, status, created_at_ms, updated_at_ms) VALUES ('pta1','pc1','tester','char1','conv1',?,?,?,?,?,?)",
                (ts, ts, ts + 1000, "pending", ts, ts),
            )
            await conn.commit()

        await record_conversation_presence(
            PresenceUpdate(
                username="tester",
                character_id="char1",
                conversation_id="conv1",
                last_user_message_id="u1",
                last_user_at_ms=ts,
                last_user_text="我回来了",
                last_assistant_message_id="a1",
                last_assistant_at_ms=ts + 1,
            )
        )

        async with aiosqlite.connect(db.db_path) as conn:
            campaign = await (await conn.execute("SELECT status, stop_reason FROM proactive_campaigns WHERE id='pc1'")).fetchone()
            attempt = await (await conn.execute("SELECT status, skip_reason FROM proactive_touch_attempts WHERE id='pta1'")).fetchone()
            presence = await (await conn.execute("SELECT state, consecutive_proactive_days FROM relationship_presence_states WHERE username='tester' AND character_id='char1'")).fetchone()
        assert campaign == ("stopped", "user_replied")
        assert attempt == ("cancelled", "user_replied")
        assert presence == ("active_chatting", 0)

    asyncio.run(run())


def test_absence_evaluation_creates_campaign_and_attempt(tmp_path, monkeypatch):
    async def run():
        db = _FakeDb(tmp_path / "long_proactive.db")
        monkeypatch.setattr("Backend.long_proactive.get_database", lambda: db)
        monkeypatch.setattr(
            "Backend.long_proactive.load_proactive_settings",
            lambda username: _async_value(ProactiveSettings(enabled=True, frequency="normal")),
        )
        await ensure_long_proactive_tables()
        ts = now_ms()
        last_user_at = ts - (ABSENCE_START_SECONDS + 60) * 1000
        row = {
            "id": "rps1",
            "username": "tester",
            "character_id": "char1",
            "conversation_id": "conv1",
            "relationship_stage": "familiar",
            "last_user_at_ms": last_user_at,
            "last_assistant_message_id": "a1",
            "absence_started_at_ms": 0,
            "motivation_history_json": "[]",
            "cooldown_until_ms": 0,
            "user_ended_conversation": 0,
        }
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO relationship_presence_states (
                    id, username, character_id, conversation_id, relationship_stage,
                    last_user_at_ms, last_assistant_message_id, motivation_history_json,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)
                """,
                ("rps1", "tester", "char1", "conv1", "familiar", last_user_at, "a1", ts, ts),
            )
            await conn.commit()

        assert await _evaluate_one_presence(row)

        async with aiosqlite.connect(db.db_path) as conn:
            campaign_count = (await (await conn.execute("SELECT COUNT(*) FROM proactive_campaigns WHERE status='active'")).fetchone())[0]
            attempt = await (
                await conn.execute("SELECT status, motivation, pressure_level FROM proactive_touch_attempts LIMIT 1")
            ).fetchone()
            presence = await (
                await conn.execute("SELECT state, absence_started_at_ms FROM relationship_presence_states WHERE id='rps1'")
            ).fetchone()
        assert campaign_count == 1
        assert attempt[0] == "pending"
        assert attempt[1] in {"thought_of_user", "life_share", "care_check", "quiet_waiting", "memory_callback", "reentry_invite"}
        assert attempt[2] == "low"
        assert presence[0].startswith("absent_") or presence[0] == "long_absence"
        assert presence[1] == last_user_at

    asyncio.run(run())


def test_quiet_hour_bypass_is_limited_to_codex_test_attempts(tmp_path, monkeypatch):
    async def run():
        db = _FakeDb(tmp_path / "long_proactive.db")
        monkeypatch.setattr("Backend.long_proactive.get_database", lambda: db)
        monkeypatch.setattr(
            "Backend.long_proactive.load_proactive_settings",
            lambda username: _async_value(ProactiveSettings(enabled=True, frequency="normal")),
        )
        monkeypatch.setattr("Backend.long_proactive._is_quiet_hour", lambda ts: True)
        await ensure_long_proactive_tables()
        ts = now_ms()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password TEXT)")
            await conn.execute("CREATE TABLE characters (id TEXT PRIMARY KEY, user_id INTEGER, name TEXT)")
            await conn.execute(
                "CREATE TABLE conversations (id TEXT PRIMARY KEY, character_id TEXT, user_id INTEGER, title TEXT, timestamp INTEGER, is_hidden INTEGER DEFAULT 0)"
            )
            await conn.execute(
                "CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT, timestamp INTEGER, message_id TEXT, sequence_number INTEGER, deleted_at TEXT, is_hidden INTEGER DEFAULT 0)"
            )
            await conn.execute("INSERT INTO users (id, username, password) VALUES (1, 'tester', 'x')")
            await conn.execute("INSERT INTO characters (id, user_id, name) VALUES ('char1', 1, '角色')")
            await conn.execute(
                "INSERT INTO conversations (id, character_id, user_id, title, timestamp) VALUES ('conv1', 'char1', 1, '角色', ?)",
                (ts,),
            )
            await conn.execute(
                """
                INSERT INTO relationship_presence_states (
                    id, username, character_id, conversation_id,
                    last_user_at_ms, last_assistant_message_id,
                    last_proactive_at_ms, user_ended_conversation,
                    content_signature_history_json, created_at_ms, updated_at_ms
                ) VALUES ('rps1', 'tester', 'char1', 'conv1', ?, 'a1', 0, 0, '[]', ?, ?)
                """,
                (ts - 25 * 60 * 60 * 1000, ts, ts),
            )
            await conn.commit()

        blocked = await _validate_attempt_sendable(
            {
                "id": "pta1",
                "username": "tester",
                "character_id": "char1",
                "conversation_id": "conv1",
                "topic_source": "absence_campaign",
            }
        )
        allowed = await _validate_attempt_sendable(
            {
                "id": "pta2",
                "username": "tester",
                "character_id": "char1",
                "conversation_id": "conv1",
                "topic_source": "codex_test_bypass_quiet",
            }
        )

        assert blocked["ok"] is False
        assert blocked["reason"] == "quiet_hours_deferred"
        assert allowed["ok"] is True

    asyncio.run(run())


def test_long_proactive_seed_keeps_user_absent_context():
    seed = _prompt_seed("thought_of_user", 0, "friend")
    task = asyncio.run(
        _build_scheduled_task_from_attempt(
            {
                "id": "pta1",
                "campaign_id": "pc1",
                "username": "tester",
                "character_id": "char1",
                "conversation_id": "conv1",
                "motivation": "thought_of_user",
                "prompt_seed": seed,
            },
            {"state": {"last_assistant_message_id": "a1", "conversation_id": "conv1", "total_proactive_in_absence": 0}},
        )
    )

    assert "用户仍未回复" in seed
    assert task is not None
    assert "不要描写用户已经回来" in task["seed"]
    assert "不要写成角色已经看到用户回来" in task["seed"]
    assert "不要假设用户已经忙完" in task["seed"]


async def _async_value(value):
    return value
