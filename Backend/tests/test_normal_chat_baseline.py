"""The baseline must not mistake a valid envelope for a correct Agent turn."""
import sys
from pathlib import Path


OPS = Path(__file__).resolve().parents[2] / 'scripts' / 'ops'
sys.path.insert(0, str(OPS))
from evaluate_normal_chat_baseline import SCENARIOS, score  # noqa: E402


def fixture():
    groups = []
    for name, _, mode, _, turns in SCENARIOS:
        groups.append({'name': name, 'turns': [{
            'user': turns[0][0], 'expected_paths': turns[0][1],
            'reply': '好。', 'envelope': {'bubble_count': 1, 'bubbles': [{}]},
            'attempts': [{}], 'format_repairs': 0, 'automatic_retries': 0,
            'prompt_skills': {'interaction_mode': mode, 'expression_paths': turns[0][1]},
        }]})
    return {'scenarios': groups, 'revision': 'test', 'model': 'fake',
            'production_writes': False, 'source_hashes': {}}


def test_score_separates_mechanical_pass_from_semantic_review():
    result = score(fixture())
    assert result['mechanical_pass_count'] == len(SCENARIOS)
    assert result['semantic_review_complete'] is False
    assert all(value is None for row in result['cases']
               for value in row['semantic_review'].values())


def test_score_rejects_wrong_mode_or_missing_expression_path():
    report = fixture()
    report['scenarios'][0]['turns'][0]['prompt_skills']['interaction_mode'] = 'virtual_roleplay'
    report['scenarios'][-1]['turns'][0]['prompt_skills']['expression_paths'] = ['conversation_reply']
    result = score(report)
    assert result['mechanical_pass_count'] == len(SCENARIOS) - 2
    assert result['cases'][0]['checks']['mode'] is False
    assert result['cases'][-1]['checks']['expression_paths'] is False


def test_score_rejects_missing_delivery_even_with_complete_skills():
    report = fixture()
    report['scenarios'][0]['turns'][0]['reply'] = ''
    report['scenarios'][1]['turns'][0]['envelope']['bubble_count'] = 2
    result = score(report)
    assert result['mechanical_pass_count'] == len(SCENARIOS) - 2


def test_score_flags_pony_hands_and_format_repair():
    report = fixture()
    report['scenarios'][0]['turns'][0]['reply'] = '我用手指拿起胡萝卜。'
    report['scenarios'][1]['turns'][0]['format_repairs'] = 1
    result = score(report)
    assert result['mechanical_pass_count'] == len(SCENARIOS) - 2
    assert result['cases'][0]['checks']['equine_anatomy'] is False
    assert result['cases'][1]['checks']['single_delivery_attempt'] is False
