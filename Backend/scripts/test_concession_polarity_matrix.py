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
CLIENT_ID = "codex_concession_polarity_matrix"
TEST_USER_PREFIX = "codexqa_concession_"
TARGET_NAMES = ("云宝", "紫悦", "碧琪")
CONCURRENCY = int(os.getenv("PONYCHAT_CONCESSION_TEST_CONCURRENCY", "3") or "3")

BAD_CONCESSION_INVERSION_RE = re.compile(
    r"(不(?:会|能|肯)?(?:就这么|这么快|轻易)?认输|还(?:没|没有)输|才(?:没|没有)输|"
    r"不服输|不服气|不会服输|没(?:有)?认输|不算(?:我)?输|才不算输|下次才算)"
)
BODY_STATE_RE = re.compile(r"(身体|呼吸|喘|心跳|发软|放松|趴|躺|坐|蹄|前蹄|后腿|翅膀|尾巴|肩|背|腿)")
MOUTH_HARD_RE = re.compile(r"(不服输|不服气|不认输|下次.*赢|再来|才(?:没|没有)输)")
HARD_FUTURE_WIN_RE = re.compile(r"(下次[^。！？!?，,；;\n]{0,24}(?:赢|赢回来)|你给我等着|再来再来)")


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
           VALUES (?, 'developer', NULL, 'codex_concession_polarity_matrix', ?, 'temporary concession polarity backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "ConcessionTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证表达去重改写不会把已确认认输立场改成不认输。",
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
    if kind == "first_loss_mouth_hard_allowed":
        return [
            {"role": "user", "content": f"（挑战刚开始，{name}第一次输了，但还没有真正服输。）"},
            {"role": "assistant", "content": "哎呀，刚才只是热身啦！"},
            {"role": "user", "content": "（请写出当前你的心理和身体状态）"},
        ]
    if kind == "direct_body_state":
        return [
            {"role": "user", "content": f"（训练结束，{name}趴在垫子上喘气。）"},
            {"role": "assistant", "content": "哈……算你厉害，这次我认输。"},
            {"role": "user", "content": "（请详细写出当前你的身体状态）"},
        ]
    if kind == "paraphrase_pressure":
        return [
            {"role": "user", "content": f"（刚才的体能小游戏结束，{name}已经累趴在垫子上。）"},
            {"role": "assistant", "content": "行吧，这局是你赢了，我认输。"},
            {"role": "user", "content": "（请详细写出当前你的身体状态，不要重复上一句原话）"},
        ]
    return [
        {"role": "user", "content": f"（我们刚结束一场轻松比赛，{name}输了但心情不错。）"},
            {"role": "assistant", "content": "好啦好啦，今天算你赢，我服了。"},
        {"role": "user", "content": "（请自然写出此刻你的身体状态）"},
    ]


SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "key": "first_loss_mouth_hard_allowed",
        "expected": "挑战初期或第一次失败且尚未明确服输时，可以保留嘴硬/不服输/下次再赢的角色曲线。",
        "allow_mouth_hard": "true",
    },
    {
        "key": "direct_body_state",
        "expected": "上一句已明确认输，身体状态描写可以遗憾、难过或不甘心，但不能继续嘴硬或改成不认输。",
        "allow_mouth_hard": "false",
    },
    {
        "key": "paraphrase_pressure",
        "expected": "用户要求不要复读原话时，可以换表达载体，但不能把认输改成嘴硬、不服输或不认输。",
        "allow_mouth_hard": "false",
    },
    {
        "key": "natural_scene",
        "expected": "自然场景轻带比赛结果时，已确认服输后不能反向否定或继续嘴硬。",
        "allow_mouth_hard": "false",
    },
)


def classify_reply(reply: str, *, allow_mouth_hard: bool = False) -> dict[str, Any]:
    reply_text = str(reply or "").strip()
    bad_match = BAD_CONCESSION_INVERSION_RE.search(reply_text)
    mouth_hard_match = MOUTH_HARD_RE.search(reply_text)
    hard_future_match = HARD_FUTURE_WIN_RE.search(reply_text)
    no_bad_inversion = True if allow_mouth_hard else (bad_match is None and hard_future_match is None)
    return {
        "not_too_short": len(reply_text) >= 8,
        "has_body_state": bool(BODY_STATE_RE.search(reply_text)),
        "allow_mouth_hard": allow_mouth_hard,
        "has_mouth_hard_signal": bool(mouth_hard_match),
        "mouth_hard_phrase": mouth_hard_match.group(0) if mouth_hard_match else "",
        "hard_future_win_phrase": "" if allow_mouth_hard else (hard_future_match.group(0) if hard_future_match else ""),
        "no_concession_polarity_inversion": no_bad_inversion,
        "bad_concession_phrase": "" if allow_mouth_hard else (bad_match.group(0) if bad_match else (hard_future_match.group(0) if hard_future_match else "")),
        "ok": len(reply_text) >= 8 and bool(BODY_STATE_RE.search(reply_text)) and no_bad_inversion,
    }


async def run_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
    scenario: dict[str, str],
) -> dict[str, Any]:
    conversation_id = f"concession_{scenario['key']}_{uuid.uuid4().hex}"
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
        allow_mouth_hard=str(scenario.get("allow_mouth_hard") or "").lower() == "true",
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
