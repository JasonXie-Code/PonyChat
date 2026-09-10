"""
providers/__init__.py
Provider 工厂模块。

用法：
    from backend.providers import get_provider

    provider = get_provider(model_name, endpoint, active_model)
    messages  = provider.preprocess_messages(messages, active_model)
    payload, api_url, uses_responses = provider.build_payload(
        payload, params, active_model,
        request_mode=request.mode,
        reasoning_policy=reasoning_policy,
        normalize_image_url=_normalize_image_url_for_model,
    )
"""

from .base import BaseProvider, LLMResponse, ParseResult
from .deepseek import DeepseekProvider
from .openai_compat import OpenAICompatProvider
from .qwen import QwenProvider
from .xai import XaiProvider

__all__ = [
    "BaseProvider",
    "LLMResponse",
    "ParseResult",
    "DeepseekProvider",
    "OpenAICompatProvider",
    "QwenProvider",
    "XaiProvider",
    "get_provider",
    "call_llm",
    "call_llm_payload",
    "call_llm_stream",
    "call_llm_stream_payload",
    "PLATFORM_FICTION_DISCLAIMER",
    "FICTION_ROLEPLAY_DISCLAIMER",
    "apply_fiction_roleplay_disclaimer_to_payload",
]

# 按优先级排列：更具体的厂商放前面；OpenAI 兼容兜底放最后（仅云端/公网 API，不含本机推理）
_PROVIDERS: list[BaseProvider] = [
    XaiProvider(),
    QwenProvider(),
    DeepseekProvider(),
]

_FALLBACK: BaseProvider = OpenAICompatProvider()


def get_provider(model_name: str, endpoint: str, model_cfg: dict) -> BaseProvider:
    """
    根据模型名称和端点自动选择 Provider。

    检测顺序（优先级从高到低）：
      2. XaiProvider           — xAI Grok
      3. QwenProvider          — 阿里云 DashScope Qwen
      4. DeepseekProvider      — DeepSeek 官方端点或 deepseek 模型名
      5. OpenAICompatProvider  — 其它 OpenAI 兼容（未匹配时兜底）
    """
    if "doubao" in (model_name or "").lower() or "ark.cn-beijing.volces.com" in (endpoint or "").lower():
        raise ValueError("Retired LLM provider; use deepseek-flash")
    for provider in _PROVIDERS:
        if provider.detect(model_name, endpoint, model_cfg):
            return provider
    return _FALLBACK


from .llm_call import (
    FICTION_ROLEPLAY_DISCLAIMER,
    PLATFORM_FICTION_DISCLAIMER,
    apply_fiction_roleplay_disclaimer_to_payload,
    call_llm,
    call_llm_payload,
    call_llm_stream,
    call_llm_stream_payload,
)
