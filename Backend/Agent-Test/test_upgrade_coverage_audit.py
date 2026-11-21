"""Regression checks for the formerly reproduced migration gaps.

Use synthetic SQLite and model callbacks only. No account, production data or
network is accessed. Execute explicitly; this is outside the default tests tree.
"""
import asyncio
import importlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_autonomous_normal import normal, history, model_result, turn
from test_unified_agent_memory import db, store, stage, commit, jobs, MemoryConflictError

delivery = importlib.import_module(normal.__package__ + ".autonomous_delivery")
stickers = importlib.import_module(normal.__package__ + ".autonomous_stickers")
reply = importlib.import_module(normal.__package__ + ".autonomous_reply")


def test_guest_can_reference_visible_group_user_message(db):
    from unified_memory_test.participants import grant_turn
    grant_turn(db, username='alice', main_character_id='twilight', speaker_character_id='pinkie',
               conversation_id='c1', message_ids=['m1'])
    guest = store(db, character_id="pinkie", conversation_id="c1")
    assert guest.has_allowed_source("m1")


def test_second_speaker_receives_first_speaker_reply():
    captured = {}

    async def runner(prompt, *args, **kwargs):
        captured.update(json.loads(prompt))
        return model_result()

    asyncio.run(turn(messages=[
        {"role": "user", "message_id": "u1", "content": "两位讨论下去公园还是图书馆"},
        {"role": "assistant", "message_id": "a1", "speaker_character_id": "twilight",
         "content": "我投图书馆一票，碧琪你呢"},
    ], speaker_character_id="pinkie", harness_runner=runner))
    assert "a1" in {row["message_id"] for row in captured["recent_raw_messages"]}


def test_disabling_memory_cancels_preexisting_draft(db):
    pending = store(db)
    stage(pending)
    jobs.configure(db, "alice", "twilight", False)
    with pytest.raises(MemoryConflictError, match="disabled"):
        commit(pending)


def test_current_image_is_sent_to_agent_without_step2_tool():
    image = {"type":"image","mimeType":"image/png","data":"cG5n"}

    async def runner(prompt, model_config, tools, **kwargs):
        assert isinstance(prompt, list) and prompt[1] == image
        assert "inspect_current_images" not in tools
        result = model_result("这是一只蓝色杯子")
        data = json.loads(result['final_response'])
        data['image_observation'] = {'image_summary':'一只蓝色杯子','visible_text':'',
            'identified_entities':['蓝色杯子'],'uncertainty':'','error':''}
        result['final_response'] = json.dumps(data, ensure_ascii=False)
        return result

    result = asyncio.run(turn(messages=[{"role":"user","content":"这张图是什么","message_id":"u1"}],
                              current_image_blocks=[image], harness_runner=runner))
    assert result["llm_api_calls"] == 1


def test_unexecuted_explicit_search_is_not_accepted():
    calls = []

    class Search:
        def register(self, capability):
            async def callback(arguments):
                calls.append(arguments)
                return {"status": "success", "results": []}
            capability("web_search", "search", {"type": "object", "properties": {},
                       "additionalProperties": False}, callback)

    async def runner(*args, **kwargs):
        return model_result("我查到了今天的消息")

    with pytest.raises(normal.NormalAgentError, match="Required tools"):
        asyncio.run(turn(messages=[{"role":"user","content":"请上网搜索今天的新闻","message_id":"u1"}], web_search_tools=Search(), harness_runner=runner))
    assert calls == []


def test_missing_voice_decision_is_repaired_before_acceptance():
    attempts = []
    async def runner(*args, **kwargs):
        attempts.append(args)
        result = model_result('你好')
        data = json.loads(result['final_response'])
        if len(attempts)==1:
            data.pop('voice_reply')
        else:
            data['voice_reply']['enabled'] = True
        result['final_response'] = json.dumps(data)
        return result

    result = asyncio.run(turn(messages=[{"role": "user", "content": "请用语音回答", "message_id": "u1"}],
                              harness_runner=runner))
    request = SimpleNamespace(_normal_planner_result={}, voice_enabled=True)
    delivery.configure_delivery(request, result)
    assert request._normal_planner_result["voice_reply"]["enabled"]


def test_natural_silence_is_representable():
    normal.reply_envelope(json.dumps({"bubble_count": 0, "bubbles": [], "used_facts": [], "no_reply_reason":"用户表示不必回复"}))


def test_sticker_supports_position_between_text_bubbles():
    tools = stickers.AgentStickerTools(None, None)
    registered = {}
    tools.register(lambda name, description, schema, callback: registered.update({name: schema}))
    placement = registered["stage_sticker"]["properties"]["placement"]
    assert "between_text" in placement["enum"] or "after_bubble_index" in registered["stage_sticker"]["properties"]


def test_search_results_do_not_replace_reading_original_evidence(db):
    """G14 is a retrieval-route limitation, not permission to trust unread sources."""
    initial = store(db)
    saved = stage(initial)
    commit(initial)
    pending = store(db, sources=[])
    observed = {}

    async def runner(prompt, model_config, tools, **kwargs):
        found = await tools["search_memory"].callback({"query": "绿茶"})
        observed["found"] = found["memories"]
        return model_result("记得你喜欢绿茶")

    asyncio.run(turn(memory_store=pending, harness_runner=runner))
    assert observed["found"][0]["entry_id"] == saved["entry_id"]
    assert not pending.has_allowed_source("m1")


def test_explicit_memory_request_in_pending_batch_is_enforced(db):
    pending = store(db)

    async def runner(*args, **kwargs):
        return model_result("好的")

    with pytest.raises(normal.NormalAgentError, match='Explicit memory'):
        asyncio.run(turn(messages=[
            {'role':'user','content':'请记住我喜欢绿茶','message_id':'m1'},
            {'role':'user','content':'顺便聊聊别的吧','message_id':'u2'},
        ],memory_store=pending,harness_runner=runner))



def test_reply_count_request_in_pending_batch_is_preserved():
    async def runner(*args, **kwargs):
        return model_result("第一段\n\n第二段\n\n第三段")

    result = asyncio.run(turn(messages=[
        {"role": "user", "content": "请分三段回答", "message_id": "u1"},
        {"role": "user", "content": "介绍一下图书馆", "message_id": "u2"},
    ], harness_runner=runner))
    assert result["required_bubble_count"] == 3


def test_existing_source_edit_invalidates_draft(db):
    pending = store(db)
    stage(pending)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE messages SET content='改为红茶' WHERE message_id='m1'")
    with pytest.raises(MemoryConflictError):
        commit(pending)


def test_guest_cannot_read_unrelated_account(db):
    assert asyncio.run(history.read_history(db, username="bob", character_id="twilight", conversation_id="c1")) == []


def test_conflict_after_valid_reply_leaves_no_memory(db):
    """Store rejects a conflict; SSE handling of it is audited separately in the report."""
    first = store(db)
    saved = stage(first)
    commit(first)
    foreground, background = store(db), store(db)
    stage(foreground, entry_id=saved["entry_id"], expected_version=1, content="用户偏好无糖绿茶")
    stage(background, entry_id=saved["entry_id"], expected_version=1, content="用户饮品偏好为绿茶")
    commit(background)
    with pytest.raises(MemoryConflictError):
        commit(foreground)
    assert store(db).list()[0]["content"] == "用户饮品偏好为绿茶"


def test_literal_punctuation_cleanup_is_shared_not_new_regression():
    """Do not report the shared renderer's punctuation policy as an Agent-only defect."""
    raw, _ = normal.reply_envelope(model_result("你好。 ")["final_response"])
    assert reply.render_envelope(json.loads(raw)) == "你好"


def test_reset_route_with_actual_agent_schema_initialized(tmp_path, monkeypatch):
    """The legacy reset fixture omits the schema that application startup creates."""
    import test_normal_single_conversation as legacy
    original = legacy._init_normal_test_db

    async def initialized(database):
        await original(database)
        jobs.initialize(database.db_path)

    monkeypatch.setattr(legacy, "_init_normal_test_db", initialized)
    legacy.test_reset_character_chat_clears_normal_scene_state(tmp_path, monkeypatch)


def test_agent_default_does_not_downgrade_proactive_relationship(tmp_path, monkeypatch):
    import Backend.long_proactive as proactive
    from Backend.chat_modules.autonomous_service import agent_planner_result, default_agent_delivery_result
    from Backend.proactive_settings import ProactiveSettings

    database = SimpleNamespace(db_path=str(tmp_path / "presence.sqlite"))

    async def initialized():
        pass

    async def settings(username):
        return ProactiveSettings(enabled=True, frequency="normal")

    database.init = initialized
    monkeypatch.setattr(proactive, "get_database", lambda: database)
    monkeypatch.setattr(proactive, "load_proactive_settings", settings)

    async def run():
        await proactive.record_conversation_presence(proactive.PresenceUpdate(
            username="alice", character_id="twilight", conversation_id="c1",
            relationship_stage="committed_partner"))
        # prepare_autonomous_request inherits this field from default_planner_result;
        # run_conversation_persistence forwards it to this shared presence writer.
        await proactive.record_conversation_presence(proactive.PresenceUpdate(
            username="alice", character_id="twilight", conversation_id="c1",
            relationship_stage=agent_planner_result(default_agent_delivery_result(), {"bubble_count":1,"envelope":"{}"})["relationship_stage"]))

    asyncio.run(run())
    with sqlite3.connect(database.db_path) as conn:
        actual = conn.execute("SELECT relationship_stage FROM relationship_presence_states").fetchone()[0]
    assert actual == "committed_partner"


def test_readding_identical_manual_memory_is_idempotent(db):
    from test_unified_agent_memory import service
    first = service.manual(db, "alice", "twilight", content="喜欢无糖绿茶", category="preference")
    again = service.manual(db, "alice", "twilight", content="喜欢无糖绿茶", category="preference")
    assert again["id"] == first["id"]
