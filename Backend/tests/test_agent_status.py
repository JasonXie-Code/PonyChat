"""Public progress is scoped, read-only, and contains no model/tool payloads."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI

from Backend.chat_modules import agent_status as status, agent_logging as logs
from Backend.routes import status as routes, auth


@pytest.fixture(autouse=True)
def isolated_status(monkeypatch, tmp_path):
    monkeypatch.setenv('PONYCHAT_AGENT_STATUS_DB_PATH', str(tmp_path / 'status.sqlite3'))


def scope(user='alice', character='pony', mode='normal', trace='trace', conversation='conv'):
    return dict(username=user, character_id=character, mode=mode, model='actual-model',
                params={'trace_id': trace, 'conversation_id': conversation})


def test_model_tool_events_deduplicate_and_do_not_publish_private_payloads():
    key = status.begin(scope())
    for _ in range(2):
        status.event(key, 'run1', 'step/start', {'turn': 1, 'step': 1, 'prompt': 'PRIVATE'})
        status.event(key, 'run1', 'assistant/message', {'turn': 1, 'step': 1, 'content': 'PRIVATE'})
        status.event(key, 'run1', 'tool/start', {'tool': 'read_memory', 'tool_call_id': 'call1', 'arguments': 'PRIVATE'})
        status.event(key, 'run1', 'tool/execution', {'tool': 'read_memory', 'tool_call_id': 'call1', 'result': 'PRIVATE'})
    status.event(key, 'run1', 'tool/execution', {'tool': 'read_memory', 'tool_call_id': 'denied', 'billable': False})
    result = status.read('alice', 'pony', 'normal', 'conv')
    assert result['model_calls'] == 1 and result['tool_calls'] == 1 and result['points'] == 2
    assert result['model'] == 'actual-model' and result['status'] == 'running'
    assert 'PRIVATE' not in json.dumps(result) and '_runs' not in result


def test_retries_accumulate_and_finished_duration_stops(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(status.time, 'time', lambda: now[0])
    key = status.begin(scope())
    status.settle_run(key, 'a', {'llm_api_calls': 2, 'tool_call_count': 3})
    now[0] += 10
    status.finish(key, 'error')
    status.begin(scope())
    status.settle_run(key, 'b', {'llm_api_calls': 1, 'tool_call_count': 2})
    now[0] += 5
    status.finish(key, 'success')
    now[0] += 20
    result = status.read('alice', 'pony', 'normal')
    assert result['elapsed_ms'] == 15000 and result['points'] == 8


def test_isolation_and_active_foreground_priority():
    key = status.begin(scope())
    status.begin(scope(mode='agent_memory', trace='background', conversation=''))
    assert status.read('alice', 'pony', 'normal')['run_id'] == 'trace'
    assert status.read('bob', 'pony', 'normal') is None
    assert status.read('alice', 'other', 'normal') is None
    assert status.read('alice', 'pony', 'galgame') is None
    status.finish(key, 'success')
    result = status.read('alice', 'pony', 'normal', 'other-conversation')
    assert result['run_id'] == 'background' and result['phase'] == 'background_memory'


def test_automatic_retry_keeps_task_running_and_accumulates_calls():
    key = status.begin(scope())
    status.settle_run(key, 'a', {'llm_api_calls': 4, 'tool_call_count': 2})
    started = status.read('alice', 'pony', 'normal')['started_at']
    status.retry(key, 1)
    running = status.read('alice', 'pony', 'normal')
    assert running['status'] == 'running' and running['finished_at'] is None
    assert running['started_at'] == started and running['retry_count'] == 1
    assert '立即重试' in running['activity']
    status.settle_run(key, 'b', {'llm_api_calls': 1, 'tool_call_count': 0})
    status.finish(key, 'success')
    result = status.read('alice', 'pony', 'normal')
    assert result['status'] == 'success' and result['points'] == 7


def test_parallel_tool_events_do_not_lose_counts():
    key = status.begin(scope())
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda i: status.event(key, 'a', 'tool/start',
            {'tool': 'read_memory', 'tool_call_id': str(i)}), range(20)))
    assert status.read('alice', 'pony', 'normal')['tool_calls'] == 20


def test_guest_progress_belongs_to_the_open_conversation():
    current = scope(character='guest')
    current['status_character_id'] = 'pony'
    status.begin(current)
    assert status.read('alice', 'pony', 'normal', 'conv') is not None
    assert status.read('alice', 'guest', 'normal', 'conv') is None


def test_game_memory_is_visible_as_background_work():
    current = scope(mode='galgame_lock')
    current['params']['phase'] = 'background_memory'
    status.begin(current)
    assert status.read('alice', 'pony', 'galgame_lock')['phase'] == 'background_memory'


def test_running_state_becomes_stale_instead_of_running_forever(monkeypatch):
    status.begin(scope())
    now = status.time.time()
    monkeypatch.setattr(status.time, 'time', lambda: now + 601)
    assert status.read('alice', 'pony', 'normal')['status'] == 'stale'


def test_service_restart_does_not_leave_a_ghost_running_task(monkeypatch):
    status.begin(scope())
    monkeypatch.setattr(status, '_process_alive', lambda identity: False)
    result = status.read('alice', 'pony', 'normal')
    assert result['status'] == 'stale' and '_process' not in result


def test_status_api_uses_verified_identity_and_disallows_writes(monkeypatch):
    status.begin(scope())
    async def verify(token):
        return {'alice-token': 'alice', 'bob-token': 'bob'}.get(token)
    monkeypatch.setattr(auth, 'auth_token_verify', verify)
    app = FastAPI()
    app.include_router(routes.router)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            path = '/api/agent/status?character_id=pony&mode=normal&conversation_id=conv'
            assert (await client.get(path)).status_code == 401
            other = await client.get(path + '&username=alice', headers={'X-Chat-Auth': 'bob-token'})
            assert other.json()['agent'] is None
            own = await client.get(path, headers={'X-Chat-Auth': 'alice-token'})
            assert own.json()['agent']['model'] == 'actual-model'
            assert own.headers['cache-control'] == 'no-store'
            assert (await client.post(path)).status_code == 405
    asyncio.run(scenario())


def test_actual_log_scope_publishes_harness_progress(monkeypatch):
    async def no_write(*args, **kwargs):
        pass
    monkeypatch.setattr(logs, 'write', no_write)
    @logs.logged_harness
    async def runner(*args, **kwargs):
        logs.record_event('step/start', {'turn': 1, 'step': 1})
        logs.record_event('tool/start', {'tool': 'read_memory', 'tool_call_id': 'x'})
        return {'finish_reason': 'completed', 'llm_api_calls': 1, 'tool_call_count': 1}
    async def scenario():
        async with logs.log_scope('alice', 'pony', 'normal', params={'conversation_id': 'conv'}):
            await runner('PRIVATE', {}, {})
    asyncio.run(scenario())
    result = status.read('alice', 'pony', 'normal', 'conv')
    assert result['status'] == 'success' and result['points'] == 2


def test_current_tools_track_overlapping_calls_and_clear_at_completion():
    key = status.begin(scope())
    status.event(key, 'a', 'tool/start', {'tool': 'read_memory', 'tool_call_id': 'one'})
    status.event(key, 'a', 'tool/start', {'tool': 'web_search', 'tool_call_id': 'two'})
    assert status.read('alice', 'pony', 'normal')['current_tools'] == ['read_memory', 'web_search']
    status.event(key, 'a', 'tool/execution', {'tool': 'read_memory', 'tool_call_id': 'one'})
    assert status.read('alice', 'pony', 'normal')['current_tools'] == ['web_search']
    status.settle_run(key, 'a', {})
    assert status.read('alice', 'pony', 'normal')['current_tools'] == []
    status.event(key, 'b', 'tool/start', {'tool': 'read_memory', 'tool_call_id': 'three'})
    status.finish(key, 'error')
    assert status.read('alice', 'pony', 'normal')['current_tools'] == []


@pytest.mark.parametrize('model', ['qwen3.5-4b-local', 'deepseek-flash'])
@pytest.mark.parametrize('fail', [False, True])
def test_status_and_logs_use_invocation_model_before_completion(monkeypatch, model, fail):
    recorded = []
    async def save(*args, **kwargs):
        recorded.append(args[3])
    from Backend import utils
    monkeypatch.setattr(utils, 'save_chat_debug_log', save)

    @logs.logged_harness
    async def runner(*args, **kwargs):
        assert status.read('alice', 'pony', 'normal', 'conv')['model'] == model
        if fail:
            raise RuntimeError('synthetic failure')
        return {'finish_reason': 'completed'}

    async def scenario():
        config = {'model_name': model}
        async with logs.log_scope('alice', 'pony', 'normal',
                                  params={'conversation_id': 'conv'}, model_config=config):
            assert status.read('alice', 'pony', 'normal', 'conv')['model'] == model
            await runner('synthetic', config, {})
    if fail:
        with pytest.raises(RuntimeError, match='synthetic failure'):
            asyncio.run(scenario())
    else:
        asyncio.run(scenario())
    assert status.read('alice', 'pony', 'normal', 'conv')['model'] == model
    assert recorded and all(value == model for value in recorded)


def test_recent_tools_remain_visible_after_execution_and_completion():
    key = status.begin(scope())
    status.event(key, 'run-1', 'tool/start', {
        'tool_call_id': 'call-1', 'tool': 'read_memory', 'billable': True})
    status.event(key, 'run-1', 'tool/execution', {
        'tool_call_id': 'call-1', 'tool': 'read_memory', 'billable': True})
    running = status.read('alice', 'pony', 'normal')
    assert running['current_tools'] == []
    assert running['recent_tools'] == ['read_memory']
    status.finish(key, 'success')
    completed = status.read('alice', 'pony', 'normal')
    assert completed['recent_tools'] == ['read_memory']


def test_multiple_agents_include_modes_and_conversations_but_isolate_owner_character():
    first = status.begin(scope(trace='older'))
    status.finish(first, 'success')
    status.begin(scope(trace='foreground'))
    status.begin(scope(trace='another', conversation='other-conversation'))
    status.begin(scope(mode='agent_memory', trace='background', conversation=''))
    status.begin(scope(mode='galgame', trace='game'))
    status.begin(scope(user='bob', trace='other-user'))
    status.begin(scope(character='other', trace='other-character'))
    agents = status.read_all('alice', 'pony', 'normal')
    assert {a['run_id'] for a in agents} == {'foreground', 'another', 'background', 'game'}
    assert all('_runs' not in a and '_process' not in a for a in agents)
    assert status.read_all('unknown', 'pony', 'normal') == []


def test_agent_list_retains_latest_completed_result_per_task_kind():
    for trace in ('first', 'second'):
        key = status.begin(scope(trace=trace))
        status.finish(key, 'success')
    bg = status.begin(scope(mode='agent_memory', trace='background', conversation=''))
    status.finish(bg, 'success')
    assert {a['run_id'] for a in status.read_all('alice', 'pony', 'normal')} == {'second', 'background'}
