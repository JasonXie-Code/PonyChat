import json
from pathlib import Path
import tempfile
import unittest

from companion_controller.audit_log import (
    PrivacyAuditLog,
    redact_private_context,
    redact_sensitive,
)
from companion_controller.general_agent import (
    AgentDecision,
    AgentStatus,
    GeneralDeviceAgent,
    SkillProgramMemory,
)
from companion_controller.mobile_tools import ScreenElement
from companion_controller.safety_policy import DeviceActionSafetyPolicy


def element(text, identifier, kind="android.widget.Button"):
    return ScreenElement(
        type=kind,
        text=text,
        identifier=identifier,
        x=10,
        y=20,
        width=100,
        height=40,
    )


class FakeTools:
    def __init__(self, screens):
        self.screens = list(screens)
        self.index = 0
        self.calls = []

    def list_apps(self, _device):
        return ""

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


class AcceptanceSafetyTest(unittest.TestCase):
    def test_final_payment_action_pauses_without_clicking(self):
        screens = [[element("确认支付", "shop:id/pay")]]
        tools = FakeTools(screens)
        brain = SequenceBrain([
            AgentDecision("click", "支付", {"identifier": "shop:id/pay"}),
        ])
        with tempfile.TemporaryDirectory() as directory:
            agent = GeneralDeviceAgent(
                tools,
                "device",
                brain,
                memory=SkillProgramMemory(Path(directory) / "programs.json"),
                audit=PrivacyAuditLog(Path(directory) / "audit.jsonl"),
                settle_seconds=0,
            )
            result = agent.run("购买商品")

        self.assertEqual(AgentStatus.USER_ACTION_REQUIRED, result.status)
        self.assertIn("确认", result.detail)
        self.assertEqual([], tools.calls)

    def test_sensitive_field_requires_user_takeover(self):
        policy = DeviceActionSafetyPolicy()
        fields = [element("短信验证码", "login:id/code", "android.widget.EditText")]

        assessment = policy.assess(
            "type_text",
            {"identifier": "login:id/code"},
            fields,
        )

        self.assertTrue(assessment.requires_confirmation)

    def test_unverified_finish_is_rejected_until_visible_evidence_exists(self):
        tools = FakeTools([
            [element("处理中", "app:id/loading")],
            [element("保存成功", "app:id/success")],
        ])
        brain = SequenceBrain([
            AgentDecision("finish", "完成", verification="保存成功"),
            AgentDecision("finish", "完成", verification="保存成功"),
        ])
        with tempfile.TemporaryDirectory() as directory:
            result = GeneralDeviceAgent(
                tools,
                "device",
                brain,
                memory=SkillProgramMemory(Path(directory) / "programs.json"),
                audit=PrivacyAuditLog(Path(directory) / "audit.jsonl"),
                settle_seconds=0,
            ).run("保存文件")

        self.assertEqual(AgentStatus.COMPLETED, result.status)
        self.assertEqual("保存成功", result.detail)

    def test_audit_log_redacts_credentials_and_known_contact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            log = PrivacyAuditLog(path)
            detail = redact_private_context(
                "已返回给原发送者 Jason；token=secret-token；验证码为 123456",
                "Jason",
            )
            log.record("qq_event_completed", detail=detail, password="plain-password")
            payload = json.loads(path.read_text(encoding="utf-8"))

        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("Jason", serialized)
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("123456", serialized)
        self.assertNotIn("plain-password", serialized)
        self.assertEqual("[已隐藏]", payload["password"])

    def test_redaction_handles_bearer_tokens(self):
        self.assertNotIn(
            "abc.def-123",
            redact_sensitive("Authorization: Bearer abc.def-123"),
        )


if __name__ == "__main__":
    unittest.main()
