"""Delivery/state separation, durable retries and per-conversation ordering."""
import asyncio
import json
import sqlite3

import pytest

from Backend.agent_memory import jobs
from Backend.agent_memory.store import AgentMemoryStore
from Backend.chat_modules import post_reply_state as queue
from Backend.chat_modules import post_reply_state_worker as worker
from Backend.chat_modules.autonomous_transaction import install_memory_transaction
from Backend.chat_modules.autonomous_scene_state import FIELDS, load_scene
from test_autonomous_upgrade_integration import database, request, save
from test_autonomous_normal import model_result
from Backend.chat_modules import autonomous_normal as normal
from test_agent_parity import business


def test_state_json_fence_is_accepted_but_prose_is_rejected():
    data = state_result()
    assert worker.parse_state_response('```json\n' + json.dumps(data) + '\n```') == data
    assert worker.parse_state_response(json.dumps(data)) == data
    with pytest.raises(ValueError, match='完整JSON'):
        worker.parse_state_response('说明文字：' + json.dumps(data))


@pytest.fixture(autouse=True)
def isolated_progress(monkeypatch, tmp_path):
    monkeypatch.setenv('PONYCHAT_AGENT_STATUS_DB_PATH', str(tmp_path / 'progress.sqlite'))


def enqueue(database):
    jobs.configure(database.db_path, 'alice', 'twilight', True)
    store = AgentMemoryStore(database.db_path, username='alice', character_id='twilight',
                            conversation_id='c1', allowed_sources=['m1'])
    req = request()
    req._post_reply_state_payload = {'messages': [{'role': 'user', 'message_id': 'm1',
        'content': '请记住我喜欢绿茶'}], 'profile': '暮光是独角兽',
        'interaction_mode': 'instant_messaging', 'required_memory_ids': ['m1']}
    install_memory_transaction(req, store)
    assert asyncio.run(save(database, req))
    return req, store


def state_result():
    return {'scene_patch': {'reset': False, 'changes': {
        key: {'value': None, 'source_message_ids': ['m1']} for key in FIELDS}},
        'memories': [{'content': '用户喜欢绿茶', 'source_message_ids': ['m1'],
                      'category': 'preference', 'importance': 5, 'occurred_at': None}],
        'followup_decision': {'enabled': False, 'reason': '本轮已经答完，没有需要主动补充的新消息。'}}


def test_front_reply_needs_no_scene_or_followup_and_no_memory_write_tools():
    req = request()
    req._defer_reply_state = True
    b = business(req, enabled=False)
    calls = []
    async def runner(prompt, config, tools, **kwargs):
        calls.append(json.loads(prompt))
        assert 'stage_memory' not in tools
        result = model_result('先把这句话交付。')
        data = json.loads(result['final_response'])
        data.pop('followup_decision')
        # Even invalid state metadata must not cause visible-text regeneration.
        data['scene_patch'] = 'not a scene patch'
        return {**result, 'final_response': json.dumps(data)}
    result = asyncio.run(normal.run_autonomous_turn(messages=[{'role':'user','content':'你好','message_id':'m1'}],
        character_profile='温和', environment='', model_config={}, scene_state={'revision':0,'fields':{}},
        business_tools=b, defer_state=True, harness_runner=runner))
    assert len(calls) == 1 and result['output_format_repairs'] == 0
    assert result['scene_patch'] is None and '先把这句话交付' in result['envelope']
    assert 'followup_contract' not in calls[0]


def test_reply_commits_before_any_state_model_and_retries_do_not_rewrite(database):
    req, store = enqueue(database)
    assert load_scene(store)['revision'] == 0
    with sqlite3.connect(database.db_path) as conn:
        assert conn.execute("SELECT content FROM messages WHERE message_id='a1'").fetchone()[0] == '记住了'
        assert conn.execute('SELECT count(*) FROM agent_memory_heads').fetchone()[0] == 0
    calls = []
    async def runner(prompt, *args, **kwargs):
        data = json.loads(prompt)
        calls.append(data)
        assert data['delivered_reply'][0]['content'] == '记住了'
        assert data['phase'] == 'post_reply_state'
        if len(calls) == 1:
            return {'finish_reason':'completed','final_response':'{}'}
        assert data['validation_feedback']
        return {'finish_reason':'completed','final_response':json.dumps(state_result())}
    async def process(path, job):
        await worker.process(path, job, harness_runner=runner, model_config={})
    queue.activate(database.db_path, req._post_reply_job_id)
    asyncio.run(queue.drain(database.db_path, 'alice', 'c1', processor=process))
    assert len(calls) == 2 and load_scene(store)['revision'] == 1
    with sqlite3.connect(database.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM messages WHERE role='assistant'").fetchone()[0] == 1
        assert conn.execute("SELECT content FROM messages WHERE message_id='a1'").fetchone()[0] == '记住了'
        assert conn.execute('SELECT status,attempts FROM normal_post_reply_jobs').fetchone() == ('done', 2)
        assert conn.execute('SELECT count(*) FROM agent_memory_heads').fetchone()[0] == 1
    asyncio.run(queue.drain(database.db_path, 'alice', 'c1', processor=process))
    assert len(calls) == 2  # Idempotent after restart/retry.


def test_state_model_receives_explicit_relative_position_dependencies(database, monkeypatch):
    from Backend.chat_modules import autonomous_scene_state as scene
    req, _ = enqueue(database)
    queue.activate(database.db_path, req._post_reply_job_id)
    snapshot = {'revision': 0, 'fields': {
        'user_position': {'value': '坐在角色旁边', 'source_message_ids': ['m1']},
        'character_position': {'value': '坐在沙发上', 'source_message_ids': ['m1']}}}
    monkeypatch.setattr(scene, 'load_scene', lambda store: snapshot)
    async def runner(prompt, *args, **kwargs):
        data = json.loads(prompt)
        assert data['position_dependencies'] == [{
            'changed_field': 'character_position', 'recheck_field': 'user_position',
            'include_recheck_field_when_changed': True, 'must_not_invent_movement': True,
            'preserve_value': '坐在角色旁边'}]
        return {'finish_reason': 'completed', 'final_response': json.dumps(state_result())}
    asyncio.run(worker.process(database.db_path, queue.pending(database.db_path)[0],
                              harness_runner=runner, model_config={}))
    assert queue.pending(database.db_path) == []


@pytest.mark.parametrize('certainty', ['explicit', 'observed', 'inferred'])
def test_understanding_is_conservatively_inferred_without_model_retry(database, certainty):
    req, _ = enqueue(database)
    queue.activate(database.db_path, req._post_reply_job_id)
    calls = []
    async def runner(*args, **kwargs):
        calls.append(1)
        assert kwargs['max_tokens'] == 8192
        data = state_result()
        data['memories'].append({'content': '用户可能喜欢清淡的饮品',
            'source_message_ids': ['m1'], 'category': 'understanding', 'certainty': certainty})
        return {'finish_reason': 'completed', 'final_response': json.dumps(data)}
    async def process(path, job):
        await worker.process(path, job, harness_runner=runner, model_config={})
    asyncio.run(queue.drain(database.db_path, 'alice', 'c1', processor=process))
    with sqlite3.connect(database.db_path) as conn:
        assert conn.execute("SELECT certainty FROM agent_memory_versions WHERE category='understanding'").fetchone()[0] == 'inferred'
        assert conn.execute('SELECT status,attempts FROM normal_post_reply_jobs').fetchone() == ('done', 1)
    assert len(calls) == 1


def test_state_progress_is_separate_from_waiting_foreground(database):
    from Backend.chat_modules import agent_logging, agent_status
    req, _ = enqueue(database)
    queue.activate(database.db_path, req._post_reply_job_id)
    @agent_logging.logged_harness
    async def runner(*args, **kwargs):
        current = agent_status.read_all('alice', 'twilight', 'normal')
        assert {r['phase'] for r in current} == {'foreground', 'background_memory'}
        return {'finish_reason': 'completed', 'final_response': json.dumps(state_result()), 'llm_api_calls': 1}
    async def scenario():
        async with agent_logging.log_scope('alice', 'twilight', 'normal',
                params={'trace_id': 'front', 'conversation_id': 'c1'}):
            await worker.process(database.db_path, queue.pending(database.db_path)[0],
                                 harness_runner=runner, model_config={})
            rows = agent_status.read_all('alice', 'twilight', 'normal')
            front = next(r for r in rows if r['phase'] == 'foreground')
            back = next(r for r in rows if r['phase'] == 'background_memory')
            assert front['status'] == 'running' and front['model_calls'] == 0
            assert back['status'] == 'success' and back['model_calls'] == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ["UPDATE messages SET is_hidden=1 WHERE message_id='m1'",
    "UPDATE messages SET content='编辑过的文本' WHERE message_id='a1'",
    "UPDATE agent_memory_state SET epoch=epoch+1"])
def test_deleted_edited_or_reset_evidence_cancels_state_job(database, change):
    req, _ = enqueue(database)
    with sqlite3.connect(database.db_path) as conn:
        conn.execute(change)
    async def runner(*args, **kwargs):
        pytest.fail('stale evidence must not reach model')
    queue.activate(database.db_path, req._post_reply_job_id)
    job = queue.pending(database.db_path)[0]
    asyncio.run(worker.process(database.db_path, job, harness_runner=runner, model_config={}))
    assert queue.pending(database.db_path) == []


def test_failed_state_is_bounded_and_next_round_cannot_read_stale_state(database):
    req, _ = enqueue(database)
    queue.activate(database.db_path, req._post_reply_job_id)
    count = []
    async def fail(*args):
        count.append(1)
        raise ValueError('invalid state')
    with pytest.raises(queue.PendingReplyState):
        asyncio.run(queue.drain(database.db_path, 'alice', 'c1', processor=fail))
    assert len(count) == 3
    with pytest.raises(queue.PendingReplyState):
        asyncio.run(queue.drain(database.db_path, 'alice', 'c1', processor=fail))
    assert len(count) == 3


@pytest.mark.parametrize('cancel', [False, True])
def test_post_commit_exception_cannot_resurrect_completed_job(database, cancel):
    req, _ = enqueue(database)
    queue.activate(database.db_path, req._post_reply_job_id)
    calls = []
    async def committed(path, job):
        calls.append(job['id'])
        queue.mark(path, job['id'], 'done')
        if cancel:
            raise asyncio.CancelledError()
        raise RuntimeError('usage bookkeeping failed after commit')
    async def scenario():
        try:
            await queue.drain(database.db_path, 'alice', 'c1', processor=committed)
        except asyncio.CancelledError:
            assert cancel
    asyncio.run(scenario())
    assert len(calls) == 1 and not queue.pending(database.db_path)
    with sqlite3.connect(database.db_path) as conn:
        assert conn.execute('SELECT status,payload,attempts FROM normal_post_reply_jobs').fetchone() == ('done', '{}', 1)


def test_restart_releases_committed_waiting_delivery_jobs(database, monkeypatch):
    req, _ = enqueue(database)
    assert queue.pending(database.db_path)[0]['status'] == 'waiting_delivery'
    launched = []
    monkeypatch.setattr(queue, 'launch', lambda *args: launched.append(args))
    async def scenario():
        task = asyncio.create_task(queue.recovery_loop(database.db_path))
        for _ in range(30):
            if launched: break
            await asyncio.sleep(.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
    assert launched and queue.pending(database.db_path)[0]['status'] == 'pending'


@pytest.mark.parametrize('new_input', [False, True])
def test_background_followup_respects_user_message_arriving_during_model(database, new_input):
    req, _ = enqueue(database)
    queue.activate(database.db_path, req._post_reply_job_id)
    async def runner(*args, **kwargs):
        if new_input:
            with sqlite3.connect(database.db_path) as conn:
                conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) "
                    "VALUES('m2','m2','c1','user','继续聊吧',3000,3)")
        data = state_result()
        data['followup_decision'] = {'enabled': True, 'reason': '稍后有新的内容可以补充',
            'summary': '分享新发现的绿茶泡法', 'target_delay_seconds': 120}
        return {'finish_reason': 'completed', 'final_response': json.dumps(data)}
    asyncio.run(worker.process(database.db_path, queue.pending(database.db_path)[0],
                              harness_runner=runner, model_config={}))
    with sqlite3.connect(database.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM scheduled_followups').fetchone()[0] == int(not new_input)
        assert conn.execute('SELECT status FROM normal_post_reply_jobs').fetchone()[0] == 'done'


def test_atomic_state_job_rolls_back_with_reply(database):
    jobs.configure(database.db_path, 'alice', 'twilight', True)
    queue.connect(database.db_path).close()
    store = AgentMemoryStore(database.db_path, username='alice',character_id='twilight',
                            conversation_id='c1',allowed_sources=['m1'])
    req = request()
    req._post_reply_state_payload = {'messages':[],'profile':'test'}
    install_memory_transaction(req, store)
    original = req._autonomous_before_reply_commit
    async def fail(conn):
        await original(conn)
        raise RuntimeError('rollback')
    req._autonomous_before_reply_commit = fail
    assert not asyncio.run(save(database, req))
    assert queue.pending(database.db_path) == []


def test_post_state_queues_new_input_without_blocking_another_character(monkeypatch, intake):
    from test_normal_reply_batch import request as chat_request, reply, received
    from Backend.chat_modules import live_turn
    send, saved = intake
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        seen = []
        async def wait(*args, **kwargs):
            entered.set()
            await release.wait()
        monkeypatch.setattr(queue, 'wait_for_conversation', wait)
        async def handler(req, *args, **kwargs):
            ids = [m.message_id for m in req.messages]
            seen.append(ids)
            if ids == ['one']:
                req._post_reply_job_id = 'test-job'
            if ids == ['two']:
                assert release.is_set()
            return reply(req, ids[-1])
        first, _ = await received(await send(chat_request('第一条','one'), handler), 'one', saved)
        assert 'assistant_paragraph' in await asyncio.wait_for(anext(first), 1)
        await asyncio.wait_for(entered.wait(), 1)
        await first.aclose()  # Disconnect cannot cancel the state barrier.
        second, _ = await received(await send(chat_request('第二条','two'), handler), 'two', saved)
        other = chat_request('另一个角色','other')
        other.character_id = 'other-character'
        third, _ = await received(await send(other, handler), 'other', saved)
        out = ''.join([p async for p in third])
        assert 'assistant_paragraph' in out and ['two'] not in seen
        release.set()
        assert 'assistant_paragraph' in ''.join([p async for p in second])
        assert seen.count(['one']) == 1 and seen.count(['two']) == 1
        assert not live_turn.registry()
    asyncio.run(scenario())


from test_normal_reply_batch import intake


def test_json_delivery_returns_while_state_is_still_processing(monkeypatch, intake):
    from test_normal_reply_batch import request as chat_request, reply
    from Backend.chat_modules import live_turn
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def wait(*args, **kwargs):
            entered.set()
            await release.wait()
        monkeypatch.setattr(queue, 'wait_for_conversation', wait)
        async def handler(req, *args, **kwargs):
            req._post_reply_job_id = 'json-state-job'
            return reply(req, '已经交付')
        response = await asyncio.wait_for(live_turn.normal_live_response(
            chat_request('你好','json-one'), 'android', 'token', {}, use_json=True, handler=handler), 2)
        assert '已经交付' in response.body.decode()
        await asyncio.wait_for(entered.wait(), 1)
        owner = next(iter(live_turn.registry().values()))
        assert not owner.done.is_set()
        release.set()
        await asyncio.wait_for(owner.done.wait(), 1)
    asyncio.run(scenario())
