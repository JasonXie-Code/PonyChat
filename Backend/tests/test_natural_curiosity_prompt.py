"""Keep conversational curiosity resident without imposing reply-shape gates."""
import asyncio
import json

import pytest

from test_autonomous_prompt_skills import normal, payload, session
from prompt_skills_under_test.autonomous_direct import NATURAL_CHARACTER_STYLE, TURN_EXPRESSION_REVIEW


def test_style_is_in_skills_on_initial_delivery_and_recovery_with_preferences_intact():
    preference = "不要问我问题；我喜欢详细的说明。"
    s = session(preference=preference)
    for extra in ({}, {"completion_feedback": "补齐语言对象"}):
        prompt, system = s.transform(payload("你喜欢什么书？", **extra), normal.SYSTEM)
        assert NATURAL_CHARACTER_STYLE not in system
        assert s.catalog["reply_expression"][1].count(NATURAL_CHARACTER_STYLE) == 1
        assert TURN_EXPRESSION_REVIEW not in system
        assert "缺失信息确实影响下一步时再提问" not in system
        assert preference not in system
        assert preference in s.catalog["preferences"][1]
        assert json.loads(prompt)["latest_user_message"]["content"] == "你喜欢什么书？"
        assert "不替用户" in s.catalog["reply_expression"][1]
        assert "reply_language" in system


@pytest.mark.parametrize("reply", ["我喜欢历史书。", "我喜欢历史书。你最近在读哪本？"])
def test_style_does_not_gate_or_rewrite_questions_or_statements(reply):
    s = session()
    raw = json.dumps({"bubble_count": 1, "bubbles": [{"index": 1, "type": "text",
        "purpose": "answer_user", "parts": [{"kind": "speech", "text": reply}]}]}, ensure_ascii=False)

    async def runner(*args, **kwargs):
        assert NATURAL_CHARACTER_STYLE not in kwargs["system_prompt"]
        await args[2]["load_chat_skill"].callback({"name": "instant_messaging"})
        bundle = await args[2]["load_chat_skill"].callback({"name": "reply_expression"})
        assert NATURAL_CHARACTER_STYLE in bundle["instructions"]
        return {"finish_reason": "completed", "final_response": raw}

    result = asyncio.run(s.runner(runner)(payload(), {}, {}, system_prompt=normal.SYSTEM))
    assert result["final_response"] == raw
    assert "completion_error" not in result


def test_expression_review_keeps_scoped_exceptions_and_does_not_rewrite_history():
    s = session()
    original = "她挥了挥蹄子。"
    source = json.loads(payload("请用第三人称再写一次挥蹄子的动作。"))
    source["recent_raw_messages"] = [{"role": "assistant", "content": original}]
    prompt, system = s.transform(json.dumps(source, ensure_ascii=False), normal.SYSTEM)
    assert json.loads(prompt)["recent_raw_messages"][0]["content"] == original
    assert "用户本轮指定第三人称叙事时按指定格式写" in s.catalog["reply_expression"][1]
    assert "用户明确要求重复的动作可以自然延续" in s.catalog["reply_expression"][1]
    assert "真正的第三者和原话引用保持各自主体" in s.catalog["reply_expression"][1]
