"""
Galgame / galgame_lock Agent：统一记账时的上下文。

用 ContextVar 传递「计费归属用户」（含 X-Chat-Auth 解析后的 effective_username），
避免在 Pydantic ChatRequest 上挂动态属性。
"""
from __future__ import annotations

import contextvars
import uuid
from typing import Any

_galgame_meter_username: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "galgame_meter_username", default=None
)


def set_galgame_meter_username(username: str | None) -> contextvars.Token[str | None]:
    """进入游戏 Agent SSE 任务时设置；返回 token 供 finally reset。"""
    u = (username or "").strip() or None
    return _galgame_meter_username.set(u)


def reset_galgame_meter_username(token: contextvars.Token[str | None]) -> None:
    _galgame_meter_username.reset(token)


def game_agent_metering_kwargs(request: Any) -> dict[str, Any]:
    """Return foreground usage attribution for one complete game Agent attempt."""
    u = _galgame_meter_username.get()
    if not u:
        u = (getattr(request, "username", None) or "").strip() or None
    mode = getattr(request, "mode", "") or ""
    if mode not in ("galgame", "galgame_lock") or not u:
        return {
            "record_usage": "none",
            "usage_meter_username": None,
        }
    log_params = getattr(request, '_agent_log_params', None)
    if not log_params:
        trace_id = uuid.uuid4().hex
        log_params = {'trace_id': trace_id, 'request_id': trace_id,
                      'conversation_id': getattr(request, 'conversation_id', None)}
        request._agent_log_params = log_params
    return {
        "record_usage": "main",
        "usage_meter_username": u,
        "agent_debug_params": log_params,
    }
