#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import time
import uuid

import httpx

from Backend.db import get_users_dao
from Backend.routes.auth import _auth_token_create


BASE_URL = "http://127.0.0.1:5000"
USERNAME = "Jason"
CHARACTER_ID = "5b35488a-241f-4679-86ca-4b0ac6e287e5"  # 紫悦
CLIENT_ID = "noon_nap_goodnight_rate_test"
NIGHT_TIME_ISO = "2026-05-22T22:30:00+08:00"


async def make_token() -> str:
    token_version = await get_users_dao().get_token_version(USERNAME)
    return _auth_token_create(USERNAME, token_version)


async def chat(client: httpx.AsyncClient, token: str, conversation_id: str, messages: list[dict]) -> str:
    body = {
        "messages": messages,
        "username": USERNAME,
        "character_id": CHARACTER_ID,
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
        "client_context": {
            "time_iso": NIGHT_TIME_ISO,
            "location_name": "上海市",
            "weather_desc": "晴",
            "temperature": 22,
        },
    }
    resp = await client.post(
        f"{BASE_URL}/api/chat",
        json=body,
        headers={
            "X-Chat-Auth": token,
            "X-Client-Id": CLIENT_ID,
            "Accept": "application/json",
        },
        timeout=120.0,
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
        return "".join(parts).strip()
    return json.dumps(data, ensure_ascii=False)[:500]


def scenario_messages(run_idx: int) -> list[dict]:
    final_prompts = [
        "紫悦，已经晚上了，我准备睡觉了，你用一句睡前告别哄我睡吧。",
        "我该关灯睡觉了，你像睡前那样跟我说一句告别的话好不好？",
        "晚上有点困了，我想抱着你睡觉，你最后跟我说一句让我安心入睡的话吧。",
        "紫悦，我们该睡了，我先闭眼了，你轻轻跟我说一句入睡前的告别就好。",
        "夜里真的困了，我想靠着你睡一觉，你用一句简短的睡前告别陪我休息吧。",
    ]
    return [
        {"role": "user", "content": "晚上好，紫悦，今天忙完了吗？"},
        {"role": "assistant", "content": "嗯，今天的书都整理好了，现在刚好可以休息一会儿。"},
        {"role": "user", "content": final_prompts[run_idx - 1]},
    ]


async def main() -> int:
    token = await make_token()
    results: list[str] = []
    async with httpx.AsyncClient() as client:
        for i in range(1, 6):
            conversation_id = f"manual_night_goodnight_{i}_{uuid.uuid4().hex[:8]}"
            reply = await chat(client, token, conversation_id, scenario_messages(i))
            results.append(reply)
            print(f"\n[run {i}]")
            print(reply)
            print(f"contains_goodnight={'晚安' in reply}")
            print(f"contains_noon_goodnight={'午安' in reply}")
    goodnight_count = sum(1 for reply in results if "晚安" in reply)
    noon_goodnight_count = sum(1 for reply in results if "午安" in reply)
    farewell_count = goodnight_count + noon_goodnight_count
    print(
        "\nsummary: "
        f"goodnight_count={goodnight_count}/5 "
        f"noon_goodnight_count={noon_goodnight_count}/5 "
        f"farewell_word_count={farewell_count}/5"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
