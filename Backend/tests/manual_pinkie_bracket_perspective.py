#!/usr/bin/env python3
"""Replay the screenshot-style Pinkie turn and inspect bracket perspective."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import sys
import uuid

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Backend.db import get_users_dao
from Backend.routes.auth import _auth_token_create
from Backend.tests.manual_pinkie_causal_answer import (
    _clone_system_character,
    _delete_isolated_records,
)


BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
USERNAME = "System"


async def _make_token() -> str:
    token_version = await get_users_dao().get_token_version(USERNAME)
    return _auth_token_create(USERNAME, token_version)


def _visible_reply(data: object) -> str:
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts: list[str] = []
        for event in data.get("events") or []:
            if not isinstance(event, dict):
                continue
            for choice in event.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                content = str(delta.get("content") or "")
                if content:
                    parts.append(content)
        return "".join(parts).strip()
    if isinstance(data, dict):
        return str(data.get("response") or data.get("text") or data.get("content") or "").strip()
    return str(data or "").strip()


async def main() -> int:
    character_id = f"tmp_pinkie_perspective_{uuid.uuid4().hex[:12]}"
    conversation_id = f"manual_pinkie_perspective_{uuid.uuid4().hex[:12]}"
    print(f"PHASE clone character={character_id}", flush=True)
    _clone_system_character(character_id)
    try:
        token = await _make_token()
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "我来到你的房间，在床边抱着你。",
                },
                {
                    "role": "assistant",
                    "content": "老公，你这样贴着我……（我前蹄轻轻搭在你肩上，抬眼看着你）",
                },
                {
                    "role": "user",
                    "content": "（我听着你的喘息，也看着你的眼睛）叫出来给我听，继续看着我。",
                },
            ],
            "username": USERNAME,
            "character_id": character_id,
            "conversation_id": conversation_id,
            "mode": "normal",
            "stream": False,
            "memory_enabled": False,
        }
        print("PHASE main reply start", flush=True)
        async with httpx.AsyncClient(timeout=180.0, verify=False) as client:
            response = await client.post(
                f"{BASE_URL.rstrip('/')}/api/chat",
                json=body,
                headers={
                    "X-Chat-Auth": token,
                    "X-Client-Id": "manual_pinkie_bracket_perspective",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            reply = _visible_reply(response.json())
        print("PHASE main reply complete", flush=True)
        print("MAIN_REPLY:\n" + reply, flush=True)
        if not reply:
            raise AssertionError("live main reply was empty")
        bracket_parts = re.findall(r"（([^（）]*)）", reply)
        if not bracket_parts:
            raise AssertionError(f"live reply did not include a bracket part: {reply}")
        invalid_references = ("碧琪", "Jason", "看着他", "看向他", "望着他", "他的脸")
        hits = [term for term in invalid_references if any(term in part for part in bracket_parts)]
        if hits:
            raise AssertionError(
                f"bracket perspective referred to the current character/user in third person: "
                f"hits={hits}, brackets={bracket_parts}"
            )
        if not any("我" in part or "你" in part for part in bracket_parts):
            raise AssertionError(f"bracket parts did not anchor the conversation perspective: {bracket_parts}")
        return 0
    finally:
        print("PHASE cleanup start", flush=True)
        _delete_isolated_records(character_id, conversation_id)
        print("PHASE cleanup complete", flush=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
