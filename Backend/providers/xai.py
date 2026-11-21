"""
providers/xai.py
xAI Grok Provider。

职责：
  - 检测 api.x.ai 端点或 grok 模型名
  - 联网搜索时切换至 /v1/responses 端点（Responses API），转换消息格式
    system → developer 角色，构建 web_search 工具
  - 非联网时使用标准 Chat Completions，移除 web_search 参数
  - 流式解析：Responses API 走 responses 事件格式，否则走标准 Chat Completions 格式
  - 非流式解析：同上双路兼容
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from ..config import logger
from .base import (
    BaseProvider,
    ParseResult,
    _extract_responses_text_and_reasoning,
    build_chat_completions_url,
    parse_chat_completions_chunk,
    parse_responses_api_chunk,
)


class XaiProvider(BaseProvider):
    """xAI Grok 模型 Provider。"""

    _ENDPOINT_SIGNALS = ("api.x.ai",)
    _NAME_SIGNALS = ("grok",)

    def detect(self, model_name: str, endpoint: str, model_cfg: dict) -> bool:
        endpoint_l = (endpoint or "").lower()
        name_l = (model_name or "").lower()
        if any(s in endpoint_l for s in self._ENDPOINT_SIGNALS):
            return True
        if any(s in name_l for s in self._NAME_SIGNALS):
            return True
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
        base_endpoint = model_cfg.get("endpoint", "")
        use_web_search = params.get("web_search", False)
        use_responses_api = (
            use_web_search
            and request_mode not in ("galgame", "galgame_lock")
        )

        if use_responses_api:
            responses_url = (
                base_endpoint.rstrip("/").replace("/chat/completions", "") + "/responses"
            )
            xai_input = []
            for m in payload.get("messages", []):
                role = m.get("role", "user")
                content = m.get("content", "")
                if not content:
                    continue
                if role == "system":
                    xai_input.append({"role": "developer", "content": content})
                else:
                    xai_input.append({"role": role, "content": content})

            new_payload: dict = {
                "model": payload.get("model", ""),
                "input": xai_input,
                "tools": [{"type": "web_search"}],
                "stream": payload.get("stream", False),
            }
            if "temperature" in params:
                new_payload["temperature"] = params["temperature"]
            # xAI 接受 max_completion_tokens，与 payload 内已有命名一致
            _max_tokens = payload.get("max_tokens") or payload.get("max_completion_tokens")
            if _max_tokens is not None:
                new_payload["max_completion_tokens"] = int(_max_tokens)

            logger.info(f"🌐 [xAI路由] 已切换至 Responses API  端点: {responses_url}")
            return new_payload, responses_url, True
        else:
            payload.pop("web_search", None)
            api_url = build_chat_completions_url(base_endpoint)
            return payload, api_url, False

    def parse_stream_chunk(self, data: dict) -> ParseResult:
        event_type = data.get("type", "")
        if event_type:
            return parse_responses_api_chunk(data)
        return parse_chat_completions_chunk(data)

    def parse_response(self, resp_json: dict) -> Tuple[str, str]:
        if "output" in resp_json:
            return _extract_responses_text_and_reasoning(resp_json)
        choices = resp_json.get("choices", [{}])
        message = choices[0].get("message", {}) if choices else {}
        return message.get("content", "") or "", message.get("reasoning_content", "") or ""
