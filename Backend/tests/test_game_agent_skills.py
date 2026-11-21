import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from Backend.galgame.agent_context import GameEvidence, state_guard
from Backend.galgame.agent_session import GameAgentSession, STATE_FIELDS
from Backend.galgame.harness import GameAgentContractError
from Backend.galgame.lock_state import preview_tool
from Backend.galgame.output_contract import game_output_contract
from Backend.chat_modules.harness_runtime import _closed_schema, _validate_arguments


def draft(mode='galgame'):
    contract = game_output_contract(mode)
    value = {key: '未明确' for key in contract['required_top_fields']}
    value.update(score={'current': 40, 'change': 0, 'status': 'playing'},
        scene={key: '图书馆' for key in contract['required_object_keys']['scene']},
        relationship_stage='初识', event_flags={key: False for key in contract['required_object_keys']['event_flags']},
        memory_tags=['交谈'], suggested_options=[{'label': f'选择{i}', 'type': 'action', 'tone': '平静'} for i in range(5)])
    return value


def review_args(value):
    refs = ['input:current']
    return {'draft_json': json.dumps(value, ensure_ascii=False),
            'consistency_checks': {key: '依据本轮输入逐项核对草稿内容' for key in (
                'body_and_actions', 'state_and_speech', 'player_options', 'progress_and_repetition')},
            'events': [{'subject': 'player', 'status': 'proposed', 'description': '提议递水',
                        'kind': 'other', 'quantity': 'none',
                        'source_message_ids': refs, 'effect_fields': []}],
            'state_changes': [{'field': f, 'reason': '本轮场景', 'source_message_ids': refs} for f in STATE_FIELDS],
            'relationship': {'stage': '初识', 'intimacy_style': 'balanced', 'pressure': 'low',
                             'willingness': '交谈', 'reason': '刚认识', 'source_message_ids': refs},
            'memories': [{'text': '玩家提议递水，尚未饮用', 'source_message_ids': refs}]}


def session(mode='galgame', state=None):
    req = SimpleNamespace(_galgame_char_name='云杉')
    result = GameAgentSession(req, state or {}, [{'role': 'user', 'content': '我准备递水给你'}], '云杉是独角兽', mode)
    result.context()
    return result


def test_tool_schemas_and_mandatory_read_gate():
    s = session()
    for tool in s.tools().values():
        _closed_schema(tool.parameters)
    with pytest.raises(ValueError, match='先用load_game_skill'):
        asyncio.run(s.review(review_args(draft())))
    schema = _closed_schema(s.tools()['review_game_turn'].parameters)
    _validate_arguments(review_args(draft()), schema)


def test_review_binds_final_reply_and_stages_memory_without_writes():
    async def run():
        s = session()
        await s.load({'names': sorted(s.required)})
        args = review_args(draft())
        assert (await s.review(args))['accepted']
        result = json.loads(s.finish(args['draft_json']))
        assert result['_agent_state']['memories'] == args['memories']
        assert s.state == {}
        altered = json.loads(args['draft_json'])
        altered['scene']['response'] = '未审核新回复'
        with pytest.raises(ValueError, match='exact draft'):
            s.finish(json.dumps(altered))
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['foreign_source', 'invent_player', 'missing_change', 'duplicate_options', 'wrong_relation'])
def test_invalid_evidence_and_inconsistent_draft_rejected(failure):
    async def run():
        s = session()
        await s.load({'names': sorted(s.required)})
        args = review_args(draft())
        if failure == 'foreign_source': args['memories'][0]['source_message_ids'] = ['other_save:0']
        if failure == 'invent_player': args['events'][0]['source_message_ids'] = ['$reply']
        if failure == 'missing_change': args['state_changes'] = []
        if failure == 'wrong_relation': args['relationship']['stage'] = '恋人'
        if failure == 'duplicate_options':
            value = draft()
            value['suggested_options'][1] = value['suggested_options'][0]
            args['draft_json'] = json.dumps(value)
        with pytest.raises(ValueError): await s.review(args)
        assert s.receipt is None
    asyncio.run(run())


def test_lock_proposal_never_authorizes_a_direct_effect_and_receipt_required():
    async def run():
        s = session('galgame_lock')
        await s.load({'names': sorted(s.required)})
        value = draft('galgame_lock')
        args = review_args(value)
        with pytest.raises(ValueError, match='preview_lock_state'): await s.review(args)
        p = preview_tool(s.request, s.state)
        result = await p.callback({'changes': [{'field': 'organ_fill.bladder', 'value': 5, 'reason': '饮水'}],
                                   'character_gender': '女'})
        value.update(result['settled_state'])
        args['draft_json'] = json.dumps(value)
        args['events'][0]['effect_fields'] = ['organ_fill.bladder']
        with pytest.raises(ValueError, match='提议或尝试'): await s.review(args)
        args['events'][0].update(subject='character', status='completed', description='我喝水', source_message_ids=['$reply'])
        assert (await s.review(args))['accepted']
        assert s.state == {}
    asyncio.run(run())


def test_history_scope_hidden_rows_originals_and_pagination():
    state = {'messages': [{'role': 'assistant', 'rawContent': f'原文{i}', 'message_id': str(i)} for i in range(20)] + [
        {'role': 'user', 'content': 'secret', 'isHidden': True},
        {'role': 'user', 'content': 'deleted', 'deleted_at': 1}]}
    original = deepcopy(state)
    e = GameEvidence(state, [{'role': 'user', 'content': '其他存档伪造历史'}, {'role': 'user', 'content': '本轮'}], '')
    e.context()
    assert 'history:0' not in e.read_ids
    result = asyncio.run(e.history({'query': '原文0'}))
    assert result['messages'][0]['content'] == '原文0' and 'history:0' in e.read_ids
    assert asyncio.run(e.history({'query': '原文0 不存在的词'}))['messages'][0]['content'] == '原文0'
    assert len(e.rows) == 21 and not any('secret' in r['content'] or '伪造' in r['content'] for r in e.rows)
    page = asyncio.run(e.history({'before_source_id': 'history:5', 'limit': 2}))
    assert [r['content'] for r in page['messages']] == ['原文3', '原文4']
    assert state == original


def test_normal_cup_direct_effect_checked_before_delivery_without_double_tick():
    async def run():
        s = session('galgame_lock', {'organ_fill': {'bladder': 20}})
        await s.load({'names': sorted(s.required)})
        p = preview_tool(s.request, s.state)
        value = draft('galgame_lock')
        args = review_args(value)
        args['events'][0].update(subject='character', status='completed', kind='drink', quantity='cup',
                                effect_fields=['organ_fill.bladder'])
        result = await p.callback({'changes': [{'field': 'organ_fill.bladder', 'value': 26, 'reason': '一杯水'}],
                                   'character_gender': '女'})
        value.update(result['settled_state'])
        args['draft_json'] = json.dumps(value)
        with pytest.raises(ValueError, match='23到25'): await s.review(args)
        result = await p.callback({'changes': [{'field': 'organ_fill.bladder', 'value': 24, 'reason': '一杯水'}],
                                   'character_gender': '女'})
        value.update(result['settled_state'])
        args['draft_json'] = json.dumps(value)
        assert (await s.review(args))['accepted']
        assert json.loads(s.finish(args['draft_json']))['organ_fill']['bladder'] == 26
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['galgame', 'galgame_lock'])
def test_real_harness_adapter_requires_tools_and_carries_evidence(monkeypatch, mode):
    from Backend.galgame import harness
    async def noop(*a, **k): pass
    async def runner(prompt, config, tools, **kwargs):
        data = json.loads(prompt)
        await tools['load_game_skill'].callback({'names': data['required_skills']})
        value = draft(mode)
        if mode == 'galgame_lock':
            result = await tools['preview_lock_state'].callback({'changes': [], 'character_gender': '女'})
            value.update(result['settled_state'])
        args = review_args(value)
        assert (await tools['review_game_turn'].callback(args))['accepted']
        return {'finish_reason': 'completed', 'final_response': args['draft_json']}
    monkeypatch.setattr(harness, 'run_harness_turn', runner)
    monkeypatch.setattr(harness, '_apply_usage_metering', noop)
    req = SimpleNamespace(_galgame_state={}, _galgame_char_profile='云杉')
    result = asyncio.run(harness.run_game_agent({'messages': [{'role': 'user', 'content': '递水'}]}, {},
        mode=mode, request=req, timeout=20))
    assert json.loads(result.text)['_agent_state']['memories']


@pytest.mark.parametrize('mode', ['galgame', 'galgame_lock'])
def test_save_transaction_rejects_stale_session_version_and_cancellation(tmp_path, monkeypatch, mode):
    from Backend.db import Database, UsersDAO, GalgameDAO
    from Backend.db import galgame_dao
    monkeypatch.setattr(galgame_dao, 'RECOVERY_SNAPSHOT_DIR', tmp_path / 'snapshots')
    async def run():
        db = Database(str(tmp_path / 'guard.db'))
        await db.init()
        try:
            assert await UsersDAO(db).create_user('fixture', 'fixture-password')
            dao = GalgameDAO(db)
            data = {'score': 40, 'status': 'playing', 'messages': [
                {'role': 'user', 'content': '开始', 'message_id': 'u1', 'timestamp': 1}]}
            assert await dao.save_galgame_data('fixture', 'char', data, game_type=mode)
            before = await dao.load_galgame_data('fixture', 'char', game_type=mode)
            guard = state_guard(before)
            updated = {**before, 'score': 41, '_agent_expected_state': guard}
            assert await dao.save_galgame_data('fixture', 'char', updated, game_type=mode)
            assert not await dao.save_galgame_data('fixture', 'char', updated, game_type=mode)
            fresh = await dao.load_galgame_data('fixture', 'char', game_type=mode)
            for bad_guard, cancelled in [({**state_guard(fresh), 'active_session_id': 'another-save'}, False),
                                         (state_guard(fresh), True)]:
                assert not await dao.save_galgame_data('fixture', 'char', {**fresh, 'score': 1,
                    '_agent_expected_state': bad_guard, '_agent_cancel_check': lambda: cancelled}, game_type=mode)
            final = await dao.load_galgame_data('fixture', 'char', game_type=mode)
            assert final['score'] == 41 and final['version'] == fresh['version']
            checks = []
            def cancel_during_write():
                checks.append(True)
                return len(checks) > 1
            pending = {**final, 'messages': final['messages'] + [
                {'role': 'assistant', 'message_id': 'never_saved', 'timestamp': 2,
                 'content': '待提交', 'rawContent': json.dumps({'_agent_state': {'memories': ['暂存记忆']}})}],
                '_agent_expected_state': state_guard(final), '_agent_cancel_check': cancel_during_write}
            assert not await dao.save_galgame_data('fixture', 'char', pending, game_type=mode)
            rolled_back = await dao.load_galgame_data('fixture', 'char', game_type=mode)
            assert rolled_back['messages'] == final['messages'] and rolled_back['version'] == final['version']
        finally:
            await db.close()
    asyncio.run(run())


def test_background_memory_is_version_bound_and_idempotent(monkeypatch):
    from Backend.galgame import memory
    from Backend import utils
    from Backend.chat_modules import character
    data = {'version': 7, 'active_session_id': 'save-one', 'score': 40,
            'messages': [{'role': 'user', 'content': '约好明天再来', 'message_id': 'u1'},
                         {'role': 'assistant', 'content': '好，明天见', 'message_id': 'a1'}]}
    saved = []
    async def load(*a, **k): return deepcopy(data)
    async def summarize(*a, **k):
        return json.dumps({'memory_entry': {'turn': 1, 'player_action': '约定', 'event': '约好明天再来'}})
    async def save(u, c, state, **kwargs):
        saved.append(state)
        return False  # A reset racing with the model can reject the CAS.
    monkeypatch.setattr(utils, 'load_galgame_state_async', load)
    monkeypatch.setattr(utils, 'save_galgame_state_async', save)
    monkeypatch.setattr(character, 'load_character_from_db', lambda *a: {'name': '云杉'})
    monkeypatch.setattr(memory, '_call_summarize_llm', summarize)
    async def run():
        await memory._run_char_memory_update_locked('fixture', 'char', 'galgame')
        assert saved[0]['_agent_expected_state'] == state_guard(data)
        assert saved[0]['char_memory']['entries'][0]['source_reply_id'] == 'a1'
        data['char_memory'] = saved[0]['char_memory']
        await memory._run_char_memory_update_locked('fixture', 'char', 'galgame')
        assert len(saved) == 1
    asyncio.run(run())


def test_staged_memory_search_is_scoped_to_delivered_history():
    from Backend.galgame.agent_context import seal_notes, message_digest
    original = {'role': 'user', 'content': '请明天归还书签'}
    reply = {'scene': {'response': '好，明天归还'}, '_agent_state': {
        'sources': [{'sha256': message_digest(original)}],
        'memories': [{'text': '承诺明天归还书签', 'source_message_ids': ['$reply']}]}}
    seal_notes(reply)
    a = {'messages': [original, {'role': 'assistant', 'rawContent': json.dumps(reply)}]}
    e = GameEvidence(a, [], '')
    result = asyncio.run(e.search_memory({'query': '书签'}))
    assert result['items'][0]['source_id'] == 'history:1'
    assert result['usable_as_original_quote'] is False
    assert asyncio.run(GameEvidence({}, [], '').search_memory({'query': '书签'}))['items'] == []
    original['content'] = '已经还了书签'
    assert asyncio.run(GameEvidence(a, [], '').search_memory({'query': '书签'}))['items'] == []
    original['content'] = '请明天归还书签'
    reply['scene']['response'] = '我没有借过'
    a['messages'][1]['rawContent'] = json.dumps(reply)
    assert asyncio.run(GameEvidence(a, [], '').search_memory({'query': '书签'}))['items'] == []


@pytest.mark.parametrize('change', ['save_failure', 'stale_version', 'changed_save'])
def test_handler_does_not_deliver_or_schedule_memory_without_commit(monkeypatch, change):
    from Backend.galgame import handler
    from Backend.utils import ChatRequest, ChatMessage
    data = {'score': 40, 'version': 2, 'active_session_id': 'current', 'messages': []}
    req = ChatRequest(username='fixture', character_id='pony', mode='galgame',
                      messages=[ChatMessage(role='user', content='你好')])
    req._game_state_guard = state_guard(data)
    if change == 'stale_version': req._game_state_guard['version'] = 1
    if change == 'changed_save': req._game_state_guard['active_session_id'] = 'old'
    writes, notifications = [], []
    async def load(*a, **k): return deepcopy(data)
    async def save(*a, **k):
        writes.append(a[2])
        return False
    async def broadcast(*a, **k): notifications.append('broadcast')
    monkeypatch.setattr(handler, 'load_galgame_state_async', load)
    monkeypatch.setattr(handler, 'save_galgame_state_async', save)
    monkeypatch.setattr(handler, 'schedule_char_memory_update_after_turn', lambda **k: notifications.append('memory'))
    monkeypatch.setattr(handler.manager, 'broadcast_sync', broadcast)
    result = asyncio.run(handler._handle_galgame_response(req, json.dumps(draft()), [], x_client_id='fixture'))
    assert result['status'] == 'error' and not notifications
    assert len(writes) == (1 if change == 'save_failure' else 0)
