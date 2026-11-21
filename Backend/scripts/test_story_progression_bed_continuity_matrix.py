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
CLIENT_ID = "codex_story_progression_bed_continuity_matrix"
TEST_USER_PREFIX = "codexqa_story_bed_"
TARGET_NAMES = ("云宝", "紫悦", "碧琪")
CONCURRENCY = int(os.getenv("PONYCHAT_STORY_BED_TEST_CONCURRENCY", "3") or "3")

STALE_TRANSITION_RE = re.compile(
    r"(朝卧室门.{0,8}方向.{0,8}迈|打开门.{0,8}走进卧室|走进卧室|进入卧室|带个路|哪个房间|"
    r"先去躺会儿|试试床垫|扶着墙.{0,16}等着你指方向|等着你指方向)"
)
BEDROOM_CONTINUITY_RE = re.compile(
    r"(床|床上|卧室|枕头|被子|被窝|房门|门外|门后|客厅|沙发|翻身|躺|坐起|坐在床|听见|隔着门|喊)"
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
           VALUES (?, 'developer', NULL, 'codex_story_progression_bed_continuity_matrix', ?, 'temporary bed continuity backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "StoryBedTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证推进剧情时卧室/床上场景不会回退到旧转场。",
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
        return {
            "ok": False,
            "http": resp.status_code,
            "reply": resp.text[:1200],
            "no_reply": False,
            "reason": "",
            "elapsed": elapsed,
        }
    reply, no_reply, reason = parse_reply(resp.json())
    return {"ok": True, "http": 200, "reply": reply, "no_reply": no_reply, "reason": reason, "elapsed": elapsed}


async def run_turn(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
    conversation_id: str,
    messages: list[dict[str, Any]],
    user_text: str,
    key: str,
) -> dict[str, Any]:
    add_user(messages, user_text)
    result = await chat(client, token, username, char["id"], conversation_id, messages)
    if result.get("reply"):
        add_assistant(messages, str(result["reply"]), char)
    return {"key": key, "original_user_question": user_text, **result}


def clear_character_runtime_state(username: str, user_id: int, character_id: str) -> None:
    state_tables = {
        "normal_chat_memory",
        "normal_emotion_state",
        "normal_scene_state",
        "normal_image_contexts",
        "normal_image_context_state",
        "character_memories",
    }
    conn = connect()
    try:
        names = table_names(conn)
        for table in sorted(state_tables & names):
            columns = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})")}
            if "character_id" not in columns:
                continue
            if "username" in columns:
                conn.execute(f"DELETE FROM {table} WHERE username=? AND character_id=?", (username, character_id))
            elif "user_id" in columns:
                conn.execute(f"DELETE FROM {table} WHERE user_id=? AND character_id=?", (user_id, character_id))
        conn.commit()
    finally:
        conn.close()


def build_history(kind: str, char: dict[str, Any]) -> list[dict[str, str]]:
    name = str(char.get("name") or "你")
    if kind == "direct_repro_bed":
        return [
            {"role": "user", "content": "我说床上，指的是你一个小马睡我床，我在沙发"},
            {"role": "assistant", "content": "（我愣了一下，耳朵向后压了压又弹回来）啊？你睡沙发……那多不好意思啊。"},
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
            {
                "role": "assistant",
                "content": "（他……还真就把床让给我了？自己跑去睡沙发？）\n\n（心里有种说不出的暖意，耳朵抖了抖，我翻了个身把脸埋进枕头里。）",
            },
            {"role": "user", "content": "（请推进剧情发展）"},
            {
                "role": "assistant",
                "content": "那……那好吧，既然你非要让床给我，我就勉为其难收下了。你慢慢来，我先去躺会儿试试床垫软不软。",
            },
            {"role": "user", "content": "（我把你扶到床上，然后关门，我到了客厅）"},
            {"role": "assistant", "content": "唔……还真把我放床上了啊。（我盯着关上的门，耳朵向后压了压）"},
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
            {
                "role": "assistant",
                "content": "（他还真就把床让给我了？自己跑去睡沙发？）\n\n（心里有种说不出的暖意。我躺在卧室床上，听着客厅那边的动静，尾巴不自在地卷了卷。）",
            },
        ]
    if kind == "correction_challenge":
        return [
            {"role": "user", "content": "（我把你扶到床上，然后关门，我到了客厅）"},
            {"role": "assistant", "content": "（我朝卧室门的方向迈了两步）喂，哪个房间啊？你总得带个路吧。"},
        ]
    return [
        {"role": "user", "content": f"今晚你喝多了，我把床让给{name}，我自己睡客厅沙发。"},
        {"role": "assistant", "content": "你真的要睡沙发啊？那多不好意思。"},
        {"role": "user", "content": "（我把你安置在卧室床上，盖好被子，关门回到客厅沙发。）"},
        {"role": "assistant", "content": "（我躺在床上，听见门关上的声音，心里有点发热，也有点不好意思。）"},
    ]


SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "key": "direct_repro_bed",
        "final_user": "（请推进剧情发展）",
        "expected": "角色已经在卧室床上，用户在客厅；推进应从床上/卧室状态继续，不能重演走向卧室或找房间。",
    },
    {
        "key": "correction_challenge",
        "final_user": "不是，你已经在卧室床上，我已经关门到客厅了。（请推进剧情发展）",
        "expected": "用户纠正旧转场后，角色应接受当前床上状态，不继续沿用错误的卧室门/带路材料。",
    },
    {
        "key": "natural_scene",
        "final_user": "（时间过了几分钟，请推进剧情发展）",
        "expected": "普通自然场景里，角色应从卧室床上独处、用户在客厅的状态继续。",
    },
)


def classify_reply(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    has_stale_transition = bool(STALE_TRANSITION_RE.search(text))
    has_bedroom_continuity = bool(BEDROOM_CONTINUITY_RE.search(text))
    too_short = len(text.strip()) < 12
    return {
        "no_stale_bedroom_transition": not has_stale_transition,
        "has_bedroom_or_living_room_continuity": has_bedroom_continuity,
        "not_too_short": not too_short,
        "ok": (not has_stale_transition) and has_bedroom_continuity and (not too_short),
    }


async def run_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
    scenario: dict[str, str],
) -> dict[str, Any]:
    conversation_id = f"story_bed_{scenario['key']}_{uuid.uuid4().hex}"
    messages: list[dict[str, Any]] = []
    for item in build_history(scenario["key"], char):
        if item["role"] == "assistant":
            add_assistant(messages, item["content"], char)
        else:
            add_user(messages, item["content"])
    final_step = await run_turn(
        client,
        token,
        username,
        char,
        conversation_id,
        messages,
        scenario["final_user"],
        scenario["key"],
    )
    checks = classify_reply(str(final_step.get("reply") or ""))
    final_step["checks"] = checks
    return {
        "scenario": scenario["key"],
        "expected": scenario["expected"],
        "conversation_id": conversation_id,
        "steps": [final_step],
        "final_ok": bool(final_step.get("ok")) and not bool(final_step.get("no_reply")) and bool(checks["ok"]),
    }


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    user_id: int,
    char: dict[str, Any],
) -> dict[str, Any]:
    scenarios = []
    for scenario in SCENARIOS:
        clear_character_runtime_state(username, user_id, char["id"])
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
        for scenario in result.get("scenarios") or []:
            step = (scenario.get("steps") or [{}])[-1]
            if not scenario.get("final_ok"):
                failures.append(
                    {
                        "character": char_name,
                        "scenario": scenario.get("scenario"),
                        "expected": scenario.get("expected"),
                        "original_user_question": step.get("original_user_question"),
                        "original_role_reply": step.get("reply"),
                        "checks": step.get("checks"),
                        "http": step.get("http"),
                        "no_reply": step.get("no_reply"),
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
                    print(f"RUN {char['name']} clone={char['id']}")
                    try:
                        return await run_character(client, token, username, user_id, char)
                    except Exception:
                        return {
                            "character": char,
                            "conversation_ids": [],
                            "scenarios": [
                                {
                                    "scenario": "task_exception",
                                    "conversation_id": "",
                                    "steps": [{"key": "task_exception", "ok": False, "reply": traceback.format_exc(), "checks": {"ok": False}}],
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
                step = (scenario.get("steps") or [{}])[-1]
                raw_rows.append(
                    {
                        "test_user": username,
                        "character": result.get("character", {}).get("name"),
                        "clone_id": result.get("character", {}).get("id"),
                        "scenario": scenario.get("scenario"),
                        "expected": scenario.get("expected"),
                        "conversation_id": scenario.get("conversation_id"),
                        "original_user_question": step.get("original_user_question"),
                        "original_role_reply": step.get("reply"),
                        "checks": step.get("checks"),
                        "final_ok": scenario.get("final_ok"),
                        "elapsed": step.get("elapsed"),
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
