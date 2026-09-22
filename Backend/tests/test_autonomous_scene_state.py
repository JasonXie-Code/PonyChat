"""Scene continuity and transactional evidence tests, without starting the app."""
import asyncio
import importlib
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest
from test_unified_agent_memory import db, store, jobs

root = types.ModuleType('scene_test_backend')
root.__path__ = [str(Path(__file__).parents[1])]
sys.modules[root.__name__] = root
package = types.ModuleType('scene_test_backend.chat_modules')
package.__path__ = [str(Path(__file__).parents[1] / 'chat_modules')]
sys.modules[package.__name__] = package
scene = importlib.import_module(package.__name__ + '.autonomous_scene_state')
normal = importlib.import_module(package.__name__ + '.autonomous_normal')


def put(db, changes, *, reset=False, snapshot=None, reply_ids=()):
    s = store(db)
    jobs.configure(db, 'alice', 'twilight', True)
    snapshot = snapshot or scene.load_scene(s)
    patch = scene.validate_patch({'reset': reset, 'changes': changes}, {'m1', 'm2'})
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        scene.commit_scene(conn, s, snapshot, patch, reply_ids)
    return scene.load_scene(store(db))


def value(text, ref='m1'):
    return {'value': text, 'source_message_ids': [ref]}


def seed(db):
    return put(db, {'location': value('窗边'), 'scene_time': value('傍晚'),
                    'user_position': value('坐在椅子上'), 'character_position': value('趴在地毯上'),
                    'contact': value('没有接触'), 'item:杯子': value('用户的杯子在桌上，水未喝')})


def test_long_history_keeps_fixed_card_outside_thirty_message_window(db):
    snapshot = seed(db)
    captured = {}

    async def runner(prompt, config, tools, **kw):
        captured.update(json.loads(prompt))
        from test_autonomous_normal import model_result
        result = model_result('我还趴在窗边地毯上。')
        data = json.loads(result['final_response'])
        data['scene_patch'] = {'reset': False, 'changes': {}}
        result['final_response'] = json.dumps(data, ensure_ascii=False)
        return result

    result = asyncio.run(normal.run_autonomous_turn(
        messages=[{'role': 'user' if i % 2 == 0 else 'assistant', 'message_id': str(i),
                   'content': '谈论音乐'} for i in range(81)],
        scene_state=snapshot, character_profile='云杉', environment='', model_config={}, harness_runner=runner))
    assert len(captured['recent_raw_messages']) == 60
    assert captured['current_scene']['fields']['character_position']['value'] == '趴在地毯上'
    assert 'scene_patch' not in json.loads(result['envelope'])  # Internal state never leaks to UI.
    assert put(db, {})['fields'] == snapshot['fields']


def test_posture_contact_delta_and_saved_reply_evidence(db):
    seed(db)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO messages(id,message_id,conversation_id,role,content) VALUES('m2','m2','c1','assistant','我站起身，松开你的手。')")
    result = put(db, {'character_position': value('站在地毯上', '$reply'),
                      'contact': value(None, '$reply')}, reply_ids=['m2'])
    assert result['fields']['character_position']['source_message_ids'] == ['m2']
    assert result['fields']['contact']['value'] is None
    assert result['fields']['user_position']['value'] == '坐在椅子上'
    assert result['fields']['location']['value'] == '窗边'


def test_item_move_and_local_correction_preserve_other_fields(db):
    initial = seed(db)
    moved = put(db, {'item:杯子': value('用户的杯子移到窗台，水喝了一半')})
    corrected = put(db, {'item:杯子': value('角色的杯子在窗台，水喝了一半')})
    for key in initial['fields'].keys() - {'item:杯子'}:
        assert corrected['fields'][key] == moved['fields'][key] == initial['fields'][key]


def test_interaction_mode_persists_and_is_conversation_scoped(db):
    initial = seed(db)
    result = put(db, {'interaction_mode': value('virtual_roleplay')})
    assert result['fields']['interaction_mode']['value'] == 'virtual_roleplay'
    assert put(db, {})['fields']['interaction_mode']['value'] == 'virtual_roleplay'
    assert scene.load_scene(store(db, conversation_id='other'))['fields'] == {}
    switched = put(db, {'interaction_mode': value('instant_messaging')})
    assert switched['fields']['interaction_mode']['value'] == 'instant_messaging'
    assert switched['fields']['location'] == initial['fields']['location']
    with pytest.raises(ValueError):
        put(db, {'interaction_mode': value('romantic')})
    with pytest.raises(ValueError):
        put(db, {'interaction_mode': value({'mode': 'virtual_roleplay'})})


def test_time_and_explicit_scene_reset_clear_old_pose_and_inventory(db):
    seed(db)
    unchanged = put(db, {})
    assert unchanged['fields']['scene_time']['value'] == '傍晚'
    result = put(db, {'scene_time': value('第二天清晨'), 'location': value('车站')}, reset=True)
    assert set(result['fields']) == {'scene_time', 'location'}


def test_isolation_deletion_reset_and_atomic_rollback(db):
    initial = seed(db)
    assert scene.load_scene(store(db, conversation_id='c2'))['fields'] == {}
    assert scene.load_scene(store(db, username='bob'))['fields'] == {}
    assert scene.load_scene(store(db, character_id='pinkie'))['fields'] == {}
    with pytest.raises(RuntimeError):
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            scene.commit_scene(conn, store(db), initial,
                {'reset': False, 'changes': {'location': value('门口')}}, [])
            raise RuntimeError('delivery cancelled')
    assert scene.load_scene(store(db)) == initial
    put(db, {})
    with pytest.raises(RuntimeError, match='changed during'):
        put(db, {}, snapshot=initial)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE messages SET is_hidden=1 WHERE message_id='m1'")
    assert scene.load_scene(store(db))['fields'] == {}
    stale = store(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE agent_memory_state SET epoch=epoch+1")
    assert scene.load_scene(store(db)) == {'revision': 0, 'fields': {}}
    assert scene.load_scene(stale) == {'revision': 0, 'fields': {}}


def test_invalid_evidence_and_reply_without_delivery_rejected(db):
    seed(db)
    with pytest.raises(ValueError):
        scene.validate_patch({'reset': False, 'changes': {'location': value('外面', 'invented')}}, {'m1'})
    # 本轮没有保存任何 assistant 段落时，丢弃依赖 $reply 的字段（保留原值），
    # 不让整笔回复事务失败；同一补丁里不依赖 $reply 的字段照常提交。
    put(db, {'location': value('外面', '$reply'),
             'contact': value('牵着前蹄', 'm1')})
    fields = scene.load_scene(store(db))['fields']
    assert fields['location']['value'] == '窗边'
    assert fields['contact']['value'] == '牵着前蹄'


def test_changed_or_cross_conversation_evidence_cannot_be_reused(db):
    initial = seed(db)
    pending_store = store(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE messages SET content='用户已经离开' WHERE message_id='m1'")
    with pytest.raises(RuntimeError, match='evidence changed'):
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            scene.commit_scene(conn, pending_store, initial,
                {'reset': False, 'changes': {'location': value('窗边')}}, [])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content) VALUES('m2','m2','c2','user','我们在海边')")
    with pytest.raises(RuntimeError, match='unavailable'):
        put(db, {'location': value('海边', 'm2')})


def test_scene_contract_requires_missing_patch_repair():
    from test_autonomous_normal import model_result
    calls = []

    async def runner(prompt, config, tools, **kw):
        calls.append(json.loads(prompt))
        result = model_result('你好。')
        if len(calls) > 1:
            data = json.loads(result['final_response'])
            data['scene_patch'] = {'reset': False, 'changes': {key: value(None, 'u') for key in scene.FIELDS}}
            result['final_response'] = json.dumps(data)
        return result

    result = asyncio.run(normal.run_autonomous_turn(
        messages=[{'role': 'user', 'message_id': 'u', 'content': '你好'}],
        scene_state={'revision': 0, 'fields': {}}, character_profile='云杉', environment='',
        model_config={}, harness_runner=runner))
    assert len(calls) == 2 and result['output_format_repairs'] == 1
    assert set(result['scene_patch']['changes']) == scene.FIELDS


def test_empty_initial_card_is_rejected_before_delivery():
    with pytest.raises(ValueError, match='六个字段'):
        scene.validate_patch({'reset': False, 'changes': {}}, {'u'}, initial=True)


def test_movement_rechecks_dependent_relative_position():
    previous = {'user_position': value('坐在角色旁边')}
    patch = {'reset': False, 'changes': {'character_position': value('站到沙发前', '$reply')}}
    with pytest.raises(ValueError, match='相对位置'):
        scene.validate_patch(patch, {'m1'}, previous=previous)
    patch['changes']['user_position'] = value('仍坐在沙发上')
    assert scene.validate_patch(patch, {'m1'}, previous=previous) == patch
