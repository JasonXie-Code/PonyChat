"""
providers/deepseek.py
DeepSeek 官方 / DeepSeek 系列模型 Provider。

行为与 OpenAICompatProvider 完全一致；仅通过 detect 提前识别 DeepSeek 端点或模型名，
避免被 OpenAI 兼容兜底错误匹配时遗漏将来可能的 DeepSeek 专属扩展。
"""

from __future__ import annotations

from .openai_compat import OpenAICompatProvider


class DeepseekProvider(OpenAICompatProvider):
    """DeepSeek API（api.deepseek.com 等）及模型名含 deepseek 的走本 Provider。"""

    _ENDPOINT_SIGNALS = ("api.deepseek.com", "deepseek.com")
    _NAME_SIGNALS = ("deepseek",)

    def detect(self, model_name: str, endpoint: str, model_cfg: dict) -> bool:
        endpoint_l = (endpoint or "").lower()
        name_l = (model_name or "").lower()
        if any(s in endpoint_l for s in self._ENDPOINT_SIGNALS):
            return True
        if any(s in name_l for s in self._NAME_SIGNALS):
            return True
        return False
