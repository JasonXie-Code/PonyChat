from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .mobile_tools import MobileTools, ScreenElement
from .qq_task import QqMessageTask

QQ_PACKAGE = "com.tencent.mobileqq"


class WorkflowStatus(str, Enum):
    COMPLETED = "completed"
    NEEDS_LOGIN = "needs_login"
    QQ_NOT_INSTALLED = "qq_not_installed"
    CONTACT_AMBIGUOUS = "contact_ambiguous"
    FAILED = "failed"


@dataclass(frozen=True)
class WorkflowResult:
    status: WorkflowStatus
    detail: str
    steps: tuple[str, ...] = ()


class QqMessageWorkflow:
    """A deterministic QQ workflow backed entirely by Mobile MCP tools."""

    def __init__(self, tools: MobileTools, device: str, *, settle_seconds: float = 0.8) -> None:
        self.tools = tools
        self.device = device
        self.settle_seconds = settle_seconds
        self.steps: list[str] = []

    def run(self, task: QqMessageTask) -> WorkflowResult:
        try:
            if QQ_PACKAGE not in self.tools.list_apps(self.device):
                return self._result(WorkflowStatus.QQ_NOT_INSTALLED, "模拟器尚未安装 QQ")

            self.tools.launch_app(self.device, QQ_PACKAGE)
            self._record("启动 QQ")
            elements = self._wait_elements(
                lambda current: self._looks_like_login(current)
                or self._find_first(current, contains=("搜索",), editable_ok=True) is not None
                or self._find_editor(current) is not None,
            )
            if self._looks_like_login(elements):
                return self._result(WorkflowStatus.NEEDS_LOGIN, "QQ 需要登录，请在模拟器中完成登录后重试")
            if self._find_editor(elements) is not None and not self._find_first(
                elements,
                contains=("搜索",),
                editable_ok=True,
            ):
                self.tools.press_button(self.device, "BACK")
                self._record("从现有会话返回 QQ 主界面")
                elements = self._wait_elements(
                    lambda current: self._looks_like_login(current)
                    or self._find_first(current, contains=("搜索",), editable_ok=True) is not None,
                )
                if self._looks_like_login(elements):
                    return self._result(WorkflowStatus.NEEDS_LOGIN, "QQ 需要登录，请登录后重试")
            if self._find_first(elements, exact=("取消", "搜索指定内容")):
                self.tools.press_button(self.device, "BACK")
                self._record("返回 QQ 主界面")
                elements = self._wait_elements(
                    lambda current: self._find_first(current, contains=("搜索",), editable_ok=True) is not None,
                )

            search = self._find_first(elements, contains=("搜索",), editable_ok=True)
            if not search:
                return self._result(WorkflowStatus.FAILED, "未在 QQ 主界面找到搜索入口")
            self._click(search)
            self._record("打开搜索")
            self._settle()
            self.tools.clear_text(self.device)
            self.tools.type_text(self.device, task.recipient, submit=False)
            self._record(f"搜索联系人：{task.recipient}")

            results = self._wait_elements(
                lambda current: bool(self._find_contact_section_candidates(current, task.recipient)),
            )
            exact = self._find_contact_section_unique(results, task.recipient)
            if not exact:
                return self._result(
                    WorkflowStatus.CONTACT_AMBIGUOUS,
                    f"未找到唯一的精确联系人「{task.recipient}」，已停止以避免误发",
                )
            self._click(exact)
            self._record(f"进入与 {task.recipient} 的会话")

            chat = self._wait_elements(
                lambda current: self._looks_like_login(current) or self._find_editor(current) is not None,
            )
            if self._looks_like_login(chat):
                return self._result(WorkflowStatus.NEEDS_LOGIN, "QQ 要求登录，请登录后重试")
            editor = self._find_editor(chat)
            if not editor:
                return self._result(WorkflowStatus.FAILED, "未找到 QQ 消息输入框")
            self._click(editor)
            self.tools.clear_text(self.device)
            self.tools.type_text(self.device, task.message, submit=False)
            self._record("填入消息")

            ready = self._wait_elements(
                lambda current: self._find_first(current, exact=("发送",)) is not None,
            )
            send = self._find_first(ready, exact=("发送",))
            if not send:
                return self._result(WorkflowStatus.FAILED, "消息已填入，但未找到发送按钮，未执行发送")
            self._click(send)
            self._record("点击发送")

            after = self._wait_elements(lambda current: self._message_visible(current, task.message))
            if not self._message_visible(after, task.message):
                return self._result(WorkflowStatus.FAILED, "已点击发送，但界面上未验证到消息")
            self._record("验证消息已出现在会话中")
            return self._result(WorkflowStatus.COMPLETED, f"已通过 QQ 向 {task.recipient} 发送消息")
        except Exception as exc:
            return self._result(WorkflowStatus.FAILED, f"QQ 操作异常：{type(exc).__name__}: {exc}")

    def _result(self, status: WorkflowStatus, detail: str) -> WorkflowResult:
        return WorkflowResult(status, detail, tuple(self.steps))

    def _record(self, step: str) -> None:
        self.steps.append(step)

    def _settle(self) -> None:
        if self.settle_seconds > 0:
            time.sleep(self.settle_seconds)

    def _settled_elements(self) -> list[ScreenElement]:
        self._settle()
        return self.tools.list_elements(self.device)

    def _wait_elements(
        self,
        predicate: Callable[[list[ScreenElement]], bool],
        *,
        timeout_seconds: float = 8.0,
    ) -> list[ScreenElement]:
        deadline = time.monotonic() + timeout_seconds
        latest: list[ScreenElement] = []
        while time.monotonic() < deadline:
            latest = self._settled_elements()
            if predicate(latest):
                return latest
        return latest

    def _click(self, element: ScreenElement) -> None:
        x, y = element.center
        self.tools.click(self.device, x, y)

    @staticmethod
    def _looks_like_login(elements: list[ScreenElement]) -> bool:
        text = "|".join(value for element in elements for value in element.strings)
        return any(marker in text for marker in (
            "请先勾选协议", "用户协议和隐私政策", "手机号登录", "QQ号登录",
            "新用户注册", "扫码登录", "一键登录",
        ))

    @staticmethod
    def _find_first(
        elements: list[ScreenElement],
        *,
        exact: tuple[str, ...] = (),
        contains: tuple[str, ...] = (),
        editable_ok: bool = False,
    ) -> ScreenElement | None:
        for element in elements:
            if not editable_ok and not element.strings:
                continue
            if any(value == token for value in element.strings for token in exact):
                return element
            if any(token in value for value in element.strings for token in contains):
                return element
        return None

    @staticmethod
    def _find_exact_unique(elements: list[ScreenElement], text: str) -> ScreenElement | None:
        # The focused search editor also echoes the query as its value. It is not
        # a contact result and must not make an otherwise exact match ambiguous.
        matches = QqMessageWorkflow._find_exact_candidates(elements, text)
        unique = {element.center: element for element in matches}
        return next(iter(unique.values())) if len(unique) == 1 else None

    @staticmethod
    def _find_contact_section_unique(elements: list[ScreenElement], text: str) -> ScreenElement | None:
        matches = QqMessageWorkflow._find_contact_section_candidates(elements, text)
        unique = {element.center: element for element in matches}
        return next(iter(unique.values())) if len(unique) == 1 else None

    @staticmethod
    def _find_contact_section_candidates(elements: list[ScreenElement], text: str) -> list[ScreenElement]:
        most_used_headers = [
            element for element in elements
            if any(value == "最常使用" for value in element.strings)
        ]
        if most_used_headers:
            section_top = min(element.center[1] for element in most_used_headers)
            boundary_markers = ("群聊", "聊天记录", "文件", "搜索综合结果")
            boundaries = [
                element.center[1] for element in elements
                if element.center[1] > section_top
                and any(marker in value for value in element.strings for marker in boundary_markers)
            ]
            section_bottom = min(boundaries, default=10**9)
            candidates = [
                element for element in QqMessageWorkflow._find_exact_candidates(elements, text)
                if section_top < element.center[1] < section_bottom
            ]
            contact_labels = [
                element for element in elements
                if any(value == "联系人" for value in element.strings)
                and section_top < element.center[1] < section_bottom
            ]
            explicitly_typed = [
                candidate for candidate in candidates
                if any(abs(label.center[1] - candidate.center[1]) <= 140 for label in contact_labels)
            ]
            return explicitly_typed or candidates
        headers = [
            element for element in elements
            if any(value == "联系人" for value in element.strings)
        ]
        if not headers:
            return QqMessageWorkflow._find_exact_candidates(elements, text)
        section_top = min(element.center[1] for element in headers)
        boundary_markers = ("聊天记录", "文件", "搜索综合结果")
        boundaries = [
            element.center[1] for element in elements
            if element.center[1] > section_top
            and any(marker in value for value in element.strings for marker in boundary_markers)
        ]
        section_bottom = min(boundaries, default=10**9)
        return [
            element for element in QqMessageWorkflow._find_exact_candidates(elements, text)
            if section_top < element.center[1] < section_bottom
        ]

    @staticmethod
    def _find_exact_candidates(elements: list[ScreenElement], text: str) -> list[ScreenElement]:
        return [
            element for element in elements
            if "EditText" not in element.type
            and any(value == text or value.split(",", 1)[0].strip() == text for value in element.strings)
        ]

    @staticmethod
    def _find_editor(elements: list[ScreenElement]) -> ScreenElement | None:
        return next((element for element in elements if "EditText" in element.type), None) or next(
            (element for element in elements if any(token in value for value in element.strings for token in ("输入", "消息"))),
            None,
        )

    @staticmethod
    def _message_visible(elements: list[ScreenElement], message: str) -> bool:
        return any(message == value for element in elements for value in element.strings)
