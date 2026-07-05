from __future__ import annotations

from Backend.galgame.repetition_guard import (
    build_repetition_avoidance_hint,
    check_signature_repetition,
    collect_recent_signature_counts,
    extract_repetition_signatures,
)


def test_extracts_generic_body_action_signatures() -> None:
    text = "云宝的翅根轻轻抖了一下，耳尖泛红。她攥紧枕头。"

    signatures = extract_repetition_signatures(text)

    assert "动作:翅根+抖" in signatures
    assert "动作:耳尖+红" in signatures
    assert "动作:枕头+攥" in signatures


def test_collects_repeated_signatures_across_characters() -> None:
    prev_turns = [
        {"body_state": "她的手指攥紧衣角，视线躲开。", "response": ""},
        {"body_state": "她手指再次攥住袖口，声音很轻。", "response": ""},
        {"body_state": "他肩膀发颤，嘴角苦笑。", "response": ""},
    ]

    counts = collect_recent_signature_counts(prev_turns)

    assert counts["动作:手指+攥"] == 2
    assert counts["动作:视线+躲"] == 1


def test_builds_avoidance_hint_for_hot_signatures() -> None:
    prev_turns = [
        {"body_state": "翅根轻轻抖动，耳尖泛红。"},
        {"response": "她翅根又颤了一下，低声说话。"},
    ]

    hint = build_repetition_avoidance_hint(prev_turns, step_name="body_state")

    assert "动作:翅根+抖" in hint
    assert "不要继续播放同一微动作" in hint


def test_blocks_same_round_response_repeating_body_state() -> None:
    body_state_sigs = extract_repetition_signatures("她的翅根轻轻抖了一下，耳尖泛红。")
    candidate = "她翅根又抖了一下，声音闷闷地说：“别看。”"

    repeated = check_signature_repetition(candidate, body_state_sigs)

    assert repeated == "动作:翅根+抖"


def test_allows_new_action_when_emotion_state_continues() -> None:
    blocked = extract_repetition_signatures("她的手指攥紧衣角，视线躲开。")
    candidate = "她把杯子推近一点，低声说：“先喝点水。”"

    repeated = check_signature_repetition(candidate, blocked)

    assert repeated == ""
