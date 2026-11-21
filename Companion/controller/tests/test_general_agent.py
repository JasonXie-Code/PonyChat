from pathlib import Path
import tempfile
import unittest

from companion_controller.general_agent import (
    AgentDecision,
    AgentStatus,
    GeneralDeviceAgent,
    SkillProgramMemory,
)
from companion_controller.mobile_tools import ScreenElement


class FakeTools:
    def __init__(self, screens):
        self.screens = list(screens)
        self.index = 0
        self.calls = []

    def list_elements(self, _device):
        screen = self.screens[min(self.index, len(self.screens) - 1)]
        self.index += 1
        return screen

    def click(self, _device, x, y):
        self.calls.append(("click", x, y))
        return "clicked"

    def save_screenshot(self, _device, _path):
        raise RuntimeError("not needed")


class SequenceBrain:
    def __init__(self, decisions):
        self.decisions = iter(decisions)

    def decide(self, **_kwargs):
        return next(self.decisions)


def button(text, identifier, x=20):
    return ScreenElement(text=text, identifier=identifier, x=x, y=20, width=80, height=40)


class GeneralDeviceAgentTest(unittest.TestCase):
    def test_explores_changed_component_then_records_successful_program(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = SkillProgramMemory(Path(directory) / "programs.json")
            tools = FakeTools([
                [button("继续", "app:id/new_continue")],
                [button("完成", "app:id/done")],
            ])
            brain = SequenceBrain([
                AgentDecision(
                    "click",
                    "发现改名后的继续按钮",
                    {"text": "继续", "identifier": "app:id/new_continue"},
                ),
                AgentDecision("finish", "任务完成", verification="屏幕出现完成"),
            ])
            result = GeneralDeviceAgent(
                tools, "device", brain, memory=memory, settle_seconds=0,
            ).run("完成测试流程")

            self.assertEqual(AgentStatus.COMPLETED, result.status)
            self.assertEqual([("click", 60, 40)], tools.calls)
            self.assertTrue(memory.path.is_file())
            self.assertIn("app:id/new_continue", memory.path.read_text(encoding="utf-8"))

    def test_technical_block_is_rejected_and_agent_keeps_solving(self):
        tools = FakeTools([
            [button("重试", "app:id/retry")],
            [button("重试", "app:id/retry")],
            [button("恢复完成", "app:id/recovered")],
        ])
        brain = SequenceBrain([
            AgentDecision("blocked", "按钮位置变了"),
            AgentDecision("click", "探索当前重试入口", {"text": "重试"}),
            AgentDecision("finish", "已恢复", verification="恢复完成"),
        ])
        with tempfile.TemporaryDirectory() as directory:
            result = GeneralDeviceAgent(
                tools,
                "device",
                brain,
                memory=SkillProgramMemory(Path(directory) / "programs.json"),
                settle_seconds=0,
            ).run("恢复任务")

        self.assertEqual(AgentStatus.COMPLETED, result.status)
        self.assertEqual(1, len(tools.calls))

    def test_permission_block_is_allowed_to_pause(self):
        tools = FakeTools([[]])
        brain = SequenceBrain([AgentDecision("blocked", "需要用户授予相机权限")])
        with tempfile.TemporaryDirectory() as directory:
            result = GeneralDeviceAgent(
                tools,
                "device",
                brain,
                memory=SkillProgramMemory(Path(directory) / "programs.json"),
                settle_seconds=0,
            ).run("拍照")

        self.assertEqual(AgentStatus.USER_ACTION_REQUIRED, result.status)


if __name__ == "__main__":
    unittest.main()
