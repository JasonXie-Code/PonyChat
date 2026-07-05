"""
providers/doubao.py
ByteDance Doubao / Seed Provider。

职责：
  - 检测 ark.cn-beijing.volces.com 端点或 doubao/seed 模型名
  - 统一在 normal/galgame/galgame_lock 模式下切换至 /responses 端点（Responses API）
  - 豆包 2.0 Lite 始终走 Responses API（仅支持该接口）
  - 消息格式转换：Chat Completions → Responses API（含多模态图片格式转换）
  - 思考控制：reasoning_policy 注入 thinking / reasoning 字段
  - 流式/非流式均走 Responses API 格式解析
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

from ..config import logger
from .base import (
    BaseProvider,
    ParseResult,
    _extract_responses_text_and_reasoning,
    parse_responses_api_chunk,
)


class DoubaoProvider(BaseProvider):
    """ByteDance 豆包 / Seed 模型 Provider。"""

    _ENDPOINT_SIGNALS = ("ark.cn-beijing.volces.com",)
    _NAME_SIGNALS = ("doubao", "seed")
    _LITE_IDS = ("doubao-2-0-lite",)
    _LITE_NAME_SIGNALS = ("2-0-lite", "seed-2-0")

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
        normalize_image_url: Optional[Callable[[str], Optional[str]]] = None,
    ) -> Tuple[dict, str, bool]:
        base_endpoint = model_cfg.get("endpoint", "")
        model_id = model_cfg.get("id", "")
        model_name = payload.get("model", "")
        model_name_lower = model_name.lower()

        is_lite = (
            model_id in self._LITE_IDS
            or any(s in model_name_lower for s in self._LITE_NAME_SIGNALS)
        )
        use_web_search = params.get("web_search", False)
        use_responses_api = is_lite or use_web_search or request_mode in (
            "normal", "galgame", "galgame_lock"
        )

        if not use_responses_api:
            return payload, base_endpoint, False

        responses_url = (
            base_endpoint.rstrip("/").replace("/chat/completions", "") + "/responses"
        )

        messages = payload.get("messages", [])
        responses_input = _convert_messages_to_responses_format(messages, normalize_image_url)

        new_payload: dict = {
            "model": model_name,
            "input": responses_input,
            "stream": payload.get("stream", False),
        }

        if use_web_search:
            new_payload["tools"] = [{"type": "web_search", "max_keyword": 3}]

        if "temperature" in payload:
            new_payload["temperature"] = payload["temperature"]

        # Responses API 用 max_output_tokens（原 Chat Completions 的 max_tokens）
        _max_tokens = payload.get("max_tokens") or payload.get("max_completion_tokens") or payload.get("max_output_tokens")
        if _max_tokens:
            new_payload["max_output_tokens"] = int(_max_tokens)

        if reasoning_policy is not None:
            if reasoning_policy.thinking_type in ("enabled", "disabled"):
                new_payload["thinking"] = {"type": reasoning_policy.thinking_type}
            # 豆包 Responses API 只支持 thinking 字段，不支持 reasoning 字段（xAI 格式），不传

        logger.info(
            f"🌐 [豆包路由] 已切换至 Responses API  端点: {responses_url}"
            f"  联网搜索: {'开启' if use_web_search else '关闭'}"
        )
        return new_payload, responses_url, True

    def parse_stream_chunk(self, data: dict) -> ParseResult:
        return parse_responses_api_chunk(data)

    def parse_response(self, resp_json: dict) -> Tuple[str, str]:
        return _extract_responses_text_and_reasoning(resp_json)


# ---------------------------------------------------------------------------
# 消息格式转换：Chat Completions → Responses API
# ---------------------------------------------------------------------------

def _convert_messages_to_responses_format(
    messages: list,
    normalize_image_url: Optional[Callable[[str], Optional[str]]] = None,
) -> List[dict]:
    """
    将 OpenAI Chat Completions 格式的 messages 转换为豆包 Responses API 格式。

    官方格式：
      纯文本:   {"role": "user", "content": "文本内容"}
      多模态:   {"role": "user", "content": [
                  {"type": "input_text",  "text": "..."},
                  {"type": "input_image", "image_url": "..."},
                ]}
    """
    converted: List[dict] = []
    system_parts: List[str] = []

    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")

        if role == "system":
            if isinstance(content, list):
                for item in content:
                    if item.get("type") in ("text", "input_text"):
                        text = item.get("text", "").strip()
                        if text:
                            system_parts.append(text)
            else:
                text = (content or "").strip()
                if text:
                    system_parts.append(text)
            continue

        if isinstance(content, list):
            has_image = any(
                item.get("type") in ("image_url", "input_image") for item in content
            )
            if has_image:
                new_content: List[dict] = []
                for item in content:
                    t = item.get("type", "")
                    if t == "text":
                        new_content.append({"type": "input_text", "text": item.get("text", "")})
                    elif t == "image_url":
                        raw_url = item.get("image_url", {}).get("url", "")
                        url = normalize_image_url(raw_url) if normalize_image_url else raw_url
                        if url:
                            image_item = {"type": "input_image", "image_url": url}
                            detail = item.get("detail") or item.get("image_url", {}).get("detail")
                            if detail:
                                image_item["detail"] = detail
                            pixel_limit = item.get("image_pixel_limit") or item.get("image_url", {}).get("image_pixel_limit")
                            if isinstance(pixel_limit, dict):
                                image_item["image_pixel_limit"] = pixel_limit
                            new_content.append(image_item)
                    elif t == "input_text":
                        new_content.append(item)
                    elif t == "input_image":
                        item_copy = dict(item)
                        raw_url = item_copy.get("image_url", "")
                        url = normalize_image_url(raw_url) if normalize_image_url else raw_url
                        item_copy["image_url"] = url
                        if url:
                            new_content.append(item_copy)
                if new_content:
                    converted.append({"role": role, "content": new_content})
            else:
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if item.get("type") in ("text", "input_text")
                ]
                combined = " ".join(text_parts).strip()
                if combined:
                    converted.append({"role": role, "content": combined})
        else:
            if content and str(content).strip():
                converted.append({"role": role, "content": content})

    if system_parts:
        system_text = "\n\n".join(system_parts).strip()
        if system_text:
            converted.insert(0, {"role": "system", "content": system_text})
            logger.info(f"📝 已保留 {len(system_parts)} 条 System Prompt 为独立 system 输入")

    return converted
