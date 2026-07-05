#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Server-side reset/opening greeting acceptance test.

Run on the backend server after deployment:
  /opt/ponychat/.venv/bin/python scripts/test_reset_opening_greeting_backend.py
"""
from __future__ import annotations

import asyncio
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

from Backend.db import get_database  # noqa: E402


BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
CLIENT_ID = "codex_reset_opening_greeting"
TEST_USER_PREFIX = "codex_reset_opening_"
TARGET_NAMES = ("紫悦", "碧琪", "柔柔")
TARGET_ALIASES = {
    "紫悦": ("紫悦", "暮光", "Twilight"),
    "碧琪": ("碧琪", "萍琪", "Pinkie"),
    "柔柔": ("柔柔", "Fluttershy"),
}
KNOWN_FALLBACK_PREFIXES = {
    "紫悦": ["很高兴认识你！"],
    "碧琪": ["很高兴认识你！"],
}


def connect() -> sqlite3.Connection:
    db = get_database()
    conn = sqlite3.connect(str(db.db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(r["name"])
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not str(r["name"]).startswith("sqlite_")
    }


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})")}


def character_name(row: sqlite3.Row) -> str:
    try:
        data = json.loads(row["data"] or "{}")
        if isinstance(data, dict) and str(data.get("name") or "").strip():
            return str(data["name"]).strip()
    except Exception:
        pass
    return str(row["name"] or row["id"])


def create_test_user(conn: sqlite3.Connection) -> tuple[str, int]:
    username = TEST_USER_PREFIX + secrets.token_hex(6)
    now = utc_now()
    cur = conn.execute(
        """INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active)
           VALUES (?, ?, 'male', 'dark', 'user', NULL, ?, ?)""",
        (username, secrets.token_urlsafe(18), now, now),
    )
    user_id = int(cur.lastrowid)
    conn.execute(
        """INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at)
           VALUES (?, 'developer', NULL, 'codex_reset_opening_greeting', ?, 'temporary reset opening test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "ResetOpeningTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证角色重置后的后台首条消息。",
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


def load_target_system_characters(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = list(
        conn.execute(
            """
            SELECT c.*
              FROM characters c
              JOIN users u ON u.id = c.user_id
             WHERE u.username = 'System'
               AND COALESCE(c.is_hidden, 0) = 0
             ORDER BY COALESCE(c.is_official_source, 0) DESC, COALESCE(c.sort_order, 0) ASC, c.name ASC
            """
        ).fetchall()
    )
    selected: dict[str, sqlite3.Row] = {}
    for row in rows:
        name = character_name(row)
        blob = f"{name}\n{row['name'] if 'name' in row.keys() else ''}"
        for target in TARGET_NAMES:
            if target in selected:
                continue
            aliases = TARGET_ALIASES[target]
            if any(alias.lower() in blob.lower() for alias in aliases):
                selected[target] = row
    missing = [name for name in TARGET_NAMES if name not in selected]
    if missing:
        raise RuntimeError(f"missing System roles: {missing}")
    return [selected[name] for name in TARGET_NAMES]


def clone_characters(conn: sqlite3.Connection, user_id: int, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
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
    now = utc_now()
    clones: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        clone_id = "tmp_reset_opening_" + uuid.uuid4().hex
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
            elif col in {"is_official_reference", "is_official_source", "is_hidden"}:
                values.append(0)
            elif col in {"hidden_at", "hidden_reason"}:
                values.append(None)
            elif col in {"created_at", "updated_at"}:
                values.append(now)
            else:
                values.append(row[col] if col in row.keys() else None)
        conn.execute(sql, values)
        clones.append({"id": clone_id, "source_id": str(row["id"]), "name": character_name(row)})
    conn.commit()
    return clones


async def wait_health(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get(f"{BASE_URL}/api/health", timeout=10.0)
    return {"http": resp.status_code, "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:300]}


async def reset_chat(client: httpx.AsyncClient, username: str, character_id: str) -> dict[str, Any]:
    payload = {"username": username, "character_id": character_id}
    started = time.perf_counter()
    resp = await client.post(
        f"{BASE_URL}/api/character/reset_chat",
        json=payload,
        headers={"X-Client-Id": CLIENT_ID, "Accept": "application/json"},
        timeout=20.0,
    )
    elapsed = time.perf_counter() - started
    body: Any
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:500]
    return {
        "raw_user_question": f"POST /api/character/reset_chat {json.dumps(payload, ensure_ascii=False)}",
        "http": resp.status_code,
        "elapsed_seconds": round(elapsed, 3),
        "body": body,
    }


def visible_opening_messages(conn: sqlite3.Connection, user_id: int, character_id: str) -> tuple[str | None, list[str]]:
    rows = list(
        conn.execute(
            """
            SELECT c.id AS conversation_id, m.content AS content
              FROM conversations c
              LEFT JOIN messages m
                     ON m.conversation_id = c.id
                    AND m.deleted_at IS NULL
                    AND COALESCE(m.is_hidden, 0) = 0
             WHERE c.user_id = ?
               AND c.character_id = ?
               AND COALESCE(c.is_hidden, 0) = 0
             ORDER BY c.timestamp DESC, m.timestamp ASC, m.sequence_number ASC
            """,
            (user_id, character_id),
        ).fetchall()
    )
    conversation_id = None
    messages: list[str] = []
    for row in rows:
        conversation_id = conversation_id or (str(row["conversation_id"]) if row["conversation_id"] else None)
        content = str(row["content"] or "").strip()
        if content:
            messages.append(content)
    return conversation_id, messages


def chat_complete_outbox_events(conn: sqlite3.Connection, user_id: int, character_id: str) -> list[dict[str, Any]]:
    if "message_outbox" not in table_names(conn):
        return []

    rows = list(
        conn.execute(
            """
            SELECT id, msg_type, payload_json, created_at, delivered_at
              FROM message_outbox
             WHERE user_id = ?
               AND msg_type = 'chat_complete'
             ORDER BY created_at ASC
            """,
            (user_id,),
        ).fetchall()
    )
    events: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        if str(payload.get("character_id") or "") != str(character_id):
            continue
        events.append(
            {
                "outbox_id": str(row["id"]),
                "msg_type": str(row["msg_type"]),
                "payload": payload,
                "created_at": row["created_at"],
                "delivered_at": row["delivered_at"],
            }
        )
    return events


async def poll_opening_messages(
    conn: sqlite3.Connection,
    user_id: int,
    char: dict[str, Any],
    *,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    conversation_id: str | None = None
    messages: list[str] = []
    while time.monotonic() < deadline:
        conversation_id, messages = visible_opening_messages(conn, user_id, char["id"])
        if messages:
            break
        await asyncio.sleep(2.0)
    return {
        "conversation_id": conversation_id,
        "raw_character_reply": messages,
        "poll_elapsed_seconds": round(timeout_seconds - max(0.0, deadline - time.monotonic()), 3),
    }


async def poll_chat_complete_outbox(
    conn: sqlite3.Connection,
    user_id: int,
    char: dict[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    events: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        events = chat_complete_outbox_events(conn, user_id, char["id"])
        if events:
            break
        await asyncio.sleep(0.5)
    return {
        "events": events,
        "poll_elapsed_seconds": round(timeout_seconds - max(0.0, deadline - time.monotonic()), 3),
    }


def evaluate_result(
    char: dict[str, Any],
    reset: dict[str, Any],
    opening: dict[str, Any],
    outbox: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    name = str(char["name"])
    messages = [str(x).strip() for x in opening.get("raw_character_reply") or [] if str(x).strip()]
    outbox_events = list(outbox.get("events") or [])
    checks: list[dict[str, Any]] = []

    def add(key: str, ok: bool, detail: Any) -> None:
        checks.append({"check": key, "ok": bool(ok), "detail": detail})

    body = reset.get("body") if isinstance(reset.get("body"), dict) else {}
    add("reset_http_200", reset.get("http") == 200, reset.get("http"))
    add("reset_under_1s", float(reset.get("elapsed_seconds") or 999) < 1.0, reset.get("elapsed_seconds"))
    add("opening_scheduled", bool((body.get("opening_greeting") or {}).get("scheduled")), body.get("opening_greeting"))

    if messages:
        prefix = KNOWN_FALLBACK_PREFIXES.get(name) or ["很高兴认识你！"]
        add("opening_not_exact_fallback", messages[: len(prefix)] != prefix, messages)
        add("chat_complete_outbox_created", bool(outbox_events), outbox_events)
        add(
            "chat_complete_event_count_matches_bubbles",
            len(outbox_events) == len(messages),
            {"event_count": len(outbox_events), "bubble_count": len(messages), "events": outbox_events},
        )
        if outbox_events:
            per_event_counts = [
                int((event.get("payload") or {}).get("bubble_count") or 0)
                for event in outbox_events
            ]
            add("each_chat_complete_represents_one_bubble", per_event_counts == [1] * len(outbox_events), per_event_counts)
    else:
        add("opening_optional_by_step0", True, "第0步允许根据角色档案判断不主动发首条；本角色本轮未产生 opening。")

    failures = [{"character": name, **check} for check in checks if not check["ok"]]
    return checks, failures


def cleanup(conn: sqlite3.Connection, username: str, user_id: int, clone_ids: list[str], conversation_ids: list[str]) -> dict[str, int]:
    conn.execute("PRAGMA foreign_keys=OFF")
    names = table_names(conn)
    for table in sorted(names):
        columns = table_columns(conn, table)
        try:
            if "username" in columns:
                conn.execute(f"DELETE FROM {table} WHERE username=?", (username,))
            if "user_id" in columns:
                conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            if conversation_ids and "conversation_id" in columns:
                conn.executemany(f"DELETE FROM {table} WHERE conversation_id=?", [(cid,) for cid in conversation_ids])
            if conversation_ids and table == "conversations" and "id" in columns:
                conn.executemany("DELETE FROM conversations WHERE id=?", [(cid,) for cid in conversation_ids])
            if clone_ids and "character_id" in columns:
                conn.executemany(f"DELETE FROM {table} WHERE character_id=?", [(cid,) for cid in clone_ids])
            if clone_ids and table == "characters" and "id" in columns:
                conn.executemany("DELETE FROM characters WHERE id=?", [(cid,) for cid in clone_ids])
        except Exception as exc:
            print(f"CLEANUP_WARN {table}: {exc}", flush=True)
    conn.commit()

    checks: dict[str, int] = {
        "left_user": int(conn.execute("SELECT COUNT(*) AS n FROM users WHERE username=?", (username,)).fetchone()["n"]) if "users" in names else 0,
        "left_chars": 0,
        "left_conversations": 0,
        "left_messages": 0,
        "left_normal_chat_memory": 0,
        "left_character_memories": 0,
    }
    if clone_ids and "characters" in names:
        checks["left_chars"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM characters WHERE id IN ({','.join('?' for _ in clone_ids)})", clone_ids).fetchone()["n"])
    if conversation_ids and "conversations" in names:
        checks["left_conversations"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM conversations WHERE id IN ({','.join('?' for _ in conversation_ids)})", conversation_ids).fetchone()["n"])
    if conversation_ids and "messages" in names:
        checks["left_messages"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM messages WHERE conversation_id IN ({','.join('?' for _ in conversation_ids)})", conversation_ids).fetchone()["n"])
    if "normal_chat_memory" in names:
        checks["left_normal_chat_memory"] = int(conn.execute("SELECT COUNT(*) AS n FROM normal_chat_memory WHERE username=?", (username,)).fetchone()["n"])
    if clone_ids and "character_memories" in names:
        checks["left_character_memories"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM character_memories WHERE character_id IN ({','.join('?' for _ in clone_ids)})", clone_ids).fetchone()["n"])
    return checks


async def main() -> int:
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    cleanup_result: dict[str, int] = {}
    conversation_ids: list[str] = []
    health: dict[str, Any] = {}
    try:
        username, user_id = create_test_user(conn)
        rows = load_target_system_characters(conn)
        clones = clone_characters(conn, user_id, rows)
        print(f"TEST_USER {username} user_id={user_id} membership=developer", flush=True)
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False), flush=True)

        async with httpx.AsyncClient() as client:
            health = await wait_health(client)

            async def one(char: dict[str, Any]) -> dict[str, Any]:
                reset = await reset_chat(client, username, char["id"])
                timeout = 120.0 if str(char["name"]) in KNOWN_FALLBACK_PREFIXES else 55.0
                opening = await poll_opening_messages(conn, user_id, char, timeout_seconds=timeout)
                outbox = {"events": [], "poll_elapsed_seconds": 0.0}
                if opening.get("raw_character_reply"):
                    outbox = await poll_chat_complete_outbox(conn, user_id, char, timeout_seconds=15.0)
                checks, item_failures = evaluate_result(char, reset, opening, outbox)
                failures.extend(item_failures)
                if opening.get("conversation_id"):
                    conversation_ids.append(str(opening["conversation_id"]))
                return {
                    "character": char["name"],
                    "clone_id": char["id"],
                    "source_id": char["source_id"],
                    "reset": reset,
                    "opening": opening,
                    "outbox": outbox,
                    "checks": checks,
                }

            results = await asyncio.gather(*(one(char) for char in clones))
            if not any((item.get("opening") or {}).get("raw_character_reply") for item in results):
                failures.append(
                    {
                        "check": "at_least_one_opening_generated",
                        "ok": False,
                        "detail": "本轮 3 个角色 Step0 都未生成 opening，未覆盖首条消息生成链路。",
                    }
                )
    except Exception as exc:
        failures.append({"error": type(exc).__name__, "detail": str(exc)})
    finally:
        try:
            cleanup_result = cleanup(
                conn,
                username,
                user_id,
                [c["id"] for c in clones],
                sorted(set(conversation_ids)),
            ) if username and user_id else {}
        finally:
            conn.close()

    if cleanup_result and any(value != 0 for value in cleanup_result.values()):
        failures.append({"error": "cleanup_not_zero", "detail": cleanup_result})

    report = {
        "problem": "重置角色后首条消息生成不得阻塞 reset；后台 opening 不应落到兜底文案。",
        "fix_points": [
            "reset_character_chat schedules opening greeting in background and returns immediately",
            "opening greeting JSON uses current bubbles[*].parts schema with legacy content compatibility",
            "opening greeting persistence enqueues one chat_complete outbox event per visible bubble",
        ],
        "expected_invariants": [
            "reset endpoint elapsed < 1s for each cloned role",
            "opening_greeting.scheduled=true in reset response",
            "第0步可自行判断是否首发；若生成 opening，则不能是精确兜底前缀",
            "若生成 opening，message_outbox 对应 chat_complete 条数必须与气泡数严格一致，且每条事件只代表 1 个气泡",
            "3 个默认角色中至少一个生成 opening，用于覆盖后台生成链路",
            "cleanup required counters all zero",
        ],
        "health": health,
        "test_user": username,
        "cloned_roles": {c["name"]: c["id"] for c in clones},
        "results": results,
        "failures": failures,
        "cleanup": cleanup_result,
    }
    print("=== RESET_OPENING_REPORT_JSON ===", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
