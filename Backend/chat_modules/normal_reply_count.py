"""Recognize explicit current-turn requests for one to five chat paragraphs.

Only affirmative output requests become a hard constraint. Topic quantities,
quoted instructions, ranges and references to numbered paragraphs are ignored.
"""
from __future__ import annotations

import re
import unicodedata


_NUMBERS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_COUNT = re.compile(
    r"(?<![第\d.一二两三四五六七八九十百])(?P<n>[1-5一二两三四五])\s*(?:个\s*)?"
    r"(?:自然段|段落|段(?:话|文字|回复)?|(?:条|个)?\s*(?:消息|回复|气泡))"
    r"|\b(?P<en>[1-5]|one|two|three|four|five)\s+(?:paragraphs?|messages?|bubbles?)\b", re.I)
_REQUEST = re.compile(r"说|回复|回答|写|发|聊|描述|描写|讲|分成|分为|分|用|给我|来|改成|改为|换成|要|正好|只|仅|就|"
                      r"\b(?:reply|respond|answer|write|send|give|use|in|exactly|only)\b", re.I)
_NEGATIVE = re.compile(r"(?:不要|别|不用|无需|不必|不是|并非|不需要|不准|不能)[^，,。！？!?；;\n]{0,14}$|"
                      r"\b(?:not|don't|do not|no need to)\b[^,.;!?\n]{0,24}$", re.I)
_CANCEL = re.compile(r"(?:不(?:用|要|必)?限制|不限|不限定)\s*(?:回复|回答)?\s*(?:段数|数量)|"
                     r"段数\s*(?:不限|随意|自由)|不用限制|自由发挥|\bno paragraph limit\b", re.I)


def requested_reply_count(message: str) -> int | None:
    text = unicodedata.normalize("NFKC", str(message or ""))
    text = re.sub(r'```[\s\S]*?```|“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"', "", text)
    candidates = []
    for match in _COUNT.finditer(text):
        before = re.split(r"[，,。！？!?；;\n]", text[:match.start()])[-1]
        after = text[match.end():]
        if re.search(r"[\d一二两三四五六七八九十]\s*(?:-|~|～|—|至|到|/|、)\s*$", before):
            continue
        if _NEGATIVE.search(before) or re.search(r"(?:上次|之前|刚才|以前|昨天|已经|写了|说了|发了)", before):
            continue
        if re.search(r"至少|至多|最多|最少|大约|差不多|不少于|不超过|如果|假如|假设|比如|例如", before):
            continue
        affirmative = _REQUEST.search(before) or re.match(r"\s*(?:就好|就行|即可|回复|回答|够了)", after)
        if not affirmative:
            continue
        value = (match.group("n") or match.group("en")).lower()
        count = int(value) if value.isdigit() else _NUMBERS[value]
        candidates.append((match.start(), count))
    if not candidates:
        return None
    position, count = candidates[-1]
    if any(cancel.start() > position for cancel in _CANCEL.finditer(text)):
        return None
    return count
