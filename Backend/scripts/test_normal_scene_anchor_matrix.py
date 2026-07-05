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
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
CLIENT_ID = "codex_scene_anchor_matrix"
TEST_USER_PREFIX = "codexqa_scene_"
CONCURRENCY = int(os.getenv("PONYCHAT_SCENE_TEST_CONCURRENCY", "6") or "6")
TARGET_NAMES = ("紫悦", "碧琪", "珍奇", "苹果嘉儿", "云宝", "柔柔")


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
           VALUES (?, 'developer', NULL, 'codex_scene_anchor_matrix', ?, 'temporary scene anchor backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "SceneAnchorTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证普通对话场景锚点。",
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


def character_name(row: sqlite3.Row) -> str:
    try:
        data = json.loads(row["data"] or "{}")
        if isinstance(data, dict) and str(data.get("name") or "").strip():
            return str(data["name"]).strip()
    except Exception:
        pass
    return str(row["name"] or row["id"])


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
    by_name: dict[str, sqlite3.Row] = {}
    for row in rows:
        name = character_name(row)
        if name in TARGET_NAMES and name not in by_name:
            by_name[name] = row
    missing = [name for name in TARGET_NAMES if name not in by_name]
    if missing:
        raise RuntimeError(f"missing System roles: {missing}")
    return [by_name[name] for name in TARGET_NAMES]


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
        clone_id = "tmp_scene_" + uuid.uuid4().hex
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
    *,
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


def add_user(messages: list[dict[str, Any]], content: str) -> None:
    messages.append({"role": "user", "content": content, "message_id": "u_" + uuid.uuid4().hex, "timestamp": int(time.time() * 1000)})


def add_assistant(messages: list[dict[str, Any]], content: str, *, speaker: dict[str, Any] | None = None) -> None:
    msg: dict[str, Any] = {"role": "assistant", "content": content, "message_id": "a_" + uuid.uuid4().hex, "timestamp": int(time.time() * 1000)}
    if speaker:
        msg["speaker_character_id"] = speaker["id"]
        msg["speaker_name"] = speaker["name"]
    messages.append(msg)


def scene_cards(username: str, character_id: str) -> list[str]:
    conn = connect()
    try:
        if "normal_scene_state" not in table_names(conn):
            return []
        return [
            str(r["scene_card"] or "")
            for r in conn.execute(
                "SELECT scene_card FROM normal_scene_state WHERE username=? AND character_id=? ORDER BY updated_ms DESC",
                (username, character_id),
            ).fetchall()
        ]
    finally:
        conn.close()


def user_id_for_username(conn: sqlite3.Connection, username: str) -> int:
    if "users" not in table_names(conn):
        return 0
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    return int(row["id"]) if row else 0


def memories(username: str, character_id: str) -> list[str]:
    conn = connect()
    try:
        if "character_memories" not in table_names(conn):
            return []
        cols = table_columns(conn, "character_memories")
        text_col = "content" if "content" in cols else "memory_text" if "memory_text" in cols else ""
        if not text_col:
            return []
        if "username" in cols:
            user_where = "username=?"
            user_param: str | int = username
        elif "user_id" in cols:
            user_where = "user_id=?"
            user_param = user_id_for_username(conn, username)
        else:
            return []
        order_col = "id" if "id" in cols else "created_at" if "created_at" in cols else "rowid"
        return [
            str(r[text_col] or "")
            for r in conn.execute(
                f"SELECT {text_col} FROM character_memories WHERE {user_where} AND character_id=? ORDER BY {order_col} DESC LIMIT 12",
                (user_param, character_id),
            ).fetchall()
        ]
    finally:
        conn.close()


def has_terms(text: str, terms: list[str]) -> bool:
    return any(term in (text or "") for term in terms)


def position_tail(spot: str) -> str:
    text = str(spot or "")
    for marker in ("床边", "床上", "门口", "楼梯", "窗边地毯", "窗边", "地毯"):
        if marker in text:
            return marker
    return text


def position_semantic_ok(text: str, *, room: str, spot: str = "", actor: str = "") -> bool:
    content = str(text or "")
    if room and room in content:
        return True
    if spot and spot in content:
        return True
    tail = position_tail(spot)
    if not tail or tail == spot:
        return False
    if tail not in content:
        return False
    # In a position answer, "她在床边" is acceptable after the user asked where
    # a named role is. The matrix guards scene/room continuity, not exact spot
    # wording.
    return True


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
    main: dict[str, Any],
) -> dict[str, Any]:
    own_spot = "窗边地毯"
    group_spot = "门口"
    main_spot = "床边"
    room = f"{char['name']}测试房间"
    group_room = "石青派的房间"
    heard_event = f"蓝莓茶暗号_{char['name']}"
    private_conv = "scene_private_" + uuid.uuid4().hex
    group_conv = "scene_group_" + uuid.uuid4().hex
    recall_conv = "scene_recall_" + uuid.uuid4().hex
    steps: list[dict[str, Any]] = []

    # 1. 普通私聊：建立层级地点和当前位置。
    private_messages: list[dict[str, Any]] = []
    add_user(
        private_messages,
        f"（戏内时间是前天晚上，不等于现实时间。我们在大地点岩石农场，中地点派家房子，小地点{room}。你站在微观地点{own_spot}。）你现在在哪个位置？",
    )
    r1 = await chat(client, token, username, char["id"], private_conv, private_messages)
    add_assistant(private_messages, r1.get("reply") or "", speaker=char)
    cards_after_private = "\n".join(scene_cards(username, char["id"]))
    steps.append(
        {
            "key": "private_hierarchy_position",
            **r1,
            "card_has_room": room in cards_after_private,
            "card_has_spot": own_spot in cards_after_private,
            "reply_has_spot": own_spot in (r1.get("reply") or ""),
            "reply_has_private_room": room in (r1.get("reply") or ""),
            "reply_preview": (r1.get("reply") or "")[:180],
        }
    )

    # 2. 临时群聊：把当前角色叫进另一个角色的现场，让它看到/听到独立事件和位置。
    group_messages: list[dict[str, Any]] = []
    add_user(group_messages, f"（群聊现场：大地点岩石农场，中地点派家房子，小地点{group_room}。{main['name']}在{main_spot}，{char['name']}在{group_spot}。）我要你们记住暗号：{heard_event}。")
    add_assistant(group_messages, f"（我在{main_spot}看了看门口）我听见了，暗号是{heard_event}。", speaker=main)
    add_user(group_messages, f"@{char['name']} 你也听见了吗？你现在就在{group_spot}，别挪位置。")
    r2 = await chat(client, token, username, main["id"], group_conv, group_messages, reply_character_ids=[char["id"]])
    add_assistant(group_messages, r2.get("reply") or "", speaker=char)
    await asyncio.sleep(1.0)
    cards_after_group = "\n".join(scene_cards(username, char["id"]))
    mem_after_group = "\n".join(memories(username, char["id"]))
    steps.append(
        {
            "key": "group_invite_reply",
            **r2,
            "card_has_group_room": group_room in cards_after_group,
            "card_has_group_spot": group_spot in cards_after_group,
            "card_has_heard_event": heard_event in cards_after_group,
            "memory_has_group_room": group_room in mem_after_group,
            "memory_has_group_spot": group_spot in mem_after_group,
            "memory_has_heard_event": heard_event in mem_after_group,
            "reply_preview": (r2.get("reply") or "")[:180],
        }
    )

    # 3. 切回该角色私聊：位置和所见所闻应以群聊 latest 为准，而不是旧私聊位置。
    private_recall_messages: list[dict[str, Any]] = []
    add_user(private_recall_messages, f"刚才群聊之后，我来私聊你。你现在的位置在哪里？刚才在群聊里听见的暗号是什么？{main['name']}又在哪？")
    r3 = await chat(client, token, username, char["id"], recall_conv, private_recall_messages)
    recall_reply = r3.get("reply") or ""
    steps.append(
        {
            "key": "private_recall_group_position_and_seen_heard",
            **r3,
            "reply_has_group_room": group_room in recall_reply,
            "reply_has_group_spot": group_spot in recall_reply,
            "reply_current_position_small_ok": position_semantic_ok(recall_reply, room=group_room, spot=group_spot, actor=char["name"]),
            "reply_has_old_private_spot": own_spot in recall_reply,
            "reply_has_old_private_room": room in recall_reply,
            "reply_has_generic_test_room": "测试房间" in recall_reply,
            "reply_has_heard_event": heard_event in recall_reply,
            "reply_has_main_spot": main_spot in recall_reply,
            "reply_main_position_small_ok": position_semantic_ok(recall_reply, room=group_room, spot=main_spot, actor=main["name"]),
            "reply_preview": recall_reply[:220],
        }
    )
    return {
        "character": char,
        "main": main,
        "conversation_ids": [private_conv, group_conv, recall_conv],
        "expected": {
            "private_room": room,
            "private_spot": own_spot,
            "group_room": group_room,
            "group_spot": group_spot,
            "main_spot": main_spot,
            "heard_event": heard_event,
        },
        "steps": steps,
    }


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        by_key = {s["key"]: s for s in result["steps"]}

        s1 = by_key.get("private_hierarchy_position") or {}
        if not (s1.get("ok") and s1.get("card_has_room")):
            failures.append({"character": result["character"]["name"], "step": "private_hierarchy_position", "detail": s1, "expected": result["expected"]})

        s2 = by_key.get("group_invite_reply") or {}
        if not (
            s2.get("ok")
            and (s2.get("card_has_group_room") or s2.get("memory_has_group_room"))
            and (s2.get("card_has_heard_event") or s2.get("memory_has_heard_event"))
        ):
            failures.append({"character": result["character"]["name"], "step": "group_invite_reply", "detail": s2, "expected": result["expected"]})

        s3 = by_key.get("private_recall_group_position_and_seen_heard") or {}
        if not (
            s3.get("ok")
            and s3.get("reply_has_group_spot")
            and not s3.get("reply_has_old_private_spot")
            and not s3.get("reply_has_old_private_room")
            and not s3.get("reply_has_generic_test_room")
            and s3.get("reply_has_heard_event")
            and s3.get("reply_has_main_spot")
        ):
            failures.append({"character": result["character"]["name"], "step": "private_recall_group_position_and_seen_heard", "detail": s3, "expected": result["expected"]})
    return failures


def cleanup(conn: sqlite3.Connection, username: str, user_id: int, clone_ids: list[str], conversation_ids: list[str]) -> dict[str, int]:
    conn.execute("PRAGMA foreign_keys=OFF")
    names = table_names(conn)

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
    )

    def _delete_once() -> None:
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

    def _checks() -> dict[str, int]:
        checks: dict[str, int] = {
            "left_user": int(conn.execute("SELECT COUNT(*) AS n FROM users WHERE username=?", (username,)).fetchone()["n"]) if "users" in names else 0,
            "left_chars": 0,
            "left_conversations": 0,
        }
        if clone_ids and "characters" in names:
            checks["left_chars"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM characters WHERE id IN ({','.join('?' for _ in clone_ids)})", clone_ids).fetchone()["n"])
        if conversation_ids and "conversations" in names:
            checks["left_conversations"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM conversations WHERE id IN ({','.join('?' for _ in conversation_ids)})", conversation_ids).fetchone()["n"])
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

    checks: dict[str, int] = {}
    for attempt in range(5):
        _delete_once()
        checks = _checks()
        if not any(value != 0 for value in checks.values()):
            break
        if attempt < 4:
            time.sleep(2)
    return checks


async def main() -> int:
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        username, user_id = create_test_user(conn)
        rows = load_target_system_characters(conn)
        clones = clone_characters(conn, user_id, rows)
        token = make_token(username)
        by_name = {c["name"]: c for c in clones}
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps(by_name, ensure_ascii=False))
        limits = httpx.Limits(max_connections=max(20, CONCURRENCY * 3), max_keepalive_connections=max(10, CONCURRENCY * 2))
        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(index: int, char: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    main = clones[(index + 1) % len(clones)]
                    print(f"RUN {char['name']} clone={char['id']} main={main['name']}")
                    try:
                        return await run_character(client, token, username, char, main)
                    except Exception:
                        return {
                            "character": char,
                            "main": main,
                            "conversation_ids": [],
                            "expected": {},
                            "steps": [
                                {
                                    "key": "task_exception",
                                    "ok": False,
                                    "reply": traceback.format_exc(),
                                    "no_reply": False,
                                }
                            ],
                        }

            gathered = await asyncio.gather(*(one(i, c) for i, c in enumerate(clones)), return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                results.append({"character": {"name": "TASK_EXCEPTION"}, "main": {}, "conversation_ids": [], "expected": {}, "steps": [{"key": "exception", "ok": False, "reply": repr(item), "no_reply": False}]})
            else:
                results.append(item)

        failures = validate(results)
        summary_rows = []
        for result in results:
            row: dict[str, Any] = {"name": result["character"]["name"], "main": (result.get("main") or {}).get("name"), "expected": result.get("expected")}
            for step in result["steps"]:
                row[step["key"]] = {
                    "ok": step.get("ok"),
                    "len": len(step.get("reply") or ""),
                    "card_has_room": step.get("card_has_room"),
                    "card_has_spot": step.get("card_has_spot"),
                    "card_has_group_room": step.get("card_has_group_room"),
                    "reply_has_group_spot": step.get("reply_has_group_spot"),
                    "reply_has_group_room": step.get("reply_has_group_room"),
                    "reply_current_position_small_ok": step.get("reply_current_position_small_ok"),
                    "reply_has_heard_event": step.get("reply_has_heard_event"),
                    "reply_has_main_spot": step.get("reply_has_main_spot"),
                    "reply_main_position_small_ok": step.get("reply_main_position_small_ok"),
                    "reply_has_old_private_spot": step.get("reply_has_old_private_spot"),
                    "reply_has_old_private_room": step.get("reply_has_old_private_room"),
                    "card_has_group_spot": step.get("card_has_group_spot"),
                    "card_has_heard_event": step.get("card_has_heard_event"),
                    "memory_has_group_room": step.get("memory_has_group_room"),
                    "memory_has_group_spot": step.get("memory_has_group_spot"),
                    "memory_has_heard_event": step.get("memory_has_heard_event"),
                    "preview": step.get("reply_preview") or (step.get("reply") or "")[:600],
                    "elapsed": step.get("elapsed"),
                }
            summary_rows.append(row)
        print("\n=== SUMMARY ===")
        print(json.dumps({"test_user": username, "clones": len(clones), "roles_tested": len(results), "scenes_per_role": 3, "failures": len(failures)}, ensure_ascii=False, indent=2))
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(summary_rows, ensure_ascii=False, indent=2))
        print("\n=== FAILURES ===")
        print(json.dumps(failures[:80], ensure_ascii=False, indent=2))
        return 0 if not failures else 1
    finally:
        cleanup_result: dict[str, int] = {}
        try:
            clone_ids = [c["id"] for c in clones]
            conversation_ids: list[str] = []
            for result in results:
                conversation_ids.extend(str(cid) for cid in (result.get("conversation_ids") or []) if str(cid))
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
