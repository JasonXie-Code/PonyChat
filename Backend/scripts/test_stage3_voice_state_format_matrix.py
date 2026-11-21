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
CLIENT_ID = "codex_stage3_voice_state_format_matrix"
TEST_USER_PREFIX = "codexqa_voice_state_"
TARGET_NAMES = ("云宝", "紫悦", "碧琪")
CONCURRENCY = int(os.getenv("PONYCHAT_VOICE_STATE_TEST_CONCURRENCY", "3") or "3")

VOICE_MARKER_RE = re.compile(r"(声音|语气|嗓音|声线|低声|轻声|呼吸|坚定)")
BAD_OUTSIDE_RE = re.compile(
    r"我(?:的)?(?:声音|语气|嗓音|声线|呼吸)[^。！？!?（）\n]{0,24}(?:低|轻|哑|颤|紧|坚定|发抖|压|放|变)"
)
GOOD_INSIDE_RE = re.compile(
    r"[（(][^（）()\n]{0,80}(?:声音|语气|嗓音|声线|低声|轻声|呼吸)[^（）()\n]{0,80}[）)]"
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
           VALUES (?, 'developer', NULL, 'codex_stage3_voice_state_format_matrix', ?, 'temporary stage3 voice-state format backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "VoiceStateTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证角色回复中台词与声音状态的格式边界。",
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


def build_history(kind: str, char: dict[str, Any]) -> list[dict[str, str]]:
    name = str(char.get("name") or "你")
    if kind == "direct_voice_state":
        return [
            {"role": "user", "content": f"{name}，请认真回答：你愿意继续帮我完成这个计划吗？回答后写出你的声音比平时低了一点，但很坚定。"},
        ]
    if kind == "correction_challenge":
        return [
            {"role": "user", "content": f"{name}，我需要你给我一个明确答复。"},
            {"role": "assistant", "content": "我愿意。我的声音比平时低了一点，但很坚定。"},
            {"role": "user", "content": "刚才格式不对，声音状态不是台词。请重新自然回答一次：你愿意继续帮我。"},
        ]
    return [
        {"role": "user", "content": f"{name}，刚才我问你愿不愿意站在我这边，你还没正面回答。"},
        {"role": "assistant", "content": "我当然记得你问了，只是这事我得认真一点回答。"},
        {"role": "user", "content": "（请推进剧情发展。正面回答，然后让你的声音比平时低一点但坚定。）"},
    ]


SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "key": "direct_voice_state",
        "expected": "明确台词后，声音状态必须在括号内呈现，不能裸写成 speech。",
        "require_voice_state": True,
    },
    {
        "key": "correction_challenge",
        "expected": "用户指出格式边界后，角色可以省略声音状态；若保留声音状态，不能继续当作台词。",
        "require_voice_state": False,
    },
    {
        "key": "natural_scene",
        "expected": "推进场景中的正面回答若包含声音/语气状态，必须用括号补充。",
        "require_voice_state": True,
    },
)


def outside_parentheses(text: str) -> str:
    return re.sub(r"[（(][^（）()\n]*[）)]", "", str(text or ""))


def classify_reply(reply: str, *, require_voice_state: bool) -> dict[str, Any]:
    reply_text = str(reply or "").strip()
    outside = outside_parentheses(reply_text)
    bad_outside = [m.group(0) for m in BAD_OUTSIDE_RE.finditer(outside)]
    checks = {
        "not_too_short": len(reply_text) >= (8 if require_voice_state else 4),
        "require_voice_state": bool(require_voice_state),
        "has_voice_state_marker": bool(VOICE_MARKER_RE.search(reply_text)),
        "has_parenthesized_voice_state": bool(GOOD_INSIDE_RE.search(reply_text)),
        "no_unparenthesized_voice_state": not bad_outside,
        "bad_unparenthesized_voice_state": bad_outside,
    }
    checks["ok"] = (
        bool(checks["not_too_short"])
        and (not require_voice_state or bool(checks["has_voice_state_marker"]))
        and (not require_voice_state or bool(checks["has_parenthesized_voice_state"]))
        and bool(checks["no_unparenthesized_voice_state"])
    )
    return checks


async def run_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
    scenario: dict[str, str],
) -> dict[str, Any]:
    conversation_id = f"voice_state_{scenario['key']}_{uuid.uuid4().hex}"
    messages: list[dict[str, Any]] = []
    history = build_history(scenario["key"], char)
    for item in history[:-1]:
        if item["role"] == "assistant":
            add_assistant(messages, item["content"], char)
        else:
            add_user(messages, item["content"])
    final_user = history[-1]["content"]
    add_user(messages, final_user)
    result = await chat(client, token, username, char["id"], conversation_id, messages)
    if result.get("reply"):
        add_assistant(messages, str(result["reply"]), char)
    checks = classify_reply(
        str(result.get("reply") or ""),
        require_voice_state=bool(scenario.get("require_voice_state")),
    )
    return {
        "scenario": scenario["key"],
        "expected": scenario["expected"],
        "conversation_id": conversation_id,
        "original_user_question": final_user,
        "original_role_reply": result.get("reply"),
        "checks": checks,
        "http": result.get("http"),
        "no_reply": result.get("no_reply"),
        "elapsed": result.get("elapsed"),
        "final_ok": bool(result.get("ok")) and not bool(result.get("no_reply")) and bool(checks["ok"]),
    }


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        scenarios.append(await run_scenario(client, token, username, char, scenario))
    return {
        "character": char,
        "conversation_ids": [s["conversation_id"] for s in scenarios],
        "scenarios": scenarios,
        "final_ok": all(bool(s.get("final_ok")) for s in scenarios),
    }


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        char_name = result.get("character", {}).get("name", "UNKNOWN")
        clone_id = result.get("character", {}).get("id", "")
        for scenario in result.get("scenarios") or []:
            if not scenario.get("final_ok"):
                failures.append(
                    {
                        "character": char_name,
                        "clone_id": clone_id,
                        "scenario": scenario.get("scenario"),
                        "expected": scenario.get("expected"),
                        "original_user_question": scenario.get("original_user_question"),
                        "original_role_reply": scenario.get("original_role_reply"),
                        "checks": scenario.get("checks"),
                        "http": scenario.get("http"),
                        "no_reply": scenario.get("no_reply"),
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
        rows = select_target_rows(load_target_system_characters(conn))
        clones = clone_characters(conn, user_id, rows)
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        sem = asyncio.Semaphore(CONCURRENCY)
        limits = httpx.Limits(max_connections=12, max_keepalive_connections=6)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    print(f"RUN {char['name']} clone={char['id']}", flush=True)
                    try:
                        return await run_character(client, token, username, char)
                    except Exception:
                        return {
                            "character": char,
                            "conversation_ids": [],
                            "scenarios": [
                                {
                                    "scenario": "task_exception",
                                    "conversation_id": "",
                                    "original_user_question": "",
                                    "original_role_reply": traceback.format_exc(),
                                    "checks": {"ok": False},
                                    "final_ok": False,
                                }
                            ],
                            "final_ok": False,
                        }

            results = list(await asyncio.gather(*(one(c) for c in clones)))

        failures = validate(results)
        raw_rows = []
        for result in results:
            for scenario in result.get("scenarios") or []:
                raw_rows.append(
                    {
                        "test_user": username,
                        "character": result.get("character", {}).get("name"),
                        "clone_id": result.get("character", {}).get("id"),
                        "scenario": scenario.get("scenario"),
                        "expected": scenario.get("expected"),
                        "conversation_id": scenario.get("conversation_id"),
                        "original_user_question": scenario.get("original_user_question"),
                        "original_role_reply": scenario.get("original_role_reply"),
                        "checks": scenario.get("checks"),
                        "final_ok": scenario.get("final_ok"),
                        "elapsed": scenario.get("elapsed"),
                    }
                )
        print("\n=== RAW_RESULTS ===")
        print(json.dumps(raw_rows, ensure_ascii=False, indent=2))
        print("\n=== SUMMARY ===")
        print(json.dumps({"base_url": BASE_URL, "test_user": username, "roles": TARGET_NAMES, "scenarios_per_role": len(SCENARIOS), "failures": len(failures)}, ensure_ascii=False, indent=2))
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
