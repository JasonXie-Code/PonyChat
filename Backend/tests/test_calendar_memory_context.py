"""Calendar boundaries and evidence-isolated, untruncated summary injection."""
from datetime import datetime
import sqlite3

from test_unified_agent_memory import db, store, stage, commit, jobs
from unified_memory_test.agent_memory.calendar_context import build_calendar_context, calendar_periods

NOW = datetime.fromisoformat('2026-09-06T23:00:00+08:00')


def test_calendar_boundaries():
    _, periods = calendar_periods(NOW)
    assert periods['daily'] == [f'2026-08-31', *[f'2026-09-0{i}' for i in range(1, 7)]]
    assert periods['weekly'] == ['2026-W36']
    assert periods['monthly'] == [f'2026-{i:02d}' for i in range(1, 10)]
    _, january = calendar_periods(datetime.fromisoformat('2027-01-01T00:30:00+08:00'))
    assert january['weekly'] == ['2026-W53']
    assert january['monthly'] == ['2027-01']


def test_includes_full_summaries_and_excludes_other_owners_and_stale(db):
    for category, period in [('daily', '2026-09-05'), ('weekly', '2026-W36'),
                             ('monthly', '2026-09'), ('annual', '2026')]:
        s = store(db)
        stage(s, category=category, period=period, content=category + '摘要' * 1000)
        commit(s)
    ctx = build_calendar_context(store(db), now=NOW)
    assert ctx['daily'][-2]['content'].startswith('daily')
    assert ctx['daily'][-1]['status'] == 'missing'
    assert len(ctx['annual'][0]['content']) > 1000
    assert ctx['monthly'][-1]['in_progress']
    assert ctx['annual'][0]['source_ref'].startswith('memory:')
    jobs.configure(db, 'bob', 'twilight', True)
    assert build_calendar_context(store(db, username='bob', sources=[]), now=NOW)['annual'] == []
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE messages SET is_hidden=1')
    ctx = build_calendar_context(store(db, sources=[]), now=NOW)
    assert ctx['annual'] == [] and all(x['status'] == 'missing' for x in ctx['daily'])


def test_disabled_and_reset_do_not_leak_context(db):
    s = store(db)
    jobs.configure(db, 'alice', 'twilight', False)
    assert build_calendar_context(s, now=NOW) is None
    jobs.configure(db, 'alice', 'twilight', True)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE agent_memory_state SET epoch=epoch+1 WHERE username='alice'")
    assert build_calendar_context(s, now=NOW) is None


def test_all_existing_years_are_included(db):
    for year in (2022, 2023, 2024, 2025):
        mid = f'year-{year}'
        timestamp = int(datetime.fromisoformat(f'{year}-05-01T12:00:00+08:00').timestamp()*1000)
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) VALUES(?,?,'c1','user',?,?,1)",
                         (mid, mid, f'{year}年一起看书', timestamp))
        s = store(db, sources=[mid])
        stage(s, category='annual', period=str(year), source_message_ids=[mid], content=f'{year}年度摘要')
        commit(s)
    assert [row['period'] for row in build_calendar_context(store(db), now=NOW)['annual']] == ['2022', '2023', '2024', '2025']
