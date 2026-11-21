from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class ContactAliasMemory:
    """User-confirmed nickname to exact app contact mapping."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else self.default_path()

    @staticmethod
    def default_path() -> Path:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "PonyChat" / "Companion" / "contact_aliases.json"

    def resolve(self, app: str, alias: str) -> str | None:
        record = self._load().get(self._key(app, alias))
        exact_name = record.get("exact_name") if isinstance(record, dict) else None
        return str(exact_name) if exact_name else None

    def remember(self, app: str, alias: str, exact_name: str) -> None:
        alias = alias.strip()
        exact_name = exact_name.strip()
        if not alias or not exact_name:
            return
        payload = self._load()
        payload[self._key(app, alias)] = {
            "app": app,
            "alias": alias,
            "exact_name": exact_name,
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps({"version": 1, "aliases": payload}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    @staticmethod
    def _key(app: str, alias: str) -> str:
        return f"{app.lower()}::{alias.strip().lower()}"

    def _load(self) -> dict[str, dict[str, str]]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            aliases = payload.get("aliases", {})
            return aliases if isinstance(aliases, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}
