"""Ephemeral chat image handoff for one-shot model processing.

Chat images are owned by the mobile client. The backend only keeps uploaded
bytes briefly so the following chat request can feed them to the model; it is
not a durable media store for conversation images.
"""

from __future__ import annotations

import secrets
import time
import asyncio
from dataclasses import dataclass
from threading import RLock, Timer
from typing import Optional, Tuple


_CHAT_IMAGE_TRANSFER_TTL_SECONDS = 30 * 60
_CHAT_IMAGE_TRANSFER_MAX_ITEMS = 256
_CHAT_IMAGE_TRANSFER_PREFIX = "tmp_"


@dataclass
class _ChatImageTransfer:
    data: bytes
    mime_type: str
    expires_at: float
    owner: str | None = None
    cleanup: object = None


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
        item = _CACHE.pop(key, None)
        if item and item.cleanup:
            item.cleanup.cancel()
    overflow = len(_CACHE) - _CHAT_IMAGE_TRANSFER_MAX_ITEMS
    if overflow > 0:
        oldest = sorted(_CACHE.items(), key=lambda item: item[1].expires_at)[:overflow]
        for key, _ in oldest:
            item = _CACHE.pop(key, None)
            if item and item.cleanup:
                item.cleanup.cancel()


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


def store_web_image_transfer(data: bytes, mime_type: str, username: str) -> str:
    """No disk/DB copy. Phone receipt or a real timer deletes pending bytes."""
    if not username or not data or len(data) > 8 * 1024 * 1024:
        raise ValueError('Invalid web image transfer')
    with _LOCK:
        _prune_locked()
        if sum(len(item.data) for item in _CACHE.values() if item.owner) + len(data) > 64 * 1024 * 1024:
            raise ValueError('Web image transfer capacity exhausted')
        url = store_chat_image_transfer(data, mime_type)
        filename = url.rsplit('/', 1)[-1]
        _CACHE[filename].owner = username
        try:
            cleanup = asyncio.get_running_loop().call_later(
                _CHAT_IMAGE_TRANSFER_TTL_SECONDS, discard_web_image_transfer, filename, username)
        except RuntimeError:
            cleanup = Timer(_CHAT_IMAGE_TRANSFER_TTL_SECONDS, discard_web_image_transfer, args=(filename, username))
            cleanup.daemon = True
            cleanup.start()
        _CACHE[filename].cleanup = cleanup
    return url


def discard_web_image_transfer(filename: str, username: str) -> bool:
    with _LOCK:
        item = _CACHE.get(filename)
        if item is None:
            return True  # Idempotent receipt after deletion or process restart.
        if not username or item.owner != username:
            return False
        _CACHE.pop(filename, None)
        if item.cleanup:
            item.cleanup.cancel()
        return True
