"""
Galgame / galgame_lock 分步生成：在 call_llm_payload 层统一记账时的上下文。

用 ContextVar 传递「计费归属用户」（含 X-Chat-Auth 解析后的 effective_username），
避免在 Pydantic ChatRequest 上挂动态属性。
"""
from __future__ import annotations

import contextvars
from typing import Any

_galgame_meter_username: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "galgame_meter_username", default=None
)


def set_galgame_meter_username(username: str | None) -> contextvars.Token[str | None]:
    """进入分步 SSE 任务时设置；返回 token 供 finally reset。"""
    u = (username or "").strip() or None
    return _galgame_meter_username.set(u)


def reset_galgame_meter_username(token: contextvars.Token[str | None]) -> None:
    _galgame_meter_username.reset(token)


def galgame_sequential_metering_kwargs(request: Any) -> dict[str, Any]:
    """
    供 generate/steps 中 call_llm_payload(..., **galgame_sequential_metering_kwargs(request)) 展开。
    仅 galgame / galgame_lock 且能解析到计费用户时：主对话用量；每日次数由 llm_call 在显式记账时自动累加。
    """
    u = _galgame_meter_username.get()
    if not u:
        u = (getattr(request, "username", None) or "").strip() or None
    mode = getattr(request, "mode", "") or ""
    if mode not in ("galgame", "galgame_lock") or not u:
        return {
            "record_usage": "none",
            "usage_meter_username": None,
        }
    return {
        "record_usage": "main",
        "usage_meter_username": u,
    }
