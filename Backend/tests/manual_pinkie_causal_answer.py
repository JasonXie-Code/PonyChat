#!/usr/bin/env python3
"""Replay the Pinkie "why are you shy" turn against a live backend."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import sys
import time
import uuid

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Backend.db import get_database
from Backend.proactive_settings import ProactiveSettings
from Backend import scheduled_followup
from Backend import config as backend_config


SOURCE_CHARACTER_ID = "pinkie_pie"


def _clone_system_character(character_id: str) -> None:
    db = get_database()
    with sqlite3.connect(db.db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        source = conn.execute(
            "SELECT * FROM characters WHERE id = ?",
            (SOURCE_CHARACTER_ID,),
        ).fetchone()
        system_user = conn.execute(
            "SELECT id FROM users WHERE username = 'System'",
        ).fetchone()
        if source is None or system_user is None:
            raise RuntimeError("System Pinkie source character is unavailable")

        columns = {row[1] for row in conn.execute("PRAGMA table_info(characters)")}
        copy_columns = [
            name
            for name in source.keys()
            if name in columns and name not in {"id", "user_id"}
        ]
        values = [source[name] for name in copy_columns]
        if "is_official_source" in copy_columns:
            values[copy_columns.index("is_official_source")] = 0
        if "is_official_reference" in copy_columns:
            values[copy_columns.index("is_official_reference")] = 0
        if "official_source_id" in copy_columns:
            values[copy_columns.index("official_source_id")] = SOURCE_CHARACTER_ID
        sql_columns = ["id", "user_id", *copy_columns]
        placeholders = ", ".join("?" for _ in sql_columns)
        conn.execute(
            f"INSERT INTO characters ({', '.join(sql_columns)}) VALUES ({placeholders})",
            (character_id, int(system_user[0]), *values),
        )
        conn.commit()


def _seed_isolated_conversation(
    character_id: str,
    conversation_id: str,
    messages: list[dict],
) -> None:
    db = get_database()
    with sqlite3.connect(db.db_path, timeout=10) as conn:
        conn.execute("PRAGMA busy_timeout = 10000")
        system_user = conn.execute(
            "SELECT id FROM users WHERE username = 'System'",
        ).fetchone()
        if system_user is None:
            raise RuntimeError("System user is unavailable")
        now_ms = int(time.time() * 1000)
        conn.execute(
            """
            INSERT INTO conversations (id, character_id, user_id, title, timestamp, version, summary)
            VALUES (?, ?, ?, ?, ?, 1, '')
            """,
            (conversation_id, character_id, int(system_user[0]), "manual Pinkie proactive grounding", now_ms),
        )
        previous_id: str | None = None
        for index, message in enumerate(messages):
            message_id = str(message["message_id"])
            conn.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, raw_content, timestamp,
                    message_id, sequence_number, previous_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{conversation_id}_{message_id}",
                    conversation_id,
                    str(message["role"]),
                    str(message["content"]),
                    str(message["content"]),
                    int(message["timestamp"]),
                    message_id,
                    index,
                    previous_id,
                ),
            )
            previous_id = message_id
        conn.commit()


def _delete_isolated_records(character_id: str, conversation_id: str) -> None:
    db = get_database()
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            with sqlite3.connect(db.db_path, timeout=5) as conn:
                conn.execute("PRAGMA busy_timeout = 5000")
                conn.execute("PRAGMA foreign_keys = OFF")
                tables = [
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                    )
                ]
                for table in tables:
                    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                    if "conversation_id" in columns:
                        conn.execute(f"DELETE FROM {table} WHERE conversation_id = ?", (conversation_id,))
                    if "character_id" in columns:
                        conn.execute(f"DELETE FROM {table} WHERE character_id = ?", (character_id,))
                    if table == "conversations" and "id" in columns:
                        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
                    if table == "characters" and "id" in columns:
                        conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))
                conn.commit()
                remaining = conn.execute(
                    "SELECT COUNT(*) FROM characters WHERE id = ?",
                    (character_id,),
                ).fetchone()[0]
                if remaining:
                    raise RuntimeError(f"failed to delete isolated character: {character_id}")
                return
        except sqlite3.OperationalError as exc:
            last_error = exc
            if "locked" not in str(exc).lower() or attempt >= 5:
                raise
            time.sleep(0.5)
    raise RuntimeError(f"failed to clean isolated records: {last_error}")


async def main() -> int:
    username = "System"
    character_id = f"tmp_pinkie_causal_{uuid.uuid4().hex[:12]}"
    conversation_id = f"manual_pinkie_causal_{uuid.uuid4().hex[:12]}"
    print(f"PHASE clone character={character_id}", flush=True)
    _clone_system_character(character_id)

    try:
        now_ms = int(time.time() * 1000)
        messages = [
            {
                "role": "user",
                "content": (
                    "【用户发送表情包】紫悦歪着头、吐着舌头，做了一个夸张又像在撒娇的搞怪表情。"
                ),
                "timestamp": now_ms - 3000,
                "message_id": f"manual_user_sticker_{uuid.uuid4().hex[:8]}",
            },
            {
                "role": "assistant",
                "content": (
                    "（我脸颊一下子烫起来，前蹄捂住嘴，眨巴眨巴眼睛）"
                    "噢，你、你这是从哪里找来的表情包啦！紫悦知道会害羞死的！"
                ),
                "timestamp": now_ms - 2000,
                "message_id": f"manual_assistant_shy_{uuid.uuid4().hex[:8]}",
            },
            {
                "role": "user",
                "content": "为什么要害羞呀",
                "timestamp": now_ms - 1000,
                "message_id": f"manual_user_why_{uuid.uuid4().hex[:8]}",
            },
            {
                "role": "assistant",
                "content": "因为紫悦平时那么认真，这个歪头吐舌的动作反差太大啦，我觉得又搞怪又像在撒娇，所以一下子替她害羞起来了。",
                "timestamp": now_ms,
                "message_id": f"manual_assistant_reason_{uuid.uuid4().hex[:8]}",
            },
        ]
        print(f"PHASE seed conversation={conversation_id}", flush=True)
        _seed_isolated_conversation(character_id, conversation_id, messages)
        source_message_id = str(messages[-1]["message_id"])
        original_settings_loader = scheduled_followup.load_proactive_settings
        original_httpx_client = backend_config.httpx_client

        async def _enabled_test_settings(_username: str) -> ProactiveSettings:
            return ProactiveSettings(enabled=True, frequency="normal", memory_enabled=False)

        scheduled_followup.load_proactive_settings = _enabled_test_settings
        test_httpx_client = httpx.AsyncClient(
            timeout=httpx.Timeout(600.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            verify=False,
            proxy=(backend_config.PROXY_URL if backend_config.PROXY_ENABLED else None),
        )
        backend_config.httpx_client = test_httpx_client
        try:
            print("PHASE proactive start", flush=True)
            proactive_result = await scheduled_followup._generate_followup_via_normal_pipeline(
                {
                    "id": f"manual_proactive_{uuid.uuid4().hex[:12]}",
                    "username": username,
                    "character_id": character_id,
                    "conversation_id": conversation_id,
                    "source_message_id": source_message_id,
                    "seed": "延续当前轻松氛围，从角色当下的感受、理解或未来设想自然续接。",
                    "reason": "manual_pinkie_fact_grounding",
                    "chain_count": 0,
                    "allow_reschedule_after_send": 0,
                },
                messages,
            )
            print("PHASE proactive complete", flush=True)
        finally:
            scheduled_followup.load_proactive_settings = original_settings_loader
            backend_config.httpx_client = original_httpx_client
            await test_httpx_client.aclose()
        proactive_reply = str(proactive_result.get("message") or "").strip()
        if not proactive_result.get("should_send") or not proactive_reply:
            raise AssertionError(
                "real proactive pipeline did not send: "
                f"reason={proactive_result.get('reason') or 'unknown'}"
            )

        print(f"BASELINE_MAIN_REPLY:\n{messages[-1]['content']}")
        print(f"PROACTIVE_REPLY:\n{proactive_reply}")
        unsupported_facts = (
            "我偷偷存",
            "我收藏",
            "我手机里",
            "喝醉",
            "发到群里",
            "发在群里",
            "被到处传",
            "私下其实",
            "上次",
            "第一次见",
            "头一回见",
            "曾经",
            "有一次",
            "昨天在",
            "今天我试做",
            "今天早上试做",
        )
        proactive_hits = [term for term in unsupported_facts if term in proactive_reply]
        if proactive_hits:
            raise AssertionError(
                "reply invented media ownership, origin, propagation, or third-party history: "
                f"proactive_hits={proactive_hits}, proactive={proactive_reply}"
            )
        return 0
    finally:
        print("PHASE cleanup start", flush=True)
        _delete_isolated_records(character_id, conversation_id)
        print("PHASE cleanup complete", flush=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
