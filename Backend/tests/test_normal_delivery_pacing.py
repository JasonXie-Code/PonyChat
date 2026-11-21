"""Synthetic Agent output, real delivery code, clocks and isolated SQLite."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import pytest

from Backend.chat_modules.normal_delivery import (
    DeliveryCancelled, NormalDeliverySession, pending_message_ids,
)
from Backend.utils import ChatMessage, ChatRequest


@pytest.fixture
def delivery_db(tmp_path):
    path = tmp_path / 'delivery.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
            CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT);
            INSERT INTO users VALUES(1,'pacing-test');
            CREATE TABLE conversations(id TEXT PRIMARY KEY,user_id INTEGER,character_id TEXT,
                timestamp INTEGER DEFAULT 1,is_hidden INTEGER DEFAULT 0,version INTEGER DEFAULT 1);
            INSERT INTO conversations(id,user_id,character_id) VALUES('conv',1,'main');
            CREATE TABLE normal_character_lifecycle(username TEXT,character_id TEXT,conversation_id TEXT,
                state TEXT,death_message_id TEXT);
            CREATE TABLE messages(id INTEGER PRIMARY KEY,conversation_id TEXT,role TEXT DEFAULT 'assistant',
                content TEXT DEFAULT '',image_url TEXT,timestamp INTEGER DEFAULT 1,message_id TEXT,
                sequence_number INTEGER,quoted_message_json TEXT,speaker_character_id TEXT,speaker_name TEXT,
                speaker_avatar TEXT,is_hidden INTEGER DEFAULT 0,deleted_at INTEGER,hidden_reason TEXT,
                raw_content TEXT,previous_message_id TEXT,suggestions TEXT,suggestions_status TEXT,
                client_id TEXT,think_translations TEXT);
            CREATE TABLE message_attachments(conversation_id TEXT,message_id TEXT,asset_id TEXT,user_sticker_id TEXT,
                name TEXT,metadata_json TEXT);
            CREATE TABLE media_assets(id TEXT,name TEXT,intro TEXT,detail TEXT,image_text TEXT,custom_tags TEXT);
            CREATE TABLE user_sticker_assets(id TEXT,name TEXT,intro TEXT,detail TEXT,image_text TEXT,custom_tags TEXT);
            CREATE TABLE message_voice_states(conversation_id TEXT,message_id TEXT,tts_text TEXT,transcript TEXT,
                text_fragments_json TEXT);
        ''')
    return path


def add_messages(path, ids):
    with sqlite3.connect(path) as conn:
        start = conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
        for offset, mid in enumerate(ids):
            conn.execute('INSERT INTO messages(conversation_id,message_id,sequence_number,content) VALUES(?,?,?,?)',
                         ('conv', mid, start + offset + 1, mid))


def request():
    return ChatRequest(username='pacing-test', character_id='main', conversation_id='conv', mode='normal',
                       messages=[ChatMessage(role='user', content='测试', message_id='u1')],
                       crisis_hotline_enabled=False)


def record_artifact(name, value):
    directory = os.environ.get('PONYCHAT_PACING_ARTIFACT_DIR')
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        (path / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


@pytest.fixture
def notification_log(monkeypatch):
    import Backend.delivery_outbox as outbox
    log = []
    async def notify(**payload):
        log.append({'mid': payload['message_id'], 'monotonic': time.monotonic(),
                    'pending_ids': sorted(pending_message_ids('pacing-test', 'main', 'conv'))})
    monkeypatch.setattr(outbox, 'enqueue_chat_complete', notify)
    return log


def synthetic_delivery(monkeypatch, path):
    import Backend.chat_modules.normal_nonstream as normal
    import Backend.chat_modules.voice_messages as voice
    current = [True]
    async def immediate_stage(awaitable, stage, is_current, error_type, **kwargs):
        result = await awaitable
        if not is_current():
            raise error_type(stage)
        return result
    # Stage-logging polls at 200 ms. Remove that unrelated scheduler latency;
    # delivery asyncio.sleep and all wall/monotonic clocks remain real.
    monkeypatch.setattr(normal, 'await_logged_normal_stage', immediate_stage)
    monkeypatch.setattr(normal, 'is_generation_current', lambda *args: current[0])
    monkeypatch.setattr(normal.random, 'uniform', lambda *args: 0)
    async def no_voice(**kwargs):
        return {}
    monkeypatch.setattr(voice, 'prepare_voice_generation_for_message', no_voice)
    monkeypatch.setattr(voice, 'prepare_voice_generation_for_messages', no_voice)

    async def persist(req, *args, **kwargs):
        # Persistence is isolated; generation and delivery remain real code.
        add_messages(path, ['a1', 'a2', 'a3'])
        req._assistant_message_meta = [dict(message_id=f'a{i}', sequence_number=i) for i in range(1, 4)]
        req._normal_delivery_session.register(req, ['a1', 'a2', 'a3'], path)
        req._deferred_chat_complete_payloads = [dict(username=req.username, character_id=req.character_id,
            conversation_id='conv', message_id=f'a{i}', preview='测试', mode='normal', completed_at_ms=1)
            for i in range(1, 4)]
        return True, 'saved', ['a1', 'a2', 'a3']
    monkeypatch.setattr(normal, 'run_conversation_persistence', persist)
    req = request()
    req._autonomous_harness = True
    req._autonomous_usage_accounted = True
    req._normal_planner_result = {'bubble_count': 3, 'voice_reply': {'enabled': False}}
    req._autonomous_llm_response = SimpleNamespace(text=json.dumps({'bubbles': [
        {'parts': [{'kind': 'speech', 'text': text}]} for text in ('甲', '乙', '丙')]}))

    async def run(*, use_json=False, internal=False):
        req._normal_internal_proactive_trigger = internal
        return await normal.handle_normal_nonstream_sse(request=req, model_name='synthetic', payload={},
            api_url='', headers={}, provider=None, httpx_client=None, messages=[], request_tokens=0,
            username=req.username, character_id=req.character_id, client_id='pacing-test',
            effective_username=req.username, release_lock=lambda: asyncio.sleep(0), use_json=use_json)
    return req, current, run


@pytest.mark.parametrize('internal_json', [False, True])
def test_actual_sse_and_internal_json_release_intervals(monkeypatch, delivery_db, notification_log, internal_json):
    req, current, run = synthetic_delivery(monkeypatch, delivery_db)
    async def case():
        started = time.monotonic()
        response = await run(use_json=internal_json, internal=internal_json)
        arrivals = []
        if internal_json:
            events = json.loads(response.body)['events']
        else:
            events = []
            async for packet in response.body_iterator:
                for line in packet.strip().splitlines():
                    if line.startswith('data: ') and line[6:] != '[DONE]':
                        event = json.loads(line[6:])
                        events.append(event)
                        if event.get('type') == 'assistant_paragraph':
                            arrivals.append(dict(mid=event['id'], monotonic=time.monotonic()))
        paragraphs = [event for event in events if event.get('type') == 'assistant_paragraph']
        assert len(paragraphs) == 3, events
        assert all(event.get('delivery_paced') is True for event in paragraphs)
        assert all(event['server_now_ms'] >= event['display_at_server_ms'] for event in paragraphs)
        assert [entry['mid'] for entry in notification_log] == ['a1', 'a2', 'a3']
        gaps = [notification_log[i]['monotonic'] - notification_log[i-1]['monotonic'] for i in (1, 2)]
        assert all(gap >= 0.29 for gap in gaps), gaps
        assert notification_log[0]['monotonic'] - started < 0.3
        assert [entry['pending_ids'] for entry in notification_log] == [['a2', 'a3'], ['a3'], []]
        if arrivals:
            assert all(arrivals[i]['monotonic'] - arrivals[i-1]['monotonic'] >= 0.28 for i in (1, 2))
        record_artifact('internal-json' if internal_json else 'sse',
            dict(started_monotonic=started, expected_min_gap_seconds=0.3, actual_ws_gaps=gaps,
                 ws=notification_log, sse=arrivals, events=paragraphs))
    asyncio.run(case())


def test_external_json_returns_fresh_schedule_before_background_delivery(monkeypatch, delivery_db, notification_log):
    req, current, run = synthetic_delivery(monkeypatch, delivery_db)
    async def case():
        started = time.monotonic()
        response = await run(use_json=True)
        returned = time.monotonic()
        events = [e for e in json.loads(response.body)['events'] if e.get('type') == 'assistant_paragraph']
        assert returned - started < 0.3
        assert not any(e.get('delivery_paced') for e in events)
        assert events[2]['display_at_server_ms'] - events[0]['server_now_ms'] == 600
        assert events[2]['display_at_server_ms'] > int(time.time() * 1000)
        await req._normal_delivery_session.background_task
        assert len(notification_log) == 3
        assert all(notification_log[i]['monotonic'] - notification_log[i-1]['monotonic'] >= 0.29 for i in (1, 2))
        record_artifact('external-json', dict(return_duration=returned-started, events=events, ws=notification_log))
    asyncio.run(case())


def test_new_user_during_interval_cancels_only_unsent_tail(monkeypatch, delivery_db, notification_log):
    req, current, run = synthetic_delivery(monkeypatch, delivery_db)
    async def case():
        response = await run()
        events = []
        async for packet in response.body_iterator:
            if packet.startswith('data: ') and packet.strip() != 'data: [DONE]':
                event = json.loads(packet[6:].strip())
                events.append(event)
                if event.get('id') == 'a1':
                    await asyncio.sleep(0.08)
                    current[0] = False
        assert [item['mid'] for item in notification_log] == ['a1']
        assert any(e.get('type') == 'cancelled' for e in events)
        with sqlite3.connect(delivery_db) as conn:
            rows = conn.execute('SELECT message_id,is_hidden FROM messages ORDER BY sequence_number').fetchall()
        assert rows == [('a1', 0), ('a2', 1), ('a3', 1)]
        assert not pending_message_ids(req.username, req.character_id, 'conv')
        record_artifact('cancelled', dict(ws=notification_log, persisted_visibility=rows, events=events))
    asyncio.run(case())


@pytest.mark.parametrize('allow', ['blocked', 'explicit_at', 'own_death'])
def test_death_before_next_release_honors_spirit_and_own_terminal_reply(delivery_db, notification_log, allow):
    add_messages(delivery_db, ['a1', 'a2'])
    req = request()
    if allow == 'explicit_at':
        req.reply_character_id = 'main'
    if allow == 'own_death':
        req._normal_committed_death_message_id = 'u1'
    async def case():
        session = NormalDeliverySession()
        session.register(req, ['a1', 'a2'], delivery_db)
        await session.release({'type': 'assistant_paragraph', 'id': 'a1'}, req, delay_seconds=0)
        with sqlite3.connect(delivery_db) as conn:
            conn.execute("INSERT INTO normal_character_lifecycle VALUES('pacing-test','main','conv','dead','u1')")
        if allow == 'blocked':
            with pytest.raises(DeliveryCancelled, match='character_is_dead'):
                await session.release({'type': 'assistant_paragraph', 'id': 'a2'}, req, delay_seconds=0.12)
        else:
            await session.release({'type': 'assistant_paragraph', 'id': 'a2'}, req, delay_seconds=0.12)
        await session.finish()
        assert len(notification_log) == (1 if allow == 'blocked' else 2)
    asyncio.run(case())


def test_history_filters_pending_ids_before_limit_and_can_fetch_late_lower_sequence(
        monkeypatch, delivery_db, notification_log):
    import Backend.routes.messages as routes
    add_messages(delivery_db, ['old', 'guest-low', 'main-high'])
    req = request()
    async def noop(*args, **kwargs):
        return {}
    async def auth(token):
        return 'pacing-test'
    monkeypatch.setattr(routes, 'auth_token_verify', auth)
    monkeypatch.setattr(routes, 'get_database', lambda: SimpleNamespace(db_path=str(delivery_db), init=noop))
    monkeypatch.setattr(routes, 'load_attachments_for_messages', noop)
    monkeypatch.setattr(routes, 'load_voice_states_for_messages', noop)
    async def load(**kwargs):
        return await routes.get_conversation_messages_paged(username='pacing-test', character_id='main',
            conversation_id='conv', x_chat_auth='synthetic', **kwargs)
    async def case():
        session = NormalDeliverySession()
        session.register(req, ['guest-low', 'main-high'], delivery_db)
        first = await load(limit=1)
        assert [m['message_id'] for m in first['messages']] == ['old']
        assert first['has_more'] is False
        assert (await load(message_id='guest-low'))['messages'] == []
        await session.release({'type': 'assistant_paragraph', 'id': 'main-high'}, req, delay_seconds=0)
        high = await load(after_seq=1)
        assert [m['message_id'] for m in high['messages']] == ['main-high']
        await session.release({'type': 'assistant_asset', 'message_id': 'guest-low'}, req, delay_seconds=0.12)
        assert (await load(after_seq=3))['messages'] == []
        late = await load(message_id='guest-low')
        assert late['messages'][0]['sequence_number'] == 2
        assert [item['mid'] for item in notification_log] == ['main-high', 'guest-low']
        await session.finish()
        record_artifact('history-nonmonotonic', dict(first=first, high=high, late=late, ws=notification_log))
    asyncio.run(case())


def test_multi_speaker_slow_generation_has_one_delivery_owner_and_fresh_intervals(
        monkeypatch, delivery_db, notification_log):
    import Backend.chat_modules.service as service
    from fastapi.responses import JSONResponse
    monkeypatch.setattr(service, '_normal_message_event_delay_seconds', lambda event: 0.2)
    async def child(req, *args, **kwargs):
        assert req._normal_delivery_managed_by_parent is True
        await asyncio.sleep(0.65 if req.reply_character_id == 'guest-a' else 0.02)
        mid = req.reply_character_id
        add_messages(delivery_db, [mid])
        req._normal_delivery_session.register(req, [mid], delivery_db)
        return JSONResponse({'events': [dict(type='assistant_paragraph', id=mid, content=mid,
            display_at_server_ms=1, server_now_ms=1, display_delay_ms=0, delivery_paced=True)]})
    monkeypatch.setattr(service, 'handle_chat_request', child)
    async def case():
        req = request()
        started = time.monotonic()
        response = await service._handle_normal_multi_speaker_request(request=req,
            reply_character_ids=['guest-a', 'guest-b'], x_client_id='test', x_chat_auth='synthetic',
            active_model={}, use_json_protocol=False, release_lock=lambda: asyncio.sleep(0))
        arrivals = []
        async for packet in response.body_iterator:
            if packet.startswith('data: ') and packet.strip() != 'data: [DONE]':
                event = json.loads(packet[6:])
                if event.get('type') == 'assistant_paragraph':
                    arrivals.append(dict(mid=event['id'], monotonic=time.monotonic(), event=event))
        assert [e['mid'] for e in arrivals] == ['guest-a', 'guest-b']
        assert arrivals[0]['monotonic'] - started >= 0.64
        gap = arrivals[1]['monotonic'] - arrivals[0]['monotonic']
        assert 0.19 <= gap < 0.5
        assert [e['mid'] for e in notification_log] == ['guest-a', 'guest-b']
        assert notification_log[0]['pending_ids'] == ['guest-b']
        with sqlite3.connect(delivery_db) as conn:
            db_order = [r[0] for r in conn.execute('SELECT message_id FROM messages ORDER BY sequence_number')]
        assert db_order == ['guest-b', 'guest-a']
        record_artifact('multi-speaker', dict(started_monotonic=started, expected_gap=0.2,
            actual_gap=gap, events=arrivals, ws=notification_log, persisted_order=db_order))
    asyncio.run(case())


def test_slow_notification_does_not_consume_next_sse_interval(monkeypatch):
    async def case():
        session = NormalDeliverySession()
        count = 0
        async def slow_notify(event, req):
            nonlocal count
            count += 1
            if count == 1:
                await asyncio.sleep(0.25)
        monkeypatch.setattr(session, 'notify', slow_notify)
        await session.release({'type': 'assistant_paragraph', 'id': 'a1'}, request(), delay_seconds=0)
        first = time.monotonic()
        await session.release({'type': 'assistant_paragraph', 'id': 'a2'}, request(), delay_seconds=0.12)
        second = time.monotonic()
        assert second - first >= 0.11
        await session.finish()
        record_artifact('slow-notification', dict(notification_delay=0.25, expected_gap=0.12, actual_gap=second-first))
    asyncio.run(case())


@pytest.mark.parametrize('cancelled', [False, True])
def test_cleanup_recovers_from_temporary_database_failure(monkeypatch, delivery_db, cancelled):
    add_messages(delivery_db, ['a1'])
    async def case():
        session = NormalDeliverySession()
        session.register(request(), ['a1'], delivery_db)
        if cancelled:
            session.cancelled = True
            hide = session.hide_cancelled_pending
            attempts = 0
            async def transient_failure():
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise sqlite3.OperationalError('database is locked')
                await hide()
            monkeypatch.setattr(session, 'hide_cancelled_pending', transient_failure)
        else:
            async def transient_failure(*args, **kwargs):
                raise sqlite3.OperationalError('database is locked')
            monkeypatch.setattr(session, 'check_persisted', transient_failure)
        await session.finish()
        if cancelled:
            assert pending_message_ids('pacing-test', 'main', 'conv') == {'a1'}
            await session.background_task
        assert not pending_message_ids('pacing-test', 'main', 'conv')
        with sqlite3.connect(delivery_db) as conn:
            hidden = conn.execute('SELECT is_hidden FROM messages').fetchone()[0]
        assert hidden == int(cancelled)
    asyncio.run(case())


def ui_routes(monkeypatch, delivery_db):
    import Backend.routes.messages as routes
    import Backend.routes.characters as characters
    import Backend.db.message_attachments as attachments
    import Backend.db.message_voice_states as voice
    async def empty(*args, **kwargs):
        return {}
    async def auth(token):
        return 'pacing-test'
    async def user_id(*args):
        return 1
    db = SimpleNamespace(db_path=str(delivery_db), init=empty, _get_user_id=user_id)
    monkeypatch.setattr(routes, 'auth_token_verify', auth)
    monkeypatch.setattr(routes, 'get_database', lambda: db)
    monkeypatch.setattr(characters, 'get_database', lambda: db)
    monkeypatch.setattr(routes, 'load_attachments_for_messages', empty)
    monkeypatch.setattr(routes, 'load_voice_states_for_messages', empty)
    monkeypatch.setattr(attachments, 'load_attachments_for_messages', empty)
    monkeypatch.setattr(voice, 'load_voice_states_for_messages', empty)
    return routes, characters


def test_search_count_and_legacy_incremental_keep_null_id_history(monkeypatch, delivery_db):
    routes, characters = ui_routes(monkeypatch, delivery_db)
    add_messages(delivery_db, ['old', 'pending'])
    with sqlite3.connect(delivery_db) as conn:
        conn.execute("INSERT INTO messages(conversation_id,content,sequence_number) VALUES('conv','legacy',0)")
    async def case():
        session = NormalDeliverySession()
        session.register(request(), ['pending'], delivery_db)
        args = dict(username='pacing-test', character_id='main', x_chat_auth='synthetic')
        counted = await routes.count_visible_messages(**args)
        assert counted['total'] == 2
        searched = await routes.search_messages(query='pending', **args)
        assert searched['total'] == 0 and searched['results'] == []
        legacy = await routes.search_messages(query='legacy', **args)
        assert legacy['total'] == 1 and legacy['results'][0]['message_id'] is None
        incremental = await characters.get_messages_since(username='pacing-test', character_id='main',
                                                         conversation_id='conv', after_seq=-1)
        assert incremental['total_count'] == 2
        assert {m['message_id'] for m in incremental['new_messages']} == {None, 'old'}
        page = await routes.get_conversation_messages_paged(conversation_id='conv', **args)
        assert {m['message_id'] for m in page['messages']} == {None, 'old'}
        await session.finish()
    asyncio.run(case())


def test_old_read_snapshot_cannot_reveal_a_concurrently_cancelled_tail(monkeypatch, delivery_db):
    import aiosqlite
    routes, _ = ui_routes(monkeypatch, delivery_db)
    add_messages(delivery_db, ['old', 'tail'])
    async def case():
        session = NormalDeliverySession()
        session.register(request(), ['tail'], delivery_db)
        session.cancelled = True
        original = aiosqlite.Cursor.fetchone
        cleanup = None
        writer_blocked = []
        async def after_first_user_read(cursor):
            nonlocal cleanup
            result = await original(cursor)
            if cleanup is None and cursor.description and len(cursor.description) == 1 and cursor.description[0][0] == 'id':
                cleanup = asyncio.create_task(session.finish())
                await asyncio.sleep(0.08)
                writer_blocked.append(not cleanup.done())
            return result
        monkeypatch.setattr(aiosqlite.Cursor, 'fetchone', after_first_user_read)
        page = await routes.get_conversation_messages_paged(username='pacing-test', character_id='main',
            conversation_id='conv', x_chat_auth='synthetic')
        assert cleanup is not None
        await cleanup
        assert writer_blocked == [True]
        assert [m['message_id'] for m in page['messages']] == ['old']
        with sqlite3.connect(delivery_db) as conn:
            assert conn.execute("SELECT is_hidden FROM messages WHERE message_id='tail'").fetchone()[0] == 1
    asyncio.run(case())
