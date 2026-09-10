import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from Backend.galgame import handler, harness
from Backend.galgame.output_contract import game_output_contract, POSE_MAX_CHARS, POSITION_MAX_CHARS


def test_contract_matches_validator_and_complete_lock_objects():
    guide = game_output_contract("galgame_lock")
    assert set(handler.REQUIRED_TOP_FIELDS) <= set(guide["required_top_fields"])
    assert guide["required_object_keys"]["scene"] == list(handler.REQUIRED_SCENE_FIELDS)
    assert guide["compact_text_max_chars"]["character_pose"] == POSE_MAX_CHARS == 10
    assert guide["compact_text_max_chars"]["player_position"] == POSITION_MAX_CHARS == 16
    assert '我=当前角色，你=当前玩家' in guide['scene_perspective']
    for key in ("char_vitals", "char_mood", "organ_fill"):
        assert key in guide["required_top_fields"]
        assert guide["required_object_keys"][key]
    guide["required_top_fields"].clear()
    assert game_output_contract("galgame_lock")["required_top_fields"]
    assert "char_vitals" not in game_output_contract("galgame")["required_top_fields"]


@pytest.mark.parametrize("initial,feedback", [(True, ""), (False, ""), (False, "character_pose(len<=10)")])
def test_contract_is_sent_on_first_continuation_and_retry(monkeypatch, initial, feedback):
    seen = []
    async def run(prompt, *args, **kwargs):
        seen.append((json.loads(prompt), kwargs["system_prompt"]))
        return {"finish_reason": "completed", "final_response": "{}"}
    async def noop(*args, **kwargs): pass
    monkeypatch.setattr(harness, "run_harness_turn", run)
    monkeypatch.setattr(harness, "_apply_usage_metering", noop)
    state = {"score": 40, "character_pose": "原来较长的姿态描述不应被服务端截断"}
    original = copy.deepcopy(state)
    request = SimpleNamespace(_galgame_state=state, _galgame_is_initial=initial)
    asyncio.run(harness.run_game_agent({"messages": [{"role": "user", "content": "继续"}]}, {},
        request=request, mode="galgame_lock", timeout=30, validation_feedback=feedback, previous_output="{}"))
    data, system = seen[0]
    assert len(seen) == 1
    assert data["output_contract"] == game_output_contract("galgame_lock")
    assert "最多10个字符" in system and "最多16个字符" in system
    assert "未变化" in system and "完整快照" in system
    assert state == original


@pytest.mark.parametrize("field,size", [("character_pose", 11), ("player_pose", 11),
                                       ("character_position", 17), ("player_position", 17)])
def test_validator_still_rejects_overlong_labels(field, size):
    guide = game_output_contract("galgame")
    value = {key: "正常" for key in guide["required_top_fields"]}
    value.update(score={"current": 40, "change": 0, "status": "playing"},
                 scene={key: "场景" for key in guide["required_object_keys"]["scene"]},
                 event_flags={key: False for key in guide["required_object_keys"]["event_flags"]},
                 memory_tags=["测试"], suggested_options=[{"label": "问好", "type": "dialogue", "tone": "温和"}])
    value[field] = "字" * size
    request = SimpleNamespace(mode="galgame")
    result = asyncio.run(handler._handle_galgame_response(request, json.dumps(value), []))
    assert result["status"] == "retry"
    assert field + "(len<=" in result["error"]


def test_validator_still_rejects_story_only_continuation():
    result = asyncio.run(handler._handle_galgame_response(SimpleNamespace(mode="galgame"),
        json.dumps({"score": {"current": 40, "change": 0, "status": "playing"},
                    "scene": {}, "suggested_options": []}), []))
    assert result["status"] == "retry"
    assert "character_pose" in result["error"]


@pytest.mark.parametrize('metadata', [{'_options_perspective': '内部提醒'},
    {'options_perspective': '内部提醒'}, {'_options_perspective': '内部提醒', 'label': '我已倒地不起'},
    {'options_perspective': '内部提醒', 'label': '我已倒地不起'},
    {'label': '视角提醒', 'type': 'dialogue', 'tone': '提示'}, '视角提醒'])
def test_internal_option_perspective_never_becomes_a_player_option(monkeypatch, metadata):
    from Backend.utils import ChatRequest
    from Backend import delivery_outbox
    guide = game_output_contract('galgame')
    value = {key: '正常' for key in guide['required_top_fields']}
    option = {'label': '安静守候', 'type': 'action', 'tone': '平静'}
    value.update(score={'current': 40, 'change': 0, 'status': 'playing'},
        scene={key: '场景' for key in guide['required_object_keys']['scene']},
        event_flags={key: False for key in guide['required_object_keys']['event_flags']},
        memory_tags=['测试'], suggested_options=[metadata, option])
    saved = {}
    async def load(*args, **kwargs): return {'score': 40, 'messages': []}
    async def save(username, character_id, data, **kwargs):
        saved.update(data)
        return True
    async def noop(*args, **kwargs): pass
    monkeypatch.setattr(handler, 'load_galgame_state_async', load)
    monkeypatch.setattr(handler, 'save_galgame_state_async', save)
    monkeypatch.setattr(handler, 'schedule_char_memory_update_after_turn', lambda **kwargs: None)
    monkeypatch.setattr(handler.manager, 'broadcast_to_user', noop)
    monkeypatch.setattr(handler.manager, 'broadcast_sync', noop)
    monkeypatch.setattr(delivery_outbox, 'enqueue_chat_complete', noop)
    req = ChatRequest(username='synthetic', character_id='synthetic', mode='galgame', messages=[])
    result = asyncio.run(handler._handle_galgame_response(req, json.dumps(value), []))
    assert result['status'] == 'success', result
    assert result['data']['suggested_options'] == [option]
    assistant = saved['messages'][-1]
    assert assistant['galgameOptions'] == [option]
    assert json.loads(assistant['rawContent'])['suggested_options'] == [option]
