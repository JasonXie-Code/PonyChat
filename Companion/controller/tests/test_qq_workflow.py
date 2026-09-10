import unittest

from companion_controller.mobile_tools import ScreenElement
from companion_controller.qq_task import QqMessageTask, parse_qq_message_task
from companion_controller.qq_workflow import QqMessageWorkflow, WorkflowStatus


def element(text="", kind="TextView", x=10, y=10, width=100, height=40):
    return ScreenElement(type=kind, text=text, x=x, y=y, width=width, height=height)


class FakeTools:
    def __init__(self, screens, apps="QQ (com.tencent.mobileqq)"):
        self.screens = list(screens)
        self.screen_index = 0
        self.apps = apps
        self.calls = []

    def list_apps(self, device):
        self.calls.append(("list_apps", device))
        return self.apps

    def launch_app(self, device, package_name):
        self.calls.append(("launch", package_name))
        return "ok"

    def list_elements(self, device):
        self.calls.append(("elements", device))
        screen = self.screens[min(self.screen_index, len(self.screens) - 1)]
        self.screen_index += 1
        return screen

    def click(self, device, x, y):
        self.calls.append(("click", x, y))
        return "ok"

    def type_text(self, device, text, submit=False):
        self.calls.append(("type", text, submit))
        return "ok"

    def clear_text(self, device):
        self.calls.append(("clear", device))
        return "ok"

    def press_button(self, device, button):
        self.calls.append(("button", button))
        return "ok"


class QqWorkflowTest(unittest.TestCase):
    def test_exact_contact_accepts_qq_composite_accessibility_label(self):
        element = ScreenElement(
            type="android.widget.RelativeLayout",
            label="谢永鹏@JasonXie, ,31条未读,消息预览,上午7:54",
            x=0,
            y=677,
            width=1080,
            height=194,
        )

        self.assertIs(element, QqMessageWorkflow._find_exact_unique([element], "谢永鹏@JasonXie"))

    def test_contact_section_excludes_duplicate_comprehensive_search_results(self):
        header = element("联系人", y=200)
        contact = element("谢永鹏@JasonXie", y=300)
        next_section = element("聊天记录", y=500)
        duplicate = element("谢永鹏@JasonXie", y=700)

        result = QqMessageWorkflow._find_contact_section_unique(
            [header, contact, next_section, duplicate],
            "谢永鹏@JasonXie",
        )

        self.assertIs(contact, result)

    def test_most_used_contact_wins_over_group_and_comprehensive_duplicates(self):
        most_used = element("最常使用", y=200)
        contact = element("谢永鹏@JasonXie", y=300)
        contact_type = element("联系人", y=355)
        group_header = element("群聊", y=500)
        group_contains_name = element("包含: 谢永鹏@JasonXie", y=600)
        comprehensive = element("搜索综合结果（人/群/频道等更多内容）", y=800)
        duplicate = element("谢永鹏@JasonXie", y=900)
        ai_duplicate = element("谢永鹏@JasonXie", y=1000)

        result = QqMessageWorkflow._find_contact_section_unique(
            [
                most_used,
                contact,
                contact_type,
                group_header,
                group_contains_name,
                comprehensive,
                duplicate,
                ai_duplicate,
            ],
            "谢永鹏@JasonXie",
        )

        self.assertIs(contact, result)

    def test_parses_recipient_and_message(self):
        self.assertEqual(
            QqMessageTask("张三", "你好呀"),
            parse_qq_message_task("帮我用QQ给张三发信息：你好呀"),
        )

    def test_missing_message_is_rejected(self):
        self.assertIsNone(parse_qq_message_task("帮我用QQ给张三发信息"))

    def test_stops_and_requests_login(self):
        tools = FakeTools([[element("手机号登录")]])
        result = QqMessageWorkflow(tools, "emulator-5554", settle_seconds=0).run(QqMessageTask("张三", "你好"))
        self.assertEqual(WorkflowStatus.NEEDS_LOGIN, result.status)
        self.assertFalse(any(call[0] == "type" for call in tools.calls))

    def test_exact_contact_full_send_and_verify(self):
        tools = FakeTools([
            [element("搜索")],
            [element("张三", kind="android.widget.EditText"), element("张三", x=20, y=100)],
            [element("", kind="android.widget.EditText"), element("发送")],
            [element("", kind="android.widget.EditText"), element("发送")],
            [element("你好呀")],
        ])
        result = QqMessageWorkflow(tools, "emulator-5554", settle_seconds=0).run(QqMessageTask("张三", "你好呀"))
        self.assertEqual(WorkflowStatus.COMPLETED, result.status)
        self.assertIn(("type", "张三", False), tools.calls)
        self.assertIn(("type", "你好呀", False), tools.calls)
        self.assertEqual(2, sum(call[0] == "clear" for call in tools.calls))

    def test_returns_from_existing_chat_before_searching_origin_sender(self):
        tools = FakeTools([
            [element("旧会话"), element("在线"), element("", kind="android.widget.EditText")],
            [element("搜索")],
            [element("原发送者", kind="android.widget.EditText"), element("原发送者", y=100)],
            [element("原发送者"), element("在线"), element("", kind="android.widget.EditText"), element("发送")],
            [element("", kind="android.widget.EditText"), element("发送")],
            [element("查询结果")],
        ])

        result = QqMessageWorkflow(tools, "emulator-5554", settle_seconds=0).run(
            QqMessageTask("原发送者", "查询结果"),
        )

        self.assertEqual(WorkflowStatus.COMPLETED, result.status)
        self.assertIn(("button", "BACK"), tools.calls)
        self.assertIn(("type", "查询结果", False), tools.calls)

    def test_ambiguous_contact_never_types_message(self):
        tools = FakeTools([
            [element("搜索")],
            [element("张三", x=10), element("张三", x=300)],
        ])
        result = QqMessageWorkflow(tools, "emulator-5554", settle_seconds=0).run(QqMessageTask("张三", "秘密"))
        self.assertEqual(WorkflowStatus.CONTACT_AMBIGUOUS, result.status)
        self.assertNotIn(("type", "秘密", False), tools.calls)


if __name__ == "__main__":
    unittest.main()
