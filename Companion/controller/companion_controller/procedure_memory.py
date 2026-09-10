from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ProcedureVariant:
    skill: str
    environment: str
    strategy: dict[str, str]
    success_count: int
    last_success_at: str


class ProcedureMemory:
    """Persistent, environment-scoped memory for successful semantic procedures."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else self.default_path()

    @staticmethod
    def default_path() -> Path:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "PonyChat" / "Companion" / "procedure_memory.json"

    def preferred_strategy(
        self,
        skill: str,
        environment: str,
        defaults: dict[str, str],
    ) -> dict[str, str]:
        variants = self._load()
        candidates = [
            item for item in variants
            if item.skill == skill and item.environment == environment
        ]
        if not candidates:
            return dict(defaults)
        best = max(candidates, key=lambda item: (item.success_count, item.last_success_at))
        return {**defaults, **best.strategy}

    def record_success(self, skill: str, environment: str, strategy: dict[str, str]) -> None:
        variants = self._load()
        now = datetime.now(timezone.utc).isoformat()
        match_index = next((
            index for index, item in enumerate(variants)
            if item.skill == skill
            and item.environment == environment
            and item.strategy == strategy
        ), None)
        if match_index is None:
            variants.append(ProcedureVariant(skill, environment, dict(strategy), 1, now))
        else:
            previous = variants[match_index]
            variants[match_index] = ProcedureVariant(
                skill,
                environment,
                dict(strategy),
                previous.success_count + 1,
                now,
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "variants": [asdict(item) for item in variants]}
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def _load(self) -> list[ProcedureVariant]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return [ProcedureVariant(**item) for item in payload.get("variants", [])]
        except (OSError, ValueError, TypeError):
            return []


def detect_browser_environment(elements: list[object]) -> str:
    text = "|".join(
        value
        for element in elements
        for value in getattr(element, "strings", ())
    ).lower()
    if "google chrome" in text or "customize and control" in text:
        return "android:chrome"
    if "firefox" in text:
        return "android:firefox"
    if "microsoft edge" in text:
        return "android:edge"
    return "android:default-browser"
