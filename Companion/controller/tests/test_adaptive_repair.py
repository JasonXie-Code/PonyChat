from pathlib import Path
import tempfile
import unittest

from companion_controller.adaptive_repair import AdaptiveSelectorMemory, QqUiRepairAgent
from companion_controller.mobile_tools import ScreenElement


def element(text="", kind="TextView", identifier=""):
    return ScreenElement(type=kind, text=text, identifier=identifier, width=100, height=40)


class QqUiRepairAgentTest(unittest.TestCase):
    def test_discovers_current_qq_controls_without_fixed_coordinates(self):
        agent = QqUiRepairAgent()
        controls = agent.inspect([
            element("谢永鹏@JasonXie", identifier="com.tencent.mobileqq:id/1yo"),
            element("在线 - WiFi", identifier="com.tencent.mobileqq:id/j64"),
            element(kind="android.widget.EditText", identifier="com.tencent.mobileqq:id/input"),
            element("发送", identifier="com.tencent.mobileqq:id/send_btn"),
        ], "谢永鹏@JasonXie")

        self.assertIsNotNone(controls)
        self.assertEqual("com.tencent.mobileqq:id/input", controls.editor.identifier)

    def test_group_screen_is_never_treated_as_private(self):
        agent = QqUiRepairAgent()
        controls = agent.inspect([
            element("PonyChat交流群"),
            element("在线"),
            element(kind="android.widget.EditText"),
            element("发送"),
        ], "PonyChat交流群")

        self.assertIsNone(controls)

    def test_validated_selector_rule_is_persisted_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = AdaptiveSelectorMemory(Path(directory) / "selectors.json")
            agent = QqUiRepairAgent(memory)
            elements = [
                element("Jason", identifier="qq:id/title-new"),
                element("在线·手机在线", identifier="qq:id/status-new"),
                element(kind="android.widget.EditText", identifier="qq:id/editor-new"),
                element("发送", identifier="qq:id/send-new"),
            ]
            controls = agent.inspect(elements, "Jason")
            agent.remember_success(controls)

            rule = memory.preferred(agent.SKILL, "android:qq")
            self.assertEqual("qq:id/editor-new", rule.editor_identifier)
            self.assertEqual(1, rule.success_count)


if __name__ == "__main__":
    unittest.main()
