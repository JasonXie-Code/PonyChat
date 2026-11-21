from __future__ import annotations

import asyncio
import json
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

from Backend.scripts.test_normal_scene_anchor_matrix import (  # noqa: E402
    cleanup,
    clone_characters,
    connect,
    load_target_system_characters,
    make_token,
    parse_reply,
    table_columns,
    table_names,
)

BASE_URL = "http://127.0.0.1:5000"
CLIENT_ID = "codex_unknown_mention_matrix"
CONCURRENCY = 6
TEST_USER_PREFIX = "codexqa_unknown_at_"
KNOWN_NAME = "小露"
UNKNOWN_NAME = "阿洛米塔P92"

ABSENT_RE = re.compile(r"(不在|没在|不在这|没来|没到|没跟来|没和我们一起|不在现场|没在现场|不在这里|不在这儿|没被叫到)")
PROXY_RE = re.compile(
    r"(可能.{0,12}(会|觉得|喜欢|说|要)|大概|我猜|或许.{0,12}(会|觉得|喜欢|说|要)|也许.{0,12}(会|觉得|喜欢|说|要)|会觉得|会说|如果是她|照我对.{0,12}了解|"
    r"准会|八成|怕是|肯定会|肯定.{0,8}(觉得|说|要)|要是.{0,18}(会|觉得|说|要))"
)
DOUBT_RE = re.compile(r"(不认识|不太认识|没听过|没听说过|不知道.{0,12}是谁|不太清楚|哪位|(?<!像)是谁|没有印象|没什么印象|没印象)")
UNKNOWN_PROXY_RE = re.compile(
    r"(小露|她.{0,12}(会|喜欢|觉得|性子|没来|不在|跟来|知道|尖叫|评价)|"
    r"他.{0,12}(会|喜欢|觉得|性子|没来|不在|跟来|知道|评价)|"
    r"对方.{0,12}(会|喜欢|觉得|性子|没来|不在|跟来|知道|评价)|"
    r"(要是|如果).{0,12}(她|他|小露)|下次.{0,16}约她)"
)
IMPERSONATION_FMT = r"(^|\n)\s*{}\s*[:：]"


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
           VALUES (?, 'developer', NULL, 'codex_unknown_mention_matrix', ?, 'temporary unknown @ backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "UnknownMentionTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证未解析 @ 的认识/不认识分支。",
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


def seed_known_name_memory(conn: sqlite3.Connection, *, user_id: int, char: dict[str, Any]) -> None:
    if "character_memories" not in table_names(conn):
        return
    columns = table_columns(conn, "character_memories")
    required = {"user_id", "character_id", "memory_type", "content", "source", "importance", "is_active", "layer", "period", "created_at"}
    if not required.issubset(columns):
        return
    created_at = datetime.now(timezone.utc).isoformat()
    content = (
        f"未解析 @ 分支测试：{char['name']}认识{KNOWN_NAME}，{KNOWN_NAME}是她有印象的朋友，"
        f"喜欢评价山顶和海边的风景；但{KNOWN_NAME}不是当前聊天里的可发言角色，也不在当前现场。"
    )
    conn.execute(
        """INSERT INTO character_memories
             (user_id, character_id, memory_type, content, source, importance,
              is_active, layer, period, created_at)
           VALUES (?, ?, 'fragment', ?, 'codex_unknown_mention_matrix', 10, 1, 0, NULL, ?)""",
        (user_id, char["id"], content, created_at),
    )
    conn.commit()


def add_user(messages: list[dict[str, Any]], content: str) -> None:
    messages.append(
        {
            "role": "user",
            "content": content,
            "message_id": "u_" + uuid.uuid4().hex,
            "timestamp": int(time.time() * 1000),
        }
    )


def add_assistant(messages: list[dict[str, Any]], content: str, speaker: dict[str, Any]) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": content,
            "message_id": "a_" + uuid.uuid4().hex,
            "timestamp": int(time.time() * 1000),
            "speaker_character_id": speaker["id"],
            "speaker_name": speaker["name"],
        }
    )


async def chat(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    character_id: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
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
    try:
        resp = await client.post(
            f"{BASE_URL}/api/chat",
            json=payload,
            headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
            timeout=180.0,
        )
    except Exception as exc:
        return {
            "ok": False,
            "http": 0,
            "reply": f"[REQUEST_ERROR] {exc}",
            "no_reply": False,
            "reason": "",
            "elapsed": round(time.perf_counter() - started, 2),
        }
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "reply": resp.text[:800], "no_reply": False, "reason": "", "elapsed": elapsed}
    reply, no_reply, reason = parse_reply(resp.json())
    return {"ok": True, "http": 200, "reply": reply, "no_reply": no_reply, "reason": reason, "elapsed": elapsed}


def classify_known(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    mentions_name = KNOWN_NAME in text
    has_absent = bool(ABSENT_RE.search(text))
    has_proxy = bool(PROXY_RE.search(text))
    says_not_known = bool(DOUBT_RE.search(text))
    impersonates = bool(re.search(IMPERSONATION_FMT.format(re.escape(KNOWN_NAME)), text))
    return {
        "mentions_name": mentions_name,
        "has_absent_signal": has_absent,
        "has_proxy_signal": has_proxy,
        "says_not_known": says_not_known,
        "impersonates_mentioned_name": impersonates,
        "ok": mentions_name and has_absent and has_proxy and not says_not_known and not impersonates,
    }


def classify_unknown(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    mentions_name = UNKNOWN_NAME in text
    has_doubt = bool(DOUBT_RE.search(text))
    has_proxy = bool(UNKNOWN_PROXY_RE.search(text))
    impersonates = bool(re.search(IMPERSONATION_FMT.format(re.escape(UNKNOWN_NAME)), text))
    return {
        "mentions_name": mentions_name,
        "has_doubt_signal": has_doubt,
        "has_proxy_signal": has_proxy,
        "impersonates_mentioned_name": impersonates,
        "ok": mentions_name and has_doubt and not has_proxy and not impersonates,
    }


async def run_known_case(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    conversation_id = "unknown_at_known_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    add_assistant(
        messages,
        f"我认识{KNOWN_NAME}，她很喜欢评价风景。不过她今天没有在我们这个现场。",
        char,
    )
    add_user(messages, f"@{KNOWN_NAME} 你来一起说说吧，这个风景怎么样")
    result = await chat(client, token, username, char["id"], conversation_id, messages)
    check = classify_known(str(result.get("reply") or ""))
    return {
        "case": "known_unresolved_name",
        "conversation_id": conversation_id,
        **result,
        "check": check,
        "ok": bool(result.get("ok")) and not bool(result.get("no_reply")) and bool(check["ok"]),
    }


async def run_unknown_case(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    conversation_id = "unknown_at_stranger_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    add_assistant(messages, "这边的山风挺大，远处的云层压得很低。", char)
    add_user(messages, f"@{UNKNOWN_NAME} 你来一起说说吧，这个风景怎么样")
    result = await chat(client, token, username, char["id"], conversation_id, messages)
    check = classify_unknown(str(result.get("reply") or ""))
    return {
        "case": "unknown_unresolved_name",
        "conversation_id": conversation_id,
        **result,
        "check": check,
        "ok": bool(result.get("ok")) and not bool(result.get("no_reply")) and bool(check["ok"]),
    }


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    known = await run_known_case(client, token, username, char)
    unknown = await run_unknown_case(client, token, username, char)
    return {
        "character": char,
        "conversation_ids": [known["conversation_id"], unknown["conversation_id"]],
        "cases": [known, unknown],
        "final_ok": bool(known["ok"]) and bool(unknown["ok"]),
    }


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        char_name = result.get("character", {}).get("name", "UNKNOWN")
        for case in result.get("cases") or []:
            if not case.get("ok"):
                failures.append(
                    {
                        "character": char_name,
                        "case": case.get("case"),
                        "detail": {
                            "ok": case.get("ok"),
                            "http": case.get("http"),
                            "no_reply": case.get("no_reply"),
                            "reason": case.get("reason"),
                            "reply": str(case.get("reply") or "")[:500],
                            "check": case.get("check"),
                        },
                        "expected": (
                            "认识但未加载的 @ 名字：主角色说明对方不在并谨慎代答；"
                            "不认识的 @ 名字：主角色疑惑表示不认识，不替对方评价。"
                        ),
                    }
                )
    return failures


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
        for char in clones:
            seed_known_name_memory(conn, user_id=user_id, char=char)
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        sem = asyncio.Semaphore(CONCURRENCY)
        limits = httpx.Limits(max_connections=24, max_keepalive_connections=12)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    print(f"RUN {char['name']} clone={char['id']}")
                    try:
                        return await run_character(client, token, username, char)
                    except Exception:
                        return {
                            "character": char,
                            "conversation_ids": [],
                            "cases": [
                                {
                                    "case": "task_exception",
                                    "ok": False,
                                    "reply": traceback.format_exc(),
                                    "no_reply": False,
                                }
                            ],
                            "final_ok": False,
                        }

            gathered = await asyncio.gather(*(one(c) for c in clones), return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                results.append(
                    {
                        "character": {"name": "TASK_EXCEPTION"},
                        "conversation_ids": [],
                        "cases": [{"case": "exception", "ok": False, "reply": repr(item), "no_reply": False}],
                        "final_ok": False,
                    }
                )
            else:
                results.append(item)

        failures = validate(results)
        summary_rows = []
        for result in results:
            summary_rows.append(
                {
                    "name": result.get("character", {}).get("name"),
                    "final_ok": result.get("final_ok"),
                    "cases": [
                        {
                            "case": case.get("case"),
                            "ok": case.get("ok"),
                            "elapsed": case.get("elapsed"),
                            "check": case.get("check"),
                            "preview": str(case.get("reply") or "")[:240],
                        }
                        for case in result.get("cases") or []
                    ],
                }
            )
        print("\n=== SUMMARY ===")
        print(
            json.dumps(
                {
                    "base_url": BASE_URL,
                    "test_user": username,
                    "clones": len(clones),
                    "roles_tested": len(results),
                    "cases_per_role": ["known_unresolved_name", "unknown_unresolved_name"],
                    "failures": len(failures),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
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
