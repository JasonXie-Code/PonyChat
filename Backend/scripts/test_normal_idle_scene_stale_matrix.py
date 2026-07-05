#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Server-side smoke test for model-owned long-idle continuity judgement."""
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import re
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
CLIENT_ID = "idle_scene_stale_matrix_bot"
TEST_USER_PREFIX = "codex_idle_scene_"
TARGET_NAME = "碧琪"
OLD_MS = int(time.time() * 1000) - 7 * 3600 * 1000


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


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not str(row["name"]).startswith("sqlite_")
    }


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def character_name(row: sqlite3.Row) -> str:
    try:
        data = json.loads(row["data"] or "{}")
        if isinstance(data, dict) and str(data.get("name") or "").strip():
            return str(data["name"]).strip()
    except Exception:
        pass
    return str(row["name"] or row["id"])


def create_test_user(conn: sqlite3.Connection) -> tuple[str, int]:
    username = TEST_USER_PREFIX + secrets.token_hex(5)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active)
           VALUES (?, ?, 'male', 'dark', 'user', NULL, ?, ?)""",
        (username, secrets.token_urlsafe(18), now, now),
    )
    user_id = int(cur.lastrowid)
    conn.execute(
        """INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at)
           VALUES (?, 'developer', NULL, 'codex_idle_scene_matrix', ?, 'temporary idle scene stale backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "IdleSceneTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证长时间断联后的普通对话场景重开。",
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


def load_system_role(conn: sqlite3.Connection) -> sqlite3.Row:
    rows = conn.execute(
        """
        SELECT c.*
          FROM characters c
          JOIN users u ON u.id = c.user_id
         WHERE u.username = 'System'
           AND COALESCE(c.is_hidden, 0) = 0
         ORDER BY COALESCE(c.is_official_source, 0) DESC, COALESCE(c.sort_order, 0) ASC, c.name ASC
        """
    ).fetchall()
    for row in rows:
        if character_name(row) == TARGET_NAME:
            return row
    raise RuntimeError(f"missing System role: {TARGET_NAME}")


def clone_role(conn: sqlite3.Connection, user_id: int, row: sqlite3.Row) -> dict[str, str]:
    columns = table_columns(conn, "characters")
    insertable = [
        col
        for col in (
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
        if col in columns
    ]
    clone_id = "tmp_idle_scene_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    values: list[Any] = []
    for col in insertable:
        if col == "id":
            values.append(clone_id)
        elif col == "user_id":
            values.append(user_id)
        elif col == "sort_order":
            values.append(0)
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
    conn.execute(
        f"INSERT INTO characters ({', '.join(insertable)}) VALUES ({', '.join('?' for _ in insertable)})",
        values,
    )
    conn.commit()
    return {"id": clone_id, "source_id": str(row["id"]), "name": character_name(row)}


def parse_reply(data: Any) -> str:
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts: list[str] = []
        for ev in data.get("events") or []:
            if not isinstance(ev, dict):
                continue
            for ch in ev.get("choices") or []:
                content = ((ch or {}).get("delta") or {}).get("content") or ""
                if content:
                    parts.append(str(content))
        return "".join(parts).strip()
    if isinstance(data, dict):
        return str(data.get("response") or data.get("text") or data.get("content") or "").strip()
    return str(data).strip()


async def chat(client: httpx.AsyncClient, token: str, username: str, character_id: str, conversation_id: str, messages: list[dict[str, Any]]) -> str:
    resp = await client.post(
        f"{BASE_URL.rstrip()}/api/chat",
        json={
            "username": username,
            "character_id": character_id,
            "conversation_id": conversation_id,
            "mode": "normal",
            "stream": False,
            "memory_enabled": True,
            "messages": messages,
        },
        headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
        timeout=180.0,
    )
    resp.raise_for_status()
    return parse_reply(resp.json())


def rewind_conversation(conn: sqlite3.Connection, conversation_id: str, username: str, character_id: str) -> None:
    if "messages" in table_names(conn):
        if "timestamp" in table_columns(conn, "messages"):
            conn.execute("UPDATE messages SET timestamp=? WHERE conversation_id=?", (OLD_MS, conversation_id))
    if "conversations" in table_names(conn):
        if "timestamp" in table_columns(conn, "conversations"):
            conn.execute("UPDATE conversations SET timestamp=? WHERE id=?", (OLD_MS, conversation_id))
    if "normal_scene_state" in table_names(conn):
        conn.execute(
            "UPDATE normal_scene_state SET updated_ms=? WHERE username=? AND character_id=?",
            (OLD_MS, username, character_id),
        )
    conn.commit()


def latest_scene_cards(conn: sqlite3.Connection, username: str, character_id: str) -> list[str]:
    if "normal_scene_state" not in table_names(conn):
        return []
    rows = conn.execute(
        """SELECT scene_card
             FROM normal_scene_state
            WHERE username=? AND character_id=?
            ORDER BY updated_ms DESC""",
        (username, character_id),
    ).fetchall()
    return [str(row["scene_card"] or "") for row in rows]


def cleanup(conn: sqlite3.Connection, username: str, user_id: int, clone_id: str, conversation_ids: list[str]) -> dict[str, int]:
    names = table_names(conn)
    clone_ids = [clone_id] if clone_id else []
    important = (
        "messages",
        "memberships",
        "daily_chat_usage",
        "daily_token_usage",
        "normal_chat_memory",
        "normal_emotion_state",
        "normal_scene_state",
        "normal_image_contexts",
        "normal_image_context_state",
        "proactive_tasks",
        "proactive_messages",
        "proactive_campaigns",
        "proactive_touch_attempts",
        "message_outbox",
        "character_memories",
        "user_settings",
    )
    for table in important:
        if table not in names:
            continue
        cols = table_columns(conn, table)
        if "conversation_id" in cols and conversation_ids:
            conn.execute(
                f"DELETE FROM {table} WHERE conversation_id IN ({','.join('?' for _ in conversation_ids)})",
                conversation_ids,
            )
        if "character_id" in cols and clone_ids:
            conn.execute(f"DELETE FROM {table} WHERE character_id IN ({','.join('?' for _ in clone_ids)})", clone_ids)
        if "username" in cols:
            conn.execute(f"DELETE FROM {table} WHERE username=?", (username,))
        if "user_id" in cols:
            conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
    if "messages" in names and conversation_ids:
        conn.execute(f"DELETE FROM messages WHERE conversation_id IN ({','.join('?' for _ in conversation_ids)})", conversation_ids)
    if "conversations" in names:
        if conversation_ids:
            conn.execute(f"DELETE FROM conversations WHERE id IN ({','.join('?' for _ in conversation_ids)})", conversation_ids)
        conn.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))
    if "characters" in names and clone_ids:
        conn.execute(f"DELETE FROM characters WHERE id IN ({','.join('?' for _ in clone_ids)})", clone_ids)
    if "users" in names:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    checks: dict[str, int] = {}
    if "users" in names:
        checks["left_user"] = int(conn.execute("SELECT COUNT(*) AS n FROM users WHERE username=?", (username,)).fetchone()["n"])
    if "characters" in names and clone_ids:
        checks["left_chars"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM characters WHERE id IN ({','.join('?' for _ in clone_ids)})", clone_ids).fetchone()["n"])
    if "conversations" in names and conversation_ids:
        checks["left_conversations"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM conversations WHERE id IN ({','.join('?' for _ in conversation_ids)})", conversation_ids).fetchone()["n"])
    return checks


async def main() -> int:
    conn = connect_db()
    username = ""
    user_id = 0
    clone: dict[str, str] = {}
    conversation_ids: list[str] = []
    try:
        username, user_id = create_test_user(conn)
        clone = clone_role(conn, user_id, load_system_role(conn))
        token = make_token(username)
        conv_id = "idle_scene_" + uuid.uuid4().hex
        conversation_ids.append(conv_id)
        print(json.dumps({"username": username, "user_id": user_id, "clone": clone, "conversation_id": conv_id}, ensure_ascii=False))
        old_user = {
            "role": "user",
            "content": "（我们坐在方糖屋一楼客厅沙发上，杯子蛋糕在茶几上，你把尾巴搭在我腿边。）",
            "message_id": "u_old_" + uuid.uuid4().hex,
            "timestamp": OLD_MS,
        }
        async with httpx.AsyncClient() as client:
            first_reply = await chat(client, token, username, clone["id"], conv_id, [old_user])
            rewind_conversation(conn, conv_id, username, clone["id"])
            history = [
                old_user,
                {
                    "role": "assistant",
                    "content": first_reply or "（我坐在方糖屋一楼客厅沙发上，把尾巴搭在你腿边。）",
                    "speaker_character_id": clone["id"],
                    "speaker_name": clone["name"],
                    "message_id": "a_old_" + uuid.uuid4().hex,
                    "timestamp": OLD_MS,
                },
                {
                    "role": "user",
                    "content": "下午好，你在做什么呢",
                    "message_id": "u_new_" + uuid.uuid4().hex,
                    "timestamp": int(time.time() * 1000),
                },
            ]
            second_reply = await chat(client, token, username, clone["id"], conv_id, history)
        cards = latest_scene_cards(conn, username, clone["id"])
        joined_cards = "\n".join(cards)
        reopen_markers = ["状态: stale", "background_only", "只作历史背景", "自然重开", "不强制继承"]
        old_physical_terms = ["尾巴搭", "腿边", "一楼客厅沙发", "沙发上", "茶几"]
        current_old_physical_patterns = [
            "尾巴搭在你腿边",
            "尾巴搭在我腿边",
            "尾巴.{0,12}腿边",
            "尾巴.*扫过你的腿边",
            "仍在.{0,12}沙发",
            "还在.{0,12}沙发",
            "继续.{0,12}沙发",
            "茶几上.{0,8}杯子蛋糕",
        ]
        reply_bad = [
            pattern
            for pattern in current_old_physical_patterns
            if re.search(pattern, second_reply)
        ]
        card_old_terms = [term for term in old_physical_terms if term in joined_cards]
        card_has_reopen_marker = any(term in joined_cards for term in reopen_markers)
        result = {
            "first_reply_preview": first_reply[:500],
            "second_reply": second_reply,
            "scene_cards": cards[:3],
            "reply_current_old_physical_patterns": reply_bad,
            "card_old_terms_observed_as_history": card_old_terms,
            "card_has_model_reopen_marker": card_has_reopen_marker,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if reply_bad or not card_has_reopen_marker:
            print(json.dumps({"status": "FAIL", **result}, ensure_ascii=False))
            return 2
        print(json.dumps({"status": "PASS", "username": username}, ensure_ascii=False))
        return 0
    finally:
        try:
            cleanup_result = cleanup(connect_db(), username, user_id, clone.get("id", ""), conversation_ids) if username and user_id else {}
            print("\n=== CLEANUP ===")
            print(json.dumps(cleanup_result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
