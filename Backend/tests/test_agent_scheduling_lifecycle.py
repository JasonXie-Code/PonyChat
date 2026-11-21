"""Isolated SQLite acceptance of both task entry points and delivery rules."""
import asyncio
import importlib
import json
import sqlite3
import time
from types import SimpleNamespace

import aiosqlite
import pytest
from fastapi.responses import JSONResponse

from Backend.chat_modules.autonomous_business import BusinessTools
from Backend.chat_modules.autonomous_transaction import install_memory_transaction
from Backend.chat_modules.normal_lifecycle import assert_normal_reply_allowed_on_connection
from Backend.proactive_settings import ProactiveSettings
from test_autonomous_upgrade_integration import database, request, save

routes = importlib.import_module('Backend.routes.proactive_tasks')
proactive_tasks = importlib.import_module('Backend.proactive_tasks')
scheduled_followup = importlib.import_module('Backend.scheduled_followup')


@pytest.fixture
def isolated_scheduler(database, monkeypatch):
    from Backend.chat_modules import normal_lifecycle
    for module in (proactive_tasks, scheduled_followup, routes, normal_lifecycle):
        monkeypatch.setattr(module, 'get_database', lambda: database)
    monkeypatch.setattr(proactive_tasks, 'is_shutdown_requested', lambda: False)
    monkeypatch.setattr(scheduled_followup, 'is_shutdown_requested', lambda: False)

    async def auth(_token):
        return 'alice'

    async def settings(_username):
        return ProactiveSettings()

    monkeypatch.setattr(routes, '_auth_username', auth)
    monkeypatch.setattr(proactive_tasks, 'load_proactive_settings', settings)
    monkeypatch.setattr(scheduled_followup, 'load_proactive_settings', settings)
    monkeypatch.setattr(scheduled_followup.model_manager, 'get_model_for_task', lambda *a: {'model_name': 'fake-agent'})
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) "
                     "VALUES('a0','a0','c1','assistant','我会按约定提醒你',2000,2)")
    return database


def set_dead(db, character='twilight', conversation='c1'):
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("INSERT INTO normal_character_lifecycle(username,character_id,conversation_id,state,created_at_ms,updated_at_ms) "
                     "VALUES('alice',?,?,'dead',1,1)", (character, conversation))


def create_task(db, entry='manual', schedule_type='once'):
    if entry == 'manual':
        body = routes.ProactiveTaskBody(character_id='twilight', conversation_id='c1', title='喝水提醒',
            task_type='reminder', prompt='提醒喝水', due_at_ms=int(time.time()*1000)-1000,
            schedule_type=schedule_type, interval_seconds=120)
        result = asyncio.run(routes.create_task(body, 'isolated'))
        task_id = result['id']
    else:
        req = request()
        b = BusinessTools(req, [{'role': 'user', 'content': '两分钟后提醒我喝水', 'message_id': 'm1'}],
            SimpleNamespace(guidance='', description=False, story=False), ProactiveSettings(), [])
        staged = asyncio.run(b.schedule(dict(kind='agreed', source_message_id='m1', summary='喝水',
            target_delay_seconds=120, schedule_type=schedule_type, interval_seconds=120)))
        install_memory_transaction(req, None, b)
        assert asyncio.run(save(db, req))
        task_id = staged['id']
        with sqlite3.connect(db.db_path) as conn:
            conn.execute('UPDATE proactive_tasks SET due_at_ms=? WHERE id=?', (int(time.time()*1000)-1000, task_id))
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute('SELECT * FROM proactive_tasks WHERE id=?', (task_id,)).fetchone())


def install_fake_agent(db, monkeypatch, calls, during_generation=None):
    service = importlib.import_module('Backend.chat_modules.service')

    async def handle(req, *_args, **_kwargs):
        calls.append(req)
        assert req._normal_internal_proactive_trigger
        assert (getattr(req, '_normal_internal_proactive_task_id', '')
                or getattr(req, '_normal_internal_followup_task_id', ''))
        if during_generation:
            await during_generation(req)
        install_memory_transaction(req, None)
        req._autonomous_pending_reply_message_ids = ('due',)
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) "
                "VALUES('due','due',?,'assistant','该喝水了',?,10)", (req.conversation_id, int(time.time()*1000)))
            await req._autonomous_before_reply_commit(conn)
            await conn.commit()
        return JSONResponse({'events': [{'type': 'assistant_paragraph', 'id': 'due', 'content': '该喝水了'},
            {'type': 'save_status', 'success': True, 'assistant_message_ids': ['due']}]})

    async def audit(*args):
        pass

    monkeypatch.setattr(service, 'handle_chat_request', handle)
    monkeypatch.setattr(scheduled_followup, '_record_proactive_audit_only', audit)


@pytest.mark.parametrize('entry', ['manual', 'agent'])
@pytest.mark.parametrize('schedule_type', ['once', 'interval'])
def test_both_task_entries_deliver_and_record_once(isolated_scheduler, monkeypatch, entry, schedule_type):
    db = isolated_scheduler
    row = create_task(db, entry, schedule_type)
    calls = []
    install_fake_agent(db, monkeypatch, calls)
    assert asyncio.run(proactive_tasks.process_due_proactive_tasks()) == 1
    assert len(calls) == 1
    assert asyncio.run(proactive_tasks.process_due_proactive_tasks()) == 0
    with sqlite3.connect(db.db_path) as conn:
        status, count, metadata = conn.execute('SELECT status,run_count,metadata_json FROM proactive_tasks WHERE id=?', (row['id'],)).fetchone()
        assert status == ('completed' if schedule_type == 'once' else 'active')
        assert count == 1 and json.loads(metadata)['last_message_id'] == 'due'
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE message_id='due'").fetchone()[0] == 1


@pytest.mark.parametrize('change', ['cancel', 'pause', 'death'])
def test_task_changes_during_agent_generation_prevent_reply_commit(isolated_scheduler, monkeypatch, change):
    db, calls = isolated_scheduler, []
    row = create_task(db)

    async def mutate(req):
        if change == 'death':
            set_dead(db)
        elif change == 'cancel':
            await routes.delete_task(row['id'], 'isolated')
        else:
            body = routes.ProactiveTaskBody(character_id='twilight', conversation_id='c1', enabled=False)
            await routes.update_task(row['id'], body, 'isolated')

    install_fake_agent(db, monkeypatch, calls, mutate)
    assert asyncio.run(proactive_tasks.process_due_proactive_tasks()) == 1
    assert len(calls) == 1
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE message_id='due'").fetchone()[0] == 0
        status, count = conn.execute('SELECT status,run_count FROM proactive_tasks WHERE id=?', (row['id'],)).fetchone()
        assert status == {'cancel': 'cancelled', 'pause': 'paused', 'death': 'skipped'}[change]
        assert count == 0


def test_dead_task_is_stopped_before_agent(isolated_scheduler, monkeypatch):
    db, calls = isolated_scheduler, []
    row = create_task(db)
    set_dead(db)
    install_fake_agent(db, monkeypatch, calls)
    assert asyncio.run(proactive_tasks.process_due_proactive_tasks()) == 1
    assert calls == []
    with sqlite3.connect(db.db_path) as conn:
        status, metadata = conn.execute('SELECT status,metadata_json FROM proactive_tasks WHERE id=?', (row['id'],)).fetchone()
        assert status == 'skipped' and json.loads(metadata)['last_reason'] == 'character_already_dead'


def test_goodnight_does_not_cancel_an_agreed_reminder(isolated_scheduler):
    db = isolated_scheduler
    row = create_task(db, 'agent')
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE messages SET content='晚安，两分钟后记得提醒我喝水' WHERE message_id='m1'")
    task = asyncio.run(proactive_tasks._build_scheduled_compatible_task(row))
    assert asyncio.run(scheduled_followup._validate_task_still_sendable(task))['ok']


@pytest.mark.parametrize('kind', ['ordinary', 'automatic', 'proactive', 'explicit_at', 'other_conversation', 'other_character'])
def test_death_rule_is_transactional_and_at_does_not_resurrect(isolated_scheduler, kind):
    db, req = isolated_scheduler, request()
    set_dead(db)
    if kind == 'explicit_at':
        req.reply_character_id = 'twilight'
    if kind == 'automatic':
        req.reply_character_id = 'twilight'
        req._normal_auto_handoff = True
    if kind == 'proactive':
        req.reply_character_id = 'twilight'
        req._normal_internal_proactive_trigger = True
    if kind == 'other_conversation':
        req.conversation_id = 'c2'
    if kind == 'other_character':
        req.character_id = 'pinkie'
    with sqlite3.connect(db.db_path) as conn:
        if kind in ('ordinary', 'automatic', 'proactive'):
            with pytest.raises(RuntimeError, match='dead'):
                assert_normal_reply_allowed_on_connection(conn, req)
        else:
            assert_normal_reply_allowed_on_connection(conn, req)
        assert conn.execute("SELECT state FROM normal_character_lifecycle WHERE character_id='twilight' AND conversation_id='c1'").fetchone()[0] == 'dead'


def test_death_during_normal_generation_rolls_back_reply(isolated_scheduler):
    db, req = isolated_scheduler, request()
    install_memory_transaction(req, None)
    set_dead(db)
    assert not asyncio.run(save(db, req))
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE message_id='a1'").fetchone()[0] == 0


@pytest.mark.parametrize('change', ['none', 'death_before', 'death_during', 'cancel', 'expire', 'user_reply'])
def test_short_followup_due_delivery_and_cancellation(isolated_scheduler, monkeypatch, change):
    from test_agent_parity import business, decision

    db = isolated_scheduler
    b = business()
    b.finalize_delivery(decision())
    install_memory_transaction(b.request, None, b)
    assert asyncio.run(save(db, b.request))
    with sqlite3.connect(db.db_path) as conn:
        task_id = conn.execute('SELECT id FROM scheduled_followups').fetchone()[0]
        conn.execute('UPDATE scheduled_followups SET due_at_ms=?', (int(time.time()*1000)-1000,))
    if change == 'death_before':
        set_dead(db)
    calls = []

    async def mutate(req):
        if change == 'death_during':
            set_dead(db)
        elif change in ('cancel', 'expire', 'user_reply'):
            with sqlite3.connect(db.db_path) as conn:
                if change == 'cancel':
                    conn.execute("UPDATE scheduled_followups SET status='cancelled' WHERE id=?", (task_id,))
                if change == 'expire':
                    conn.execute('UPDATE scheduled_followups SET expires_at_ms=1 WHERE id=?', (task_id,))
                if change == 'user_reply':
                    conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) "
                        "VALUES('u2','u2','c1','user','我回来了',3000,3)")

    install_fake_agent(db, monkeypatch, calls, mutate)
    assert asyncio.run(scheduled_followup.process_due_followups()) == 1
    assert len(calls) == int(change != 'death_before')
    if calls:
        trigger = calls[0].messages[-1].content
        assert 'Agent追发原文与时间事实' in trigger and 'assistant_bubbles' in trigger
        assert 'expression_motif_policy' not in trigger and 'subject_integrity' not in trigger
    with sqlite3.connect(db.db_path) as conn:
        status, sent = conn.execute('SELECT status,sent_message_id FROM scheduled_followups WHERE id=?', (task_id,)).fetchone()
        assert status == ('sent' if change == 'none' else 'cancelled')
        assert (sent == 'due') == (change == 'none')
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE message_id='due'").fetchone()[0] == int(change == 'none')


def test_dead_long_absence_and_legacy_append_are_blocked(isolated_scheduler, monkeypatch):
    long_proactive = importlib.import_module('Backend.long_proactive')
    db = isolated_scheduler
    monkeypatch.setattr(long_proactive, 'get_database', lambda: db)
    monkeypatch.setattr(long_proactive, '_is_quiet_hour', lambda ts: False)
    set_dead(db)
    task = dict(id='isolated', username='alice', character_id='twilight', conversation_id='c1')
    assert asyncio.run(long_proactive._validate_attempt_sendable(task)) == {
        'ok': False, 'reason': 'character_already_dead'}
    assert asyncio.run(long_proactive._append_long_proactive_message(task, '不应发出的文本')) == []
    assert asyncio.run(scheduled_followup._append_assistant_message(task, '不应发出的文本')) == []


@pytest.mark.parametrize('change', ['reschedule', 'content'])
def test_edit_after_batch_selection_invalidates_old_task_snapshot(isolated_scheduler, monkeypatch, change):
    db, calls = isolated_scheduler, []
    old = create_task(db)
    # Even a same-millisecond edit must invalidate an already selected row.
    monkeypatch.setattr(routes, '_now_ms', lambda: old['updated_at_ms'])
    body = routes.ProactiveTaskBody(character_id='twilight', conversation_id='c1', prompt='新的提醒内容',
        due_at_ms=int(time.time()*1000)+120000 if change == 'reschedule' else old['due_at_ms'])
    assert asyncio.run(routes.update_task(old['id'], body, 'isolated')) == {'status': 'ok'}
    install_fake_agent(db, monkeypatch, calls)
    assert asyncio.run(proactive_tasks._process_one_task(old)) is False
    assert calls == []
    with sqlite3.connect(db.db_path) as conn:
        status, updated, prompt = conn.execute('SELECT status,updated_at_ms,prompt FROM proactive_tasks WHERE id=?', (old['id'],)).fetchone()
        assert status == 'active' and updated > old['updated_at_ms'] and prompt == '新的提醒内容'


@pytest.mark.parametrize('kind', ['agreed', 'followup'])
def test_silent_agent_never_claims_an_old_assistant_reply_as_task_delivery(isolated_scheduler, monkeypatch, kind):
    from test_agent_parity import business, decision

    db = isolated_scheduler
    if kind == 'agreed':
        row = create_task(db)
        task_id, table = row['id'], 'proactive_tasks'
    else:
        b = business()
        b.finalize_delivery(decision())
        install_memory_transaction(b.request, None, b)
        assert asyncio.run(save(db, b.request))
        with sqlite3.connect(db.db_path) as conn:
            task_id = conn.execute('SELECT id FROM scheduled_followups').fetchone()[0]
            conn.execute('UPDATE scheduled_followups SET due_at_ms=?', (int(time.time()*1000)-1000,))
        table = 'scheduled_followups'
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) "
            "VALUES('other','other','c1','assistant','来源消息之后已经发生的另一轮聊天',4000,4)")
    calls = []
    install_fake_agent(db, monkeypatch, calls)
    service = importlib.import_module('Backend.chat_modules.service')

    async def silent(req, *_args, **_kwargs):
        calls.append(req)
        req._autonomous_pending_reply_message_ids = ()
        install_memory_transaction(req, None)
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute('BEGIN IMMEDIATE')
            await req._autonomous_before_reply_commit(conn)
            await conn.commit()
        return JSONResponse({'events': [{'type': 'no_reply', 'reason': 'agent_chose_silence'},
                                        {'type': 'save_status', 'success': True}]})

    monkeypatch.setattr(service, 'handle_chat_request', silent)
    processor = proactive_tasks.process_due_proactive_tasks if kind == 'agreed' else scheduled_followup.process_due_followups
    assert asyncio.run(processor()) == 1 and len(calls) == 1
    with sqlite3.connect(db.db_path) as conn:
        if kind == 'agreed':
            status, count, metadata = conn.execute('SELECT status,run_count,metadata_json FROM proactive_tasks WHERE id=?', (task_id,)).fetchone()
            assert status == 'skipped' and count == 0 and 'last_message_id' not in json.loads(metadata)
        else:
            assert conn.execute('SELECT status,sent_message_id FROM scheduled_followups WHERE id=?', (task_id,)).fetchone() == ('cancelled', None)


@pytest.mark.parametrize('history', ['empty', 'user_only', 'no_conversation'])
def test_manual_task_without_assistant_history_uses_one_normal_conversation(isolated_scheduler, monkeypatch, history):
    from Backend.db.conversations_dao import ConversationsDAO

    db, calls = isolated_scheduler, []
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("DELETE FROM messages WHERE role='assistant'")
        if history != 'user_only':
            conn.execute('DELETE FROM messages')
        if history == 'no_conversation':
            conn.execute('DELETE FROM conversations')
    body = routes.ProactiveTaskBody(character_id='twilight', title='手动提醒', prompt='提醒喝水',
        due_at_ms=int(time.time()*1000)-1000)
    created = asyncio.run(routes.create_task(body, 'isolated'))
    assert created['status'] == 'ok'
    with sqlite3.connect(db.db_path) as conn:
        conversation = conn.execute('SELECT conversation_id FROM proactive_tasks WHERE id=?', (created['id'],)).fetchone()[0]
    expected = ConversationsDAO(db)._stable_normal_conversation_id(1, 'twilight') if history == 'no_conversation' else 'c1'
    assert conversation == expected
    # A second explicit reminder reuses the same container.
    body.due_at_ms = int(time.time()*1000)+3600000
    assert asyncio.run(routes.create_task(body, 'isolated'))['status'] == 'ok'
    install_fake_agent(db, monkeypatch, calls)
    assert asyncio.run(proactive_tasks.process_due_proactive_tasks()) == 1
    assert len(calls) == 1
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM conversations WHERE character_id=?', ('twilight',)).fetchone()[0] == 1
        assert conn.execute("SELECT conversation_id FROM messages WHERE message_id='due'").fetchone()[0] == expected


@pytest.mark.parametrize('reset', ['hidden', 'deleted'])
def test_bound_task_does_not_recreate_reset_conversation(isolated_scheduler, monkeypatch, reset):
    db, calls = isolated_scheduler, []
    create_task(db)
    with sqlite3.connect(db.db_path) as conn:
        if reset == 'hidden':
            conn.execute("UPDATE conversations SET is_hidden=1 WHERE id='c1'")
        else:
            conn.execute("DELETE FROM messages WHERE conversation_id='c1'")
            conn.execute("DELETE FROM conversations WHERE id='c1'")
    install_fake_agent(db, monkeypatch, calls)
    assert asyncio.run(proactive_tasks.process_due_proactive_tasks()) == 1
    assert calls == []
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM conversations WHERE COALESCE(is_hidden,0)=0').fetchone()[0] == 0


@pytest.mark.parametrize('target', ['unknown_character', 'foreign_character', 'foreign_conversation'])
def test_manual_task_cannot_create_or_bind_an_unowned_character(isolated_scheduler, target):
    db = isolated_scheduler
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("INSERT INTO users(id,username,password) VALUES(2,'bob','test')")
        conn.execute("INSERT INTO characters(id,user_id,name) VALUES('foreign',2,'他人的角色')")
        conn.execute("INSERT INTO conversations(id,user_id,character_id,title,timestamp) VALUES('foreign_conv',2,'foreign','other',1)")
    body = routes.ProactiveTaskBody(character_id={'unknown_character':'missing', 'foreign_character':'foreign',
        'foreign_conversation':'twilight'}[target], conversation_id='foreign_conv' if target == 'foreign_conversation' else '')
    response = asyncio.run(routes.create_task(body, 'isolated'))
    assert response.status_code == 404
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM proactive_tasks').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM conversations').fetchone()[0] == 2


@pytest.mark.parametrize('dead', [False, True])
def test_runtime_receipt_uses_new_messages_and_the_actual_canonical_conversation(isolated_scheduler, monkeypatch, dead):
    from Backend.chat_modules import runtime
    long_proactive = importlib.import_module('Backend.long_proactive')
    db, req = isolated_scheduler, request()
    monkeypatch.setattr(runtime, 'get_database', lambda: db)

    async def no_presence(*args, **kwargs):
        pass

    monkeypatch.setattr(long_proactive, 'record_presence_from_saved_messages', no_presence)
    req.conversation_id = 'stale_client_conversation'
    req._normal_skip_persistence_galgame_lock = True
    req._normal_persist_append_only = True
    req._defer_chat_complete_until_voice_ready = True
    from Backend.chat_modules.normal_delivery import NormalDeliverySession, pending_message_ids
    req._normal_delivery_session = NormalDeliverySession()
    if dead:
        set_dead(db)
    else:
        row = create_task(db)
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE proactive_tasks SET status='processing' WHERE id=?", (row['id'],))
        req._normal_internal_proactive_trigger = True
        req._normal_internal_proactive_task_id = row['id']
        req._normal_internal_proactive_source_message_id = 'a0'
    install_memory_transaction(req, None)
    succeeded, _, ids = asyncio.run(runtime.run_conversation_persistence(req, 'isolated', '现在到了约定时间，请喝一杯水。'))
    assert req.conversation_id == 'c1'
    assert succeeded is not dead
    pending = pending_message_ids(req.username, req.character_id, 'c1')
    assert pending == (set(ids or []) if not dead else set())
    assert not pending_message_ids(req.username, req.character_id, 'stale_client_conversation')
    asyncio.run(req._normal_delivery_session.finish())
    with sqlite3.connect(db.db_path) as conn:
        if dead:
            assert conn.execute("SELECT COUNT(*) FROM messages WHERE role='assistant'").fetchone()[0] == 1
        else:
            assert ids and tuple(ids) == req._autonomous_pending_reply_message_ids
            metadata = json.loads(conn.execute('SELECT metadata_json FROM proactive_tasks WHERE id=?', (row['id'],)).fetchone()[0])
            assert metadata['last_message_id'] in ids and metadata['last_message_id'] != 'a0'


def test_detail_delivery_view_serializes_cancel_while_agent_reads_full_history(isolated_scheduler, monkeypatch):
    from Backend.chat_modules.normal_delivery import NormalDeliverySession, pending_message_ids
    import Backend.db.conversations_dao as conversations
    db, req = isolated_scheduler, request()
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("INSERT INTO messages(conversation_id,role,content,timestamp,message_id,sequence_number) "
                     "VALUES('c1','assistant','待发送',3,'tail',3)")
    async def case():
        session = NormalDeliverySession()
        session.register(req, ['tail'], db.db_path)
        dao = conversations.ConversationsDAO(db)
        full = await dao.load_conversations(req.username, req.character_id)
        assert 'tail' in {m['message_id'] for conv in full for m in conv['messages']}
        original = conversations.load_attachments_for_messages
        cleanup = None
        blocked = []
        async def concurrent_cancel(*args, **kwargs):
            nonlocal cleanup
            session.cancelled = True
            cleanup = asyncio.create_task(session.finish())
            await asyncio.sleep(0.08)
            blocked.append(not cleanup.done())
            return await original(*args, **kwargs)
        monkeypatch.setattr(conversations, 'load_attachments_for_messages', concurrent_cancel)
        visible = await dao.load_conversations(req.username, req.character_id, visible_delivery_only=True)
        await cleanup
        assert blocked == [True]
        assert 'tail' not in {m['message_id'] for conv in visible for m in conv['messages']}
        assert not pending_message_ids(req.username, req.character_id, 'c1')
    asyncio.run(case())
