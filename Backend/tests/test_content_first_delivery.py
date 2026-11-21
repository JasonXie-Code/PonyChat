"""Transport filling preserves every authored part and business decision."""
import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location('content_first_candidate',
    Path(__file__).parents[1] / 'Agent-Test/content_first_delivery.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_fill_indices_without_rewriting_parts_or_business_metadata():
    value = {'bubbles': [{'parts': [{'kind': 'speech', 'text': '那我这点沉稳保不住了'}]},
                         {'parts': [{'kind': 'thought', 'text': '手有余香是原样引用'}]}],
             'voice_reply': {'enabled': False}, 'reply_language': {'language': 'Chinese'},
             'used_facts': [], 'scene_patch': {'reset': False, 'changes': {}},
             'followup_decision': {'enabled': False, 'reason': 'unchanged'}}
    raw = json.dumps(value, ensure_ascii=False)
    before = {'finish_reason': 'completed', 'final_response': raw, 'llm_api_calls': 1}
    after = module.normalize_author_delivery(before)
    result = json.loads(after['final_response'])
    assert before['final_response'] == raw and after['agent_authored_response'] == raw
    assert result['bubble_count'] == 2
    assert [b['index'] for b in result['bubbles']] == [1, 2]
    assert [b['parts'] for b in result['bubbles']] == [b['parts'] for b in value['bubbles']]
    assert {k: v for k, v in result.items() if k not in {'bubbles', 'bubble_count'}} == {
        k: v for k, v in value.items() if k != 'bubbles'}
    assert after['llm_api_calls'] == 1 and after['transport_normalization']['model_calls'] == 0


def test_malformed_reply_and_explicit_wrong_indices_still_reach_existing_validator():
    malformed = {'finish_reason': 'completed', 'final_response': 'not json'}
    assert module.normalize_author_delivery(malformed) is malformed
    raw = json.dumps({'bubbles': [{'index': 9, 'parts': [{'kind': 'speech', 'text': 'hello'}]}],
                      'bubble_count': 5})
    result = json.loads(module.normalize_author_delivery({'finish_reason': 'completed', 'final_response': raw})['final_response'])
    assert result['bubbles'][0]['index'] == 9 and result['bubble_count'] == 5


def test_zero_bubbles_keeps_silence_decision():
    value = {'bubbles': [], 'no_reply_reason': '当前沉默'}
    result = module.normalize_author_delivery({'finish_reason': 'completed', 'final_response': json.dumps(value)})
    assert json.loads(result['final_response']) == {**value, 'bubble_count': 0}
