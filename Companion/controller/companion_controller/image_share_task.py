from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserImageToQqTask:
    query: str
    recipient: str


_PATTERNS = (
    re.compile(
        r"(?:Companion)?(?:在|用)(?:浏览器)?(?:里面|中)?搜索(?P<query>.+?)的图片[，,]?(?:并)?发给\s*QQ\s*(?:的|里)?(?P<recipient>.+)",
        re.I,
    ),
    re.compile(
        r"(?:帮我)?(?:在|用)浏览器搜索(?P<query>.+?)(?:图片)?[，,]?(?:并)?(?:用)?\s*QQ\s*发给(?P<recipient>.+)",
        re.I,
    ),
)


def parse_browser_image_to_qq_task(instruction: str) -> BrowserImageToQqTask | None:
    text = instruction.strip().strip("。")
    for pattern in _PATTERNS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        query = match.group("query").strip(" ，,;；:：\"“”").replace("“", "").replace("”", "")
        recipient = match.group("recipient").strip(" ，,;；:：\"“”")
        if query and recipient:
            return BrowserImageToQqTask(query=query, recipient=recipient)
    return None
