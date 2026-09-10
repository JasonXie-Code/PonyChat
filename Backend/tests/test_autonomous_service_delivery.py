"""Execute autonomous delivery with real service/SSE code and isolated app boundaries."""
import asyncio
import ast
import importlib.util
import json
import logging
from pathlib import Path
import random
import sys
import time
from types import ModuleType, SimpleNamespace
import uuid

import pytest


@pytest.mark.parametrize('save_ok,supersede,silence', [
    (True, False, False), (False, False, False), (True, True, False), (True, False, True)])
def test_autonomous_delivery_skips_legacy_models_and_commits_only_current_saved_reply(
        monkeypatch, save_ok, supersede, silence):
    root = '_autonomous_delivery_test'
    for name in (root, root + '.chat_modules', root + '.db', root + '.agent_memory'):
        module = ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules[root + '.chat_modules'].__path__ = [str(Path(__file__).parents[1] / 'chat_modules')]
    calls = []
    current = [True]

    def module(name, **exports):
        value = ModuleType(name)
        value.__dict__.update(exports)
        monkeypatch.setitem(sys.modules, name, value)
        return value

    async def logged(awaitable, stage, is_current, error_type, **_kwargs):
        result = await awaitable
        if not is_current():
            raise error_type(stage)
        return result

    module('Backend.chat_modules.normal_stage_logging', await_logged_normal_stage=logged)
    module(root + '.config', logger=logging.getLogger('autonomous-test'))
    module(root + '.background_jobs', create_tracked_task=lambda coro, **kwargs: asyncio.create_task(coro))
    async def notify(**kwargs):
        pass
    module(root + '.delivery_outbox', enqueue_chat_complete=notify)
    async def meter_user(username, result, **_kwargs):
        usage = result['usage']
        counters = {'input_tokens': usage['prompt_tokens'],
                    'output_tokens': usage['completion_tokens'],
                    'llm_api_calls': result['llm_api_calls']}
        calls.append(('usage', username, counters['input_tokens'], counters['output_tokens'],
                      counters['llm_api_calls']))
        calls.append(('membership', username, counters['llm_api_calls']))
        return counters

    module(root + '.agent_memory.usage', meter_user=meter_user)
    service_path = Path(__file__).parents[1] / 'chat_modules' / 'autonomous_service.py'
    spec = importlib.util.spec_from_file_location(root + '.chat_modules.autonomous_service', service_path)
    service = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, service)
    spec.loader.exec_module(service)

    class Store:
        def commit(self, *, reply_succeeded, generation_is_current):
            if reply_succeeded and generation_is_current():
                calls.append('commit')
            return []

        def discard(self):
            calls.append('discard')

    async def persist(request, model_name, full_text, started, **kwargs):
        calls.append(('persist', full_text))
        if supersede:
            current[0] = False
        return save_ok, 'saved' if save_ok else 'failed', ['assistant-1'] if save_ok else []

    async def forbidden(*args, **kwargs):
        pytest.fail('Autonomous delivery must not execute a legacy model or Step 4')

    class Response:
        def __init__(self, body):
            self.body = body

    namespace = {'__name__': root + '.chat_modules.normal_nonstream',
        '__package__': root + '.chat_modules', 'asyncio': asyncio, 'json': json,
        'time': time, 'uuid': uuid, 'random': random, 'logger': logging.getLogger('autonomous-test'),
        'JSONResponse': Response, 'effective_speaker_character_id': lambda r: r.character_id,
        'speaker_event_fields': lambda r: {}, 'is_generation_current': lambda *args: current[0],
        'run_conversation_persistence': persist, 'call_llm_payload': forbidden,
        'run_normal_handoff_router_decision': forbidden, 'write_guest_direct_memory_once': forbidden,
        '_normal_handoff_router_has_recent_non_main_speaker': lambda *args, **kwargs: False,
        'build_assistant_units': lambda text, **kwargs: [{'type': 'text', 'content': part}
            for part in text.split('\n\n')], '_should_emit_json_compat_delta': lambda **kwargs: False}
    sse = service_path.with_name('normal_nonstream_impl') / 'normal_nonstream_sse.py'
    exec(compile(sse.read_text(encoding='utf-8'), str(sse), 'exec'), namespace)
    request = SimpleNamespace(username='', character_id='role', conversation_id='conversation', mode='normal',
        messages=[SimpleNamespace(role='user', content='hello', message_id='user-1')],
        crisis_hotline_enabled=False, _autonomous_harness=True, _autonomous_memory_store=Store(),
        _normal_planner_result={'bubble_count': 0 if silence else 1, 'voice_reply': {'enabled': False},
                                'speech_reason': 'handoff' if silence else ''},
        _autonomous_usage={'prompt_tokens': 12, 'completion_tokens': 3}, _autonomous_llm_calls=1,
        _normal_enable_stage3_handoff_events=silence,
        _normal_handoff_router_result={'reply_character_id': 'guest', 'reason': '用户在叫她'} if silence else None,
        _autonomous_llm_response=SimpleNamespace(text=json.dumps({'bubble_count': 0, 'bubbles': [],
            'no_reply_reason': 'handoff'} if silence else {'bubbles': [{'parts': [
            {'kind': 'speech', 'text': '等我一下。'},
            {'kind': 'action', 'text': '我搬来小凳子。'},
            {'kind': 'speech', 'text': '这样就够得到啦。'}]}]})))

    async def release():
        calls.append('release')

    result = asyncio.run(namespace['handle_normal_nonstream_sse'](request=request, model_name='vision-exp',
        payload={}, api_url='', headers={}, provider=None, httpx_client=None, messages=[], request_tokens=999,
        username='user', character_id='role', client_id='client', effective_username='user', release_lock=release,
        active_model={}, use_json=True))
    asyncio.run(service.settle_autonomous_usage(request, 'user'))
    expected = '' if silence else '等我一下。（我搬来小凳子）这样就够得到啦'
    assert ('persist', expected) in calls
    assert ('usage', 'user', 12, 3, 1) in calls
    assert ('membership', 'user', 1) in calls
    assert calls.count(('usage', 'user', 12, 3, 1)) == 1
    assert ('commit' in calls) is (save_ok and not supersede)
    assert calls[-2:] == ['discard', 'release']
    events = result.body['events']
    assert any('error' in event for event in events) is (not save_ok and not supersede), events
    if supersede:
        assert any(event.get('type') == 'cancelled' for event in events)
    elif save_ok:
        if silence:
            assert any(event.get('type') == 'no_reply' for event in events)
            assert any(event.get('type') == 'normal_handoff_request' and
                       event.get('reply_character_id') == 'guest' for event in events)
        else:
            assert any(event.get('content') == expected for event in events)
            assert next(event['metadata']['usage'] for event in events if 'metadata' in event) == {
                'input_tokens': 12, 'output_tokens': 3}


def test_harness_speaker_router_uses_code_only(monkeypatch):
    path = Path(__file__).parents[1] / 'chat_modules/service_impl/chat_request_helpers.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == 'handle_requested_normal_reply_speakers_if_needed')
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(path), 'exec'), namespace)
    observed = []

    class Models:
        def __getattribute__(self, name):
            raise AssertionError('Harness speaker path must not select a legacy router model')

    async def rebuild(*args, **kwargs):
        pass

    async def explicit(*args, **kwargs):
        return []

    async def router(request, config, **kwargs):
        observed.append(config)
        return []

    request = SimpleNamespace(mode='normal', is_summary_request=False,
                              _normal_autonomous_harness_requested=True)
    result = asyncio.run(namespace['handle_requested_normal_reply_speakers_if_needed'](
        request, None, None, {'api_key':'legacy'}, False, None, 'user', 'role', 'client',
        SimpleNamespace(model_manager=Models()), logging.getLogger('speaker-code-only'), lambda r: [],
        rebuild, explicit, router, lambda *args: None, None))
    assert result is None
    assert observed == [{}]


@pytest.mark.parametrize('lifecycle', ['alive', 'dead', 'spirit', 'unavailable'])
def test_harness_request_bypasses_eager_assembly_and_legacy_stages(monkeypatch, lifecycle):
    root = '_autonomous_entry_test'
    calls = []
    for name in (root, root + '.chat_modules'):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)

    async def noop(*args, **kwargs):
        return None

    async def forbidden(*args, **kwargs):
        pytest.fail('Harness entry must bypass eager memory and legacy inference')

    async def prepare(request, model_config, **kwargs):
        calls.append(('agent', kwargs))
        request._autonomous_harness = True
        return [{'role': 'user', 'content': 'latest raw message'}]

    async def deliver(**kwargs):
        calls.append(('deliver', kwargs['messages']))
        return 'delivered'

    async def logged(awaitable, *_args, **_kwargs):
        return await awaitable

    async def auth(*args):
        return {'active_model': {'model_name': 'vision-exp'}, 'request_tokens': 3,
                'client_id': 'client', 'character_id': 'character', 'username': 'user',
                'effective_username': 'user'}

    async def alive(*args):
        if lifecycle == 'unavailable':
            raise RuntimeError('isolated state store unavailable')
        return 'dead' if lifecycle in ('dead', 'spirit') else 'alive'

    async def release(*args):
        calls.append('release')

    async def save_user(*args, **kwargs):
        assert kwargs.get('persist_user_only')
        calls.append('user_only')
        return True, 'saved', []

    async def speakers(*args):
        assert args[0]._normal_autonomous_harness_requested is True
        assert args[0]._normal_enable_stage3_handoff_events is True
        assert args[14] is noop  # Deterministic direct-name routing remains connected.
        return None

    async def user_context(*args, **kwargs):
        return 'SHARED USER PROFILE'

    def module(suffix, **exports):
        value = ModuleType(root + suffix)
        value.__dict__.update(exports)
        monkeypatch.setitem(sys.modules, value.__name__, value)

    module('.chat_modules.autonomous_service', prepare_autonomous_request=prepare)
    module('.chat_modules.normal_nonstream', handle_normal_nonstream_sse=deliver)
    module('.chat_modules.autonomous_shortcuts', is_description_shortcut=lambda text:False,
           is_story_shortcut=lambda text:False)
    module('.chat_modules.normal_lifecycle', get_normal_character_state=alive)
    module('.chat_modules.normal_speaker', explicit_user_at_reply_requested=lambda *a: lifecycle == 'spirit')
    module('.chat_modules.runtime', run_conversation_persistence=save_user)
    module('.scheduled_followup', cancel_pending_for_user_message=noop,
           cancel_pending_step4_next_turn_prep_decision=lambda *a: None)
    namespace = {'__name__': root + '.chat_modules.service', '__package__': root + '.chat_modules',
        'asyncio': asyncio, 'logger': logging.getLogger('autonomous-entry'), 'time': time,
        'resolve_auth_and_quota': auth, 'normal_generation_current_for_request': lambda *a: True,
        'await_normal_stage_with_generation_guard': logged, 'handle_quota_no_reply_if_needed': noop,
        'handle_requested_normal_reply_speakers_if_needed': speakers,
        'maybe_early_android_normal_accepted_response': noop,
        '_rebuild_android_normal_request_from_server_history': noop,
        '_normal_no_reply_response': lambda *a, **kw: kw['reason'],
        'config': SimpleNamespace(httpx_client=None), 'requested_reply_character_ids': None,
        'resolve_explicit_at_reply_character_ids': None, 'run_normal_user_speaker_intent_router': noop,
        'mark_normal_forced_reply_characters': None, '_handle_normal_multi_speaker_request': None,
        '_ANDROID_DELTA_CLIENT_IDS': set(), '_latest_visible_user_batch': None,
        '_persist_android_normal_user_delta': noop, 'prepare_normal_reply_speaker': noop,
        '_normal_reply_debounce_ms': lambda: 0, 'is_generation_current': lambda *a: True,
        '_collapse_unreplied_user_tail_for_model_context': lambda r: pytest.fail('raw messages collapsed'),
        'get_last_user_image_urls': lambda r: [], 'effective_speaker_character_id': lambda r: 'character',
        '_build_planner_character_prompt_context': lambda *a: 'FULL RAW ROLE PROFILE',
        'format_client_context': lambda c: 'RAW ENVIRONMENT', 'assemble_messages': forbidden,
        '_is_new_contact_opening': noop, 'build_user_context': user_context, 'run_normal_stage2': forbidden,
        'NormalGenerationSuperseded': type('Superseded', (Exception,), {}),
        'NormalAgentError': type('AgentError', (Exception,), {}),
        'release_normal_generation_lock_for_request': release,
        'generation_locker': None, 'manager': None,
    }
    from fastapi import HTTPException
    namespace['HTTPException'] = HTTPException
    path = Path(__file__).parents[1] / 'chat_modules/service_impl/chat_request.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef))
    isolated = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), function], type_ignores=[])
    exec(compile(ast.fix_missing_locations(isolated), str(path), 'exec'), namespace)
    request = SimpleNamespace(mode='normal', normal_engine='harness', is_summary_request=False,
        username='user', character_id='character', conversation_id='conversation', client_context={'hour': 5},
        messages=[SimpleNamespace(role='user', content='latest raw message', isHidden=False)])
    if lifecycle == 'unavailable':
        with pytest.raises(HTTPException) as error:
            asyncio.run(namespace['handle_chat_request'](request, None, None, {}))
        assert error.value.status_code == 503
        assert calls == ['release']
        return
    if lifecycle == 'dead':
        assert asyncio.run(namespace['handle_chat_request'](request, None, None, {})) == 'character_already_dead'
        assert calls == ['user_only', 'release']
        return
    assert asyncio.run(namespace['handle_chat_request'](request, None, None, {})) == 'delivered'
    assert bool(getattr(request, '_normal_dead_spirit_reply', False)) == (lifecycle == 'spirit')
    assert calls == [('agent', {'profile': 'FULL RAW ROLE PROFILE', 'environment': 'RAW ENVIRONMENT\nSHARED USER PROFILE',
                               'image_urls': []}), ('deliver', [{'role': 'user', 'content': 'latest raw message'}])]
