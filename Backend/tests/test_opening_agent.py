"""Opening events exercise the real Agent/skills pipeline with a fake transport."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from Backend.chat_modules import opening_agent as opening
from Backend.chat_modules.autonomous_normal import run_autonomous_turn, NormalAgentError
from Backend.chat_modules.autonomous_prompt_skills import run_skill_turn


@pytest.mark.parametrize('quiet', [False, True])
def test_opening_runs_main_agent_with_skills_without_fabricating_user(quiet):
    async def runner(prompt, model, tools, **options):
        data = json.loads(prompt)
        assert data['internal_task']['type'] == 'new_contact_opening'
        assert data['latest_user_message'] == {}
        assert data['current_user_batch'] == []
        assert data['recent_raw_messages'] == []
        assert data['reply_constraints']['required_bubble_count'] is None
        assert '正文格式合同' not in options['system_prompt']
        await tools['read_character_reference'].callback({'query': '性格'})
        for name in ('instant_messaging', 'evidence', 'reply_language', 'voice_reply', 'delivery',
                     'reply_expression', 'reply_conditions'):
            await tools['load_chat_skill'].callback({'name': name})
        await tools['select_reply_paths'].callback({'paths': ['conversation_reply']})
        for name in ('conversation_reply', 'reply_deduplication', 'reply_review'):
            await tools['load_chat_skill'].callback({'name': name})
        envelope = {'voice_reply': {'enabled': False, 'reason': '文字开场'},
                    'reply_language': {'language': 'Chinese', 'reason': '当前语境'},
                    'bubble_count': 0 if quiet else 1, 'used_facts': [],
                    'bubbles': [] if quiet else [{'index': 1, 'type': 'text', 'purpose': 'answer_user',
                                                  'parts': [{'kind': 'speech', 'text': '你好，很高兴认识你。'}]}]}
        if quiet:
            envelope['no_reply_reason'] = '角色愿意等对方先开口'
        return {'finish_reason': 'completed', 'final_response': json.dumps(envelope),
                'usage': {}, 'llm_api_calls': 1}

    result = asyncio.run(run_skill_turn(
        run_autonomous_turn, messages=[], internal_task='new_contact_opening',
        character_profile='性格：安静友好', home_profile='名称：测试角色\n简介：安静友好',
        environment='', model_config={}, harness_runner=runner))
    assert result['bubble_count'] == (0 if quiet else 1)
    assert result['input_message_ids'] == []
    assert result['prompt_skills']['interaction_mode'] == 'instant_messaging'


@pytest.mark.parametrize('messages,task,error', [
    ([], None, NormalAgentError),
    ([], 'unknown', ValueError),
    ([{'role': 'user', 'content': '你好'}], 'new_contact_opening', ValueError),
])
def test_empty_conversation_exception_is_only_for_internal_opening(messages, task, error):
    with pytest.raises(error):
        asyncio.run(run_autonomous_turn(messages=messages, internal_task=task,
                                       character_profile='', environment='', model_config={}))


@pytest.fixture
def adapter(monkeypatch):
    captured = {}
    monkeypatch.setattr(opening, 'load_character_from_db', lambda *a: {'name': '测试', 'prompt': '友好'})
    monkeypatch.setattr(opening.model_manager, 'get_model_for_task', lambda task: {'model_name': 'test'})
    monkeypatch.setattr(opening, 'build_character_profile_prompt_block', lambda *a, **k: '名称：测试')
    monkeypatch.setattr(opening, 'character_profile_reference_guidance', lambda *a: '')
    async def context(*args, **kwargs):
        assert kwargs['is_new_contact_opening']
        return '用户背景'
    async def settings(*a):
        return {}
    async def meter(username, result, **kwargs):
        captured['meter'] = (username, result, kwargs)
    monkeypatch.setattr(opening, 'build_user_context', context)
    monkeypatch.setattr(opening, 'SettingsDAO', lambda db: SimpleNamespace(load_settings=settings))
    monkeypatch.setattr(opening, 'get_database', lambda: None)
    monkeypatch.setattr(opening, 'meter_user', meter)
    return captured


def test_adapter_renders_parts_and_records_usage_without_membership_charge(adapter, monkeypatch):
    async def agent(actual_turn, **kwargs):
        assert actual_turn is run_autonomous_turn
        assert kwargs['messages'] == []
        assert kwargs['internal_task'] == 'new_contact_opening'
        return {'envelope': json.dumps({'bubble_count': 2, 'bubbles': [
            {'parts': [{'kind': 'speech', 'text': '你好。'}]},
            {'parts': [{'kind': 'thought', 'text': '我有点好奇'}]},
        ]}), 'usage': {'prompt_tokens': 10}, 'llm_api_calls': 1}
    monkeypatch.setattr(opening, 'run_skill_turn', agent)
    result = asyncio.run(opening.generate_opening_greeting('alice', 'test'))
    assert result['bubbles'] == ['你好', '（我有点好奇）']
    assert adapter['meter'][2] == {'charge_membership': False}


def test_agent_failure_records_partial_usage_and_never_falls_back(adapter, monkeypatch):
    async def agent(actual_turn, **kwargs):
        kwargs['usage_sink']({'usage': {'prompt_tokens': 17}, 'llm_api_calls': 1})
        raise RuntimeError('model failed')
    monkeypatch.setattr(opening, 'run_skill_turn', agent)
    with pytest.raises(RuntimeError, match='model failed'):
        asyncio.run(opening.generate_opening_greeting('alice', 'test'))
    assert adapter['meter'][1]['usage']['prompt_tokens'] == 17


def test_missing_model_returns_no_canned_greeting(adapter, monkeypatch):
    monkeypatch.setattr(opening.model_manager, 'get_model_for_task', lambda _: None)
    result = asyncio.run(opening.generate_opening_greeting('alice', 'test'))
    assert result == {'bubbles': [], 'reason': 'model_unavailable'}
    assert 'meter' not in adapter
