from __future__ import annotations

import json
import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from Backend.chat_modules import opening_greeting
from Backend.chat_modules.opening_greeting import OpeningGreetingPolicy, _fallback_bubbles


def test_fallback_bubbles_start_with_common_greeting():
    policy = OpeningGreetingPolicy(True, 3, "test", "")
    for name in ("碧琪", "珍奇", "紫悦", "苹果嘉儿", "云宝"):
        bubbles = _fallback_bubbles({"name": name}, policy)
        assert bubbles
        assert bubbles[0] == "很高兴认识你！"


def test_opening_step0_model_decides_even_for_official_names(monkeypatch):
    async def fake_call_llm(*_args, **_kwargs):
        return SimpleNamespace(
            text=json.dumps(
                {
                    "should_send": False,
                    "bubble_count": 0,
                    "reason": "model_decided_quiet_opening",
                    "style_hint": "",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(opening_greeting, "call_llm", fake_call_llm)
    monkeypatch.setattr(
        opening_greeting.model_manager,
        "get_model_for_task",
        lambda _task: {"id": "test-model"},
    )

    policy = asyncio.run(
        opening_greeting.analyze_opening_greeting_policy(
            "tester",
            "twilight",
            char={"name": "紫悦", "prompt": "理性友好，朋友包括柔柔和碧琪。"},
        )
    )

    assert policy.should_send is False
    assert policy.bubble_count == 0
    assert policy.reason == "model_decided_quiet_opening"


def test_opening_generation_accepts_content_only_bubble_json(monkeypatch):
    async def fake_build_user_context(*_args, **_kwargs):
        return ""

    async def fake_call_llm(*_args, **_kwargs):
        return SimpleNamespace(
            text=json.dumps(
                {
                    "bubbles": [
                        {"content": "嗨，新朋友！"},
                        {"content": "今天要不要聊点开心的？"},
                    ]
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(opening_greeting, "build_user_context", fake_build_user_context)
    monkeypatch.setattr(opening_greeting, "call_llm", fake_call_llm)
    monkeypatch.setattr(
        opening_greeting.model_manager,
        "get_model_for_task",
        lambda _task: {"id": "test-model"},
    )

    bubbles = asyncio.run(
        opening_greeting.generate_opening_greeting_bubbles(
            "tester",
            "pinkie",
            char={"name": "碧琪", "prompt": "热情活泼。"},
            policy=OpeningGreetingPolicy(True, 2, "test", "热情但自然。"),
        )
    )

    assert bubbles == ["嗨，新朋友！", "今天要不要聊点开心的？"]


def test_opening_generation_uses_current_parts_schema_for_single_bubble(monkeypatch):
    captured = {}

    async def fake_build_user_context(*_args, **_kwargs):
        return ""

    async def fake_call_llm(messages, *_args, **_kwargs):
        captured["system"] = messages[0]["content"]
        return SimpleNamespace(
            text=json.dumps(
                {
                    "bubble_count": 1,
                    "bubbles": [
                        {
                            "index": 1,
                            "type": "text",
                            "parts": [{"kind": "speech", "text": "你好，我是紫悦。很高兴认识你！"}],
                            "purpose": "opening_greeting",
                        }
                    ],
                    "used_facts": [],
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(opening_greeting, "build_user_context", fake_build_user_context)
    monkeypatch.setattr(opening_greeting, "call_llm", fake_call_llm)
    monkeypatch.setattr(
        opening_greeting.model_manager,
        "get_model_for_task",
        lambda _task: {"id": "test-model"},
    )

    bubbles = asyncio.run(
        opening_greeting.generate_opening_greeting_bubbles(
            "tester",
            "twilight",
            char={"name": "紫悦", "prompt": "理性友好。"},
            policy=OpeningGreetingPolicy(True, 1, "test", "理性、友好。"),
        )
    )

    assert bubbles == ["你好，我是紫悦。很高兴认识你！"]
    assert '"bubble_count": 1' in captured["system"]
    assert '"index": 2' not in captured["system"]
    assert '"parts"' in captured["system"]


def test_opening_greeting_notify_enqueues_chat_complete(monkeypatch):
    captured = []

    async def fake_message_ids(conversation_id):
        assert conversation_id == "conv_opening"
        return ["opening_1", "opening_2"]

    async def fake_enqueue_chat_complete(**kwargs):
        captured.append(kwargs)

    from Backend import delivery_outbox

    monkeypatch.setattr(opening_greeting, "_opening_message_ids", fake_message_ids)
    monkeypatch.setattr(delivery_outbox, "enqueue_chat_complete", fake_enqueue_chat_complete)

    ok = asyncio.run(
        opening_greeting._notify_opening_greeting_created(
            "tester",
            "char_opening",
            "conv_opening",
            ["第一条", "第二条"],
        )
    )

    assert ok is True
    assert len(captured) == 2
    assert [item["username"] for item in captured] == ["tester", "tester"]
    assert [item["character_id"] for item in captured] == ["char_opening", "char_opening"]
    assert [item["conversation_id"] for item in captured] == ["conv_opening", "conv_opening"]
    assert [item["message_id"] for item in captured] == ["opening_1", "opening_2"]
    assert [item["preview"] for item in captured] == ["第一条", "第二条"]
    assert [item["mode"] for item in captured] == ["normal", "normal"]
    assert [item["message_count"] for item in captured] == [1, 1]
    assert [item["assistant_message_ids"] for item in captured] == [["opening_1"], ["opening_2"]]
