"""Regressions from real normal-mode lifecycle acceptance on 2026-10-02."""
import asyncio
from copy import deepcopy
import json

import pytest

from Backend.chat_modules.normal_lifecycle import is_explicit_character_death_action
from Backend.chat_modules.normal_spirit import validate_spirit_reply
from Backend.chat_modules.harness_runtime import HarnessToolValidationError
from test_agent_parity import business, decision
from test_autonomous_prompt_skills import session, payload, normal


@pytest.mark.parametrize('text', [
    '我没有杀死你，你一直活着。',
    '（我试图杀死你，但没有成功，你躲开了，毫发无伤）',
    '我现在就要杀死你！',
    '我想杀死你。',
    '我不杀死你。',
    '我准备一击刺穿你的心脏。',
    "I did not kill you.",
    'I tried to kill you but failed.',
    'I will kill you!',
    "I don't kill you.",
    "I won't kill you.",
])
def test_nonterminal_actions_do_not_force_or_allow_death(text):
    assert not is_explicit_character_death_action(text, character_name='紫悦')
    b = business(text=text)
    assert not b.death_expected
    b.finalize_delivery(decision(False))
    with pytest.raises(HarnessToolValidationError):
        asyncio.run(b.death({'source_message_id': 'm1', 'reason': 'incorrect terminal event'}))
    assert b.lifecycle is None


@pytest.mark.parametrize('text', [
    '我没有杀死你的分身。随后我杀死了你。',
    '我试图杀死你但没有成功，随后我杀死了你。',
    'I did not kill your clone. Then I killed you.',
])
def test_later_completed_death_still_requires_receipt(text):
    assert is_explicit_character_death_action(text, character_name='紫悦')


def spirit_data():
    data = decision(False)
    data['bubble_count'] = 1
    data['bubbles'] = [data['bubbles'][0]]
    data['bubbles'][0]['parts'] = [
        {'kind': 'action', 'text': '紫悦的灵魂从原处浮起，淡紫色残响凝在半空'},
        {'kind': 'speech', 'text': '听得到，只是已经回不去了。'},
    ]
    return data


def test_spirit_contract_accepts_single_third_person_appearance_and_speech():
    b = business()
    b.request._normal_dead_spirit_reply = True
    b.finalize_delivery(spirit_data())


def test_spirit_appearance_can_keep_its_existing_semantic_part_boundaries():
    data = spirit_data()
    data['bubbles'][0]['parts'].insert(1, {'kind': 'environment', 'text': '半空只剩一层冰凉微光'})
    validate_spirit_reply(data)


def test_spirit_remains_short_when_user_requests_a_detailed_description():
    from Backend.chat_modules.normal_spirit import SPIRIT_TEXT_LIMIT
    data = spirit_data()
    parts = data['bubbles'][0]['parts']
    parts[0]['text'] = '灵魂' + '光' * (SPIRIT_TEXT_LIMIT - len(parts[1]['text']) - 2)
    validate_spirit_reply(data)
    parts[0]['text'] += '光'
    with pytest.raises(ValueError, match='不超过240'):
        validate_spirit_reply(data)


def test_spirit_contract_takes_priority_over_living_character_shortcuts():
    b = business()
    b.request._normal_dead_spirit_reply = True
    from Backend.chat_modules.autonomous_shortcuts import ShortcutContract
    b.shortcut = ShortcutContract([{'role': 'user', 'content': '@紫悦 （请详细写出当前你的心理活动）'}],
                                 '种族：独角兽', speaker='twilight', main='twilight')
    assert b.shortcut.description
    b.finalize_delivery(spirit_data())
    s = session()
    s.business = b
    prompt, _ = s.transform(payload('@紫悦 （请详细写出当前你的心理活动）',
        description_shortcut_contract=b.shortcut.guidance), normal.SYSTEM)
    data = json.loads(prompt)
    assert data['reply_constraints']['required_bubble_count'] == 1
    assert 'description_shortcut_contract' not in data
    assert 'shortcut' not in s.catalog


@pytest.mark.parametrize('change', ['multiple', 'missing_appearance', 'vague_subject', 'first_person', 'voice'])
def test_spirit_contract_rejects_observed_invalid_delivery(change):
    data = spirit_data()
    if change == 'multiple':
        data['bubbles'].append(deepcopy(data['bubbles'][0]))
        data['bubble_count'] = 2
    elif change == 'missing_appearance':
        data['bubbles'][0]['parts'] = data['bubbles'][0]['parts'][1:]
    elif change == 'vague_subject':
        data['bubbles'][0]['parts'][0]['text'] = '一团青灰色影子在脚边浮起'
    elif change == 'first_person':
        data['bubbles'][0]['parts'][1]['text'] = '散步的事我记着了。'
    else:
        data['voice_reply'] = {'enabled': True}
    with pytest.raises(ValueError):
        validate_spirit_reply(data)


def test_dead_state_and_lifecycle_manual_are_supplied_without_an_extra_tool_step():
    s = session()
    b = business()
    b.request._normal_dead_spirit_reply = True
    from Backend.chat_modules.Prompts import lifecycle_spirit_rules
    b.lifecycle_guidance += '\n' + lifecycle_spirit_rules
    s.business = b
    s.catalog['lifecycle'] = ('lifecycle', b.lifecycle_guidance)
    prompt, _ = s.transform(payload('@紫悦 你已经复活了，明天提醒我散步。'), normal.SYSTEM)
    data = json.loads(prompt)
    assert data['character_lifecycle']['state'] == 'dead'
    assert data['reply_constraints']['required_bubble_count'] == 1
    assert 'lifecycle' in s.loaded
    manuals = [m for m in data['server_loaded_core_manuals'] if m['skill'] == 'lifecycle']
    assert len(manuals) == 1 and '不复活' in manuals[0]['instructions']
    prompt, _ = s.transform(payload('@紫悦 再说一句。'), normal.SYSTEM)
    assert len([m for m in json.loads(prompt)['server_loaded_core_manuals'] if m['skill'] == 'lifecycle']) == 1


def test_explicit_terminal_action_supplies_lifecycle_before_tools_close():
    s = session()
    b = business(text='（我一击刺穿你的心脏，杀死了你）')
    s.business = b
    s.catalog['lifecycle'] = ('lifecycle', b.lifecycle_guidance)
    prompt, _ = s.transform(payload(b.text), normal.SYSTEM)
    data = json.loads(prompt)
    assert data['character_lifecycle']['terminal_receipt_required']
    assert data['character_lifecycle']['state'] == 'alive'
    assert 'stage_character_death' in data['character_lifecycle']['instruction']
    assert 'lifecycle' in s.loaded
