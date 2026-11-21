"""Behavior boundaries for Agent follow-ups and deterministic lock settlement."""
import asyncio
import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import pytest

from Backend.chat_modules.autonomous_business import BusinessTools
from Backend.chat_modules.autonomous_followup import finalize_followup
from Backend.chat_modules.autonomous_reply import reply_envelope
from Backend.chat_modules.autonomous_transaction import install_memory_transaction
from Backend.proactive_settings import ProactiveSettings
from Backend.galgame.lock_state import baseline, preview_tool, validate_preview
from Backend.chat_modules.harness_runtime import HarnessToolValidationError, _closed_schema
from test_autonomous_upgrade_integration import database, request, save
from test_autonomous_normal import model_result
from Backend.chat_modules.autonomous_shortcuts import ShortcutContract


def business(req=None, text='你先看着窗外，我想想刚才的问题。', enabled=True):
    req = req or request()
    shortcut = SimpleNamespace(guidance='', description=False, story=False)
    return BusinessTools(req, [{'role': 'user', 'content': text, 'message_id': 'm1'}],
                         shortcut, ProactiveSettings(enabled=enabled), [])


def decision(enabled=True):
    data = json.loads(model_result('好，我看看窗外。')['final_response'])
    data['followup_decision'] = {'enabled': enabled, 'reason': '角色可独立分享刚观察到的新变化',
        'summary': '用户尚未回应；角色继续观察窗边，稍后分享自己的新发现，不替用户作答。',
        'target_delay_seconds': 120}
    return data


def test_followup_is_committed_with_reply_and_not_in_visible_envelope(database):
    b, data = business(), decision()
    b.finalize_delivery(data)
    assert len(b.schedules) == 1
    envelope, _ = reply_envelope(json.dumps(data))
    assert 'followup_decision' not in envelope and '用户尚未回应' not in envelope
    install_memory_transaction(b.request, None, b)
    assert asyncio.run(save(database, b.request))
    with sqlite3.connect(database.db_path) as conn:
        row = conn.execute('SELECT source_message_id,cancel_if_user_replies,allow_reschedule_after_send FROM scheduled_followups').fetchone()
        assert row == ('a1', 1, 0)


@pytest.mark.parametrize('case', ['disabled', 'ended', 'internal', 'opening', 'description', 'dead', 'missing_source'])
def test_followup_hard_stop_overrides_positive_model_decision(case):
    b = business(enabled=case != 'disabled', text='晚安，我去睡觉了' if case == 'ended' else '继续聊')
    if case == 'internal': b.request._normal_internal_proactive_trigger = True
    if case == 'opening': b.request._is_new_contact_opening = True
    if case == 'description': b.shortcut.description = True
    if case == 'dead': b.lifecycle = {'reason': 'terminal'}
    if case == 'missing_source': b.history[0]['message_id'] = ''
    assert not finalize_followup(b, decision())['enabled']
    assert not b.schedules


def test_followup_redecision_replaces_draft_without_duplicate():
    b = business()
    finalize_followup(b, decision())
    finalize_followup(b, decision())
    assert len(b.schedules) == 1
    finalize_followup(b, decision(False))
    assert b.schedules == []


def test_guest_does_not_schedule_a_main_character_followup():
    req = request()
    req.reply_character_id = 'pinkie'
    req._normal_speaker_is_guest = True
    b = business(req)
    assert finalize_followup(b, decision())['blocked_reason'] == 'temporary_guest_speaker'
    assert not b.schedules


@pytest.mark.parametrize('text', ['别再给我发消息', '不要主动打扰我', '不用补一句'])
def test_explicit_do_not_contact_prevents_followup(text):
    b = business(text=text)
    assert not finalize_followup(b, decision())['enabled']
    assert not b.schedules


def test_terminal_event_requires_tool_receipt_before_delivery():
    b = business(text='你被事故杀死了')
    b.death_expected = True
    with pytest.raises(ValueError, match='stage_character_death'):
        b.finalize_delivery(decision(False))
    b.lifecycle = {'source_message_id': 'm1', 'reason': '本轮终局'}
    b.finalize_delivery(decision(False))


def test_reminder_retries_are_idempotent_and_different_reminders_survive():
    b = business(text='两分钟后提醒我喝水')
    assert b.reminder_expected
    with pytest.raises(ValueError, match='stage_schedule'):
        b.finalize_delivery(decision(False))
    args = dict(kind='agreed', source_message_id='m1', summary='喝水', target_delay_seconds=120)
    first = asyncio.run(b.schedule(args))
    again = asyncio.run(b.schedule(dict(args, reason='重复调用', task_type='reminder')))
    assert first['id'] == again['id'] and again['already_staged'] and len(b.schedules) == 1
    b.finalize_delivery(decision(False))
    asyncio.run(b.schedule(dict(args, summary='开会')))
    assert len(b.schedules) == 2


@pytest.mark.parametrize('text', ['如果两分钟后提醒我会怎样', '不用两分钟后提醒我了', '明天提醒我做这件事'])
def test_ambiguous_or_cancelled_reminder_does_not_force_schedule(text):
    assert not business(text=text).reminder_expected


@pytest.mark.parametrize('patch', [None, {'enabled': 'true'}, {'enabled': True, 'reason': ''},
    {'enabled': True, 'reason': 'new', 'summary': 'new', 'target_delay_seconds': True}])
def test_malformed_decision_never_schedules(patch):
    b, data = business(), decision()
    data['followup_decision'] = patch
    with pytest.raises(ValueError): finalize_followup(b, data)
    assert not b.schedules


@pytest.mark.parametrize('failure', ['cancelled', 'disabled', 'new_user', 'none'])
def test_followup_commit_rechecks_cancellation_and_settings(database, failure):
    b = business()
    finalize_followup(b, decision())
    install_memory_transaction(b.request, None, b)
    assert asyncio.run(save(database, b.request))
    with sqlite3.connect(database.db_path) as conn:
        fid = conn.execute('SELECT id FROM scheduled_followups').fetchone()[0]
        conn.execute('UPDATE scheduled_followups SET status=?', ('cancelled' if failure == 'cancelled' else 'processing',))
        if failure == 'disabled':
            conn.execute('INSERT INTO user_settings(user_id,settings) VALUES(1,?)', (json.dumps({'proactive_messages_enabled': False}),))
        if failure == 'new_user':
            conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) VALUES('u2','u2','c1','user','我回来了',3000,3)")
    req = request()
    req._normal_internal_followup_task_id = fid
    req._normal_internal_proactive_source_message_id = 'a1'
    req._autonomous_pending_reply_message_ids = ('a2',)
    install_memory_transaction(req, None)
    import aiosqlite
    async def commit():
        async with aiosqlite.connect(database.db_path) as conn:
            await conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) VALUES('a2','a2','c1','assistant','新发现',4000,4)")
            await req._autonomous_before_reply_commit(conn)
            await conn.commit()
    if failure == 'none':
        asyncio.run(commit())
        with sqlite3.connect(database.db_path) as conn:
            assert conn.execute('SELECT status,sent_message_id FROM scheduled_followups').fetchone() == ('sent', 'a2')
    else:
        with pytest.raises(RuntimeError): asyncio.run(commit())
        with sqlite3.connect(database.db_path) as conn:
            assert not conn.execute("SELECT 1 FROM messages WHERE message_id='a2'").fetchone()


def preview(state=None, changes=None):
    state = state or {}
    req = SimpleNamespace(_galgame_char_name='云杉')
    tool = preview_tool(req, state)
    _closed_schema(tool.parameters)
    inputs = [{'field': path, 'value': value, 'reason': '本轮新事件'} for path, value in (changes or {}).items()]
    result = asyncio.run(tool.callback({'changes': inputs, 'character_gender': '女'}))
    return req, result


def test_lock_neutral_tick_is_exact_and_preview_never_mutates_state():
    state = baseline({})
    original = deepcopy(state)
    req, result = preview(state)
    settled = result['settled_state']
    assert (settled['organ_fill']['stomach'], settled['organ_fill']['bladder'], settled['organ_fill']['rectum'],
            settled['char_vitals']['thirst']) == (29, 12, 1, 31)
    assert state == original
    data = {**settled, 'score': {'current': 40, 'status': 'playing'}}
    assert validate_preview(req, data, state) == ''
    data['char_vitals']['thirst'] += 1
    assert '逐值复制' in validate_preview(req, data, state)


def test_lock_food_transmission_and_death_are_available_before_prose():
    _, result = preview(changes={'organ_fill.stomach': 60})
    assert result['settled_state']['organ_fill']['rectum'] == 11
    req, dead = preview(changes={'char_vitals.blood_loss': 96})
    assert dead['death'] and '失血' in dead['death_reason']
    assert dead['narrative_hints']['body_state']
    data = {**deepcopy(dead['settled_state']), 'score': {'current': 40, 'status': 'playing'}}
    assert '终局' in validate_preview(req, data, {})
    data['score'] = {'current': 0, 'status': 'lose'}
    assert validate_preview(req, data, {}) == ''


def test_lock_changed_values_require_direct_event_reasons():
    req = SimpleNamespace()
    tool = preview_tool(req, {})
    with pytest.raises(HarnessToolValidationError, match='事件依据'):
        asyncio.run(tool.callback({'changes': [{'field': 'char_vitals.thirst', 'value': 0, 'reason': ''}], 'character_gender': '女'}))
    assert req._galgame_lock_settlement is None


@pytest.mark.parametrize('changes', [
    [{'field': 'char_vitals.thirst', 'value': True, 'reason': '喝水'}],
    [{'field': 'other.thirst', 'value': 0, 'reason': '喝水'}],
    [{'field': 'char_vitals.thirst', 'value': 0, 'reason': '喝水'}] * 2,
])
def test_lock_sparse_changes_fail_closed(changes):
    req = SimpleNamespace()
    with pytest.raises(HarnessToolValidationError):
        asyncio.run(preview_tool(req, {}).callback({'changes': changes, 'character_gender': '女'}))
    assert req._galgame_lock_settlement is None


def test_game_scene_boundary_recovery_preserves_model_values_and_checks():
    from Backend.galgame.output_contract import REQUIRED_SCENE_FIELDS, restore_scene_siblings
    scene = {key: '场景原文' for key in REQUIRED_SCENE_FIELDS}
    req, result = preview(changes={'char_vitals.blood_loss': 96})
    nested = {'score': {'current': 0, 'status': 'lose'},
              'scene': {**scene, **result['settled_state'], 'relationship_stage': '相识'}}
    recovered = restore_scene_siblings(nested, 'galgame_lock')
    assert recovered['scene'] == scene
    assert recovered['relationship_stage'] == '相识'
    assert validate_preview(req, recovered, {}) == ''
    # This repairs nesting only: genuinely omitted fields remain missing.
    assert 'suggested_options' not in recovered
    assert 'char_vitals' in nested['scene'] and 'char_vitals' not in nested
    wrong_values = deepcopy(recovered)
    wrong_values['char_vitals']['blood_loss'] = 0
    assert '逐值复制' in validate_preview(req, wrong_values, {})
    for ambiguous in ({**nested, 'char_vitals': {'blood_loss': 0}},
                      {**nested, 'scene': {**nested['scene'], 'unknown': '不能猜字段'}}):
        assert restore_scene_siblings(ambiguous, 'galgame_lock') is ambiguous


def test_lock_opening_mood_and_stale_baseline():
    state = {'_init_mood_delta': {'fear': 9}}
    req, result = preview(state)
    assert req._galgame_lock_settlement['baseline']['char_mood']['fear'] == 59
    newer = baseline(state)
    newer['organ_fill']['stomach'] = 70
    assert '过期' in validate_preview(req, {**result['settled_state'], 'score': {}}, newer)


@pytest.mark.parametrize('fatal_state', [{'blood_loss': 96}, {'oxygen': 5}, {'body_temp': 5},
    {'body_temp': 95}, {'infection': 92}, {'stamina': 3, 'blood_loss': 70}, {'thirst': 98}])
def test_saved_terminal_state_cannot_be_healed_by_an_ordinary_turn(fatal_state):
    original = baseline({'char_vitals': fatal_state})
    attempted_healing = {'char_vitals.' + key: baseline({})['char_vitals'][key] for key in fatal_state}
    req, result = preview(original, attempted_healing)
    assert result['terminal_at_start'] and result['death']
    assert result['settled_state'] == original
    assert '终局' in validate_preview(req, {**result['settled_state'], 'score': {'current': 1, 'status': 'playing'}}, original)


def test_rescue_before_the_death_threshold_still_takes_effect():
    _, result = preview({'char_vitals': {'blood_loss': 89}}, {'char_vitals.blood_loss': 60})
    assert not result['terminal_at_start'] and not result['death']
    assert result['settled_state']['char_vitals']['blood_loss'] == 59


@pytest.mark.parametrize('verb', ['写出', '描写出'])
@pytest.mark.parametrize('target,kind', [('你的心理活动','thought'), ('你的身体状态','body_state'), ('你看到的画面','visual')])
def test_description_shortcut_requires_exactly_three_pure_paragraphs(verb, target, kind):
    history = [{'role': 'user', 'content': f'（请详细{verb}当前{target}）', 'message_id':'m1'}]
    contract = ShortcutContract(history, '成年女性，人类', speaker='twilight', main='twilight')
    assert contract.description
    data = json.loads(model_result('我的注意力回到眼前\n\n我的心情渐渐安定\n\n我留意着细微的变化')['final_response'])
    data['reply_language']['language'] = 'Chinese'
    for b in data['bubbles']: b['parts'][0]['kind'] = kind
    assert contract.delivery_error(data) == ''
    data['bubbles'][1]['parts'][0]['kind'] = 'speech'
    assert '非speech' in contract.delivery_error(data)
    data['bubbles'][1]['parts'][0]['kind'] = ' Speech '
    assert '非speech' in contract.delivery_error(data)
    data['bubbles'][1]['parts'][0]['kind'] = kind
    data['bubbles'].pop()
    data['bubble_count'] = 2
    assert '3个气泡' in contract.delivery_error(data)
