"""Verify review isolation, metadata preservation, budgets and failure accounting."""
import asyncio
from copy import deepcopy
import importlib
import json
import time

import pytest
from test_autonomous_prompt_skills import session, PACKAGE, payload, normal

reviewer = importlib.import_module(PACKAGE + '.agent_expression_review')


def bubble(text):
    return {'index': 1, 'type': 'text', 'purpose': 'answer_user',
            'parts': [{'kind': 'speech', 'text': text}]}


def fixture():
    source = {'bubble_count': 1, 'bubbles': [bubble('好。你靠着就好。我就在这里陪着你。')],
              'used_facts': ['用户要求安静'], 'voice_reply': {'enabled': False, 'reason': '用户设置'},
              'reply_language': {'language': 'Chinese', 'reason': '延续'}}
    envelope, _ = reviewer.reply_envelope(json.dumps(source, ensure_ascii=False))
    return {'envelope': envelope, 'bubble_count': 1, 'scene_patch': {'unchanged': True},
            'usage': {'prompt_tokens': 100}, 'llm_api_calls': 2, 'tool_call_count': 3}


def edit(replacement='好。你靠着就好。'):
    return {'bubble': 1, 'part': 1, 'original': '好。你靠着就好。我就在这里陪着你。',
            'replacement': replacement, 'reason': '删除重复陪伴收尾'}


def test_loaded_expression_includes_completion_and_review_rules():
    manual = asyncio.run(session().load({'name': 'reply_expression'}))['instructions']
    assert '到这句话结束该意图的表述' in manual
    assert '删去重复动机' in manual
    assert '宣告遵守规则的收尾' in manual
    assert reviewer.EXPRESSION_COMPLETION in manual


def test_review_uses_exact_source_no_tools_and_preserves_nonvisible_state():
    result = fixture()
    original = deepcopy(result)
    task = json.loads(payload('请保留我的消息——不要修改。'))
    task_before = deepcopy(task)
    accounted = []

    async def run(prompt, config, tools, **options):
        data = json.loads(prompt)
        assert data['sources']['latest_user_message'] == task['latest_user_message']
        assert data['sources']['current_user_batch'] == task['current_user_batch']
        assert data['draft'] == json.loads(original['envelope'])
        assert tools == {} and options['max_tool_calls'] == 0
        assert options['timeout_seconds'] <= 45
        return {'finish_reason': 'completed', 'final_response': json.dumps({
            'edits': [edit()]}),
                'llm_api_calls': 1, 'usage': {'prompt_tokens': 20, 'completion_tokens': 10}}

    record = asyncio.run(reviewer.review_expression_once(result, task=task, manuals={}, model_config={},
        runner=run, deadline=time.monotonic()+60, usage_sink=accounted.append))
    assert record['status'] == 'reviewed'
    assert record['draft'] == original['envelope'] and task == task_before
    assert result['scene_patch'] == original['scene_patch']
    final = json.loads(result['envelope'])
    for key in ('used_facts', 'voice_reply', 'reply_language'):
        assert final[key] == json.loads(original['envelope'])[key]
    assert result['llm_api_calls'] == 3 and result['tool_call_count'] == 3
    assert accounted[-1]['usage']['prompt_tokens'] == 120


@pytest.mark.parametrize('response,required', [
    ('not json', None),
    (json.dumps({'edits': [edit('')]}), None),
    (json.dumps({'edits': []}), 3),
    (json.dumps({'edits': [], 'voice_reply': {}}), None),
    (json.dumps({'edits': [edit('好。我永远不走。')]}), None),
    (json.dumps({'edits': [edit(), edit()]}), None),
    (json.dumps({'edits': [{**edit(), 'original': '不存在的原文'}]}), None),
])
def test_invalid_review_retains_original_without_claiming_success(response, required):
    result = fixture()
    result['required_bubble_count'] = required
    original = result['envelope']
    async def run(*args, **kwargs):
        return {'finish_reason': 'completed', 'final_response': response, 'llm_api_calls': 1}
    record = asyncio.run(reviewer.review_expression_once(result, task={}, manuals={}, model_config={},
        runner=run, deadline=time.monotonic()+60))
    assert record['status'] == 'failed_original_retained'
    assert result['envelope'] == original and result['llm_api_calls'] == 3


def test_edits_preserve_untouched_details_and_allow_punctuation_only():
    source = json.loads(fixture()['envelope'])
    source['bubbles'][0]['parts'].append({'kind': 'action', 'text': '脸颊发烫，鬃毛垂下来'})
    before = deepcopy(source)
    updated, _ = reviewer.apply_edits(source, {'edits': [edit('好，你靠着就好。')]})
    assert updated['bubbles'][0]['parts'][1] == source['bubbles'][0]['parts'][1]
    assert source == before


def test_deadline_and_silent_reply_skip_without_model_call():
    async def run(*args, **kwargs):
        raise AssertionError('Must not call model')
    for result, deadline, status in [(fixture(), time.monotonic()-1, 'skipped_deadline'),
                                      ({'bubble_count': 0}, time.monotonic()+10, 'not_applicable')]:
        record = asyncio.run(reviewer.review_expression_once(result, task={}, manuals={}, model_config={},
            runner=run, deadline=deadline))
        assert record['status'] == status


def test_cancellation_propagates_and_accounts_partial_usage():
    result = fixture()
    accounted = []
    async def run(*args, **kwargs):
        error = asyncio.CancelledError()
        error.harness_usage = {'llm_api_calls': 1, 'usage': {'completion_tokens': 4}}
        raise error
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(reviewer.review_expression_once(result, task={}, manuals={}, model_config={},
            runner=run, deadline=time.monotonic()+60, usage_sink=accounted.append))
    assert accounted[-1]['llm_api_calls'] == 3 and accounted[-1]['incomplete']


def test_live_task_snapshot_uses_latest_input():
    s = session()
    first = payload('先说一句')
    s.transform(first, normal.SYSTEM)
    class Channel:
        async def prepare_input(self, rows):
            return [{'type': 'text', 'text': payload(rows[-1]['content'])}]
    channel = Channel()
    s.bind_live_input(channel)
    asyncio.run(channel.prepare_input([{'content': '现在不要说话'}]))
    assert s.task_snapshot['latest_user_message']['content'] == '现在不要说话'


def test_skill_entry_reviews_once_with_final_reads_and_preserved_primary_result():
    from test_autonomous_prompt_skills import skills
    calls = []
    usage = []

    async def runner(prompt, config, tools, **options):
        data = json.loads(prompt)
        calls.append(options['system_prompt'])
        if options['system_prompt'].startswith(reviewer.EXPRESSION_REVIEW_WORKFLOW):
            assert tools == {}
            assert data['sources']['latest_user_message']['content'] == '今天不想说话。'
            assert data['sources']['personal_preferences'] == '原样的个人偏好——保持。'
            assert data['sources']['character_reference_evidence'][-1]['matched']
            assert 'available_skills' not in data['sources']
            return {'finish_reason': 'completed', 'final_response': json.dumps({'edits': [edit()] if len(calls) == 2 else []}),
                    'llm_api_calls': 1, 'usage': {'prompt_tokens': 20}}
        await tools['load_chat_skill'].callback({'name': 'instant_messaging'})
        await tools['read_character_reference'].callback({'query': '青竹 竹林'})
        return {'finish_reason': 'completed'}

    async def actual(**kwargs):
        await kwargs['harness_runner'](payload('今天不想说话。'), {}, {}, system_prompt=normal.SYSTEM)
        return {**fixture(), 'scene_patch': {'changes': {}},
                'final_response': 'untouched initial model output'}

    result = asyncio.run(skills.run_skill_turn(actual, character_profile='青竹住在竹林',
        personal_preferences='原样的个人偏好——保持。', harness_runner=runner, model_config={},
        usage_sink=usage.append, deadline=time.monotonic()+60))
    assert len(calls) == 3
    assert result['prompt_skills']['expression_review']['status'] == 'reviewed'
    assert result['final_response'] == 'untouched initial model output'
    assert result['llm_api_calls'] == 4 and usage[-1]['usage']['prompt_tokens'] == 140


def test_review_recovers_once_and_keeps_failed_attempt_evidence_and_usage():
    result = fixture()
    calls = []
    async def run(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            error = TimeoutError()
            error.harness_usage = {'llm_api_calls': 1, 'usage': {'prompt_tokens': 10}}
            raise error
        return {'finish_reason': 'completed', 'final_response': '{"edits":[]}',
                'llm_api_calls': 1, 'usage': {'prompt_tokens': 20}}
    record = asyncio.run(reviewer.review_expression(result, task={}, manuals={}, model_config={},
        runner=run, deadline=time.monotonic()+60))
    assert record['status'] == 'reviewed' and len(record['passes']) == 3
    assert record['passes'][0]['status'] == 'failed_original_retained'
    assert record['passes'][0]['llm_api_calls'] == 1
    assert reviewer.EXPRESSION_FINAL_CHECK in calls[-1]['system_prompt']
    assert [c['reasoning_effort'] for c in calls] == ['low', 'low', 'low']
    assert all(c['max_tokens'] == 8192 and c['timeout_seconds'] <= 45 for c in calls)
    # Every pass uses the runtime's fixed Flash model and low reasoning.
    assert all('model' not in c for c in calls)
    assert result['llm_api_calls'] == 5 and result['usage']['prompt_tokens'] == 150


def test_repeated_invalid_edits_stop_after_three_attempts():
    result = fixture()
    original = result['envelope']
    async def run(*args, **kwargs):
        return {'finish_reason': 'completed', 'final_response': '{"edits":[{}]}', 'llm_api_calls': 1}
    record = asyncio.run(reviewer.review_expression(result, task={}, manuals={}, model_config={},
        runner=run, deadline=time.monotonic()+60))
    assert record['status'] == 'partial_review_original_or_prior_retained'
    assert len(record['passes']) == 3 and result['envelope'] == original
    assert result['llm_api_calls'] == 5
