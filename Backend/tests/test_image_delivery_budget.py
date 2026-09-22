"""Exploration limits cannot strand inspected images or reopen exploration."""
import asyncio
import importlib
import json
import time
import types
import urllib.error
import urllib.request

import pytest

from test_autonomous_normal import normal, turn, run, model_result
from test_autonomous_prompt_skills import session
from test_harness_runtime import run_harness_turn


@pytest.mark.parametrize('finish', ['tool_time_budget_exhausted', 'tool_budget_exhausted'])
def test_finalization_keeps_pixels_and_only_sending_even_without_profile_intro(finish):
    images = importlib.import_module(normal.__package__ + '.autonomous_web_images').WebImageTools(
        None, username='synthetic', transfer_store=lambda *args: '/transfer/synthetic')
    images.candidates['web:test'] = {'source_url': 'https://example.org', 'title': 'test'}
    images.downloaded['web:test'] = {'data': b'pixels', 'mime_type': 'image/png', 'width': 1, 'height': 1}
    current = session(home='')
    calls = []

    async def transport(prompt, config, tools, **options):
        calls.append(options)
        if len(calls) == 1:
            await tools['load_chat_skill'].callback({'name': 'instant_messaging'})
            options['tool_budget_state'].update(calls=12, deadline=time.monotonic()-1)
            return model_result(finish=finish)
        assert set(tools) == {'stage_web_image'}
        assert options['timeout_seconds'] is None
        assert options['tool_timeout_seconds'] is None and options['max_tool_calls'] is None
        assert any(b.get('data') == 'cGl4ZWxz' for b in prompt)
        data = json.loads(prompt[0]['text'])
        assert data['required_tools_before_reply'] == []
        staged = await tools['stage_web_image'].callback({'image_ref': 'web:test', 'match_kind': 'approximate'})
        assert staged['staged']
        return model_result('找到一张近似的，发给你了。')

    result = run(turn(web_image_tools=images, harness_runner=current.runner(transport)))
    assert len(calls) == 2 and images.selected == {'web:test': 1}
    assert '发给你了' in result['envelope']


@pytest.mark.parametrize('already_exhausted', [False, True])
def test_sending_outlives_exploration_and_cannot_reopen_search(monkeypatch, already_exhausted):
    monkeypatch.setenv('PONYCHAT_HARNESS_POOL', '0')
    state = {'calls': 12, 'deadline': time.monotonic()-1} if already_exhausted else {}
    calls = []

    class Harness:
        def __init__(self, **config):
            self.config = config

        def run(self, prompt, on_notification=None):
            from pathlib import Path
            patch = json.loads(Path(self.config['patches'][0]).read_text())
            endpoint = patch[-1]['insert'][0]['config']['endpoint']
            def request(name):
                return urllib.request.urlopen(urllib.request.Request(endpoint+'/'+name, data=b'{}',
                    headers={'Authorization': 'Bearer '+self.config['env']['PONYCHAT_HARNESS_TOKEN']}), timeout=2)
            if not already_exhausted:
                with request('search_images') as response:
                    assert json.load(response)['value']['found']
            with request('stage_web_image') as response:
                assert json.load(response)['value']['staged']
            with pytest.raises(urllib.error.HTTPError) as error:
                request('search_images')
            assert error.value.code == (404 if already_exhausted else 409)
            return types.SimpleNamespace(final_response='done', finish_reason='completed', events=[])

        def close(self):
            pass

    async def search():
        calls.append('search')
        return {'found': True}

    async def send():
        await asyncio.sleep(.15)  # Longer than the entire exploration allowance.
        calls.append('send')
        return {'staged': True}

    monkeypatch.setitem(__import__('sys').modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))
    result = asyncio.run(run_harness_turn('test', {}, {'search_images': search, 'stage_web_image': send},
        tool_timeout_seconds=None if already_exhausted else .08, max_tool_calls=12,
        delivery_only=already_exhausted, delivery_tool_names=('stage_web_image',),
        delivery_timeout_seconds=.8, tool_budget_state=state, stop_on_tool_budget=True, timeout_seconds=2))
    assert result['finish_reason'] == 'completed'
    assert calls == (['send'] if already_exhausted else ['search', 'send'])
    assert state['calls'] == (12 if already_exhausted else 1)
    assert state['delivery_calls'] == 1


def test_exploration_and_delivery_windows_are_separate(monkeypatch):
    """Exploration gets its own window; the delivery retry keeps the rest.

    The exploration attempt used to receive the whole user-facing total, so a
    single slow retrieval step could spend the delivery and recovery time before
    the Agent ever tried to answer.
    """
    clock = [100.0]
    monkeypatch.setattr(normal, 'time', types.SimpleNamespace(monotonic=lambda: clock[0]))
    images = importlib.import_module(normal.__package__ + '.autonomous_web_images').WebImageTools(None, username='synthetic')
    limits = []

    async def runner(prompt, config, tools, **options):
        limits.append(options['timeout_seconds'])
        if len(limits) == 1:
            clock[0] += 40
            return model_result(finish='tool_time_budget_exhausted')
        assert tools == {} and options['force_no_tools']
        assert options['delivery_tool_names'] == () and options['max_tool_calls'] == 0
        if len(limits) == 2:
            clock[0] += 30
            return model_result() | {'final_response': 'invalid JSON'}
        return model_result()

    run(turn(web_image_tools=images, harness_runner=runner))
    assert limits == [normal.NORMAL_EXPLORATION_LIMIT_SECONDS, None, None]


@pytest.mark.parametrize('finish', ['tool_time_budget_exhausted', 'tool_budget_exhausted'])
@pytest.mark.parametrize('has_candidate', [False, True])
def test_no_viewed_image_means_no_image_tool_in_delivery(finish, has_candidate):
    images = importlib.import_module(normal.__package__ + '.autonomous_web_images').WebImageTools(
        None, username='synthetic')
    if has_candidate:
        images.candidates['web:test'] = {'source_url': 'https://example.org', 'title': 'unread'}
    current = session(home='')
    calls = []

    async def transport(prompt, config, tools, **options):
        calls.append(options)
        if len(calls) == 1:
            await tools['load_chat_skill'].callback({'name': 'instant_messaging'})
            return model_result(finish=finish)
        assert tools == {}
        assert options['max_tool_calls'] == 0 and options['delivery_tool_names'] == ()
        data = json.loads(prompt)
        assert '没有已下载查看' in data['completion_feedback']
        return model_result('好，我坐在这里。')

    result = run(turn(web_image_tools=images, harness_runner=current.runner(transport)))
    assert len(calls) == 2 and not images.selected
    assert '我坐在这里' in result['envelope']


def test_recovery_reuses_staged_image_transfer(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(normal, 'time', types.SimpleNamespace(monotonic=lambda: clock[0]))
    transfers = []
    images = importlib.import_module(normal.__package__ + '.autonomous_web_images').WebImageTools(
        None, username='synthetic', transfer_store=lambda *args: transfers.append(args) or '/transfer/one')
    images.candidates['web:test'] = {'source_url': 'https://example.org', 'title': 'test'}
    images.downloaded['web:test'] = {'data': b'pixels', 'mime_type': 'image/png'}
    calls = []

    async def runner(prompt, config, tools, **options):
        calls.append(options)
        await tools['stage_web_image'].callback({'image_ref': 'web:test'})
        if len(calls) <= 2:
            clock[0] += 60 if len(calls) == 1 else 1000
            raise asyncio.TimeoutError()
        return model_result()

    run(turn(web_image_tools=images, harness_runner=runner))
    assert len(calls) == 3
    assert len(transfers) == 1
    assert list(images.selected) == ['web:test']
