import asyncio

import pytest

from Backend.chat_modules.personal_preferences import personal_preferences_prompt
from Backend.chat_modules import request_context
from Backend.utils import ChatRequest, ChatMessage


@pytest.mark.parametrize("mode", ["normal", "galgame", "galgame_lock"])
def test_preferences_reach_user_context_for_only_current_account_character_mode(monkeypatch, mode):
    class Users:
        async def update_last_active(self, username):
            pass

    values = {"normal": "短句偏好", "galgame": "冒险偏好", "galgame_lock": "温柔偏好"}

    async def identity(username):
        return {"user": {"gender": "male"}, "settings": {
            "share_with_ai": False,
            "personal_preferences": {"char_a": values, "char_b": {"normal": "其他角色"}},
        } if username == "alice" else {}}

    monkeypatch.setattr(request_context, "get_users_dao", lambda: Users())
    monkeypatch.setattr(request_context, "load_user_identity", identity)
    request = ChatRequest(username="alice", character_id="char_a", mode=mode,
                          messages=[ChatMessage(role="user", content="你好")])
    prompt = asyncio.run(request_context.build_user_context(request, "alice"))
    assert values[mode] in prompt
    assert all(value not in prompt for key, value in values.items() if key != mode)
    assert "其他角色" not in prompt
    assert "优先于角色默认风格" in prompt
    other = asyncio.run(request_context.build_user_context(request, "bob"))
    assert not any(value in other for value in values.values())


@pytest.mark.parametrize("value", [None, {}, [], 42, "", "   "])
def test_empty_and_invalid_preferences_are_not_injected(value):
    assert personal_preferences_prompt({"personal_preferences": {"a": {"normal": value}}}, "a", "normal") == ""


def test_missing_scope_does_not_fall_back_and_prompt_is_bounded():
    settings = {"personal_preferences": {"a": {"normal": "x" * 5000}}}
    assert personal_preferences_prompt(settings, "b", "normal") == ""
    assert personal_preferences_prompt(settings, "a", "galgame") == ""
    assert personal_preferences_prompt(settings, "a", "unknown") == ""
    assert personal_preferences_prompt(settings, "a", "normal").endswith("x" * 4000)
    assert not personal_preferences_prompt(settings, "a", "normal").endswith("x" * 4001)
