#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import aiosqlite
import httpx

from Backend.db import get_database, get_users_dao
from Backend.routes.auth import _auth_token_create


BASE_URL = "http://127.0.0.1:5000"
USERNAME = "Jason"
CHARACTER_ID = "5b35488a-241f-4679-86ca-4b0ac6e287e5"  # 紫悦
CLIENT_ID = "user_agreed_task_timing_test"


def now_ms() -> int:
    return int(time.time() * 1000)


async def make_token() -> str:
    token_version = await get_users_dao().get_token_version(USERNAME)
    return _auth_token_create(USERNAME, token_version)


async def chat(client: httpx.AsyncClient, token: str, conversation_id: str, text: str) -> str:
    body = {
        "messages": [{"role": "user", "content": text, "timestamp": now_ms()}],
        "username": USERNAME,
        "character_id": CHARACTER_ID,
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
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


async def latest_followup(conversation_id: str) -> dict[str, Any] | None:
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT *
              FROM scheduled_followups
             WHERE username=? AND character_id=? AND conversation_id=?
             ORDER BY created_at_ms DESC
             LIMIT 1
            """,
            (USERNAME, CHARACTER_ID, conversation_id),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def wait_sent(task_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    db = get_database()
    while time.time() < deadline:
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM scheduled_followups WHERE id=?", (task_id,)) as cur:
                row = await cur.fetchone()
        if row and str(row["status"]) in {"sent", "cancelled", "expired", "failed"}:
            return dict(row)
        await asyncio.sleep(3)
    raise TimeoutError(f"task {task_id} not finished within {timeout_seconds}s")


def parse_plan(row: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(row.get("planner_json") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def run_case(client: httpx.AsyncClient, token: str, delay: int, label: str, wait_for_send: bool) -> None:
    conversation_id = f"manual_timer_{delay}_{uuid.uuid4().hex[:10]}"
    started = now_ms()
    text = f"亲爱的，我们口头约定一下，{label}后提醒我一下，这是定时测试。你先正常回复我就行。"
    reply = await chat(client, token, conversation_id, text)
    print(f"\n[{label}] 主回复: {reply[:160]}")

    row = None
    for _ in range(20):
        row = await latest_followup(conversation_id)
        if row:
            break
        await asyncio.sleep(1)
    if not row:
        raise AssertionError(f"{label}: no scheduled_followup row")

    plan = parse_plan(row)
    agreed = plan.get("user_agreed_task") or {}
    if not agreed.get("enabled"):
        raise AssertionError(f"{label}: user_agreed_task not enabled: {plan}")
    target_delay = int(agreed.get("target_delay_seconds") or 0)
    if abs(target_delay - delay) > max(5, int(delay * 0.15)):
        raise AssertionError(f"{label}: target_delay_seconds={target_delay}, expected around {delay}")

    due_at = int(row.get("due_at_ms") or 0)
    created_at = int(row.get("created_at_ms") or 0)
    due_delta_from_user = int((due_at - started) / 1000)
    due_delta_from_schedule = int((due_at - created_at) / 1000)
    print(
        f"[{label}] 预约 OK: id={row['id']} status={row['status']} "
        f"due_delta_from_schedule={due_delta_from_schedule}s "
        f"due_delta_from_user={due_delta_from_user}s agreed={agreed}"
    )
    if abs(due_delta_from_schedule - delay) > max(8, int(delay * 0.2)):
        raise AssertionError(f"{label}: due_delta_from_schedule={due_delta_from_schedule}, expected around {delay}")

    if not wait_for_send:
        return

    finished = await wait_sent(str(row["id"]), delay + 180)
    status = str(finished.get("status") or "")
    sent_id = str(finished.get("sent_message_id") or "")
    print(f"[{label}] 执行结果: status={status} sent_message_id={sent_id}")
    if status != "sent" or not sent_id:
        raise AssertionError(f"{label}: not sent: {finished}")


async def main() -> int:
    token = await make_token()
    async with httpx.AsyncClient() as client:
        await run_case(client, token, 30, "30秒", True)
        await run_case(client, token, 60, "1分钟", True)
        await run_case(client, token, 180, "3分钟", True)
        await run_case(client, token, 7200, "2小时", False)
    print("\n全部手动定时测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
