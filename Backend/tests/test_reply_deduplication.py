"""The deduplication manual has one owner and cannot be skipped or kept stale."""
import asyncio
import json

import pytest
from test_autonomous_prompt_skills import skills, normal, payload
from prompt_skills_under_test.autonomous_expression_paths import serial_session_class, ExpressionReadIncomplete
from prompt_skills_under_test import Prompts


def session():
    return serial_session_class(skills.PromptSkills, skills.HarnessTool)(
        profile='名称：柔柔', home_profile='名称：柔柔', preferences='',
        business=type('Business', (), {'guidance': ''})(), normal_module=normal)


async def through_path(s):
    await s.read_next({})
    await s.read_next({})
    await s.select_paths({'paths': ['conversation_reply']})
    await s.read_next({})


def test_hidden_manual_absent_from_initial_context_and_read_before_review():
    s = session()
    data, system = s.transform(payload(), normal.SYSTEM)
    assert Prompts.reply_deduplication not in data + system
    assert 'reply_deduplication' not in [x['name'] for x in json.loads(data)['available_skills']]
    asyncio.run(through_path(s))
    assert s.next_required() == 'reply_deduplication'
    blocked = asyncio.run(s.load({'name': 'reply_review'}))
    assert blocked['status'] == 'blocked'
    result = asyncio.run(s.read_next({}))
    assert Prompts.reply_deduplication in result['instructions']
    assert s.next_required() == 'reply_review'
    assert s.deduplication_reads == ['initial']
    asyncio.run(s.load({'name': 'reply_deduplication'}))
    assert s.deduplication_reads == ['initial']


def test_final_delivery_without_deduplication_is_rejected():
    s = session()

    async def transport(*args, **kwargs):
        await through_path(s)
        return {'finish_reason': 'completed', 'final_response': '{}'}

    with pytest.raises(ExpressionReadIncomplete, match='reply_deduplication'):
        asyncio.run(s.runner(transport)(payload(), {}, {}, system_prompt=normal.SYSTEM))


@pytest.mark.parametrize('change', ['input', 'path'])
def test_changed_input_or_added_path_requires_fresh_deduplication(change):
    s = session()
    s.transform(payload(), normal.SYSTEM)
    asyncio.run(through_path(s))
    asyncio.run(s.read_next({}))
    asyncio.run(s.read_next({}))
    assert s.next_required() is None
    if change == 'input':
        s.transform(payload('补充：我轻轻握住你的前蹄'), normal.SYSTEM)
        asyncio.run(s.select_paths({'paths': ['interaction_reply']}))
    else:
        asyncio.run(s.select_paths({'paths': ['interaction_reply']}))
    assert not {'reply_deduplication', 'reply_review'} & s.loaded
    while s.next_required() != 'reply_deduplication':
        asyncio.run(s.read_next({}))
    assert 'reply_review' not in s.loaded
    asyncio.run(s.read_next({}))
    assert s.deduplication_reads == ['initial', 'input_changed' if change == 'input' else 'path_added']


def test_repetition_statistics_are_observations_without_information_gain_requirement():
    text = Prompts.reply_deduplication
    assert 'reply_repetition_context' in text
    assert '它不是禁词表，也不是改写清单' in text
    assert '不要求每句话或每个气泡增加新信息' in text
    assert '不要求模型对本轮或跨轮台词另做同义、意象或词句查重' in text
    assert '信息增量' not in Prompts.reply_expression
    assert '跨轮与本轮表达去重' not in Prompts.DEFAULT_CHARACTER_REPLY_STYLE_PROMPT


def test_review_checks_whole_turn_flow_without_changing_bubble_rule():
    assert '通读本轮所有可见片段' in Prompts.reply_review
    assert '用户明确要求的文体、列举或结构照常执行' in Prompts.reply_review
    assert '气泡数量及拆分仍按delivery决定' in Prompts.reply_review
    assert '同一个连贯意思可包含多个句子' in Prompts.delivery


def test_batch_skills_use_production_serial_gate():
    s = session()
    result = asyncio.run(s.load({'names': ['evidence', 'reply_expression', 'reply_review']}))
    assert 'evidence' in s.loaded and 'reply_expression' in s.loaded
    assert 'reply_review' not in s.loaded
    assert result['skills'][-1]['status'] == 'blocked'
