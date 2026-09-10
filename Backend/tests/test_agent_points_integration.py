"""Use the real point ledger for Agent counters and all shared metering modes."""
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from Backend import db
from Backend.db.membership_dao import MembershipDAO
from Backend.agent_memory.usage import meter_user
from Backend.chat_modules.autonomous_service import settle_autonomous_usage
from Backend.providers.llm_call import _apply_usage_metering
from Backend.galgame import harness


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    path = tmp_path / 'usage.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, role TEXT);
            INSERT INTO users VALUES(1, 'alice', 'user');
            CREATE TABLE daily_chat_usage(user_id INTEGER, usage_date TEXT, usage_count INTEGER,
                last_used_at TEXT, UNIQUE(user_id,usage_date));''')
    users = []
    async def tokens(username, inp, out, *, llm_api_calls):
        users.append((username, inp, out, llm_api_calls))
    monkeypatch.setattr(db, 'get_users_dao', lambda: SimpleNamespace(
        increment_usage=tokens, increment_companion_usage=tokens))
    monkeypatch.setattr(db, 'get_membership_dao', lambda: MembershipDAO(SimpleNamespace(db_path=str(path))))
    def points():
        with sqlite3.connect(path) as conn:
            return conn.execute('SELECT COALESCE(SUM(usage_count),0) FROM daily_chat_usage').fetchone()[0]
    return points, users


@pytest.mark.parametrize('channel', ['main', 'companion'])
def test_shared_meter_charges_model_plus_tools_without_inflating_models(ledger, channel):
    points, users = ledger
    asyncio.run(_apply_usage_metering(record_usage=channel, username='alice',
        resp_json={'usage': {'prompt_tokens': 12, 'completion_tokens': 3}}, llm_api_calls=3, tool_call_count=2))
    assert points() == 5 and users == [('alice', 12, 3, 3)]


def test_normal_settlement_is_idempotent(ledger):
    points, users = ledger
    request = SimpleNamespace(_autonomous_usage={'prompt_tokens': 12, 'completion_tokens': 3},
        _autonomous_llm_calls=3, _autonomous_tool_calls=2)
    async def scenario():
        await asyncio.gather(settle_autonomous_usage(request, 'alice'), settle_autonomous_usage(request, 'alice'))
        await settle_autonomous_usage(request, 'alice')
    asyncio.run(scenario())
    assert points() == 5 and len(users) == 1


def test_background_usage_and_empty_startup_attempt(ledger):
    points, _ = ledger
    asyncio.run(meter_user('alice', {'llm_api_calls': 2, 'tool_call_count': 4, 'incomplete': True}))
    asyncio.run(_apply_usage_metering(record_usage='main', username='alice', resp_json={}, llm_api_calls=0))
    assert points() == 6


@pytest.mark.parametrize('failure', [RuntimeError, asyncio.TimeoutError, asyncio.CancelledError])
def test_normal_partial_attempt_preserves_model_and_tool_usage(failure):
    from test_autonomous_normal import turn
    collected = []
    async def runner(*args, **kwargs):
        error = failure()
        error.harness_usage = {'llm_api_calls': 2, 'tool_call_count': 3,
                               'usage': {'prompt_tokens': 10}}
        raise error
    async def scenario():
        await turn(harness_runner=runner, usage_sink=collected.append)
    with pytest.raises(BaseException):
        asyncio.run(scenario())
    assert len(collected) == 1
    attempts = 1 if failure is asyncio.CancelledError else 2
    assert collected[0]['llm_api_calls'] == 2 * attempts and collected[0]['tool_call_count'] == 3 * attempts


def test_outer_normal_deadline_retains_child_cancellation_usage(monkeypatch):
    from test_autonomous_normal import normal, turn
    collected = []
    real_wait_for = asyncio.wait_for
    async def brief_wait_for(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.02)
    monkeypatch.setattr(normal.asyncio, 'wait_for', brief_wait_for)
    async def runner(*args, **kwargs):
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError as error:
            error.harness_usage = {'llm_api_calls': 2, 'tool_call_count': 3}
            raise
    with pytest.raises(normal.NormalAgentError, match='time budget'):
        asyncio.run(turn(harness_runner=runner, usage_sink=collected.append))
    assert collected[0]['llm_api_calls'] == 4 and collected[0]['tool_call_count'] == 6


@pytest.mark.parametrize('mode', ['galgame', 'galgame_lock'])
@pytest.mark.parametrize('failure', [None, RuntimeError, asyncio.CancelledError])
def test_game_attempts_settle_success_and_partial_failure(ledger, monkeypatch, mode, failure):
    points, users = ledger
    async def runner(*args, **kwargs):
        result = {'llm_api_calls': 2, 'tool_call_count': 3, 'usage': {},
                  'finish_reason': 'completed', 'final_response': '{"score":40}'}
        if failure:
            error = failure()
            error.harness_usage = result
            raise error
        return result
    monkeypatch.setattr(harness, 'run_harness_turn', runner)
    request = SimpleNamespace(_galgame_state={}, _galgame_char_profile='synthetic')
    async def scenario():
        return await harness.run_game_agent({'messages': [{'role': 'user', 'content': 'synthetic'}]}, {},
            request=request, mode=mode, timeout=3, record_usage='main', usage_meter_username='alice')
    if failure:
        with pytest.raises(failure):
            asyncio.run(scenario())
    else:
        asyncio.run(scenario())
    assert points() == 5 and len(users) == 1 and users[0][-1] == 2
