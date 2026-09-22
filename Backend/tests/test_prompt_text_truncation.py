"""语音风格提示（emotion_prompt / instruct）的裁剪必须停在词边界。

回归背景：`voice_reply.emotion_prompt` 之前按字符硬切 100 个字符，英文提示会被切成
`...warm and a little hesitant, trailin` 这种半个单词，并原样送进语音服务。
"""
import importlib
import json
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = "prompt_text_limits_under_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "chat_modules")]
sys.modules[PACKAGE] = package
text_limits = importlib.import_module(PACKAGE + ".text_limits")
delivery = importlib.import_module(PACKAGE + ".autonomous_delivery")

SPEECH_TEXT = "我把灯调暗一点再唱。"
LONG_PROMPT = (
    "Speak slowly and gently in a soft, shy, almost whispering voice, "
    "warm and a little hesitant, trailing off at the end."
)


def test_character_cut_scenario_no_longer_ends_inside_a_word():
    assert LONG_PROMPT[:100].endswith("trailin")  # 旧行为：被切成半个单词

    trimmed = text_limits.truncate_prompt_text(LONG_PROMPT, delivery.EMOTION_PROMPT_MAX_CHARS)

    assert 0 < len(trimmed) <= delivery.EMOTION_PROMPT_MAX_CHARS
    assert LONG_PROMPT.startswith(trimmed)
    assert trimmed.endswith("warm and a little hesitant")
    assert not trimmed.endswith("trailin")


@pytest.mark.parametrize("limit", range(20, 121, 7))
def test_truncation_never_lands_inside_a_word(limit):
    trimmed = text_limits.truncate_prompt_text(LONG_PROMPT, limit)

    assert 0 < len(trimmed) <= limit
    assert LONG_PROMPT.startswith(trimmed)
    if len(trimmed) == len(LONG_PROMPT):
        return  # 未触发裁剪，无需检查边界
    following = LONG_PROMPT[len(trimmed)]
    assert not re.match(r"[A-Za-z0-9]", following), f"cut inside a word: {trimmed!r}"


APOSTROPHE_PROMPT = (
    "It's warm and playful, but don't shout; they're listening, and it isn't loud."
)


def _ends_mid_word(text, trimmed):
    """裁剪结果之后紧跟的字符仍属于同一个词时返回 True（词内撇号同样算）。"""
    if not trimmed or len(trimmed) >= len(text):
        return False
    following = text[len(trimmed)]
    if re.match(r"[A-Za-z0-9]", following):
        return True
    return (following in "'’" and len(text) > len(trimmed) + 1
            and text[len(trimmed) + 1].isalnum())


@pytest.mark.parametrize("limit", range(1, len(APOSTROPHE_PROMPT) + 2))
def test_apostrophe_words_are_never_cut_in_half(limit):
    trimmed = text_limits.truncate_prompt_text(APOSTROPHE_PROMPT, limit)

    assert 0 < len(trimmed) <= limit
    assert APOSTROPHE_PROMPT.startswith(trimmed)
    # 只有“整段可用前缀本身就是一个词”时才无法退到词边界，其余情况都不许停在词中。
    window = APOSTROPHE_PROMPT[:limit].rstrip()
    if _ends_mid_word(APOSTROPHE_PROMPT, trimmed):
        assert not re.search(r"\s", window), f"avoidable mid-word cut: {trimmed!r}"


def test_cut_before_an_apostrophe_drops_the_partial_word():
    # 旧行为：只看下一个字符是不是字母数字，撇号被当成安全边界，留下 "Please don"。
    assert "Please don't shout"[:10] == "Please don"

    assert text_limits.truncate_prompt_text("Please don't shout", 10) == "Please"
    # 弯撇号（模型输出的 `don’t`）与直撇号同源，同样不能留下半个词。
    assert text_limits.truncate_prompt_text("Please don’t shout", 10) == "Please"
    # 截断点正好落在撇号之后，残缺的仍是 `don't` 这个词。
    assert text_limits.truncate_prompt_text("Please don't shout", 11) == "Please"


def test_complete_words_ending_with_an_apostrophe_are_kept():
    # `cats'` 本身是完整的词，不能因为末尾是撇号就被当成半个词丢掉。
    assert text_limits.truncate_prompt_text("the cats' toys are here", 9) == "the cats"
    # 落单的撇号不是完整的词，必须一并清掉。
    assert text_limits.truncate_prompt_text("it's fine now", 3) == "it"


def test_cut_after_a_space_keeps_the_complete_last_word():
    # 旧行为：window 先 rstrip()，却仍用原始 prefix_chars 判断词边界，误删完整的 `softly`。
    assert text_limits.truncate_prompt_text("Speak softly today", 13) == "Speak softly"
    # 上限正好落在词尾、或落在下一个词的词头，结果都应是同一个完整前缀。
    assert text_limits.truncate_prompt_text("Speak softly today", 12) == "Speak softly"
    assert text_limits.truncate_prompt_text("Speak softly today", 14) == "Speak softly"
    assert text_limits.truncate_prompt_text("Speak softly today", 15) == "Speak softly"
    assert text_limits.truncate_prompt_text("Speak softly today", 16) == "Speak softly"
    # 直到最后一个词开始为止，结果都停在同一个完整前缀。
    assert text_limits.truncate_prompt_text("Speak softly today", 17) == "Speak softly"
    # 整段可用前缀只有一个词时无法退到词边界，只能按字符裁剪且不留尾随空白。
    assert text_limits.truncate_prompt_text("Softly", 4) == "Soft"


def test_short_prompt_is_returned_unchanged():
    assert text_limits.truncate_prompt_text("Calm.", delivery.EMOTION_PROMPT_MAX_CHARS) == "Calm."
    assert text_limits.truncate_prompt_text("保持原音色，语速自然", 220) == "保持原音色，语速自然"


def test_empty_and_non_positive_limits_are_safe():
    assert text_limits.truncate_prompt_text(None, 100) == ""
    assert text_limits.truncate_prompt_text("   ", 100) == ""
    assert text_limits.truncate_prompt_text(LONG_PROMPT, 0) == ""


def test_cjk_prompt_breaks_on_punctuation_before_falling_back_to_characters():
    cjk = "保持原音色，能量稍高，语速稍快，停顿短促，收尾有力，不要改变声线粗细"
    trimmed = text_limits.truncate_prompt_text(cjk, 20)
    assert trimmed == "保持原音色，能量稍高，语速稍快"
    # 整段没有任何标点时只能字符裁剪，但结果仍必须非空且不超限。
    dense = "温柔自然" * 20
    fallback = text_limits.truncate_prompt_text(dense, 25)
    assert 0 < len(fallback) <= 25


def test_sibling_220_char_limit_also_avoids_mid_word_cuts():
    long_cjk_free = (LONG_PROMPT + " ") * 3
    trimmed = text_limits.truncate_prompt_text(long_cjk_free, 220)
    assert 0 < len(trimmed) <= 220
    assert long_cjk_free.startswith(trimmed)
    assert not re.match(r"[A-Za-z0-9]", long_cjk_free[len(trimmed)])


def _delivery_request(emotion_prompt: str):
    envelope = {
        "voice_reply": {"enabled": True, "emotion_prompt": emotion_prompt, "reason": "voice turn"},
        "reply_language": {"language": "Chinese", "reason": "沿用中文"},
        "bubbles": [{"index": 1, "type": "text", "purpose": "answer_user",
                     "parts": [{"kind": "speech", "text": SPEECH_TEXT}]}],
    }
    request = types.SimpleNamespace(voice_enabled=True, _normal_planner_result={})
    delivery.configure_delivery(request, {"final_response": json.dumps(envelope, ensure_ascii=False),
                                         "envelope": json.dumps(envelope, ensure_ascii=False)})
    return request


def test_delivery_attaches_a_complete_style_instruction():
    request = _delivery_request(LONG_PROMPT)

    sentences = request._normal_voice_sentences_by_text_index[0]
    assert [item["text"] for item in sentences] == [SPEECH_TEXT]
    emotion = sentences[0]["emotion_prompt"]
    assert emotion == "Speak slowly and gently in a soft, shy, almost whispering voice, warm and a little hesitant"


def test_delivery_keeps_short_style_instruction_and_default():
    assert _delivery_request("Calm.")._normal_voice_sentences_by_text_index[0][0]["emotion_prompt"] == "Calm."
    assert _delivery_request("")._normal_voice_sentences_by_text_index[0][0]["emotion_prompt"] == (
        "Warm, relaxed, conversational."
    )
