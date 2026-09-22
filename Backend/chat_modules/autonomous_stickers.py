"""Agent-selected platform stickers staged for the existing message delivery path."""
from __future__ import annotations
from .Prompts import AUTONOMOUS_STICKERS_TEXT

import re

from .harness_runtime import HarnessToolValidationError


def explicitly_requests_sticker_repeat(text: str) -> bool:
    for clause in re.split(r"[，,。！？!?；;\n]", str(text or "")):
        if re.search(r"不要|不用|别|无需|不必", clause):
            continue
        repeats = re.search(r"再发|再来|再给|重发|重复发", clause)
        reference = re.search(r"(?:刚才|刚刚|上次|上一|同一|同样的|那张).{0,12}(?:张|图|表情包|贴纸)|那张", clause)
        if repeats and reference:
            return True
    return False


class AgentStickerTools:
    def __init__(self, loader, attachment_factory):
        self._loader = loader
        self._attachment_factory = attachment_factory
        self._candidates = {}
        self._selected = {}
        self._placements = {}
        self.searched = False

    async def search(self, arguments):
        query = arguments.get("query", "")
        tags = arguments.get("tags", [])
        candidates = await self._loader(query, tags, set(self._selected))
        self.searched = True
        for item in candidates[:12]:
            self._candidates[item["ref"]] = item
        return {"candidates": [{key: item.get(key) for key in (
            "ref", "name", "intro", "detail", "image_text", "emotions", "custom_tags")}
            for item in candidates[:12]], "instruction": AUTONOMOUS_STICKERS_TEXT['search_1']}

    async def stage(self, arguments):
        ref = arguments["asset_ref"]
        if not self.searched:
            raise HarnessToolValidationError(AUTONOMOUS_STICKERS_TEXT['stage_2'])
        if not ref:
            if not arguments.get("reason", "").strip():
                raise HarnessToolValidationError(AUTONOMOUS_STICKERS_TEXT['stage_5'])
            self._selected.clear()
            self._placements.clear()
            return {"staged": False, "reason": AUTONOMOUS_STICKERS_TEXT['stage_3']}
        if ref not in self._candidates:
            raise HarnessToolValidationError(AUTONOMOUS_STICKERS_TEXT['stage_4'])
        if ref not in self._selected and len(self._selected) >= 4:
            raise HarnessToolValidationError("每轮最多4张表情包")
        position = arguments.get('after_bubble_index')
        if position is not None and (type(position) is not int or not 0 <= position <= 6):
            raise HarnessToolValidationError('after_bubble_index must be 0..6')
        candidate = self._candidates[ref]
        rid = self._selected[ref]["metadata"]["request_id"] if ref in self._selected else f"agent_sticker_{len(self._selected)+1}"
        self._selected[ref] = self._attachment_factory(candidate, {"request_id": rid, "query": arguments.get("reason", "")})
        self._placements[ref] = position if position is not None else arguments.get("placement", "after_text")
        return {"staged": True, "asset_ref": ref, "request_id": rid,
                "delivery": AUTONOMOUS_STICKERS_TEXT['stage_1']}

    def register(self, capability):
        capability("search_stickers", AUTONOMOUS_STICKERS_TEXT['register_1'], {
            "type": "object", "properties": {
                "query": {"type": "string", "maxLength": 300},
                "tags": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 40}}},
            "additionalProperties": False}, self.search)
        capability("stage_sticker", AUTONOMOUS_STICKERS_TEXT['register_2'], {
            "type": "object", "properties": {
                "asset_ref": {"type": "string", "maxLength": 200},
                "reason": {"type": "string", "maxLength": 300},
                "placement": {"type": "string", "enum": ["before_text", "after_text"]},
                "after_bubble_index": {"type":"integer","minimum":0,"maximum":6,"description":AUTONOMOUS_STICKERS_TEXT['register_3']}},
            "required": ["asset_ref"], "additionalProperties": False}, self.stage)

    def apply_to_request(self, request, bubble_count=1):
        items = []
        for ref, attachment in self._selected.items():
            placement = self._placements[ref]
            index = min(placement, bubble_count) if type(placement) is int else (0 if placement=='before_text' else bubble_count)
            items.append((attachment, index))
        apply_image_attachments(request, items, bubble_count)


def apply_image_attachments(request, items, bubble_count, *, append=False):
    slots, attachments = {}, {}
    if append:
        attachments.update(getattr(request, '_assistant_asset_by_request_id', {}) or {})
        index = 0
        for unit in getattr(request, '_assistant_reply_sequence', []) or []:
            if unit.get('type') == 'text':
                index += 1
            elif unit.get('type') == 'asset':
                slots.setdefault(index, []).append(unit)
    for attachment, index in items:
        rid = attachment['metadata']['request_id']
        attachments[rid] = attachment
        slots.setdefault(index, []).append({'type': 'asset', 'request_id': rid})
    sequence = list(slots.get(0, []))
    for index in range(1, bubble_count + 1):
        sequence.append({'type': 'text', 'intent': 'agent_reply'})
        sequence.extend(slots.get(index, []))
    request._assistant_reply_sequence = sequence
    request._assistant_asset_by_request_id = attachments
    request._assistant_asset_attachments = list(attachments.values())


def make_sticker_tools(*, username, character_id, profile, recent_messages):
    # Reuse platform filtering, metadata, URL construction and recent-asset cooldown.
    # No eager catalog read and no second LLM selector: the same Agent chooses.
    from .assets import (_candidate_to_attachment, _preferred_character_name_terms,
                         _recall_platform_candidates, _recent_asset_ids_from_db,
                         _recent_asset_ids_from_messages)
    from .expression_context import build_expression_context

    latest = next((m.get("content", "") for m in reversed(recent_messages or []) if m.get("role") == "user"), "")
    repeat_requested = explicitly_requests_sticker_repeat(latest)
    history = build_expression_context(recent_messages, speaker_character_id=character_id)

    async def load(query, tags, selected_refs):
        cooldown = set()
        if not repeat_requested:
            cooldown.update(_recent_asset_ids_from_messages(recent_messages))
            cooldown.update(history["recent_sticker_asset_ids"])
            cooldown.update(await _recent_asset_ids_from_db(username=username, character_id=character_id))
        cooldown.update(ref.removeprefix("platform:") for ref in selected_refs)
        return await _recall_platform_candidates(
            {"query": query, "tags": tags, "preferred_character_names": _preferred_character_name_terms(profile, character_id)},
            age_rating="all", max_flirt_level=0, cooldown_asset_ids=cooldown, limit=12)

    return AgentStickerTools(load, _candidate_to_attachment)
