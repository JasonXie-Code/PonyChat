from __future__ import annotations

from Backend.routes import minigames


def test_xiangqi_reply_style_state_marks_repeated_phrases_and_arc():
    state = minigames._xiangqi_reply_style_state(
        history=[
            {
                "actor": "character",
                "reply_text": "哇，你又吃掉我一个卒！那我让车挪一下，看看能不能碰到你的炮～",
            },
            {
                "actor": "user",
                "is_capture": True,
                "captured_piece": "炮",
                "captured_piece_kind": "cannon",
            },
            {
                "actor": "character",
                "reply_text": "哇，你的车又逼过来啦！那我先躲开再说～",
            },
        ],
        dialogue_history=[
            {"role": "user", "text": "手下留情啊"},
            {"role": "character", "text": "嘿嘿，那我看看能不能再将你一军～"},
        ],
    )

    assert "哇" in state["overused_phrases"]
    assert "嘿嘿" in state["overused_phrases"]
    assert "那我" in state["overused_phrases"]
    assert "看看能不能" in state["overused_phrases"]
    assert "将你一军" in state["overused_phrases"]
    assert "炮" in state["emotional_arc"]["recent_character_losses"]
    assert "不得再出现 overused_phrases" in state["next_reply_guidance"]


def test_xiangqi_execute_normalize_preserves_model_repeated_terms():
    normalized = minigames._normalize_execute_result(
        {
            "action": "chat_only",
            "近期重复词": ["嘿嘿", "那我", "嘿嘿", "特别特别特别特别长的口癖"],
            "character_reply": {"reaction_text": "嘿嘿，我看一下。"},
        }
    )

    assert normalized["近期重复词"][:2] == ["嘿嘿", "那我"]
    assert normalized["近期重复词"].count("嘿嘿") == 1
    assert all(len(term) <= 19 for term in normalized["近期重复词"])
