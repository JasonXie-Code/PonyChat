from __future__ import annotations

import argparse
import json
import sys

from .mcp_client import MobileMcpTools, StdioMcpClient
from .chrome_workflow import ChromeWebsiteWorkflow, ChromeWorkflowStatus
from .backend_vision import BackendDeepSeekVisionVerifier
from .qq_task import parse_qq_message_task
from .qq_workflow import QqMessageWorkflow, WorkflowStatus
from .image_share_task import parse_browser_image_to_qq_task
from .image_to_qq_workflow import BrowserImageToQqWorkflow, ImageShareStatus
from .qq_reply_daemon import QqReplyDaemon
from .backend_agent_brain import BackendMobileAgentBrain
from .general_agent import AgentStatus, GeneralDeviceAgent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Companion mobile task through Mobile MCP")
    parser.add_argument("instruction", nargs="?", default="")
    parser.add_argument("--device", default="", help="Mobile MCP device id; defaults to the only online Android device")
    parser.add_argument("--check", action="store_true", help="Only verify Mobile MCP and device connectivity")
    parser.add_argument("--open-url", default="", help="Run the deterministic Chrome website workflow")
    parser.add_argument("--screenshot", default="", help="Save the final mobile screenshot to this path")
    parser.add_argument("--select-contact", default="", help="Resume a paused QQ share with this exact visible contact")
    parser.add_argument("--remember-as", default="", help="Remember --select-contact under this user nickname")
    parser.add_argument("--watch-qq-replies", action="store_true", help="Watch Companion private-reply events and execute them through Mobile MCP")
    parser.add_argument("--autonomous", action="store_true", help="Run the instruction with the general observe-act-verify-repair agent")
    args = parser.parse_args()

    image_task = parse_browser_image_to_qq_task(args.instruction)
    task = parse_qq_message_task(args.instruction)
    if not args.check and not args.open_url and not args.select_contact and not args.watch_qq_replies and not args.autonomous and not task and not image_task:
        print(json.dumps({
            "status": "missing_details",
            "detail": "请同时说明精确联系人和要发送的内容",
        }, ensure_ascii=False))
        return 2

    with StdioMcpClient() as client:
        tools = MobileMcpTools(client)
        devices = tools.list_devices()
        device_id = args.device
        if not device_id:
            android_devices = [device for device in devices if device.get("platform") == "android" and device.get("state") == "online"]
            if len(android_devices) == 1:
                device_id = str(android_devices[0].get("id") or "")
        if not any(device.get("id") == device_id for device in devices):
            print(json.dumps({
                "status": "device_not_found",
                "detail": f"未找到唯一设备，请通过 --device 指定 Mobile MCP 设备 id：{device_id or '(empty)'}",
                "devices": devices,
            }, ensure_ascii=False))
            return 1
        if args.check:
            apps = tools.list_apps(device_id)
            print(json.dumps({
                "status": "ok",
                "device": device_id,
                "qq_installed": "com.tencent.mobileqq" in apps,
                "devices": devices,
            }, ensure_ascii=False))
            return 0
        if args.watch_qq_replies:
            QqReplyDaemon(tools, device_id).run()
            return 0
        if args.autonomous:
            if not args.instruction.strip():
                print(json.dumps({"status": "missing_details", "detail": "请提供设备任务"}, ensure_ascii=False))
                return 2
            result = GeneralDeviceAgent(tools, device_id, BackendMobileAgentBrain()).run(args.instruction)
            print(json.dumps({
                "status": result.status.value,
                "detail": result.detail,
                "turns": len(result.turns),
            }, ensure_ascii=False))
            return 0 if result.status is AgentStatus.COMPLETED else 1
        if args.open_url:
            verifier = BackendDeepSeekVisionVerifier() if args.screenshot else None
            chrome_result = ChromeWebsiteWorkflow(
                tools,
                device_id,
                vision_verifier=verifier,
            ).run(args.open_url, args.screenshot)
            print(json.dumps({
                "status": chrome_result.status.value,
                "detail": chrome_result.detail,
                "screenshot": chrome_result.screenshot_path,
                "steps": chrome_result.steps,
            }, ensure_ascii=False))
            return 0 if chrome_result.status in {
                ChromeWorkflowStatus.COMPLETED,
                ChromeWorkflowStatus.COMPLETED_UNVERIFIED,
            } else 1
        if args.select_contact:
            result = BrowserImageToQqWorkflow(tools, device_id).resume_contact_selection(
                args.select_contact,
                remember_as=args.remember_as,
                screenshot_path=args.screenshot,
            )
            print(json.dumps({
                "status": result.status.value,
                "detail": result.detail,
                "screenshot": result.screenshot_path,
                "steps": result.steps,
            }, ensure_ascii=False))
            return 0 if result.status is ImageShareStatus.COMPLETED else 1
        if image_task:
            result = BrowserImageToQqWorkflow(tools, device_id).run(image_task, args.screenshot)
            print(json.dumps({
                "status": result.status.value,
                "detail": result.detail,
                "screenshot": result.screenshot_path,
                "contact_candidates": result.contact_candidates,
                "steps": result.steps,
            }, ensure_ascii=False))
            return 0 if result.status is ImageShareStatus.COMPLETED else 1
        assert task is not None
        result = QqMessageWorkflow(tools, device_id).run(task)
    print(json.dumps({
        "status": result.status.value,
        "detail": result.detail,
        "steps": result.steps,
    }, ensure_ascii=False))
    return 0 if result.status is WorkflowStatus.COMPLETED else 1


if __name__ == "__main__":
    sys.exit(main())
