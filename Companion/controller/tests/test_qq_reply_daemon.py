import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from companion_controller.image_to_qq_workflow import ImageShareStatus
from companion_controller.mobile_tools import ScreenElement
from companion_controller.qq_workflow import WorkflowStatus
from companion_controller.qq_reply_daemon import (
    ControllerLeasedMobileTools,
    PhysicalTouchMonitor,
    QqReplyDaemon,
    QqReplyEvent,
    QqReplyExecutor,
    ReplyJournal,
    UserStoppedError,
)


def element(text="", kind="TextView", x=10, y=10):
    return ScreenElement(type=kind, text=text, x=x, y=y, width=100, height=40)


class FakeTools:
    def __init__(self, screens):
        self.screens = list(screens)
        self.index = 0
        self.calls = []

    def list_elements(self, device):
        screen = self.screens[min(self.index, len(self.screens) - 1)]
        self.index += 1
        return screen

    def click(self, device, x, y):
        self.calls.append(("click", x, y))

    def clear_text(self, device):
        self.calls.append(("clear", device))

    def type_text(self, device, text, submit=False):
        self.calls.append(("type", text, submit))


class FakeRecovery:
    def __init__(self, result=(True, "自主恢复完成")):
        self.result = result
        self.calls = []

    @staticmethod
    def may_attempt(detail):
        return "需要登录" not in detail and "用户已停止" not in detail

    def execute(self, event, **kwargs):
        self.calls.append((event, kwargs))
        return self.result


class QqReplyExecutorTest(unittest.TestCase):
    def test_physical_touch_monitor_only_matches_touch_down(self):
        self.assertIsNotNone(PhysicalTouchMonitor.TOUCH_DOWN.search(
            "[ 123.000] /dev/input/event4: EV_ABS ABS_MT_TRACKING_ID 0000002a",
        ))
        self.assertIsNotNone(PhysicalTouchMonitor.TOUCH_DOWN.search(
            "[ 123.000] /dev/input/event4: EV_KEY BTN_TOUCH DOWN",
        ))
        self.assertIsNone(PhysicalTouchMonitor.TOUCH_DOWN.search(
            "[ 123.100] /dev/input/event4: EV_ABS ABS_MT_TRACKING_ID ffffffff",
        ))
        self.assertIsNone(PhysicalTouchMonitor.TOUCH_DOWN.search(
            "[ 123.100] /dev/input/event4: EV_KEY BTN_TOUCH UP",
        ))

    @patch("companion_controller.qq_reply_daemon.time.sleep")
    def test_controller_waits_until_user_continues_after_physical_touch(self, _sleep):
        leased = ControllerLeasedMobileTools(
            FakeTools([]),
            "emulator",
            "adb",
            monitor_physical_touches=False,
        )
        leased._event = QqReplyEvent("event", "token", "Jason", "reply")
        leased._touch_detected.set()
        states = iter((2, 2, 1))
        leased._query_control = lambda _event: next(states)

        leased.await_user_control()

        self.assertFalse(leased._touch_detected.is_set())
        self.assertEqual(2, _sleep.call_count)

    def test_controller_aborts_when_user_stops_after_physical_touch(self):
        leased = ControllerLeasedMobileTools(
            FakeTools([]),
            "emulator",
            "adb",
            monitor_physical_touches=False,
        )
        leased._event = QqReplyEvent("event", "token", "Jason", "reply")
        leased._touch_detected.set()
        leased._query_control = lambda _event: 3

        with self.assertRaisesRegex(UserStoppedError, "用户已停止"):
            leased.await_user_control()

    @patch("companion_controller.qq_reply_daemon.subprocess.run")
    def test_mobile_input_is_bracketed_by_controller_lease(self, run):
        run.return_value = SimpleNamespace(returncode=0, stderr="")
        tools = FakeTools([])
        leased = ControllerLeasedMobileTools(
            tools,
            "emulator",
            "adb",
            monitor_physical_touches=False,
        )
        event = QqReplyEvent("event", "token", "Jason", "回复")

        with leased.for_event(event):
            leased.click("emulator", 10, 20)

        actions = [call.args[0][9] for call in run.call_args_list]
        self.assertEqual([
            "top.ponychat.companion.action.AGENT_INPUT_BEGIN",
            "top.ponychat.companion.action.AGENT_INPUT_END",
        ], actions)
        self.assertIn(("click", 10, 20), tools.calls)

    def test_mobile_mcp_sends_once_and_verifies_new_message(self):
        chat = [element("Jason"), element("在线 - WiFi"), element(kind="android.widget.EditText"), element("发送")]
        tools = FakeTools([chat, chat, chat + [element("角色回复")]])
        success, _ = QqReplyExecutor(tools, "emulator", settle_seconds=0).execute(
            QqReplyEvent("event-1", "token", "Jason", "角色回复"),
        )
        self.assertTrue(success)
        self.assertEqual(1, sum(call[0] == "type" for call in tools.calls))

    def test_wrong_chat_never_types(self):
        tools = FakeTools([[element("别人"), element("在线"), element(kind="android.widget.EditText")]])
        success, _ = QqReplyExecutor(tools, "emulator", settle_seconds=0).execute(
            QqReplyEvent("event-1", "token", "Jason", "秘密"),
        )
        self.assertFalse(success)
        self.assertFalse(any(call[0] == "type" for call in tools.calls))

    @patch("companion_controller.qq_reply_daemon.subprocess.run")
    def test_journal_prevents_duplicate_event_execution(self, _run):
        with tempfile.TemporaryDirectory() as directory:
            journal = ReplyJournal(Path(directory) / "events.json")
            tools = FakeTools([])
            daemon = QqReplyDaemon(
                tools,
                "emulator",
                journal=journal,
                monitor_physical_touches=False,
            )
            daemon.executor.execute = lambda event: (True, "ok")
            payload = json.dumps({
                "event_id": "same-event", "ack_token": "token",
                "sender": "Jason", "response": "回复",
                "source": "qq_foreground_message_row",
            })
            daemon._consume(io.StringIO(payload + "\n" + payload + "\n"))
            self.assertTrue(journal.contains("same-event"))

    @patch("companion_controller.qq_reply_daemon.subprocess.run")
    def test_device_command_routes_to_workflow_instead_of_typing_reply(self, _run):
        with tempfile.TemporaryDirectory() as directory:
            daemon = QqReplyDaemon(
                FakeTools([]),
                "emulator",
                journal=ReplyJournal(Path(directory) / "events.json"),
                monitor_physical_touches=False,
            )
            calls = []
            daemon.executor.execute = lambda event: self.fail("command must not become a chat reply")
            daemon.command_executor.execute = lambda event, command: calls.append((event, command)) or (True, "已发送图片")
            payload = json.dumps({
                "event_id": "command-event",
                "ack_token": "token",
                "sender": "Jason",
                "response": "我来找找",
                "instruction": "帮我从网上找一下小马宝莉紫悦的图片",
                "source": "qq_foreground_message_row",
            })

            daemon._consume(io.StringIO(payload + "\n"))

            self.assertEqual(1, len(calls))
            self.assertEqual("Jason", calls[0][0].sender)
            self.assertEqual("image_search", calls[0][1].kind)

    def test_command_result_recipient_is_forced_to_origin_sender(self):
        daemon = QqReplyDaemon(FakeTools([]), "emulator", monitor_physical_touches=False)
        captured = []
        daemon.command_executor.workflow.run = lambda task, **_: captured.append(task) or SimpleNamespace(
            status=ImageShareStatus.COMPLETED,
            detail="ok",
        )
        event = QqReplyEvent(
            "event", "token", "原发送者@QQ", "",
            "Companion在浏览器里面搜索紫悦的图片，并发给QQ的另一个人",
        )
        from companion_controller.qq_command import parse_qq_device_command
        command = parse_qq_device_command(event.instruction)

        success, _ = daemon.command_executor.execute(event, command)

        self.assertTrue(success)
        self.assertEqual("原发送者@QQ", captured[0].recipient)

    def test_web_query_summary_is_returned_only_to_origin_sender(self):
        daemon = QqReplyDaemon(FakeTools([]), "emulator", monitor_physical_touches=False)
        daemon.command_executor.web_workflow.run = lambda command: SimpleNamespace(
            success=True,
            message="天气查询：深圳\n• 31°C\n完整结果：https://example.test",
            detail="已查询",
            url="https://example.test",
        )
        sent = []
        daemon.command_executor.qq_workflow.run = lambda task: (
            sent.append(task) or SimpleNamespace(status=WorkflowStatus.COMPLETED, detail="ok")
        )
        event = QqReplyEvent(
            "event", "token", "原发送者@QQ", "", "帮我从网上看看深圳今天的天气",
        )
        from companion_controller.qq_command import parse_qq_device_command

        success, _ = daemon.command_executor.execute(
            event,
            parse_qq_device_command(event.instruction),
        )

        self.assertTrue(success)
        self.assertEqual("原发送者@QQ", sent[0].recipient)
        self.assertIn("31°C", sent[0].message)

    @patch("companion_controller.qq_reply_daemon.time.sleep")
    def test_transient_browser_failure_retries_with_another_provider(self, _sleep):
        daemon = QqReplyDaemon(FakeTools([]), "emulator", monitor_physical_touches=False)
        providers = []
        results = iter((
            SimpleNamespace(status=ImageShareStatus.FAILED, detail="浏览器闪退"),
            SimpleNamespace(status=ImageShareStatus.COMPLETED, detail="已发送图片"),
        ))
        daemon.command_executor.workflow.run = lambda task, **kwargs: (
            providers.append(kwargs["preferred_provider"]) or next(results)
        )
        daemon.command_executor.workflow.tools.press_button = lambda *args: None
        event = QqReplyEvent("event", "token", "Jason", "", "帮我网上找紫悦图片")
        from companion_controller.qq_command import parse_qq_device_command

        success, detail = daemon.command_executor.execute(
            event,
            parse_qq_device_command(event.instruction),
        )

        self.assertTrue(success)
        self.assertEqual(["google_images", "bing_images"], providers)
        self.assertIn("2 轮", detail)

    def test_login_problem_stops_without_retry(self):
        daemon = QqReplyDaemon(FakeTools([]), "emulator", monitor_physical_touches=False)
        attempts = []
        daemon.command_executor.workflow.run = lambda task, **kwargs: (
            attempts.append(kwargs) or SimpleNamespace(
                status=ImageShareStatus.NEEDS_LOGIN,
                detail="QQ 需要登录",
            )
        )
        event = QqReplyEvent("event", "token", "Jason", "", "帮我网上找紫悦图片")
        from companion_controller.qq_command import parse_qq_device_command

        success, detail = daemon.command_executor.execute(
            event,
            parse_qq_device_command(event.instruction),
        )

        self.assertFalse(success)
        self.assertEqual(1, len(attempts))
        self.assertEqual("QQ 需要登录", detail)

    def test_unverified_send_is_inspected_by_autonomous_recovery_without_blind_retry(self):
        recovery = FakeRecovery()
        daemon = QqReplyDaemon(
            FakeTools([]),
            "emulator",
            monitor_physical_touches=False,
            recovery=recovery,
        )
        attempts = []
        daemon.command_executor.workflow.run = lambda task, **kwargs: (
            attempts.append(kwargs) or SimpleNamespace(
                status=ImageShareStatus.SEND_UNVERIFIED,
                detail="已点击发送但结果无法验证",
            )
        )
        event = QqReplyEvent("event", "token", "Jason", "", "帮我网上找紫悦图片")
        from companion_controller.qq_command import parse_qq_device_command

        success, detail = daemon.command_executor.execute(
            event,
            parse_qq_device_command(event.instruction),
        )

        self.assertFalse(success)
        self.assertEqual(1, len(attempts))
        self.assertIn("无法验证", detail)

        recovered, _ = daemon.recovery.execute(
            event,
            operation="device_command",
            failure=detail,
            command=parse_qq_device_command(event.instruction),
        )
        self.assertTrue(recovered)
        self.assertEqual(1, len(recovery.calls))

    @patch("companion_controller.qq_reply_daemon.subprocess.run")
    def test_daemon_hands_technical_chat_failure_to_general_agent(self, _run):
        with tempfile.TemporaryDirectory() as directory:
            recovery = FakeRecovery()
            daemon = QqReplyDaemon(
                FakeTools([]),
                "emulator",
                journal=ReplyJournal(Path(directory) / "events.json"),
                monitor_physical_touches=False,
                recovery=recovery,
            )
            daemon.executor.execute = lambda _event: (False, "QQ 组件名变了")
            payload = json.dumps({
                "event_id": "repair-event",
                "ack_token": "token",
                "sender": "Jason",
                "response": "回复",
                "instruction": "你好",
                "source": "qq_foreground_message_row",
            })

            daemon._consume(io.StringIO(payload + "\n"))

            self.assertEqual(1, len(recovery.calls))
            self.assertTrue(daemon.journal.contains("repair-event"))

    @patch("companion_controller.qq_reply_daemon.subprocess.run")
    def test_legacy_event_without_verified_source_is_rejected_without_input(self, run):
        run.return_value = SimpleNamespace(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as directory:
            daemon = QqReplyDaemon(
                FakeTools([]),
                "emulator",
                journal=ReplyJournal(Path(directory) / "events.json"),
                monitor_physical_touches=False,
            )
            daemon.executor.execute = lambda _event: self.fail("untrusted event must not execute")
            payload = json.dumps({
                "event_id": "legacy-wrong-event",
                "ack_token": "token",
                "sender": "Jason",
                "response": "错误回复",
                "instruction": "发送",
            })

            daemon._consume(io.StringIO(payload + "\n"))

            self.assertTrue(daemon.journal.contains("legacy-wrong-event"))
            self.assertIn("failed", str(run.call_args_list[-1]))

    @patch("companion_controller.qq_reply_daemon.subprocess.run")
    def test_logcat_poll_can_recover_after_failed_snapshot(self, run):
        run.side_effect = (
            SimpleNamespace(returncode=1, stdout="", stderr="offline"),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        daemon = QqReplyDaemon(FakeTools([]), "emulator", monitor_physical_touches=False)

        self.assertFalse(daemon._poll_logcat_once())
        self.assertTrue(daemon._poll_logcat_once())


if __name__ == "__main__":
    unittest.main()
