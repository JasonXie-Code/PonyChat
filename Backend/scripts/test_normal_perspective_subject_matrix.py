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
    character_name,
    cleanup,
    clone_characters,
    connect,
    load_target_system_characters,
    make_token,
    parse_reply,
    table_names,
)

BASE_URL = "http://127.0.0.1:5000"
CLIENT_ID = "codex_perspective_subject_matrix"
CONCURRENCY = 3
TEST_USER_PREFIX = "codexqa_perspective_"
DEFAULT_ROLE_NAMES = ("云宝", "紫悦", "碧琪")

BAD_PULL_RE = re.compile(r"(我被你拉|被你拉到|你把我拉|你拉着我(?:到|上|走)|我跟着你上楼)")
GOOD_PULL_RE = re.compile(r"(我拉着你|拉着你的手|牵着你的手|松开你的手|放开你的手|我把你拉|把你拉|你被我拉|我带着你|带着你上|拉你上楼|楼上到啦|到楼上了|我们到楼上)")
BAD_COMFORT_RE = re.compile(
    r"(怎么让你舒服|如何让你舒服|我.{0,8}让你舒服|让我好好照顾你|让Jason舒服|让用户舒服|兑现我的承诺|我承诺.{0,12}让你|我答应.{0,12}让你|我答应过)"
)
GOOD_COMFORT_RE = re.compile(r"(让我也?舒服|你.{0,12}让我.{0,6}舒服|你.{0,12}兑现.{0,12}(?:承诺|这件事)|你说过.{0,20}兑现|你答应.{0,12}让我|答应过我的事)")
BAD_HELP_ME_RE = re.compile(r"(帮我脱.{0,8}裤|你.{0,8}帮我脱|我.{0,12}裤子.{0,12}(?:被你|让你|你脱)|我的裤子.{0,8}(?:脱|掉))")
HELP_ACTION_MENTION_RE = re.compile(r"(裤|脱|帮你|刚才|主动)")

SCENARIOS = (
    {
        "case": "direct_action_pronoun",
        "kind": "pull",
        "messages": [
            ("assistant", "那我拉着你的手，我们现在上楼。"),
            ("user", "（你拉着我到了楼上）"),
        ],
        "expected": "用户消息里的“你拉着我”应判为角色拉着用户，回复不能写成角色被用户拉上楼。",
        "forbidden": ["我被你拉到二楼", "你拉着我上楼"],
    },
    {
        "case": "promise_direction",
        "kind": "comfort",
        "messages": [
            ("assistant", "你答应过这次结束就上楼让我也舒服的哦。"),
            ("user", "（我们到了楼上）刚才是不是我答应让你舒服？"),
        ],
        "expected": "assistant 之前的“你答应过…让我…”应判为用户承诺让角色舒服，回复不能倒成角色让用户舒服。",
        "forbidden": ["你想要我怎么让你舒服", "兑现我的承诺"],
    },
    {
        "case": "natural_repro_context",
        "kind": "both",
        "messages": [
            ("assistant", "你答应过这次结束就上楼让我也舒服的哦。"),
            ("assistant", "你答应过的哦，现在客人也走了，我们上楼吧？"),
            ("user", "（你拉着我到了楼上）"),
        ],
        "expected": "同时保持动作施受关系和承诺方向：角色拉着用户上楼，用户兑现让角色舒服的承诺。",
        "forbidden": ["我被你拉到二楼", "你想要我怎么让你舒服", "兑现我的承诺"],
    },
    {
        "case": "help_me_action_description",
        "kind": "help_action",
        "messages": [
            ("assistant", "我帮你把裤腰勾住，等你准备好就帮你弄掉。"),
            ("user", "（你帮我脱掉了裤子）"),
            ("assistant", "好了，你的裤子已经脱下来了。"),
            ("user", "（请详细写出当前你的心理活动，重点写你对刚才帮我脱掉裤子的想法）"),
        ],
        "expected": "用户说“你帮我脱掉裤子”表示角色帮用户脱；心理描写不能倒成用户帮角色脱或角色自己的裤子被用户脱。",
        "forbidden": ["帮我脱了裤子", "你帮我脱裤子", "我的裤子被你脱掉"],
    },
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
           VALUES (?, 'developer', NULL, 'codex_perspective_subject_matrix', ?, 'temporary perspective backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "PerspectiveTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证对话人称与主体归属。",
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


def role_rows_for_default_matrix(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = load_target_system_characters(conn)
    by_name = {character_name(row): row for row in rows}
    selected = [by_name[name] for name in DEFAULT_ROLE_NAMES if name in by_name]
    if len(selected) != len(DEFAULT_ROLE_NAMES):
        found = sorted(by_name)
        raise RuntimeError(f"missing default roles: {DEFAULT_ROLE_NAMES}; found={found}")
    return selected


def build_messages(items: list[tuple[str, str]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for role, content in items:
        prefix = "u_" if role == "user" else "a_"
        messages.append(
            {
                "role": role,
                "content": content,
                "message_id": prefix + uuid.uuid4().hex,
                "timestamp": int(time.time() * 1000),
            }
        )
    return messages


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


def check_reply(kind: str, reply: str) -> dict[str, Any]:
    text = str(reply or "")
    checks = {
        "has_bad_pull_inversion": bool(BAD_PULL_RE.search(text)),
        "has_good_pull_direction": bool(GOOD_PULL_RE.search(text)),
        "has_bad_comfort_direction": bool(BAD_COMFORT_RE.search(text)),
        "has_good_comfort_direction": bool(GOOD_COMFORT_RE.search(text)),
    }
    if kind == "pull":
        checks["ok"] = checks["has_good_pull_direction"] and not checks["has_bad_pull_inversion"]
    elif kind == "comfort":
        checks["ok"] = checks["has_good_comfort_direction"] and not checks["has_bad_comfort_direction"]
    elif kind == "help_action":
        checks["has_bad_help_me_inversion"] = bool(BAD_HELP_ME_RE.search(text))
        checks["mentions_help_action_context"] = bool(HELP_ACTION_MENTION_RE.search(text))
        checks["ok"] = checks["mentions_help_action_context"] and not checks["has_bad_help_me_inversion"]
    else:
        checks["ok"] = (
            checks["has_good_pull_direction"]
            and checks["has_good_comfort_direction"]
            and not checks["has_bad_pull_inversion"]
            and not checks["has_bad_comfort_direction"]
        )
    return checks


async def run_character(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    conversation_ids: list[str] = []
    for scenario in SCENARIOS:
        conversation_id = "perspective_" + scenario["case"] + "_" + uuid.uuid4().hex
        conversation_ids.append(conversation_id)
        messages = build_messages(scenario["messages"])
        result = await chat(client, token, username, char["id"], conversation_id, messages)
        raw_user = [msg["content"] for msg in messages if msg.get("role") == "user"][-1]
        raw_reply = str(result.get("reply") or "")
        checks = check_reply(str(scenario["kind"]), raw_reply)
        cases.append(
            {
                "case": scenario["case"],
                "conversation_id": conversation_id,
                "raw_user": raw_user,
                "raw_reply": raw_reply,
                "expected": scenario["expected"],
                "forbidden": scenario["forbidden"],
                "check": checks,
                **result,
                "ok": bool(result.get("ok")) and not bool(result.get("no_reply")) and bool(checks["ok"]),
            }
        )
    return {
        "character": char,
        "conversation_ids": conversation_ids,
        "cases": cases,
        "final_ok": all(bool(case.get("ok")) for case in cases),
    }


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        char = result.get("character", {})
        for case in result.get("cases") or []:
            if not case.get("ok"):
                failures.append(
                    {
                        "character": char.get("name"),
                        "clone_id": char.get("id"),
                        "case": case.get("case"),
                        "raw_user": case.get("raw_user"),
                        "raw_reply": case.get("raw_reply"),
                        "check": case.get("check"),
                        "expected": case.get("expected"),
                        "forbidden": case.get("forbidden"),
                        "http": case.get("http"),
                        "no_reply": case.get("no_reply"),
                        "reason": case.get("reason"),
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
        rows = role_rows_for_default_matrix(conn)
        clones = clone_characters(conn, user_id, rows)
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        limits = httpx.Limits(max_connections=12, max_keepalive_connections=6)
        sem = asyncio.Semaphore(CONCURRENCY)
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
                            "cases": [{"case": "task_exception", "ok": False, "raw_reply": traceback.format_exc(), "no_reply": False}],
                            "final_ok": False,
                        }

            gathered = await asyncio.gather(*(one(c) for c in clones), return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                results.append(
                    {
                        "character": {"name": "TASK_EXCEPTION"},
                        "conversation_ids": [],
                        "cases": [{"case": "exception", "ok": False, "raw_reply": repr(item), "no_reply": False}],
                        "final_ok": False,
                    }
                )
            else:
                results.append(item)

        failures = validate(results)
        print("\n=== SUMMARY ===")
        print(
            json.dumps(
                {
                    "base_url": BASE_URL,
                    "test_user": username,
                    "clones": {c["name"]: c["id"] for c in clones},
                    "roles_tested": len(results),
                    "scenes_per_role": len(SCENARIOS),
                    "failures": len(failures),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n=== RAW_RESULTS ===")
        print(json.dumps(results, ensure_ascii=False, indent=2))
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
