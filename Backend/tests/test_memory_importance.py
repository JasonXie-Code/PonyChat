"""Scoring reaches both Agents, survives storage, and cannot invalidate evidence."""
import asyncio
import importlib
import json
import sqlite3

import pytest

from test_unified_agent_memory import db, store, stage, commit, WHEN, service, evidence, ReviewTools
from test_autonomous_normal import normal, model_result
from test_autonomous_prompt_skills import session
from unified_memory_test.agent_memory import rescore
from unified_memory_test.agent_memory.review import STAGE_SCHEMA


def args(**overrides):
    return {'kind': 'fact', 'category': 'preference', 'content': '用户喜欢绿茶',
            'source_message_ids': ['m1'], 'occurred_at': WHEN, 'importance': 7, **overrides}


def test_foreground_and_background_require_and_persist_scores(db):
    s = store(db)
    async def runner(_prompt, _config, tools, **kwargs):
        schema = tools['stage_memory'].parameters
        assert 'importance' in schema['required']
        for bad in [None, True, 0, 11, '7', 7.5]:
            invalid = args(importance=bad)
            if bad is None:
                invalid.pop('importance')
            with pytest.raises(normal.HarnessToolValidationError, match='importance'):
                await tools['stage_memory'].callback(invalid)
        await tools['stage_memory'].callback(args())
        return model_result('记下了。')
    asyncio.run(normal.run_autonomous_turn(messages=[{'role':'user','content':'请记住，我喜欢绿茶','message_id':'m1'}],
        character_profile='温和的成年独角兽', environment='', model_config={}, memory_store=s, harness_runner=runner))
    commit(s)
    assert service.memories(db, 'alice', 'twilight')[0]['importance'] == 7
    existing = store(db).list()[0]
    s = store(db)
    tools = ReviewTools(db, {'username':'alice','character_id':'twilight'}, s)
    assert 'importance' in STAGE_SCHEMA['required']
    with pytest.raises(ValueError, match='importance'):
        asyncio.run(tools.stage({k:v for k,v in args().items() if k != 'importance'}))
    asyncio.run(tools.stage(args(entry_id=existing['entry_id'], expected_version=1, importance=8)))
    commit(s)
    assert service.memories(db, 'alice', 'twilight')[0]['importance'] == 8


def test_opt_in_memory_manual_contains_shared_rubric():
    manual = asyncio.run(session().load({'name':'memory'}))['instructions']
    assert '不能省略或统一填5' in manual and '9至10' in manual


def test_retrieval_prioritizes_relevance_then_importance_without_reordering_ui(db):
    s = store(db)
    stage(s, content='绿茶偏好', importance=9)
    stage(s, content='绿茶临时记录', importance=3)
    stage(s, content='绿茶桂花两个词的记录', importance=4)
    commit(s)
    assert store(db).list()[0]['content'] == '绿茶桂花两个词的记录'
    result = asyncio.run(store(db).search('绿茶', limit=1))
    assert result[0]['importance'] == 9
    result = asyncio.run(store(db).search('绿茶 桂花', limit=1))
    assert result[0]['importance'] == 4
    assert asyncio.run(store(db).search('不存在')) == []


def test_high_value_old_memory_survives_candidate_cap(db):
    s = store(db); row = stage(s, content='绿茶重要偏好', importance=9); commit(s)
    with sqlite3.connect(db) as c:
        template = list(c.execute('SELECT * FROM agent_memory_versions').fetchone())
        for i in range(510):
            mid = 'low' + str(i)
            c.execute('INSERT INTO agent_memory_heads(entry_id,username,character_id,epoch,version) VALUES(?,?,?,?,?)',
                      (mid, 'alice', 'twilight', 0, 1))
            values = template.copy(); values[0] = mid; values[6] = '绿茶琐事'+str(i); values[-1] = 3
            c.execute('INSERT INTO agent_memory_versions VALUES('+','.join('?' for _ in values)+')', values)
    assert asyncio.run(store(db).search('绿茶', limit=1))[0]['entry_id'] == row['entry_id']


def score_answer(plan, value=9):
    return {'scores':[{'entry_id':r['memory']['entry_id'],'version':r['memory']['version'],
                      'importance':value,'reason':'有持续影响的明确事实'} for r in plan['candidates']]}


def test_rescore_preserves_versions_text_and_dependent_summary_and_manual_edits(db):
    s = store(db); row = stage(s); commit(s)
    ref = f"memory:{row['entry_id']}:1"
    summary = store(db, sources=[ref])
    stage(summary, category='daily', period='2026-09-05', source_message_ids=[ref], content='日摘')
    commit(summary)
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        before = c.execute('SELECT * FROM agent_memory_versions').fetchall()
        fingerprint = evidence.resolve(c, 'alice', 'twilight', ref)
    plan = rescore.collect(db, 'alice')
    result = rescore.apply(db, plan, score_answer(plan))
    assert len(result['applied']) == 1 and len(store(db).list()) == 2
    assert asyncio.run(store(db).search('绿茶'))[0]['importance'] == 9
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        assert c.execute('SELECT * FROM agent_memory_versions').fetchall() == before
        assert evidence.resolve(c, 'alice', 'twilight', ref) == fingerprint
    assert rescore.apply(db, plan, score_answer(plan))['skipped'][0]['reason'] == 'already_scored'
    item = next(r for r in service.memories(db, 'alice', 'twilight') if r['entry_id']==row['entry_id'])
    service.manual(db, 'alice', 'twilight', memory_id=item['id'], importance=4)
    assert service.memories(db, 'alice', 'twilight')[0]['importance'] == 4


def test_rescore_skips_manual_hidden_changed_and_other_owner_data(db):
    service.manual(db, 'alice', 'twilight', content='手动设置为5分', importance=5)
    s = store(db); stage(s); commit(s)
    plan = rescore.collect(db, 'alice')
    assert len(plan['candidates']) == 1
    assert any(r['reason']=='manual_score_preserved' for r in plan['skipped'])
    assert not rescore.collect(db, 'bob')['candidates']
    with sqlite3.connect(db) as c:
        c.execute('UPDATE messages SET is_hidden=1')
    result = rescore.apply(db, plan, score_answer(plan))
    assert not result['applied'] and result['skipped'][0]['reason']=='stale_evidence'


@pytest.mark.parametrize('bad',[0,11,True,'8',8.5])
def test_rescore_rejects_invalid_model_score(db,bad):
    s=store(db);stage(s);commit(s)
    plan=rescore.collect(db,'alice')
    with pytest.raises(ValueError):rescore.apply(db,plan,score_answer(plan,bad))
    assert store(db).list()[0]['importance']==5
