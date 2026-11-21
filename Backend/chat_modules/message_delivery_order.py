from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

from ..config import logger


def _key(username: str | None, character_id: str | None, conversation_id: str | None) -> str:
    u = (username or "").strip()
    c = (character_id or "").strip()
    v = (conversation_id or "").strip()
    return f"{u}\n{c}\n{v}" if u and c and v else ""


@dataclass
class _DeliveryState:
    active_count: int = 0
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    released: asyncio.Event = field(default_factory=asyncio.Event)


_active_deliveries: dict[str, _DeliveryState] = {}


def mark_conversation_delivery_active(
    username: str | None,
    character_id: str | None,
    conversation_id: str | None,
) -> None:
    key = _key(username, character_id, conversation_id)
    if not key:
        return
    state = _active_deliveries.get(key)
    if state is None:
        state = _DeliveryState()
        _active_deliveries[key] = state
    state.active_count += 1
    state.released.clear()


def clear_conversation_delivery_active(
    username: str | None,
    character_id: str | None,
    conversation_id: str | None,
) -> None:
    key = _key(username, character_id, conversation_id)
    if not key:
        return
    state = _active_deliveries.get(key)
    if state is None:
        return
    state.active_count = max(0, state.active_count - 1)
    if state.active_count <= 0:
        state.released.set()
        _active_deliveries.pop(key, None)


async def wait_for_conversation_delivery_slot(
    username: str | None,
    character_id: str | None,
    conversation_id: str | None,
    *,
    timeout_seconds: float | None = None,
    reason: str = "",
) -> bool:
    key = _key(username, character_id, conversation_id)
    if not key:
        return True
    state = _active_deliveries.get(key)
    if state is None:
        return True
    timeout = timeout_seconds
    if timeout is None:
        timeout = float(os.getenv("PONYCHAT_DELIVERY_ORDER_WAIT_SECONDS") or "240")
    try:
        await asyncio.wait_for(state.released.wait(), timeout=max(0.1, float(timeout)))
        return True
    except asyncio.TimeoutError:
        logger.warning(
            "[DeliveryOrder] wait timeout user=%s char=%s conv=%s reason=%s active_for_ms=%s",
            (username or "")[:32],
            (character_id or "")[:32],
            (conversation_id or "")[:12],
            reason or "",
            int(time.time() * 1000) - state.started_at_ms,
        )
        return False
