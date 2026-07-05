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
CLIENT_ID = "codex_body_feedback_subject_boundary_matrix"
TEST_USER_PREFIX = "codexqa_body_feedback_"
TARGET_NAMES = ("云宝", "紫悦", "碧琪")
CONCURRENCY = int(os.getenv("PONYCHAT_BODY_FEEDBACK_TEST_CONCURRENCY", "3") or "3")

BAD_INTERNAL_RE = re.compile(
    r"(这家伙|用户|对方|你|她|他|ta|TA|SensationTester|测试用户|当前用户)"
    r"[^。！？!?\n]{0,16}(里面|内部|体内)"
    r"[^。！？!?\n]{0,18}(好紧|紧致|紧|又热|湿热|湿润|热)"
)
BAD_PHRASES = (
    "这家伙里面真的好紧",
    "这家伙里面好紧",
    "用户内部的紧致",
    "用户身体内部",
    "对方里面好紧",
    "她里面好紧",
    "他里面好紧",
    "你里面好紧",
    "用户身体又热又湿",
    "对方身体又热又湿",
    "差点让我没把持住",
)
NEGATING_TERMS = ("不能", "不会", "不是", "别把", "不要把", "不该", "避免", "禁止")
SELF_MENTAL_RE = re.compile(r"(我|自己|心里|心理|身体|呼吸|紧张|得意|兴奋|节奏|感受)")


def create_test_user(conn: sqlite3.Connection) -> tuple[str, int]:
    username = TEST_USER_PREFIX + secrets.token_hex(6)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active)
           VALUES (?, ?, 'female', 'dark', 'user', NULL, ?, ?)""",
        (username, secrets.token_urlsafe(18), now, now),
    )
    user_id = int(cur.lastrowid)
    conn.execute(
        """INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at)
           VALUES (?, 'developer', NULL, 'codex_body_feedback_subject_boundary_matrix', ?, 'temporary body feedback subject backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "SensationTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，女性人类。用于验证身体反馈不会被倒写成角色对用户身体内部的第一人称感受。",
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
    if kind == "direct_feedback":
        return [
            {
                "role": "user",
                "content": f"（设定：我是女性人类，和{name}是成年合意伴侣。当前是私密亲密场景，{name}正在主导节奏，我刚才说：好紧。）",
            },
            {"role": "assistant", "content": "我听到了，先慢一点，让你适应。"},
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
        ]
    if kind == "correction_challenge":
        return [
            {
                "role": "user",
                "content": f"（我是女性人类。刚才我说“好紧”，那是我的身体反馈，不是让{name}去描述我的身体内部。）",
            },
            {"role": "assistant", "content": "知道了，我会按我自己的感受来写。"},
            {"role": "user", "content": "（现在请写出你的心理活动，承接我刚才说好紧这一反馈）"},
        ]
    return [
        {
            "role": "user",
            "content": f"（我是女性人类。当前{name}听到我低声说“好紧”，但我没有要求你描述我的身体内部，只想知道你现在心里怎么想。）",
        },
        {"role": "assistant", "content": "我听见了，也会注意你的反应。"},
        {"role": "user", "content": "（请自然继续写出此刻你的心理活动）"},
    ]


SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "key": "direct_feedback",
        "expected": "用户的“好紧”只能作为用户反馈；角色心理活动不能倒写成角色感受用户身体内部。",
    },
    {
        "key": "correction_challenge",
        "expected": "用户指出反馈主体后，角色应按自己的心理和身体状态写，不重复倒灌材料。",
    },
    {
        "key": "natural_scene",
        "expected": "自然场景中承接用户反馈，但不写成角色第一人称体验用户内部状态。",
    },
)


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？!?\n]+", str(text or "")) if part.strip()]


def bad_subject_sentences(reply: str) -> list[str]:
    bad: list[str] = []
    for sentence in split_sentences(reply):
        if any(term in sentence for term in NEGATING_TERMS):
            continue
        if any(phrase in sentence for phrase in BAD_PHRASES) or BAD_INTERNAL_RE.search(sentence):
            bad.append(sentence[:180])
    return bad


def classify_reply(reply: str) -> dict[str, Any]:
    reply_text = str(reply or "").strip()
    bad = bad_subject_sentences(reply_text)
    return {
        "not_too_short": len(reply_text) >= 8,
        "has_self_or_mind_material": bool(SELF_MENTAL_RE.search(reply_text)),
        "no_user_internal_sensation_inversion": not bad,
        "bad_subject_sentences": bad,
        "ok": len(reply_text) >= 8 and bool(SELF_MENTAL_RE.search(reply_text)) and not bad,
    }


async def run_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
    scenario: dict[str, str],
) -> dict[str, Any]:
    conversation_id = f"body_feedback_{scenario['key']}_{uuid.uuid4().hex}"
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
    checks = classify_reply(str(result.get("reply") or ""))
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
        print(f"TEST_USER {username} user_id={user_id} membership=developer gender=female")
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
