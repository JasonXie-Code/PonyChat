# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from agent import PonyChatGooseStyleAgent
from tools import (
    agent_tools_manifest,
    describe_pose_image_prompt_tool,
    export_conversation_document_tool,
    get_character_profile_tool,
    load_system_characters_tool,
    read_dialogue_context_tool,
    read_summaries_tool,
    search_character_setting_tool,
    search_memory_fragments_tool,
    update_working_state_tool,
)


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "load_system_characters":
        return load_system_characters_tool(arguments)
    if name == "get_character_profile":
        return get_character_profile_tool(arguments)
    if name == "search_character_setting":
        return search_character_setting_tool(arguments)
    if name == "read_dialogue_context":
        return read_dialogue_context_tool(arguments)
    if name == "search_memory_fragments":
        return search_memory_fragments_tool(arguments)
    if name == "read_summaries":
        return read_summaries_tool(arguments)
    if name == "update_working_state":
        return update_working_state_tool(arguments)
    if name == "export_conversation_document":
        return export_conversation_document_tool(arguments)
    if name == "describe_pose_image_prompt":
        return describe_pose_image_prompt_tool(arguments)
    if name == "normal_chat_turn":
        agent = PonyChatGooseStyleAgent(
            username=str(arguments.get("username") or "System"),
            remote_url=str(arguments.get("remote_url") or ""),
            refresh_roles=bool(arguments.get("refresh_roles")),
        )
        result = agent.run_turn(
            character_id=str(arguments.get("character_id") or ""),
            character_index=int(arguments.get("character_index") or 0),
            messages=arguments.get("messages") if isinstance(arguments.get("messages"), list) else [],
            latest_user_input=str(arguments.get("latest_user_input") or ""),
            memory_fragments=arguments.get("memory_fragments") if isinstance(arguments.get("memory_fragments"), list) else [],
            summaries=arguments.get("summaries") if isinstance(arguments.get("summaries"), dict) else {},
            working_state=arguments.get("working_state") if isinstance(arguments.get("working_state"), dict) else {},
        )
        return result.to_dict(include_trace=True)
    raise KeyError(f"unknown tool: {name}")


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = str(request.get("method") or "")
    request_id = request.get("id")
    if method.startswith("notifications/"):
        return None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ponychat-agent-test", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": agent_tools_manifest()}
        elif method == "tools/call":
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            name = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            data = call_tool(name, arguments)
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(data, ensure_ascii=False, indent=2),
                    }
                ],
                "isError": False,
            }
        else:
            raise KeyError(f"unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }


def serve() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            response = handle_request(request)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def self_test() -> int:
    tools = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    chat = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "normal_chat_turn",
                "arguments": {
                    "messages": [{"role": "user", "content": "今天有点累，陪我聊会儿"}],
                    "latest_user_input": "今天有点累，陪我聊会儿",
                    "character_index": 0,
                },
            },
        }
    )
    ok = bool(tools and "result" in tools and chat and "result" in chat)
    print(json.dumps({"ok": ok, "tools": tools, "chat": chat}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal stdio MCP server for Goose/PonyChat agent testing.")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
