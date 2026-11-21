"""Structured reply regression cases for the shared normal-chat renderer."""
import importlib
import json
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).parents[1]
PACKAGE = "autonomous_reply_under_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "chat_modules")]
sys.modules[PACKAGE] = package
reply = importlib.import_module(PACKAGE + ".autonomous_reply")
parts_module = importlib.import_module(PACKAGE + ".normal_parts")


def document(parts):
    return {"bubble_count": 1, "bubbles": [{"index": 1, "type": "text", "purpose": "reply", "parts": parts}], "used_facts": []}


def render(parts):
    raw, count = reply.reply_envelope(json.dumps(document(parts), ensure_ascii=False))
    assert count == 1
    return reply.render_envelope(json.loads(raw))


def test_mixed_parts_preserve_order_and_backend_adds_brackets():
    assert render([
        {"kind": "speech", "text": "等我一下。"},
        {"kind": "action", "text": "我把小凳子搬到彩带下面。"},
        {"kind": "speech", "text": "这样就够得到啦。"},
    ]) == "等我一下。（我把小凳子搬到彩带下面）这样就够得到啦"


@pytest.mark.parametrize("kind", sorted(parts_module._NORMAL_STAGE3_BRACKET_PART_KINDS))
def test_all_description_kinds_are_bracketed(kind):
    assert render([{"kind": kind, "text": "我有自己的感受。"}]) == "（我有自己的感受）"


@pytest.mark.parametrize("bad", ["（我点头）", "(我点头)", "第一行\n第二行", "", "<think>private</think>"])
def test_model_cannot_supply_brackets_lines_or_internal_text(bad):
    with pytest.raises(ValueError):
        render([{"kind": "action", "text": bad}])


def test_unknown_kind_and_plain_text_are_rejected_instead_of_becoming_speech():
    with pytest.raises(ValueError):
        render([{"kind": "system_instruction", "text": "internal"}])
    with pytest.raises(ValueError):
        reply.reply_envelope("台词（我点头）")


def test_six_bubbles_are_preserved_instead_of_folded():
    data = document([{"kind": "speech", "text": "第一句。第二句。"}])
    data["bubbles"] = [dict(data["bubbles"][0], index=i) for i in range(1, 7)]
    data["bubble_count"] = 6
    raw, count = reply.reply_envelope(json.dumps(data))
    assert count == 6
    assert reply.render_envelope(json.loads(raw)).split("\n\n") == ["第一句。第二句"] * 6
    data["bubble_count"] = True
    with pytest.raises(ValueError):
        reply.reply_envelope(json.dumps(data))


def test_markdown_is_cleaned_inside_typed_parts_without_affecting_question_marks():
    assert render([{"kind": "speech", "text": "你喜欢**无糖茉莉花茶**，对吗？"}]) == "你喜欢无糖茉莉花茶，对吗？"
    assert render([{"kind": "speech", "text": "好呀！"}]) == "好呀！"
    assert render([{"kind": "speech", "text": "版本 5.6.17，2 * 3 = 6。"}]) == "版本 5.6.17，2 * 3 = 6"


@pytest.mark.parametrize(('kind', 'left', 'right'), [
    ('speech', '尾巴都要翘上天啦', '不过只能亲一下哦'),
    ('thought', '连蹄子都软了', '我明明天天见你'),
    ('thought', '那片脆脆的反而成了小事', '我偷偷在想'),
])
def test_logged_adjacent_parts_keep_a_visible_boundary(kind, left, right):
    actual = render([{'kind': kind, 'text': left}, {'kind': kind, 'text': right}])
    expected = left + '，' + right
    assert actual == (expected if kind == 'speech' else '（' + expected + '）')


@pytest.mark.parametrize('mark', ['。', '，', '！', '？', '；', '……'])
def test_description_merge_preserves_supplied_internal_punctuation(mark):
    assert render([{'kind': 'action', 'text': '我停下脚步' + mark},
                   {'kind': 'thought', 'text': '我想起了约定。'}]) == '（我停下脚步' + mark + '我想起了约定）'


def test_three_adjacent_descriptions_merge_once_without_dropping_sentences():
    assert render([{'kind': 'action', 'text': '我站起来。'},
                   {'kind': 'gaze', 'text': '我看向窗外。'},
                   {'kind': 'thought', 'text': '我想出去走走。'}]) == '（我站起来。我看向窗外。我想出去走走）'


def test_adjacent_speech_keeps_existing_punctuation_and_leading_punctuation():
    assert render([{'kind': 'speech', 'text': '好呀！'},
                   {'kind': 'speech', 'text': '我们走吧。'}]) == '好呀！我们走吧'
    assert render([{'kind': 'speech', 'text': '好呀'},
                   {'kind': 'speech', 'text': '，我们走吧。'}]) == '好呀，我们走吧'


def test_english_parts_keep_word_spacing_without_chinese_punctuation():
    assert render([{'kind': 'speech', 'text': 'All right.'},
                   {'kind': 'speech', 'text': 'Let us go.'}]) == 'All right. Let us go.'
    assert render([{'kind': 'thought', 'text': 'I pause'},
                   {'kind': 'thought', 'text': 'and look outside'}]) == '（I pause and look outside）'


def test_legacy_bracket_merge_keeps_the_same_fragment_boundaries():
    merge = parts_module._merge_adjacent_normal_bracket_descriptions
    assert merge('（我站起来。）（我望向窗外）（我想出门）') == '（我站起来。我望向窗外，我想出门）'
    assert merge('(I pause.)(I look outside.)') == '(I pause. I look outside.)'
    assert merge('（我站起来）好呀（我看向你）') == '（我站起来）好呀（我看向你）'


def test_fragment_join_does_not_guess_punctuation_inside_a_single_part():
    assert render([{'kind': 'speech', 'text': '天啦不过我明明天天见你'}]) == '天啦不过我明明天天见你'


def test_empty_description_is_rejected_before_group_merging():
    _, _, error = parts_module._normal_stage3_render_parts_bubble({'parts': [
        {'kind': 'thought', 'text': '。'}, {'kind': 'action', 'text': '我站起来'}]}, 1)
    assert error
