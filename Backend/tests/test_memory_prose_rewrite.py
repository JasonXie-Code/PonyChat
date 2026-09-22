import json
import sqlite3

import pytest
from test_unified_agent_memory import db, store, stage, commit, WHEN, MemoryConflictError
from unified_memory_test.agent_memory import prose, rewrite, evidence
from unified_memory_test.agent_memory.schema import connect


def test_labels_removed_at_write_without_changing_scope_or_time(db):
    target = store(db)
    saved = stage(target, content='【虚拟扮演】【经历】我和Alice一起喝茶。',
                  kind='current_scene', category='current_scene')
    commit(target)
    row = store(db).list()[0]
    assert row['content'] == '我和Alice一起喝茶。'
    assert row['kind'] == 'current_scene' and row['occurred_at'] == WHEN
    assert row['source_message_ids'] == ['m1']
    assert prose.clean_memory_prose('我记得书名叫【回家】。') == '我记得书名叫【回家】。'


@pytest.mark.parametrize('text', ['【经历】我在喝茶', '2026-09-12我在喝茶', '星期六我在喝茶', 'Alice喜欢喝茶', '这段虚拟扮演中我喝茶'])
def test_generated_prose_requires_plain_first_person_without_dates(text):
    with pytest.raises(ValueError):
        prose.validate_rewritten_prose(text)


def test_regeneration_rebases_derived_evidence_and_preserves_versions(db):
    target = store(db)
    first = stage(target, content='Alice喜欢绿茶', importance=8)['entry_id']
    commit(target)
    target = store(db, sources=[f'memory:{first}:1'])
    summary = stage(target, content='当天Alice聊过绿茶', category='daily', period='2026-09-05',
                    source_message_ids=[f'memory:{first}:1'])['entry_id']
    commit(target)
    plan = rewrite.snapshot(db, 'alice', 'twilight')
    result = rewrite.apply(db, plan, {first: '我记得Alice喜欢绿茶。', summary: '我和Alice聊过绿茶。'})
    assert result['processed'] == result['rewritten'] == 2
    with connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM agent_memory_versions').fetchone()[0] == 4
        new = conn.execute('SELECT * FROM agent_memory_versions WHERE entry_id=? AND version=2', (summary,)).fetchone()
        assert json.loads(new['source_message_ids']) == [f'memory:{first}:2']
        assert new['occurred_at'] == WHEN and new['period'] == '2026-09-05'
        assert evidence.valid(conn, 'alice', 'twilight', new)
        old = conn.execute('SELECT content FROM agent_memory_versions WHERE entry_id=? AND version=1', (first,)).fetchone()
        assert old[0] == 'Alice喜欢绿茶'
    assert len(store(db).list()) == 2
    assert store(db, username='bob').list() == []


def test_concurrent_edit_aborts_regeneration(db):
    target = store(db)
    mid = stage(target)['entry_id']
    commit(target)
    plan = rewrite.snapshot(db, 'alice', 'twilight')
    target = store(db)
    stage(target, entry_id=mid, expected_version=1, content='用户改为喜欢红茶')
    commit(target)
    with pytest.raises(MemoryConflictError):
        rewrite.apply(db, plan, {mid: '我记得Alice喜欢绿茶。'})
    assert store(db).list()[0]['content'] == '用户改为喜欢红茶'


def test_stale_memories_are_not_resurrected(db):
    target = store(db)
    stage(target)
    commit(target)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE messages SET deleted_at='deleted' WHERE message_id='m1'")
    plan = rewrite.snapshot(db, 'alice', 'twilight')
    assert not plan['rows'] and len(plan['stale']) == 1
    result = rewrite.apply(db, plan, {})
    assert result['stale_preserved'] == 1 and not store(db).list()


@pytest.mark.parametrize('text', ['我记得Alice的生日是5月6日。', '我知道Alice每星期二18:30上课。', '我和Alice约好2026年10月1日见面。'])
def test_fact_dates_are_preserved(text):
    assert prose.validate_rewritten_prose(text) == text


def test_unknown_event_time_survives_commit_and_rewrite(db):
    target = store(db)
    draft = target.stage(kind='fact', content='我记得Alice以前养过猫，具体时间未知。',
        source_message_ids=['m1'], occurred_at=None)
    commit(target)
    assert store(db).list()[0]['occurred_at'] is None
    plan = rewrite.snapshot(db, 'alice', 'twilight')
    rewrite.apply(db, plan, {draft['entry_id']: '我记得Alice曾养过猫，具体时间未知。'})
    assert store(db).list()[0]['occurred_at'] is None


def test_forgetting_is_retraction_not_cancelled_plan(db):
    target = store(db)
    mid = stage(target)['entry_id']
    commit(target)
    target = store(db)
    stage(target, entry_id=mid, expected_version=1, status='retracted')
    commit(target)
    assert store(db).list() == []
    assert store(db).list(include_stale=True)[0]['status'] == 'retracted'
    with connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM agent_memory_versions WHERE entry_id=?', (mid,)).fetchone()[0] == 2
