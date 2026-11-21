"""记忆碎片正文必须收束在40字以内（提示词约束 + 写入前兜底）。"""
from __future__ import annotations

import asyncio

import pytest

from Backend.memory import extractor
from Backend.memory.extractor import (
    MAX_FRAGMENT_CHARS,
    _EXTRACT_SYSTEM_PROMPT,
    limit_fragment_content,
)


def test_limit_is_40_chars():
    assert MAX_FRAGMENT_CHARS == 40


def test_short_fragment_is_untouched():
    text = "我今天和Jason去公园散步"
    assert limit_fragment_content(text) == text


def test_trim_stops_at_the_last_clause_boundary_inside_the_limit():
    text = "我陪石青派去矿山看设备，路上她说起姐姐的事，后来我们一起回了派家屋子"
    result = limit_fragment_content(text, limit=20)
    assert result == "我陪石青派去矿山看设备"
    assert len(result) <= 20


@pytest.mark.parametrize('length', [41, 60, 200, 4000])
def test_overlong_fragment_never_exceeds_the_limit(length):
    text = "我" * length
    assert len(limit_fragment_content(text)) <= MAX_FRAGMENT_CHARS


def test_boundary_trim_keeps_the_fact_head_and_drops_the_tail():
    text = "，".join(["我在图书馆借了星图册",
                    "后来和紫悦核对过两遍",
                    "最后放回靠窗的书架",
                    "傍晚的时候外面下起了很大的雨",
                    "我们只好留在屋里继续看书"])
    assert len(text) > MAX_FRAGMENT_CHARS
    result = limit_fragment_content(text, limit=MAX_FRAGMENT_CHARS)
    assert len(result) <= MAX_FRAGMENT_CHARS
    assert result.startswith("我在图书馆借了星图册")
    assert "我们只好留在屋里继续看书" not in result


def test_whitespace_only_content_collapses_to_empty():
    assert limit_fragment_content("   ") == ""


def test_extract_prompt_requires_40_char_fragments():
    assert "15~40字" in _EXTRACT_SYSTEM_PROMPT
    assert "最多不超过40字" in _EXTRACT_SYSTEM_PROMPT
    assert "15~80字" not in _EXTRACT_SYSTEM_PROMPT


def _stub_extract_environment(monkeypatch, saved, model_content):
    async def fake_call_llm_payload(payload, model, **kwargs):
        return type('Result', (), {'text': model_content})()

    async def fake_load_user_identity(username):
        return {"display_name": "Jason"}

    async def fake_build_memory_identity_block(username, character_id):
        return ""

    async def fake_load_character_identity(username, character_id):
        return {"name": "柔柔"}

    async def fake_add_memory(**kwargs):
        saved.append(kwargs)
        return len(saved)

    monkeypatch.setattr(extractor.model_manager, "get_model_for_task", lambda task: {"model_name": "stub", "name": "stub"})
    monkeypatch.setattr(extractor, "load_user_identity", fake_load_user_identity)
    monkeypatch.setattr(extractor, "build_memory_identity_block", fake_build_memory_identity_block)
    monkeypatch.setattr(extractor, "load_character_identity", fake_load_character_identity)
    monkeypatch.setattr(extractor, "add_memory", fake_add_memory)
    monkeypatch.setattr(extractor, "apply_llm_task_payload_config", lambda payload, task: None)
    monkeypatch.setattr(extractor, "call_llm_payload", fake_call_llm_payload)


def test_extracted_overlong_content_is_stored_within_the_limit(monkeypatch):
    saved = []
    overlong = "我" * 30 + "，" + "他" * 40 + "。"
    _stub_extract_environment(
        monkeypatch,
        saved,
        '[{"type": "episode", "content": "%s", "importance": 6}]' % overlong,
    )
    written = asyncio.run(extractor.do_extract(
        "Jason", "fluttershy__u_1", [{"role": "user", "content": "问"}],
    ))
    assert written == 1
    assert len(saved[0]["content"]) <= MAX_FRAGMENT_CHARS
    assert saved[0]["content"] == limit_fragment_content(overlong)


def test_extracted_short_content_is_stored_verbatim(monkeypatch):
    saved = []
    _stub_extract_environment(
        monkeypatch,
        saved,
        '[{"type": "preference", "content": "Jason说他喜欢薄荷茶", "importance": 7}]',
    )
    assert asyncio.run(extractor.do_extract(
        "Jason", "fluttershy__u_1", [{"role": "user", "content": "我喜欢薄荷茶"}],
    )) == 1
    # 用户名按既有规则归一为 {{USER}} 占位符，长度不受影响
    assert saved[0]["content"] == "{{USER}}说他喜欢薄荷茶"
