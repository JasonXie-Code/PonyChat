from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ScreenElement:
    type: str = ""
    text: str = ""
    label: str = ""
    name: str = ""
    value: str = ""
    identifier: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    focused: bool = False

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    @property
    def strings(self) -> tuple[str, ...]:
        return tuple(value.strip() for value in (self.text, self.label, self.name, self.value) if value.strip())


class MobileTools(Protocol):
    def list_apps(self, device: str) -> str: ...
    def launch_app(self, device: str, package_name: str) -> str: ...
    def list_elements(self, device: str) -> list[ScreenElement]: ...
    def click(self, device: str, x: int, y: int) -> str: ...
    def long_press(self, device: str, x: int, y: int, duration_ms: int = 700) -> str: ...
    def swipe(self, device: str, direction: str, *, x: int | None = None, y: int | None = None, distance: int | None = None) -> str: ...
    def type_text(self, device: str, text: str, submit: bool = False) -> str: ...
    def clear_text(self, device: str) -> str: ...
    def press_button(self, device: str, button: str) -> str: ...
    def open_url(self, device: str, url: str) -> str: ...
    def save_screenshot(self, device: str, path: str) -> str: ...


def parse_elements_tool_result(result: str) -> list[ScreenElement]:
    marker = "Found these elements on screen:"
    payload = result.split(marker, 1)[1].strip() if marker in result else result.strip()
    raw = json.loads(payload)
    elements: list[ScreenElement] = []
    for item in raw:
        rect = item.get("coordinates") or {}
        elements.append(ScreenElement(
            type=str(item.get("type") or ""),
            text=str(item.get("text") or ""),
            label=str(item.get("label") or ""),
            name=str(item.get("name") or ""),
            value=str(item.get("value") or ""),
            identifier=str(item.get("identifier") or ""),
            x=int(rect.get("x") or 0),
            y=int(rect.get("y") or 0),
            width=int(rect.get("width") or 0),
            height=int(rect.get("height") or 0),
            focused=bool(item.get("focused")),
        ))
    return elements
