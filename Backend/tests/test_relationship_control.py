"""Manual relationship selection remains authoritative across Agent writes and resets."""
import asyncio
import json
import sqlite3

import pytest

from test_unified_agent_memory import db, store, commit, WHEN
from unified_memory_test.agent_memory import jobs, service
from unified_memory_test.agent_memory.relationship import DECISION_ENUMS, project, stage_agent_decision
from unified_memory_test.agent_memory.relationship_control import control, set_control
from unified_memory_test.agent_memory.store import MemoryConflictError


def decide(db, stage='familiar'):
    draft = store(db)
    result = stage_agent_decision(draft, {'relationship_stage': stage},
                                  source_message_ids=['m1'], occurred_at=WHEN)
    commit(draft)
    return result


@pytest.mark.parametrize('stage', DECISION_ENUMS['relationship_stage'])
def test_manual_selection_survives_agent_update_and_auto_restores_inference(db, stage):
    set_control(db, 'alice', 'twilight', 'manual', stage)
    result = decide(db, 'familiar')
    assert result['relationship_state']['relationship_stage'] == stage
    assert project(db, 'alice', 'twilight')['relationship_stage'] == stage
    assert project(db, 'alice', 'twilight')['relationship_mode'] == 'manual'
    assert control(db, 'alice', 'twilight')['stage'] == stage
    # A repeated/no-change tool call must also return the manual selection.
    assert decide(db)['relationship_state']['relationship_stage'] == stage
    set_control(db, 'alice', 'twilight', 'auto')
    assert project(db, 'alice', 'twilight')['relationship_stage'] == 'familiar'
    assert project(db, 'alice', 'twilight')['manual_relationship_stage'] is None
    decide(db, 'new_contact')
    assert project(db, 'alice', 'twilight')['relationship_stage'] == 'new_contact'


def test_manual_control_is_scoped_durable_and_independent_of_memory(db):
    set_control(db, 'alice', 'twilight', 'manual', 'committed_partner')
    assert project(db, 'bob', 'twilight') is None
    assert project(db, 'alice', 'pinkie') is None
    jobs.configure(db, 'alice', 'twilight', False)
    async def reset():
        import aiosqlite
        async with aiosqlite.connect(db) as conn:
            await service.reset_on_connection(conn, 'alice', 'twilight')
            await conn.commit()
    asyncio.run(reset())
    assert project(db, 'alice', 'twilight')['relationship_stage'] == 'committed_partner'
    jobs.initialize(db)
    assert control(db, 'alice', 'twilight')['stage'] == 'committed_partner'


def test_inflight_agent_cannot_override_manual_change(db):
    pending = store(db)
    stage_agent_decision(pending, {'relationship_stage': 'broken_up'},
                         source_message_ids=['m1'], occurred_at=WHEN)
    set_control(db, 'alice', 'twilight', 'manual', 'committed_partner')
    commit(pending)
    assert project(db, 'alice', 'twilight')['relationship_stage'] == 'committed_partner'
    set_control(db, 'alice', 'twilight', 'auto')
    assert project(db, 'alice', 'twilight')['relationship_stage'] == 'broken_up'


def test_manual_change_invalidates_inflight_background_review(db):
    jobs.enqueue(db, 'alice', 'twilight', immediate=True)
    job = jobs.claim(db)
    pending = store(db)
    pending.stage(kind='fact', category='episode', content='有依据的小事',
                  source_message_ids=['m1'], occurred_at=WHEN)
    set_control(db, 'alice', 'twilight', 'manual', 'committed_partner')
    with pytest.raises(MemoryConflictError):
        pending.commit(reply_succeeded=True, generation_is_current=lambda: True,
                       expected_revision=job['revision'])


def test_changed_selection_hides_old_prose_and_repeated_save_is_idempotent(db):
    from test_relationship_page_limits import page
    service.manual(db, 'alice', 'twilight', category='relationship_page', content=json.dumps(page()))
    set_control(db, 'alice', 'twilight', 'manual', 'committed_partner')
    selected = project(db, 'alice', 'twilight')
    revision = jobs.status(db, 'alice', 'twilight')['revision']
    assert selected['relationship_page'] is None
    set_control(db, 'alice', 'twilight', 'manual', 'committed_partner')
    assert jobs.status(db, 'alice', 'twilight')['revision'] == revision
    assert project(db, 'alice', 'twilight')['updated_at_ms'] == selected['updated_at_ms']
    assert json.loads(store(db).list(category='relationship_page')[0]['content']) == page()


@pytest.mark.parametrize('mode,stage', [('invalid', None), ('manual', None), ('manual', 'bad')])
def test_invalid_controls_are_not_saved(db, mode, stage):
    with pytest.raises(ValueError):
        set_control(db, 'alice', 'twilight', mode, stage)
    assert control(db, 'alice', 'twilight')['mode'] == 'auto'


def test_corrupt_old_page_cannot_hide_manual_control(db):
    from test_relationship_page_limits import page
    service.manual(db, 'alice', 'twilight', category='relationship_page', content=json.dumps(page()))
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE agent_memory_versions SET content='invalid' WHERE category='relationship_page'")
    set_control(db, 'alice', 'twilight', 'manual', 'committed_partner')
    assert project(db, 'alice', 'twilight')['relationship_stage'] == 'committed_partner'
