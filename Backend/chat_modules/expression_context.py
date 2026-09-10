"""Observed auxiliary-expression history; no inferred preferences or random quotas."""
from __future__ import annotations

import re


_BASE = (r"(?:[\U0001F1E6-\U0001F1FF]{2}|[0-9#*]\uFE0F?\u20E3|"
         r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u00A9\u00AE\u203C\u2049\u2122\u2139"
         r"\u2194-\u2199\u21A9-\u21AA\u231A-\u231B\u2328\u23CF\u23E9-\u23F3\u23F8-\u23FA"
         r"\u24C2\u25AA-\u25AB\u25B6\u25C0\u25FB-\u25FE\u2934-\u2935\u2B05-\u2B07"
         r"\u2B1B-\u2B1C\u2B50\u2B55\u3030\u303D\u3297\u3299]\uFE0F?[\U0001F3FB-\U0001F3FF]?)")
_EMOJI = re.compile(_BASE + r"(?:\u200D" + _BASE + r")*")


def emoji_symbols(text: str) -> list[str]:
    """Keep flags, skin tones and joined pictographs together for recent-use hints."""
    return list(dict.fromkeys(_EMOJI.findall(str(text or ""))))


def build_expression_context(messages, *, speaker_character_id=None) -> dict:
    # A completed role turn can contain several persisted bubbles and image rows.
    # Count that group once; another speaker must neither count nor reset cooldown.
    turns, current = [], None
    for message in messages or []:
        if (message.get("isHidden") or message.get("is_hidden")
                or message.get("deleted_at") is not None):
            continue
        if message.get("role") == "user":
            current = None
            continue
        if message.get("role") != "assistant":
            continue
        speaker = message.get("speaker_character_id")
        if speaker_character_id and speaker and speaker != speaker_character_id:
            continue
        if current is None:
            current = {"emoji": [], "sticker_asset_ids": [], "has_sticker": False}
            turns.append(current)
        current["emoji"] = list(dict.fromkeys(current["emoji"] + emoji_symbols(message.get("content", ""))))
        for attachment in message.get("attachments") or []:
            if not isinstance(attachment, dict) or attachment.get("type") not in {"sticker", "emoji_asset"}:
                continue
            current["has_sticker"] = True
            asset_id = attachment.get("asset_id")
            if asset_id and str(asset_id) not in current["sticker_asset_ids"]:
                current["sticker_asset_ids"].append(str(asset_id))
    turns = turns[-20:]

    def count(window):
        return {"observed_turns": len(window),
                "auxiliary_turns": sum(bool(t["emoji"] or t["has_sticker"]) for t in window),
                "sticker_turns": sum(t["has_sticker"] for t in window)}

    return {"basis": "observed_completed_turns_for_current_character",
            "history_may_be_incomplete": True,
            "note": "每组为用户消息之间的同一角色回复，不按气泡数计轮。符号计数含显式请求与引用，语义仍看原文。",
            "recent_10": count(turns[-10:]), "recent_15": count(turns[-15:]),
            "recent_20": count(turns), "recent_3": count(turns[-3:]),
            "prior_turns_in_next_window": {str(size): count(turns[-(size-1):]) for size in (10, 15, 20)},
            "previous_turn_used_auxiliary": bool(turns and (turns[-1]["emoji"] or turns[-1]["has_sticker"])),
            "recent_emoji": list(dict.fromkeys(s for t in turns[-10:] for s in t["emoji"])),
            "recent_sticker_asset_ids": list(dict.fromkeys(s for t in turns[-10:] for s in t["sticker_asset_ids"]))}
