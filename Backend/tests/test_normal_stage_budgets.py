"""Separated stage budgets, single-copy skill context and degraded recovery.

Covers the follow-up to a real 125s timeout: exploration had been handed the whole
user-facing total, a delivery retry inherited that same spent window, the per-turn
manuals cost one model round trip each, and the only retry re-sent the full prompt.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

from test_autonomous_normal import normal, turn, run, model_result, row_message
from test_autonomous_prompt_skills import session, payload


# --------------------------------------------------------------------------
# 1. Four separate deadlines and three distinct error types
# --------------------------------------------------------------------------

def test_exploration_expiry_enters_delivery_instead_of_failing(monkeypatch):
    """Exploration running out must not consume the delivery or recovery windows."""
    clock = [0.0]
    monkeypatch.setattr(normal, 'time', types.SimpleNamespace(monotonic=lambda: clock[0]))
    observed = []

    async def runner(prompt, config, tools, **options):
        observed.append(options)
        if len(observed) == 1:
            # Burn the whole exploration window without returning a finish reason.
            clock[0] = normal.NORMAL_EXPLORATION_LIMIT_SECONDS + 1.0
            return model_result(finish='tool_budget_exhausted')
        return model_result()

    run(turn(harness_runner=runner))
    assert observed[0]['delivery_only'] is False
    assert observed[1]['delivery_only'] is True
    assert observed[1]['force_no_tools'] is True


# --------------------------------------------------------------------------
# 2. One copy of every manual, and one round trip for the fixed set
# --------------------------------------------------------------------------

def test_fixed_manuals_can_be_read_in_one_round_trip():
    skills = session(home='')
    fixed = ['evidence', 'reply_expression', 'reply_language', 'voice_reply', 'delivery']
    result = asyncio.run(skills.load({'names': fixed}))
    assert [item['skill'] for item in result['skills']] == fixed
    assert set(skills.loaded) == set(fixed)
    # The single-name form keeps its original shape for existing callers.
    single = asyncio.run(skills.load({'name': 'speech'}))
    assert single['skill'] == 'speech' and 'instructions' in single


def test_each_manual_appears_at_most_once_per_prompt():
    skills = session(home='')
    skills.loaded.update({'evidence', 'reply_expression', 'reply_language', 'voice_reply', 'delivery'})
    prompt, _ = skills.transform(payload(previous_attempt={'reply': 'draft'}), normal.SYSTEM)
    data = json.loads(prompt)
    docs = [item['skill'] for item in data.get('finalization_skills', [])]
    docs += [item['result']['skill'] for item in data.get('verified_observations', [])
             if item.get('tool') == 'load_chat_skill']
    assert len(docs) == len(set(docs)), f"duplicate manual in one prompt: {docs}"


def test_a_skill_read_twice_is_injected_once():
    skills = session(home='')
    asyncio.run(skills.load({'name': 'delivery'}))
    asyncio.run(skills.load({'names': ['delivery', 'evidence']}))
    prompt, _ = skills.transform(payload(previous_attempt={'reply': 'draft'}), normal.SYSTEM)
    data = json.loads(prompt)
    injected = [item['result']['skill'] for item in data.get('verified_observations', [])
                if item.get('tool') == 'load_chat_skill']
    assert sorted(injected) == ['delivery', 'evidence']


# --------------------------------------------------------------------------
# 3. Delivery has its own generation budget, and it reaches the request
# --------------------------------------------------------------------------

class _Harness:
    def __init__(self, **config):
        self.config = config
        self.instances.append(self)

    instances: list = []

    def run(self, prompt, on_notification=None, **kwargs):
        return types.SimpleNamespace(final_response='{}', finish_reason='completed', events=[])

    def close(self):
        pass


def _capture(monkeypatch):
    monkeypatch.setenv('PONYCHAT_HARNESS_POOL', '0')
    _Harness.instances = []
    monkeypatch.setitem(sys.modules, 'deepseek_harness',
                        types.SimpleNamespace(DeepSeekHarness=_Harness))
    return _Harness.instances


def test_delivery_request_carries_its_own_reasoning_budget(monkeypatch):
    from test_harness_runtime import run_harness_turn
    instances = _capture(monkeypatch)
    asyncio.run(run_harness_turn('hi', {}, {}, delivery_only=True,
                                 delivery_reasoning_effort=None, timeout_seconds=5))
    assert instances[-1].config['reasoning_effort'] is None

    asyncio.run(run_harness_turn('hi', {}, {}, delivery_only=True,
                                 delivery_reasoning_effort='low', timeout_seconds=5))
    assert instances[-1].config['reasoning_effort'] == 'low'


def test_callers_cannot_raise_exploration_reasoning(monkeypatch):
    from test_harness_runtime import run_harness_turn
    instances = _capture(monkeypatch)
    asyncio.run(run_harness_turn('hi', {}, {}, reasoning_effort='high', timeout_seconds=5))
    assert instances[-1].config['reasoning_effort'] == 'low'


def test_unsupported_delivery_reasoning_is_rejected(monkeypatch):
    from test_harness_runtime import run_harness_turn
    _capture(monkeypatch)
    with pytest.raises(ValueError, match='reasoning effort'):
        asyncio.run(run_harness_turn('hi', {}, {}, delivery_only=True,
                                     delivery_reasoning_effort='max', timeout_seconds=5))


def test_delivery_attempt_sends_the_delivery_generation_budget(monkeypatch):
    """The parameters the Agent layer sets must survive into the runtime options."""
    sent = []

    async def runner(prompt, config, tools, **options):
        sent.append(options)
        if len(sent) == 1:
            return model_result(finish='tool_budget_exhausted')
        return model_result()

    run(turn(harness_runner=runner))
    delivery = sent[1]
    assert delivery['delivery_reasoning_effort'] == normal.NORMAL_DELIVERY_REASONING_EFFORT
    assert delivery['max_tokens'] <= normal.NORMAL_DELIVERY_MAX_TOKENS
    exploration = sent[0]
    assert 0 < exploration['tool_timeout_seconds'] <= normal.NORMAL_EXPLORATION_LIMIT_SECONDS


def test_delivery_reasoning_effort_reaches_the_sdk_initialize_payload():
    """Inspect the wire payload, not just our own signature.

    The SDK omits `reasoningEffort` when it is None, so a delivery pass configured
    with None really does go out without a reasoning declaration instead of being
    silently coerced back to low somewhere below us.
    """
    from deepseek_harness.client import HarnessClient

    captured = []

    def build(reasoning_effort):
        client = HarnessClient.__new__(HarnessClient)
        client.request = lambda method, payload, **kwargs: captured.append((method, dict(payload)))
        client.config = types.SimpleNamespace(initialize_timeout_seconds=5, profile='sdk-minimal')
        HarnessClient.initialize(client, cwd='.', provider='deepseek-official',
                                 model='deepseek-v4-flash', reasoning_effort=reasoning_effort)
        return captured[-1][1]

    assert 'reasoningEffort' not in build(None)
    assert build('low')['reasoningEffort'] == 'low'


# --------------------------------------------------------------------------
# 4. One controlled degraded recovery that keeps the task, the facts,
#    the saved preferences and the operations already executed
# --------------------------------------------------------------------------

def test_degraded_recovery_keeps_task_facts_and_executed_operations():
    prompt_data = {
        'latest_user_message': {'role': 'user', 'content': '记住我喜欢红茶'},
        'current_user_batch': [{'role': 'user', 'content': '记住我喜欢红茶'}],
        'character_profile': '紫悦',
        'environment': '【当前环境】',
        'current_scene': {'fields': {'location': {'value': '图书馆'}}},
        'relationship_state': {'relationship_stage': 'committed_partner'},
        'relationship_execution_contract': {'fixed_rule': '按已确认关系承接'},
        'verified_observations': [{'tool': 'stage_memory', 'result': {'staged': True}}],
        'previous_attempt': {'reply': '草稿', 'tool_attempts': [{'tool': 'stage_memory', 'success': True}]},
        'source_message_times': {'m1': {'occurred_at': '2026-09-14T00:00:00+00:00'}},
        'recent_raw_messages': [{'sequence_number': i, 'role': 'user' if i % 2 else 'assistant',
                                 'content': f'第{i}条'} for i in range(1, 41)],
        'noise_that_should_drop': 'x' * 5000,
    }
    degraded = normal._degraded_prompt_data(prompt_data, rounds=3)

    for key in ('latest_user_message', 'current_user_batch', 'character_profile', 'environment',
                'current_scene', 'relationship_state', 'relationship_execution_contract',
                'verified_observations', 'source_message_times'):
        assert degraded[key] == prompt_data[key], f"{key} must survive the degraded retry"
    assert degraded['previous_attempt']['tool_attempts'] == prompt_data['previous_attempt']['tool_attempts']
    assert degraded['previous_attempt']['reply'] == '草稿'
    assert degraded['degraded_recovery']['maximum'] == 1
    assert degraded['required_tools_before_reply'] == []
    assert 'noise_that_should_drop' not in degraded
    # Whole rounds, not a dangling tail: every kept message keeps its neighbour.
    kept = degraded['recent_raw_messages']
    assert kept and len(kept) < len(prompt_data['recent_raw_messages'])
    assert kept[0]['sequence_number'] % 2 == 1 and kept[-1]['sequence_number'] == 40


def test_degraded_recovery_drops_the_whole_transcript_only_when_empty():
    degraded = normal._degraded_prompt_data({'recent_raw_messages': [], 'latest_user_message': {'content': '嗨'}})
    assert degraded['recent_raw_messages'] == []
    assert degraded['latest_user_message'] == {'content': '嗨'}


def test_exploration_timeout_switches_without_using_failure_retry(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(normal, 'time', types.SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []
    async def runner(prompt, config, tools, **options):
        calls.append(options)
        if len(calls) == 1:
            clock[0] = 60
            raise asyncio.TimeoutError()
        assert tools == {} and options['timeout_seconds'] is None
        clock[0] = 10000
        return model_result()
    result = run(turn(harness_runner=runner))
    assert result['automatic_retries'] == 0
    assert len(calls) == 2


def test_delivery_model_failure_still_stops_after_one_recovery(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(normal, 'time', types.SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []
    async def runner(prompt, config, tools, **options):
        calls.append(options)
        if len(calls) == 1:
            clock[0] = 60
            return model_result(finish='tool_time_budget_exhausted')
        clock[0] += 1000
        assert options['timeout_seconds'] is None and tools == {}
        raise RuntimeError('provider failed')
    with pytest.raises(RuntimeError, match='provider failed'):
        run(turn(harness_runner=runner))
    assert len(calls) == 3
