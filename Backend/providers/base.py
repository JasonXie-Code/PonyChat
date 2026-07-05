"""
providers/base.py
Provider 基础接口与公共工具。

每个 Provider 实现：
  detect()                   — 判断当前模型是否由本 Provider 处理
  preprocess_messages()      — 发送 API 前对 messages 进行预处理（如合并 system、strip 图片）
  build_payload()            — 在基础 payload 上追加厂商专属参数，返回 (payload, api_url, uses_responses_format)
  parse_stream_chunk()       — 从一个 SSE data 块中提取 (content_delta, reasoning_delta, signal_end_reasoning, fallback_full_text)
  parse_response()           — 从完整非流式响应 JSON 中提取 (content, reasoning)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple


# ---------------------------------------------------------------------------
# URL 辅助
# ---------------------------------------------------------------------------

def build_chat_completions_url(endpoint: str) -> str:
    """
    将模型配置里的 endpoint 规范化为 Chat Completions 实际请求地址。

    约定：
      - 若已是 `/chat/completions`，则原样返回
      - 若已是 `/responses`，则保留给专用 Provider 使用
      - 否则自动补成 `<base>/chat/completions`
    """
    base = str(endpoint or "").rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions") or base.endswith("/responses"):
        return base
    return f"{base}/chat/completions"


# ---------------------------------------------------------------------------
# 返回类型
# ---------------------------------------------------------------------------

class ParseResult:
    """
    parse_stream_chunk 的返回值。

    content             — 正文增量（UTF-8 字符串）
    reasoning           — 推理链增量（已被调用方包裹 <think> 标签）
    signal_end_reasoning— True 表示本 chunk 要结束推理链（如 output_item.added 事件）
    fallback_full_text  — response.completed 事件中提取的完整文本（去重后再追加）
    """
    __slots__ = ("content", "reasoning", "signal_end_reasoning", "fallback_full_text")

    def __init__(
        self,
        content: str = "",
        reasoning: str = "",
        signal_end_reasoning: bool = False,
        fallback_full_text: str = "",
    ) -> None:
        self.content = content
        self.reasoning = reasoning
        self.signal_end_reasoning = signal_end_reasoning
        self.fallback_full_text = fallback_full_text

    def __repr__(self) -> str:
        return (
            f"ParseResult(content={self.content[:30]!r}, "
            f"reasoning={self.reasoning[:30]!r}, "
            f"signal_end_reasoning={self.signal_end_reasoning}, "
            f"fallback_full_text={self.fallback_full_text[:30]!r})"
        )


# ---------------------------------------------------------------------------
# 公共 Responses API 流解析（xAI 和豆包共用相同事件格式）
# ---------------------------------------------------------------------------

def parse_responses_api_chunk(data: dict) -> ParseResult:
    """
    解析 Responses API SSE 事件块，适用于 xAI Grok 和豆包。

    事件类型映射：
      response.output_text.delta              → content 增量
      response.content_part.delta             → content 增量（豆包兼容）
      response.reasoning_summary_text.delta   → reasoning 增量
      response.output_item.added              → 信号：结束推理链
      response.completed                      → fallback 完整文本
    """
    event_type = data.get("type", "")

    if event_type == "response.output_text.delta":
        return ParseResult(content=data.get("delta", ""))

    if event_type == "response.content_part.delta":
        delta_data = data.get("delta", {})
        text = delta_data.get("text", "") if isinstance(delta_data, dict) else str(delta_data)
        return ParseResult(content=text, signal_end_reasoning=bool(text))

    if event_type == "response.reasoning_summary_text.delta":
        return ParseResult(reasoning=data.get("delta", ""))

    if event_type == "response.output_item.added":
        return ParseResult(signal_end_reasoning=True)

    if event_type == "response.completed":
        extracted = _extract_text_from_completed_event(data)
        return ParseResult(fallback_full_text=extracted)

    return ParseResult()


def _extract_text_from_completed_event(data: dict) -> str:
    """从 response.completed 事件中提取正文（兼容 xAI 和豆包的输出结构差异）。"""
    response_data = data.get("response", {})
    output = response_data.get("output", [])
    parts: List[str] = []
    for item in output:
        if item.get("type") == "message":
            for part in item.get("content", []):
                part_type = part.get("type", "")
                if part_type in ("output_text", "text"):
                    text = part.get("text", "")
                    if text:
                        parts.append(text)
    return "".join(parts)


# ---------------------------------------------------------------------------
# 公共 Chat Completions 流解析（标准 OpenAI 格式）
# ---------------------------------------------------------------------------

def parse_chat_completions_chunk(data: dict) -> ParseResult:
    """
    解析标准 Chat Completions SSE 块。
    支持 reasoning_content（DeepSeek-R1 / Qwen3.5-Plus）。
    """
    delta = data.get("choices", [{}])[0].get("delta", {})
    content = delta.get("content", "") or ""
    reasoning = delta.get("reasoning_content", "") or ""
    return ParseResult(content=content, reasoning=reasoning)


# ---------------------------------------------------------------------------
# Responses API 完整响应解析（非流式）
# ---------------------------------------------------------------------------

def _extract_responses_text_and_reasoning(resp_json: dict) -> Tuple[str, str]:
    """
    兼容 Responses API 多种输出结构，提取正文与思维链。
    被 doubao / xai provider 和 galgame 包共用。
    """
    if not isinstance(resp_json, dict):
        return "", ""

    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    output = resp_json.get("output", [])
    if not isinstance(output, list):
        output = []

    def _append(bucket: List[str], value: Any) -> None:
        if isinstance(value, str):
            s = value.strip()
            if s:
                bucket.append(s)

    def _collect_reasoning(obj: Any) -> None:
        if isinstance(obj, str):
            _append(reasoning_parts, obj)
            return
        if isinstance(obj, dict):
            _append(reasoning_parts, obj.get("text"))
            _append(reasoning_parts, obj.get("content"))
            _append(reasoning_parts, obj.get("reasoning_content"))
            summary = obj.get("summary")
            if isinstance(summary, str):
                _append(reasoning_parts, summary)
            elif isinstance(summary, list):
                for s in summary:
                    if isinstance(s, dict):
                        _append(reasoning_parts, s.get("text"))
                    else:
                        _append(reasoning_parts, s)
            return
        if isinstance(obj, list):
            for item in obj:
                _collect_reasoning(item)

    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()

        if item_type == "message":
            for part in item.get("content", []):
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").lower()
                if part_type in ("output_text", "text"):
                    _append(text_parts, part.get("text"))
                elif "reasoning" in part_type or "summary" in part_type:
                    _collect_reasoning(part)
                else:
                    _append(text_parts, part.get("content"))

        if "reasoning" in item_type or "summary" in item_type:
            _collect_reasoning(item)

        if "reasoning" in item:
            _collect_reasoning(item.get("reasoning"))

    if not text_parts:
        _append(text_parts, resp_json.get("output_text"))

    if not reasoning_parts:
        _collect_reasoning(resp_json.get("reasoning"))
        _append(reasoning_parts, resp_json.get("reasoning_content"))
        _append(reasoning_parts, resp_json.get("thinking"))

    return "\n".join(text_parts).strip(), "\n".join(reasoning_parts).strip()


# ---------------------------------------------------------------------------
# 统一 LLM 调用返回值（call_llm）
# ---------------------------------------------------------------------------


@dataclass
class LLMResponse:
    """非流式 LLM 调用的统一返回结构。"""

    text: str = ""
    reasoning: str = ""
    usage: dict = field(default_factory=dict)
    raw_response: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 基础 Provider
# ---------------------------------------------------------------------------

class BaseProvider:
    """
    所有 Provider 的基类，提供默认空实现。
    子类覆盖需要自定义的方法即可，不需要实现全部接口。
    """

    def detect(self, model_name: str, endpoint: str, model_cfg: dict) -> bool:
        """返回 True 表示本 Provider 负责处理该模型。"""
        return False

    def preprocess_messages(self, messages: list, model_cfg: dict) -> list:
        """在构建 payload 前对 messages 进行预处理，默认不修改。"""
        return messages

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
        """
        在基础 payload 上追加厂商专属参数。

        返回：
          payload          — 修改后的 payload（可能是全新 dict）
          api_url          — 实际调用的 API 端点 URL
          uses_responses   — True 表示使用 Responses API 格式（非 Chat Completions）
        """
        api_url = model_cfg.get("endpoint", "")
        return payload, api_url, False

    def parse_stream_chunk(self, data: dict) -> ParseResult:
        """解析一个 SSE 流式数据块，默认使用标准 Chat Completions 格式。"""
        return parse_chat_completions_chunk(data)

    def parse_response(self, resp_json: dict) -> Tuple[str, str]:
        """
        解析完整的非流式响应 JSON，返回 (content, reasoning)。
        默认使用标准 Chat Completions 格式。
        """
        choices = resp_json.get("choices", [{}])
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content", "") or ""
        reasoning = message.get("reasoning_content", "") or ""
        return content, reasoning
