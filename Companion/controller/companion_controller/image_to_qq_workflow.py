from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

from .image_share_task import BrowserImageToQqTask
from .contact_memory import ContactAliasMemory
from .mobile_tools import MobileTools, ScreenElement
from .procedure_memory import ProcedureMemory, detect_browser_environment
from .qq_workflow import QQ_PACKAGE


class ImageShareStatus(str, Enum):
    COMPLETED = "completed"
    NEEDS_LOGIN = "needs_login"
    QQ_NOT_INSTALLED = "qq_not_installed"
    CONTACT_AMBIGUOUS = "contact_ambiguous"
    NEEDS_CONTACT_SELECTION = "needs_contact_selection"
    SEND_UNVERIFIED = "send_unverified"
    FAILED = "failed"


@dataclass(frozen=True)
class ImageShareResult:
    status: ImageShareStatus
    detail: str
    steps: tuple[str, ...] = ()
    screenshot_path: str = ""
    contact_candidates: tuple[str, ...] = ()


class BrowserImageToQqWorkflow:
    SKILL = "browser_search_image_share_to_qq"
    DEFAULT_STRATEGY = {
        "search_provider": "google_images",
        "share_action": "semantic_long_press",
        "share_target": "qq",
    }

    def __init__(
        self,
        tools: MobileTools,
        device: str,
        *,
        memory: ProcedureMemory | None = None,
        contact_memory: ContactAliasMemory | None = None,
        settle_seconds: float = 0.8,
    ) -> None:
        self.tools = tools
        self.device = device
        self.memory = memory or ProcedureMemory()
        self.contact_memory = contact_memory or ContactAliasMemory()
        self.settle_seconds = settle_seconds
        self.steps: list[str] = []

    def search_images(self, query: str, screenshot_path: str = "") -> ImageShareResult:
        """Open verified image-search results and leave them visible on the device."""
        self.steps = []
        try:
            opened = self._open_image_results(query)
            if isinstance(opened, ImageShareResult):
                return opened
            _, environment, strategy = opened
            output = ""
            if screenshot_path:
                output = str(Path(screenshot_path).resolve())
                self.tools.save_screenshot(self.device, output)
                self._record("保存图片搜索结果截图")
            self.memory.record_success(self.SKILL, environment, strategy)
            self._record(f"记住 {environment} 的成功流程")
            return self._result(
                ImageShareStatus.COMPLETED,
                f"已在默认浏览器打开“{query}”的图片搜索结果",
                output,
            )
        except Exception as exc:
            return self._result(ImageShareStatus.FAILED, f"图片搜索操作异常：{type(exc).__name__}: {exc}")

    def run(
        self,
        task: BrowserImageToQqTask,
        screenshot_path: str = "",
        *,
        preferred_provider: str = "",
    ) -> ImageShareResult:
        self.steps = []
        try:
            if QQ_PACKAGE not in self.tools.list_apps(self.device):
                return self._result(ImageShareStatus.QQ_NOT_INSTALLED, "设备尚未安装 QQ")
            opened = self._open_image_results(task.query, preferred_provider)
            if isinstance(opened, ImageShareResult):
                return opened
            image_results, environment, strategy = opened

            share_image = self._find_shareable_image(task.query, image_results)
            if not share_image:
                return self._result(
                    ImageShareStatus.FAILED,
                    "缩略图和展开大图均未出现“分享图片”操作，需要恢复浏览器后重试",
                )
            strategy["share_action"] = next(iter(share_image.strings), "semantic_long_press")
            self._click(share_image)
            self._record("选择分享图片")

            share_sheet = self._wait_elements(lambda current: self._find_exact(current, "QQ") is not None)
            qq = self._find_exact(share_sheet, "QQ")
            if not qq:
                self.tools.swipe(self.device, "left", y=2200, distance=600)
                self._record("QQ 未显示，自动滚动分享目标")
                share_sheet = self._wait_elements(lambda current: self._find_exact(current, "QQ") is not None, timeout_seconds=5)
                qq = self._find_exact(share_sheet, "QQ")
            if not qq:
                return self._result(ImageShareStatus.FAILED, "系统分享面板中未找到 QQ")
            self._click(qq)
            self._record("在系统分享面板选择 QQ")

            requested_recipient = task.recipient
            target_recipient = self.contact_memory.resolve("qq", requested_recipient) or requested_recipient
            if target_recipient != requested_recipient:
                self._record(f"使用已记住的小名：{requested_recipient} → {target_recipient}")
            contacts = self._wait_elements(
                lambda current: self._looks_like_login(current)
                or bool(self._contact_candidates(current, target_recipient))
                or self._find_editor(current, "搜索") is not None,
            )
            if self._looks_like_login(contacts):
                return self._result(ImageShareStatus.NEEDS_LOGIN, "QQ 需要登录，请完成登录后重试")
            candidates = self._contact_candidates(contacts, target_recipient)
            if not candidates:
                search = self._find_editor(contacts, "搜索")
                if not search:
                    return self._result(ImageShareStatus.FAILED, "QQ 分享页未找到好友搜索入口")
                self._click(search)
                self.tools.clear_text(self.device)
                self.tools.type_text(self.device, target_recipient, submit=False)
                self._record(f"在 QQ 中搜索联系人：{target_recipient}")
                contacts = self._wait_elements(
                    lambda current: bool(self._contact_candidates(current, target_recipient)),
                )
                candidates = self._contact_candidates(contacts, target_recipient)
            if len(candidates) > 1:
                return self._result(
                    ImageShareStatus.NEEDS_CONTACT_SELECTION,
                    f"“{requested_recipient}”匹配到多个联系人，请在当前 QQ 列表中选择；选择后可记住这个小名",
                    contact_candidates=tuple(candidates),
                )
            if not candidates:
                return self._result(
                    ImageShareStatus.CONTACT_AMBIGUOUS,
                    f"未找到联系人「{target_recipient}」，已停止以避免误发",
                )
            contact = self._find_exact_contact_row(contacts, candidates[0])
            if not contact:
                self._record("联系人节点变化，自动重新观察")
                contacts = self._wait_elements(
                    lambda current: self._find_exact_contact_row(current, candidates[0]) is not None,
                    timeout_seconds=5,
                )
                contact = self._find_exact_contact_row(contacts, candidates[0])
            if not contact:
                return self._result(ImageShareStatus.FAILED, "重新观察后联系人入口仍不可操作")
            resolved_recipient = candidates[0]
            self._click(contact)
            self._record(f"选择唯一联系人：{resolved_recipient}")

            confirmation = self._wait_elements(lambda current: self._share_confirmation(current, resolved_recipient))
            if not self._share_confirmation(confirmation, resolved_recipient):
                return self._result(ImageShareStatus.FAILED, "QQ 未显示包含图片预览的发送确认页")
            send = self._find_exact(confirmation, "发送")
            if not send:
                return self._result(ImageShareStatus.FAILED, "QQ 发送确认页缺少发送按钮，未执行发送")
            self._click(send)
            self._record("确认发送图片")

            after = self._wait_elements(lambda current: not self._share_confirmation(current, resolved_recipient))
            if self._share_confirmation(after, resolved_recipient):
                return self._result(
                    ImageShareStatus.SEND_UNVERIFIED,
                    "已点击发送，但 QQ 确认页未关闭；为避免重复发送，需要人工确认",
                )
            if screenshot_path:
                output = str(Path(screenshot_path).resolve())
                self.tools.save_screenshot(self.device, output)
                self._record("保存发送结果截图")
            else:
                output = ""
            self.memory.record_success(self.SKILL, environment, strategy)
            self._record(f"记住 {environment} 的成功流程")
            return self._result(
                ImageShareStatus.COMPLETED,
                f"已从默认浏览器搜索“{task.query}”图片并通过 QQ 发送给 {resolved_recipient}",
                output,
            )
        except Exception as exc:
            return self._result(ImageShareStatus.FAILED, f"图片分享操作异常：{type(exc).__name__}: {exc}")

    def _open_image_results(
        self,
        query: str,
        preferred_provider: str = "",
    ) -> tuple[list[ScreenElement], str, dict[str, str]] | ImageShareResult:
        self.tools.press_button(self.device, "HOME")
        self._record("返回系统桌面")
        self._settle()
        self.tools.open_url(self.device, self._search_url(query, "google_images"))
        self._record(f"用默认浏览器搜索图片：{query}")
        results = self._wait_elements(
            lambda current: bool(self._find_image_results(current, query)),
            timeout_seconds=15,
        )
        environment = detect_browser_environment(results)
        strategy = self.memory.preferred_strategy(self.SKILL, environment, self.DEFAULT_STRATEGY)
        if preferred_provider:
            strategy["search_provider"] = preferred_provider
        if strategy["search_provider"] != "google_images":
            self.tools.open_url(self.device, self._search_url(query, strategy["search_provider"]))
            results = self._wait_elements(
                lambda current: bool(self._find_image_results(current, query)),
                timeout_seconds=15,
            )
        if not self._find_image_results(results, query):
            self.tools.open_url(self.device, self._search_url(query, "bing_images"))
            self._record("未识别到结果，自动切换 Bing 图片搜索")
            results = self._wait_elements(
                lambda current: bool(self._find_image_results(current, query)),
                timeout_seconds=15,
            )
            strategy["search_provider"] = "bing_images"
        image_results = self._find_image_results(results, query)
        if not image_results:
            return self._result(ImageShareStatus.FAILED, "已自动更换图片搜索源，但仍未观察到图片结果")
        return image_results, environment, strategy

    def _find_shareable_image(
        self,
        query: str,
        initial_results: list[ScreenElement],
    ) -> ScreenElement | None:
        results = initial_results
        for index in range(min(3, len(results))):
            current_results = results if index == 0 else (
                self._find_image_results(self.tools.list_elements(self.device), query) or results
            )
            if index >= len(current_results):
                break
            image_result = current_results[index]
            image_x = image_result.x + image_result.width // 2
            image_y = image_result.y + min(image_result.height // 3, 260)
            self.tools.long_press(self.device, image_x, image_y, 700)
            self._record("长按相关图片结果" if index == 0 else f"自动尝试第 {index + 1} 个相关图片结果")
            menu = self._wait_elements(
                lambda current: self._find_share_image(current) is not None
                or self._looks_like_image_menu(current),
                timeout_seconds=4,
            )
            share_image = self._find_share_image(menu)
            if share_image:
                return share_image
            if self._looks_like_image_menu(menu):
                self.tools.press_button(self.device, "BACK")
                self._settle()

            refreshed = self._find_image_results(self.tools.list_elements(self.device), query)
            if not refreshed:
                self.tools.press_button(self.device, "BACK")
                refreshed = self._wait_elements(
                    lambda current: bool(self._find_image_results(current, query)),
                    timeout_seconds=5,
                )
                refreshed = self._find_image_results(refreshed, query)
            if not refreshed:
                continue
            expanded_target = refreshed[min(index, len(refreshed) - 1)]
            self._click(expanded_target)
            self._record(f"展开第 {index + 1} 个图片结果后重试")
            expanded = self._wait_elements(lambda current: bool(current), timeout_seconds=3)
            large_image = self._largest_image_candidate(expanded)
            if large_image:
                self.tools.long_press(self.device, *large_image.center, 800)
                menu = self._wait_elements(
                    lambda current: self._find_share_image(current) is not None
                    or self._looks_like_image_menu(current),
                    timeout_seconds=4,
                )
                share_image = self._find_share_image(menu)
                if share_image:
                    return share_image
                if self._looks_like_image_menu(menu):
                    self.tools.press_button(self.device, "BACK")
            self.tools.press_button(self.device, "BACK")
            results = self._wait_elements(
                lambda current: bool(self._find_image_results(current, query)),
                timeout_seconds=5,
            )
        return None

    def resume_contact_selection(
        self,
        selected_contact: str,
        *,
        remember_as: str = "",
        screenshot_path: str = "",
    ) -> ImageShareResult:
        """Continue a paused QQ share after a user chooses one visible candidate."""
        try:
            contacts = self.tools.list_elements(self.device)
            contact = self._find_exact_contact_row(contacts, selected_contact)
            if not contact:
                return self._result(ImageShareStatus.FAILED, "所选联系人已不在当前 QQ 列表，请重新执行任务")
            self._click(contact)
            self._record(f"用户选择联系人：{selected_contact}")
            confirmation = self._wait_elements(lambda current: self._share_confirmation(current, selected_contact))
            if not self._share_confirmation(confirmation, selected_contact):
                return self._result(ImageShareStatus.FAILED, "QQ 未显示所选联系人的图片发送确认页")
            send = self._find_exact(confirmation, "发送")
            if not send:
                return self._result(ImageShareStatus.FAILED, "未找到发送按钮，未执行发送")
            self._click(send)
            self._record("确认发送图片")
            after = self._wait_elements(lambda current: not self._share_confirmation(current, selected_contact))
            if self._share_confirmation(after, selected_contact):
                return self._result(ImageShareStatus.FAILED, "发送确认页未关闭")
            if remember_as:
                self.contact_memory.remember("qq", remember_as, selected_contact)
                self._record(f"记住联系人小名：{remember_as} → {selected_contact}")
            output = ""
            if screenshot_path:
                output = str(Path(screenshot_path).resolve())
                self.tools.save_screenshot(self.device, output)
                self._record("保存发送结果截图")
            return self._result(
                ImageShareStatus.COMPLETED,
                f"已通过 QQ 向 {selected_contact} 发送图片",
                output,
            )
        except Exception as exc:
            return self._result(ImageShareStatus.FAILED, f"联系人选择续办异常：{type(exc).__name__}: {exc}")

    def _result(
        self,
        status: ImageShareStatus,
        detail: str,
        screenshot_path: str = "",
        contact_candidates: tuple[str, ...] = (),
    ) -> ImageShareResult:
        return ImageShareResult(status, detail, tuple(self.steps), screenshot_path, contact_candidates)

    def _record(self, step: str) -> None:
        self.steps.append(step)

    def _settle(self) -> None:
        if self.settle_seconds:
            time.sleep(self.settle_seconds)

    def _wait_elements(
        self,
        predicate: Callable[[list[ScreenElement]], bool],
        *,
        timeout_seconds: float = 10,
    ) -> list[ScreenElement]:
        deadline = time.monotonic() + timeout_seconds
        latest: list[ScreenElement] = []
        while time.monotonic() < deadline:
            self._settle()
            latest = self.tools.list_elements(self.device)
            if predicate(latest):
                return latest
        return latest

    def _click(self, element: ScreenElement) -> None:
        self.tools.click(self.device, *element.center)

    @staticmethod
    def _search_url(query: str, provider: str) -> str:
        encoded = quote_plus(query)
        if provider == "bing_images":
            return f"https://www.bing.com/images/search?q={encoded}"
        return f"https://www.google.com/search?tbm=isch&q={encoded}"

    @staticmethod
    def _find_image_result(elements: list[ScreenElement], query: str) -> ScreenElement | None:
        return next(iter(BrowserImageToQqWorkflow._find_image_results(elements, query)), None)

    @staticmethod
    def _find_image_results(elements: list[ScreenElement], query: str) -> list[ScreenElement]:
        tokens = [token for token in query.replace("的", " ").split() if token]
        candidates = [
            element for element in elements
            if element.y > 450
            and element.width >= 180
            and element.height >= 180
            and element.strings
            and any(token in value for token in tokens for value in element.strings)
            and ("Button" in element.type or "View" in element.type)
        ]
        return sorted(candidates, key=lambda item: (item.y, item.x))

    @staticmethod
    def _find_share_image(elements: list[ScreenElement]) -> ScreenElement | None:
        aliases = ("Share image", "分享图片", "分享图像", "共享图片", "共享图像")
        return next((
            element for element in elements
            if any(alias.lower() in value.lower() for alias in aliases for value in element.strings)
        ), None)

    @staticmethod
    def _looks_like_image_menu(elements: list[ScreenElement]) -> bool:
        menu_words = (
            "open image", "download image", "copy image", "search image", "share image",
            "打开图片", "下载图片", "复制图片", "搜索图片", "分享图片",
        )
        return any(
            word in value.lower()
            for element in elements
            for value in element.strings
            for word in menu_words
        )

    @staticmethod
    def _largest_image_candidate(elements: list[ScreenElement]) -> ScreenElement | None:
        candidates = [
            element for element in elements
            if element.y > 300
            and element.width >= 240
            and element.height >= 240
            and ("Image" in element.type or "View" in element.type or "Button" in element.type)
        ]
        return max(candidates, key=lambda item: item.width * item.height, default=None)

    @staticmethod
    def _find_exact(elements: list[ScreenElement], text: str) -> ScreenElement | None:
        matches = [element for element in elements if any(value == text for value in element.strings)]
        return max(matches, key=lambda item: item.width * item.height, default=None)

    @staticmethod
    def _find_editor(elements: list[ScreenElement], hint: str) -> ScreenElement | None:
        return next((
            element for element in elements
            if "EditText" in element.type and any(hint in value for value in element.strings)
        ), None)

    @staticmethod
    def _find_contact_row(elements: list[ScreenElement], recipient: str) -> ScreenElement | None:
        candidates = BrowserImageToQqWorkflow._contact_candidates(elements, recipient)
        if len(candidates) != 1:
            return None
        return BrowserImageToQqWorkflow._find_exact_contact_row(elements, candidates[0])

    @staticmethod
    def _contact_candidates(elements: list[ScreenElement], recipient: str) -> list[str]:
        names = {
            value.split(",", 1)[0].strip()
            for element in elements
            if "EditText" not in element.type
            for value in element.strings
            if BrowserImageToQqWorkflow._recipient_matches(value, recipient)
        }
        return sorted(names)

    @staticmethod
    def _find_exact_contact_row(elements: list[ScreenElement], exact_name: str) -> ScreenElement | None:
        matches = [
            element for element in elements
            if "EditText" not in element.type
            and any(value.split(",", 1)[0].strip() == exact_name for value in element.strings)
        ]
        if not matches:
            return None
        # QQ can render the same exact contact both as a recommended-person tile
        # and as a recent-chat row. They are two entry points to one identity,
        # not two ambiguous contacts; prefer the largest row-like target.
        return max(matches, key=lambda item: item.width * item.height)

    @staticmethod
    def _recipient_matches(value: str, recipient: str) -> bool:
        display = value.split(",", 1)[0].strip()
        return display == recipient or display.startswith(f"{recipient}@")

    @staticmethod
    def _matched_recipient_name(element: ScreenElement, recipient: str) -> str:
        return next(
            value.split(",", 1)[0].strip()
            for value in element.strings
            if BrowserImageToQqWorkflow._recipient_matches(value, recipient)
        )

    @staticmethod
    def _looks_like_login(elements: list[ScreenElement]) -> bool:
        text = "|".join(value for element in elements for value in element.strings)
        return any(marker in text for marker in (
            "手机号登录", "QQ号登录", "扫码登录", "用户协议和隐私政策", "一键登录",
        ))

    @staticmethod
    def _share_confirmation(elements: list[ScreenElement], recipient: str) -> bool:
        values = [value for element in elements for value in element.strings]
        return (
            any(value == recipient for value in values)
            and any("图片预览" in value for value in values)
            and "发送" in values
        )
