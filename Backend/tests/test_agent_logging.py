"""Exercise real log files, SDK callbacks, concurrency and admin index/export."""
import asyncio
import json
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from Backend import utils
from Backend.chat_modules import agent_logging as logs, harness_runtime as runtime
from Backend.routes.admin import llm_logs, llm_log_indexer


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, '_CHAT_LOGS_DIR', str(tmp_path / 'logs'))
    monkeypatch.setenv('PONYCHAT_HARNESS_POOL', '0')
    async def name(_):
        return 'Test character'
    monkeypatch.setattr(utils, '_get_character_name', name)
    return tmp_path / 'logs'


def read_logs(root):
    return [(path, llm_logs._read_log_detail(str(path))) for path in sorted(root.rglob('*.js'))]


def test_sdk_steps_tools_and_errors_survive_disk_and_index(log_dir, monkeypatch):
    events = [
        {'type': 'step/start', 'data': {'turn': 1, 'step': 1}},
        {'type': 'assistant/message', 'data': {'turn': 1, 'step': 1,
            'content': 'The word error is ordinary reply text', 'usage': {'inputTokens': 11, 'outputTokens': 3}}},
        {'type': 'step/end', 'data': {'turn': 1, 'step': 1}},
    ]
    class Harness:
        def __init__(self, **config):
            self.config = config

        def run(self, prompt, on_notification=None):
            patch = json.loads(Path(self.config['patches'][0]).read_text(encoding='utf-8'))
            endpoint = patch[-1]['insert'][0]['config']['endpoint']
            for args in ({'query': 'ok'}, {'query': 'fail'}, {'unexpected': True}):
                req = urllib.request.Request(endpoint + '/search', data=json.dumps(args).encode(),
                    headers={'Authorization': 'Bearer ' + self.config['env']['PONYCHAT_HARNESS_TOKEN']})
                try:
                    urllib.request.urlopen(req, timeout=5).read()
                except urllib.error.HTTPError:
                    pass
            for event in events:
                on_notification({'params': event})
            return types.SimpleNamespace(final_response='error is just text', finish_reason='completed', events=events)

        def close(self):
            pass

    async def search(args):
        if args['query'] == 'fail':
            raise RuntimeError('Synthetic lookup failure')
        return {'matches': ['verifiable fact'], 'api_key': 'DO_NOT_LOG'}

    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))
    tool = runtime.HarnessTool(search, 'search source text', {'type': 'object',
        'properties': {'query': {'type': 'string'}}, 'required': ['query']})

    async def scenario():
        async with logs.log_scope('alice', 'pony', 'normal', params={'conversation_id': 'conv-a'}):
            return await runtime.run_harness_turn('synthetic prompt', {'api_key': 'CONFIG_SECRET'},
                {'search': tool}, system_prompt='synthetic system')
    result = asyncio.run(scenario())
    assert result['final_response'] == 'error is just text'
    records = read_logs(log_dir)
    assert len({r['params']['trace_id'] for _, r in records}) == 1
    assert all(r['params']['conversation_id'] == 'conv-a' for _, r in records)
    by_stage = {r['stage']: r for _, r in records}
    assert {'AGENT_RUN_REQUEST', 'AGENT_RUN_RESPONSE', 'AGENT_STEP_START',
            'AGENT_STEP_RESPONSE', 'AGENT_STEP_END', 'AGENT_TOOL_RESULT', 'AGENT_EXECUTION_END'} <= by_stage.keys()
    run = by_stage['AGENT_RUN_RESPONSE']['data']
    assert run['request']['system_prompt'] == 'synthetic system'
    assert run['request']['prompt'] == 'synthetic prompt'
    assert run['usage']['total_tokens'] == 14
    assert len(run['sdk_events']) == 3
    tools = [e['data'] for e in run['events'] if e['type'] == 'tool/execution']
    assert [e['http_status'] for e in tools] == [200, 500, 422]
    assert tools[0]['result']['matches'] == ['verifiable fact']
    assert tools[1]['error']['message'] == 'Synthetic lookup failure'
    assert all(e['latency_ms'] >= 0 for e in tools)
    text = '\n'.join(p.read_text(encoding='utf-8') for p, _ in records)
    assert 'DO_NOT_LOG' not in text and 'CONFIG_SECRET' not in text
    assert 'REDACTED' in text
    indexed = [llm_log_indexer._parse_log_file(str(p))[0] for p, _ in records]
    assert sum(e['total_tokens'] for e in indexed) == 14
    for entry, (_, raw) in zip(indexed, records):
        assert entry['status'] == llm_logs._infer_status_from_log(raw)
    assert next(e for e in indexed if e['stage'] == 'AGENT_RUN_RESPONSE')['status'] == 'success'


@pytest.mark.parametrize('failure', [RuntimeError('failed'), TimeoutError('expired'), asyncio.CancelledError()])
def test_failure_and_partial_usage_are_recorded_without_swallowing(log_dir, failure):
    @logs.logged_harness
    async def fail(*args, **kwargs):
        logs.record_event('assistant/message', {'step': 1, 'content': 'partial'})
        failure.harness_usage = {'usage': {'prompt_tokens': 7, 'completion_tokens': 2}, 'llm_api_calls': 1}
        raise failure
    async def scenario():
        async with logs.log_scope('alice', 'pony', 'normal'):
            await fail('prompt', {}, {})
    with pytest.raises(type(failure)):
        asyncio.run(scenario())
    records = {r['stage']: r for _, r in read_logs(log_dir)}
    assert records['AGENT_RUN_RESPONSE']['data']['status'] == logs.outcome(failure)
    assert records['AGENT_EXECUTION_END']['data']['status'] == logs.outcome(failure)
    assert records['AGENT_RUN_RESPONSE']['data']['usage']['prompt_tokens'] == 7
    assert records['AGENT_STEP_RESPONSE']['data']['events'][0]['data']['content'] == 'partial'


def test_concurrent_scopes_retries_and_filenames_remain_isolated(log_dir):
    @logs.logged_harness
    async def run(prompt, *_args, **_kwargs):
        await asyncio.sleep(.001)
        logs.record_event('assistant/message', {'content': prompt})
        return {'final_response': prompt, 'finish_reason': 'completed'}
    async def user(name):
        async with logs.log_scope(name, 'pony', 'normal', params={'conversation_id': name}):
            for _ in range(2):
                await run(name, {}, {})
            await asyncio.gather(*(logs.write('SAME_STAGE', {'status': 'success'}) for _ in range(12)))
    async def scenario():
        await asyncio.gather(user('alice'), user('bob'))
        assert logs.current_params() == {}
    asyncio.run(scenario())
    records = [r for _, r in read_logs(log_dir)]
    assert sum(r['stage'] == 'SAME_STAGE' for r in records) == 24
    traces = {user: {r['params']['trace_id'] for r in records if r['username'] == user} for user in ('alice', 'bob')}
    assert len(traces['alice']) == len(traces['bob']) == 1
    assert traces['alice'].isdisjoint(traces['bob'])
    for user in traces:
        runs = [r for r in records if r['username'] == user and r['stage'] == 'AGENT_RUN_RESPONSE']
        assert {r['params']['run_number'] for r in runs} == {1, 2}
        assert all(r['data']['final_response'] == user for r in runs)


def test_admin_detail_and_export_respect_agent_trace(log_dir, tmp_path, monkeypatch):
    async def scenario():
        for user in ('alice', 'bob'):
            async with logs.log_scope(user, 'pony', 'normal', params={'trace_id': user, 'conversation_id': user}):
                await logs.write('AGENT_RUN_RESPONSE', {'kind': 'agent_run', 'status': 'success',
                    'request': {'prompt': user}, 'final_response': user})
        db = str(tmp_path / 'index.sqlite')
        indexer = llm_log_indexer.LLMLogIndexer(db)
        indexer.logs_root = str(log_dir)
        await indexer.init_schema()
        await indexer.scan_all()
        monkeypatch.setattr(llm_logs, '_get_db_path', lambda: db)
        async def ensure():
            return indexer
        monkeypatch.setattr(llm_logs, '_ensure_indexer', ensure)
        app = FastAPI()
        app.include_router(llm_logs.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            exported = await client.get('/llm-logs/export', params={'traceId': 'alice'})
            assert exported.status_code == 200
            assert all(r['username'] == 'alice' for r in exported.json())
            assert len(exported.json()) == 2
            import aiosqlite
            async with aiosqlite.connect(db) as conn:
                row = await (await conn.execute("SELECT id FROM llm_log_index WHERE trace_id='alice' AND stage='AGENT_RUN_RESPONSE'")).fetchone()
            detail = (await client.get(f'/llm-logs/{row[0]}')).json()
            assert detail['request']['prompt'] == 'alice'
            assert detail['traceId'] == 'alice' and detail['conversationId'] == 'alice'
    asyncio.run(scenario())


def test_redaction_keeps_text_but_omits_image_bytes():
    original = {'type': 'image', 'data': 'BASE64_BYTES', 'apiKey': 'secret', 'caption': 'hello'}
    safe = logs.snapshot(original)
    assert safe['data'] == '[image bytes omitted]' and safe['caption'] == 'hello'
    assert original['data'] == 'BASE64_BYTES'
    assert 'secret' not in logs.snapshot('Bearer secret')


def test_logging_io_failure_does_not_change_reply(monkeypatch):
    async def broken(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(utils, 'save_chat_debug_log', broken)
    @logs.logged_harness
    async def run(*args, **kwargs):
        logs.record_event('assistant/message', {'content': 'ok'})
        return {'final_response': 'ok', 'finish_reason': 'completed'}
    async def scenario():
        async with logs.log_scope('test', 'pony', 'normal'):
            return await run('prompt', {}, {})
    assert asyncio.run(scenario())['final_response'] == 'ok'


@pytest.mark.parametrize('saved', [True, False])
def test_persistence_result_keeps_generation_trace(log_dir, saved):
    @logs.logged_persistence
    async def persist(*args, **kwargs):
        return saved, '' if saved else 'synthetic database error', ['reply-1'] if saved else None
    request = types.SimpleNamespace(username='alice', character_id='pony', mode='normal',
        conversation_id='conv', _agent_log_params={'trace_id': 'generation-trace', 'request_id': 'generation-trace'})
    assert asyncio.run(persist(request, runtime.MODEL, 'final visible text'))[0] is saved
    record = read_logs(log_dir)[0][1]
    assert record['params']['trace_id'] == 'generation-trace'
    assert record['data']['save_ok'] is saved
    assert record['data']['status'] == ('success' if saved else 'error')
    assert record['data']['submitted_reply'] == 'final visible text'


def test_game_agent_attempts_share_request_trace():
    from Backend.galgame.metering import game_agent_metering_kwargs
    request = utils.ChatRequest(messages=[], username='alice', character_id='pony',
                                conversation_id='conv', mode='galgame')
    first = game_agent_metering_kwargs(request)
    second = game_agent_metering_kwargs(request)
    assert first['record_usage'] == 'main' and first['usage_meter_username'] == 'alice'
    assert first['agent_debug_params']['trace_id'] == second['agent_debug_params']['trace_id']
    assert first['agent_debug_params']['conversation_id'] == 'conv'


def test_summary_tokens_are_not_double_counted_and_legacy_is_preserved():
    data = {'usage': {'prompt_tokens': 7, 'completion_tokens': 2}}
    assert llm_log_indexer._extract_tokens(data) == (7, 2, 9)
    assert llm_log_indexer._extract_tokens({**data, 'usage_scope': 'summary'}) == (0, 0, 0)


def test_final_sdk_messages_are_recovered_once(log_dir):
    @logs.logged_harness
    async def run(*args, **kwargs):
        event = {'type': 'assistant/message', 'data': {'turn': 1, 'step': 1, 'content': 'settled reply'}}
        logs.reconcile_sdk_events([event, event])
        logs.reconcile_sdk_events([event])
        return {'finish_reason': 'completed', 'final_response': 'settled reply'}
    async def scenario():
        async with logs.log_scope('test', 'pony', 'normal'):
            await run('prompt', {}, {})
    asyncio.run(scenario())
    records = [r for _,r in read_logs(log_dir) if r['stage']=='AGENT_STEP_RESPONSE']
    assert len(records)==1
    assert records[0]['data']['events'][0]['data']['captured_on_completion'] is True


def test_final_sdk_messages_do_not_duplicate_live_callbacks(log_dir):
    @logs.logged_harness
    async def run(*args, **kwargs):
        data = {'turn': 1, 'step': 1, 'content': 'live reply'}
        logs.record_event('assistant/message', data)
        logs.reconcile_sdk_events([{'type': 'assistant/message', 'data': data}])
        return {'finish_reason': 'completed', 'final_response': 'live reply'}
    async def scenario():
        async with logs.log_scope('test', 'pony', 'normal'):
            await run('prompt', {}, {})
    asyncio.run(scenario())
    records = [r for _,r in read_logs(log_dir) if r['stage']=='AGENT_STEP_RESPONSE']
    assert len(records)==1
    assert 'captured_on_completion' not in records[0]['data']['events'][0]['data']
