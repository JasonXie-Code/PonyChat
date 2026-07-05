#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import secrets
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
CLIENT_ID = "speaker_router_backend_bot"
TARGET_NAMES = ["柔柔", "碧琪", "紫悦"]


def _load_env_secret() -> str:
    if os.getenv("AUTH_SECRET"):
        return str(os.getenv("AUTH_SECRET"))
    env_path = Path("/opt/ponychat/.env")
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "AUTH_SECRET":
                return value.strip().strip("'\"")
    return "ponychat_default_secret_change_in_production"


def make_token(username: str) -> str:
    exp = int(time.time()) + 6 * 3600
    payload = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(_load_env_secret().encode(), payload_b64.encode(), "sha256").digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def connect_db() -> sqlite3.Connection:
    from Backend.db import get_database

    conn = sqlite3.connect(str(get_database().db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def create_test_user(conn: sqlite3.Connection) -> tuple[str, int, str]:
    username = "codex_speaker_router_" + secrets.token_hex(5)
    password = "CodexTest#" + secrets.token_hex(4)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active)
           VALUES (?, ?, 'male', 'dark', 'user', NULL, ?, ?)""",
        (username, password, now, now),
    )
    user_id = int(cur.lastrowid)
    conn.execute(
        """INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at)
           VALUES (?, 'developer', NULL, 'codex_speaker_router_backend', ?, 'temporary backend speaker router test', ?, ?)""",
        (user_id, now, now, now),
    )
    settings = {
        "nickname": "CodexSpeakerRouterTester",
        "species_preset": "人类",
        "share_with_ai": True,
        "bio": "临时自动化测试用户。",
    }
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (user_id, json.dumps(settings, ensure_ascii=False)),
    )
    conn.commit()
    return username, user_id, password


def load_system_roles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in TARGET_NAMES)
    return conn.execute(
        f"""
        SELECT c.*
          FROM characters c
          JOIN users u ON u.id = c.user_id
         WHERE u.username = 'System'
           AND c.name IN ({placeholders})
           AND COALESCE(c.is_hidden, 0) = 0
         ORDER BY c.name
        """,
        TARGET_NAMES,
    ).fetchall()


def clone_roles(conn: sqlite3.Connection, user_id: int, rows: list[sqlite3.Row]) -> dict[str, dict[str, str]]:
    columns = table_columns(conn, "characters")
    insertable = [
        c
        for c in (
            "id",
            "user_id",
            "name",
            "avatar",
            "prompt",
            "bio",
            "data",
            "sort_order",
            "memory_identity_profile",
            "official_source_id",
            "is_official_reference",
            "is_official_source",
            "official_content_hash_at_link",
            "is_hidden",
            "hidden_at",
            "hidden_reason",
            "created_at",
            "updated_at",
        )
        if c in columns
    ]
    sql = f"INSERT INTO characters ({', '.join(insertable)}) VALUES ({', '.join('?' for _ in insertable)})"
    clones: dict[str, dict[str, str]] = {}
    now = datetime.now(timezone.utc).isoformat()
    for idx, row in enumerate(rows):
        clone_id = "tmp_router_" + uuid.uuid4().hex
        values: list[Any] = []
        for col in insertable:
            if col == "id":
                values.append(clone_id)
            elif col == "user_id":
                values.append(user_id)
            elif col == "sort_order":
                values.append(idx)
            elif col == "official_source_id":
                values.append(str(row["id"]))
            elif col in {"is_official_reference", "is_official_source"}:
                values.append(0)
            elif col == "is_hidden":
                values.append(0)
            elif col in {"hidden_at", "hidden_reason"}:
                values.append(None)
            elif col in {"created_at", "updated_at"}:
                values.append(now)
            else:
                values.append(row[col] if col in row.keys() else None)
        conn.execute(sql, values)
        clones[str(row["name"])] = {"id": clone_id, "source_id": str(row["id"]), "name": str(row["name"])}
    conn.commit()
    return clones


def event_text_and_speakers(data: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    parts: list[str] = []
    speakers: list[dict[str, str]] = []
    for ev in data.get("events") or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") in {"message", "assistant_message", "normal_message"}:
            speakers.append(
                {
                    "type": str(ev.get("type") or ""),
                    "speaker_name": str(ev.get("speaker_name") or ev.get("speakerName") or ""),
                    "speaker_character_id": str(ev.get("speaker_character_id") or ev.get("speakerCharacterId") or ""),
                    "multi_reply_character_id": str(ev.get("multi_reply_character_id") or ""),
                }
            )
        for ch in ev.get("choices") or []:
            delta = ch.get("delta") or {}
            content = delta.get("content") or ""
            if content:
                parts.append(str(content))
    return "".join(parts).strip(), speakers


async def chat(client: httpx.AsyncClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    resp = await client.post(
        f"{BASE_URL.rstrip()}/api/chat",
        json=body,
        headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
        timeout=180.0,
    )
    resp.raise_for_status()
    return resp.json()


async def main() -> int:
    conn = connect_db()
    username, user_id, password = create_test_user(conn)
    rows = load_system_roles(conn)
    if {str(r["name"]) for r in rows} != set(TARGET_NAMES):
        raise RuntimeError(f"missing target roles: got {[str(r['name']) for r in rows]}")
    clones = clone_roles(conn, user_id, rows)
    token = make_token(username)
    main_id = clones["柔柔"]["id"]
    pinkie_id = clones["碧琪"]["id"]
    twilight_id = clones["紫悦"]["id"]
    conv_id = "router_backend_" + uuid.uuid4().hex
    group_conv_id = "router_backend_group_" + uuid.uuid4().hex
    print(
        json.dumps(
            {
                "username": username,
                "password": password,
                "user_id": user_id,
                "clones": clones,
                "conversation_id": conv_id,
                "group_conversation_id": group_conv_id,
            },
            ensure_ascii=False,
        )
    )

    async with httpx.AsyncClient() as client:
        def build_history(latest_user: str, *, pinkie_name: str = "碧琪") -> list[dict[str, Any]]:
            return [
                {"role": "user", "content": "紫悦和碧琪先听着，柔柔介绍一下这本书。"},
                {
                    "role": "assistant",
                    "content": "嗯……这本书讲的是森林里的小动物怎么互相帮助，我觉得特别温暖。",
                    "speaker_character_id": main_id,
                    "speaker_name": "柔柔",
                },
                {"role": "user", "content": "@碧琪 @紫悦 你们两个都说一句，这本书哪里最值得看。"},
                {
                    "role": "assistant",
                    "content": "哇！我最喜欢小兔子帮小松鼠收集坚果那段，超级温暖又可爱！",
                    "speaker_character_id": pinkie_id,
                    "speaker_name": pinkie_name,
                },
                {
                    "role": "assistant",
                    "content": "我觉得那段展示了友谊可以跨越物种自然发生，跟小马谷的经历很像。",
                    "speaker_character_id": twilight_id,
                    "speaker_name": "紫悦",
                },
                {"role": "user", "content": latest_user},
            ]

        history_assistant_contents = {
            "嗯……这本书讲的是森林里的小动物怎么互相帮助，我觉得特别温暖。",
            "哇！我最喜欢小兔子帮小松鼠收集坚果那段，超级温暖又可爱！",
            "我觉得那段展示了友谊可以跨越物种自然发生，跟小马谷的经历很像。",
        }

        def max_message_rowid() -> int:
            row = conn.execute("SELECT COALESCE(MAX(rowid), 0) AS n FROM messages").fetchone()
            return int(row["n"] or 0)

        def assistant_rows_after(rowid: int) -> list[dict[str, Any]]:
            rows = conn.execute(
                """SELECT m.rowid, m.conversation_id, m.role, substr(m.content,1,160) AS content,
                          COALESCE(m.speaker_character_id,'') AS speaker_character_id,
                          COALESCE(m.speaker_name,'') AS speaker_name, COALESCE(m.is_hidden,0) AS is_hidden
                     FROM messages m
                     JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.user_id = ?
                      AND c.character_id = ?
                      AND m.rowid > ?
                      AND m.role = 'assistant'
                    ORDER BY m.rowid""",
                (user_id, main_id, rowid),
            ).fetchall()
            return [dict(r) for r in rows]

        def selected_speaker_ids(rows: list[dict[str, Any]]) -> list[str]:
            selected: list[str] = []
            for row in rows:
                speaker_id = str(row.get("speaker_character_id") or "")
                if speaker_id:
                    selected.append(speaker_id)
                    continue
                content = str(row.get("content") or "")
                if content and content not in history_assistant_contents:
                    selected.append(main_id)
            return selected

        cases = [
            {
                "key": "prefix_colon",
                "message": "碧琪：评价我和柔柔的观点。",
                "expect": [pinkie_id],
            },
            {
                "key": "suffix_name",
                "message": "你来说说你的看法吧碧琪。",
                "expect": [pinkie_id],
            },
            {
                "key": "prefix_no_punct",
                "message": "紫悦你觉得那本书怎么样。",
                "expect": [twilight_id],
            },
            {
                "key": "partial_name",
                "message": "玉琪，你来说说你的看法。",
                "expect": [pinkie_id],
                "pinkie_name": "玉琪派",
            },
            {
                "key": "opinion_about_named_role",
                "message": "你觉得玉琪喜欢我吗。",
                "expect": [main_id],
                "pinkie_name": "玉琪派",
                "allow_extra": False,
            },
            {
                "key": "group_all_recent",
                "message": "我让你们都过来看看这个书，分别评价一下我和柔柔的观点。",
                "expect": [main_id, pinkie_id, twilight_id],
                "allow_extra": False,
            },
            {
                "key": "group_state_single",
                "message": "你们几个姐妹平时都是分开睡的吧。",
                "expect_any_one_of": [main_id, pinkie_id, twilight_id],
                "expect_count": 1,
                "allow_extra": False,
            },
        ]

        for idx, case in enumerate(cases, start=1):
            before = max_message_rowid()
            conv = f"router_backend_{case['key']}_{uuid.uuid4().hex}"
            data = await chat(
                client,
                token,
                {
                    "username": username,
                    "character_id": main_id,
                    "conversation_id": conv,
                    "mode": "normal",
                    "stream": False,
                    "memory_enabled": True,
                    "messages": build_history(case["message"], pinkie_name=str(case.get("pinkie_name") or "碧琪")),
                },
            )
            text, response_speakers = event_text_and_speakers(data)
            conn.commit()
            assistants = assistant_rows_after(before)
            selected_ids = selected_speaker_ids(assistants)
            print(
                json.dumps(
                    {
                        "step": case["key"],
                        "message": case["message"],
                        "text": text,
                        "response_speakers": response_speakers,
                        "assistant_speakers": assistants,
                        "selected_ids": selected_ids,
                    },
                    ensure_ascii=False,
                )
            )
            if "expect_any_one_of" in case:
                allowed = list(case["expect_any_one_of"])
                expected_count = int(case.get("expect_count") or 1)
                missing = []
                extra = [cid for cid in selected_ids if cid not in allowed]
                wrong_count = len(selected_ids) != expected_count
                bad_selection = not selected_ids or not all(cid in allowed for cid in selected_ids)
                failed = wrong_count or bad_selection or (extra and not case.get("allow_extra", False))
                expected_for_log = allowed
            else:
                expected = list(case["expect"])
                missing = [cid for cid in expected if cid not in selected_ids]
                extra = [cid for cid in selected_ids if cid not in expected]
                failed = bool(missing or (extra and not case.get("allow_extra", False)))
                expected_for_log = expected
            if failed:
                print(
                    json.dumps(
                        {
                            "status": "FAIL",
                            "case": case["key"],
                            "expected_ids": expected_for_log,
                            "expected_count": case.get("expect_count"),
                            "selected_ids": selected_ids,
                            "missing": missing,
                            "extra": extra,
                            "assistant_speakers": assistants,
                        },
                        ensure_ascii=False,
                    )
                )
                return 10 + idx
    print(json.dumps({"status": "PASS", "username": username}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
