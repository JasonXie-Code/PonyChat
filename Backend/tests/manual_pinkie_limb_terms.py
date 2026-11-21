#!/usr/bin/env python3
"""Replay the Pinkie bedside body-state turn against a live backend."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
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
    character_id = f"tmp_pinkie_limb_{uuid.uuid4().hex[:12]}"
    conversation_id = f"manual_pinkie_limb_{uuid.uuid4().hex[:12]}"
    print(f"PHASE clone character={character_id}", flush=True)
    _clone_system_character(character_id)
    try:
        token = await _make_token()
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "我来到你的房间，在床边陪着你。",
                },
                {
                    "role": "assistant",
                    "content": "（我坐在床边，后腿还有点软，脸颊发烫，心跳很快，前蹄轻轻按在床沿上。）",
                },
                {
                    "role": "user",
                    "content": "先吃吃你。",
                },
                {
                    "role": "assistant",
                    "content": "（我低垂着眼，前蹄仍按着床沿，蹄尖微微收紧，把床单抓出一点褶皱。）",
                },
                {
                    "role": "user",
                    "content": "（请详细写出当前你的身体状态）",
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
                    "X-Client-Id": "manual_pinkie_limb_terms",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            reply = _visible_reply(response.json())
        print("PHASE main reply complete", flush=True)
        print("MAIN_REPLY:\n" + reply, flush=True)
        if not reply:
            raise AssertionError("live main reply was empty")
        invalid_terms = ("手指", "指尖", "手掌", "手腕")
        hits = [term for term in invalid_terms if term in reply]
        if hits:
            raise AssertionError(f"pony reply used human limb terms: hits={hits}, reply={reply}")
        return 0
    finally:
        print("PHASE cleanup start", flush=True)
        _delete_isolated_records(character_id, conversation_id)
        print("PHASE cleanup complete", flush=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
