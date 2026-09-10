"""Autonomous turn tests load only stdlib modules, without starting Backend."""
import ast
import asyncio
import importlib
import json
import re
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = "autonomous_normal_under_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "chat_modules")]
sys.modules[PACKAGE] = package
normal = importlib.import_module(PACKAGE + ".autonomous_normal")
history = importlib.import_module(PACKAGE + ".autonomous_history")
memory = importlib.import_module(PACKAGE + ".agent_memory_store")
WHEN = "2026-09-06T15:00:00+08:00"


def run(coroutine):
    return asyncio.run(coroutine)


def model_result(text="我在这里。", finish="completed"):
    paragraphs = text.split("\n\n")
    data = {"voice_reply": {"enabled": False, "reason": "text conversation"},
            "followup_decision": {"enabled": False, "reason": "本条已答完，没有新的续接内容"},
            "reply_language": {"language": "auto", "reason": "current language"},
            "bubble_count": len(paragraphs), "bubbles": [
        {"index": i, "type": "text", "purpose": "answer_user", "parts": [{"kind": "speech", "text": p}]}
        for i, p in enumerate(paragraphs, 1)], "used_facts": []}
    return {"finish_reason": finish, "final_response": json.dumps(data, ensure_ascii=False), "usage": {}, "llm_api_calls": 1}


def test_autonomous_system_defaults_to_no_dash_in_visible_replies():
    assert '默认不要使用破折号' in normal.SYSTEM
    assert '必须用第二人称“你”指用户' in normal.SYSTEM
    assert '无论当前用户是动作主体、动作对象、心理所想对象还是回忆对象' in normal.SYSTEM
    assert '（你抱住我的那一刻，我一下安静下来）' in normal.SYSTEM
    assert '以用户明确要求为准' in normal.SYSTEM
    assert normal.DEFAULT_CHARACTER_REPLY_STYLE_PROMPT in normal.SYSTEM
    assert '主体与对象换位时，仍保持此人称' in normal.OUTPUT_CONTRACT


def test_missing_final_container_closer_does_not_call_model_again():
    calls = []

    async def runner(prompt, config, tools, **kwargs):
        calls.append(prompt)
        result = model_result('我望着你。')
        result['final_response'] = result['final_response'][:-1]
        return result

    result = run(normal.run_autonomous_turn(
        messages=[{'role': 'user', 'content': '你好', 'message_id': 'u1'}],
        character_profile='温和', environment='', model_config={}, harness_runner=runner))
    assert len(calls) == 1
    assert result['json_closers_recovered'] is True
    assert result['output_format_repairs'] == 0
    assert json.loads(result['envelope'])['bubbles'][0]['parts'][0]['text'] == '我望着你。'


def test_personal_preferences_follow_default_style_prompt(monkeypatch):
    captured = {}

    async def runner(_prompt, _config, _tools, **kwargs):
        captured.update(kwargs)
        return model_result()

    result = asyncio.run(normal.run_autonomous_turn(
        messages=[{'role': 'user', 'content': '你好', 'message_id': 'u1'}],
        character_profile='角色', environment='环境', model_config={},
        personal_preferences='用户偏好：使用第三人称括号描写。', harness_runner=runner))

    assert result['bubble_count'] == 1
    system = captured['system_prompt']
    assert system.index('默认不要使用破折号') < system.index('用户偏好：使用第三人称括号描写。')


def make_store(path, sources=("latest",)):
    # This suite exercises the legacy transaction fixture; score persistence is
    # verified against the production unified store in test_memory_importance.
    class TransactionFixture(memory.AgentMemoryStore):
        def stage(self, *, importance=None, **kwargs):
            return super().stage(**kwargs)
    return TransactionFixture(path, username="alice", character_id="twilight",
                                  conversation_id="c1", allowed_sources=sources)


def turn(**kwargs):
    args = {"messages": [{"role": "user", "content": "我喜欢红茶", "message_id": "latest"}],
            "character_profile": "暮光闪闪：独角兽", "environment": "傍晚，窗边", "model_config": {}}
    return normal.run_autonomous_turn(**(args | kwargs))


def stage_args(source="latest"):
    return {"kind": "fact", "content": "用户喜欢红茶", "source_message_ids": [source], "occurred_at": WHEN, "importance": 7}


def test_simple_chat_needs_no_tool_calls_and_gets_raw_context():
    observed = {}
    messages = [{"role": "assistant", "content": f"原始内容 {i}", "message_id": str(i)} for i in range(40)]
    messages += [{"role": "user", "content": "晚安！", "message_id": "latest"},
                 {"role": "user", "content": "隐藏内容", "message_id": "hidden", "isHidden": True}]

    async def runner(prompt, model_config, tools, **kwargs):
        observed.update(json.loads(prompt))
        assert tools == {}
        return model_result("晚安！\n\n愿你睡个好觉。")

    result = run(turn(messages=messages, harness_runner=runner))
    assert observed["character_profile"] == "暮光闪闪：独角兽"
    assert observed["environment"] == "傍晚，窗边"
    assert observed["latest_user_message"]["content"] == "晚安！"
    assert [m["message_id"] for m in observed["recent_raw_messages"]] == [str(i) for i in range(10, 40)]
    assert observed["memory_enabled"] is False
    assert observed["expression_context"]["recent_10"]["observed_turns"] == 1
    envelope = json.loads(result["envelope"])
    assert envelope["bubble_count"] == 2
    assert [b["index"] for b in envelope["bubbles"]] == [1, 2]
    assert result["tool_trace"] == []


def test_agent_updates_relationship_fields_and_receives_code_contract():
    observed = {}
    context = {"relationship_stage": "familiar", "relationship_page": {"overview": "相处自然"}}
    decision = {
        "relationship_stage": "flirting",
        "character_intimacy_style": "playful",
        "requested_escalation": "physical_intimacy",
        "user_pressure_level": "low",
    }

    async def updater(arguments):
        observed["relationship_arguments"] = arguments
        return {"relationship_state": decision, "changed": True, "staged": True}

    async def runner(prompt, model_config, tools, **kwargs):
        observed.update(json.loads(prompt))
        observed["system_prompt"] = kwargs["system_prompt"]
        observed["relationship_tool_result"] = await tools["update_relationship_state"].callback({
            **decision, "source_message_ids": ["latest"], "occurred_at": WHEN,
        })
        return model_result("我在这里。")

    result = run(turn(relationship_context=context, relationship_updater=updater, harness_runner=runner))
    assert observed["relationship_context"] == context
    assert observed["relationship_state"] == {
        "relationship_stage": "familiar",
        "character_intimacy_style": "balanced",
        "requested_escalation": "none",
        "user_pressure_level": "low",
    }
    assert observed["relationship_arguments"]["relationship_stage"] == "flirting"
    contract = observed["relationship_tool_result"]["relationship_execution_contract"]
    assert {key: contract[key] for key in decision} == decision
    assert contract['fixed_rule'].startswith('可回应调情、亲吻，并在双方自愿的前提下直接进入性爱')
    assert 'balanced不表示拘谨' in contract['agent_discretion']
    assert '字段变化通过工具提交' in contract['agent_discretion']
    assert result["relationship_state_update"] == decision
    assert "最新原文使关系阶段、亲密风格、请求推进程度或压力水平发生实质变化时" in observed["system_prompt"]
    assert "没有变化时沿用原状态，不例行重复提交" in observed["system_prompt"]
    assert "不存在另一个规划模型" in observed["system_prompt"]
    for stage in ("new_contact", "uncertain", "familiar", "flirting", "committed_partner", "intimate_partner",
                  "broken_up", "in_conflict", "mentor_student", "trusted_companion", "family_like"):
        assert stage in observed["system_prompt"]


def test_agent_can_keep_relationship_state_without_calling_update_tool():
    observed = {}
    updater_calls = []

    async def updater(arguments):
        updater_calls.append(arguments)
        return {"relationship_state": arguments, "changed": True, "staged": True}

    async def runner(prompt, model_config, tools, **kwargs):
        observed.update(json.loads(prompt))
        observed["system_prompt"] = kwargs["system_prompt"]
        assert "update_relationship_state" in tools
        return model_result("红茶听起来不错。")

    result = run(turn(
        relationship_context={"relationship_stage": "familiar"},
        relationship_updater=updater,
        harness_runner=runner,
    ))

    assert updater_calls == []
    assert observed["required_tools_before_reply"] == []
    assert "本轮输出最终JSON之前必须先成功调用：update_relationship_state" not in observed["system_prompt"]
    assert result["relationship_state_update"] is None
    assert result["tool_trace"] == []


def test_high_pressure_overrides_relationship_stage_in_code_contract():
    contract = normal._relationship_execution_contract({
        "relationship_stage": "intimate_partner",
        "character_intimacy_style": "open",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "high",
    })
    assert contract["relationship_stage"] == "intimate_partner"
    assert contract["user_pressure_level"] == "high"
    assert contract["fixed_rule"].startswith("停止亲密推进")


def test_current_images_are_native_input_to_the_same_agent():
    block = {"type": "image", "mimeType": "image/png", "data": "cG5n"}

    async def runner(prompt, model_config, tools, **kwargs):
        assert isinstance(prompt, list)
        assert json.loads(prompt[0]["text"])["current_images_available"] is True
        assert prompt[1] == block
        assert "inspect_current_images" not in tools
        assert "自己读取画面和文字，按实际内容回应" in kwargs["system_prompt"]
        result = model_result("图里是一只蓝色杯子。")
        data = json.loads(result['final_response'])
        data['image_observation'] = {'image_summary':'一只蓝色杯子','visible_text':'',
                                     'identified_entities':['蓝色杯子'],'uncertainty':'','error':''}
        result['final_response'] = json.dumps(data, ensure_ascii=False)
        return result

    result = run(turn(current_image_blocks=[block], harness_runner=runner))
    assert result["llm_api_calls"] == 1


def test_removed_legacy_behavior_is_not_in_agent_system_prompt():
    observed = {}

    async def runner(prompt, model_config, tools, **kwargs):
        observed["system"] = kwargs["system_prompt"]
        return model_result("我直接回答。")

    run(turn(harness_runner=runner))
    assert "【旧版普通对话行为对齐规则】" not in observed["system"]
    assert "先回应用户刚说的话、刚做的动作或舞台指令，再补充解释、情绪和推进" not in observed["system"]


def test_visible_records_filter_deleted_and_internal_content():
    rows = normal.visible_messages([
        {"role": "user", "content": "first", "message_id": 1},
        {"role": "user", "content": "latest copy", "message_id": "1", "raw_content": "hidden reasoning"},
        {"role": "assistant", "content": "deleted", "deleted_at": "2026-09-06"},
        {"role": "system", "content": "internal"},
        {"role": "assistant", "content": "hidden", "is_hidden": 1}, None,
    ])
    assert rows == [{"role": "user", "content": "latest copy", "message_id": "1"}]
    assert normal.visible_messages([
        {"role": "user", "content": "old snapshot", "message_id": "m1"},
        {"role": "user", "content": "hidden snapshot", "message_id": "m1", "is_hidden": True},
    ]) == []


@pytest.mark.parametrize("text", ["", "<think>private</think>正文", "<|tool_call|>private", "<｜tool_calls｜>"])
def test_invalid_replies_are_not_enveloped(text):
    with pytest.raises(normal.NormalAgentError):
        normal.reply_envelope(text)


def test_stage_is_draft_until_successful_current_delivery(tmp_path):
    path = tmp_path / "app.sqlite"
    store = make_store(path)

    async def runner(prompt, model_config, tools, **kwargs):
        assert {"search_memory", "stage_memory", "request_memory_review"} == set(tools)
        staged = await tools["stage_memory"].callback(stage_args())
        assert staged["staged"] is True
        return model_result("红茶的香气很适合现在。")

    result = run(turn(memory_store=store, harness_runner=runner))
    assert result["memory_store"] is store
    assert not path.exists()
    saved = store.commit(reply_succeeded=True, generation_is_current=lambda: True)
    assert len(saved) == 1 and saved[0]["source_message_ids"] == ["latest"]


@pytest.mark.parametrize("failure", ["invalid", "unfinished", "cancelled"])
def test_failed_generation_discards_all_drafts(tmp_path, failure):
    path = tmp_path / "app.sqlite"
    store = make_store(path)

    async def runner(prompt, model_config, tools, **kwargs):
        await tools["stage_memory"].callback(stage_args())
        if failure == "cancelled":
            raise asyncio.CancelledError()
        return model_result("" if failure == "invalid" else "正文", "max_steps" if failure == "unfinished" else "completed")

    with pytest.raises((normal.NormalAgentError, asyncio.CancelledError)):
        run(turn(memory_store=store, harness_runner=runner))
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True) == []
    assert not path.exists()


def test_setup_failure_also_discards_preexisting_draft(tmp_path):
    store = make_store(tmp_path / "app.sqlite")
    store.stage(**stage_args())
    with pytest.raises(normal.NormalAgentError):
        run(turn(messages=[], memory_store=store))
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True) == []


def test_request_message_ids_do_not_grant_memory_source_permission(tmp_path):
    store = make_store(tmp_path / "app.sqlite", sources=())

    async def runner(prompt, model_config, tools, **kwargs):
        with pytest.raises(ValueError, match="visible raw messages"):
            await tools["stage_memory"].callback(stage_args())
        return model_result()

    run(turn(memory_store=store, harness_runner=runner))
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True) == []


def test_expanding_sources_cannot_reopen_a_discarded_turn(tmp_path):
    store = make_store(tmp_path / "app.sqlite", sources=())
    store.allow_visible_sources(["visible-db-row"])
    store.stage(**stage_args("visible-db-row"))
    store.discard()
    store.allow_visible_sources(["later-row"])
    with pytest.raises(RuntimeError):
        store.stage(**stage_args("later-row"))
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True) == []


def test_only_visible_trusted_history_extends_sources_and_advances_cursor(tmp_path):
    store = make_store(tmp_path / "app.sqlite")
    cursors = []

    async def reader(**kwargs):
        cursors.append(kwargs)
        return [{"role": "user", "message_id": "old", "content": "我以前就喜欢红茶", "sequence_number": None},
                {"role": "user", "message_id": "secret", "content": "隐藏记录", "is_hidden": True}]

    async def runner(prompt, model_config, tools, **kwargs):
        with pytest.raises(ValueError):
            await tools["stage_memory"].callback(stage_args("old"))
        page = await tools["read_history"].callback({"limit": 2})
        assert page["next_before_message_id"] == "old"
        await tools["stage_memory"].callback(stage_args("old"))
        with pytest.raises(ValueError):
            await tools["stage_memory"].callback(stage_args("secret"))
        await tools["read_history"].callback({"limit": 2})
        return model_result()

    messages = [{"role": "assistant", "message_id": "recent", "content": "你好"},
                {"role": "user", "message_id": "latest", "content": "我的偏好是什么"}]
    run(turn(messages=messages, memory_store=store, history_reader=reader, harness_runner=runner))
    assert [c["before_message_id"] for c in cursors] == ["recent", "old"]
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True)[0]["source_message_ids"] == ["old"]


@pytest.fixture
def history_db(tmp_path):
    # Extract the production SQL literal without importing Backend/config.
    tree = ast.parse((ROOT / "db/database_impl/schema.py").read_text(encoding="utf-8"))
    sql = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "SCHEMA_SQL" for t in n.targets))
    path = tmp_path / "app.sqlite"
    with sqlite3.connect(path) as conn:
        for table in ("users", "conversations", "messages"):
            statement = re.search(r"CREATE TABLE IF NOT EXISTS " + table + r" \([\s\S]*?\n\);", sql).group()
            conn.execute(statement)
        conn.executemany("INSERT INTO users(id,username,password) VALUES(?,?,?)", [(1,"alice","unused"),(2,"bob","unused")])
        conn.executemany("INSERT INTO conversations(id,character_id,user_id,title,timestamp,is_hidden) VALUES(?,?,?,?,?,?)",
                         [("c1","twilight",1,"chat",0,0),("c2","twilight",1,"other",0,0),
                          ("c3","twilight",2,"private",0,0),("hidden","twilight",1,"hidden",0,1)])
        for mid, conv, stamp, seq, role, hidden, deleted in [
            ("m1","c1",1,1,"user",0,None), ("m2","c1",2,None,"user",0,None),
            ("m3","c1",3,5,"assistant",0,None), ("m4","c1",3,5,"user",0,None),
            ("m5","c1",4,6,"assistant",1,None), ("m6","c1",5,7,"user",0,"deleted"),
            ("m7","c1",6,8,"system",0,None), ("m8","c1",7,9,"assistant",0,None),
            ("foreign","c2",8,10,"user",0,None), ("bob","c3",9,11,"user",0,None),
            ("secret","hidden",10,12,"user",0,None),
        ]:
            conn.execute("INSERT INTO messages(id,message_id,conversation_id,content,timestamp,sequence_number,role,is_hidden,deleted_at,raw_content,quoted_message_json,speaker_character_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                         ("id-"+mid, None if mid=="m2" else mid, conv, "raw-"+mid, stamp, seq, role, hidden, deleted,
                          "private thinking", '{"message_id":"m1","content":"quoted visible text"}', "twilight"))
    return path


def read(path, **kwargs):
    defaults = {"username": "alice", "character_id": "twilight", "conversation_id": "c1"}
    return run(history.read_history(path, **(defaults | kwargs)))


def test_history_uses_real_schema_and_preserves_visible_quotes(history_db):
    rows = read(history_db)
    assert [r["message_id"] for r in rows] == ["m1", "id-m2", "m3", "m4", "m8"]
    assert rows[-1]["content"] == "raw-m8"
    assert rows[-1]["quoted_message"]["content"] == "quoted visible text"
    assert rows[-1]["speaker_character_id"] == "twilight"
    assert all("raw_content" not in row for row in rows)


def test_history_images_are_bound_to_visible_message_and_conversation(history_db):
    with sqlite3.connect(history_db) as conn:
        conn.execute("CREATE TABLE message_attachments(conversation_id TEXT,message_id TEXT,type TEXT,asset_id TEXT,name TEXT)")
        conn.executemany("INSERT INTO message_attachments VALUES(?,?,?,?,?)", [
            ('c1', 'm8', 'sticker', 'visible', 'hello'),
            ('c2', 'm8', 'sticker', 'foreign', 'private'),
            ('c1', 'm5', 'sticker', 'hidden', 'hidden'),
            ('c1', 'm8', 'image', 'photo', 'ordinary photo'),
        ])
    rows = read(history_db)
    assert rows[-1]['attachments'] == [
        {'type': 'sticker', 'asset_id': 'visible', 'name': 'hello'},
        {'type': 'image', 'asset_id': 'photo', 'name': 'ordinary photo'}]
    assert sum(len(row.get('attachments', [])) for row in rows) == 2
    assert read(history_db, username='bob') == []


def test_message_cursor_pages_null_and_duplicate_sequences_without_gaps(history_db):
    first = read(history_db, limit=2)
    second = read(history_db, limit=2, before_message_id=first[0]["message_id"])
    third = read(history_db, limit=2, before_message_id=second[0]["message_id"])
    assert [r["message_id"] for r in third+second+first] == ["m1", "id-m2", "m3", "m4", "m8"]


def test_history_voice_state_is_bound_to_visible_message_and_conversation(history_db):
    with sqlite3.connect(history_db) as conn:
        conn.execute("CREATE TABLE message_voice_states(conversation_id TEXT,message_id TEXT,voice_status TEXT,tts_text TEXT)")
        conn.executemany("INSERT INTO message_voice_states VALUES(?,?,?,?)", [
            ('c1', 'm8', 'ready', 'Hello'),
            ('c2', 'm8', 'ready', 'Foreign private speech'),
            ('c1', 'm5', 'ready', 'Hidden speech'),
        ])
    rows = normal.visible_messages(read(history_db))
    assert rows[-1]['voice_state'] == {'voice_status': 'ready', 'tts_text': 'Hello'}
    assert sum('voice_state' in row for row in rows) == 1
    assert read(history_db, username='bob') == []


def test_history_scope_and_cursor_cannot_leak_hidden_or_other_conversations(history_db):
    assert read(history_db, username="bob") == []
    assert read(history_db, character_id="rainbow") == []
    assert read(history_db, conversation_id="hidden") == []
    for cursor in ("foreign", "bob", "secret", "m5", "m6", "nonexistent"):
        assert read(history_db, before_message_id=cursor) == []
    with pytest.raises(ValueError):
        read(history_db, before_message_id="m8", before_sequence=9)


def test_history_does_not_create_missing_database(tmp_path):
    path = tmp_path / "missing.sqlite"
    assert read(path) == []
    assert not path.exists()


@pytest.mark.parametrize("text", ["请记住我喜欢红茶", "记住我更喜欢绿茶", "把这个约定记下来", "记一下我的偏好"])
def test_explicit_memory_commands_are_narrowly_detected(text):
    assert normal._explicit_memory_request(text)


@pytest.mark.parametrize("text", ["别记住我的偏好", "不用记下来", "不要记一下", "请勿记住我", "记住了吗？",
                                   "你记住我了吗？", "你记下来了吗？", "我喜欢红茶", "今晚想喝茶"])
def test_negations_questions_and_ordinary_chat_are_not_forced_memory_requests(text):
    assert not normal._explicit_memory_request(text)


def row_message(mid, text):
    return {"role": "user", "message_id": mid, "content": text}


def test_explicit_memory_with_successful_stage_uses_only_one_attempt(tmp_path):
    store = make_store(tmp_path / "app.sqlite")
    calls = []

    async def runner(prompt, config, tools, **kwargs):
        calls.append(1)
        await tools["stage_memory"].callback(stage_args())
        return model_result()

    result = run(turn(messages=[row_message("latest", "请记住我的偏好")], memory_store=store, harness_runner=runner))
    assert calls == [1] and result["memory_completion_repairs"] == 0


@pytest.mark.parametrize("text,source", [("不要记住我的偏好", "latest"), ("你记住我了吗", "latest"),
                                         ("今晚想喝茶", "latest"), ("请记住我的偏好", "other")])
def test_negative_ordinary_or_untrusted_requests_are_not_forced_to_retry(tmp_path, text, source):
    store = make_store(tmp_path / "app.sqlite", sources=(source,))
    calls = []

    async def runner(*args, **kwargs):
        calls.append(1)
        return model_result()

    result = run(turn(messages=[row_message("latest", text)], memory_store=store, harness_runner=runner))
    assert calls == [1] and result["memory_completion_repairs"] == 0


def test_format_repairs_and_automatic_retry_share_three_minute_deadline(tmp_path, monkeypatch):
    store = make_store(tmp_path / "app.sqlite")
    clock = iter([0.0, 0.0, 181.0, 181.0])
    monkeypatch.setattr(normal, "time", types.SimpleNamespace(monotonic=lambda: next(clock)))
    attempts = []

    async def runner(*args, **kwargs):
        attempts.append(1)
        return model_result() | {"final_response": "not JSON"}

    with pytest.raises(normal.NormalAgentError, match="total time budget"):
        run(turn(messages=[row_message("latest", "请记住我喜欢红茶")], memory_store=store, harness_runner=runner))
    assert attempts == [1]
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True) == []


def test_date_only_validation_feedback_can_be_corrected_using_derived_source_time(tmp_path):
    store = make_store(tmp_path / "app.sqlite")
    message = row_message("latest", "请记住我喜欢红茶") | {"timestamp": 1788675137617}

    async def runner(prompt, config, tools, **kwargs):
        data = json.loads(prompt)
        assert data["latest_user_message"]["timestamp"] == 1788675137617
        occurred_at = data["source_message_times"]["latest"]["occurred_at"]
        assert occurred_at == "2026-09-06T06:12:17.617000+00:00"
        with pytest.raises(normal.HarnessToolValidationError, match="timezone"):
            await tools["stage_memory"].callback(stage_args() | {"occurred_at": "2026-09-06"})
        await tools["stage_memory"].callback(stage_args() | {"occurred_at": occurred_at})
        return model_result()

    result = run(turn(messages=[message], memory_store=store, harness_runner=runner))
    assert result["memory_completion_repairs"] == 0
    assert [event["success"] for event in result["tool_trace"]] == [False, True]
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True)[0]["occurred_at"] == "2026-09-06T06:12:17.617000+00:00"


def test_source_time_metadata_never_invents_time_for_date_only_or_missing_values():
    messages = [row_message("date-only", "历史事件") | {"timestamp": "2026-08-01"},
                row_message("missing", "历史事件"),
                row_message("iso", "记录") | {"timestamp": "2026-09-06T14:12:17+08:00"}]
    assert normal._source_message_times(messages) == {
        "iso": {"occurred_at": "2026-09-06T06:12:17+00:00",
                "meaning": "来源消息的记录时间；并非消息提到的所有历史事件的发生时间"}}


def test_schema_rejected_tool_attempts_are_metered_without_tool_cap(tmp_path):
    store = make_store(tmp_path / "app.sqlite")
    budgets = []

    async def runner(prompt, config, tools, **kwargs):
        budgets.append(kwargs["max_tool_calls"])
        if len(budgets) == 1:
            # Invalid arguments are rejected before a callback/trace entry.
            return model_result() | {"tool_call_count": 6, "final_response": "not JSON"}
        await tools["stage_memory"].callback(stage_args())
        return model_result() | {"tool_call_count": 1}

    result = run(turn(messages=[row_message("latest", "请记住我喜欢红茶")], memory_store=store, harness_runner=runner))
    assert budgets == [normal.NORMAL_TOOL_CALL_LIMIT, 0]
    assert result["tool_call_count"] == 7


def test_format_retry_keeps_staged_memory_and_never_delivers_invalid_text(tmp_path):
    store = make_store(tmp_path / "app.sqlite")
    calls = []

    async def runner(prompt, config, tools, **kwargs):
        calls.append(json.loads(prompt))
        if len(calls) == 1:
            await tools["stage_memory"].callback(stage_args())
            return model_result() | {"final_response": "好的。（我点头）"}
        assert "JSON" in calls[-1]["completion_feedback"]
        assert "不要重复stage_memory" in calls[-1]["completion_feedback"]
        return model_result("好的。")

    result = run(turn(messages=[row_message("latest", "请记住我喜欢红茶")], memory_store=store, harness_runner=runner))
    assert len(calls) == 2
    assert result["output_format_repairs"] == 1 and result["memory_completion_repairs"] == 0
    assert result["llm_api_calls"] == 2
    assert len(store.commit(reply_succeeded=True, generation_is_current=lambda: True)) == 1


@pytest.mark.parametrize("request_text", ["用欢快的语气念一样的诗歌。", "重新读一遍", "继续"])
def test_agent_final_repetition_is_never_rejected_or_regenerated(request_text):
    text = "Twinkle, twinkle, little star, how I wonder what you are."
    messages = [row_message("u1", "念诗"), {"role":"assistant","content":text},
                row_message("u2", "再念"), {"role":"assistant","content":text},
                row_message("latest", request_text)]
    calls = []
    async def runner(prompt, *args, **kwargs):
        calls.append(json.loads(prompt))
        assert "reply_dedup_context" not in calls[-1]
        return model_result(text)
    result = run(turn(messages=messages, harness_runner=runner))
    assert len(calls) == 1 and result['output_format_repairs'] == 0
    assert result['reply_dedup_report']['status'] == 'agent_owned'
    assert text in result['envelope']


@pytest.mark.parametrize("text", ["请记住我喜欢红茶", "只说三段话", "请联网搜索", "你好"])
def test_valid_output_is_not_blocked_by_content_or_unperformed_business_work(tmp_path, text):
    store = make_store(tmp_path / 'app.sqlite')
    calls = []
    class Business:
        def register(self, capability): pass
        def completion_error(self, data):
            raise AssertionError('Post-Agent business validation must not run')
    async def runner(*args, **kwargs):
        calls.append(1)
        return model_result('一段合法正文。') | {'completion_error':'未完成业务'}
    result = run(turn(messages=[row_message('latest', text)], memory_store=store,
                      business_tools=Business(), harness_runner=runner))
    assert calls == [1] and result['output_format_repairs'] == 0
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True) == []


@pytest.mark.parametrize('valid_attempt', [2, 3, 4, None])
def test_malformed_output_has_four_attempts_per_execution_and_one_automatic_retry(valid_attempt):
    calls = []
    async def runner(*args, **kwargs):
        calls.append(1)
        return model_result() if len(calls) == valid_attempt else model_result() | {'final_response':'not JSON'}
    if valid_attempt is None:
        with pytest.raises(normal.NormalAgentError):
            run(turn(harness_runner=runner))
        assert len(calls) == 8
    else:
        result = run(turn(harness_runner=runner))
        assert len(calls) == valid_attempt
        assert result['output_format_repairs'] == valid_attempt - 1


def test_failed_memory_tool_remains_invalid_without_forcing_final_retry(tmp_path):
    store = make_store(tmp_path / 'app.sqlite')
    calls = []
    async def runner(prompt, config, tools, **kwargs):
        calls.append(1)
        with pytest.raises(ValueError):
            await tools['stage_memory'].callback(stage_args('forged-id'))
        return model_result('还没有保存成功。')
    result = run(turn(memory_store=store, harness_runner=runner))
    assert calls == [1] and result['tool_trace'][0]['success'] is False
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True) == []


@pytest.mark.parametrize('raw', ['[]', 'null', '42', '{}'])
def test_incompatible_json_shape_is_retried_as_format_error(raw):
    calls = []
    async def runner(*args, **kwargs):
        calls.append(1)
        return model_result() | {'final_response': raw} if len(calls) == 1 else model_result()
    result = run(turn(harness_runner=runner))
    assert calls == [1, 1] and result['output_format_repairs'] == 1
