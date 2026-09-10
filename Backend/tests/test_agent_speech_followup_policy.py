"""Articulation stays Agent-owned; delayed plans carry evidence without rewriting."""
import asyncio
from copy import deepcopy
import json

import pytest

from test_agent_parity import business, decision
from test_autonomous_normal import model_result, row_message
from Backend.chat_modules.autonomous_normal import run_autonomous_turn, _current_character_mouth_occupied
from Backend.chat_modules.autonomous_followup import finalize_followup
from Backend.chat_modules.autonomous_followup_context import format_followup_context
from Backend.chat_modules.autonomous_prompt_rules import SPEECH_GUIDANCE


def test_consentual_intimate_mouth_guidance_selects_sounds_by_context_without_banning_repetition():
    for phrase in ('轻吻、试探', '被亲吻打断', '羞怯、被逗弄', '强烈快感'):
        assert phrase in SPEECH_GUIDANCE
    for sound in ('唔嗯', '嗯唔', '呜呜', '哈啊', '嗯啊'):
        assert sound in SPEECH_GUIDANCE
    assert '自动选择最贴切的音组' in SPEECH_GUIDANCE
    assert '可以在持续受限或同一情绪延续时重复' in SPEECH_GUIDANCE
    assert '不为变化而强行换音' in SPEECH_GUIDANCE
    assert '双方明确自愿' in SPEECH_GUIDANCE


@pytest.mark.parametrize('text', [
    '我亲上你的嘴，没有立刻松开。',
    '你点头后，我继续亲着你，故意不急着放开。',
    '我吻着你，感觉你的呼吸越来越急，也没有马上停下。',
    '我却还捂住你的嘴不放。',
])
def test_natural_ongoing_user_actions_mark_character_mouth_as_occupied(text):
    assert _current_character_mouth_occupied({'content': text})


@pytest.mark.parametrize('text', [
    '我刚才亲过你的嘴，现在已经松开了。',
    '我想亲你的嘴，但还没有靠近。',
    '如果我亲你的嘴，你会躲开吗？',
])
def test_finished_or_planned_actions_do_not_mark_character_mouth_as_occupied(text):
    assert not _current_character_mouth_occupied(text)


@pytest.mark.parametrize('parts', [
    [{'kind': 'speech', 'text': '唔，嗯……'}],
    [{'kind': 'action', 'text': '我点点头，等咽下嘴里的面包再开口'}],
    [{'kind': 'speech', 'text': '这段台词用于证明交付代码不会检查发声文风或要求重试'}],
])
def test_mouth_scene_does_not_check_rewrite_or_retry_parts(parts):
    text = '你的嘴里还含着面包，先别咽，回答我。'
    b = business(text=text)
    data = decision(False)
    data['first_bubble_speech'] = 'muffled'  # An old model field is inert too.
    data['bubbles'][0]['parts'] = deepcopy(parts)
    calls = []
    async def runner(*args, **kwargs):
        calls.append(1)
        return model_result() | {'final_response': json.dumps(data, ensure_ascii=False)}
    result = asyncio.run(run_autonomous_turn(messages=[row_message('m1', text)],
        character_profile='开朗的成年角色', environment='', model_config={},
        business_tools=b, harness_runner=runner))
    assert len(calls) == 1 and result['output_format_repairs'] == 0
    assert json.loads(result['envelope'])['bubbles'][0]['parts'] == parts


def test_agent_followup_preserves_plan_and_speaker_evidence(monkeypatch):
    from Backend import scheduled_followup as old
    def forbidden(*args, **kwargs):
        pytest.fail('Agent plans must not use old semantic rewrites or time-word filters')
    monkeypatch.setattr(old, '_apply_step4_subject_integrity_guard', forbidden)
    monkeypatch.setattr(old, '_is_early_morning_time_mismatch', forbidden)
    b = business(text='你刚才夸我了，我先想一想。')
    data = decision()
    data['bubbles'][0]['parts'] = [{'kind': 'speech', 'text': '是我在夸你刚才的表现'}]
    data['followup_decision'].update(summary='角色被夸帅，明天早晨再补充看法', reason='保留模型原始判断以核对')
    original = deepcopy(data)
    finalize_followup(b, data)
    plan = b.schedules[0]['plan']
    assert plan['seed'] == original['followup_decision']['summary']
    assert plan['reason'] == original['followup_decision']['reason']
    context = plan['agent_context']
    assert context['user_messages'][0]['content'] == b.text
    assert context['assistant_bubbles'] == original['bubbles']
    assert data == original
    task = {'character_id': b.request.character_id, 'due_at_ms': context['planned_at_ms'] + 120_000,
            'planner_json': json.dumps({'scheduled_followup': plan})}
    rendered = format_followup_context(task, now_ms=context['planned_at_ms'] + 180_000)
    payload = json.loads(rendered.split('\n', 2)[2])
    assert payload['clock']['elapsed_seconds'] == 180
    assert payload['evidence'] == context
    assert payload['plan']['summary'] == original['followup_decision']['summary']
    with pytest.raises(ValueError, match='another speaker'):
        format_followup_context({**task, 'character_id': 'other'})
    assert format_followup_context({'planner_json': '{}'}) == ''


@pytest.mark.parametrize('spirit', [False, True])
def test_death_prevents_new_reminders_even_if_the_user_requests_one(spirit):
    from Backend.chat_modules.harness_runtime import HarnessToolValidationError
    b = business(text='两分钟后提醒我喝水')
    if spirit:
        b.request._normal_dead_spirit_reply = True
    else:
        b.lifecycle = {'source_message_id': 'm1', 'reason': 'terminal event'}
    with pytest.raises(HarnessToolValidationError, match='已死亡'):
        asyncio.run(b.schedule(dict(kind='agreed', source_message_id='m1', summary='喝水', target_delay_seconds=120)))
    b.finalize_delivery(decision(False))
    assert b.schedules == []


def test_death_cancels_a_task_staged_earlier_in_the_same_turn():
    b = business(text='你已经死了。两分钟后提醒我喝水')
    task = asyncio.run(b.schedule(dict(kind='agreed', source_message_id='m1', summary='喝水', target_delay_seconds=120)))
    receipt = asyncio.run(b.death(dict(source_message_id='m1', reason='当前实际终局')))
    assert receipt['cancelled_schedule_ids'] == [task['id']]
    b.finalize_delivery(decision(False))
    assert b.schedules == []
