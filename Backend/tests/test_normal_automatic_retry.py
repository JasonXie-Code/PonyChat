"""Foreground failures recover once without another user message or early commit."""
import asyncio
import json

import pytest

from test_autonomous_normal import normal, turn, run, make_store, model_result, stage_args
from test_agent_parity import business, decision
from Backend.chat_modules.autonomous_normal import run_autonomous_turn


@pytest.mark.parametrize('failure', [RuntimeError, TimeoutError])
def test_execution_error_retries_immediately_and_keeps_drafts_and_usage(tmp_path, failure):
    store = make_store(tmp_path / 'memory.sqlite')
    attempts, metering = [], []

    async def runner(prompt, config, tools, **options):
        attempts.append(json.loads(prompt))
        if len(attempts) == 1:
            await tools['stage_memory'].callback(stage_args())
            exc = failure('synthetic model failure')
            exc.harness_usage = {'usage': {'prompt_tokens': 10}, 'llm_api_calls': 2, 'tool_call_count': 1}
            raise exc
        assert options['max_tool_calls'] == normal.NORMAL_TOOL_CALL_LIMIT
        assert attempts[-1]['automatic_retry'] == {'attempt': 1, 'maximum': 1}
        assert attempts[-1]['verified_observations'][0]['tool'] == 'stage_memory'
        assert metering == []
        return model_result() | {'usage': {'prompt_tokens': 5}}

    result = run(turn(memory_store=store, harness_runner=runner, usage_sink=metering.append))
    assert len(attempts) == 2 and result['automatic_retries'] == 1
    assert result['usage']['prompt_tokens'] == 15
    assert result['llm_api_calls'] == 3 and result['tool_call_count'] == 1
    assert len(metering) == 1 and metering[0]['incomplete'] is False
    assert len(store.commit(reply_succeeded=True, generation_is_current=lambda: True)) == 1


def test_incomplete_run_also_recovers_without_new_input():
    calls = []

    async def runner(*args, **options):
        calls.append(1)
        return model_result(finish='max_steps' if len(calls) == 1 else 'completed')

    result = run(turn(harness_runner=runner))
    assert len(calls) == 2 and result['llm_api_calls'] == 2
    assert result['automatic_retries'] == 1


def test_repeated_transport_failure_stops_after_one_retry_and_discards(tmp_path):
    store = make_store(tmp_path / 'memory.sqlite')
    calls, metering = [], []

    async def runner(prompt, config, tools, **options):
        calls.append(1)
        if len(calls) == 1:
            await tools['stage_memory'].callback(stage_args())
        exc = RuntimeError('still unavailable')
        exc.harness_usage = {'usage': {'prompt_tokens': 10}, 'llm_api_calls': 2,
                             'tool_call_count': int(len(calls) == 1)}
        raise exc

    with pytest.raises(RuntimeError, match='still unavailable'):
        run(turn(memory_store=store, harness_runner=runner, usage_sink=metering.append))
    assert len(calls) == 2
    assert len(metering) == 1 and metering[0]['incomplete'] is True
    assert metering[0]['llm_api_calls'] == 4 and metering[0]['tool_call_count'] == 1
    assert metering[0]['usage']['prompt_tokens'] == 20
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True) == []


@pytest.mark.parametrize('cancel_on', [1, 2])
def test_cancellation_is_never_retried(tmp_path, cancel_on):
    store = make_store(tmp_path / 'memory.sqlite')
    calls = []

    async def runner(prompt, config, tools, **options):
        calls.append(1)
        if len(calls) == 1:
            await tools['stage_memory'].callback(stage_args())
        if len(calls) == cancel_on:
            raise asyncio.CancelledError()
        raise RuntimeError('transient failure')

    with pytest.raises(asyncio.CancelledError):
        run(turn(memory_store=store, harness_runner=runner))
    assert len(calls) == cancel_on
    assert store.commit(reply_succeeded=True, generation_is_current=lambda: True) == []


def test_missing_followup_fields_after_tool_exhaustion_recovers_without_duplicate_schedule():
    b = business(text='你好，给你带了一本新书。')
    calls, budgets = [], []

    async def runner(prompt, config, tools, **options):
        calls.append(json.loads(prompt))
        budgets.append(options['max_tool_calls'])
        if len(calls) == 1:
            return model_result(finish='tool_budget_exhausted') | {'tool_call_count': 12}
        data = decision()
        if len(calls) < 5:
            data['followup_decision'].pop('summary')
            data['followup_decision'].pop('target_delay_seconds')
        return model_result() | {'final_response': json.dumps(data, ensure_ascii=False)}

    result = asyncio.run(run_autonomous_turn(messages=b.history, character_profile='成年角色',
        environment='', model_config={}, business_tools=b, harness_runner=runner))
    assert len(calls) == 5 and budgets == [normal.NORMAL_TOOL_CALL_LIMIT, 0, 0, 0, 0]
    assert result['automatic_retries'] == 1 and result['llm_api_calls'] == 5
    assert result['tool_call_count'] == 12
    assert len(b.schedules) == 1
    assert b.schedules[0]['kind'] == 'followup'


def test_resident_followup_schema_survives_no_tools_and_retry():
    from test_autonomous_prompt_skills import session, payload
    s = session()
    for retry in (False, True):
        prompt, _ = s.transform(payload(followup_contract='full contract',
            **({'completion_feedback': 'missing summary'} if retry else {})), normal.SYSTEM)
        contract = json.loads(prompt)['followup_contract']
        assert 'summary' in contract and 'target_delay_seconds' in contract
        assert '60到1800' in contract and 'followup技能' in contract
        assert not s.loaded


def test_retry_uses_only_remaining_time(monkeypatch):
    from types import SimpleNamespace
    clock = [100.0]
    monkeypatch.setattr(normal, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    limits = []

    async def runner(prompt, config, tools, **options):
        limits.append(options['timeout_seconds'])
        if len(limits) == 1:
            clock[0] += 62
            raise RuntimeError('model failure')
        return model_result()

    result = run(turn(harness_runner=runner))
    # The first attempt gets the exploration window, never the whole total. By the
    # time the retry starts that window is spent, so it delivers from existing
    # evidence inside the delivery window and extends nothing.
    assert limits == [normal.NORMAL_EXPLORATION_LIMIT_SECONDS, None]
    assert result['automatic_retries'] == 1


def test_normal_stops_tools_at_twelve_and_finishes_from_existing_information():
    budgets = []

    async def runner(prompt, config, tools, **options):
        budgets.append(options['max_tool_calls'])
        if len(budgets) == 1:
            assert options['stop_on_tool_budget'] is True
            assert 0 < options['tool_timeout_seconds'] <= normal.NORMAL_TOOL_TIME_LIMIT_SECONDS
            return model_result(finish='tool_budget_exhausted') | {'tool_call_count': 12}
        assert options['force_no_tools'] is True
        assert json.loads(prompt)['verified_observations'] == []
        return model_result()

    result = run(turn(harness_runner=runner))
    assert budgets == [normal.NORMAL_TOOL_CALL_LIMIT, 0]
    assert result['tool_call_count'] == 12
    assert result['automatic_retries'] == 0


def test_request_has_no_wall_clock_cutoff_but_can_be_cancelled(monkeypatch):
    from Backend.chat_modules import autonomous_service as service
    cancelled = []
    async def prepare(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
    monkeypatch.setattr(service, '_prepare_autonomous_request', prepare)
    async def exercise():
        task = asyncio.create_task(service._bounded_autonomous_request())
        await asyncio.sleep(.02)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(exercise())
    assert cancelled == [True]


def test_output_repair_keeps_tools_for_an_unfinished_required_reminder():
    b = business(text='两分钟后提醒我喝水。')
    assert b.reminder_expected
    attempts = []

    async def runner(prompt, config, tools, **options):
        attempts.append(options['max_tool_calls'])
        if len(attempts) == 1:
            return model_result() | {'final_response': 'invalid JSON'}
        assert options['max_tool_calls'] == normal.NORMAL_TOOL_CALL_LIMIT and 'stage_schedule' in tools
        await tools['stage_schedule'].callback({'kind': 'agreed', 'summary': '提醒用户喝水',
            'target_delay_seconds': 120, 'source_message_id': 'm1', 'reason': '用户明确要求'})
        return model_result() | {'final_response': json.dumps(decision(False), ensure_ascii=False)}

    result = asyncio.run(run_autonomous_turn(messages=b.history, character_profile='成年角色',
        environment='', model_config={}, business_tools=b, harness_runner=runner))
    assert attempts == [normal.NORMAL_TOOL_CALL_LIMIT, normal.NORMAL_TOOL_CALL_LIMIT]
    assert result['output_format_repairs'] == 1
    assert len(b.schedules) == 1 and b.schedules[0]['kind'] == 'agreed'


def test_output_repair_keeps_required_character_reference_available():
    from test_autonomous_prompt_skills import session
    current = session(home='')
    attempts = []

    async def transport(prompt, config, tools, **options):
        attempts.append(options['max_tool_calls'])
        if len(attempts) == 1:
            return model_result() | {'final_response': 'invalid JSON'}
        assert options['max_tool_calls'] == normal.NORMAL_TOOL_CALL_LIMIT
        await tools['read_character_reference'].callback({'query': '青竹 陆马'})
        await tools['load_chat_skill'].callback({'name': 'instant_messaging'})
        return model_result()

    result = run(turn(harness_runner=current.runner(transport)))
    assert attempts == [normal.NORMAL_TOOL_CALL_LIMIT, normal.NORMAL_TOOL_CALL_LIMIT] and current.reference_searched
    assert result['output_format_repairs'] == 1
