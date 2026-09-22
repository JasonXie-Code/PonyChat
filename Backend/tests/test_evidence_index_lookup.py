"""Indexed evidence resolution preserves legacy IDs and authorization filters."""
import sqlite3

import pytest
from test_unified_agent_memory import db, evidence


@pytest.mark.parametrize('message_id', [None, '', 'public-id'])
def test_lookup_preserves_legacy_id_precedence_and_visibility(db, message_id):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        c.execute("UPDATE messages SET id='internal-id',message_id=?", (message_id,))
        ref = message_id or 'internal-id'
        assert evidence.resolve(c, 'alice', 'twilight', ref)
        assert evidence.resolve(c, 'bob', 'twilight', ref) is None
        assert evidence.resolve(c, 'alice', 'pinkie', ref) is None
        if message_id:
            assert evidence.resolve(c, 'alice', 'twilight', 'internal-id') is None
        c.execute('UPDATE messages SET is_hidden=1')
        assert evidence.resolve(c, 'alice', 'twilight', ref) is None


def test_missing_reference_uses_bounded_index_work(db):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        c.executescript('CREATE INDEX msg_public ON messages(message_id); CREATE INDEX msg_internal ON messages(id);')
        c.executemany("INSERT INTO messages(id,message_id,conversation_id,role,content) VALUES(?,?,'c1','user','test')",
                      [(f'id-{i}', f'pub-{i}') for i in range(10000)])
        def work(sql):
            steps = 0
            def tick():
                nonlocal steps
                steps += 1
                return 0
            c.set_progress_handler(tick, 100)
            try:
                assert c.execute(sql, ('alice','twilight','missing')).fetchall() == []
            finally:
                c.set_progress_handler(None, 0)
            return steps
        old = work(evidence.RAW_SELECT + " AND COALESCE(NULLIF(m.message_id,''),m.id)=?3")
        new = work(evidence.RAW_SELECT + evidence.RAW_REF_FILTER)
        assert old > 100 and new < old / 10
