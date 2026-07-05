from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

galgame_messages = importlib.import_module("Backend.galgame.messages")
character_module = importlib.import_module("Backend.chat_modules.character")
build_galgame_messages = galgame_messages.build_galgame_messages
from Backend.utils import ChatMessage, ChatRequest


def test_galgame_messages_rebuild_history_from_server_state_with_delta_user(monkeypatch):
    seen_game_types: list[str] = []

    async def fake_wait_for_pending_char_memory(*_args, **_kwargs):
        return None

    async def fake_load_galgame_state(_username, _character_id, game_type="galgame"):
        seen_game_types.append(game_type)
        return {
            "score": 61,
            "messages": [
                {"role": "user", "content": "开场选择：图书馆", "message_id": "u1"},
                {
                    "role": "assistant",
                    "rawContent": '{"scene":{"response":"她抬头看向你。"},"score":{"current":55}}',
                    "message_id": "a1",
                },
            ],
            "char_memory": {"entries": []},
        }

    monkeypatch.setattr(galgame_messages, "wait_for_pending_char_memory", fake_wait_for_pending_char_memory)
    monkeypatch.setattr(galgame_messages, "load_galgame_state_async", fake_load_galgame_state)
    monkeypatch.setattr(
        character_module,
        "load_character_prompts",
        lambda *_args, **_kwargs: ("角色设定", "普通补充指令不应进入 galgame"),
    )
    monkeypatch.setattr(character_module, "load_character_from_db", lambda *_args, **_kwargs: {"name": "测试角色"})

    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="galgame",
        messages=[ChatMessage(role="user", content="继续观察她的反应", message_id="u2")],
    )

    result = asyncio.run(
        build_galgame_messages(
            request,
            [{"role": "system", "content": "client context"}, {"role": "user", "content": "继续观察她的反应"}],
        )
    )

    dialogue = [m for m in result if m.get("role") in ("user", "assistant")]
    assert result[0]["role"] == "system"
    assert result[1] == {"role": "system", "content": "client context"}
    assert dialogue[0] == {"role": "user", "content": "开场选择：图书馆"}
    assert dialogue[-1] == {"role": "user", "content": "继续观察她的反应"}
    assert any(m.get("role") == "assistant" and "她抬头看向你" in m.get("content", "") for m in dialogue)
    assert request._galgame_ai_turns_count == 1
    assert request._galgame_char_name == "测试角色"
    assert seen_game_types == ["galgame"]


def test_galgame_lock_delta_user_reads_lock_state_bucket(monkeypatch):
    seen_game_types: list[str] = []

    async def fake_wait_for_pending_char_memory(*_args, **_kwargs):
        return None

    async def fake_load_galgame_state(_username, _character_id, game_type="galgame"):
        seen_game_types.append(game_type)
        return {
            "score": 70,
            "messages": [
                {"role": "user", "content": "锁分开场", "message_id": "lock-u1"},
                {
                    "role": "assistant",
                    "rawContent": '{"scene":{"response":"锁分回复"},"score":{"current":70}}',
                    "message_id": "lock-a1",
                },
            ],
            "char_memory": {"entries": []},
        }

    monkeypatch.setattr(galgame_messages, "wait_for_pending_char_memory", fake_wait_for_pending_char_memory)
    monkeypatch.setattr(galgame_messages, "load_galgame_state_async", fake_load_galgame_state)
    monkeypatch.setattr(character_module, "load_character_prompts", lambda *_args, **_kwargs: ("角色设定", ""))
    monkeypatch.setattr(character_module, "load_character_from_db", lambda *_args, **_kwargs: {"name": "锁分角色"})

    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="galgame_lock",
        messages=[ChatMessage(role="user", content="锁分继续", message_id="lock-u2")],
    )

    result = asyncio.run(build_galgame_messages(request, [{"role": "user", "content": "锁分继续"}]))

    dialogue = [m for m in result if m.get("role") in ("user", "assistant")]
    assert [m["content"] for m in dialogue if m.get("role") == "user"] == ["锁分开场", "锁分继续"]
    assert request._galgame_ai_turns_count == 1
    assert request._galgame_char_name == "锁分角色"
    assert seen_game_types == ["galgame_lock"]
