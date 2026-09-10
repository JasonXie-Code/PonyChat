"""Shared normal-chat parts renderer: the server, not the model, adds brackets.

Shared by Agent replies and the
existing pipeline use exactly the same validation and visible formatting.
"""
from __future__ import annotations

import re
from typing import Any


_PART_BOUNDARY_PUNCTUATION = frozenset("，。！？；：、,.!?;:…—–-")
_CLOSING_QUOTES = "\"'”’」』》】"


def _join_normal_part_text(left: str, right: str) -> str:
    """Join semantic parts without losing a boundary or duplicating punctuation.

    Parts are complete semantic fragments, not streaming/token chunks. Keep
    supplied punctuation; otherwise separate CJK fragments with a comma and
    space-delimited text with a space. Never guess boundaries inside a part.
    """
    left, right = left.rstrip(), right.lstrip()
    if not left or not right:
        return left or right
    tail = left.rstrip(_CLOSING_QUOTES)[-1:]
    head = right.lstrip("\"'“‘「『《【")[:1]
    cjk = bool(re.search(r"[\u3400-\u9fff\uf900-\ufaff]", tail + head))
    if right[0] in _PART_BOUNDARY_PUNCTUATION:
        separator = ""
    elif tail in _PART_BOUNDARY_PUNCTUATION:
        separator = "" if cjk else " "
    else:
        separator = "，" if cjk else " "
    return left + separator + right


def _merge_adjacent_normal_bracket_descriptions(text: str) -> str:
    """Merge immediately adjacent full-bracket description fragments in one bubble."""
    merged = str(text or "")
    if not merged:
        return merged
    previous = None
    while previous != merged:
        previous = merged
        merged = re.sub(r"（([^（）]*)）[ \t\f\v]*（([^（）]*)）",
                        lambda m: "（" + _join_normal_part_text(m[1], m[2]) + "）", merged)
        merged = re.sub(r"\(([^()]*)\)[ \t\f\v]*\(([^()]*)\)",
                        lambda m: "(" + _join_normal_part_text(m[1], m[2]) + ")", merged)
    return merged


_BRACKET_CHAR_RE = re.compile(r"[（）()]")


def _normal_stage3_clean_field_text(value: Any) -> str:
    return re.sub(r"[\r\n]+", " ", str(value or "")).strip()


def _normal_stage3_strip_bracket_terminal_period(text: str) -> str:
    return re.sub(r"。+$", "", str(text or "").rstrip()).rstrip()


def _normal_stage3_strip_terminal_speech_period(text: str) -> str:
    return re.sub(r"。+$", "", str(text or "").rstrip()).rstrip()


_NORMAL_STAGE3_PART_KINDS: set[str] = {
    "speech",
    "action",
    "thought",
    "body_state",
    "expression",
    "gaze",
    "voice_state",
    "scene",
    "visual",
    "sensory",
    "emotion",
}


_NORMAL_STAGE3_BRACKET_PART_KINDS = _NORMAL_STAGE3_PART_KINDS - {"speech"}


def _normal_stage3_render_parts_bubble(item: dict, pos: int) -> tuple[str, dict[str, Any], str]:
    parts = item.get("parts")
    if not isinstance(parts, list) or not parts:
        return "", {}, f"第 {pos} 个 bubble 必须包含非空 parts 数组；旧 content/bracket_content/speech_content 格式不再接受。"

    groups: list[tuple[bool, str]] = []
    kind_counts: dict[str, int] = {}
    speech_chars = 0
    bracket_chars = 0
    for part_pos, part in enumerate(parts, start=1):
        if not isinstance(part, dict):
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}] 必须是 object，包含 kind/text。"
        kind = str(part.get("kind") or "").strip().lower()
        if kind not in _NORMAL_STAGE3_PART_KINDS:
            allowed = "/".join(sorted(_NORMAL_STAGE3_PART_KINDS))
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}].kind 必须是 {allowed} 之一，当前为 {kind or '空'}。"
        raw_text = str(part.get("text") or "")
        if "\n" in raw_text or "\r" in raw_text:
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}].text 内部含换行；每个 part 文本内部不得换行。"
        text = _normal_stage3_clean_field_text(raw_text)
        if not text:
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}].text 不能为空。"
        if _BRACKET_CHAR_RE.search(text):
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}].text 不得包含括号；后端会根据 kind 统一添加全角括号。"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        speech = kind == "speech"
        if not speech and not _normal_stage3_strip_bracket_terminal_period(text):
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}].text 去掉括号内句号后不能为空。"
        if groups and groups[-1][0] == speech:
            groups[-1] = (speech, _join_normal_part_text(groups[-1][1], text))
        else:
            groups.append((speech, text))

    rendered_parts: list[str] = []
    for speech, text in groups:
        if speech:
            rendered_parts.append(text)
            speech_chars += len(text)
        else:
            # Strip only at the end of a merged description. Periods between
            # its constituent parts are now sentence punctuation, not terminal.
            text = _normal_stage3_strip_bracket_terminal_period(text)
            if not text:
                return "", {}, f"第 {pos} 个 bubble 的描写去掉括号内句号后不能为空。"
            rendered_parts.append(f"（{text}）")
            bracket_chars += len(text)

    rendered = "".join(rendered_parts).strip()
    rendered = _normal_stage3_strip_terminal_speech_period(rendered)
    if not rendered:
        return "", {}, f"第 {pos} 个 bubble.parts 渲染后为空。"
    return rendered, {
        "render_mode": "parts",
        "part_count": len(parts),
        "part_kinds": kind_counts,
        "speech_chars": speech_chars,
        "bracket_chars": bracket_chars,
    }, ""
