# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json

import aiosqlite

from Backend.chat_modules import character as character_module
from Backend.db.character_content_permissions import apply_character_content_creator_permissions
from Backend.db.characters_dao import CharactersDAO
from Backend.db.database import Database
from Backend.db.settings_dao import SettingsDAO
from Backend.db.users_dao import UsersDAO
from Backend.utils import compute_character_hash


def test_creator_can_edit_is_restored_after_stale_false_flag():
    char = {
        "id": "char-1",
        "name": "紫悦nsfw",
        "prompt": "original prompt",
        "owner": "991406477",
        "owner_raw": "991406477",
        "canEdit": False,
    }
    content_hash = compute_character_hash(char)

    apply_character_content_creator_permissions(
        [char],
        {
            content_hash: {
                "id": "char-1",
                "creator": "安",
                "creator_raw": "安",
                "created_at": "2026-06-04T00:00:00",
                "is_official_character": False,
            }
        },
        current_username="安",
    )

    assert char["creator"] == "安"
    assert char["canEdit"] is True


def test_non_creator_cannot_edit_same_content_character():
    char = {
        "id": "char-1",
        "name": "紫悦nsfw",
        "prompt": "original prompt",
        "canEdit": True,
    }
    content_hash = compute_character_hash(char)

    apply_character_content_creator_permissions(
        [char],
        {
            content_hash: {
                "id": "char-1",
                "creator": "安",
                "creator_raw": "安",
                "created_at": "2026-06-04T00:00:00",
                "is_official_character": False,
            }
        },
        current_username="other_user",
    )

    assert char["creator"] == "安"
    assert char["canEdit"] is False


def test_renamed_user_loads_owned_character_as_editable(tmp_path):
    asyncio.run(_run_renamed_user_loads_owned_character_as_editable(tmp_path))


async def _run_renamed_user_loads_owned_character_as_editable(tmp_path):
    db = Database(str(tmp_path / "ponychat.db"))
    await db.init()

    users = UsersDAO(db)
    chars = CharactersDAO(db)
    assert await users.create_user("991406477", "pw")
    assert await chars.save_characters(
        "991406477",
        [
            {
                "id": "twilight-nsfw",
                "name": "紫悦nsfw",
                "prompt": "original prompt",
                "owner": "991406477",
                "owner_raw": "991406477",
                "publicOwner": "991406477",
                "addedFrom": "991406477",
                "canEdit": False,
            }
        ],
    )

    assert await users.rename_user("991406477", "安")

    loaded = await chars.load_characters("安")
    assert len(loaded) == 1
    assert loaded[0]["owner"] == "安"
    assert loaded[0]["owner_raw"] == "安"
    assert loaded[0]["publicOwner"] == "安"
    assert loaded[0]["addedFrom"] == "安"
    assert loaded[0]["creator"] == "安"
    assert loaded[0]["canEdit"] is True


def test_owned_character_author_display_uses_nickname(tmp_path):
    asyncio.run(_run_owned_character_author_display_uses_nickname(tmp_path))


async def _run_owned_character_author_display_uses_nickname(tmp_path):
    db = Database(str(tmp_path / "ponychat.db"))
    await db.init()

    users = UsersDAO(db)
    settings = SettingsDAO(db)
    chars = CharactersDAO(db)
    assert await users.create_user("991406477", "pw")
    assert await settings.save_settings("991406477", {"nickname": "安"})
    assert await chars.save_characters(
        "991406477",
        [
            {
                "id": "twilight-nsfw",
                "name": "紫悦-NSFW2",
                "prompt": "original prompt",
                "owner": "991406477",
                "owner_raw": "991406477",
                "publicOwner": "991406477",
                "addedFrom": "991406477",
                "canEdit": True,
            }
        ],
    )

    loaded = await chars.load_characters("991406477")
    assert len(loaded) == 1
    assert loaded[0]["owner"] == "991406477"
    assert loaded[0]["owner_raw"] == "991406477"
    assert loaded[0]["publicOwner"] == "安"
    assert loaded[0]["addedFrom"] == "安"
    assert loaded[0]["creator"] == "991406477"
    assert loaded[0]["canEdit"] is True


def test_character_prompt_column_is_canonical_for_compat_json(tmp_path, monkeypatch):
    asyncio.run(_run_character_prompt_column_is_canonical_for_compat_json(tmp_path, monkeypatch))


async def _run_character_prompt_column_is_canonical_for_compat_json(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "ponychat.db"))
    await db.init()

    users = UsersDAO(db)
    chars = CharactersDAO(db)
    assert await users.create_user("tester", "pw")
    assert await chars.save_characters(
        "tester",
        [
            {
                "id": "char-1",
                "name": "测试角色",
                "prompt": "canonical prompt",
                "owner": "tester",
                "owner_raw": "tester",
            }
        ],
    )
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute("SELECT prompt, data FROM characters WHERE id = ?", ("char-1",)) as cur:
            saved_prompt, saved_data_json = await cur.fetchone()
    assert saved_prompt == "canonical prompt"
    assert "prompt" not in json.loads(saved_data_json)

    stale_data = {
        "id": "char-1",
        "name": "测试角色",
        "prompt": "stale json prompt",
    }
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            "UPDATE characters SET prompt = ?, data = ? WHERE id = ?",
            ("canonical prompt after edit", json.dumps(stale_data, ensure_ascii=False), "char-1"),
        )
        await conn.commit()

    loaded = await chars.load_characters("tester")
    assert loaded[0]["prompt"] == "canonical prompt after edit"

    monkeypatch.setattr(character_module, "get_database", lambda: db)
    loaded_direct = character_module.load_character_from_db("tester", "char-1")
    assert loaded_direct["prompt"] == "canonical prompt after edit"
