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
