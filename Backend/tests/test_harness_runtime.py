import asyncio
import importlib.util
import json
import sys
import threading
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# The app package starts services and honors the global model-call pause on import.
# This adapter's isolated unit tests need neither those side effects nor credentials.
_package = types.ModuleType('tested_harness')
_package.__path__ = [str(Path(__file__).parents[1] / 'chat_modules')]
sys.modules['tested_harness'] = _package
_spec = importlib.util.spec_from_file_location("tested_harness.harness_runtime",
    Path(__file__).parents[1] / "chat_modules" / "harness_runtime.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
MODEL, run_harness_turn = _module.MODEL, _module.run_harness_turn


@pytest.fixture(autouse=True)
def isolated_runtime_mode(monkeypatch):
    # These fakes model one-shot SDK lifetimes. Pool/session behavior has its
    # own tests; a developer's .env must not silently select that other path.
    monkeypatch.setenv('PONYCHAT_HARNESS_POOL', '0')


def test_time_only_tool_policy_allows_more_than_twelve_calls_and_meters_them(monkeypatch):
    calls = []

    class Harness:
        def __init__(self, **config):
            self.config = config

        def run(self, prompt, on_notification=None):
            patch = json.loads(Path(self.config['patches'][0]).read_text(encoding='utf8'))
            config = patch[-1]['insert'][0]['config']
            for _ in range(16):
                request = urllib.request.Request(config['endpoint'] + '/read_memory', data=b'{}',
                    headers={'Authorization': 'Bearer ' + self.config['env']['PONYCHAT_HARNESS_TOKEN']})
                with urllib.request.urlopen(request, timeout=2) as response:
                    assert json.load(response) == {'value': {'found': True}}
            return types.SimpleNamespace(final_response='done', finish_reason='completed', events=[])

        def close(self):
            pass

    async def callback():
        calls.append(1)
        return {'found': True}

    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))
    result = asyncio.run(run_harness_turn('test', {}, {'read_memory': callback}, max_tool_calls=None))
    assert len(calls) == 16 and result['tool_call_count'] == 16


def test_native_image_prompt_blocks_reach_harness_unchanged(monkeypatch):
    prompt = [{"type": "text", "text": "describe"},
              {"type": "image", "mimeType": "image/png", "data": "cG5n"}]

    class Harness:
        def __init__(self, **config):
            self.config = config

        def run(self, actual, on_notification=None):
            assert actual == prompt
            patch = json.loads(Path(self.config['patches'][0]).read_text(encoding='utf-8'))
            assert any(row.get('insert') == [{
                'id': 'attachment-local', 'name': '@deepseek-ai/dsh-attachment-local'
            }] for row in patch)
            return types.SimpleNamespace(final_response='done', finish_reason='completed', events=[])

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))
    assert asyncio.run(run_harness_turn(prompt, {}, {}))['final_response'] == 'done'


def test_failed_turn_preserves_completed_step_usage(monkeypatch):
    class Harness:
        def __init__(self, **config):
            pass

        def run(self, prompt, on_notification=None):
            on_notification({'method':'event','params':{'type':'step/end','data':{
                'turn':1,'step':1,'usage':{'inputTokens':11,'outputTokens':3}}}})
            raise RuntimeError('synthetic failure after a settled step')

        def close(self):
            pass
    monkeypatch.setitem(sys.modules,'deepseek_harness',types.SimpleNamespace(DeepSeekHarness=Harness))
    with pytest.raises(RuntimeError) as error:
        asyncio.run(run_harness_turn('test',{},{}))
    assert error.value.harness_usage['usage']['prompt_tokens']==11
    assert error.value.harness_usage['llm_api_calls']==1
    assert error.value.harness_usage['incomplete'] is True


def test_capacity_serializes_and_cancelled_waiter_does_not_leak(monkeypatch):
    from tested_harness.harness_capacity import harness_slot
    monkeypatch.setenv('PONYCHAT_HARNESS_CONCURRENCY','1')
    async def scenario():
        active=0
        peak=0
        async def work():
            nonlocal active,peak
            async with harness_slot(1):
                active+=1;peak=max(peak,active)
                await asyncio.sleep(0.01)
                active-=1
        await asyncio.gather(work(),work(),work())
        assert peak==1
        async with harness_slot(1):
            waiting=asyncio.create_task(work())
            await asyncio.sleep(0)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):await waiting
        await work()
    asyncio.run(scenario())


def test_capacity_allows_ten_and_queues_eleventh(monkeypatch):
    from tested_harness.harness_capacity import harness_slot
    monkeypatch.setenv('PONYCHAT_HARNESS_CONCURRENCY','10')
    async def scenario():
        entered=[]
        release=asyncio.Event()
        ready=asyncio.Event()
        async def work(index):
            async with harness_slot(2):
                entered.append(index)
                if len(entered)==10:ready.set()
                await release.wait()
        tasks=[asyncio.create_task(work(i)) for i in range(11)]
        await asyncio.wait_for(ready.wait(),1)
        await asyncio.sleep(.02)
        assert len(entered)==10
        release.set()
        await asyncio.gather(*tasks)
        assert len(entered)==11
    asyncio.run(scenario())


def test_capability_bridge_and_scope_rejection(monkeypatch):
    instances = []
    callback_threads = []

    class Harness:
        def __init__(self, **config):
            self.config = config
            self.closed = False
            instances.append(self)

        def run(self, prompt, on_notification=None):
            patch = json.loads(Path(self.config['patches'][0]).read_text(encoding='utf-8'))
            disabled = {row['id'] for row in patch if row.get('disabled')}
            assert {'persistent-bash', 'persistent-pwsh', 'str-replace-editor'} <= disabled
            config = patch[-1]['insert'][0]['config']

            def request(body, token, name='read_memory'):
                req = urllib.request.Request(config['endpoint'] + '/' + name,
                    data=body, headers={'Authorization': 'Bearer ' + token})
                return json.loads(urllib.request.urlopen(req, timeout=5).read())

            token = self.config['env']['PONYCHAT_HARNESS_TOKEN']
            with pytest.raises(urllib.error.HTTPError) as error:
                request(b'{}', 'wrong-token')
            assert error.value.code == 403
            for forbidden_tool in ('pwsh', 'bash', 'str_replace_editor', 'other_user_memory'):
                with pytest.raises(urllib.error.HTTPError) as error:
                    request(b'{}', token, forbidden_tool)
                assert error.value.code == 404
            with pytest.raises(urllib.error.HTTPError) as error:
                request(b'{"user_id":"other"}', token)
            assert error.value.code == 422
            assert request(b'{}', token) == {'value': {'color': 'blue'}, 'budget': {'limit': 2, 'remaining': 0}}
            with pytest.raises(urllib.error.HTTPError) as error:
                request(b'{}', token)
            assert error.value.code == 409
            assert json.loads(error.value.read())['code'] == 'tool_budget_exhausted'
            return types.SimpleNamespace(final_response='blue', finish_reason='completed', events=[])

        def close(self):
            self.closed = True

    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))

    async def callback():
        callback_threads.append(threading.get_ident())
        return {'color': 'blue'}

    result = asyncio.run(run_harness_turn('color?', {'endpoint': 'https://example.test/v1/chat/completions'},
        {'read_memory': callback}, max_tool_calls=2))
    assert result['final_response'] == 'blue'
    assert result['llm_api_calls'] == 0
    assert result['tool_call_count'] == 2  # Invalid scope argument plus the valid call.
    assert result['usage'] == {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    assert callback_threads == [threading.get_ident()]
    assert instances[0].config['model'] == MODEL
    assert instances[0].config['reasoning_effort'] == 'low'
    assert instances[0].config['base_url'] == 'https://example.test/v1'
    assert instances[0].closed
    assert not Path(instances[0].config['dsh_home']).exists()


@pytest.mark.parametrize('cancel', [False, True])
def test_timeout_and_cancellation_close_runtime(monkeypatch, cancel):
    released = threading.Event()
    entered = threading.Event()
    instances = []

    class Harness:
        def __init__(self, **config):
            self.home = config['dsh_home']
            instances.append(self)

        def run(self, prompt, on_notification=None):
            entered.set()
            released.wait(5)
            raise RuntimeError('closed')

        def close(self):
            released.set()

    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))

    async def run():
        task = asyncio.create_task(run_harness_turn('test', {}, {}, timeout_seconds=.1))
        if cancel:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else asyncio.TimeoutError):
            await task

    asyncio.run(run())
    assert released.is_set()
    assert not Path(instances[0].home).exists()


def test_usage_counts_canonical_settled_steps_once_including_cached_input():
    first = {'inputTokens': 293, 'outputTokens': 52, 'totalTokens': 345, 'reasoningTokens': 23}
    second = {'inputTokens': 112, 'cacheReadTokens': 256, 'outputTokens': 9, 'totalTokens': 377}
    events = [
        {'type': 'assistant/chunk', 'data': {'turn': 1, 'step': 1,
            'chunk': {'type': 'usage', 'usage': first}}},
        {'type': 'assistant/message', 'data': {'turn': 1, 'step': 1, 'usage': first}},
        {'type': 'step/end', 'data': {'turn': 1, 'step': 1}},
        {'type': 'step/end', 'data': {'turn': 1, 'step': 1}},
        {'type': 'assistant/message', 'data': {'turn': 1, 'step': 2, 'usage': second}},
        {'type': 'step/end', 'data': {'turn': 1, 'step': 2, 'usage': second}},
        {'type': 'assistant/message', 'data': {'turn': 2, 'step': 1,
            'usage': {'inputTokens': 5, 'outputTokens': 4}}},
        {'type': 'step/end', 'data': {'turn': 2, 'step': 1}},
        # A failed settled attempt is a call, but missing usage is not fabricated.
        {'type': 'step/end', 'data': {'turn': 2, 'step': 2}},
        # A provider response remains billable if Harness fails before emitting
        # its matching step/end bookkeeping event.
        {'type': 'assistant/message', 'data': {'turn': 2, 'step': 3,
            'usage': {'inputTokens': 7, 'outputTokens': 2, 'totalTokens': 9}}},
        {'type': 'step/start', 'data': {'turn': 2, 'step': 3}},
        # A started call interrupted before its response still costs one point.
        {'type': 'step/start', 'data': {'turn': 2, 'step': 4}},
        {'type': 'step/start', 'data': {'turn': 2, 'step': 4}},
    ]
    assert _module.summarize_harness_usage(events) == {
        'usage': {'prompt_tokens': 673, 'completion_tokens': 67, 'total_tokens': 740},
        'llm_api_calls': 6,
    }


def test_schema_tools_accept_bounded_arguments_and_reject_scope_injection(monkeypatch):
    received = []
    schema = {'type': 'object', 'properties': {
        'query': {'type': 'string', 'minLength': 1, 'maxLength': 30},
        'cursor': {'type': 'integer', 'minimum': 0, 'maximum': 100},
        'drafts': {'type': 'array', 'maxItems': 2, 'items': {'type': 'object',
            'properties': {'text': {'type': 'string', 'maxLength': 40}}, 'required': ['text']}},
    }, 'required': ['query']}

    class Harness:
        def __init__(self, **config):
            self.config = config

        def run(self, prompt, on_notification=None):
            patch = json.loads(Path(self.config['patches'][0]).read_text(encoding='utf-8'))
            config = patch[-1]['insert'][0]['config']
            advertised = config['tools'][0]['parameters']
            assert advertised['additionalProperties'] is False
            assert advertised['properties']['drafts']['items']['additionalProperties'] is False

            def request(args):
                req = urllib.request.Request(config['endpoint'] + '/search_memory',
                    data=json.dumps(args).encode(), headers={'Authorization':
                        'Bearer ' + self.config['env']['PONYCHAT_HARNESS_TOKEN']})
                return json.loads(urllib.request.urlopen(req, timeout=5).read())

            invalid = [{'query': 'ok', 'user_id': 'other'}, {'query': 1}, {'query': ''},
                       {'query': 'x' * 31}, {'query': 'ok', 'cursor': True},
                       {'query': 'ok', 'cursor': -1}, {'cursor': 1},
                       {'query': 'ok', 'drafts': [{'text': 'x', 'session_id': 'other'}]},
                       {'query': 'ok', 'drafts': [{'text': 'x'}] * 3}]
            for args in invalid:
                with pytest.raises(urllib.error.HTTPError) as error:
                    request(args)
                assert error.value.code == 422
            assert request({'query': '颜色', 'cursor': 5, 'drafts': [{'text': '蓝色'}]})['value'] == 'found'
            return types.SimpleNamespace(final_response='done', finish_reason='completed', events=[])

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))

    async def callback(args):
        received.append(args)
        return 'found'

    asyncio.run(run_harness_turn('lookup', {}, {'search_memory': _module.HarnessTool(
        callback=callback, description='Find current user memories', parameters=schema)}))
    assert received == [{'query': '颜色', 'cursor': 5, 'drafts': [{'text': '蓝色'}]}]
    for forbidden in ('user_id', 'username', 'sessionId', 'character_id', 'tenant', 'account_id'):
        with pytest.raises(ValueError, match='scope identifiers'):
            _module._closed_schema({'type': 'object', 'properties': {forbidden: {'type': 'string'}}})
    with pytest.raises(ValueError, match='unknown fields'):
        _module._closed_schema({'type': 'object', 'additionalProperties': True})
    references = _module._closed_schema({'type': 'object', 'properties': {
        'source_message_ids': {'type': 'array', 'items': {'type': 'string'}},
        'entry_id': {'type': 'string'}, 'before_sequence': {'type': 'integer', 'minimum': 0}}})
    _module._validate_arguments({'source_message_ids': ['message-1'],
        'entry_id': 'memory-1', 'before_sequence': 5}, references)


def test_only_explicit_public_validation_errors_reach_tool_client(monkeypatch):
    class Harness:
        def __init__(self, **config):
            self.config = config

        def run(self, prompt, on_notification=None):
            patch = json.loads(Path(self.config['patches'][0]).read_text(encoding='utf-8'))
            endpoint = patch[-1]['insert'][0]['config']['endpoint']
            for name, expected_status, expected_error in (
                ('stage_memory', 422, 'occurred_at must be ISO 8601 with timezone; use source_occurred_at'),
                ('private_failure', 500, 'Chat capability failed'),
            ):
                req = urllib.request.Request(endpoint + '/' + name, data=b'{}',
                    headers={'Authorization': 'Bearer ' + self.config['env']['PONYCHAT_HARNESS_TOKEN']})
                with pytest.raises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(req, timeout=5)
                assert error.value.code == expected_status
                body = json.loads(error.value.read())
                assert body['error'] == expected_error
                assert set(body) == {'error', 'budget'}
                assert 'private/server/path' not in json.dumps(body)
            return types.SimpleNamespace(final_response='done', finish_reason='completed', events=[])

        def close(self):
            pass

    async def public_failure():
        raise _module.HarnessToolValidationError(
            'occurred_at must be ISO 8601 with timezone; use source_occurred_at')

    async def private_failure():
        raise ValueError('secret at private/server/path')

    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))
    asyncio.run(run_harness_turn('repair', {}, {'stage_memory': public_failure,
                                               'private_failure': private_failure}))


@pytest.mark.parametrize('pooled', [False, True])
def test_budget_exhaustion_stops_worker_and_preserves_usage(monkeypatch, pooled):
    import importlib
    from dataclasses import make_dataclass
    Notification = make_dataclass('Notification', ['method', 'payload'], slots=True)
    pool = importlib.import_module('tested_harness.harness_pool')
    monkeypatch.setenv('PONYCHAT_HARNESS_POOL', '1' if pooled else '0')
    monkeypatch.setattr(pool, 'memory_allows_start', lambda *_: True)
    closed = threading.Event()
    attempted = []
    callbacks = []
    instances = []

    class Harness:
        def __init__(self, **config):
            self.config = config
            instances.append(self)

        def start(self):
            pass

        def run(self, prompt, on_notification=None, session_id=None):
            config = json.loads(Path(self.config['patches'][0]).read_text())[-1]['insert'][0]['config']
            headers = {'Authorization': 'Bearer '+self.config['env']['PONYCHAT_HARNESS_TOKEN']}
            if session_id:
                headers['X-PonyChat-Session'] = session_id
            on_notification(Notification('session.event', {'event': {'type':'step/end', 'data':{
                'turn':1, 'step':1, 'usage':{'inputTokens':10,'outputTokens':2}}}}))
            for _ in range(2):
                req = urllib.request.Request(config['endpoint']+'/stage', data=b'{}', headers=headers)
                try:
                    body = json.load(urllib.request.urlopen(req, timeout=2))
                    assert body['budget']['remaining'] == 0
                    attempted.append(200)
                except urllib.error.HTTPError as exc:
                    body = json.loads(exc.read())
                    attempted.append(exc.code)
                    assert body['code'] == 'tool_budget_exhausted' and body['retryable'] is False
            # Simulate an SDK that would otherwise keep reasoning until timeout.
            assert closed.wait(2)
            on_notification(Notification('session.event', {'event': {'type':'step/end', 'data':{
                'turn':1, 'step':2, 'usage':{'inputTokens':3,'outputTokens':1}}}}))
            raise RuntimeError('runtime stopped')

        def close(self):
            closed.set()

    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))
    async def stage():
        callbacks.append('saved draft')
        return {'staged': True}
    result = asyncio.run(run_harness_turn('review', {}, {'stage':stage},
        max_tool_calls=1, stop_on_tool_budget=True, timeout_seconds=4))
    assert attempted == [200, 409]
    assert callbacks == ['saved draft']
    assert result['finish_reason'] == 'tool_budget_exhausted'
    assert result['final_response'] is None
    assert result['llm_api_calls'] == 2 and result['usage']['total_tokens'] == 16
    assert closed.is_set()
    assert not Path(instances[0].config['dsh_home']).exists()


@pytest.mark.parametrize('slow_tool', [False, True])
def test_tool_time_budget_stops_runtime_after_first_tool(monkeypatch, slow_tool):
    monkeypatch.setenv('PONYCHAT_HARNESS_POOL', '0')
    closed = threading.Event()
    callbacks = []

    class Harness:
        def __init__(self, **config):
            self.config = config

        def run(self, prompt, on_notification=None):
            config = json.loads(Path(self.config['patches'][0]).read_text())[-1]['insert'][0]['config']
            headers = {'Authorization': 'Bearer ' + self.config['env']['PONYCHAT_HARNESS_TOKEN']}
            request = urllib.request.Request(config['endpoint'] + '/stage', data=b'{}', headers=headers)
            if slow_tool:
                try:
                    urllib.request.urlopen(request, timeout=2)
                except (OSError, urllib.error.HTTPError):
                    pass
            else:
                assert json.load(urllib.request.urlopen(request, timeout=2))['value']['staged'] is True
            assert closed.wait(2)
            raise RuntimeError('runtime stopped')

        def close(self):
            closed.set()

    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))

    async def stage():
        callbacks.append('saved draft')
        if slow_tool:
            try:
                await asyncio.sleep(10)
            finally:
                callbacks.append('cancelled')
        return {'staged': True}

    result = asyncio.run(run_harness_turn(
        'review', {}, {'stage': stage}, max_tool_calls=12, stop_on_tool_budget=True,
        tool_timeout_seconds=.05, timeout_seconds=4))
    assert callbacks == (['saved draft', 'cancelled'] if slow_tool else ['saved draft'])
    assert result['finish_reason'] == 'tool_time_budget_exhausted'
    assert result['tool_call_count'] == 1
    assert closed.is_set()
