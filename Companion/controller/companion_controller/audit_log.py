from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any


_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)(密码|口令|验证码|校验码|动态码)\s*(?:是|为|[:：=])\s*[^\s;,；，]+"),
    re.compile(
        r"(?i)(api[_ -]?key|token|authorization|password|passwd|secret)"
        r"\s*[:=]\s*(?:bearer\s+)?[^\s;,；，]+",
    ),
    re.compile(r"(?<!\d)\d{4,8}(?!\d)(?=\s*(?:是|为)?\s*(?:验证码|校验码|动态码))"),
)
_SECRET_KEYS = {"ack_token", "token", "password", "passwd", "secret", "authorization", "cookie"}


def redact_sensitive(value: str) -> str:
    redacted = str(value)
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[已隐藏]", redacted)
    return redacted


def redact_private_context(value: str, *private_values: str) -> str:
    """Redact known per-task private values after credential scrubbing."""
    redacted = redact_sensitive(value)
    for private_value in private_values:
        candidate = str(private_value).strip()
        if candidate:
            redacted = redacted.replace(candidate, "[已隐藏对象]")
    return redacted


def stable_private_reference(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


class PrivacyAuditLog:
    """Append-only task audit without raw messages, credentials or contact names."""

    def __init__(self, path: str | Path | None = None) -> None:
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PonyChat" / "Companion"
        self.path = Path(path) if path else root / "task_audit.jsonl"

    def record(self, event: str, **fields: Any) -> None:
        payload = {
            "time_ms": int(time.time() * 1000),
            "event": event,
            **{key: self._safe_value(key, value) for key, value in fields.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    @classmethod
    def _safe_value(cls, key: str, value: Any) -> Any:
        if key.lower() in _SECRET_KEYS:
            return "[已隐藏]"
        if isinstance(value, dict):
            return {nested: cls._safe_value(nested, item) for nested, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._safe_value(key, item) for item in value]
        if isinstance(value, str):
            return redact_sensitive(value)[:500]
        return value
