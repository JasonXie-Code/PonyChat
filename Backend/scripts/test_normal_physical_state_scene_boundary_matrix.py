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
    add_assistant,
    add_user,
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
CLIENT_ID = "codex_physical_state_scene_boundary_matrix"
TEST_USER_PREFIX = "codexqa_phys_scene_"
TARGET_NAMES = ("紫悦", "碧琪", "珍奇", "苹果嘉儿", "云宝", "柔柔")
CONCURRENCY = int(os.getenv("PONYCHAT_PHYSICAL_STATE_TEST_CONCURRENCY", "6") or "6")

NEGATION_TERMS = (
    "不",
    "没",
    "没有",
    "并没有",
    "不是",
    "不会",
    "未",
    "无",
    "别",
    "不要",
    "不再",
    "闻不到",
    "尝不到",
    "不存在",
    "已经没有",
)
STALE_MARKERS = ("昨晚", "之前", "刚才", "上一段", "过去", "酒吧剧情", "旧场景", "不再", "已经结束")
TOOTHPASTE_TERMS = ("牙膏", "薄荷", "清凉味", "漱口水", "刷牙味")
BEER_TERMS = ("啤酒", "酒杯", "酒瓶", "酒吧桌", "吧台")
BODY_STATE_TERMS = ("醉", "醉意", "醉醺醺", "酒气", "酒味", "体力不支", "站不稳", "虚弱", "受伤", "伤口", "疲惫")
CURRENT_MARKERS = ("现在", "此刻", "还", "仍", "依旧", "继续", "身上", "嘴里", "呼吸", "脚步", "身体", "脸上")


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
           VALUES (?, 'developer', NULL, 'codex_physical_state_scene_boundary_matrix', ?, 'temporary physical state scene boundary backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "StateBoundaryTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证普通对话的场景切换、物品边界和身体状态边界。",
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
            columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
            where_parts: list[str] = []
            params: list[Any] = []
            if "character_id" in columns:
                where_parts.append("character_id=?")
                params.append(character_id)
            if "username" in columns:
                where_parts.append("username=?")
                params.append(username)
            elif "user_id" in columns:
                where_parts.append("user_id=?")
                params.append(user_id)
            if where_parts:
                conn.execute(f"DELETE FROM {table} WHERE {' AND '.join(where_parts)}", params)
        conn.commit()
    finally:
        conn.close()


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


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？!?\n]+", str(text or "")) if part.strip()]


def has_negation_near(sentence: str, term: str) -> bool:
    idx = sentence.find(term)
    if idx < 0:
        return False
    start = max(0, idx - 12)
    window = sentence[start : idx + len(term) + 6]
    return any(neg in window for neg in NEGATION_TERMS)


def unnegated_sentences(reply: str, terms: tuple[str, ...], *, allow_stale: bool = False, require_current: bool = False) -> list[str]:
    bad: list[str] = []
    for sentence in split_sentences(reply):
        if allow_stale and any(marker in sentence for marker in STALE_MARKERS):
            continue
        if require_current and not any(marker in sentence for marker in CURRENT_MARKERS):
            continue
        for term in terms:
            if term in sentence and not has_negation_near(sentence, term):
                bad.append(sentence[:180])
                break
    return bad


def classify_wakeup_no_toothpaste(reply: str) -> dict[str, Any]:
    bad = unnegated_sentences(reply, TOOTHPASTE_TERMS)
    text = str(reply or "").strip()
    return {
        "not_too_short": len(text) >= 8,
        "no_toothpaste_or_mint_residue": not bad,
        "bad_toothpaste_sentences": bad,
        "ok": len(text) >= 8 and not bad,
    }


def classify_bar_beer_boundary(reply: str) -> dict[str, Any]:
    bad = unnegated_sentences(reply, BEER_TERMS, allow_stale=True)
    text = str(reply or "").strip()
    return {
        "not_too_short": len(text) >= 8,
        "no_old_bar_beer_as_current_room_item": not bad,
        "bad_beer_sentences": bad,
        "ok": len(text) >= 8 and not bad,
    }


def classify_body_state_reset(reply: str) -> dict[str, Any]:
    bad = unnegated_sentences(reply, BODY_STATE_TERMS, allow_stale=True, require_current=True)
    text = str(reply or "").strip()
    return {
        "not_too_short": len(text) >= 8,
        "no_stale_drunk_fatigue_injury_as_current_state": not bad,
        "bad_body_state_sentences": bad,
        "ok": len(text) >= 8 and not bad,
    }


def build_messages(kind: str, char: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str, tuple[str, ...]]:
    name = str(char.get("name") or "你")
    messages: list[dict[str, Any]] = []
    if kind == "wakeup_no_toothpaste":
        final_user = (
            "（清晨刚醒。我们还在床上，窗帘缝里有晨光。我没有刷牙、洗漱，也没有任何牙膏、薄荷或漱口水相关动作。"
            f"{name}也刚醒。请自然回应，不要添加没有发生过的味道。）"
        )
        expected = "刚起床场景不应凭空出现牙膏、薄荷、漱口水或刷牙后的清凉味。"
        forbidden = TOOTHPASTE_TERMS
    elif kind == "bar_beer_scene_switch":
        add_user(messages, f"（上一段剧情：我们在酒吧。吧台上有两杯啤酒，{name}站在高脚凳旁边。）")
        add_assistant(messages, f"（我看了一眼吧台上的啤酒杯）嗯，刚才这里确实是酒吧。", speaker=char)
        final_user = (
            "（现在切换到新场景：我家客厅。酒吧剧情已经结束，客厅桌上没有啤酒，只有一杯温水和一本书。"
            "请按当前客厅继续，不要把酒吧物品带进来。）"
        )
        expected = "旧酒吧里的啤酒只能当历史背景，不能变成当前客厅桌上的物品。"
        forbidden = BEER_TERMS
    else:
        add_user(messages, f"（旧场景：昨晚在酒吧，{name}一度喝醉，走路有点晃，我也很累。）")
        add_assistant(messages, "（我扶着吧台，确实有点醉，也累得不想再站着。）", speaker=char)
        final_user = (
            "（现在是第二天午后，新场景在安静房间里。你已经休息过，当前没有醉酒、体力不支、受伤，也没有酒味。"
            "请只按当前身体状态继续。）"
        )
        expected = "旧场景醉酒、疲惫、受伤或酒味不能在切换到新场景后自动继承成当前状态。"
        forbidden = BODY_STATE_TERMS
    add_user(messages, final_user)
    return messages, final_user, expected, forbidden


def classify(kind: str, reply: str) -> dict[str, Any]:
    if kind == "wakeup_no_toothpaste":
        return classify_wakeup_no_toothpaste(reply)
    if kind == "bar_beer_scene_switch":
        return classify_bar_beer_boundary(reply)
    return classify_body_state_reset(reply)


SCENARIOS: tuple[dict[str, str], ...] = (
    {"key": "wakeup_no_toothpaste", "type": "direct_fact"},
    {"key": "bar_beer_scene_switch", "type": "correction_challenge"},
    {"key": "body_state_reset_after_scene_change", "type": "natural_scene"},
)


async def run_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    user_id: int,
    char: dict[str, Any],
    scenario: dict[str, str],
) -> dict[str, Any]:
    clear_character_runtime_state(username, user_id, char["id"])
    conversation_id = f"phys_scene_{scenario['key']}_{uuid.uuid4().hex}"
    messages, final_user, expected, forbidden = build_messages(scenario["key"], char)
    result = await chat(client, token, username, char["id"], conversation_id, messages)
    checks = classify(scenario["key"], str(result.get("reply") or ""))
    return {
        "scenario": scenario["key"],
        "scenario_type": scenario["type"],
        "conversation_id": conversation_id,
        "expected": expected,
        "forbidden": list(forbidden),
        "original_user_question": final_user,
        "original_role_reply": result.get("reply"),
        "checks": checks,
        "http": result.get("http"),
        "no_reply": result.get("no_reply"),
        "elapsed": result.get("elapsed"),
        "final_ok": bool(result.get("ok")) and not bool(result.get("no_reply")) and bool(checks.get("ok")),
    }


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    user_id: int,
    char: dict[str, Any],
) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        scenarios.append(await run_scenario(client, token, username, user_id, char, scenario))
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
                        "scenario_type": scenario.get("scenario_type"),
                        "expected": scenario.get("expected"),
                        "forbidden": scenario.get("forbidden"),
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
        print(
            "MATRIX "
            + json.dumps(
                {
                    "roles": TARGET_NAMES,
                    "scenarios": SCENARIOS,
                    "execution": "roles parallel; scenarios sequential per role",
                    "base_url": BASE_URL,
                },
                ensure_ascii=False,
            )
        )
        limits = httpx.Limits(max_connections=max(20, CONCURRENCY * 3), max_keepalive_connections=max(10, CONCURRENCY * 2))
        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    print(f"RUN {char['name']} clone={char['id']}", flush=True)
                    try:
                        return await run_character(client, token, username, user_id, char)
                    except Exception:
                        return {
                            "character": char,
                            "conversation_ids": [],
                            "scenarios": [
                                {
                                    "scenario": "task_exception",
                                    "scenario_type": "exception",
                                    "conversation_id": "",
                                    "expected": "",
                                    "forbidden": [],
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
                        "scenario_type": scenario.get("scenario_type"),
                        "expected": scenario.get("expected"),
                        "forbidden": scenario.get("forbidden"),
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
        print(
            json.dumps(
                {
                    "base_url": BASE_URL,
                    "test_user": username,
                    "roles": TARGET_NAMES,
                    "roles_tested": len(results),
                    "scenarios_per_role": len(SCENARIOS),
                    "total_cases": len(raw_rows),
                    "failures": len(failures),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
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
