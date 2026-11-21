import json

import pytest

from Backend.chat_modules.reply_json import close_complete_json


def test_recovers_container_suffix_without_changing_text():
    value = {'bubbles': [{'parts': [{'kind': 'thought', 'text': '我望着你，想着“{未来}”。'}]}]}
    raw = json.dumps(value, ensure_ascii=False)
    assert close_complete_json(raw) == raw
    assert json.loads(close_complete_json(raw[:-2])) == value


@pytest.mark.parametrize('raw', [
    '{"text":"半句话', '{"n":12', '{"ok":tru', '{"text":"ok",',
    '{"parts":[{"text":"ok"}] trailing', '{"text":"ok" "x":1}',
    '{"text":"ok"]', '{"text":', '{"text":"ok"}</tool>',
])
def test_ambiguous_or_invalid_json_is_not_guessed(raw):
    assert close_complete_json(raw) == raw


@pytest.mark.parametrize('template', [
    '```json\n%s\n```', '```JSON\r\n%s\r\n```', '```\n%s\n```',
    '~~~json\n%s\n~~~', '````json\n%s\n````',
    '```application/json\n%s\n```', '\ufeff%s',
    '以下是回复：\n```json\n%s\n```\n以上是结果。',
    '以下是回复：\n%s', '结果：%s\n已完成。',
])
def test_unwraps_common_model_output_without_changing_values(template):
    value = {'bubbles': [{'text': '引号"、括号{[]}、反斜线\\和```都属于原文。'}]}
    raw = json.dumps(value, ensure_ascii=False)
    assert close_complete_json(template % raw) == raw


@pytest.mark.parametrize('raw', [
    '```json\n{"x":1}\n```\n```json\n{"x":2}\n```',
    '结果：{"x":1} 或 {"x":2}',
    '结果：{"outer":{"x":1}',
    '```json\n{"text":"半句话\n```',
    '```json\n{"n":12\n```',
    '```python\n{"x":1}\n```',
    '<tool>{"x":1}</tool>',
    '结果：{"x":1,}',
    "结果：{'x': 1}",
])
def test_does_not_select_or_rewrite_ambiguous_payloads(raw):
    assert close_complete_json(raw) == raw


def test_wrapped_container_recovery_preserves_existing_contract():
    assert json.loads(close_complete_json('```json\n{"text":"完整文字"\n```')) == {
        'text': '完整文字'}


def test_arrays_are_recognized_but_delivery_schema_still_rejects_them():
    from Backend.chat_modules.autonomous_contracts import delivery_metadata

    normalized = close_complete_json('```json\n[{"text":"完整文字"}]\n```')
    assert json.loads(normalized) == [{'text': '完整文字'}]
    with pytest.raises(ValueError, match='JSON object'):
        delivery_metadata(normalized)
