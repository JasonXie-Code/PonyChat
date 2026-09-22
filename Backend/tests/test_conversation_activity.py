import asyncio
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from Backend import conversation_activity as activity
from Backend.routes import status, auth


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / 'activity.sqlite'
    with sqlite3.connect(path) as conn:
        conn.executescript('''
            CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT);
            CREATE TABLE user_settings(user_id INTEGER, settings TEXT);
            CREATE TABLE conversations(id TEXT, user_id INTEGER, character_id TEXT, is_hidden INTEGER);
            CREATE TABLE messages(message_id TEXT, conversation_id TEXT, role TEXT, client_id TEXT,
                timestamp INTEGER, sequence_number INTEGER, deleted_at TEXT, is_hidden INTEGER);
            CREATE TABLE scheduled_followups(username TEXT, character_id TEXT, conversation_id TEXT,
                status TEXT, due_at_ms INTEGER, expires_at_ms INTEGER, cancel_if_user_replies INTEGER,
                updated_at_ms INTEGER, created_at_ms INTEGER, seed TEXT, reason TEXT, planner_json TEXT,
                source_message_id TEXT);
            INSERT INTO users VALUES(1,'alice'),(2,'bob');
            INSERT INTO user_settings VALUES(1,'{}'),(2,'{}');
            INSERT INTO conversations VALUES('conv',1,'pony',0),('other',2,'pony',0);
            INSERT INTO messages VALUES('source','conv','assistant','android',1000,0,NULL,0);
        ''')
    monkeypatch.setattr(activity, 'get_database', lambda: SimpleNamespace(db_path=path))
    return path


def read(**overrides):
    return asyncio.run(activity.read_conversation_activity(**{
        'username': 'alice', 'character_id': 'pony', 'mode': 'normal',
        'conversation_id': 'conv', 'now_ms': 100_000, **overrides}))


def task(database, state='pending', *, expires=300_000, conversation='conv'):
    with sqlite3.connect(database) as conn:
        conn.execute('INSERT INTO scheduled_followups VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('alice', 'pony', conversation, state, 160_000, expires, 1, 90_000, 80_000,
             'PRIVATE plan', 'PRIVATE reasoning', 'PRIVATE context', 'source'))


@pytest.mark.parametrize('state', ['pending', 'processing', 'sent', 'cancelled', 'expired', 'failed'])
def test_committed_states_are_read_only_and_do_not_expose_plan_text(database, state):
    task(database, state)
    before = database.read_bytes()
    result = read()
    assert result['state'] == state
    assert 'PRIVATE' not in json.dumps(result)
    assert ('due_at_ms' in result) == (state in ('pending', 'processing'))
    assert result['consecutive_limit'] == 5
    assert database.read_bytes() == before


def test_none_is_not_a_guessed_model_decision(database):
    assert read()['state'] == 'none'
    task(database, conversation='elsewhere')
    assert read()['state'] == 'none'


@pytest.mark.parametrize('override', [dict(username='bob'), dict(character_id='other'),
                                    dict(conversation_id='other'), dict(conversation_id=None)])
def test_owner_character_conversation_isolation(database, override):
    task(database)
    assert read(**override)['state'] == 'no_conversation'
    assert 'due_at_ms' not in read(**override)


@pytest.mark.parametrize('mode', ['galgame', 'galgame_lock'])
def test_game_never_exposes_normal_plan(database, mode):
    task(database)
    assert read(mode=mode)['state'] == 'unsupported'
    assert 'due_at_ms' not in read(mode=mode)


@pytest.mark.parametrize('settings', [{'memory_enabled': False}, {'proactive_messages_enabled': False}])
def test_settings_override_pending_plan(database, settings):
    task(database)
    with sqlite3.connect(database) as conn:
        conn.execute('UPDATE user_settings SET settings=? WHERE user_id=1', (json.dumps(settings),))
    assert read()['state'] == 'disabled'
    assert read()['proactive_enabled'] is False


def test_expiry_is_projected_without_mutating_scheduler(database):
    task(database, 'processing', expires=99_999)
    assert read()['state'] == 'expired'
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT status FROM scheduled_followups').fetchone()[0] == 'processing'


def test_consecutive_limit_and_user_reply_reset(database):
    task(database)
    with sqlite3.connect(database) as conn:
        conn.executemany('INSERT INTO messages VALUES(?,?,?,?,?,?,NULL,0)', [
            (str(i), 'conv', 'assistant', 'scheduled_followup', i * 5000, i) for i in range(1, 6)])
    assert read()['state'] == 'limit_reached'
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO messages VALUES('new','conv','user','android',40000,6,NULL,0)")
    assert read()['consecutive_count'] == 0
    assert read()['state'] == 'cancelled'


def test_status_api_authentication_and_graceful_partial_failure(database, monkeypatch):
    task(database)
    monkeypatch.setattr(activity.time, 'time', lambda: 100)
    async def verify(token):
        return {'alice-token': 'alice', 'bob-token': 'bob'}.get(token)
    monkeypatch.setattr(auth, 'auth_token_verify', verify)
    monkeypatch.setenv('PONYCHAT_AGENT_STATUS_DB_PATH', str(database.parent / 'agents.sqlite'))
    app = FastAPI()
    app.include_router(status.router)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            path = '/api/agent/status?character_id=pony&conversation_id=conv&mode=normal'
            assert (await client.get(path)).status_code == 401
            other = await client.get(path + '&username=alice', headers={'X-Chat-Auth': 'bob-token'})
            assert other.json()['conversation_activity']['state'] == 'no_conversation'
            own = await client.get(path, headers={'X-Chat-Auth': 'alice-token'})
            assert own.json()['conversation_activity']['state'] == 'pending'
            assert own.headers['cache-control'] == 'no-store'
            async def unavailable(*args):
                raise sqlite3.OperationalError('locked')
            monkeypatch.setattr(activity, 'read_conversation_activity', unavailable)
            error = await client.get(path, headers={'X-Chat-Auth': 'alice-token'})
            assert error.status_code == 200
            assert error.json()['conversation_activity']['state'] == 'unavailable'
    asyncio.run(scenario())
