"""波浪号「～」声音记号：默认提示词规则，不含用户可切换档位。"""
import re

from Backend.chat_modules.Prompts import (
    CHAT_SKILL_TEXTS,
    SKILL_WHEN,
    speech,
    voice_reply,
)


def test_speech_skill_authorises_the_tilde_with_bounded_conditions():
    assert "轻量声音记号" in speech
    assert "不接在句末标点之后" in speech
    assert "严肃说明、冲突、道歉、悲伤和事实纠正时不用" in speech
    assert "只在speech中使用" in speech


def test_sound_mark_skill_is_discoverable_for_affectionate_dialogue():
    assert '亲昵、撒娇或玩笑台词也读取' in SKILL_WHEN['speech']


def test_voice_reply_binds_the_sound_mark_to_emotion_prompt():
    assert "emotion_prompt是整轮共用的简短英文语调指导" in voice_reply
    assert "不承诺实际音频精确复现每个符号" in voice_reply


def test_skill_rule_numbers_stay_continuous_after_the_new_rules():
    for name, text in CHAT_SKILL_TEXTS.items():
        numbers = [int(match.group(1)) for line in text.splitlines()
                   if (match := re.match(r"^(\d+)\.\s", line))]
        assert numbers == list(range(1, len(numbers) + 1)), (name, numbers)


def test_new_rules_do_not_embed_examples_in_skill_text():
    for name, text in CHAT_SKILL_TEXTS.items():
        assert not re.search(r"例如|比如|譬如|示例", text), name
