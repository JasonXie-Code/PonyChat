from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
import re

from .mobile_tools import ScreenElement


_PRIVATE_ONLINE = re.compile(r"^在线(?:\s*[-·]\s*.+)?$")
_GROUP_SIGNALS = ("群聊", "交流群", "群公告", "@全体成员")


@dataclass(frozen=True)
class QqPrivateChatControls:
    title: ScreenElement
    status: ScreenElement
    editor: ScreenElement
    send: ScreenElement


@dataclass(frozen=True)
class SelectorRule:
    skill: str
    environment: str
    title_identifier: str
    status_identifier: str
    editor_identifier: str
    send_identifier: str
    success_count: int = 1


class AdaptiveSelectorMemory:
    """Stores validated semantic selector rules; coordinates are never persisted."""

    def __init__(self, path: str | Path | None = None) -> None:
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PonyChat" / "Companion"
        self.path = Path(path) if path else root / "adaptive_selectors.json"

    def preferred(self, skill: str, environment: str) -> SelectorRule | None:
        matches = [
            rule for rule in self._load()
            if rule.skill == skill and rule.environment == environment
        ]
        return max(matches, key=lambda rule: rule.success_count, default=None)

    def record(self, rule: SelectorRule) -> None:
        rules = self._load()
        index = next((
            position for position, existing in enumerate(rules)
            if existing.skill == rule.skill
            and existing.environment == rule.environment
            and self._selectors(existing) == self._selectors(rule)
        ), None)
        if index is None:
            rules.append(rule)
        else:
            rules[index] = SelectorRule(
                **{
                    **asdict(rule),
                    "success_count": rules[index].success_count + 1,
                },
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "rules": [asdict(item) for item in rules]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _selectors(rule: SelectorRule) -> tuple[str, ...]:
        return (
            rule.title_identifier,
            rule.status_identifier,
            rule.editor_identifier,
            rule.send_identifier,
        )

    def _load(self) -> list[SelectorRule]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return [SelectorRule(**item) for item in payload.get("rules", [])]
        except (OSError, ValueError, TypeError):
            return []


class QqUiRepairAgent:
    """Repairs QQ selectors from live semantics, then remembers only verified rules."""

    SKILL = "qq_private_reply"

    def __init__(self, memory: AdaptiveSelectorMemory | None = None) -> None:
        self.memory = memory

    def inspect(
        self,
        elements: list[ScreenElement],
        sender: str,
        *,
        environment: str = "android:qq",
    ) -> QqPrivateChatControls | None:
        visible = "|".join(value for item in elements for value in item.strings)
        if any(signal in visible for signal in _GROUP_SIGNALS):
            return None
        preferred = self.memory.preferred(self.SKILL, environment) if self.memory else None
        title = self._choose(
            [item for item in elements if sender in item.strings],
            preferred.title_identifier if preferred else "",
        )
        status = self._choose(
            [item for item in elements if any(_PRIVATE_ONLINE.fullmatch(value) for value in item.strings)],
            preferred.status_identifier if preferred else "",
        )
        editor = self._choose(
            [
                item for item in elements
                if "EditText" in item.type or item.identifier.endswith(":id/input")
            ],
            preferred.editor_identifier if preferred else "",
        )
        send = self._choose(
            [
                item for item in elements
                if "发送" in item.strings or item.identifier.endswith(":id/send_btn")
            ],
            preferred.send_identifier if preferred else "",
        )
        if not all((title, status, editor, send)):
            return None
        return QqPrivateChatControls(title, status, editor, send)

    def remember_success(
        self,
        controls: QqPrivateChatControls,
        *,
        environment: str = "android:qq",
    ) -> None:
        if self.memory is None:
            return
        self.memory.record(SelectorRule(
            skill=self.SKILL,
            environment=environment,
            title_identifier=controls.title.identifier,
            status_identifier=controls.status.identifier,
            editor_identifier=controls.editor.identifier,
            send_identifier=controls.send.identifier,
        ))

    @staticmethod
    def _choose(candidates: list[ScreenElement], preferred_identifier: str) -> ScreenElement | None:
        if preferred_identifier:
            preferred = next(
                (item for item in candidates if item.identifier == preferred_identifier),
                None,
            )
            if preferred is not None:
                return preferred
        return candidates[0] if candidates else None
