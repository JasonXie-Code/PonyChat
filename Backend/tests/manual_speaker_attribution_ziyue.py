#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx

from Backend.db import get_users_dao
from Backend.routes.auth import _auth_token_create


BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "https://ponychat.org")
USERNAME = "Jason"
CHARACTER_ID = "5b35488a-241f-4679-86ca-4b0ac6e287e5"  # 紫悦
CLIENT_ID = "speaker_attribution_ziyue_test"


async def make_token() -> str:
    token_version = await get_users_dao().get_token_version(USERNAME)
    return _auth_token_create(USERNAME, token_version)


async def main() -> int:
    token = await make_token()
    conversation_id = f"manual_speaker_attr_ziyue_{uuid.uuid4().hex[:10]}"
    messages = [
        {
            "role": "user",
            "content": "紫悦，你刚才说自己小时候在云中城读书时很孤单，那后来为什么还愿意继续学习魔法呢？",
        },
        {
            "role": "assistant",
            "content": "因为我那时候觉得，书本至少不会笑我，也不会嫌我问太多问题。云中城那段经历其实是我自己刚刚说出来的，不是你告诉我的；你只是愿意听我把它讲完，这让我觉得很安心。",
        },
        {
            "role": "user",
            "content": "（举起杯子示意你碰杯）",
        },
    ]
    body = {
        "messages": messages,
        "username": USERNAME,
        "character_id": CHARACTER_ID,
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    async with httpx.AsyncClient(timeout=180.0, verify=False) as client:
        resp = await client.post(
            f"{BASE_URL.rstrip('/')}/api/chat",
            json=body,
            headers={
                "X-Chat-Auth": token,
                "X-Client-Id": CLIENT_ID,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts: list[str] = []
        for ev in data.get("events") or []:
            for ch in ev.get("choices") or []:
                content = ((ch.get("delta") or {}).get("content") or "")
                if content:
                    parts.append(content)
        reply = "".join(parts).strip()
    else:
        reply = json.dumps(data, ensure_ascii=False)

    print(reply)
    forbidden = ["你告诉我", "你跟我说", "你分享给我", "你让我知道", "把云中城的事告诉我"]
    hits = [phrase for phrase in forbidden if phrase in reply]
    if hits:
        raise AssertionError(f"speaker attribution still wrong: {hits}\nreply={reply}")
    if not any(phrase in reply for phrase in ["听我说", "听我讲", "陪我聊", "愿意听", "被理解"]):
        raise AssertionError(f"reply avoided wrong attribution but did not acknowledge listening/understanding: {reply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
