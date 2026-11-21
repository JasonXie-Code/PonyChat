"""
providers/qwen.py
Alibaba DashScope / Qwen Provider。

职责：
  - 检测 DashScope 端点或 qwen 系列模型名
  - 普通对话优先切换到阿里云官方 Responses API（支持内建工具/联网搜索）
  - 非普通模式保留 Chat Completions 兼容路径，并注入 enable_thinking
  - 流式/非流式解析同时兼容 Responses API 与 Chat Completions
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


class QwenProvider(BaseProvider):
    """Alibaba DashScope Qwen 系列模型 Provider。"""

    _ENDPOINT_SIGNALS = ("dashscope.aliyuncs.com",)
    _NAME_SIGNALS = ("qwen",)

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
        use_responses_api = request_mode == "normal"

        if use_responses_api:
            responses_url = self._build_responses_url(base_endpoint)
            new_payload: dict = {
                "model": payload.get("model", ""),
                # 阿里云官方文档说明 Responses API 兼容 Chat 格式 message array，
                # 这里直接复用现有消息历史，避免再做一层 role/content 重写。
                "input": payload.get("messages", []),
                "stream": payload.get("stream", False),
            }
            if "temperature" in payload:
                new_payload["temperature"] = payload["temperature"]
            # Responses API 用 max_output_tokens（原 Chat Completions 的 max_tokens）
            _max_tokens = payload.get("max_tokens") or payload.get("max_completion_tokens") or payload.get("max_output_tokens")
            if _max_tokens:
                new_payload["max_output_tokens"] = int(_max_tokens)
            enable_thinking = bool(model_cfg.get("enable_thinking", True))
            new_payload["enable_thinking"] = enable_thinking
            if enable_thinking:
                thinking_budget_level = str(params.get("thinking_budget") or "").strip().lower()
                _THINKING_BUDGET_MAP = {"low": 4096, "medium": 8192, "high": 16384}
                if thinking_budget_level in _THINKING_BUDGET_MAP:
                    new_payload["thinking_budget"] = _THINKING_BUDGET_MAP[thinking_budget_level]
                    logger.info(
                        "💭 [Qwen思考预算] 档位=%s → thinking_budget=%d tokens",
                        thinking_budget_level, _THINKING_BUDGET_MAP[thinking_budget_level],
                    )
            if use_web_search:
                # 官方建议联网任务优先启用内建工具组合。
                new_payload["tools"] = [
                    {"type": "web_search"},
                    {"type": "web_extractor"},
                    {"type": "code_interpreter"},
                ]
            logger.info(
                "🌐 [Qwen路由] 已切换至阿里云官方 Responses API  端点: %s  联网搜索: %s",
                responses_url,
                "开启" if use_web_search else "关闭",
            )
            return new_payload, responses_url, True

        api_url = build_chat_completions_url(base_endpoint)
        payload["enable_thinking"] = bool(model_cfg.get("enable_thinking", True))
        payload.pop("web_search", None)
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

    @staticmethod
    def _build_responses_url(endpoint: str) -> str:
        base = str(endpoint or "").rstrip("/")
        if not base:
            return ""
        if base.endswith("/responses"):
            return base
        if "/api/v2/apps/protocols/compatible-mode/v1" in base:
            return base.replace("/chat/completions", "").rstrip("/") + "/responses"
        if "/compatible-mode/v1" in base:
            host = base.split("/compatible-mode/v1", 1)[0]
            return host + "/api/v2/apps/protocols/compatible-mode/v1/responses"
        return base.rstrip("/").replace("/chat/completions", "") + "/responses"
