"""Local selection must reach the correct model, vision route and context limit."""
import asyncio
import json
from pathlib import Path
import sys
import types

import pytest


@pytest.mark.parametrize('pooled', ['0', '1'])
def test_harness_switches_provider_model_and_back(monkeypatch, pooled):
    from Backend.chat_modules.harness_runtime import run_harness_turn
    seen = []

    class Harness:
        def __init__(self, **config):
            self.config = config
            seen.append(config)
            self.patch = json.loads(Path(config['patches'][0]).read_text())

        def start(self):
            pass

        def run(self, *args, **kwargs):
            return types.SimpleNamespace(final_response='ok', finish_reason='completed', events=[])

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Harness))
    monkeypatch.setenv('PONYCHAT_HARNESS_POOL', pooled)
    cfg = json.loads((Path(__file__).parents[1] / 'conf/models/local.json').read_text())['models'][0]

    async def scenario():
        for config in ({'model_name': 'deepseek-flash'}, cfg, {'model_name': 'deepseek-flash'}):
            result = await run_harness_turn('synthetic', config, {})
            assert result['model'] == config['model_name']
    asyncio.run(scenario())
    assert [c['provider'] for c in seen] == ['deepseek-official', 'ponychat-local', 'deepseek-official']
    assert seen[1]['reasoning_effort'] is None
    from Backend.chat_modules.harness_model import provider_patch
    route = provider_patch(cfg)[0]['insert'][0]['config']['providers']['ponychat-local']
    assert route['models'][0]['contextWindow'] == 131072
    assert route['models'][0]['input'] == ['text', 'image']


@pytest.mark.parametrize('mode', ['normal', 'galgame'])
@pytest.mark.parametrize('explicit,enabled,expected', [
    (None, True, 'qwen3.5-4b-local'), ('deepseek-flash', True, 'qwen3.5-4b-local'),
    ('deepseek-flash', False, 'qwen3.5-4b-local'), ('missing', True, 'qwen3.5-4b-local')])
def test_main_chat_ignores_stale_user_and_client_selection(monkeypatch, mode, explicit, enabled, expected):
    from Backend.chat_modules import request_context
    from Backend.chat_modules.request_context import ChatRequest, ChatMessage
    preferred = {'id': 'qwen3.5-4b-local'}
    async def selected(username):
        raise AssertionError('Main chat must not consult legacy user preferences')
    monkeypatch.setattr(request_context, 'get_user_active_model', selected)
    monkeypatch.setattr(request_context, '_routing_model_manager', types.SimpleNamespace(
        config={'models': [{'id': 'deepseek-flash', 'enabled': enabled}]},
        get_model_for_task=lambda task: preferred))
    monkeypatch.setattr(request_context, 'apply_backend_context_summary_if_needed', lambda req: asyncio.sleep(0))
    request = ChatRequest(mode=mode, model_id=explicit,
                          messages=[ChatMessage(role='user', content='synthetic')])
    result = asyncio.run(request_context.resolve_auth_and_quota(request, None, None, {'id': 'old'}))
    assert result['active_model']['id'] == expected


def test_global_switch_controls_chat_even_when_deepseek_is_first(monkeypatch):
    from Backend.model_manager import ModelManager
    manager = ModelManager.__new__(ModelManager)
    config = {'active_model': 'qwen3.5-4b-local', 'models': [
        {'id': 'deepseek-flash', 'for_chat': True, 'api_key': 'synthetic'},
        {'id': 'qwen3.5-4b-local', 'for_chat': True, 'api_key': 'local'}]}
    monkeypatch.setattr(manager, '_load_config', lambda: config)
    assert manager.get_model_for_task('chat')['id'] == 'qwen3.5-4b-local'
    config['active_model'] = 'deepseek-flash'
    assert manager.get_model_for_task('chat')['id'] == 'deepseek-flash'
