"""Keep conversational rules in skills without imposing reply-shape gates."""
import asyncio
import json

import pytest

from test_autonomous_prompt_skills import normal, payload, session
from prompt_skills_under_test.Prompts import CHAT_SKILL_TEXTS, reply_expression


def test_style_is_in_skills_on_initial_delivery_and_recovery_with_preferences_intact():
    preference = "不要问我问题；我喜欢详细的说明。"
    s = session(preference=preference)
    for extra in ({}, {"completion_feedback": "补齐语言对象"}):
        prompt, system = s.transform(payload("你喜欢什么书？", **extra), normal.SYSTEM)
        assert reply_expression not in system
        assert s.catalog["reply_expression"][1] == reply_expression
        assert "缺失信息确实影响下一步时再提问" not in system
        assert preference not in system
        assert preference in s.catalog["preferences"][1]
        assert json.loads(prompt)["latest_user_message"]["content"] == "你喜欢什么书？"
        assert "不代写用户反应" not in system
        assert "不代写用户反应" in CHAT_SKILL_TEXTS["interaction_reply"]
        assert "reply_language" not in system
        assert "reply_language" in s.catalog["delivery"][1]


@pytest.mark.parametrize("reply", ["我喜欢历史书。", "我喜欢历史书。你最近在读哪本？"])
def test_style_does_not_gate_or_rewrite_questions_or_statements(reply):
    s = session()
    raw = json.dumps({"bubble_count": 1, "bubbles": [{"index": 1, "type": "text",
        "purpose": "answer_user", "parts": [{"kind": "speech", "text": reply}]}]}, ensure_ascii=False)

    async def runner(*args, **kwargs):
        assert reply_expression not in kwargs["system_prompt"]
        await args[2]["load_chat_skill"].callback({"name": "instant_messaging"})
        bundle = await args[2]["load_chat_skill"].callback({"name": "reply_expression"})
        assert reply_expression in bundle["instructions"]
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
    assert "所有非speech片段固定从当前角色的第一人称视角呈现" in CHAT_SKILL_TEXTS["reply_perspective"]
    assert "speech中的角色自称不受本条限制" in CHAT_SKILL_TEXTS["reply_perspective"]
    assert "用户明确要求重复的动作可以自然延续" in CHAT_SKILL_TEXTS["interaction_reply"]
    assert "只有真正的第三者使用姓名或第三人称" in CHAT_SKILL_TEXTS["reply_perspective"]
