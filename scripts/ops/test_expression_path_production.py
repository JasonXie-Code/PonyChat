"""Safety and completeness of the serial skill dependency protocol."""
from pathlib import Path
import asyncio
import json

import pytest

from replay_expression_focus import load_modules
from expression_path_serial import OWNERS
import importlib


def session():
    modules = load_modules()
    skills = modules['autonomous_prompt_skills']
    adapter = importlib.import_module(skills.__package__ + '.autonomous_expression_paths')
    cls = adapter.serial_session_class(skills.PromptSkills, modules['harness_runtime'].HarnessTool)
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
        assert len(calls) == 1
        assert sum(e['status'] == 'delivery_blocked' for e in s.gate_events) == 1
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


def test_early_final_fails_without_repair():
    async def run():
        s = session()
        calls = []
        async def fake(*args, **kwargs):
            calls.append(1)
            return {'finish_reason': 'completed', 'final_response': '{}', 'usage': {'total_tokens': 17}}
        with pytest.raises(RuntimeError) as caught:
            await s.runner(fake)('{}', {}, {}, system_prompt='system')
        assert len(calls) == 1
        assert caught.value.retryable is False
        assert caught.value.harness_usage['usage']['total_tokens'] == 17
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


def test_production_rules_preserved_once_and_children_are_not_top_level():
    import re
    from pathlib import Path
    from expression_path_experiment import partition
    s = session()
    text = '\n'.join(s.catalog[name][1] for name in OWNERS)
    for rule in partition(Path(__file__).with_name('expression_original.txt').read_text(encoding='utf-8')).values():
        assert text.count(re.sub(r'^\d+\.\s*', '', rule)) == 1
    prompt, _ = s.transform('{"latest_user_message":{"content":"你好"}}', 'system')
    names = {row['name'] for row in json.loads(prompt)['available_skills']}
    assert names.intersection(OWNERS) == {'reply_expression'}


def test_cursor_reads_one_skill_per_call_and_preserves_image_input():
    async def run():
        s = session()
        calls = []
        async def fake(prompt, config, tools, **options):
            calls.append(prompt)
            assert prompt[1]['image_url']['url'] == 'https://example.invalid/a.png'
            cursor = tools['read_next_reply_skill'].callback
            result = await cursor({})
            assert result['skill'] == 'reply_expression'
            result = await cursor({})
            assert result['skill'] == 'reply_conditions'
            result = await tools['select_reply_paths'].callback({'paths': ['interaction_reply']})
            assert result['next_call']['reads'] == 'reply_perspective'
            loaded = []
            while not result['complete']:
                assert result['next_call']['tool'] == 'read_next_reply_skill'
                result = await cursor(result['next_call']['arguments'])
                loaded.append(result['skill'])
            assert loaded == ['reply_perspective', 'interaction_reply', 'reply_review']
            assert result['next_call'] is None
            return {'finish_reason': 'completed', 'final_response': '{}'}
        prompt = [{'type': 'text', 'text': '{"latest_user_message":{"content":"图片"}}'},
                  {'type': 'image_url', 'image_url': {'url': 'https://example.invalid/a.png'}}]
        result = await s.runner(fake)(prompt, {}, {}, system_prompt='system')
        assert len(calls) == 1 and not s.gate_events
    asyncio.run(run())


def test_delivery_only_does_not_expose_selector_or_retry():
    async def run():
        s = session()
        async def fake(prompt, config, tools, **options):
            assert 'select_reply_paths' not in tools and 'load_chat_skill' not in tools
            return {'finish_reason': 'completed', 'final_response': '{}'}
        with pytest.raises(RuntimeError):
            await s.runner(fake)('{}', {}, {}, system_prompt='system', delivery_only=True)
        assert len(s.gate_events) == 1
    asyncio.run(run())


def test_live_input_invalidates_read_contract_before_final():
    from types import SimpleNamespace
    async def run():
        s = session()
        s.transform('{"latest_user_message":{"message_id":"a","content":"再见"}}', 'system')
        for name in ('reply_expression', 'reply_conditions'):
            await s.load({'name': name})
        await s.select_paths({'paths': ['conversation_reply']})
        for name in ('conversation_reply', 'reply_review'):
            await s.load({'name': name})
        async def prepare(rows):
            return [{'type': 'text', 'text': json.dumps({'latest_user_message': rows[-1]})}]
        channel = SimpleNamespace(prepare_input=prepare)
        s.bind_live_input(channel)
        blocks = await channel.prepare_input([{'message_id': 'b', 'content': '等一下，抱抱我'}])
        assert s.next_required() == 'select_reply_paths'
        assert not s.selected_paths and 'reply_review' not in s.loaded
        assert json.loads(blocks[0]['text'])['expression_read_contract']['next_call']['tool'] == 'select_reply_paths'
    asyncio.run(run())
