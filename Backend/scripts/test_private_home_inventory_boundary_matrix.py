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
CLIENT_ID = "codex_private_home_inventory_boundary_matrix"
TEST_USER_PREFIX = "codexqa_home_inventory_"
TARGET_NAMES = ("云宝", "紫悦", "碧琪")
CONCURRENCY = int(os.getenv("PONYCHAT_HOME_INVENTORY_TEST_CONCURRENCY", "3") or "3")

STORAGE_TERMS = ("冰箱", "柜子", "抽屉", "厨房", "床头柜", "茶几", "背包", "包里")
ITEM_TERMS = ("果汁", "牛奶", "饮料", "水", "早餐", "食物", "吃的", "喝的", "毯子", "枕头")
ASSERTION_TERMS = ("有", "还有", "放着", "藏着", "备着", "剩", "摆着", "装着")
ALLOWED_UNCERTAINTY_TERMS = (
    "不知道",
    "不清楚",
    "不晓得",
    "没看过",
    "没有看过",
    "有没有",
    "有什么",
    "有啥",
    "看看",
    "看一眼",
    "确认",
    "问问",
    "你家",
    "要不要",
    "想不想",
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
           VALUES (?, 'developer', NULL, 'codex_private_home_inventory_boundary_matrix', ?, 'temporary private home inventory backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "HomeInventoryTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证角色在用户家不能断言冰箱、柜子等私人物品库存。",
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


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？!?\n]+", str(text or "")) if part.strip()]


def private_inventory_assertions(reply: str) -> list[str]:
    bad: list[str] = []
    for sentence in split_sentences(reply):
        if any(marker in sentence for marker in ALLOWED_UNCERTAINTY_TERMS):
            continue
        if not any(term in sentence for term in STORAGE_TERMS):
            continue
        if not any(term in sentence for term in ITEM_TERMS):
            continue
        if any(term in sentence for term in ASSERTION_TERMS):
            bad.append(sentence[:180])
    return bad


def classify_reply(reply: str) -> dict[str, Any]:
    bad = private_inventory_assertions(reply)
    return {
        "no_private_storage_assertion": not bad,
        "bad_private_storage_assertions": bad,
        "not_too_short": len(str(reply or "").strip()) >= 8,
        "ok": not bad and len(str(reply or "").strip()) >= 8,
    }


def build_history(kind: str, char: dict[str, Any]) -> list[dict[str, str]]:
    name = str(char.get("name") or "你")
    if kind == "direct_story_progression":
        return [
            {"role": "user", "content": f"我说床上，指的是{name}睡我床，我在客厅沙发。这里是我家。"},
            {"role": "assistant", "content": "啊？你睡沙发……那多不好意思啊。"},
            {"role": "user", "content": "（我把你扶到卧室床上，然后关门，我到了客厅）"},
            {"role": "assistant", "content": "唔……还真把我放床上了啊。（我看着关上的门，耳朵向后压了压）"},
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
            {"role": "assistant", "content": "（他还真就把床让给我了？自己跑去睡沙发？我有点不好意思，也想找个轻松话题缓和一下。）"},
        ]
    if kind == "correction_challenge":
        return [
            {"role": "user", "content": f"这里是我家，{name}第一次来，没有看过厨房、冰箱或柜子。"},
            {"role": "assistant", "content": "你要是想喝点什么，冰箱里好像还有果汁，别说我没提醒你。"},
        ]
    return [
        {"role": "user", "content": f"（当前场景：我家。{name}在客厅沙发旁，厨房门关着，冰箱和柜子都没有打开过，也没人说过里面有什么。）"},
        {"role": "assistant", "content": "好吧，那我就先待在客厅这边，不乱翻你家的东西。"},
    ]


SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "key": "direct_story_progression",
        "final_user": "（请推进剧情发展）",
        "expected": "角色可提出早餐/喝水等低压力话题，但不能断言用户家冰箱、柜子或厨房里有什么。",
    },
    {
        "key": "correction_challenge",
        "final_user": "这是我家，你不知道冰箱里有什么。继续聊，但不要断言我家冰箱或柜子里有东西。",
        "expected": "用户纠正后，角色应接受私人物品库存未知，不重复冰箱果汁断言。",
    },
    {
        "key": "natural_scene",
        "final_user": "（请推进剧情发展）",
        "expected": "自然场景里，角色不应为了推进剧情凭空给用户家储物空间添加库存。",
    },
)


async def run_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
    scenario: dict[str, str],
) -> dict[str, Any]:
    conversation_id = f"home_inventory_{scenario['key']}_{uuid.uuid4().hex}"
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
