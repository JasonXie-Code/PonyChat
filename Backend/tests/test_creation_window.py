import asyncio
import copy
import pytest
from fastapi import HTTPException
from Backend.creation.window import fit_history
from Backend.creation.context import DEFAULT_LAYOUT, BASE_RULE, build_messages


async def count(messages):
    return sum(len(m['content'])+3 for m in messages)


def test_short_history_unchanged():
    session = {'character_setting': '角色', 'instructions': '要求'}
    history = [{'role': 'user', 'content': '你好'}]
    result = asyncio.run(fit_history({}, session, history, {'context_length': 65536}, count))
    assert result == build_messages({}, session, history)


def test_thousand_turns_keep_maximum_recent_turns_and_layout_without_mutating_history():
    layout = copy.deepcopy(DEFAULT_LAYOUT)
    layout.insert(3, {'id': 'custom', 'kind': 'custom', 'title': '自定义', 'text': '固定内容'})
    layout[0]['text'] = '系统'
    session = {'character_setting': '角色', 'instructions': '要求', 'context_layout': layout}
    history = [{'role': role, 'content': f'{i:04d}'+('文'*40)}
               for i in range(1000) for role in ('user', 'assistant')]
    history.append({'role': 'user', 'content': '最新输入'})
    original = copy.deepcopy(history)
    config = {'context_length': 65536, 'options': {'max_tokens': 8192}}
    result = asyncio.run(fit_history({}, session, history, config, count))
    tokens = asyncio.run(count(result))
    assert tokens <= 65536-8192-1
    assert result[:2] == [{'role': 'system', 'content': text} for text in [BASE_RULE, '角色']]
    assert result[-3:-1] == [{'role': 'system', 'content': text} for text in ['固定内容', '要求']]
    assert result[-1]['content'] == '最新输入'
    assert result[2]['role'] == 'user' and result[2]['content'] != history[0]['content']
    assert len(result) < len(history)
    dropped = next(i for i, m in enumerate(history) if m['content'] == result[2]['content'])
    assert asyncio.run(count(build_messages({}, session, history[dropped-2:]))) > 65536-8192-1
    assert history == original


def test_reordered_input_and_settings_preserved():
    layout = copy.deepcopy(DEFAULT_LAYOUT)
    layout[0]['text'] = 'system'
    layout[3], layout[4] = layout[4], layout[3]
    session = {'character_setting': '角色', 'context_layout': layout}
    history = [{'role': 'user', 'content': 'old'*100}, {'role': 'assistant', 'content': 'reply'*100},
               {'role': 'user', 'content': '最新'}]
    result = asyncio.run(fit_history({}, session, history,
        {'context_length': len(BASE_RULE) + 100, 'options': {'max_tokens': 20}}, count))
    assert result[-1]['content'] == '最新'
    assert len(result) == 3


def test_oversized_latest_input_not_silently_cut_and_actual_capacity_used():
    session = {'character_setting': '角色'}
    history = [{'role': 'user', 'content': '长'*1000}]
    with pytest.raises(HTTPException) as error:
        asyncio.run(fit_history({}, session, history,
            {'context_length': 65536, 'options': {'max_tokens': 20}}, count, capacity=500))
    assert error.value.status_code == 413 and history[0]['content'] == '长'*1000
