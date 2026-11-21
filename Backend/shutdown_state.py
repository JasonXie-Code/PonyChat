from __future__ import annotations

import time
from typing import Optional

_shutdown_requested = False
_shutdown_reason: Optional[str] = None
_shutdown_requested_at: Optional[float] = None


def request_shutdown(reason: str = "shutdown") -> None:
    global _shutdown_requested, _shutdown_reason, _shutdown_requested_at
    if _shutdown_requested:
        return
    _shutdown_requested = True
    _shutdown_reason = str(reason or "shutdown")
    _shutdown_requested_at = time.time()


def is_shutdown_requested() -> bool:
    return _shutdown_requested


def shutdown_reason() -> str:
    return _shutdown_reason or ""


def shutdown_requested_at() -> Optional[float]:
    return _shutdown_requested_at
