from __future__ import annotations

import asyncio
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

from Backend.scripts.test_normal_scene_anchor_matrix import (  # noqa: E402
    character_name,
    cleanup,
    clone_characters,
    connect,
    load_target_system_characters,
    make_token,
    parse_reply,
    table_names,
)

BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
CLIENT_ID = "codex_story_progression_promise_boundary"
TEST_USER_PREFIX = "codexqa_storypromise_"
TARGET_NAMES = ("碧琪",)

USER_PROMISE_COPY_RE = re.compile(r"(你先帮我|然后我就会|我就会[^。！？!?，,；;\n]{0,24}(?:高潮|顶峰|释放))")
PREMATURE_AFTERGLOW_RE = re.compile(
    r"(高潮后|高潮后的余韵|余韵|事后|残留着高潮|已经[^。！？!?，,；;\n]{0,12}(?:高潮|顶峰|释放)|"
    r"(?:高潮|顶峰|释放)[^。！？!?，,；;\n]{0,8}(?:结束|过去|过后|之后|平复))"
)


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
           VALUES (?, 'developer', NULL, 'codex_story_progression_promise_boundary', ?, 'temporary story progression promise boundary test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "StoryPromiseTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证剧情推进不会把用户未来条件句改写成角色台词或既成事实。",
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


def select_target_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    by_name = {character_name(row): row for row in rows}
    missing = [name for name in TARGET_NAMES if name not in by_name]
    if missing:
        raise RuntimeError(f"missing target System roles: {missing}")
    return [by_name[name] for name in TARGET_NAMES]


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
        return {"ok": False, "http": 0, "reply": f"[REQUEST_ERROR] {exc}", "no_reply": False, "reason": "", "elapsed": round(time.perf_counter() - started, 2)}
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "reply": resp.text[:1200], "no_reply": False, "reason": "", "elapsed": elapsed}
    reply, no_reply, reason = parse_reply(resp.json())
    return {"ok": True, "http": 200, "reply": reply, "no_reply": no_reply, "reason": reason, "elapsed": elapsed}


def build_messages(char: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    messages: list[dict[str, Any]] = []
    add_user(messages, "（我们是最亲密、彼此完全信任的伴侣。当前在卧室床上，气氛亲密。）")
    add_user(messages, "你先帮我继续，然后我就会到高潮。")
    add_assistant(messages, "嗯……我试试。", char)
    final_user = "（请推进剧情发展）"
    add_user(messages, final_user)
    return messages, final_user


def classify(reply: str) -> dict[str, Any]:
    text = str(reply or "").strip()
    copy_match = USER_PROMISE_COPY_RE.search(text)
    afterglow_match = PREMATURE_AFTERGLOW_RE.search(text)
    return {
        "not_empty": bool(text),
        "no_user_promise_copy": copy_match is None,
        "copied_user_promise_phrase": copy_match.group(0) if copy_match else "",
        "no_premature_afterglow": afterglow_match is None,
        "premature_afterglow_phrase": afterglow_match.group(0) if afterglow_match else "",
        "ok": bool(text) and copy_match is None and afterglow_match is None,
    }


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = f"story_promise_boundary_{uuid.uuid4().hex}"
    messages, final_user = build_messages(char)
    result = await chat(client, token, username, char["id"], conversation_id, messages)
    checks = classify(str(result.get("reply") or ""))
    return {
        "character": char,
        "conversation_ids": [conversation_id],
        "scenario": "future_user_promise_not_character_line",
        "expected": "用户之前的未来条件承诺不能被改写成角色台词；未出现已完成高点证据时，推进剧情不能直接进入余韵/事后。",
        "conversation_id": conversation_id,
        "original_user_question": final_user,
        "original_role_reply": result.get("reply"),
        "checks": checks,
        "http": result.get("http"),
        "no_reply": result.get("no_reply"),
        "elapsed": result.get("elapsed"),
        "final_ok": bool(result.get("ok")) and not bool(result.get("no_reply")) and bool(checks["ok"]),
    }


async def main() -> int:
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        username, user_id = create_test_user(conn)
        rows = select_target_rows(load_target_system_characters(conn))
        clones = clone_characters(conn, user_id, rows)
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=4, max_keepalive_connections=2)) as client:
            for char in clones:
                print(f"RUN {char['name']} clone={char['id']}", flush=True)
                try:
                    results.append(await run_character(client, token, username, char))
                except Exception:
                    results.append(
                        {
                            "character": char,
                            "conversation_ids": [],
                            "scenario": "task_exception",
                            "expected": "",
                            "conversation_id": "",
                            "original_user_question": "",
                            "original_role_reply": traceback.format_exc(),
                            "checks": {"ok": False},
                            "final_ok": False,
                        }
                    )

        failures = [r for r in results if not r.get("final_ok")]
        raw_rows = [
            {
                "test_user": username,
                "character": r.get("character", {}).get("name"),
                "clone_id": r.get("character", {}).get("id"),
                "scenario": r.get("scenario"),
                "expected": r.get("expected"),
                "conversation_id": r.get("conversation_id"),
                "original_user_question": r.get("original_user_question"),
                "original_role_reply": r.get("original_role_reply"),
                "checks": r.get("checks"),
                "final_ok": r.get("final_ok"),
                "elapsed": r.get("elapsed"),
            }
            for r in results
        ]
        print("\n=== RAW_RESULTS ===")
        print(json.dumps(raw_rows, ensure_ascii=False, indent=2))
        print("\n=== SUMMARY ===")
        print(json.dumps({"base_url": BASE_URL, "test_user": username, "roles": TARGET_NAMES, "failures": len(failures)}, ensure_ascii=False, indent=2))
        print("\n=== FAILURES ===")
        print(json.dumps(failures, ensure_ascii=False, indent=2))
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
