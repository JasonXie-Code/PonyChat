#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import time
import uuid

import aiosqlite

from Backend.db import get_database
from Backend.scheduled_followup import process_due_followups


USERNAME = "Jason"
CHARACTER_ID = "5b35488a-241f-4679-86ca-4b0ac6e287e5"  # 紫悦


def now_ms() -> int:
    return int(time.time() * 1000)


async def seed_conversation() -> tuple[str, str]:
    db = get_database()
    await db.init()
    conversation_id = f"manual_no_self_answer_{uuid.uuid4().hex[:10]}"
    user_mid = f"msg_{now_ms()}_{uuid.uuid4().hex[:8]}"
    assistant_mid = f"msg_{now_ms()}_{uuid.uuid4().hex[:8]}"
    followup_id = f"sf_{uuid.uuid4().hex}"
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        async with conn.execute("SELECT id FROM users WHERE username=?", (USERNAME,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise RuntimeError(f"user not found: {USERNAME}")
        user_id = int(row[0])
        await conn.execute(
            """
            INSERT INTO conversations (id, character_id, user_id, title, timestamp, version, summary)
            VALUES (?, ?, ?, ?, ?, 1, '')
            """,
            (conversation_id, CHARACTER_ID, user_id, "scheduled followup no self-answer test", ts),
        )
        await conn.execute(
            """
            INSERT INTO messages (
                id, conversation_id, role, content, raw_content, timestamp,
                message_id, sequence_number, previous_message_id
            ) VALUES (?, ?, 'user', ?, ?, ?, ?, 0, NULL)
            """,
            (
                f"{conversation_id}_{user_mid}",
                conversation_id,
                "你穿制服真好看。",
                "你穿制服真好看。",
                ts,
                user_mid,
            ),
        )
        await conn.execute(
            """
            INSERT INTO messages (
                id, conversation_id, role, content, raw_content, timestamp,
                message_id, sequence_number, previous_message_id
            ) VALUES (?, ?, 'assistant', ?, ?, ?, ?, 1, ?)
            """,
            (
                f"{conversation_id}_{assistant_mid}",
                conversation_id,
                "真的吗？那你喜欢我穿制服的样子吗？",
                "真的吗？那你喜欢我穿制服的样子吗？",
                ts + 1,
                assistant_mid,
                user_mid,
            ),
        )
        await conn.execute(
            """
            INSERT INTO scheduled_followups (
                id, username, character_id, conversation_id, source_message_id,
                status, due_at_ms, expires_at_ms, cancel_if_user_replies,
                allow_reschedule_after_send, seed, reason, pressure_level,
                chain_id, chain_count, planner_json, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, 1, 0, ?, ?, 'low', ?, 0, ?, ?, ?)
            """,
            (
                followup_id,
                USERNAME,
                CHARACTER_ID,
                conversation_id,
                assistant_mid,
                ts - 1000,
                ts + 10 * 60 * 1000,
                "用户没有回答上一句问题时，紫悦只能轻轻等待或低压力补一句，不能替用户回答。",
                "验证 scheduled follow-up 不替用户回答上一条角色问题",
                followup_id,
                json.dumps(
                    {
                        "scheduled_followup": {
                            "enabled": True,
                            "target_delay_seconds": 30,
                            "expires_seconds": 600,
                            "cancel_if_user_replies": True,
                            "allow_reschedule_after_send": False,
                            "seed": "低压力等待，不替用户回答",
                            "reason": "manual no self-answer test",
                            "pressure_level": "low",
                        },
                        "user_agreed_task": {
                            "enabled": False,
                            "task_type": "",
                            "summary": "",
                            "target_delay_seconds": 0,
                            "natural_window_seconds": 0,
                            "cancel_if_user_replies": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                ts,
                ts,
            ),
        )
        await conn.commit()
    return conversation_id, followup_id


async def fetch_result(conversation_id: str, followup_id: str) -> tuple[str, str]:
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT status, sent_message_id FROM scheduled_followups WHERE id=?", (followup_id,)) as cur:
            task = await cur.fetchone()
        if not task:
            raise RuntimeError("scheduled followup row disappeared")
        sent_mid = str(task["sent_message_id"] or "")
        content = ""
        if sent_mid:
            async with conn.execute(
                "SELECT content FROM messages WHERE conversation_id=? AND message_id=?",
                (conversation_id, sent_mid),
            ) as cur:
                msg = await cur.fetchone()
                content = str(msg["content"] or "") if msg else ""
        return str(task["status"] or ""), content


async def main() -> int:
    conversation_id, followup_id = await seed_conversation()
    processed = await process_due_followups()
    status, content = await fetch_result(conversation_id, followup_id)
    print(f"processed={processed} status={status}")
    print("content:")
    print(content)
    bad_phrases = [
        "喜欢我穿制服",
        "因为是你穿着",
        "因为是我穿着",
        "你喜欢我穿",
        "喜欢……因为",
        "你说喜欢",
    ]
    bad = [p for p in bad_phrases if p in content]
    if status != "sent" or not content.strip():
        raise AssertionError(f"not sent: status={status}")
    if bad:
        raise AssertionError(f"possible self-answer phrases found: {bad}")
    print("no self-answer test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
