from __future__ import annotations

import json
import io
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import time
from typing import TextIO

from .adaptive_repair import AdaptiveSelectorMemory, QqUiRepairAgent
from .audit_log import PrivacyAuditLog, redact_private_context, stable_private_reference
from .backend_agent_brain import BackendMobileAgentBrain
from .general_agent import AgentStatus, BlockerPolicy, GeneralDeviceAgent
from .image_share_task import BrowserImageToQqTask
from .image_to_qq_workflow import BrowserImageToQqWorkflow, ImageShareStatus
from .mobile_tools import MobileTools, ScreenElement
from .qq_command import QqDeviceCommand, parse_qq_device_command
from .qq_task import QqMessageTask
from .qq_workflow import QqMessageWorkflow, WorkflowStatus
from .web_query_workflow import BrowserWebQueryWorkflow


@dataclass(frozen=True)
class QqReplyEvent:
    event_id: str
    ack_token: str
    sender: str
    response: str
    instruction: str = ""
    kind: str = "chat"
    source: str = ""

    @classmethod
    def from_log_line(cls, line: str) -> "QqReplyEvent":
        data = json.loads(line.strip())
        return cls(
            event_id=str(data["event_id"]),
            ack_token=str(data["ack_token"]),
            sender=str(data["sender"]),
            response=str(data.get("response") or ""),
            instruction=str(data.get("instruction") or ""),
            kind=str(data.get("kind") or "chat"),
            source=str(data.get("source") or ""),
        )


class QqReplyExecutor:
    """Executes an already-authorized private reply using only Mobile MCP tools."""

    def __init__(
        self,
        tools: MobileTools,
        device: str,
        *,
        settle_seconds: float = 0.4,
        repair_agent: QqUiRepairAgent | None = None,
    ) -> None:
        self.tools = tools
        self.device = device
        self.settle_seconds = settle_seconds
        self.repair_agent = repair_agent or QqUiRepairAgent()

    def execute(self, event: QqReplyEvent) -> tuple[bool, str]:
        try:
            before = self.tools.list_elements(self.device)
            controls = self.repair_agent.inspect(before, event.sender)
            if controls is None:
                return False, "发送前页面不再是已确认的目标私聊"
            previous_count = self._exact_count(before, event.response)
            self.tools.click(self.device, *controls.editor.center)
            self.tools.clear_text(self.device)
            self.tools.type_text(self.device, event.response, submit=False)
            ready = self._wait(lambda items: self.repair_agent.inspect(items, event.sender) is not None)
            ready_controls = self.repair_agent.inspect(ready, event.sender)
            if ready_controls is None:
                return False, "回复已输入，但发送按钮不可用"
            self.tools.click(self.device, *ready_controls.send.center)
            after = self._wait(
                lambda items: self._exact_count(items, event.response) > previous_count,
                timeout_seconds=10.0,
            )
            if self._exact_count(after, event.response) <= previous_count:
                return False, "点击发送后未验证到新增回复"
            self.repair_agent.remember_success(ready_controls)
            return True, "Mobile MCP 已输入、发送并验证新增消息"
        except Exception as exc:
            if isinstance(exc, UserStoppedError):
                raise
            return False, f"Mobile MCP 执行异常：{type(exc).__name__}: {exc}"

    def _wait(self, predicate, *, timeout_seconds: float = 6.0) -> list[ScreenElement]:
        deadline = time.monotonic() + timeout_seconds
        latest: list[ScreenElement] = []
        while time.monotonic() < deadline:
            if self.settle_seconds:
                time.sleep(self.settle_seconds)
            latest = self.tools.list_elements(self.device)
            if predicate(latest):
                return latest
        return latest

    @staticmethod
    def _find_exact(elements: list[ScreenElement], value: str) -> ScreenElement | None:
        return next((item for item in elements if value in item.strings), None)

    @staticmethod
    def _exact_count(elements: list[ScreenElement], value: str) -> int:
        return sum(1 for item in elements if value in item.strings)


class ControllerLeasedMobileTools:
    """Marks host-injected input so Android does not treat it as a user interruption."""

    MUTATING_METHODS = {
        "launch_app", "click", "long_press", "swipe", "type_text", "clear_text",
        "press_button", "open_url",
    }

    def __init__(
        self,
        tools: MobileTools,
        device: str,
        adb: str,
        *,
        monitor_physical_touches: bool = True,
    ) -> None:
        self._tools = tools
        self._device = device
        self._adb = adb
        self._event: QqReplyEvent | None = None
        self._touch_detected = threading.Event()
        self._monitor = PhysicalTouchMonitor(adb, device, self._on_physical_touch)
        self._monitor_physical_touches = monitor_physical_touches

    @contextmanager
    def for_event(self, event: QqReplyEvent):
        previous = self._event
        self._event = event
        self._touch_detected.clear()
        if self._monitor_physical_touches:
            self._monitor.start()
        try:
            yield
        finally:
            if self._monitor_physical_touches:
                self._monitor.stop()
            self._event = previous
            self._touch_detected.clear()

    def __getattr__(self, name: str):
        target = getattr(self._tools, name)
        if name not in self.MUTATING_METHODS:
            return target

        def leased_call(*args, **kwargs):
            event = self._event
            if event is None:
                return target(*args, **kwargs)
            self.await_user_control()
            self._signal("top.ponychat.companion.action.AGENT_INPUT_BEGIN", event, timeout_ms=10_000)
            try:
                result = target(*args, **kwargs)
            finally:
                self._signal("top.ponychat.companion.action.AGENT_INPUT_END", event)
            self.await_user_control()
            return result

        return leased_call

    def await_user_control(self) -> None:
        event = self._event
        if event is None or not self._touch_detected.is_set():
            return
        while True:
            state = self._query_control(event)
            if state == 1:
                self._touch_detected.clear()
                return
            if state in {0, 3}:
                raise UserStoppedError("用户已停止本次任务")
            time.sleep(0.2)

    def _on_physical_touch(self) -> None:
        event = self._event
        if event is None or self._touch_detected.is_set():
            return
        try:
            self._signal("top.ponychat.companion.action.PHYSICAL_TOUCH", event)
            self._touch_detected.set()
        except Exception:
            return

    def _query_control(self, event: QqReplyEvent) -> int:
        completed = self._run_broadcast(
            "top.ponychat.companion.action.QUERY_CONTROL",
            event,
        )
        match = re.search(r"result=(-?\d+)", completed.stdout)
        return int(match.group(1)) if match else 0

    def _signal(self, action: str, event: QqReplyEvent, *, timeout_ms: int = 0) -> None:
        completed = self._run_broadcast(action, event, timeout_ms=timeout_ms)
        if completed.returncode != 0:
            raise RuntimeError(f"无法建立 Controller 输入租约：{completed.stderr.strip()}")

    def _run_broadcast(
        self,
        action: str,
        event: QqReplyEvent,
        *,
        timeout_ms: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            self._adb, "-s", self._device, "shell", "am", "broadcast",
            "-n", "top.ponychat.companion/.reply.QqReplyResultReceiver",
            "-a", action,
            "--es", "event_id", event.event_id,
            "--es", "ack_token", event.ack_token,
        ]
        if timeout_ms:
            command.extend(("--ei", "timeout_ms", str(timeout_ms)))
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )


class UserStoppedError(RuntimeError):
    pass


class PhysicalTouchMonitor:
    TOUCH_DOWN = re.compile(r"(?:ABS_MT_TRACKING_ID\s+(?!ffffffff)|BTN_TOUCH\s+DOWN)", re.I)

    def __init__(self, adb: str, device: str, on_touch) -> None:
        self.adb = adb
        self.device = device
        self.on_touch = on_touch
        self.process: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.process is not None:
            return
        self.process = subprocess.Popen(
            [self.adb, "-s", self.device, "shell", "getevent", "-lt"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.thread = threading.Thread(target=self._consume, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        self.thread = None

    def _consume(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            if self.TOUCH_DOWN.search(line):
                self.on_touch()


class QqDeviceCommandExecutor:
    """Routes parsed private QQ commands to reusable Mobile MCP workflows."""

    def __init__(self, tools: MobileTools, device: str) -> None:
        self.workflow = BrowserImageToQqWorkflow(tools, device)
        self.web_workflow = BrowserWebQueryWorkflow(tools, device)
        self.qq_workflow = QqMessageWorkflow(tools, device)

    def execute(self, event: QqReplyEvent, command: QqDeviceCommand) -> tuple[bool, str]:
        # A QQ-originated result is capability-bound to the private sender. Never honor a
        # recipient supplied inside the instruction, because that would let one user make
        # Companion disclose data or message a different user.
        origin_task = BrowserImageToQqTask(command.query, event.sender)
        if command.kind in {"weather_search", "article_search", "video_search", "web_search"}:
            return self._execute_web_query(event, command)
        if command.kind not in {"image_search", "image_share_to_qq"}:
            return False, f"尚不支持的设备指令：{command.kind}"
        attempts: list[str] = []
        providers = ("google_images", "bing_images", "google_images")
        for attempt, provider in enumerate(providers, start=1):
            result = self.workflow.run(origin_task, preferred_provider=provider)
            attempts.append(f"第{attempt}轮：{result.detail}")
            if result.status is ImageShareStatus.COMPLETED:
                return True, f"{result.detail}（共尝试 {attempt} 轮）"
            if result.status in {
                ImageShareStatus.NEEDS_LOGIN,
                ImageShareStatus.NEEDS_CONTACT_SELECTION,
                ImageShareStatus.CONTACT_AMBIGUOUS,
                ImageShareStatus.QQ_NOT_INSTALLED,
                ImageShareStatus.SEND_UNVERIFIED,
            }:
                return False, result.detail
            if "用户已停止" in result.detail:
                return False, result.detail
            if attempt < len(providers):
                self.workflow.tools.press_button(self.workflow.device, "HOME")
                time.sleep(1.0)
        return False, "；".join(attempts)

    def _execute_web_query(
        self,
        event: QqReplyEvent,
        command: QqDeviceCommand,
    ) -> tuple[bool, str]:
        result = self.web_workflow.run(command)
        if not result.success:
            return False, f"联网查询失败：{result.detail}；可手动查看：{result.url}"
        sent = self.qq_workflow.run(QqMessageTask(event.sender, result.message))
        if sent.status is WorkflowStatus.COMPLETED:
            return True, f"{result.detail}，结果已返回给原发送者 {event.sender}"
        return False, f"查询成功但回传失败：{sent.detail}；查询链接：{result.url}"


class AutonomousTaskRecovery:
    """Lets the general device Agent resume every non-user-blocking failure."""

    def __init__(
        self,
        tools: MobileTools,
        device: str,
        agent: GeneralDeviceAgent | None = None,
    ) -> None:
        self.tools = tools
        self.device = device
        self.agent = agent or GeneralDeviceAgent(tools, device, BackendMobileAgentBrain())

    @staticmethod
    def may_attempt(detail: str) -> bool:
        return "用户已停止" not in detail and not BlockerPolicy.may_pause(detail)

    def execute(
        self,
        event: QqReplyEvent,
        *,
        operation: str,
        failure: str,
        command: QqDeviceCommand | None,
    ) -> tuple[bool, str]:
        is_chat = operation == "chat_reply"
        if is_chat:
            goal = (
                f"恢复 QQ 私聊回复任务。原发送者是精确联系人「{event.sender}」，"
                f"待发文本是「{event.response}」。当前故障：{failure}。"
                "先观察当前状态；若该文本已作为我方新消息出现，只验证完成，"
                "不得重发。否则自主返回、重开 QQ、搜索并进入该精确私聊，"
                "重新发现输入框和发送入口，发送一次并回读验证。"
                "禁止群聊，禁止其他联系人。"
            )
            family = "qq_private_reply_recovery"
        else:
            instruction = event.instruction or (command.query if command else "")
            kind = command.kind if command else "general_device"
            goal = (
                f"从当前安全状态继续 QQ 私聊设备任务。指令：「{instruction}」。"
                f"原发送者是精确联系人「{event.sender}」，当前故障：{failure}。"
                "像人一样观察、尝试替代入口、重开应用、切换工具并回读验证；"
                "不得因按钮改名、位置变化、无 UI 树、应用闪退或浏览器变化而停止。"
                f"任务结果和摘要只能回传给「{event.sender}」，禁止群聊和其他联系人。"
            )
            family = f"qq_device_{kind}_recovery"
        result = self.agent.run(goal, task_family=family)
        if result.status is AgentStatus.COMPLETED:
            if is_chat and not self._chat_result_visible(event):
                return False, "自主恢复声称完成，但未从精确私聊回读到回复"
            return True, f"自主 Agent 已恢复并验证：{result.detail}"
        return False, f"自主 Agent {result.status.value}：{result.detail}"

    def _chat_result_visible(self, event: QqReplyEvent) -> bool:
        try:
            elements = self.tools.list_elements(self.device)
        except Exception:
            return False
        has_sender = any(event.sender in item.strings for item in elements)
        has_private_status = any(
            any(value.strip().startswith("在线") for value in item.strings)
            for item in elements
        )
        has_response = any(event.response in item.strings for item in elements)
        return has_sender and has_private_status and has_response


class ReplyJournal:
    def __init__(self, path: Path | None = None) -> None:
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PonyChat" / "Companion"
        self.path = path or root / "qq_reply_events.json"
        self._handled = self._load()

    def contains(self, event_id: str) -> bool:
        return event_id in self._handled

    def record(self, event_id: str) -> None:
        self._handled.add(event_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(self._handled)[-500:], ensure_ascii=False), encoding="utf-8")

    def _load(self) -> set[str]:
        try:
            return set(json.loads(self.path.read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return set()


class QqReplyDaemon:
    TRUSTED_EVENT_SOURCES = frozenset({
        "qq_foreground_message_row",
        "qq_private_notification",
    })
    LOGCAT_POLL_SECONDS = 1.0

    def __init__(
        self,
        tools: MobileTools,
        device: str,
        *,
        journal: ReplyJournal | None = None,
        monitor_physical_touches: bool = True,
        recovery: AutonomousTaskRecovery | None = None,
        audit: PrivacyAuditLog | None = None,
    ) -> None:
        self.device = device
        self.adb = shutil.which("adb") or "adb"
        self.leased_tools = ControllerLeasedMobileTools(
            tools,
            device,
            self.adb,
            monitor_physical_touches=monitor_physical_touches,
        )
        self.executor = QqReplyExecutor(
            self.leased_tools,
            device,
            repair_agent=QqUiRepairAgent(AdaptiveSelectorMemory()),
        )
        self.command_executor = QqDeviceCommandExecutor(self.leased_tools, device)
        self.recovery = recovery or AutonomousTaskRecovery(self.leased_tools, device)
        self.journal = journal or ReplyJournal()
        self.audit = audit or PrivacyAuditLog()
        self._seen_event_ids: set[str] = set()

    def run(self, stream: TextIO | None = None) -> None:
        if stream is not None:
            self._consume(stream)
            return
        while True:
            self._poll_logcat_once()
            time.sleep(self.LOGCAT_POLL_SECONDS)

    def _poll_logcat_once(self) -> bool:
        command = [
            self.adb, "-s", self.device, "logcat", "-d", "-v", "raw", "-s",
            "CompanionReplyReady:I", "*:S",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            self.audit.record(
                "qq_logcat_poll_failed",
                error_type=type(error).__name__,
            )
            return False
        if completed.returncode != 0:
            self.audit.record(
                "qq_logcat_poll_failed",
                returncode=completed.returncode,
            )
            return False
        self._consume(io.StringIO(completed.stdout))
        return True

    def _consume(self, stream: TextIO) -> None:
        for line in stream:
            try:
                event = QqReplyEvent.from_log_line(line)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if event.event_id in self._seen_event_ids:
                continue
            self._seen_event_ids.add(event.event_id)
            if self.journal.contains(event.event_id):
                operation = "device_command" if parse_qq_device_command(event.instruction) else "chat_reply"
                self.audit.record(
                    "qq_event_deduplicated",
                    event_id=event.event_id,
                    sender_ref=stable_private_reference(event.sender),
                    operation=operation,
                )
                self._ack(event, True, "事件已处理，未重复执行", operation)
                continue
            if event.source not in self.TRUSTED_EVENT_SOURCES:
                detail = "拒绝未标记可信消息来源的旧事件，未输入或发送"
                self.journal.record(event.event_id)
                self.audit.record(
                    "qq_event_rejected",
                    event_id=event.event_id,
                    sender_ref=stable_private_reference(event.sender),
                    reason="untrusted_event_source",
                )
                print(
                    json.dumps({
                        "event_id": event.event_id,
                        "sender_ref": stable_private_reference(event.sender),
                        "operation": "chat_reply",
                        "success": False,
                        "detail": detail,
                    }, ensure_ascii=False),
                    flush=True,
                )
                self._ack(event, False, detail, "chat_reply")
                continue
            # Claim before any device mutation. If the host crashes midway, replaying a
            # buffered log line must never duplicate a partially completed send.
            self.journal.record(event.event_id)
            command = parse_qq_device_command(event.instruction)
            with self.leased_tools.for_event(event):
                try:
                    if command is None:
                        success, detail = self.executor.execute(event)
                        operation = "chat_reply"
                    else:
                        success, detail = self.command_executor.execute(event, command)
                        operation = "device_command"
                    if not success and self.recovery.may_attempt(detail):
                        success, detail = self.recovery.execute(
                            event,
                            operation=operation,
                            failure=detail,
                            command=command,
                        )
                    self.leased_tools.await_user_control()
                except UserStoppedError as error:
                    success, detail = False, str(error)
            safe_detail = redact_private_context(detail, event.sender)
            self.audit.record(
                "qq_event_completed" if success else "qq_event_failed",
                event_id=event.event_id,
                sender_ref=stable_private_reference(event.sender),
                operation=operation,
                detail=safe_detail,
            )
            print(
                json.dumps({
                    "event_id": event.event_id,
                    "sender_ref": stable_private_reference(event.sender),
                    "operation": operation,
                    "success": success,
                    "detail": safe_detail,
                }, ensure_ascii=False),
                flush=True,
            )
            self._ack(event, success, detail, operation)

    def _ack(self, event: QqReplyEvent, success: bool, detail: str, operation: str) -> None:
        subprocess.run(
            [
                self.adb, "-s", self.device, "shell", "am", "broadcast",
                "-n", "top.ponychat.companion/.reply.QqReplyResultReceiver",
                "-a", "top.ponychat.companion.action.QQ_REPLY_RESULT",
                "--es", "event_id", event.event_id,
                "--es", "ack_token", event.ack_token,
                "--es", "status", "completed" if success else "failed",
                "--es", "detail", detail,
                "--es", "operation", operation,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
