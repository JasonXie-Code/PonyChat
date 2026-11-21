import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location('tested_probe_report',
    Path(__file__).parents[1] / 'Agent-Test' / 'write_reply_probe_report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def event(sequence, stage, data):
    return {'sequence': sequence, 'stage': stage, 'data': data}


def response(text):
    return {'final_response': json.dumps({'bubbles': [{'parts': [{'kind': 'speech', 'text': text}]}]})}


def test_bubble_source_distinguishes_first_draft_from_format_repair():
    row = {'turn': 2, 'user_message': '当前问题', 'delivered_messages': ['修复后新增尾句！'],
        'runtime_probe': {'events': [
            event(1, 'POST_SKILL_ADAPTER_REQUEST', {'prompt': json.dumps({'latest_user_message': '当前问题'})}),
            event(2, 'RAW_HARNESS_RETURN', response('首次正文')),
            event(3, 'POST_SKILL_ADAPTER_REQUEST', {'prompt': json.dumps({
                'latest_user_message': '当前问题', 'previous_attempt': {}, 'completion_feedback': '字段缺失'})}),
            event(4, 'RAW_HARNESS_RETURN', response('修复后新增尾句'))]}}
    summary = report.summarize(row)
    assert summary['bubbles'][0]['first_seen_attempt'] == 2
    assert summary['bubbles'][0]['observed_origins'][0]['raw_return_event'] == 4
    assert summary['requests'][1]['completion_feedback'] == '字段缺失'


def test_malformed_output_and_missing_matches_remain_explicitly_unresolved():
    for raw in ('invalid', '[]', '{"bubbles": [{}]}', '{"bubbles": [{"parts": 1}]}'):
        assert report.authored_texts(raw) == []
    summary = report.summarize({'turn': 1, 'user_message': '你好',
                               'delivered_messages': ['未匹配文本'], 'runtime_probe': {}})
    assert summary['bubbles'][0]['unresolved_origin'] is True
    assert summary['bubbles'][0]['first_seen_attempt'] is None


def test_task_selection_ignores_non_task_text_and_does_not_invent_pending_fields():
    prompt = [{'type': 'text', 'text': '普通正文'}, {'type': 'text', 'text': json.dumps({
        'latest_user_message': {'content': 'hi'}, 'recent_raw_messages': [], 'some_fact': 3})}]
    assert report.task_data(prompt)['some_fact'] == 3
    row = {'turn': 1, 'user_message': 'hi', 'delivered_messages': [], 'runtime_probe': {
        'events': [event(1, 'POST_SKILL_ADAPTER_REQUEST', {'prompt': prompt})]}}
    assert report.summarize(row)['requests'][0]['pending_fields'] == {}


def test_failed_request_without_return_does_not_shift_later_bubble_provenance():
    row = {'turn': 1, 'user_message': 'hi', 'delivered_messages': ['成功台词'], 'runtime_probe': {'events': [
        event(1, 'POST_SKILL_ADAPTER_REQUEST', {'prompt': '{}'}),
        event(2, 'POST_SKILL_ADAPTER_REQUEST', {'prompt': '{}'}),
        event(3, 'RAW_HARNESS_RETURN', response('成功台词'))]}}
    assert report.summarize(row)['bubbles'][0]['first_seen_attempt'] == 2


def test_wire_summary_checks_actual_sdk_system_and_user_against_application():
    row = {'turn': 1, 'user_message': 'hi', 'delivered_messages': [], 'runtime_probe': {'events': [
        event(1, 'POST_SKILL_ADAPTER_REQUEST', {'system_prompt': 'app system', 'prompt': 'app user'}),
        event(2, 'MODEL_WIRE_REQUEST', {'model': 'deepseek-flash', 'reasoning_effort': 'low',
             'messages': [{'role': 'system', 'content': 'app system'}, {'role': 'user', 'content': 'app user'}]}),
        event(3, 'MODEL_WIRE_REQUEST', {'messages': [{'role': 'system', 'content': 'extra SDK instructions'}]})]}}
    wire = report.summarize(row)['model_wire_requests']
    assert wire[0]['system_exactly_matches_application'] and wire[0]['user_exactly_matches_application']
    assert wire[1]['system_exactly_matches_application'] is False


def test_report_reads_only_canonical_progress_and_ignores_incomplete_final_files(tmp_path):
    (tmp_path / 'lotus_blossom.json').write_text(json.dumps({
        'character_id': 'lotus_blossom', 'character_name': '芙蓉', 'turns': []}), encoding='utf-8')
    (tmp_path / 'lotus_blossom.final.json').write_text('', encoding='utf-8')
    (tmp_path / 'unrelated.json').write_text('not valid JSON', encoding='utf-8')
    report.write(tmp_path)
    assert json.loads((tmp_path / '回复来源摘要.json').read_text(encoding='utf-8')) == {'lotus_blossom': []}
