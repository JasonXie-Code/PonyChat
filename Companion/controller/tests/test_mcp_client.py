import os
import base64
import unittest
from unittest.mock import Mock, patch

from companion_controller.mcp_client import McpError, MobileMcpTools, StdioMcpClient, sanitized_mobile_mcp_environment


class McpClientSecurityTest(unittest.TestCase):
    def test_actionable_tool_error_is_not_treated_as_success(self):
        client = StdioMcpClient()
        client._request = Mock(return_value={
            "content": [{
                "type": "text",
                "text": "Non-ASCII text is not supported. Please fix the issue and try again.",
            }],
        })

        with self.assertRaises(McpError):
            client.call_tool("mobile_type_keys", {"device": "emulator-5554", "text": "你好"})

    @patch("companion_controller.mcp_client.subprocess.run")
    @patch("companion_controller.mcp_client.shutil.which", return_value="adb")
    def test_unicode_text_uses_official_devicekit_dex(self, _which, run):
        tools = MobileMcpTools(Mock())

        tools.type_text("emulator-5554", "你好")

        encoded = base64.b64encode("你好".encode("utf-8")).decode("ascii")
        self.assertEqual("com.mobilenext.devicekit.Clipboard", run.call_args_list[0].args[0][-4])
        self.assertEqual(encoded, run.call_args_list[0].args[0][-1])
        self.assertIn("KEYCODE_PASTE", run.call_args_list[1].args[0])
        self.assertEqual("clear", run.call_args_list[2].args[0][-1])

    def test_child_environment_excludes_model_keys_and_disables_telemetry(self):
        with patch.dict(os.environ, {
            "PATH": "test-path",
            "PONYCHAT_DEEPSEEK_API_KEY": "secret-deepseek",
            "PONYCHAT_DOUBAO_API_KEY": "secret-doubao",
        }, clear=True):
            child = sanitized_mobile_mcp_environment()

        self.assertEqual("test-path", child["PATH"])
        self.assertEqual("1", child["MOBILEMCP_DISABLE_TELEMETRY"])
        self.assertEqual("1", child["MOBILEMCP_LEGACY_ROBOT"])
        self.assertNotIn("PONYCHAT_DEEPSEEK_API_KEY", child)
        self.assertNotIn("PONYCHAT_DOUBAO_API_KEY", child)
        self.assertNotIn("secret-deepseek", child.values())
        self.assertNotIn("secret-doubao", child.values())


if __name__ == "__main__":
    unittest.main()
