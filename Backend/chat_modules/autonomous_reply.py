"""Validate the Agent's normal-chat envelope and render through legacy parts."""
from __future__ import annotations

from .Prompts import OUTPUT_CONTRACT

import json
import re

from .normal_parts import _normal_stage3_render_parts_bubble
from .normal_plain_text import normal_plain_text
from .autonomous_wire_format import normalize_used_facts




def reply_envelope(raw: str) -> tuple[str, int]:
    if not raw or len(raw) > 16000 or re.search(r"<｜|<\||<(?:think|analysis|tool_call)\b", raw, re.I):
        raise ValueError("最终回复为空、过长或含内部标记")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("最终回复必须是包含bubble_count和bubbles的JSON object") from exc
    if not isinstance(data, dict):
        raise ValueError("最终回复必须是JSON object")
    bubbles, count = data.get("bubbles"), data.get("bubble_count")
    if type(count) is not int or not 0 <= count <= 6 or not isinstance(bubbles, list) or len(bubbles) != count:
        raise ValueError("bubble_count必须是0到6的整数并与bubbles长度一致")
    if count == 0 and not (data.get('delivery_mode') == 'assets_only' or
                          isinstance(data.get('no_reply_reason'), str) and data['no_reply_reason'].strip()):
        raise ValueError('零文字气泡必须说明no_reply_reason或delivery_mode=assets_only')
    clean = []
    for pos, bubble in enumerate(bubbles, 1):
        if not isinstance(bubble, dict) or type(bubble.get("index")) is not int or bubble["index"] != pos:
            raise ValueError("bubble.index必须从1开始连续编号")
        if bubble.get("type") != "text" or not isinstance(bubble.get("purpose"), str) or not bubble["purpose"].strip():
            raise ValueError("bubble需要type=text和非空purpose")
        parts = bubble.get("parts")
        if not isinstance(parts, list) or not 1 <= len(parts) <= 32:
            raise ValueError("bubble.parts必须是非空数组，最多32个片段")
        normalized = []
        for part in parts:
            if not isinstance(part, dict) or not isinstance(part.get("text"), str):
                raise ValueError("每个part需要kind和字符串text")
            # Validate the model's original boundaries before cleanup can alter them.
            _, _, error = _normal_stage3_render_parts_bubble({"parts": [part]}, pos)
            if error:
                raise ValueError(error)
            text = normal_plain_text(part["text"])
            normalized.append({"kind": part["kind"].strip().lower(), "text": text})
        item = {"index": pos, "type": "text", "purpose": bubble["purpose"].strip()[:80], "parts": normalized}
        _, _, error = _normal_stage3_render_parts_bubble(item, pos)
        if error:
            raise ValueError(error)
        clean.append(item)
    facts = normalize_used_facts(data.get("used_facts", []))
    extra = {k: data[k] for k in ('voice_reply','reply_language','no_reply_reason','delivery_mode') if k in data}
    observation = data.get('image_observation')
    if observation is not None:
        if not isinstance(observation, dict) or set(observation) - {
                'image_summary', 'visible_text', 'identified_entities', 'uncertainty', 'error'}:
            raise ValueError('image_observation字段不合法')
        strings = {}
        for key in ('image_summary', 'visible_text', 'uncertainty', 'error'):
            value = observation.get(key, '')
            if not isinstance(value, str):
                raise ValueError('image_observation文本字段必须是字符串')
            strings[key] = value.strip()[:4000]
        entities = observation.get('identified_entities', [])
        if not isinstance(entities, list) or len(entities) > 30 or any(
                not isinstance(value, str) or not value.strip() for value in entities):
            raise ValueError('image_observation.identified_entities必须是字符串数组')
        extra['image_observation'] = {**strings, 'identified_entities': [v.strip()[:200] for v in entities]}
    return json.dumps({"bubble_count": count, "bubbles": clean, "used_facts": facts[:32], **extra}, ensure_ascii=False), count


def render_envelope(data: dict) -> str:
    """Render the Agent envelope locally; never expose JSON to the App."""
    paragraphs = []
    for pos, bubble in enumerate(data["bubbles"], 1):
        text, _, error = _normal_stage3_render_parts_bubble(bubble, pos)
        if error:
            raise ValueError(error)
        paragraphs.append(text)
    if not paragraphs and data.get('bubble_count') != 0:
        raise ValueError("Empty autonomous reply")
    return "\n\n".join(paragraphs)
