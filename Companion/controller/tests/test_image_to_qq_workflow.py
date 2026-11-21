import tempfile
import unittest
from pathlib import Path

from companion_controller.image_share_task import (
    BrowserImageToQqTask,
    parse_browser_image_to_qq_task,
)
from companion_controller.image_to_qq_workflow import (
    BrowserImageToQqWorkflow,
    ImageShareStatus,
)
from companion_controller.contact_memory import ContactAliasMemory
from companion_controller.mobile_tools import ScreenElement
from companion_controller.procedure_memory import ProcedureMemory


def element(text="", kind="android.view.View", x=10, y=10, width=100, height=40):
    return ScreenElement(type=kind, text=text, x=x, y=y, width=width, height=height)


class FakeTools:
    def __init__(self, screens):
        self.screens = list(screens)
        self.index = 0
        self.calls = []

    def list_apps(self, device):
        return "QQ (com.tencent.mobileqq)\nChrome (com.android.chrome)"

    def list_elements(self, device):
        screen = self.screens[min(self.index, len(self.screens) - 1)]
        self.index += 1
        return screen

    def press_button(self, device, button):
        self.calls.append(("button", button))

    def open_url(self, device, url):
        self.calls.append(("open_url", url))

    def long_press(self, device, x, y, duration_ms=700):
        self.calls.append(("long_press", x, y, duration_ms))

    def click(self, device, x, y):
        self.calls.append(("click", x, y))

    def clear_text(self, device):
        self.calls.append(("clear", device))

    def type_text(self, device, text, submit=False):
        self.calls.append(("type", text, submit))

    def save_screenshot(self, device, path):
        self.calls.append(("screenshot", path))


class BrowserImageToQqWorkflowTest(unittest.TestCase):
    def test_search_only_reuses_browser_detection_and_leaves_results_visible(self):
        result_item = element("小马宝莉 紫悦 - Wiki", "android.widget.Button", 10, 600, 500, 700)
        with tempfile.TemporaryDirectory() as directory:
            tools = FakeTools([[result_item, element("Customize and control Google Chrome")]])
            result = BrowserImageToQqWorkflow(
                tools,
                "emulator-5554",
                memory=ProcedureMemory(Path(directory) / "memory.json"),
                settle_seconds=0,
            ).search_images("小马宝莉 紫悦")

        self.assertEqual(ImageShareStatus.COMPLETED, result.status)
        self.assertIn("图片搜索结果", result.detail)
        self.assertTrue(any(call[0] == "open_url" for call in tools.calls))
        self.assertFalse(any(call[0] == "long_press" for call in tools.calls))

    def test_parses_requested_case(self):
        self.assertEqual(
            BrowserImageToQqTask("小马宝莉的小马紫悦", "谢永鹏"),
            parse_browser_image_to_qq_task(
                "Companion在浏览器里面搜索小马宝莉的小马“紫悦”的图片，并发给QQ的谢永鹏"
            ),
        )

    def test_full_semantic_share_and_memory(self):
        result_item = element("小马宝莉 紫悦 - Wiki", "android.widget.Button", 10, 600, 500, 700)
        contact_text = element("谢永鹏@JasonXie", "android.widget.TextView", 180, 1000, 350, 70)
        contact_row = element("谢永鹏@JasonXie", "android.widget.RelativeLayout", 0, 970, 1080, 150)
        screens = [
            [result_item, element("Customize and control Google Chrome")],
            [element("Share image", "android.widget.TextView")],
            [element("QQ", "android.widget.TextView", 200, 2000, 200, 100)],
            [contact_text, contact_row, element("搜索", "android.widget.EditText")],
            [
                element("谢永鹏@JasonXie"),
                element("图片预览", "android.widget.ImageView"),
                element("发送", "android.widget.Button"),
            ],
            [element("Share completed")],
        ]
        with tempfile.TemporaryDirectory() as directory:
            memory = ProcedureMemory(Path(directory) / "memory.json")
            tools = FakeTools(screens)
            result = BrowserImageToQqWorkflow(
                tools,
                "emulator-5554",
                memory=memory,
                settle_seconds=0,
            ).run(BrowserImageToQqTask("小马宝莉 紫悦", "谢永鹏@JasonXie"))

            self.assertEqual(ImageShareStatus.COMPLETED, result.status)
            self.assertTrue(any(call[0] == "long_press" for call in tools.calls))
            self.assertTrue((Path(directory) / "memory.json").is_file())
            learned = memory.preferred_strategy(
                BrowserImageToQqWorkflow.SKILL,
                "android:chrome",
                BrowserImageToQqWorkflow.DEFAULT_STRATEGY,
            )
            self.assertEqual("Share image", learned["share_action"])

    def test_ambiguous_contact_stops_before_send(self):
        screens = [
            [element("紫悦", "android.widget.Button", 10, 600, 500, 700)],
            [element("分享图片")],
            [element("QQ")],
            [
                element("谢永鹏@JasonXie", y=700),
                element("谢永鹏@Work", y=1100),
                element("搜索", "android.widget.EditText"),
            ],
            [element("谢永鹏@JasonXie", y=700), element("谢永鹏@Work", y=1100)],
        ]
        with tempfile.TemporaryDirectory() as directory:
            tools = FakeTools(screens)
            result = BrowserImageToQqWorkflow(
                tools,
                "emulator-5554",
                memory=ProcedureMemory(Path(directory) / "memory.json"),
                settle_seconds=0,
            ).run(BrowserImageToQqTask("紫悦", "谢永鹏"))

        self.assertEqual(ImageShareStatus.NEEDS_CONTACT_SELECTION, result.status)
        self.assertEqual(("谢永鹏@JasonXie", "谢永鹏@Work"), result.contact_candidates)
        self.assertFalse(any("发送" in str(call) for call in tools.calls))

    def test_unique_name_at_alias_is_safe_match(self):
        contact = element("谢永鹏@JasonXie", "android.widget.RelativeLayout", 0, 900, 1080, 150)

        self.assertIs(contact, BrowserImageToQqWorkflow._find_contact_row([contact], "谢永鹏"))

    def test_multiple_name_at_alias_rows_are_ambiguous(self):
        contacts = [
            element("谢永鹏@JasonXie", y=700),
            element("谢永鹏@Work", y=1100),
        ]

        self.assertIsNone(BrowserImageToQqWorkflow._find_contact_row(contacts, "谢永鹏"))

    def test_same_exact_contact_in_recommendations_and_recent_is_not_ambiguous(self):
        recommendation = element("谢永鹏@JasonXie", y=500, width=160, height=290)
        recent_row = element("谢永鹏@JasonXie", y=1100, width=1080, height=150)

        self.assertIs(
            recent_row,
            BrowserImageToQqWorkflow._find_contact_row([recommendation, recent_row], "谢永鹏"),
        )

    def test_resume_selection_sends_and_remembers_nickname(self):
        contact = element("王晓明@销售部", "android.widget.RelativeLayout", 0, 900, 1080, 150)
        screens = [
            [contact],
            [element("王晓明@销售部"), element("图片预览"), element("发送", "android.widget.Button")],
            [element("已发送")],
        ]
        with tempfile.TemporaryDirectory() as directory:
            aliases = ContactAliasMemory(Path(directory) / "contacts.json")
            result = BrowserImageToQqWorkflow(
                FakeTools(screens),
                "emulator-5554",
                contact_memory=aliases,
                settle_seconds=0,
            ).resume_contact_selection("王晓明@销售部", remember_as="王总")

            self.assertEqual(ImageShareStatus.COMPLETED, result.status)
            self.assertEqual("王晓明@销售部", aliases.resolve("qq", "王总"))


if __name__ == "__main__":
    unittest.main()
