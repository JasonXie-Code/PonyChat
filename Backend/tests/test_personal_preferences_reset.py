"""Reset real conversation/game state while retaining independent user settings."""
import asyncio
import json
import sqlite3

import pytest


PREFERENCES = {"personal_preferences": {"char_reset": {
    "normal": "简短", "galgame": "冒险", "galgame_lock": "温柔",
}}}


def test_normal_reset_keeps_all_personal_preferences(tmp_path, monkeypatch):
    from Backend.tests import test_normal_single_conversation as existing

    original = existing._init_normal_test_db

    async def initialized(db):
        await original(db)
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("CREATE TABLE user_settings (user_id INTEGER PRIMARY KEY, settings TEXT)")
            conn.execute("INSERT INTO user_settings VALUES (1, ?)", (json.dumps(PREFERENCES),))

    monkeypatch.setattr(existing, "_init_normal_test_db", initialized)
    existing.test_reset_character_chat_clears_normal_scene_state(tmp_path, monkeypatch)
    with sqlite3.connect(tmp_path / "ponychat_test.db") as conn:
        assert json.loads(conn.execute("SELECT settings FROM user_settings").fetchone()[0]) == PREFERENCES


@pytest.mark.parametrize("mode", ["galgame", "galgame_lock"])
def test_game_reset_keeps_all_personal_preferences(tmp_path, monkeypatch, mode):
    from Backend.db.database import Database
    from Backend.routes import galgame

    db = Database(str(tmp_path / "reset.db"))
    with sqlite3.connect(db.db_path) as conn:
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
            INSERT INTO users VALUES (1, 'tester');
            CREATE TABLE user_settings (user_id INTEGER PRIMARY KEY, settings TEXT);
        """)
        conn.execute("INSERT INTO user_settings VALUES (1, ?)", (json.dumps(PREFERENCES),))
        conn.execute(f"""CREATE TABLE {mode}_data (
            character_id TEXT PRIMARY KEY, user_id INTEGER, score INTEGER,
            status TEXT, version INTEGER, force_clear INTEGER,
            active_session_id TEXT, updated_at TEXT)""")
        conn.execute(f"INSERT INTO {mode}_data (character_id, user_id, score) VALUES ('char_reset', 1, 80)")

    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(db, "init", noop)
    monkeypatch.setattr(galgame, "get_database", lambda: db)
    monkeypatch.setattr(galgame.manager, "broadcast_sync", noop)
    result = asyncio.run(galgame.reset_galgame({
        "username": "tester", "character_id": "char_reset", "game_type": mode,
    }, x_client_id="test"))
    assert result["success"]
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute(f"SELECT score FROM {mode}_data").fetchone()[0] == 40
        assert json.loads(conn.execute("SELECT settings FROM user_settings").fetchone()[0]) == PREFERENCES
