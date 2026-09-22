"""Real opening persistence/delivery with synthetic greetings and isolated SQLite."""
import asyncio
import sqlite3
import time

import pytest

from Backend.chat_modules import opening_greeting as opening
from Backend.chat_modules.normal_delivery import pending_message_ids
from test_autonomous_upgrade_integration import database


@pytest.fixture
def opening_setup(database, monkeypatch):
    with sqlite3.connect(database.db_path) as conn:
        conn.execute('DELETE FROM messages')
    monkeypatch.setattr(opening, 'get_database', lambda: database)
    async def generate(*args, **kwargs):
        return {'bubbles': ['你好！', '很高兴认识你。', '今天想聊什么？'], 'reason': 'agent_opening'}

    monkeypatch.setattr(opening, 'generate_opening_greeting', generate)
    monkeypatch.setattr(opening, 'normal_text_bubble_delay_seconds', lambda _: 0.06)
    return database


def test_opening_delivery_spaces_notifications_and_gates_history(opening_setup, monkeypatch):
    from Backend import delivery_outbox
    log = []

    async def notify(**payload):
        with sqlite3.connect(opening_setup.db_path) as conn:
            ids = {row[0] for row in conn.execute('SELECT message_id FROM messages')}
        pending = pending_message_ids('alice', 'twilight', 'c1')
        log.append((time.monotonic(), payload, ids - pending, pending))

    monkeypatch.setattr(delivery_outbox, 'enqueue_chat_complete', notify)

    async def run():
        # Concurrent add/restore/reset requests share the same opening lock.
        return await asyncio.gather(*[
            opening.ensure_opening_greeting('alice', 'twilight', conversation_id='c1')
            for _ in range(2)
        ])

    results = asyncio.run(run())
    assert sum(result['created'] for result in results) == 1
    assert results[0]['notified']
    assert len(log) == 3
    assert all(log[i][0] - log[i-1][0] >= 0.055 for i in (1, 2))
    assert [len(item[2]) for item in log] == [1, 2, 3]
    assert [len(item[3]) for item in log] == [2, 1, 0]
    for _, payload, visible, _ in log:
        assert payload['message_id'] in visible
        assert payload['assistant_message_ids'] == [payload['message_id']]
        assert payload['message_count'] == 1
    assert not pending_message_ids('alice', 'twilight', 'c1')


def test_removing_conversation_stops_opening_tail(opening_setup, monkeypatch):
    from Backend import delivery_outbox
    sent = []

    async def notify(**payload):
        sent.append(payload['message_id'])
        with sqlite3.connect(opening_setup.db_path) as conn:
            conn.execute("UPDATE conversations SET is_hidden=1 WHERE id='c1'")

    monkeypatch.setattr(delivery_outbox, 'enqueue_chat_complete', notify)
    result = asyncio.run(opening.ensure_opening_greeting('alice', 'twilight', conversation_id='c1'))
    assert not result['notified']
    assert len(sent) == 1
    with sqlite3.connect(opening_setup.db_path) as conn:
        rows = conn.execute('SELECT message_id,is_hidden FROM messages').fetchall()
    assert {mid for mid, hidden in rows if not hidden} == set(sent)
    assert not pending_message_ids('alice', 'twilight', 'c1')


def test_text_interval_uses_normal_length_and_jitter(monkeypatch):
    from Backend.chat_modules import normal_delivery
    monkeypatch.setattr(normal_delivery.random, 'uniform', lambda lo, hi: 2.0)
    assert normal_delivery.normal_text_bubble_delay_seconds('你好') == 2.3
    assert normal_delivery.normal_text_bubble_delay_seconds('字' * 20) == 4.0
    assert normal_delivery.normal_text_bubble_delay_seconds('字' * 100) == 10.0


def test_agent_can_decline_without_persisting_or_notifying(opening_setup, monkeypatch):
    async def quiet(*args, **kwargs):
        return {'bubbles': [], 'reason': '等对方先开口'}
    monkeypatch.setattr(opening, 'generate_opening_greeting', quiet)
    result = asyncio.run(opening.ensure_opening_greeting('alice', 'twilight', conversation_id='c1'))
    assert result['created'] is False
    assert result['reason'] == '等对方先开口'
    assert result['policy_source'] == 'main_agent'
    with sqlite3.connect(opening_setup.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0


def test_user_message_arriving_during_agent_prevents_opening(opening_setup, monkeypatch):
    async def race(*args, **kwargs):
        with sqlite3.connect(opening_setup.db_path) as conn:
            conn.execute("INSERT INTO messages (id,conversation_id,role,content,timestamp,message_id) "
                         "VALUES ('user-first','c1','user','你好',1,'user-first')")
        return {'bubbles': ['你好'], 'reason': 'agent_opening'}
    monkeypatch.setattr(opening, 'generate_opening_greeting', race)
    result = asyncio.run(opening.ensure_opening_greeting('alice', 'twilight', conversation_id='c1'))
    assert result['created'] is False
    assert result['reason'] == 'conversation_changed_before_persist'
    with sqlite3.connect(opening_setup.db_path) as conn:
        assert conn.execute('SELECT role FROM messages').fetchall() == [('user',)]


def test_existing_message_skips_agent_entirely(opening_setup, monkeypatch):
    with sqlite3.connect(opening_setup.db_path) as conn:
        conn.execute("INSERT INTO messages (id,conversation_id,role,content,timestamp,message_id) "
                     "VALUES ('existing','c1','assistant','你好',1,'existing')")
    async def unexpected(*args, **kwargs):
        pytest.fail('Agent must not run for a nonempty conversation')
    monkeypatch.setattr(opening, 'generate_opening_greeting', unexpected)
    result = asyncio.run(opening.ensure_opening_greeting('alice', 'twilight', conversation_id='c1'))
    assert result['reason'] == 'conversation_already_has_messages'
