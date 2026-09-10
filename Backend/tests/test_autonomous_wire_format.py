"""Strict compatibility and lossless prompt compaction boundary tests."""
import copy
import asyncio
import importlib
import json
from pathlib import Path
import sys
import types

import pytest

PACKAGE = "wire_format_under_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).parents[1] / "chat_modules")]
sys.modules[PACKAGE] = package
wire = importlib.import_module(PACKAGE + ".autonomous_wire_format")
reply = importlib.import_module(PACKAGE + ".autonomous_reply")
skills = importlib.import_module(PACKAGE + ".autonomous_prompt_skills")
normal = importlib.import_module(PACKAGE + ".autonomous_normal")


def envelope(facts):
    return {"bubble_count": 1, "bubbles": [{"index": 1, "type": "text", "purpose": "reply",
        "parts": [{"kind": "speech", "text": "I remember your tea preference!"}]}],
        "voice_reply": {"enabled": True, "reason": "continue", "emotion_prompt": "Warm"},
        "reply_language": {"language": "English", "reason": "continue"}, "used_facts": facts}


def test_known_fact_record_matches_string_envelope_without_mutating_raw():
    facts = ["unchanged", {"type": "context", "content": "  mint tea  "}]
    original = envelope(facts)
    raw = json.dumps(original)
    actual, count = reply.reply_envelope(raw)
    expected, _ = reply.reply_envelope(json.dumps(envelope(["unchanged", "  mint tea  "])))
    assert actual == expected and count == 1
    parsed = json.loads(actual)
    for key in ("bubbles", "voice_reply", "reply_language"):
        assert parsed[key] == original[key]
    assert json.loads(raw) == original


def test_full_turn_accepts_legacy_facts_in_one_call_and_retains_raw_audit():
    calls = []
    raw = json.dumps(envelope([{"type": "context", "content": "mint tea"}]))

    async def runner(prompt, config, tools, **options):
        calls.append(prompt)
        return {"finish_reason": "completed", "final_response": raw,
                "usage": {"total_tokens": 123}, "llm_api_calls": 1}

    result = asyncio.run(normal.run_autonomous_turn(
        messages=[{"role": "user", "content": "Hello", "message_id": "source-a"}],
        character_profile="温和的成年独角兽", environment="", model_config={}, harness_runner=runner))
    assert len(calls) == 1 and result["output_format_repairs"] == 0
    assert result["final_response"] == raw
    assert json.loads(result["envelope"])["bubbles"] == json.loads(raw)["bubbles"]
    assert json.loads(result["envelope"])["used_facts"] == ["mint tea"]


@pytest.mark.parametrize("fact", [None, 1, [], {}, {"content": "x"}, {"type": "context"},
    {"type": "context", "content": "x", "source": "unknown"},
    {"type": "", "content": "x"}, {"type": 1, "content": "x"},
    {"type": "context", "content": " "}, {"type": "context", "content": {"x": 1}}])
def test_unknown_fact_shapes_still_fail(fact):
    with pytest.raises(ValueError, match="used_facts"):
        reply.reply_envelope(json.dumps(envelope([fact])))


def test_fact_compatibility_does_not_bypass_reply_validation():
    data = envelope([{"type": "context", "content": "tea"}])
    data["bubbles"][0]["parts"][0]["text"] = "first\nsecond"
    with pytest.raises(ValueError):
        reply.reply_envelope(json.dumps(data))
    with pytest.raises(ValueError):
        reply.reply_envelope("plain text")


def prompt_fixture():
    state = {"relationship_stage": "friends", "character_intimacy_style": "balanced",
             "requested_escalation": "none", "user_pressure_level": "low"}
    message = {"message_id": "source-a", "role": "user", "content": "Remember mint tea",
               "timestamp": 1788716299862, "sequence_number": 29}
    return {"recent_raw_messages": [message], "latest_user_message": copy.deepcopy(message),
            "current_user_batch": [copy.deepcopy(message)],
            "source_message_times": {"source-a": {"occurred_at": "2026-09-06T17:38:19.862000+00:00"}},
            "relationship_state": state,
            "relationship_context": {**state, "relationship_page": "Exact source text", "updated_at_ms": 10},
            "relationship_execution_contract": {**state, "fixed_rule": "unchanged rule"}}


def test_time_and_state_are_reconstructible_without_changing_sources():
    original = prompt_fixture()
    compact = wire.compact_task_data(copy.deepcopy(original))
    assert original["recent_raw_messages"][0]["timestamp"] == 1788716299862
    for key in ("recent_raw_messages", "current_user_batch"):
        assert compact[key][0] == {k: v for k, v in original[key][0].items() if k != "timestamp"}
    assert compact["source_message_times"] == original["source_message_times"]
    for name in ("relationship_context", "relationship_execution_contract"):
        item = dict(compact[name])
        assert item.pop("relationship_state_ref") == "relationship_state"
        item.update(compact["relationship_state"])
        assert item == original[name]
    assert wire.compact_task_data(copy.deepcopy(compact)) == compact


@pytest.mark.parametrize("time", ["2026-09-06T17:38:19.862", "2026-09-06T17:38:19.862001+00:00",
    "2026-09-06T17:38:19.863+00:00", "invalid", None])
def test_ambiguous_times_are_not_removed(time):
    original = prompt_fixture()
    original["source_message_times"]["source-a"]["occurred_at"] = time
    assert wire.compact_task_data(original)["latest_user_message"]["timestamp"] == 1788716299862


def test_timezone_offset_preserves_instant_and_conflicting_relationship_is_retained():
    data = prompt_fixture()
    data["source_message_times"]["source-a"]["occurred_at"] = "2026-09-07T01:38:19.862+08:00"
    data["relationship_context"]["relationship_stage"] = "unknown"
    before = copy.deepcopy(data["relationship_context"])
    result = wire.compact_task_data(data)
    assert "timestamp" not in result["latest_user_message"]
    assert result["relationship_context"] == before


@pytest.mark.parametrize("image", [False, True])
def test_actual_transform_preserves_media_history_language_and_memory_sources(image):
    data = prompt_fixture()
    data["environment"] = 'previous_reply_language=English; voice_reply=true'
    raw = json.dumps(data, ensure_ascii=False)
    source = [{"type": "text", "text": raw}, {"type": "image", "data": "synthetic", "mimeType": "image/png"}] if image else raw
    before = copy.deepcopy(source)
    session = skills.PromptSkills(profile="角色名称：青竹", preferences="", business=types.SimpleNamespace(guidance=""),
                                 normal_module=normal, home_profile="名称：青竹\n简介：爱读书")
    result, system = session.transform(source, normal.SYSTEM)
    encoded = result[0]["text"] if image else result
    parsed = json.loads(encoded)
    assert encoded == json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    assert parsed["environment"] == data["environment"]
    assert parsed["source_message_times"] == data["source_message_times"]
    assert "timestamp" not in parsed["latest_user_message"]
    assert "字符串数组" in system
    assert source == before
    if image:
        assert result[1] == source[1]
