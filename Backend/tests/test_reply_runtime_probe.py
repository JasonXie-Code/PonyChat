import asyncio
import importlib.util
from pathlib import Path
import types
import pytest
import json


path = Path(__file__).parents[1] / 'Agent-Test' / 'reply_runtime_probe.py'
spec = importlib.util.spec_from_file_location('tested_reply_probe', path)
probe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_module)


def test_probe_is_passive_and_preserves_visible_character_thought():
    calls = []

    async def write(stage, data, *, params=None):
        calls.append((stage, data, params))
        return 'original result'

    module = types.SimpleNamespace(write=write, snapshot=lambda value: value)
    original = probe_module.install_logging_probe(module)

    async def run():
        probe, token = probe_module.start_probe()
        payload = {'parts': [{'kind': 'thought', 'text': '阿林来了，我有点开心。'}],
                   'reasoning_content': 'private hidden text'}
        assert await module.write('AGENT_RUN_RESPONSE', payload, params={'run_id': 'r1'}) == 'original result'
        probe_module.stop_probe(token)
        export = probe.export()
        assert export['extra_model_calls'] == 0
        assert export['events'][0]['data']['parts'] == payload['parts']
        assert 'private hidden text' not in str(export)
        assert calls == [('AGENT_RUN_RESPONSE', payload, {'run_id': 'r1'})]

    asyncio.run(run())
    module.write = original


def test_concurrent_and_nested_requests_are_isolated():
    async def child(name):
        probe, token = probe_module.start_probe()
        await asyncio.sleep(0)
        probe_module.current_probe().record('request', {'name': name})
        probe_module.stop_probe(token)
        return probe.export()

    async def run():
        parent, token = probe_module.start_probe()
        outputs = await asyncio.gather(child('a'), child('b'))
        assert probe_module.current_probe() is parent
        probe_module.stop_probe(token)
        assert [o['events'][0]['data']['name'] for o in outputs] == ['a', 'b']
        assert parent.events == []
        assert probe_module.current_probe() is None

    asyncio.run(run())


def test_capture_redacts_credentials_and_bounds_events_without_altering_source():
    probe = probe_module.ReplyProbe()
    value = {'api_key': 'secret-one', 'nested': {'Authorization': 'Bearer secret-two'},
             'text': 'Bearer secret-three', 'type': 'image', 'data': 'base64-secret'}
    probe.record('x', value)
    assert 'secret-' not in str(probe.export())
    assert value['api_key'] == 'secret-one'
    for _ in range(5001):
        probe.record('x', {})
    assert len(probe.events) == 5000 and probe.dropped == 2


def test_capture_failure_does_not_break_original_logging():
    calls = []

    async def write(*args, **kwargs):
        calls.append(True)

    def broken_snapshot(value):
        raise ValueError('broken capture')

    module = types.SimpleNamespace(write=write, snapshot=broken_snapshot)
    probe_module.install_logging_probe(module)

    async def run():
        probe, token = probe_module.start_probe()
        await module.write('x', {})
        probe_module.stop_probe(token)
        assert probe.capture_errors == 1 and calls == [True]

    asyncio.run(run())


def test_disabled_probe_does_not_record_and_preserves_logging_error():
    async def write(*args, **kwargs):
        raise RuntimeError('original failure')

    module = types.SimpleNamespace(write=write, snapshot=lambda value: value)
    probe_module.install_logging_probe(module)

    async def run():
        try:
            await module.write('x', {})
        except RuntimeError as error:
            assert str(error) == 'original failure'
        else:
            raise AssertionError('original logging error must remain observable')
        assert probe_module.current_probe() is None

    asyncio.run(run())


def test_nullable_schema_is_captured_and_uncopyable_payload_never_blocks_reply():
    probe = probe_module.ReplyProbe()
    probe.request('test', {'tool': types.SimpleNamespace(description='test',
        parameters={'type': ['object', 'null']})}, {})
    assert probe.events[0]['data']['tools'][0]['parameters']['type'] == ['object', 'null']
    cycle = {}
    cycle['itself'] = cycle
    probe.record('bad diagnostic', cycle)
    assert probe.capture_errors == 1


def test_controlled_duty_ablation_changes_only_the_known_sentence():
    original = probe_module.AGENT_DUTY + '\n其他身体、事实、工具和历史规则保持。'
    changed = probe_module.writing_first_system(original)
    assert original.replace(probe_module.AGENT_DUTY, '') == changed.replace(probe_module.WRITING_DUTY, '')
    for unknown in ('unknown prompt', original + probe_module.AGENT_DUTY):
        with pytest.raises(ValueError):
            probe_module.writing_first_system(unknown)


def test_direct_text_experiment_rejects_needed_tools_and_preserves_low():
    task = {'interaction_context': {'selected_this_turn': 'instant_messaging'},
            'latest_user_message': {'content': '会紧张吗？'}, 'required_tools_before_reply': []}
    original = {'system_prompt': 'existing rules', 'reasoning_effort': 'low'}
    options = probe_module.direct_text_options(json.dumps(task), original)
    assert options['force_no_tools'] and options['delivery_only'] and options['max_tool_calls'] == 0
    assert options['delivery_reasoning_effort'] == 'low' and original['system_prompt'] == 'existing rules'
    for alteration in ({'required_tools_before_reply': ['search_memory']},
                       {'current_images_available': True},
                       {'latest_user_message': {'content': '请记住这件事'}},
                       {'interaction_context': {'selected_this_turn': 'virtual_roleplay'}}):
        with pytest.raises(ValueError):
            probe_module.direct_text_options(json.dumps({**task, **alteration}), original)


def test_role_voice_replaces_only_operator_identity_and_keeps_effective_contracts():
    rest = '完整身体合同\n完整事实合同\n最后JSON合同'
    original = probe_module.AGENT_DUTY + '\n可用工具以本轮为准\nread_character_reference读取资料\n' + rest
    changed = probe_module.role_voice_system(original)
    assert changed == probe_module.ROLE_VOICE + '\n' + rest
    with pytest.raises(ValueError):
        probe_module.role_voice_system('unrecognized root')
