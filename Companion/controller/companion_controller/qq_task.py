from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QqMessageTask:
    recipient: str
    message: str


_PATTERNS = (
    re.compile(r"(?:帮我)?用\s*qq\s*给\s*(?P<recipient>.+?)\s*发(?:一条)?(?:信息|消息)(?:\s*[:：]\s*|\s*说\s*)(?P<message>.+)", re.I),
    re.compile(r"(?:帮我)?给\s*(?P<recipient>.+?)\s*用\s*qq\s*发(?:一条)?(?:信息|消息)(?:\s*[:：]\s*|\s*说\s*)(?P<message>.+)", re.I),
)


def parse_qq_message_task(instruction: str) -> QqMessageTask | None:
    text = instruction.strip()
    for pattern in _PATTERNS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        recipient = match.group("recipient").strip(" ，,;；:：")
        message = match.group("message").strip()
        if recipient and message:
            return QqMessageTask(recipient=recipient, message=message)
    return None
