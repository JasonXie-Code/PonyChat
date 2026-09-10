from __future__ import annotations

import json
import base64
import os
from pathlib import Path
import shutil
import subprocess
import threading
from collections import deque
from typing import Any

from .mobile_tools import ScreenElement, parse_elements_tool_result


class McpError(RuntimeError):
    pass


def sanitized_mobile_mcp_environment() -> dict[str, str]:
    allowed = (
        "PATH", "PATHEXT", "SystemRoot", "WINDIR", "COMSPEC", "USERPROFILE",
        "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "ANDROID_HOME", "ANDROID_SDK_ROOT",
    )
    env = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    env["MOBILEMCP_DISABLE_TELEMETRY"] = "1"
    # mobilecli currently exposes only the root node on the Android 16 AVD.
    # Mobile MCP's maintained legacy robot uses its complete UIAutomator tree.
    env["MOBILEMCP_LEGACY_ROBOT"] = "1"
    return env


class StdioMcpClient:
    def __init__(self, command: list[str] | None = None) -> None:
        npx = "npx.cmd" if os.name == "nt" else "npx"
        self.command = command or [npx, "-y", "@mobilenext/mobile-mcp@latest"]
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._stderr_lines: deque[str] = deque(maxlen=50)
        self._stderr_thread: threading.Thread | None = None

    def __enter__(self) -> "StdioMcpClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        if self.process:
            return
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=sanitized_mobile_mcp_environment(),
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self._request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "ponychat-companion", "version": "0.1.0"},
        })
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        if not self.process:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process = None

    def _drain_stderr(self) -> None:
        process = self.process
        if not process or not process.stderr:
            return
        for line in process.stderr:
            self._stderr_lines.append(line.rstrip())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        content = self._content_text(result)
        # Mobile MCP currently returns ActionableError as a successful MCP result.
        # Promote its documented suffix to an exception so workflows cannot
        # silently continue after a failed device action.
        actionable = content.rstrip().endswith("Please fix the issue and try again.")
        if result.get("isError") or actionable:
            raise McpError(content or f"Mobile MCP tool failed: {name}")
        return content

    @staticmethod
    def _content_text(result: dict[str, Any]) -> str:
        return "\n".join(
            str(block.get("text", ""))
            for block in result.get("content", [])
            if block.get("type") == "text"
        )

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            assert self.process and self.process.stdout
            while True:
                line = self.process.stdout.readline()
                if not line:
                    stderr = "\n".join(self._stderr_lines)
                    raise McpError(f"Mobile MCP exited unexpectedly: {stderr[-1000:]}")
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if response.get("id") != request_id:
                    continue
                if "error" in response:
                    raise McpError(str(response["error"]))
                return response.get("result") or {}

    def _write(self, payload: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise McpError("Mobile MCP is not running")
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()


class MobileMcpTools:
    def __init__(self, client: StdioMcpClient) -> None:
        self.client = client

    def list_devices(self) -> list[dict[str, Any]]:
        result = self.client.call_tool("mobile_list_available_devices", {})
        payload = json.loads(result)
        return list(payload.get("devices") or [])

    def list_apps(self, device: str) -> str:
        return self.client.call_tool("mobile_list_apps", {"device": device})

    def launch_app(self, device: str, package_name: str) -> str:
        return self.client.call_tool("mobile_launch_app", {"device": device, "packageName": package_name})

    def list_elements(self, device: str) -> list[ScreenElement]:
        result = self.client.call_tool("mobile_list_elements_on_screen", {"device": device})
        return parse_elements_tool_result(result)

    def click(self, device: str, x: int, y: int) -> str:
        return self.client.call_tool("mobile_click_on_screen_at_coordinates", {"device": device, "x": x, "y": y})

    def long_press(self, device: str, x: int, y: int, duration_ms: int = 700) -> str:
        return self.client.call_tool("mobile_long_press_on_screen_at_coordinates", {
            "device": device,
            "x": x,
            "y": y,
            "duration": duration_ms,
        })

    def swipe(
        self,
        device: str,
        direction: str,
        *,
        x: int | None = None,
        y: int | None = None,
        distance: int | None = None,
    ) -> str:
        arguments: dict[str, Any] = {"device": device, "direction": direction}
        if x is not None:
            arguments["x"] = x
        if y is not None:
            arguments["y"] = y
        if distance is not None:
            arguments["distance"] = distance
        return self.client.call_tool("mobile_swipe_on_screen", arguments)

    def type_text(self, device: str, text: str, submit: bool = False) -> str:
        if any(ord(character) > 127 for character in text):
            self._type_unicode_with_devicekit(device, text)
            if submit:
                self.press_button(device, "ENTER")
            return "Typed Unicode text with Mobile Next DeviceKit"
        return self.client.call_tool("mobile_type_keys", {"device": device, "text": text, "submit": submit})

    def clear_text(self, device: str) -> str:
        adb = self._adb_path()
        subprocess.run(
            [adb, "-s", device, "shell", "input", "keyevent", "KEYCODE_MOVE_END"],
            check=True, capture_output=True, text=True, timeout=15,
        )
        subprocess.run(
            [adb, "-s", device, "shell", "input", "keyevent", *(["KEYCODE_DEL"] * 128)],
            check=True, capture_output=True, text=True, timeout=15,
        )
        return "Cleared focused text field"

    @staticmethod
    def _adb_path() -> str:
        adb = shutil.which("adb")
        if not adb and os.environ.get("LOCALAPPDATA"):
            candidate = Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
            if candidate.is_file():
                adb = str(candidate)
        if not adb:
            raise McpError("Android adb executable was not found")
        return adb

    @classmethod
    def _type_unicode_with_devicekit(cls, device: str, text: str) -> None:
        adb = cls._adb_path()

        dex_path = "/data/local/tmp/devicekit.dex"
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        base = [adb, "-s", device, "shell", f"CLASSPATH={dex_path}", "app_process", "/"]
        try:
            subprocess.run(
                [*base, "com.mobilenext.devicekit.Clipboard", "set", "--base64", encoded],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            subprocess.run(
                [adb, "-s", device, "shell", "input", "keyevent", "KEYCODE_PASTE"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise McpError(f"DeviceKit Unicode input failed: {detail or exc.returncode}") from exc
        finally:
            subprocess.run(
                [*base, "com.mobilenext.devicekit.Clipboard", "clear"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )

    def press_button(self, device: str, button: str) -> str:
        return self.client.call_tool("mobile_press_button", {"device": device, "button": button})

    def open_url(self, device: str, url: str) -> str:
        return self.client.call_tool("mobile_open_url", {"device": device, "url": url})

    def save_screenshot(self, device: str, path: str) -> str:
        return self.client.call_tool("mobile_save_screenshot", {"device": device, "saveTo": path})
