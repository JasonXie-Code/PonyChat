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


def test_moved_rules_have_a_single_text_owner_and_keep_exceptions():
    for phrase in ('同一称呼没有新的明确作用时省略', '同一音节组合、节奏、尾音',
                   '减少重复的情绪结论和陪伴承诺', '角色特色意象可以点缀'):
        owners = [name for name, text in Prompts.CHAT_SKILL_TEXTS.items() if phrase in text]
        assert owners == ['reply_deduplication']
        assert phrase not in Prompts.DEFAULT_CHARACTER_REPLY_STYLE_PROMPT
    assert '不把同一部位再次出现直接判错' in Prompts.reply_deduplication
    assert '状态和意图相同时允许短音自然重复' in Prompts.reply_deduplication


def test_lexical_habits_are_a_required_check_with_a_stated_action():
    """只展示重复用词不够，要求里必须同时给出该做什么。"""
    text = Prompts.reply_deduplication
    # 检查清单必须覆盖用词这一类
    assert '开场句式、称呼、拟音、收尾含义和习惯用词' in text
    # 并且给出动作与边界说明
    for phrase in ('习惯用词是例外', '改用自然说法、常见同义词或直接省略',
                   '没有新的表达作用时不再沿用', '不算用同义改写掩盖同一模板'):
        assert phrase in text
        owners = [name for name, body in Prompts.CHAT_SKILL_TEXTS.items() if phrase in body]
        assert owners == ['reply_deduplication']
    # 既有边界不得被这次改动移除
    assert '统计只作定位证据，不是禁词表' in text
    assert '专有名称可以正常重复' in text


def test_batch_skills_use_production_serial_gate():
    s = session()
    result = asyncio.run(s.load({'names': ['evidence', 'reply_expression', 'reply_review']}))
    assert 'evidence' in s.loaded and 'reply_expression' in s.loaded
    assert 'reply_review' not in s.loaded
    assert result['skills'][-1]['status'] == 'blocked'
