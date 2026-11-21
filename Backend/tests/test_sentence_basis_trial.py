import importlib.util
import json
from pathlib import Path
import sys

folder = Path(__file__).parents[1] / 'Agent-Test'
sys.path.insert(0, str(folder))
spec = importlib.util.spec_from_file_location('sentence_basis_trial', folder / 'run_sentence_basis_trial.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


def annotated(source_id='U'):
    return {'bubbles': [{'sentences': [{'kind': 'speech', 'text': 'visible sentence',
        'purpose': 'respond', 'basis': [{'source_id': source_id, 'support': 'current input'}],
        'contribution': 'new response'}]}]}


def test_reference_validation_does_not_rewrite_visible_content():
    content = json.dumps(annotated())
    result = trial.validate(content, 'annotated', {'U': {'text': 'current'}})
    assert result['valid'] and result['bubbles'] == ['visible sentence']
    assert json.loads(content) == annotated()


def test_unknown_reference_is_rejected_even_when_explanation_is_present():
    result = trial.validate(json.dumps(annotated('invented')), 'annotated', {'U': {}})
    assert not result['valid']
    assert any('source does not exist' in e for e in result['errors'])


def test_autonomous_expression_is_allowed_but_missing_annotations_are_not():
    assert trial.validate(json.dumps(annotated('autonomous')), 'annotated', {})['valid']
    value = annotated()
    del value['bubbles'][0]['sentences'][0]['contribution']
    assert not trial.validate(json.dumps(value), 'annotated', {'U': {}})['valid']


def test_json_control_does_not_require_annotations():
    value = {'bubbles': [{'sentences': [{'kind': 'thought', 'text': 'visible thought'}]}]}
    result = trial.validate(json.dumps(value), 'json', {})
    assert result['valid'] and result['bubbles'] == ['(visible thought)']


def test_multiple_sentences_in_one_unit_are_reported_separately_from_json_validity():
    value = annotated()
    value['bubbles'][0]['sentences'][0]['text'] = '第一句。第二句。'
    result = trial.validate(json.dumps(value), 'annotated', {'U': {}})
    assert result['valid']
    assert result['granularity_warnings']
