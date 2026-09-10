"""Preferences must reach the actual Agent system, beyond background context."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from Backend.chat_modules import autonomous_normal, personal_preferences
from Backend.galgame import harness
from Backend.db.settings_dao import SettingsDAO


def model_result(text="今晚一起去散步吧，我来带路。"):
    body = {"voice_reply": {"enabled": False, "reason": "text"},
            "reply_language": {"language": "auto", "reason": "current"},
            "bubble_count": 1, "bubbles": [{"index": 1, "type": "text", "purpose": "answer_user",
            "parts": [{"kind": "speech", "text": text}]}], "used_facts": []}
    return {"finish_reason": "completed", "final_response": json.dumps(body, ensure_ascii=False),
            "usage": {}, "llm_api_calls": 1}


@pytest.mark.parametrize("memory_enabled", [False, True])
def test_normal_service_loads_effective_speaker_preferences_before_memory(monkeypatch, memory_enabled):
    from Backend.chat_modules import autonomous_service, normal_speaker

    class ScopeReached(Exception):
        pass

    saved = {"personal_preferences": {"invited-speaker": {"normal": "主动邀请"}}}

    async def settings(self, username):
        assert username == "alice"
        return saved

    def preferences(settings, character_id, mode, *, compact=False):
        assert settings is saved
        assert (character_id, mode) == ("invited-speaker", "normal")
        assert compact is True
        raise ScopeReached

    monkeypatch.setattr(normal_speaker, "effective_speaker_character_id", lambda request: "invited-speaker")
    monkeypatch.setattr(SettingsDAO, "load_settings", settings)
    monkeypatch.setattr(personal_preferences, "personal_preferences_prompt", preferences)
    request = SimpleNamespace(username="alice", character_id="main", memory_enabled=memory_enabled)
    with pytest.raises(ScopeReached):
        asyncio.run(autonomous_service.prepare_autonomous_request(
            request, {}, profile="", environment="", image_urls=[]))


@pytest.mark.parametrize("retry", [False, True])
def test_normal_preferences_are_system_instructions_even_without_memory(retry):
    systems = []
    preference = personal_preferences.personal_preferences_prompt(
        {"personal_preferences": {"shy": {"normal": "主动邀请我，不要等我推动。"}}}, "shy", "normal")

    async def runner(prompt, config, tools, **kwargs):
        systems.append(kwargs["system_prompt"])
        assert json.loads(prompt)["memory_enabled"] is False
        if retry and len(systems) == 1:
            return model_result() | {"final_response": "invalid envelope"}
        return model_result()

    asyncio.run(autonomous_normal.run_autonomous_turn(
        messages=[{"role": "user", "content": "今晚有空。", "message_id": "latest"}],
        character_profile="内向，害羞，总是等别人邀请。", environment="图书馆", model_config={},
        personal_preferences=preference, harness_runner=runner))
    assert len(systems) == (2 if retry else 1)
    for system in systems:
        assert preference in system
        assert system.index(preference) > system.index("根据给定角色身份")
        assert "按个人偏好改变实际行为" in system


@pytest.mark.parametrize("mode", ["normal", "galgame", "galgame_lock"])
def test_loader_uses_exact_account_character_mode(monkeypatch, mode):
    async def settings(self, username):
        return {"personal_preferences": {"shy": {
            "normal": "普通主动", "galgame": "游戏主动", "galgame_lock": "锁分主动"},
            "other": {"normal": "其他角色"}}} if username == "alice" else {}

    monkeypatch.setattr(SettingsDAO, "load_settings", settings)
    prompt = asyncio.run(personal_preferences.load_personal_preferences_prompt("alice", "shy", mode))
    assert {"normal": "普通主动", "galgame": "游戏主动", "galgame_lock": "锁分主动"}[mode] in prompt
    assert "其他角色" not in prompt
    assert not asyncio.run(personal_preferences.load_personal_preferences_prompt("bob", "shy", mode))
    assert not asyncio.run(personal_preferences.load_personal_preferences_prompt("alice", "missing", mode))
    assert not asyncio.run(personal_preferences.load_personal_preferences_prompt(None, "shy", mode))


@pytest.mark.parametrize("mode", ["galgame", "galgame_lock"])
@pytest.mark.parametrize("stage", ["initial", "continuation", "retry"])
def test_game_preferences_survive_minimal_agent_payload(monkeypatch, mode, stage):
    captured = {}

    async def preferences(username, character_id, scope_mode):
        assert (username, character_id, scope_mode) == ("alice", "shy", mode)
        return "优先执行个人偏好：主动邀请。"

    async def runner(prompt, config, tools, **kwargs):
        captured.update(kwargs)
        assert set(tools) == ({'preview_lock_state'} if mode == 'galgame_lock' else set())
        data = json.loads(prompt)
        assert data['is_initial'] == (stage == 'initial')
        assert data['context'] == ['当前阶段格式要求']
        if stage == 'retry': assert data['validation_feedback'] == '字段缺失'
        assert len(data["ordered_messages"]) == 1
        return {"finish_reason": "completed", "final_response": "{}", "usage": {}}

    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(harness, "load_personal_preferences_prompt", preferences)
    monkeypatch.setattr(harness, "run_harness_turn", runner)
    monkeypatch.setattr(harness, "_save_chat_debug_if_requested", noop)
    monkeypatch.setattr(harness, "_apply_usage_metering", noop)
    asyncio.run(harness.run_game_agent(
        {"messages": [{"role": "system", "content": "当前阶段格式要求"},
                      {"role": "user", "content": "已精简的阶段输入，无背景资料"}]}, {},
        mode=mode, timeout=10,
        request=SimpleNamespace(_galgame_is_initial=stage == 'initial', _galgame_state={}, _galgame_char_profile=''),
        validation_feedback='字段缺失' if stage == 'retry' else '',
        chat_debug_request={"username": "alice", "character_id": "shy", "stage": stage}))
    assert captured["system_prompt"].endswith("优先执行个人偏好：主动邀请。")
    assert captured["max_tool_calls"] == (4 if mode == 'galgame_lock' else 0)
