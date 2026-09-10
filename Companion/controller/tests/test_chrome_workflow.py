import unittest

from companion_controller.chrome_workflow import ChromeWebsiteWorkflow, ChromeWorkflowStatus
from companion_controller.mobile_tools import ScreenElement


class FakeChromeTools:
    def __init__(self, screens):
        self.screens = iter(screens)
        self.calls = []

    def list_apps(self, device):
        return "Chrome (com.android.chrome)"

    def launch_app(self, device, package_name):
        self.calls.append(("launch", package_name))
        return "ok"

    def list_elements(self, device):
        return next(self.screens)

    def click(self, device, x, y):
        return "ok"

    def type_text(self, device, text, submit=False):
        return "ok"

    def press_button(self, device, button):
        self.calls.append(("button", button))
        return "ok"

    def open_url(self, device, url):
        self.calls.append(("url", url))
        return "ok"

    def save_screenshot(self, device, path):
        self.calls.append(("screenshot", path))
        return "ok"


class AcceptingVisionVerifier:
    def verify_website(self, screenshot_path, expected_host):
        return expected_host == "yuelimei.cn"


class FailingVisionVerifier:
    def verify_website(self, screenshot_path, expected_host):
        raise RuntimeError("ModelNotOpen")


class ChromeWorkflowTest(unittest.TestCase):
    def test_opens_website_from_home_and_verifies_host(self):
        tools = FakeChromeTools([
            [ScreenElement(text="Search or type URL")],
            [ScreenElement(text="https://yuelimei.cn")],
        ])
        result = ChromeWebsiteWorkflow(tools, "device", settle_seconds=0).run("https://yuelimei.cn")
        self.assertEqual(ChromeWorkflowStatus.COMPLETED, result.status)
        self.assertEqual(("button", "HOME"), tools.calls[0])
        self.assertIn(("launch", "com.android.chrome"), tools.calls)
        self.assertIn(("url", "https://yuelimei.cn"), tools.calls)

    def test_stops_for_chrome_first_run_terms(self):
        tools = FakeChromeTools([[ScreenElement(text="Accept & continue")]])
        result = ChromeWebsiteWorkflow(tools, "device", settle_seconds=0).run("https://yuelimei.cn")
        self.assertEqual(ChromeWorkflowStatus.NEEDS_CHROME_SETUP, result.status)
        self.assertFalse(any(call[0] == "url" for call in tools.calls))

    def test_uses_vision_when_chrome_tree_hides_address_bar(self):
        tools = FakeChromeTools([
            [ScreenElement(text="Search or type URL")],
            [ScreenElement(text="深圳悦丽美贸易有限公司")],
        ] * 20)
        result = ChromeWebsiteWorkflow(
            tools,
            "device",
            vision_verifier=AcceptingVisionVerifier(),
            settle_seconds=0,
            host_timeout_seconds=0,
        ).run("https://yuelimei.cn", "result.png")
        self.assertEqual(ChromeWorkflowStatus.COMPLETED, result.status)
        self.assertIn("豆包视觉验证页面", result.steps)

    def test_keeps_device_success_when_cloud_verifier_is_unavailable(self):
        tools = FakeChromeTools([
            [ScreenElement(text="Search or type URL")],
            [ScreenElement(text="深圳悦丽美贸易有限公司")],
        ])
        result = ChromeWebsiteWorkflow(
            tools,
            "device",
            vision_verifier=FailingVisionVerifier(),
            settle_seconds=0,
            host_timeout_seconds=0,
        ).run("https://yuelimei.cn", "result.png")
        self.assertEqual(ChromeWorkflowStatus.COMPLETED_UNVERIFIED, result.status)
        self.assertIn("ModelNotOpen", result.detail)
        self.assertIn("豆包视觉验证不可用", result.steps)

    def test_rejects_non_http_url(self):
        tools = FakeChromeTools([])
        result = ChromeWebsiteWorkflow(tools, "device", settle_seconds=0).run("file:///etc/passwd")
        self.assertEqual(ChromeWorkflowStatus.FAILED, result.status)


if __name__ == "__main__":
    unittest.main()
