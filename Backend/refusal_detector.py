# -*- coding: utf-8 -*-
"""
拒绝检测已关闭：`is_refusal` / `is_invalid_context_summary` 恒为 False，全部放行。

摘要落库、Galgame 分步、MLP RAG 等仍调用同名函数以保持接口稳定，但不再拦截任何文本。
若需恢复历史关键词策略，请从版本控制回溯。
"""
from __future__ import annotations


async def is_refusal(text: str, *, max_text_len: int = 600) -> bool:
    """恒为 False（保留参数以兼容旧调用）。"""
    return False


def is_invalid_context_summary(text: str) -> bool:
    """恒为 False（保留参数以兼容旧调用）。"""
    return False
