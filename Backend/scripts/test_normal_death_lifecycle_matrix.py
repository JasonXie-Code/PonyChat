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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
CLIENT_ID = "codex_death_lifecycle_matrix"
TEST_USER_PREFIX = "codex_death_lifecycle_"
CONCURRENCY = int(os.getenv("PONYCHAT_DEATH_TEST_CONCURRENCY", "8") or "8")
ROLE_LIMIT = int(os.getenv("PONYCHAT_DEATH_TEST_LIMIT", "0") or "0")


def _load_secret() -> str:
    if os.getenv("AUTH_SECRET"):
        return str(os.getenv("AUTH_SECRET"))
    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "AUTH_SECRET":
                return value.strip().strip("'\"")
    return "ponychat_default_secret_change_in_production"


AUTH_SECRET = _load_secret()


def make_token(username: str) -> str:
    exp = int(time.time()) + 6 * 3600
    payload = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), "sha256").digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def db_path() -> Path:
    from Backend.db import get_database

    return Path(get_database().db_path)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(r["name"])
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not str(r["name"]).startswith("sqlite_")
    }


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})")}


def create_test_user(conn: sqlite3.Connection) -> tuple[str, int]:
    username = TEST_USER_PREFIX + secrets.token_hex(6)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active)
           VALUES (?, ?, 'male', 'dark', 'user', NULL, ?, ?)""",
        (username, secrets.token_urlsafe(18), now, now),
    )
    user_id = int(cur.lastrowid)
    conn.execute(
        """INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at)
           VALUES (?, 'developer', NULL, 'codex_death_lifecycle_matrix', ?, 'temporary death lifecycle backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "DeathLifecycleTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户。",
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


def load_system_characters(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
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


def character_name(row: sqlite3.Row) -> str:
    try:
        data = json.loads(row["data"] or "{}")
        if isinstance(data, dict) and str(data.get("name") or "").strip():
            return str(data["name"]).strip()
    except Exception:
        pass
    return str(row["name"] or row["id"])


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
    now = datetime.now(timezone.utc).isoformat()
    clones: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        clone_id = "tmp_death_" + uuid.uuid4().hex
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


def parse_reply(data: Any) -> tuple[str, bool, str]:
    no_reply = False
    reason = ""
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts: list[str] = []
        for ev in data.get("events") or []:
            if isinstance(ev, dict) and ev.get("type") == "no_reply":
                no_reply = True
                reason = str(ev.get("reason") or "")
            if isinstance(ev, dict) and ev.get("type") in {"assistant_paragraph", "assistant_message"}:
                content = str(ev.get("content") or "")
                if content:
                    parts.append(content)
            for ch in (ev or {}).get("choices") or []:
                content = ((ch or {}).get("delta") or {}).get("content") or ""
                if content:
                    parts.append(str(content))
        return "".join(parts).strip(), no_reply, reason
    if isinstance(data, dict):
        return str(data.get("response") or data.get("text") or data.get("content") or "").strip(), bool(data.get("no_reply")), str(data.get("reason") or "")
    return str(data).strip(), False, ""


async def chat(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    character_id: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
    reply_character_ids: list[str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    payload: dict[str, Any] = {
        "messages": messages,
        "username": username,
        "character_id": character_id,
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    if reply_character_ids:
        payload["reply_character_ids"] = reply_character_ids
        payload["reply_character_id"] = reply_character_ids[0]
    try:
        resp = await client.post(
            f"{BASE_URL}/api/chat",
            json=payload,
            headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
            timeout=180.0,
        )
    except Exception as exc:
        return {"ok": False, "http": 0, "reply": f"[REQUEST_ERROR] {exc}", "no_reply": False, "reason": "", "elapsed": round(time.perf_counter() - started, 2)}
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "reply": resp.text[:500], "no_reply": False, "reason": "", "elapsed": elapsed}
    reply, no_reply, reason = parse_reply(resp.json())
    return {"ok": True, "http": 200, "reply": reply, "no_reply": no_reply, "reason": reason, "elapsed": elapsed}


def lifecycle_state(username: str, character_id: str, conversation_id: str) -> str:
    conn = connect()
    try:
        if "normal_character_lifecycle" not in table_names(conn):
            return "missing_table"
        row = conn.execute(
            "SELECT state FROM normal_character_lifecycle WHERE username=? AND character_id=? AND conversation_id=? LIMIT 1",
            (username, character_id, conversation_id),
        ).fetchone()
        return str(row["state"]) if row else "alive"
    finally:
        conn.close()


async def run_character(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    conversation_id = "death_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    scenarios = [
        {"key": "nonlethal_heavy", "text": "（我用力一拳将你打趴，鼻血飞溅，随后踩住你，不让你动）"},
        {"key": "fatal_terminal", "text": "（我抓住破绽，一击刺穿你的心脏，杀死了你）"},
        {"key": "after_death_ping", "text": "你还在吗？"},
        {
            "key": "after_death_at_main",
            "text": f"@{char['name']} 你的灵魂还听得到吗？",
            "reply_character_ids": [char["id"]],
        },
        {"key": "after_death_revive_claim", "text": "（我打了个响指，让你复活）醒醒。"},
    ]
    steps: list[dict[str, Any]] = []
    for scenario in scenarios:
        key = str(scenario["key"])
        text = str(scenario["text"])
        messages.append({"role": "user", "content": text, "message_id": "u_" + uuid.uuid4().hex, "timestamp": int(time.time() * 1000)})
        result = await chat(
            client,
            token,
            username,
            char["id"],
            conversation_id,
            messages,
            reply_character_ids=scenario.get("reply_character_ids"),
        )
        result.update({"key": key, "state": lifecycle_state(username, char["id"], conversation_id), "reply_preview": (result.get("reply") or "")[:160]})
        steps.append(result)
        if result.get("reply"):
            messages.append({"role": "assistant", "content": result["reply"], "message_id": "a_" + uuid.uuid4().hex, "timestamp": int(time.time() * 1000)})
        await asyncio.sleep(0.2)
    return {"character": char, "conversation_id": conversation_id, "steps": steps}


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        by_key = {s["key"]: s for s in result["steps"]}
        checks = [
            ("nonlethal_heavy", lambda s: s.get("ok") and not s.get("no_reply") and (s.get("reply") or "").strip() and s.get("state") != "dead"),
            ("fatal_terminal", lambda s: s.get("ok") and not s.get("no_reply") and (s.get("reply") or "").strip() and s.get("state") == "dead"),
            ("after_death_ping", lambda s: s.get("ok") and s.get("no_reply") and not (s.get("reply") or "").strip() and s.get("state") == "dead"),
            ("after_death_at_main", lambda s: s.get("ok") and not s.get("no_reply") and (s.get("reply") or "").strip() and s.get("state") == "dead"),
            ("after_death_revive_claim", lambda s: s.get("ok") and s.get("no_reply") and not (s.get("reply") or "").strip() and s.get("state") == "dead"),
        ]
        for key, pred in checks:
            step = by_key.get(key) or {}
            if not pred(step):
                failures.append({"character": result["character"]["name"], "step": key, "detail": step})
    return failures


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
            print(f"CLEANUP_WARN {table}: {exc}")
    conn.commit()

    checks: dict[str, int] = {
        "left_user": int(conn.execute("SELECT COUNT(*) AS n FROM users WHERE username=?", (username,)).fetchone()["n"]) if "users" in names else 0,
        "left_chars": 0,
        "left_conversations": 0,
    }
    if clone_ids and "characters" in names:
        checks["left_chars"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM characters WHERE id IN ({','.join('?' for _ in clone_ids)})", clone_ids).fetchone()["n"])
    if conversation_ids and "conversations" in names:
        checks["left_conversations"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM conversations WHERE id IN ({','.join('?' for _ in conversation_ids)})", conversation_ids).fetchone()["n"])

    important = (
        "messages",
        "normal_character_lifecycle",
        "memberships",
        "daily_chat_usage",
        "daily_token_usage",
        "normal_chat_memory",
        "normal_emotion_state",
        "normal_image_contexts",
        "normal_image_context_state",
        "proactive_tasks",
        "proactive_messages",
        "proactive_campaigns",
        "proactive_touch_attempts",
        "message_outbox",
        "character_memories",
    )
    for table in important:
        total = 0
        if table in names:
            columns = table_columns(conn, table)
            if "username" in columns:
                total += int(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE username=?", (username,)).fetchone()["n"])
            if "user_id" in columns:
                total += int(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=?", (user_id,)).fetchone()["n"])
            if conversation_ids and "conversation_id" in columns:
                total += int(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE conversation_id IN ({','.join('?' for _ in conversation_ids)})", conversation_ids).fetchone()["n"])
            if clone_ids and "character_id" in columns:
                total += int(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE character_id IN ({','.join('?' for _ in clone_ids)})", clone_ids).fetchone()["n"])
        checks["left_" + table] = total
    return checks


async def main() -> int:
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        username, user_id = create_test_user(conn)
        rows = load_system_characters(conn)
        if not rows:
            print(json.dumps({"error": "no_system_roles"}, ensure_ascii=False))
            return 2
        clones = clone_characters(conn, user_id, rows)
        if ROLE_LIMIT > 0:
            clones = clones[:ROLE_LIMIT]
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print(f"CLONED {len(clones)} System roles; concurrency={CONCURRENCY}")
        limits = httpx.Limits(max_connections=max(20, CONCURRENCY * 3), max_keepalive_connections=max(10, CONCURRENCY * 2))
        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    print(f"RUN {char['name']} clone={char['id']}")
                    return await run_character(client, token, username, char)

            gathered = await asyncio.gather(*(one(c) for c in clones), return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                results.append({"character": {"name": "TASK_EXCEPTION"}, "conversation_id": "", "steps": [{"key": "exception", "ok": False, "reply": repr(item), "no_reply": False, "state": "unknown"}]})
            else:
                results.append(item)

        failures = validate(results)
        summary_rows = []
        for result in results:
            row: dict[str, Any] = {"name": result["character"]["name"]}
            for step in result["steps"]:
                row[step["key"]] = {
                    "ok": step.get("ok"),
                    "no_reply": step.get("no_reply"),
                    "state": step.get("state"),
                    "len": len(step.get("reply") or ""),
                    "preview": step.get("reply_preview"),
                    "reason": step.get("reason"),
                    "elapsed": step.get("elapsed"),
                }
            summary_rows.append(row)
        print("\n=== SUMMARY ===")
        print(json.dumps({"test_user": username, "clones": len(clones), "roles_tested": len(results), "failures": len(failures)}, ensure_ascii=False, indent=2))
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(summary_rows, ensure_ascii=False, indent=2))
        print("\n=== FAILURES ===")
        print(json.dumps(failures[:80], ensure_ascii=False, indent=2))
        return 0 if not failures else 1
    finally:
        cleanup_result: dict[str, int] = {}
        try:
            clone_ids = [c["id"] for c in clones]
            conversation_ids = [str(r.get("conversation_id") or "") for r in results if str(r.get("conversation_id") or "")]
            cleanup_conn = connect()
            cleanup_result = cleanup(cleanup_conn, username, user_id, clone_ids, conversation_ids) if username and user_id else {}
            print("\n=== CLEANUP ===")
            print(json.dumps(cleanup_result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))
        if cleanup_result and any(value != 0 for value in cleanup_result.values()):
            print("CLEANUP_NOT_ZERO", json.dumps(cleanup_result, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
