"""Ephemeral chat image handoff for one-shot model processing.

Chat images are owned by the mobile client. The backend only keeps uploaded
bytes briefly so the following chat request can feed them to the model; it is
not a durable media store for conversation images.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from threading import RLock
from typing import Optional, Tuple


_CHAT_IMAGE_TRANSFER_TTL_SECONDS = 30 * 60
_CHAT_IMAGE_TRANSFER_MAX_ITEMS = 256
_CHAT_IMAGE_TRANSFER_PREFIX = "tmp_"


@dataclass
class _ChatImageTransfer:
    data: bytes
    mime_type: str
    expires_at: float


_LOCK = RLock()
_CACHE: dict[str, _ChatImageTransfer] = {}


def _mime_to_ext(mime_type: str) -> str:
    normalized = (mime_type or "").lower().strip()
    if normalized in {"image/png", "image/apng"}:
        return "png"
    if normalized == "image/webp":
        return "webp"
    return "jpg"


def _prune_locked(now: Optional[float] = None) -> None:
    current = now if now is not None else time.time()
    expired = [key for key, value in _CACHE.items() if value.expires_at <= current]
    for key in expired:
        _CACHE.pop(key, None)
    overflow = len(_CACHE) - _CHAT_IMAGE_TRANSFER_MAX_ITEMS
    if overflow > 0:
        oldest = sorted(_CACHE.items(), key=lambda item: item[1].expires_at)[:overflow]
        for key, _ in oldest:
            _CACHE.pop(key, None)


def store_chat_image_transfer(data: bytes, mime_type: str) -> str:
    if not data:
        raise ValueError("empty image data")
    now = time.time()
    ext = _mime_to_ext(mime_type)
    token = f"{_CHAT_IMAGE_TRANSFER_PREFIX}{secrets.token_urlsafe(18)}.{ext}"
    with _LOCK:
        _prune_locked(now)
        _CACHE[token] = _ChatImageTransfer(
            data=bytes(data),
            mime_type=mime_type,
            expires_at=now + _CHAT_IMAGE_TRANSFER_TTL_SECONDS,
        )
    return f"/chat_images/{token}"


def load_chat_image_transfer(filename_or_url: str) -> Optional[Tuple[bytes, str]]:
    raw = (filename_or_url or "").strip()
    if raw.startswith("/chat_images/"):
        raw = raw.rsplit("/", 1)[-1]
    if not raw.startswith(_CHAT_IMAGE_TRANSFER_PREFIX):
        return None
    now = time.time()
    with _LOCK:
        _prune_locked(now)
        item = _CACHE.get(raw)
        if item is None or item.expires_at <= now:
            _CACHE.pop(raw, None)
            return None
        return item.data, item.mime_type
