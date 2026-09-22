"""Real live intake, guest handler, Agent preparation, SSE and SQLite delivery."""
import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone

import pytest

from test_autonomous_upgrade_integration import database
from test_autonomous_normal import model_result
from expression_skill_contract import read_expression_contract
from Backend.chat_modules import service, live_turn, harness_runtime
from Backend.chat_modules import normal_speaker
from Backend.chat_modules.live_reply_batch import ReplyBatch
from Backend.utils import ChatMessage, ChatRequest


@pytest.mark.parametrize("already_running", [False, True])
def test_explicit_guest_flows_through_actual_handler_and_original_window(database, monkeypatch, already_running):
    from Backend.routes import auth
    from Backend import background_jobs
    from Backend.chat_modules import state, normal_nonstream
    from Backend.chat_modules.service_impl import chat_request_helpers

    async def noop(*args, **kwargs): return None
    async def verify(_token): return "alice"
    async def authenticated(req, client, token, model):
        assert req.username == "alice"
        return {"active_model": {"model_name": "synthetic"}, "request_tokens": 0,
                "client_id": client, "character_id": req.character_id,
                "username": req.username, "effective_username": req.username}

    # Keep database, routing, speaker profiles, Agent preparation and persistence
    # real. Replace account verification, external generation and notifications.
    for name, module in list(sys.modules.items()):
        if not name.startswith("Backend") or module is None:
            continue
        if hasattr(module, "get_database"):
            monkeypatch.setattr(module, "get_database", lambda: database)
        if hasattr(module, "save_chat_debug_log"):
            monkeypatch.setattr(module, "save_chat_debug_log", noop)
    monkeypatch.setattr(auth, "auth_token_verify", verify)
    monkeypatch.setattr(service, "resolve_auth_and_quota", authenticated)
    monkeypatch.setattr(service, "_normal_reply_debounce_ms", lambda: 0)
    monkeypatch.setattr(service, "_is_new_contact_opening", noop)
    # The prompt still uses the actual character database and reference tools.
    async def user_context(*args, **kwargs): return "合成测试用户"
    monkeypatch.setattr(service, "build_user_context", user_context)
    for module in (service, state, normal_nonstream, chat_request_helpers):
        monkeypatch.setattr(module, "is_generation_current", lambda *a, **kw: True)
    monkeypatch.setattr(service.generation_locker, "release", noop)
    monkeypatch.setattr(service.manager, "broadcast_to_user", noop)
    monkeypatch.setattr(service.manager, "broadcast_sync", noop)
    monkeypatch.setattr(service.manager, "is_active_chat", lambda *a, **kw: True)
    monkeypatch.setattr(background_jobs, "create_tracked_task", lambda coro, **kw: asyncio.create_task(coro))

    with sqlite3.connect(database.db_path) as conn:
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) "
                     "VALUES('secret','secret','c1','user','很早的主角色私聊秘密',1,0)")
        for index in range(9):
            conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) "
                         "VALUES(?,?,'c1','user','公开话题',?,?)", (f'past{index}', f'past{index}', index+2, index+1))
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,speaker_character_id) "
                     "VALUES('old-reply','old-reply','c1','assistant','我们继续这个话题。',1500,'twilight')")
        for cid, name in (("twilight", "暮光闪闪"), ("pinkie", "碧琪")):
            conn.execute("UPDATE characters SET data=? WHERE id=?", (json.dumps({
                "name": name, "profileIntro": name + "的独立档案", "profileSpecies": "小马"}), cid))

    async def scenario():
        first_started, finish_first = asyncio.Event(), asyncio.Event()
        later_started, finish_later = asyncio.Event(), asyncio.Event()
        later_round = False
        private_recall = False
        generated = []
        def agent_reply(text, mid):
            """Synthetic Agent delivery; the envelope must satisfy the delivery contract."""
            value = model_result(text)
            data = json.loads(value['final_response'])
            data['reply_language']['language'] = 'Chinese'
            from Backend.chat_modules.autonomous_scene_state import FIELDS
            # These synthetic messages establish no scene facts; initialize as unknown.
            data['scene_patch'] = {'reset': False, 'changes': {
                field: {'value': None, 'source_message_ids': [mid]} for field in sorted(FIELDS)}}
            return {**value, 'final_response': json.dumps(data, ensure_ascii=False)}
        async def runner(prompt, model, tools, **kwargs):
            task = json.loads(prompt)
            profile = task["character_profile"]
            speaker = "pinkie" if "碧琪的独立档案" in profile else "twilight"
            generated.append((speaker, task))
            # The Agent refuses to deliver before an interaction mode is read; this
            # guest chat is ordinary instant messaging.
            await tools["load_chat_skill"].callback({"name": "instant_messaging"})
            await tools["read_character_reference"].callback({"query": "独立档案"})
            if private_recall:
                seen = await tools['read_group_experience'].callback({'limit': 40})
                text = json.dumps(seen, ensure_ascii=False)
                assert '青色晚风' in text and '请记住我喜欢绿茶' in text
                assert '很早的主角色私聊秘密' not in text
                # Ordinary private chat still completes the serial expression reads.
                await read_expression_contract(tools)
                return agent_reply('我记得参加了群聊，后来紫悦说了青色晚风。',
                                   task['latest_user_message']['message_id'])
            if speaker == "twilight" and already_running and len(generated) == 1:
                first_started.set()
                await finish_first.wait()
            if later_round and speaker == "twilight":
                channel = kwargs.get("input_channel")
                assert channel is live_turn.active_turn("alice", "twilight")
                later_started.set()
                await finish_later.wait()
                # Intake is a merged ReplyBatch now: the retired per-turn inbox
                # was drained with take_pending() and folded in through
                # prepare_input()/try_seal(), while batch intake cancels the
                # in-flight attempt and re-runs the same turn with one merged
                # request. The same intent is therefore observed as: the
                # supplement belongs to this turn's admitted batch, this
                # attempt's model input carries it, nothing is left queued
                # behind the turn, and the turn still owns the reply.
                assert isinstance(channel, ReplyBatch)
                assert "supplement" in channel.known
                assert channel.revision >= 2
                merged = task.get("current_user_batch") or []
                assert {"ordinary", "supplement"} <= {row.get("message_id") for row in merged}
                assert any(row.get("content") == "还有时间问题" for row in merged)
                assert not channel.pending
                assert not channel.delivered
                await tools["handoff_reply"].callback({"reply_character_id": "pinkie", "reason": "请碧琪安排后续"})
            if speaker == "pinkie":
                assert "【当前临时群聊】" in task["environment"]
                assert "本轮只由「碧琪」(pinkie) 发言" in task["environment"]
                assert kwargs.get("input_channel") is None
                assert '很早的主角色私聊秘密' not in json.dumps(task, ensure_ascii=False)
                older = await tools['read_history'].callback({'limit': 40})
                assert '很早的主角色私聊秘密' not in json.dumps(older, ensure_ascii=False)
                secret = await tools['read_original_messages'].callback({'message_ids': ['secret']})
                assert secret['messages'] == []
                if not later_round:
                    await tools["handoff_reply"].callback({"reply_character_id": "twilight", "reason": "请紫悦接着评价"})
            # Every real character request is an Agent turn, so each one completes
            # the serial expression reads (including after a live-input refresh).
            await read_expression_contract(tools)
            # The synthetic model answers each round with its own wording, as a
            # real one would: a verbatim repeat of the previous assistant message
            # is suppressed by the reply-level duplicate guard.
            if later_round:
                reply_text = "时间安排我也记下了，青色晚风。" if speaker == "twilight" else "后续时间安排我来盯着。"
            else:
                reply_text = "我接着说这个话题，青色晚风。" if speaker == "twilight" else "我来评价刚才的话题。"
            return agent_reply(reply_text, task['latest_user_message']['message_id'])
        monkeypatch.setattr(harness_runtime, "run_harness_turn", runner)

        def incoming(text, mid):
            return ChatRequest(username="alice", character_id="twilight", conversation_id="c1",
                mode="normal", memory_enabled=True,
                messages=[ChatMessage(role="user", content=text, message_id=mid, timestamp=2000)])

        async def send(req):
            return await live_turn.normal_live_response(req, "android", "isolated-token", {},
                use_json=True, handler=service.handle_chat_request)

        initial, initial_turn = None, None
        if already_running:
            initial = asyncio.create_task(send(incoming("碧琪你来评价一下", "intro")))
            await asyncio.wait_for(first_started.wait(), 3)
            initial_turn = live_turn.active_turn("alice", "twilight")
        called = asyncio.create_task(send(incoming("@碧琪", "at")))
        if initial is not None:
            # An addressed message arriving mid-turn is absorbed by the running
            # batch (admitted after persistence, revision bumped, in-flight
            # attempt cancelled and re-run) instead of waiting in a separate
            # routing queue, so the running turn keeps ownership and resolves
            # the new speaker on its re-run. That is what routing_waiting used
            # to assert. Admission is only observable once its persistence
            # finishes, so wait for the merge instead of sleeping.
            async def wait_for_addressed_merge():
                while "at" not in initial_turn.known:
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(wait_for_addressed_merge(), 3)
            merged_turn = live_turn.active_turn("alice", "twilight")
            assert isinstance(merged_turn, ReplyBatch)
            assert merged_turn is initial_turn
            assert not merged_turn.delivered
            assert "at" in merged_turn.known
            assert merged_turn.revision >= 2
            finish_first.set()
            first_response = await asyncio.wait_for(initial, 5)
            assert not any(e.get("type") == "error" for e in json.loads(first_response.body)["events"])
        response = await asyncio.wait_for(called, 8)
        events = json.loads(response.body)["events"]
        assert not any(e.get("type") == "error" for e in events), events
        assert any(e.get("speaker_character_id") == "pinkie" for e in events), events
        if initial is not None:
            # Both acknowledgements name the one running job: the addressed
            # message joined that turn instead of opening a new one.
            def accepted_job_ids(payload):
                return [e.get("job_id") for e in json.loads(payload.body)["events"]
                        if e.get("type") == "accepted"]
            assert accepted_job_ids(first_response) == accepted_job_ids(response) == [merged_turn.job_id]
        # Handoff uses a second real character request, not the first Agent
        # impersonating the other character inside its own response.
        assert [speaker for speaker, _ in generated] == (
            ["twilight", "pinkie", "twilight"] if already_running else ["pinkie", "twilight"])
        later_round = True
        ordinary = asyncio.create_task(send(incoming("那后续应该怎么安排？", "ordinary")))
        await asyncio.wait_for(later_started.wait(), 3)
        supplement = asyncio.create_task(send(incoming("还有时间问题", "supplement")))
        async def wait_for_merge():
            # Merged input lands in batch.known, not in the retired LiveTurn inbox.
            while True:
                turn = live_turn.active_turn("alice", "twilight")
                if turn is not None and "supplement" in turn.known:
                    return turn
                await asyncio.sleep(0.01)
        continued_turn = await asyncio.wait_for(wait_for_merge(), 3)
        assert isinstance(continued_turn, ReplyBatch)
        assert not continued_turn.delivered
        assert {"ordinary", "supplement"} <= continued_turn.known
        assert continued_turn.revision >= 2
        finish_later.set()
        continued, joined = await asyncio.wait_for(asyncio.gather(ordinary, supplement), 8)
        for result in (continued, joined):
            continued_events = json.loads(result.body)["events"]
            assert not any(e.get("type") == "error" for e in continued_events), continued_events
            assert any(e.get("speaker_character_id") == "pinkie" for e in continued_events)
            assert not any(e.get("type") == "normal_handoff_request" for e in continued_events)
        assert [speaker for speaker, _ in generated[-2:]] == ["twilight", "pinkie"]
        with sqlite3.connect(database.db_path) as conn:
            rows = conn.execute("SELECT role,content,speaker_character_id,conversation_id FROM messages "
                                "WHERE message_id='at' OR (role='assistant' AND conversation_id='c1')").fetchall()
        assert sum(r[0] == "user" and r[1] == "@碧琪" for r in rows) == 1
        assert sum(r[0] == "assistant" and r[2] == "pinkie" and r[3] == "c1" for r in rows) == 2
        assert all(r[3] == "c1" for r in rows)
        from Backend.agent_memory.participants import read_group_experience
        assert not read_group_experience(database.db_path, username='alice', character_id='outsider')
        private_recall = True
        private = ChatRequest(username='alice', character_id='pinkie', conversation_id='private-pinkie',
            mode='normal', memory_enabled=True, messages=[ChatMessage(role='user',
            content='刚才你参加的群聊，后来紫悦说了什么？', message_id='private-question', timestamp=99999999)])
        private_response = await asyncio.wait_for(send(private), 6)
        private_events = json.loads(private_response.body)['events']
        assert not any(e.get('type') == 'error' for e in private_events), private_events
        assert any('青色晚风' in e.get('content', '') for e in private_events)
        # The normal review job can consume exactly the same granted originals
        # and write an episode into Pinkie's shared Agent Memory store.
        from Backend.agent_memory import jobs
        from Backend.agent_memory.store import AgentMemoryStore
        async def review_runner(prompt, model, tools, **kwargs):
            raw = json.loads(prompt)['recent_raw_messages']['messages']
            evidence = next(row for row in raw if '青色晚风' in row.get('content', '')
                            and row.get('conversation_id') == 'c1')
            await tools['stage_memory'].callback({'kind': 'fact', 'category': 'episode',
                'certainty': 'observed', 'content': '我参加过临时群聊，听到紫悦提起青色晚风。', 'importance': 6,
                'source_message_ids': [evidence['message_id']],
                'occurred_at': datetime.fromtimestamp(evidence['timestamp']/1000, timezone.utc).isoformat()})
            return {'finish_reason': 'completed', 'final_response': '{"needs_more":true}', 'llm_api_calls': 1}
        async def profile(*args): return '碧琪的独立档案'
        jobs.enqueue(database.db_path, 'alice', 'pinkie', immediate=True)
        reviewed = await jobs.run_one(database.db_path, {}, profile, username='alice', character_id='pinkie',
                                      harness_runner=review_runner)
        assert any(row['category'] == 'episode' for row in reviewed['saved'])
        personal = AgentMemoryStore(database.db_path, username='alice', character_id='pinkie',
                                    conversation_id=private.conversation_id)
        assert any('青色晚风' in row['content'] for row in personal.list(category='episode'))
        await database.close()
    asyncio.run(scenario())
