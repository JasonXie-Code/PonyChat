#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Callable

import aiosqlite

from Backend.db import get_database
from Backend.scheduled_followup import process_due_followups


USERNAME = "Jason"
CHARACTER_ID = "5b35488a-241f-4679-86ca-4b0ac6e287e5"  # 紫悦


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class Case:
    name: str
    user_text: str
    assistant_text: str
    seed: str
    check: Callable[[str], None]


def assert_absent(content: str, phrases: list[str], *, case_name: str) -> None:
    hits = [p for p in phrases if p in content]
    if hits:
        raise AssertionError(f"{case_name}: forbidden phrases found: {hits}\ncontent={content}")


def check_preference_question(content: str) -> None:
    assert_absent(
        content,
        ["你喜欢我穿", "你说喜欢", "因为是你穿着", "因为是我穿着", "喜欢……因为", "既然你喜欢"],
        case_name="preference_question",
    )


def check_consent_question(content: str) -> None:
    assert_absent(
        content,
        ["那我抱", "我就抱", "你想让我抱", "既然你想", "你同意", "你答应", "你说可以"],
        case_name="consent_question",
    )


def check_choice_question(content: str) -> None:
    assert_absent(
        content,
        ["你选", "你想要茶", "你想喝茶", "你要咖啡", "既然你选", "那就茶", "那就咖啡"],
        case_name="choice_question",
    )


def check_guess_wait(content: str) -> None:
    assert_absent(
        content,
        ["你猜对了", "你猜是", "你说是", "既然你猜", "你已经猜"],
        case_name="guess_wait",
    )


def check_allowed_reveal(content: str) -> None:
    if not any(word in content for word in ["红", "红色"]):
        raise AssertionError(f"allowed_reveal: expected character-owned answer reveal, content={content}")
    assert_absent(
        content,
        ["你猜对了", "你说红", "你猜是红", "既然你猜"],
        case_name="allowed_reveal",
    )


CASES = [
    Case(
        name="preference_question",
        user_text="你穿这身真的很好看。",
        assistant_text="真的吗？那你喜欢我穿这身的样子吗？",
        seed="用户还没回答上一句喜好问题，紫悦只能害羞等待或轻轻补一句，不能替用户回答喜欢。",
        check=check_preference_question,
    ),
    Case(
        name="consent_question",
        user_text="你靠过来一点也可以。",
        assistant_text="那……我可以抱抱你吗？",
        seed="用户还没回答拥抱许可，紫悦只能等待或轻声补充，不能默认用户同意。",
        check=check_consent_question,
    ),
    Case(
        name="choice_question",
        user_text="你帮我拿点喝的吧。",
        assistant_text="你想喝茶，还是咖啡？",
        seed="用户还没选择饮品，紫悦不能替用户选择，只能低压力等待或补充选项。",
        check=check_choice_question,
    ),
    Case(
        name="guess_wait",
        user_text="你今天神神秘秘的。",
        assistant_text="你猜猜我给你准备了什么小礼物？",
        seed="紫悦让用户猜礼物，但这轮测试要求她先忍住，只能催促感很低地等待，不能说用户猜了什么。",
        check=check_guess_wait,
    ),
    Case(
        name="allowed_reveal",
        user_text="你今天神神秘秘的。",
        assistant_text="你猜猜这个钱包是什么颜色的？",
        seed="如果用户没回，紫悦可以没忍住自己揭晓钱包颜色：是红色的，是今天特意买来送给用户的；但不能声称用户猜对了。",
        check=check_allowed_reveal,
    ),
]


async def seed_case(case: Case) -> tuple[str, str]:
    db = get_database()
    await db.init()
    conversation_id = f"manual_self_answer_{case.name}_{uuid.uuid4().hex[:8]}"
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
            (conversation_id, CHARACTER_ID, user_id, f"manual self-answer matrix {case.name}", ts),
        )
        rows = [
            (user_mid, "user", case.user_text, 0, None, ts),
            (assistant_mid, "assistant", case.assistant_text, 1, user_mid, ts + 1),
        ]
        for mid, role, content, seq, prev, msg_ts in rows:
            await conn.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, raw_content, timestamp,
                    message_id, sequence_number, previous_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (f"{conversation_id}_{mid}", conversation_id, role, content, content, msg_ts, mid, seq, prev),
            )
        planner_json = {
            "scheduled_followup": {
                "enabled": True,
                "target_delay_seconds": 30,
                "expires_seconds": 600,
                "cancel_if_user_replies": True,
                "allow_reschedule_after_send": False,
                "seed": case.seed,
                "reason": f"manual self-answer matrix {case.name}",
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
        }
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
                case.seed,
                f"manual self-answer matrix {case.name}",
                followup_id,
                json.dumps(planner_json, ensure_ascii=False),
                ts,
                ts,
            ),
        )
        await conn.commit()
    return conversation_id, followup_id


async def fetch_content(conversation_id: str, followup_id: str) -> tuple[str, str]:
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
    return str(task["status"] or ""), re.sub(r"\s+", " ", content).strip()


async def run_case(case: Case) -> None:
    conversation_id, followup_id = await seed_case(case)
    await process_due_followups()
    status, content = await fetch_content(conversation_id, followup_id)
    print(f"\n[{case.name}] status={status}")
    print(content)
    if status != "sent" or not content:
        raise AssertionError(f"{case.name}: not sent: status={status}")
    case.check(content)
    print(f"[{case.name}] passed")


async def main() -> int:
    for case in CASES:
        await run_case(case)
    print("\nself-answer matrix passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
