"""Normal-turn selection bounds, time weighting and evidence isolation."""
from datetime import datetime, timedelta
import sqlite3

from test_unified_agent_memory import db, store, stage, commit, jobs
from unified_memory_test.agent_memory.fragment_context import build_fragment_context

NOW = datetime.fromisoformat('2026-10-02T12:00:00+08:00')


def add(db, name, *, age=0, importance=5, category='fact', status='active'):
    s = store(db)
    row = stage(s, content='我记得' + name, category=category, importance=importance, status=status)
    commit(s)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE agent_memory_versions SET created_at=? WHERE entry_id=?',
                     ((NOW - timedelta(days=age)).isoformat(), row['entry_id']))
    return row['entry_id']


def test_recent_thirty_plus_ten_unique_important_with_times(db):
    old = {add(db, str(i), age=100+i, importance=8) for i in range(15)}
    recent = {add(db, '近期' + str(i), age=i, importance=10 if i == 0 else 2) for i in range(30)}
    ctx = build_fragment_context(store(db), now=NOW)
    assert {r['entry_id'] for r in ctx['recent']} == recent
    assert len(ctx['important']) == 10
    assert {r['entry_id'] for r in ctx['important']} <= old
    assert all(r['importance'] >= 8 for r in ctx['important'])
    assert all(r['created_at'] and r['occurred_at'] and r['source_ref'] for r in ctx['recent'])
    assert ctx['recent'][0]['created_at'] == NOW.isoformat()


def test_age_and_importance_both_affect_extra_order(db):
    fresh8 = add(db, '较新八分', age=35, importance=8)
    fresh10 = add(db, '较新十分', age=35, importance=10)
    old10 = add(db, '很旧十分', age=400, importance=10)
    add(db, '七分不入额外', age=31, importance=7)
    for i in range(30):
        add(db, '近期' + str(i), age=i)
    rows = build_fragment_context(store(db), now=NOW)['important']
    assert [r['entry_id'] for r in rows] == [fresh10, fresh8, old10]


def test_all_fragments_not_only_first_five_hundred(db):
    s = store(db)
    first = stage(s, content='我记得很早的重要约定', importance=10)
    commit(s)
    # Copy valid evidence to create a large history without model/service startup.
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE agent_memory_versions SET created_at=?', ((NOW-timedelta(days=600)).isoformat(),))
        for i in range(510):
            mid = f'bulk-{i}'
            conn.execute("INSERT INTO agent_memory_heads(entry_id,username,character_id,epoch,version) VALUES(?,'alice','twilight',0,1)", (mid,))
            conn.execute('''INSERT INTO agent_memory_versions SELECT ?,1,kind,category,status,certainty,content,
                source_message_ids,evidence_json,occurred_at,?,origin_conversation_id,scope_conversation_id,
                period,period_hash,2 FROM agent_memory_versions WHERE entry_id=?''',
                (mid, (NOW-timedelta(hours=i)).isoformat(), first['entry_id']))
    assert [r['entry_id'] for r in build_fragment_context(store(db), now=NOW)['important']] == [first['entry_id']]


def test_scope_validity_effective_score_and_unknown_event_time(db):
    target = add(db, '八分候选', age=100, importance=7)
    add(db, '撤回', status='retracted', importance=10)
    s = store(db)
    stage(s, kind='current_scene', content='我在门口')
    commit(s)
    for i in range(30):
        add(db, '近期' + str(i), age=i)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO agent_memory_importance_reviews VALUES(?,1,8,'review','test','digest',?)", (target, NOW.isoformat()))
        conn.execute("UPDATE agent_memory_versions SET occurred_at='' WHERE entry_id=?", (target,))
    ctx = build_fragment_context(store(db, conversation_id='c2'), now=NOW)
    assert ctx['important'][0]['importance'] == 8
    assert ctx['important'][0]['occurred_at'] is None
    jobs.configure(db, 'bob', 'twilight', True)
    assert build_fragment_context(store(db, username='bob', sources=[]), now=NOW)['recent'] == []
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE messages SET is_hidden=1')
    ctx = build_fragment_context(store(db), now=NOW)
    assert ctx['recent'] == ctx['important'] == []


def test_disabled_and_reset(db):
    s = store(db)
    jobs.configure(db, 'alice', 'twilight', False)
    assert build_fragment_context(s, now=NOW) is None
    jobs.configure(db, 'alice', 'twilight', True)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE agent_memory_state SET epoch=epoch+1 WHERE username='alice'")
    assert build_fragment_context(s, now=NOW) is None


def test_fragments_reach_normal_prompt_and_survive_degraded_delivery(db):
    from test_autonomous_normal import normal, run, model_result

    add(db, '用户喜欢绿茶')
    fragments = build_fragment_context(store(db), now=NOW)
    observed = []

    async def runner(prompt, config, tools, **options):
        import json
        data = json.loads(prompt)
        observed.append(data['memory_fragments'])
        assert normal._degraded_prompt_data(data)['memory_fragments'] == fragments
        return model_result()

    run(normal.run_autonomous_turn(
        messages=[{'role': 'user', 'content': '你好', 'message_id': 'u1'}],
        character_profile='温和', environment='', model_config={},
        memory_fragments=fragments, harness_runner=runner))
    assert observed == [fragments]
