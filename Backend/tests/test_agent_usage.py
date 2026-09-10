"""Harness token and point accounting uses actual Agent model steps."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


def load_usage(monkeypatch, calls):
    root = '_agent_usage_test'
    package = ModuleType(root)
    package.__path__ = []
    memory = ModuleType(root + '.agent_memory')
    memory.__path__ = [str(Path(__file__).parents[1] / 'agent_memory')]
    db = ModuleType(root + '.db')

    class Users:
        async def increment_usage(self, username, inp, out, **kwargs):
            calls.append(('tokens', username, inp, out, kwargs['llm_api_calls']))

    class Membership:
        async def increment_by(self, username, count):
            calls.append(('points', username, count))

    db.get_users_dao = Users
    db.get_membership_dao = Membership
    for name, module in ((root, package), (root + '.agent_memory', memory), (root + '.db', db)):
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).parents[1] / 'agent_memory' / 'usage.py'
    spec = importlib.util.spec_from_file_location(root + '.agent_memory.usage', path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_agent_usage_meters_aggregated_tokens_and_every_model_step(monkeypatch):
    calls = []
    usage = load_usage(monkeypatch, calls)
    result = {'usage': {'prompt_tokens': 673, 'completion_tokens': 67, 'total_tokens': 740},
              'llm_api_calls': 5, 'tool_call_count': 3, 'incomplete': True}
    assert asyncio.run(usage.meter_user('alice', result)) == {
        'input_tokens': 673, 'output_tokens': 67, 'llm_api_calls': 5, 'tool_call_count': 3, 'points': 8}
    assert calls == [('tokens', 'alice', 673, 67, 5), ('points', 'alice', 8)]


def test_agent_usage_rejects_invalid_counters_and_can_skip_points(monkeypatch):
    calls = []
    usage = load_usage(monkeypatch, calls)
    result = {'usage': {'input_tokens': 12, 'output_tokens': -3}, 'llm_api_calls': True}
    assert asyncio.run(usage.meter_user('alice', result, charge_membership=False)) == {
        'input_tokens': 12, 'output_tokens': 0, 'llm_api_calls': 1, 'tool_call_count': 0, 'points': 1}
    assert calls == [('tokens', 'alice', 12, 0, 1)]


@pytest.mark.parametrize('invalid', [True, -1, '3', 1.5, None])
def test_invalid_tool_counts_do_not_inflate_points(monkeypatch, invalid):
    usage = load_usage(monkeypatch, [])
    assert usage.normalized({'llm_api_calls': 2, 'tool_call_count': invalid})['points'] == 2


def test_tools_remain_billable_after_interruption_without_token_usage(monkeypatch):
    calls = []
    usage = load_usage(monkeypatch, calls)
    counters = asyncio.run(usage.meter_user('alice', {'tool_call_count': 4, 'incomplete': True}))
    assert counters['points'] == 4 and counters['llm_api_calls'] == 0
    assert calls == [('tokens', 'alice', 0, 0, 0), ('points', 'alice', 4)]


def test_empty_and_unattributed_attempts_do_not_bill(monkeypatch):
    calls = []
    usage = load_usage(monkeypatch, calls)
    asyncio.run(usage.meter_user('alice', {}))
    asyncio.run(usage.meter_user('', {'llm_api_calls': 2, 'tool_call_count': 3}))
    assert calls == []
