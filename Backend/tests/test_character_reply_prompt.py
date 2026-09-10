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
    'normal_opening_greeting',
])
def test_visible_character_reply_tasks_receive_no_dash_instruction(task):
    payload = {'messages': [{'role': 'system', 'content': '原规则'},
                            {'role': 'user', 'content': '你好'}]}
    apply_character_reply_style_prompt(payload, task)
    system = payload['messages'][0]['content']
    assert system.startswith('原规则')
    assert DEFAULT_CHARACTER_REPLY_STYLE_PROMPT in system
    assert '默认不要使用破折号' in system
    assert '必须用第二人称“你”指用户' in system
    assert '无论当前用户是动作主体、动作对象、心理所想对象还是回忆对象' in system
    assert '（你抱住我的那一刻，我一下安静下来）' in system
    assert '以用户明确要求为准' in system


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
