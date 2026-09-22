"""Safety and completeness of the serial skill dependency protocol."""
from pathlib import Path
import asyncio
import json

import pytest

from replay_expression_focus import load_modules
from expression_path_serial import OWNERS, serial_session_class


def session():
    modules = load_modules()
    skills = modules['autonomous_prompt_skills']
    cls = serial_session_class(skills.PromptSkills, Path(__file__).with_name('expression_original.txt').read_text(encoding='utf-8'), modules['harness_runtime'].HarnessTool)
    return cls(profile='名称：柔柔', preferences='', business=None, normal_module=modules['autonomous_normal'])


def test_unique_ownership_covers_all_rules_once():
    assert sorted(n for numbers in OWNERS.values() for n in numbers) == list(range(1, 19))


def test_serial_dependencies_repeat_reads_and_late_path_invalidate_review():
    async def run():
        s = session()
        assert (await s.load({'name': 'interaction_reply'}))['status'] == 'blocked'
        assert not s.loaded
        for name in ['reply_expression', 'reply_conditions']:
            await s.load({'name': name})
        assert s.next_required() == 'select_reply_paths'
        await s.select_paths({'paths': ['conversation_reply']})
        await s.load({'name': 'conversation_reply'})
        await s.load({'name': 'reply_review'})
        assert s.next_required() is None
        await s.select_paths({'paths': ['interaction_reply']})
        assert s.next_required() == 'reply_perspective'
        assert 'reply_review' not in s.loaded
        for name in ['reply_perspective', 'interaction_reply', 'reply_review']:
            await s.load({'name': name})
        assert s.next_required() is None
        repeat = await s.load({'name': 'reply_perspective'})
        assert repeat['status'] == 'already_loaded' and 'instructions' not in repeat
    asyncio.run(run())


def test_explicit_description_contract_cannot_be_omitted():
    async def run():
        s = session()
        await s.load({'name': 'reply_expression'})
        await s.load({'name': 'reply_conditions'})
        s.task_snapshot = {'description_shortcut_contract': 'load_chat_skill:shortcut'}
        assert (await s.select_paths({'paths': ['conversation_reply']}))['status'] == 'blocked'
        assert s.selected_paths == []
    asyncio.run(run())


def test_unread_path_never_delivers_even_when_model_keeps_returning_valid_json():
    async def run():
        s = session()
        calls = []

        async def fake(prompt, config, tools, **options):
            calls.append(prompt)
            validator = load_modules()['harness_runtime']._closed_schema
            for tool in tools.values():
                validator(tool.parameters)
            return {'finish_reason': 'completed', 'final_response': '{"bubbles":[]}'}

        with pytest.raises(RuntimeError, match='read contract incomplete'):
            await s.runner(fake)('{"latest_user_message":{"content":"再见"}}', {}, {}, system_prompt='system')
        assert len(calls) == 3
        assert sum(e['status'] == 'delivery_blocked' for e in s.gate_events) == 3
    asyncio.run(run())


def test_no_tool_budget_fails_closed_without_retry():
    async def run():
        s = session()
        calls = []

        async def fake(*args, **kwargs):
            calls.append(1)
            return {'finish_reason': 'completed', 'final_response': '{}'}

        with pytest.raises(RuntimeError, match='read contract incomplete'):
            await s.runner(fake)('{"latest_user_message":{"content":"再见"}}', {}, {},
                                 system_prompt='system', max_tool_calls=0, force_no_tools=True)
        assert len(calls) == 1
    asyncio.run(run())


def test_early_final_is_held_until_model_completes_serial_reads():
    async def run():
        s = session()
        calls = []

        async def fake(prompt, config, tools, **options):
            calls.append(1)
            if len(calls) == 2:
                loader = tools['load_chat_skill'].callback
                await loader({'name': 'instant_messaging'})
                await loader({'name': 'reply_expression'})
                await loader({'name': 'reply_conditions'})
                await tools['select_reply_paths'].callback({'paths': ['conversation_reply']})
                await loader({'name': 'conversation_reply'})
                await loader({'name': 'reply_review'})
            return {'finish_reason': 'completed', 'final_response': '{}'}

        result = await s.runner(fake)('{"latest_user_message":{"content":"再见"}}', {}, {}, system_prompt='system')
        assert result['finish_reason'] == 'completed'
        assert len(calls) == 2 and s.next_required() is None
        assert sum(e['status'] == 'delivery_blocked' for e in s.gate_events) == 1
    asyncio.run(run())


def test_new_user_input_invalidates_prior_path_and_review():
    async def run():
        s = session()
        first = json.dumps({'latest_user_message': {'message_id': 'a', 'content': '再见'}})
        s.transform(first, 'system')
        for name in ['reply_expression', 'reply_conditions']:
            await s.load({'name': name})
        await s.select_paths({'paths': ['conversation_reply']})
        await s.load({'name': 'conversation_reply'})
        await s.load({'name': 'reply_review'})
        assert s.next_required() is None
        s.transform(first, 'system')
        assert s.next_required() is None
        second = json.dumps({'latest_user_message': {'message_id': 'b', 'content': '等一下，我想抱抱你'}})
        s.transform(second, 'system')
        assert s.next_required() == 'select_reply_paths'
        assert not s.selected_paths
        assert 'conversation_reply' not in s.loaded and 'reply_review' not in s.loaded
    asyncio.run(run())
