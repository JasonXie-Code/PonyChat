from __future__ import annotations

import re
from typing import Any


def split_assistant_paragraphs(text: str) -> list[str]:
    clean = (text or "").strip()
    if not clean:
        return []
    parts = [p.strip() for p in re.split(r"\n+", clean) if p.strip()]
    return parts or [clean]


def is_asset_only_reply_sequence_with_assets(
    reply_sequence: list[dict[str, Any]] | None,
    *,
    attachment_by_request_id: dict[str, dict[str, Any]] | None = None,
    fallback_attachments: list[dict[str, Any]] | None = None,
) -> bool:
    sequence = [x for x in (reply_sequence or []) if isinstance(x, dict)]
    if not sequence:
        return False
    if any(str(item.get("type") or "").strip().lower() != "asset" for item in sequence):
        return False

    attachments = attachment_by_request_id or {}
    if attachments:
        return any(isinstance(value, dict) and value for value in attachments.values())
    return any(isinstance(value, dict) and value for value in (fallback_attachments or []))


def build_assistant_units(
    text: str,
    *,
    reply_sequence: list[dict[str, Any]] | None = None,
    attachment_by_request_id: dict[str, dict[str, Any]] | None = None,
    fallback_attachments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build ordered assistant message units from text and selected assets.

    The main LLM still produces only text. The director's reply_sequence decides
    where selected assets sit relative to text slots.
    """
    paragraphs = split_assistant_paragraphs(text)
    sequence = [x for x in (reply_sequence or []) if isinstance(x, dict)]
    attachments = attachment_by_request_id or {}

    if not sequence:
        units = [{"type": "text", "content": p} for p in paragraphs]
        for att in fallback_attachments or []:
            units.append({"type": "asset", "attachment": att})
        return units

    text_slot_count = sum(1 for item in sequence if item.get("type") == "text")
    if text_slot_count <= 0 and paragraphs:
        sequence = [*sequence, {"type": "text", "intent": "reply_text"}]
        text_slot_count = 1

    paragraph_slots: list[list[str]] = []
    remaining = list(paragraphs)
    if text_slot_count <= 1:
        paragraph_slots = [remaining] if text_slot_count == 1 else []
    else:
        for slot_idx in range(text_slot_count):
            if slot_idx < text_slot_count - 1:
                paragraph_slots.append(remaining[:1])
                remaining = remaining[1:]
            else:
                paragraph_slots.append(remaining)

    text_slot_index = 0
    units: list[dict[str, Any]] = []
    used_assets: set[str] = set()
    for item in sequence:
        typ = str(item.get("type") or "").strip().lower()
        if typ == "text":
            slot_paras = paragraph_slots[text_slot_index] if text_slot_index < len(paragraph_slots) else []
            for para in slot_paras:
                if para:
                    units.append({"type": "text", "content": para})
            text_slot_index += 1
            continue
        if typ == "asset":
            rid = str(item.get("request_id") or item.get("id") or "").strip()
            attachment = attachments.get(rid) if rid else None
            if attachment:
                used_assets.add(rid)
                units.append({"type": "asset", "request_id": rid, "attachment": attachment})

    for rid, attachment in attachments.items():
        if rid not in used_assets:
            units.append({"type": "asset", "request_id": rid, "attachment": attachment})

    if not any(u.get("type") == "text" for u in units) and paragraphs:
        units.extend({"type": "text", "content": p} for p in paragraphs)

    return units
