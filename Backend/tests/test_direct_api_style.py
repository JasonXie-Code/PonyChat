import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('direct_api_style', Path(__file__).parents[1] / 'Agent-Test/run_direct_api_style.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def fixture_row():
    task = {'character_profile': 'complete profile', 'non_speech_perspective_contract': 'perspective',
            'server_loaded_core_manuals': [{'skill': k, 'instructions': k} for k in
                ('reply_expression', 'character_body', 'evidence')],
            'recent_raw_messages': [{'role': 'user', 'content': 'previous user'},
                                    {'role': 'assistant', 'content': 'previous reply'}],
            'latest_user_message': {'content': 'current question'}}
    wire = {'model': 'deepseek-flash', 'messages': [{'role': 'user', 'content': json.dumps(task)}],
            'tools': [{'type': 'function'}], 'stream': True, 'stream_options': {'include_usage': True},
            'dsh_plugin_packages': {'version': 1}, 'thinking': '[redacted]', 'reasoning_effort': 'low'}
    return {'runtime_probe': {'events': [
        {'stage': 'POST_SKILL_ADAPTER_REQUEST', 'data': {'prompt': json.dumps(task)}},
        {'stage': 'MODEL_WIRE_REQUEST', 'data': wire}]}}


def test_plain_request_preserves_profile_history_current_question_and_low():
    payload, task = runner.make_request(fixture_row(), 'plain')
    assert payload['messages'][1:-1] == task['recent_raw_messages']
    assert payload['messages'][-1] == {'role': 'user', 'content': 'current question'}
    assert task['character_profile'] in payload['messages'][0]['content']
    assert payload['reasoning_effort'] == 'low'
    assert 'tools' not in payload


def test_exact_wire_preserves_all_fields_except_restoring_redacted_thinking():
    row = fixture_row()
    payload, _ = runner.make_request(row, 'wire-exact')
    original = row['runtime_probe']['events'][1]['data']
    assert payload == {**original, 'thinking': {'type': 'enabled'}}
    assert original['thinking'] == '[redacted]'


def test_saved_response_omits_private_reasoning_without_changing_visible_content():
    original = {'choices': [{'message': {'content': 'visible', 'reasoning_content': 'private',
                                        'tool_calls': []}}]}
    saved = runner.public_response(original)
    assert saved['choices'][0]['message'] == {'content': 'visible', 'tool_calls': []}
    assert 'reasoning_content' in original['choices'][0]['message']
