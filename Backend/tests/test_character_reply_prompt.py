"""All user-visible character generation modes receive the shared style prompt."""
import copy

import pytest

from Backend.chat_modules.character_reply_prompt import (
    DEFAULT_CHARACTER_REPLY_STYLE_PROMPT,
    apply_character_reply_style_prompt,
    with_character_reply_style_prompt,
)


@pytest.mark.parametrize('task', [
    'normal', 'galgame', 'galgame_lock', 'companion',
])
def test_visible_character_reply_tasks_receive_no_dash_instruction(task):
    payload = {'messages': [{'role': 'system', 'content': '原规则'},
                            {'role': 'user', 'content': '你好'}]}
    apply_character_reply_style_prompt(payload, task)
    system = payload['messages'][0]['content']
    assert system.startswith('原规则')
    assert DEFAULT_CHARACTER_REPLY_STYLE_PROMPT in system
    assert '默认不要使用破折号' in system
    assert '都用第二人称“你”或用户名字指用户' in system
    assert '无论当前用户是动作主体、动作对象、心理所想对象还是回忆对象' in system
    assert '例如' not in DEFAULT_CHARACTER_REPLY_STYLE_PROMPT
    assert '台词中的角色自称不受本条限制' in system
    assert '非台词描写仍保持当前角色为“我”、当前用户为“你”' in system
    assert '以用户明确要求为准' in system
    assert '【轻松聊天与用户压力】' in system


@pytest.mark.parametrize('task', ['classify', 'memory', 'ctx_memory', 'web_search'])
def test_internal_tasks_do_not_receive_character_reply_style(task):
    payload = {'messages': [{'role': 'system', 'content': '只输出内部 JSON'}]}
    original = copy.deepcopy(payload)
    apply_character_reply_style_prompt(payload, task)
    assert payload == original


def test_responses_input_and_missing_system_are_supported_idempotently():
    payload = {'input': [{'role': 'user', 'content': '你好'}]}
    apply_character_reply_style_prompt(payload, 'normal')
    apply_character_reply_style_prompt(payload, 'normal')
    assert payload['input'][0] == {
        'role': 'system', 'content': DEFAULT_CHARACTER_REPLY_STYLE_PROMPT}
    assert with_character_reply_style_prompt(
        DEFAULT_CHARACTER_REPLY_STYLE_PROMPT).count('【角色回复默认表达规则】') == 1


def test_harness_direct_system_receives_same_low_pressure_rule():
    from Backend.chat_modules.autonomous_direct import direct_system
    from Backend.chat_modules.Prompts import LOW_PRESSURE_CONVERSATION_PROMPT
    system = direct_system('core')
    assert system.startswith('core')
    assert LOW_PRESSURE_CONVERSATION_PROMPT in system
    assert LOW_PRESSURE_CONVERSATION_PROMPT in DEFAULT_CHARACTER_REPLY_STYLE_PROMPT


def test_old_default_marker_does_not_suppress_new_shared_rule():
    old = '【角色回复默认表达规则】\n默认不要使用破折号。'
    updated = with_character_reply_style_prompt(old)
    assert updated.startswith(old)
    assert updated.count('【角色回复默认表达规则】') == 1
    assert updated.count('【轻松聊天与用户压力】') == 1
    assert with_character_reply_style_prompt(updated) == updated
