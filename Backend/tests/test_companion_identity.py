from Backend.companion_identity import (
    apply_personality_style,
    character_identity_summary,
    identity_session_key,
    normalize_personality_style,
)
from pathlib import Path


def test_roles_have_separate_session_and_memory_scope_keys():
    assert identity_session_key("jason", "twilight") != identity_session_key("jason", "rainbow")


def test_source_conversations_do_not_share_transient_context():
    qq_alice = identity_session_key("jason", "twilight", "qq-private:alice-hash")
    qq_bob = identity_session_key("jason", "twilight", "qq-private:bob-hash")
    screen_companion = identity_session_key("jason", "twilight")

    assert qq_alice != qq_bob
    assert qq_alice != screen_companion
    assert identity_session_key("jason", "twilight", "") == screen_companion


def test_style_changes_expression_without_replacing_canonical_persona():
    prompt = apply_personality_style("你是暮光闪闪。记得用户喜欢读书。", "lively")
    assert "你是暮光闪闪" in prompt
    assert "用户喜欢读书" in prompt
    assert "更活泼" in prompt
    assert normalize_personality_style("unknown") == "canonical"


def test_character_catalog_does_not_expose_full_prompt():
    summary = character_identity_summary("twilight", {
        "name": "暮光闪闪",
        "profilePersonality": "认真、好学",
        "profileIntro": "来自小马谷",
        "prompt": "不应返回的完整设定",
    })
    assert summary["name"] == "暮光闪闪"
    assert summary["personality"] == "认真、好学"
    assert "prompt" not in summary


def test_identity_switch_waits_for_shared_memory_persistence():
    source = (
        Path(__file__).parents[1]
        / "routes" / "companion_chat_impl" / "message_routes.py"
    ).read_text(encoding="utf-8")
    assert "memory_persisted = await _write_companion_memory(" in source
    assert "asyncio.create_task(_write_companion_memory(" not in source
    assert '"memory_persisted": memory_persisted' in source
