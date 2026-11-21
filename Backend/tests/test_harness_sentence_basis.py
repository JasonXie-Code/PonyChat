import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('harness_sentence_basis', Path(__file__).parents[1] / 'Agent-Test/harness_sentence_basis.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


def test_annotation_preserves_original_task_and_harness_options():
    task = {'character_profile': 'profile', 'latest_user_message': {'content': 'input'},
        'visible_punctuation_policy': {'dash_allowed': False}, 'scene_patch': {'reset': False},
        'recent_raw_messages': [{'role': 'assistant', 'content': 'history'}]}
    options = {'system_prompt': 'all production rules', 'reasoning_effort': 'low', 'max_tool_calls': None}
    prompt, updated, sources = trial.annotate_request(json.dumps(task), options)
    decoded = json.loads(prompt)
    assert decoded.pop('sentence_source_index') == sources
    assert decoded == task
    assert updated['reasoning_effort'] == 'low' and updated['max_tool_calls'] is None
    assert updated['system_prompt'].startswith(options['system_prompt'])
    assert options['system_prompt'] == 'all production rules'


def test_trial_refuses_missing_default_punctuation_contract():
    with pytest.raises(ValueError, match='no-dash'):
        trial.annotate_request('{}', {'system_prompt': 'rules'})


def test_annotations_do_not_make_a_bad_source_or_dash_pass():
    unit = {'kind': 'speech', 'text': '有—破折号。', 'purpose': 'respond',
        'basis': [{'source_id': 'invented', 'support': 'claim'}], 'contribution': 'claim'}
    result = trial.inspect_response(json.dumps({'bubbles': [{'parts': [unit]}]}), {'U': {}})
    assert not result['valid']
    assert any('invalid source' in e for e in result['errors'])
    assert any('prohibited dash' in e for e in result['errors'])
    assert result['sentences'][0]['text'] == unit['text']


def test_compact_reuses_material_and_preserves_production_rules():
    task = {'character_profile': 'first\n\nthird', 'latest_user_message': {'content': 'input'},
        'visible_punctuation_policy': {'dash_allowed': False},
        'recent_raw_messages': [{'role': 'assistant', 'content': 'history'}]}
    options = {'system_prompt': 'production rules', 'reasoning_effort': 'low', 'max_tool_calls': None}
    prompt, updated, sources = trial.annotate_request(json.dumps(task), options, compact=True)
    decoded = json.loads(prompt)
    assert 'sentence_source_index' not in decoded
    assert decoded.pop('sentence_source_locator')['U'] == 'latest_user_message.content'
    assert decoded == task
    assert sources['P3']['text'] == 'third' and 'P2' not in sources
    assert {k: v for k, v in updated.items() if k != 'system_prompt'} == {k: v for k, v in options.items() if k != 'system_prompt'}
    assert updated['system_prompt'].startswith(options['system_prompt'])
    unit = {'kind': 'speech', 'text': '回应。', 'why': '接住当前示好', 'refs': ['U', 'P3']}
    raw = json.dumps({'bubbles': [{'parts': [unit]}]})
    assert trial.inspect_response(raw, sources, compact=True)['valid']
    unit.update(text='回应。重复。', refs=['P2'], why='长' * 25)
    result = trial.inspect_response(json.dumps({'bubbles': [{'parts': [unit]}]}), sources, compact=True)
    assert not result['valid']
    assert any('invalid source' in e for e in result['errors'])
    assert any('multiple sentences' in e for e in result['errors'])
    assert any('exceeds' in e for e in result['errors'])


def test_focused_schema_is_only_a_hint_and_keeps_scene_state():
    task = {'character_profile': 'profile', 'latest_user_message': {'content': 'input'},
        'visible_punctuation_policy': {'dash_allowed': False}, 'current_scene': {'known': 'unchanged'}}
    options = {'system_prompt': 'production rules', 'reasoning_effort': 'low'}
    prompt, updated, _ = trial.annotate_request(json.dumps(task), options, compact=True, focused=True)
    decoded = json.loads(prompt)
    assert decoded['current_scene'] == task['current_scene']
    assert 'scene_patch' not in decoded
    assert len(decoded['sentence_delivery_schema_hint']['initial_scene_fields']) == 6
    assert updated['system_prompt'].startswith(options['system_prompt'])
    with pytest.raises(ValueError, match='requires compact'):
        trial.annotate_request(json.dumps(task), options, focused=True)
