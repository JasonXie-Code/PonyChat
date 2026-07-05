"""
providers/openai_compat.py
其它 OpenAI 兼容厂商 Provider（兜底）。

适用于：apiyi、poloai、自托管、未在专用 Provider 中列名的端点等；不修改 payload，标准 Chat Completions。
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from .base import BaseProvider, ParseResult, build_chat_completions_url, parse_chat_completions_chunk


class OpenAICompatProvider(BaseProvider):
    """非 DeepSeek 的 OpenAI 兼容端点；detect 恒为 False，由 get_provider 在列表末尾显式作为兜底。"""

    def detect(self, model_name: str, endpoint: str, model_cfg: dict) -> bool:
        return False

    def build_payload(
        self,
        payload: dict,
        params: dict,
        model_cfg: dict,
        *,
        request_mode: str = "normal",
        reasoning_policy: Optional[Any] = None,
        normalize_image_url: Optional[Any] = None,
    ) -> Tuple[dict, str, bool]:
        api_url = build_chat_completions_url(model_cfg.get("endpoint", ""))
        return payload, api_url, False

    def parse_stream_chunk(self, data: dict) -> ParseResult:
        return parse_chat_completions_chunk(data)

    def parse_response(self, resp_json: dict) -> tuple[str, str]:
        choices = resp_json.get("choices", [{}])
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content", "") or ""
        reasoning = message.get("reasoning_content", "") or ""
        return content, reasoning
