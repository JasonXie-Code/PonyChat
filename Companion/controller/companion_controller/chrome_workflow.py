from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from .mobile_tools import MobileTools, ScreenElement

CHROME_PACKAGE = "com.android.chrome"


class WebsiteVisionVerifier(Protocol):
    def verify_website(self, screenshot_path: str, expected_host: str) -> bool: ...


class ChromeWorkflowStatus(str, Enum):
    COMPLETED = "completed"
    COMPLETED_UNVERIFIED = "completed_unverified"
    CHROME_NOT_INSTALLED = "chrome_not_installed"
    NEEDS_CHROME_SETUP = "needs_chrome_setup"
    FAILED = "failed"


@dataclass(frozen=True)
class ChromeWorkflowResult:
    status: ChromeWorkflowStatus
    detail: str
    screenshot_path: str = ""
    steps: tuple[str, ...] = ()


class ChromeWebsiteWorkflow:
    def __init__(
        self,
        tools: MobileTools,
        device: str,
        *,
        vision_verifier: WebsiteVisionVerifier | None = None,
        settle_seconds: float = 1.0,
        host_timeout_seconds: float = 12.0,
    ) -> None:
        self.tools = tools
        self.device = device
        self.vision_verifier = vision_verifier
        self.settle_seconds = settle_seconds
        self.host_timeout_seconds = host_timeout_seconds
        self.steps: list[str] = []

    def run(self, url: str, screenshot_path: str = "") -> ChromeWorkflowResult:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return self._result(ChromeWorkflowStatus.FAILED, f"无效网址：{url}")
        try:
            if CHROME_PACKAGE not in self.tools.list_apps(self.device):
                return self._result(ChromeWorkflowStatus.CHROME_NOT_INSTALLED, "设备未安装 Chrome")
            self.tools.press_button(self.device, "HOME")
            self._record("返回系统桌面")
            self._settle()
            self.tools.launch_app(self.device, CHROME_PACKAGE)
            self._record("启动 Chrome")
            first_screen = self._elements()
            if self._needs_setup(first_screen):
                return self._result(
                    ChromeWorkflowStatus.NEEDS_CHROME_SETUP,
                    "Chrome 首次启动需要用户完成协议/账号选择",
                )
            self.tools.open_url(self.device, url)
            self._record(f"打开 {url}")
            elements = self._wait_for_host(parsed.hostname, self.host_timeout_seconds)
            if screenshot_path:
                output = str(Path(screenshot_path).resolve())
                self.tools.save_screenshot(self.device, output)
                self._record("保存结果截图")
            else:
                output = ""
            verified_by_ui = self._contains_host(elements, parsed.hostname)
            verified_by_vision = False
            verification_error = ""
            if not verified_by_ui and output and self.vision_verifier:
                try:
                    verified_by_vision = self.vision_verifier.verify_website(output, parsed.hostname)
                    if verified_by_vision:
                        self._record("DeepSeek 视觉验证页面")
                except Exception as exc:
                    verification_error = f"{type(exc).__name__}: {exc}"
                    self._record("DeepSeek 视觉验证不可用")
            if not verified_by_ui and not verified_by_vision:
                return self._result(
                    ChromeWorkflowStatus.COMPLETED_UNVERIFIED,
                    f"Chrome 已打开 {parsed.hostname} 并保存截图，但自动验收未完成"
                    + (f"：{verification_error}" if verification_error else "：UI 树未暴露地址栏内容"),
                    output,
                )
            return self._result(
                ChromeWorkflowStatus.COMPLETED,
                f"Chrome 已从桌面打开 {parsed.hostname}"
                + ("（视觉验证）" if verified_by_vision else "（UI 树验证）"),
                output,
            )
        except Exception as exc:
            return self._result(ChromeWorkflowStatus.FAILED, f"Chrome 操作异常：{type(exc).__name__}: {exc}")

    def _result(self, status: ChromeWorkflowStatus, detail: str, screenshot_path: str = "") -> ChromeWorkflowResult:
        return ChromeWorkflowResult(status, detail, screenshot_path, tuple(self.steps))

    def _record(self, step: str) -> None:
        self.steps.append(step)

    def _settle(self) -> None:
        if self.settle_seconds:
            time.sleep(self.settle_seconds)

    def _elements(self) -> list[ScreenElement]:
        self._settle()
        return self.tools.list_elements(self.device)

    def _wait_for_host(self, host: str, timeout_seconds: float = 12.0) -> list[ScreenElement]:
        deadline = time.monotonic() + timeout_seconds
        latest: list[ScreenElement] = []
        while time.monotonic() < deadline:
            latest = self._elements()
            if self._contains_host(latest, host):
                break
        return latest

    @staticmethod
    def _contains_host(elements: list[ScreenElement], host: str) -> bool:
        expected = host.removeprefix("www.").lower()
        return any(expected in value.lower() for element in elements for value in element.strings)

    @staticmethod
    def _needs_setup(elements: list[ScreenElement]) -> bool:
        text = "|".join(value for element in elements for value in element.strings)
        return any(marker in text for marker in (
            "Accept & continue", "Chrome Terms of Service", "Use without an account",
            "接受并继续", "Chrome 服务条款", "不登录使用",
        ))
