# -*- coding: utf-8 -*-
"""
助手正文后处理：按模型配置截断「下一轮对话」泄露（如续写出 [INST]…）。
与推理部署位置无关。
"""
from __future__ import annotations

from typing import Any, Optional
import re


_THINK_BLOCK_RE = re.compile(
    r"<(?:think|thinking)>[\s\S]*?(?:</(?:think|thinking)>|$)",
    re.IGNORECASE,
)
_THINK_FENCE_RE = re.compile(
    r"```[ \t]*(?:think|thinking)[^\n\r]*[\r\n]+[\s\S]*?(?:```|$)",
    re.IGNORECASE,
)


def sanitize_assistant_strip_thinking_blocks(content: str) -> str:
    """Remove visible reasoning blocks from assistant-facing text, including unclosed tails."""
    if not content:
        return content
    cleaned = _THINK_BLOCK_RE.sub("", content)
    cleaned = _THINK_FENCE_RE.sub("", cleaned)
    return cleaned.strip()


def sanitize_assistant_close_leading_fullwidth_parens(content: str) -> str:
    """Balance full-width parens for assistant description paragraphs."""
    if not content:
        return content
    parts = re.split(r"(\n+)", content)
    fixed: list[str] = []
    for part in parts:
        if not part or part.startswith("\n"):
            fixed.append(part)
            continue
        stripped = part.strip()
        opens = stripped.count("（")
        closes = stripped.count("）")
        if stripped.startswith("（") and opens > closes:
            right_ws_len = len(part) - len(part.rstrip())
            suffix = part[len(part) - right_ws_len :] if right_ws_len else ""
            body = part[: len(part) - right_ws_len] if right_ws_len else part
            part = body + "）" + suffix
        elif stripped.endswith("）") and closes > opens:
            left_ws_len = len(part) - len(part.lstrip())
            prefix = part[:left_ws_len] if left_ws_len else ""
            body = part[left_ws_len:] if left_ws_len else part
            part = prefix + "（" + body
        fixed.append(part)
    return "".join(fixed).strip()


def sanitize_assistant_strip_markers(content: str, model_cfg: Optional[dict]) -> str:
    """
    在助手正文里截断泄露标记；由模型配置 assistant_strip_markers 列出前缀；无配置则原样返回。
    """
    if not content:
        return content
    cfg = model_cfg if isinstance(model_cfg, dict) else {}
    markers = cfg.get("assistant_strip_markers")
    if not isinstance(markers, list) or not markers:
        return content
    earliest = len(content)
    for m in markers:
        if isinstance(m, str) and m:
            pos = content.find(m)
            if pos != -1 and pos < earliest:
                earliest = pos
    if earliest < len(content):
        return content[:earliest].rstrip()
    return content
