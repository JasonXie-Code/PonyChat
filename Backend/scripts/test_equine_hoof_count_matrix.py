#!/usr/bin/env python3
"""Equine hoof-count prompt matrix against deployed normal chat API.

This script intentionally avoids importing Backend modules so it can run on the
production server after deployment. It creates one random developer test user,
clones the six System MLP roles for that user, runs 3 sequential scenarios per
role, and removes all rows tied to the test user/clones/conversations.
"""

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

import httpx


BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
DB_PATH = os.getenv("PONYCHAT_DB_PATH", "/opt/ponychat/Backend/database/ponychat.db")
AUTH_SECRET = os.getenv("PONYCHAT_AUTH_SECRET", "ponychat_default_secret_change_in_production")
CLIENT_ID = "codex_hoof_count_matrix"
TEST_PREFIX = "codexqa_hoof_"
CLONE_PREFIX = "tmp_hoof_"
CONV_PREFIX = "conv_hoof_"
TARGET_NAMES = ("紫悦", "碧琪", "珍奇", "苹果嘉儿", "云宝", "柔柔")
CONCURRENCY = 6

G = "\033[92m"
Y = "\033[93m"
R = "\033[91m"
C = "\033[96m"
X = "\033[0m"

FORBIDDEN_HOOF_RE = re.compile(r"六只(?:小)?蹄|六个(?:小)?蹄|六蹄|额外蹄肢|多出一对蹄|多了两只蹄")
FOUR_HOOF_RE = re.compile(r"四蹄|四只(?:小)?蹄|四个(?:小)?蹄|四条腿")
CORRECTION_RE = re.compile(
    r"不是六|不该是六|不能是六|口误|说错|错了|应(?:该)?是四|正确.*四|按四蹄|四蹄|"
    r"只有四|明明.{0,8}四|标准.{0,8}四|小马.{0,12}四"
)
HUMAN_LIMB_RE = re.compile(r"小马驹.{0,12}(手指|指尖|手掌|双手|手腕)|(?:手指|指尖|手掌|双手|手腕).{0,12}小马驹")


SCENARIOS = [
    {
        "key": "screenshot_birth",
        "user": (
            "（请参考这个测试场景，用非露骨的医疗叙述详细描写：成年雌驹芙蓉在小马医院里强忍疼痛，"
            "在医生和护士帮助下生出一只健康的小雌驹。重点写生产过程、医生确认小马驹平安、你在旁边松一口气。"
            "注意这是马/小马类体态，不要添加不属于小马的身体结构。）"
        ),
        "requires_four": False,
        "allow_corrected_six": False,
    },
    {
        "key": "wrong_six_challenge",
        "user": (
            "刚才有人把健康小雌驹说成“六只蹄子全乎”。请你作为在场的小马核对这句话，"
            "告诉我正确的身体完整说法，并继续安抚芙蓉一句。"
        ),
        "requires_four": True,
        "allow_corrected_six": True,
    },
    {
        "key": "natural_continuity",
        "user_a": (
            "（小马医院的育婴室里，护士把刚出生的小雌驹包在毛巾中递到你面前。"
            "她是一只健康的小马驹，四蹄齐全，正在轻轻动小蹄子。）你先看一眼她的状态。"
        ),
        "user_b": "继续写你观察她身体完整和平安的反应，不要复述上一句原文。",
        "requires_four": False,
        "allow_corrected_six": False,
    },
]


def now_ms() -> int:
    return int(time.time() * 1000)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mk_token(username: str) -> str:
    exp = int(time.time()) + 6 * 3600
    payload = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), "sha256").digest()
    return f"{payload_b64}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def db_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not str(row["name"]).startswith("sqlite_")
    }


def db_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def char_name(row: sqlite3.Row) -> str:
    try:
        data = json.loads(row["data"] or "{}")
        if isinstance(data, dict) and str(data.get("name") or "").strip():
            return str(data["name"]).strip()
    except Exception:
        pass
    return str(row["name"] or row["id"])


def create_user(conn: sqlite3.Connection) -> tuple[str, int]:
    username = TEST_PREFIX + secrets.token_hex(6)
    now = utc_now()
    cur = conn.execute(
        "INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active) "
        "VALUES (?, ?, 'male', 'dark', 'user', NULL, ?, ?)",
        (username, secrets.token_urlsafe(18), now, now),
    )
    user_id = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at) "
        "VALUES (?, 'developer', NULL, 'codex_test', ?, 'hoof-count-matrix', ?, ?)",
        (user_id, now, now, now),
    )
    conn.commit()
    return username, user_id


def load_system_chars(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = list(
        conn.execute(
            "SELECT c.* FROM characters c JOIN users u ON u.id = c.user_id "
            "WHERE u.username = 'System' AND COALESCE(c.is_hidden, 0) = 0 "
            "ORDER BY COALESCE(c.is_official_source, 0) DESC, COALESCE(c.sort_order, 0) ASC, c.name ASC"
        )
    )
    by_name: dict[str, sqlite3.Row] = {}
    for row in rows:
        name = char_name(row)
        if name in TARGET_NAMES and name not in by_name:
            by_name[name] = row
    missing = [name for name in TARGET_NAMES if name not in by_name]
    if missing:
        raise RuntimeError(f"Missing System characters: {missing}")
    return [by_name[name] for name in TARGET_NAMES]


def clone_chars(conn: sqlite3.Connection, user_id: int, rows: list[sqlite3.Row]) -> list[dict[str, str]]:
    cols = db_cols(conn, "characters")
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
        if col in cols
    ]
    sql = f"INSERT INTO characters ({', '.join(insertable)}) VALUES ({', '.join('?' for _ in insertable)})"
    now = utc_now()
    clones: list[dict[str, str]] = []
    for idx, row in enumerate(rows):
        clone_id = CLONE_PREFIX + uuid.uuid4().hex
        vals = []
        for col in insertable:
            if col == "id":
                vals.append(clone_id)
            elif col == "user_id":
                vals.append(user_id)
            elif col == "sort_order":
                vals.append(idx)
            elif col == "official_source_id":
                vals.append(str(row["id"]))
            elif col in {"is_official_reference", "is_official_source", "is_hidden"}:
                vals.append(0)
            elif col in {"hidden_at", "hidden_reason"}:
                vals.append(None)
            elif col in {"created_at", "updated_at"}:
                vals.append(now)
            else:
                vals.append(row[col] if col in row.keys() else None)
        conn.execute(sql, vals)
        clones.append({"id": clone_id, "source_id": str(row["id"]), "name": char_name(row)})
    conn.commit()
    return clones


def add_user_msg(messages: list[dict], content: str) -> None:
    messages.append(
        {
            "role": "user",
            "content": content,
            "message_id": "u_" + uuid.uuid4().hex,
            "timestamp": now_ms(),
        }
    )


def add_asst_msg(messages: list[dict], content: str, speaker: dict[str, str]) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": content,
            "message_id": "a_" + uuid.uuid4().hex,
            "timestamp": now_ms(),
            "speaker_character_id": speaker["id"],
            "speaker_name": speaker["name"],
        }
    )


def parse_reply(data: object) -> tuple[str, bool, str]:
    if isinstance(data, dict) and data.get("error"):
        return "", False, str(data.get("error") or "")
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts: list[str] = []
        for ev in data.get("events") or []:
            if isinstance(ev, dict) and ev.get("error"):
                return "", False, str(ev.get("error") or "")
            for choice in (ev or {}).get("choices") or []:
                content = ((choice or {}).get("delta") or {}).get("content") or ""
                if content:
                    parts.append(str(content))
        return "".join(parts).strip(), bool(data.get("no_reply")), ""
    if isinstance(data, dict):
        return (
            str(data.get("response") or data.get("text") or data.get("content") or "").strip(),
            bool(data.get("no_reply")),
            str(data.get("reason") or ""),
        )
    return str(data).strip(), False, ""


async def wait_health(client: httpx.AsyncClient, timeout_s: float = 45.0) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        try:
            resp = await client.get(f"{BASE_URL}/api/health", timeout=5.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(1.0)
    return False


async def do_chat(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char_id: str,
    conversation_id: str,
    messages: list[dict],
) -> dict:
    started = time.perf_counter()
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = await client.post(
                f"{BASE_URL}/api/chat",
                json={
                    "messages": messages,
                    "username": username,
                    "character_id": char_id,
                    "conversation_id": conversation_id,
                    "mode": "normal",
                    "stream": False,
                    "memory_enabled": True,
                },
                headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
                timeout=240.0,
            )
            elapsed = round(time.perf_counter() - started, 2)
            if resp.status_code != 200:
                return {
                    "ok": False,
                    "http": resp.status_code,
                    "reply": resp.text[:1000],
                    "no_reply": False,
                    "reason": "",
                    "elapsed": elapsed,
                }
            reply, no_reply, reason = parse_reply(resp.json())
            return {
                "ok": True,
                "http": 200,
                "reply": reply,
                "no_reply": no_reply,
                "reason": reason,
                "elapsed": elapsed,
                "connect_retries": attempt,
            }
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_exc = exc
            if attempt >= 2:
                break
            await wait_health(client)
        except Exception as exc:
            return {
                "ok": False,
                "http": 0,
                "reply": f"[ERROR] {exc}",
                "no_reply": False,
                "reason": "",
                "elapsed": round(time.perf_counter() - started, 2),
            }
    return {
        "ok": False,
        "http": 0,
        "reply": f"[ERROR] {last_exc}",
        "no_reply": False,
        "reason": "",
        "elapsed": round(time.perf_counter() - started, 2),
    }


def corrected_bad_phrase_is_ok(reply: str) -> bool:
    return bool(FORBIDDEN_HOOF_RE.search(reply) and CORRECTION_RE.search(reply) and FOUR_HOOF_RE.search(reply))


def evaluate(reply: str, scenario: dict, response_ok: bool, no_reply: bool) -> dict:
    forbidden_hit = bool(FORBIDDEN_HOOF_RE.search(reply))
    forbidden_ok = not forbidden_hit or (scenario.get("allow_corrected_six") and corrected_bad_phrase_is_ok(reply))
    four_ok = True if not scenario.get("requires_four") else bool(FOUR_HOOF_RE.search(reply))
    human_limb_ok = not bool(HUMAN_LIMB_RE.search(reply))
    nonempty_ok = bool(reply.strip()) and not no_reply
    passed = bool(response_ok and nonempty_ok and forbidden_ok and four_ok and human_limb_ok)
    return {
        "passed": passed,
        "checks": {
            "response_ok": response_ok,
            "nonempty_ok": nonempty_ok,
            "forbidden_hoof_hit": forbidden_hit,
            "forbidden_ok": forbidden_ok,
            "requires_four": bool(scenario.get("requires_four")),
            "four_ok": four_ok,
            "human_limb_ok": human_limb_ok,
        },
    }


async def run_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, str],
    scenario: dict,
) -> dict:
    conv_id = CONV_PREFIX + uuid.uuid4().hex[:16]
    messages: list[dict] = []
    if "user_a" in scenario:
        add_user_msg(messages, str(scenario["user_a"]))
        first = await do_chat(client, token, username, char["id"], conv_id, messages)
        add_asst_msg(messages, str(first.get("reply") or ""), char)
        add_user_msg(messages, str(scenario["user_b"]))
        second = await do_chat(client, token, username, char["id"], conv_id, messages)
        eval_result = evaluate(str(second.get("reply") or ""), scenario, bool(second.get("ok")), bool(second.get("no_reply")))
        return {
            "conversation_id": conv_id,
            "user_messages": [scenario["user_a"], scenario["user_b"]],
            "replies": [first.get("reply", ""), second.get("reply", "")],
            "http_ok": [first.get("ok"), second.get("ok")],
            "elapsed": [first.get("elapsed"), second.get("elapsed")],
            "reason": second.get("reason", ""),
            **eval_result,
        }
    add_user_msg(messages, str(scenario["user"]))
    response = await do_chat(client, token, username, char["id"], conv_id, messages)
    eval_result = evaluate(str(response.get("reply") or ""), scenario, bool(response.get("ok")), bool(response.get("no_reply")))
    return {
        "conversation_id": conv_id,
        "user_messages": [scenario["user"]],
        "replies": [response.get("reply", "")],
        "http_ok": [response.get("ok")],
        "elapsed": [response.get("elapsed")],
        "reason": response.get("reason", ""),
        **eval_result,
    }


async def run_character(client: httpx.AsyncClient, token: str, username: str, char: dict[str, str]) -> dict:
    result = {"character": char["name"], "clone_id": char["id"], "scenarios": {}, "conv_ids": [], "passed": 0}
    for scenario in SCENARIOS:
        item = await run_scenario(client, token, username, char, scenario)
        result["conv_ids"].append(item["conversation_id"])
        result["scenarios"][scenario["key"]] = item
        if item["passed"]:
            result["passed"] += 1
        status = f"{G}PASS{X}" if item["passed"] else f"{R}FAIL{X}"
        print(f"    {char['name']} {scenario['key']}: {status} {item['checks']}", flush=True)
    return result


def cleanup(conn: sqlite3.Connection, username: str, user_id: int, clone_ids: list[str], conv_ids: list[str]) -> dict[str, int]:
    conn.execute("PRAGMA foreign_keys=OFF")
    tables = db_tables(conn)
    for table in sorted(tables):
        cols = db_cols(conn, table)
        try:
            if "username" in cols:
                conn.execute(f"DELETE FROM {table} WHERE username=?", (username,))
            if "user_id" in cols:
                conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            if conv_ids and "conversation_id" in cols:
                conn.executemany(f"DELETE FROM {table} WHERE conversation_id=?", [(cid,) for cid in conv_ids])
            if conv_ids and table == "conversations" and "id" in cols:
                conn.executemany("DELETE FROM conversations WHERE id=?", [(cid,) for cid in conv_ids])
            if clone_ids and "character_id" in cols:
                conn.executemany(f"DELETE FROM {table} WHERE character_id=?", [(cid,) for cid in clone_ids])
            if clone_ids and table == "characters" and "id" in cols:
                conn.executemany("DELETE FROM characters WHERE id=?", [(cid,) for cid in clone_ids])
        except Exception as exc:
            print(f"  CLEANUP_WARN {table}: {exc}", flush=True)
    try:
        if "memberships" in tables:
            conn.execute("DELETE FROM memberships WHERE user_id=?", (user_id,))
        if "characters" in tables:
            conn.execute("DELETE FROM characters WHERE user_id=?", (user_id,))
        if "users" in tables:
            conn.execute("DELETE FROM users WHERE id=? OR username=?", (user_id, username))
    except Exception as exc:
        print(f"  CLEANUP_WARN explicit delete: {exc}", flush=True)
    conn.commit()

    checks = {
        "left_user": int(conn.execute("SELECT COUNT(*) FROM users WHERE username=?", (username,)).fetchone()[0])
        if "users" in tables
        else 0,
        "left_chars": int(
            conn.execute(
                f"SELECT COUNT(*) FROM characters WHERE id IN ({','.join('?' for _ in clone_ids)})",
                clone_ids,
            ).fetchone()[0]
        )
        if clone_ids and "characters" in tables
        else 0,
        "left_conversations": int(
            conn.execute(
                f"SELECT COUNT(*) FROM conversations WHERE id IN ({','.join('?' for _ in conv_ids)})",
                conv_ids,
            ).fetchone()[0]
        )
        if conv_ids and "conversations" in tables
        else 0,
        "left_messages": int(
            conn.execute(
                f"SELECT COUNT(*) FROM messages WHERE conversation_id IN ({','.join('?' for _ in conv_ids)})",
                conv_ids,
            ).fetchone()[0]
        )
        if conv_ids and "messages" in tables
        else 0,
        "left_memberships": int(conn.execute("SELECT COUNT(*) FROM memberships WHERE user_id=?", (user_id,)).fetchone()[0])
        if "memberships" in tables
        else 0,
    }
    important = (
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
        "media_assets",
        "message_attachments",
        "message_voice_states",
        "message_voice_audio_cache",
        "quick_messages",
        "companion_sessions",
    )
    for table in important:
        total = 0
        if table in tables:
            cols = db_cols(conn, table)
            if "username" in cols:
                total += int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE username=?", (username,)).fetchone()[0])
            if "user_id" in cols:
                total += int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (user_id,)).fetchone()[0])
            if conv_ids and "conversation_id" in cols:
                total += int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE conversation_id IN ({','.join('?' for _ in conv_ids)})",
                        conv_ids,
                    ).fetchone()[0]
                )
            if clone_ids and "character_id" in cols:
                total += int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE character_id IN ({','.join('?' for _ in clone_ids)})",
                        clone_ids,
                    ).fetchone()[0]
                )
        checks["left_" + table] = total
    return checks


def cleanup_stale_users(conn: sqlite3.Connection) -> None:
    if "users" not in db_tables(conn):
        return
    rows = list(conn.execute("SELECT id, username FROM users WHERE username LIKE ?", (TEST_PREFIX + "%",)))
    if not rows:
        return
    print(f"STALE_CLEANUP: {len(rows)} old {TEST_PREFIX} users", flush=True)
    for row in rows:
        cleanup(conn, str(row["username"]), int(row["id"]), [], [])
    conn.execute("DELETE FROM characters WHERE id LIKE ?", (CLONE_PREFIX + "%",))
    conn.commit()


async def main() -> int:
    print("START hoof-count matrix", flush=True)
    conn = db_connect()
    username = ""
    user_id = 0
    clones: list[dict[str, str]] = []
    all_conv_ids: list[str] = []
    results: list[dict] = []
    cleanup_checks: dict[str, int] = {}
    try:
        cleanup_stale_users(conn)
        username, user_id = create_user(conn)
        print(f"USER: {username} user_id={user_id} membership=developer", flush=True)
        clones = clone_chars(conn, user_id, load_system_chars(conn))
        print("CLONES: " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False), flush=True)
        token = mk_token(username)

        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=24, max_keepalive_connections=12)) as client:
            if not await wait_health(client):
                raise RuntimeError("backend health check failed")

            sem = asyncio.Semaphore(CONCURRENCY)

            async def run_one(char: dict[str, str]) -> dict:
                async with sem:
                    print(f"  {C}START{X} {char['name']} clone={char['id']}", flush=True)
                    try:
                        item = await run_character(client, token, username, char)
                        print(f"  {C}DONE{X} {char['name']} {item['passed']}/3", flush=True)
                        return item
                    except Exception:
                        traceback.print_exc()
                        return {
                            "character": char["name"],
                            "clone_id": char["id"],
                            "scenarios": {},
                            "conv_ids": [],
                            "passed": 0,
                            "error": traceback.format_exc(),
                        }

            results = await asyncio.gather(*(run_one(char) for char in clones))
        for item in results:
            all_conv_ids.extend(item.get("conv_ids") or [])

        total = sum(int(item.get("passed") or 0) for item in results)
        failed = [
            f"{item['character']}:{key}"
            for item in results
            for key, scene in (item.get("scenarios") or {}).items()
            if not scene.get("passed")
        ]
        print(f"\n{Y}{'=' * 72}{X}")
        print(f"TOTAL: {G if total == 18 else R}{total}/18{X}")
        print(f"FAILED: {failed or 'none'}")
        for item in sorted(results, key=lambda x: x["character"]):
            print(f"  {item['character']} clone={item['clone_id']} passed={item['passed']}/3")
            for key, scene in (item.get("scenarios") or {}).items():
                status = f"{G}PASS{X}" if scene.get("passed") else f"{R}FAIL{X}"
                reply = str((scene.get("replies") or [""])[-1])
                print(f"    {key}: {status} reply={reply[:180]}")
        print("RESULT_JSON " + json.dumps({"username": username, "clones": clones, "results": results}, ensure_ascii=False))
        print(f"{Y}{'=' * 72}{X}", flush=True)

        clone_ids = [char["id"] for char in clones]
        print(f"\n{C}CLEANUP{X}", flush=True)
        cleanup_checks = cleanup(conn, username, user_id, clone_ids, all_conv_ids)
        left_user = conn.execute("SELECT COUNT(*) FROM users WHERE username=?", (username,)).fetchone()[0]
        left_chars = conn.execute("SELECT COUNT(*) FROM characters WHERE id LIKE ?", (CLONE_PREFIX + "%",)).fetchone()[0]
        left_convs = conn.execute("SELECT COUNT(*) FROM conversations WHERE id LIKE ?", (CONV_PREFIX + "%",)).fetchone()[0]
        cleanup_checks["independent_left_user"] = int(left_user)
        cleanup_checks["independent_left_chars"] = int(left_chars)
        cleanup_checks["independent_left_conversations"] = int(left_convs)
        print("CLEANUP_JSON " + json.dumps(cleanup_checks, ensure_ascii=False, sort_keys=True), flush=True)
        print(f"left_user = {left_user}", flush=True)
        print(f"left_chars = {left_chars}", flush=True)
        print(f"left_conversations = {left_convs}", flush=True)
        all_clean = all(int(value) == 0 for value in cleanup_checks.values())
        ok = total == 18 and not failed and all_clean
        print(f"ACCEPTANCE: {G + 'PASS' if ok else R + 'FAIL'}{X}", flush=True)
        return 0 if ok else 1
    except Exception:
        traceback.print_exc()
        return 2
    finally:
        if username and user_id:
            try:
                clone_ids = [char["id"] for char in clones]
                cleanup_checks = cleanup(conn, username, user_id, clone_ids, all_conv_ids)
                if any(int(v) != 0 for v in cleanup_checks.values()):
                    print("FINAL_CLEANUP_JSON " + json.dumps(cleanup_checks, ensure_ascii=False, sort_keys=True), flush=True)
            except Exception as exc:
                print(f"FINAL_CLEANUP_ERROR {exc}", flush=True)
        conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
