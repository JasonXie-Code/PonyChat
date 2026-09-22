#!/usr/bin/env python3
"""Replay a Pinkie memory probe with a conflicting recent assistant answer."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Backend.db import get_database, get_users_dao
from Backend.routes.auth import _auth_token_create
from Backend.tests.manual_pinkie_causal_answer import (
    _delete_isolated_records,
)


BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
USERNAME = "System"
SOURCE_CHARACTER_ID = "pinkie_pie__u_1"
PRE_PROBE_SNAPSHOT_CUTOFF_MS = 1_782_864_000_000
PRE_PROBE_SNAPSHOT_CUTOFF_TEXT = "2026-07-01 00:00:00"


def _clone_jason_pinkie_with_memories(character_id: str, conversation_id: str) -> None:
    db = get_database()
    with sqlite3.connect(db.db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        source = conn.execute(
            "SELECT * FROM characters WHERE id = ?",
            (SOURCE_CHARACTER_ID,),
        ).fetchone()
        system_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (USERNAME,),
        ).fetchone()
        if source is None or system_user is None:
            raise RuntimeError("Jason Pinkie source or System user is unavailable")
        system_user_id = int(system_user[0])
        columns = {row[1] for row in conn.execute("PRAGMA table_info(characters)")}
        copy_columns = [
            name for name in source.keys() if name in columns and name not in {"id", "user_id"}
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
            (character_id, system_user_id, *values),
        )
        # Test first-generation recall from the completed June event snapshot,
        # without mixing in the later July current scene or wrong answers.
        memory_rows = conn.execute(
            """
            SELECT memory_type, content, source, importance, is_active, layer,
                   period, created_at, last_recalled_at, recall_count
            FROM character_memories
            WHERE character_id = ? AND is_active = 1
              AND COALESCE(layer, 0) = 0
              AND CAST(created_at AS TEXT) < ?
            """,
            (SOURCE_CHARACTER_ID, PRE_PROBE_SNAPSHOT_CUTOFF_TEXT),
        ).fetchall()
        conn.executemany(
            """
            INSERT INTO character_memories (
                user_id, character_id, memory_type, content, source, importance,
                is_active, layer, period, created_at, last_recalled_at, recall_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (system_user_id, character_id, *tuple(row))
                for row in memory_rows
            ],
        )
        context_row = conn.execute(
            """
            SELECT char_memory_json, short_term_memory, long_term_memory,
                   entries_covered_count, lt_covered_count, updated_at
            FROM normal_chat_memory
            WHERE character_id = ?
              AND (short_term_memory LIKE '%尾巴塞%' OR long_term_memory LIKE '%尾巴塞%')
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (SOURCE_CHARACTER_ID,),
        ).fetchone()
        if not memory_rows or context_row is None:
            raise RuntimeError("Jason Pinkie memory evidence is unavailable")
        context_values = list(tuple(context_row))
        try:
            context_entries = json.loads(str(context_values[0] or "[]"))
        except (TypeError, ValueError):
            context_entries = []
        if isinstance(context_entries, list):
            context_values[0] = json.dumps(
                [
                    entry
                    for entry in context_entries
                    if not isinstance(entry, dict)
                    or int(entry.get("at_ms") or 0) < PRE_PROBE_SNAPSHOT_CUTOFF_MS
                ],
                ensure_ascii=False,
            )
        conn.execute(
            """
            INSERT INTO normal_chat_memory (
                username, character_id, conversation_id, char_memory_json,
                short_term_memory, long_term_memory, entries_covered_count,
                lt_covered_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (USERNAME, character_id, conversation_id, *context_values),
        )
        conn.commit()


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
    character_id = f"tmp_pinkie_memory_probe_{uuid.uuid4().hex[:12]}"
    conversation_id = f"manual_pinkie_memory_probe_{uuid.uuid4().hex[:12]}"
    print(f"PHASE clone character={character_id}", flush=True)
    _clone_jason_pinkie_with_memories(character_id, conversation_id)
    try:
        token = await _make_token()
        first_messages = [
            {"role": "user", "content": "我们之前有玩过你后庭吗"},
            {"role": "assistant", "content": "有过呀。"},
            {"role": "user", "content": "上一次是什么样的，你还记得吗"},
        ]
        body = {
            "messages": first_messages,
            "username": USERNAME,
            "character_id": character_id,
            "conversation_id": conversation_id,
            "mode": "normal",
            "stream": False,
            "memory_enabled": True,
        }
        print("PHASE first recall reply start", flush=True)
        async with httpx.AsyncClient(timeout=240.0, verify=False) as client:
            response = await client.post(
                f"{BASE_URL.rstrip('/')}/api/chat",
                json=body,
                headers={
                    "X-Chat-Auth": token,
                    "X-Client-Id": "manual_pinkie_memory_detail_probe",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            first_reply = _visible_reply(response.json())
            print("PHASE first recall reply complete", flush=True)
            print("FIRST_REPLY:\n" + first_reply, flush=True)
            if not first_reply:
                raise AssertionError("live first recall reply was empty")

            followup_body = dict(body)
            followup_body["messages"] = [
                *first_messages,
                {"role": "assistant", "content": first_reply},
                {"role": "user", "content": "那次有用什么玩具吗"},
            ]
            print("PHASE detail followup reply start", flush=True)
            followup_response = await client.post(
                f"{BASE_URL.rstrip('/')}/api/chat",
                json=followup_body,
                headers={
                    "X-Chat-Auth": token,
                    "X-Client-Id": "manual_pinkie_memory_detail_probe",
                    "Accept": "application/json",
                },
            )
            followup_response.raise_for_status()
            detail_reply = _visible_reply(followup_response.json())
        print("PHASE detail followup reply complete", flush=True)
        print("DETAIL_REPLY:\n" + detail_reply, flush=True)
        if not detail_reply:
            raise AssertionError("live detail followup reply was empty")
        required_groups = (("尾巴塞",), ("铃铛", "叮当"))
        contradicted = ("没用玩具", "没有用玩具", "一楼客厅", "客厅沙发")
        for label, reply in (("first", first_reply), ("detail", detail_reply)):
            missing = ["/".join(group) for group in required_groups if not any(term in reply for term in group)]
            if missing:
                raise AssertionError(
                    f"{label} memory answer omitted event evidence: missing={missing}, reply={reply}"
                )
            hits = [term for term in contradicted if term in reply]
            if hits:
                raise AssertionError(
                    f"{label} memory answer repeated unsupported claims: hits={hits}, reply={reply}"
                )
        return 0
    finally:
        print("PHASE cleanup start", flush=True)
        _delete_isolated_records(character_id, conversation_id)
        print("PHASE cleanup complete", flush=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
