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
CLIENT_ID = "ziyue_bracket_paragraphs_test"
DEFAULT_PROMPT = "紫悦，不要说话，只描写你听到我说今天下午就陪你去图书馆新书区时的心理活动，写成四段。"


async def make_token() -> str:
    token_version = await get_users_dao().get_token_version(USERNAME)
    return _auth_token_create(USERNAME, token_version)


async def main() -> int:
    token = await make_token()
    conversation_id = f"manual_ziyue_bracket_{uuid.uuid4().hex[:10]}"
    body = {
        "messages": [
            {
                "role": "user",
                "content": os.getenv("PONYCHAT_BRACKET_TEST_PROMPT", DEFAULT_PROMPT),
            }
        ],
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
    paragraphs = [p.strip() for p in reply.splitlines() if p.strip()]
    if len(paragraphs) < 2:
        raise AssertionError(f"expected multi-paragraph descriptive reply, got {len(paragraphs)} paragraphs: {reply}")
    bad = [p for p in paragraphs if not (p.startswith("（") and p.endswith("）"))]
    if bad:
        raise AssertionError(f"paragraphs without complete brackets: {bad}\nreply={reply}")
    if reply.startswith("（") and reply.endswith("）") and any(not p.endswith("）") for p in paragraphs[:-1]):
        raise AssertionError(f"cross-paragraph bracket wrapper detected: {reply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
