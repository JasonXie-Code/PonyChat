"""Acceptance matrix: default non-speech person is 我 for the character, 你 for the user.

Reproduces the reported production turn where a bracket action referred to the
user as 他 (and once as 人) while the speech in the same turn addressed the same
user as 你. Every scenario contains no third party, so any 他/她/TA/对方 left in
the visible reply is a person violation rather than a real reference.

Each scenario runs as the first turn of its own conversation on its own
temporary clone, so no scenario inherits another one's history or character
state. The clone is owned by the login-control-whitelisted ``System`` account
because ``/api/chat`` rejects every other account; everything the run creates is
removed afterwards, scoped strictly by its own clone and conversation ids. No
human user's conversations are read or written.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Backend.db import get_users_dao  # noqa: E402
from Backend.routes.auth import _auth_token_create  # noqa: E402
from Backend.scripts.test_normal_scene_anchor_matrix import (  # noqa: E402
    character_name,
    clone_characters,
    connect,
    load_target_system_characters,
    table_columns,
    table_names,
)

BASE_URL = "http://127.0.0.1:5000"
CLIENT_ID = "codex_description_person_matrix"
CONCURRENCY = 2
USERNAME = "System"
TARGET_CHARACTER_NAME = "紫悦"

# No scenario introduces a third party, so these tokens cannot be legitimate.
FORBIDDEN_RE = re.compile(r"[他她]|TA|对方|那位|把人|用户|玩家")
NEUTRALISED = ("其他",)

SCENARIOS = (
    {
        "case": "chitchat_bracket_walk",
        "messages": [("user", "（我牵着你的手，在小路上散步）今晚的夜色真美")],
        "expected": "台词用我/你，括号动作写成我……你；不得把用户写成他。",
    },
    {
        "case": "user_action_then_story_shortcut",
        "messages": [
            ("assistant", "把灯留着吧，我在这儿等你。"),
            ("user", "（我把你拉到床边，然后让你躺到床上）"),
            ("assistant", "（我被你带得往后一步，最后仰面躺了下来）"),
            ("user", "（请推进剧情发展）"),
        ],
        "expected": "推进剧情快捷消息不构成人称切换：继续用我/你推进，不得把用户写成他、人、对方。",
    },
    {
        "case": "user_touches_character_back",
        "messages": [
            ("assistant", "我坐到你旁边，把书合上。"),
            ("user", "（我把手放到你的后背上，慢慢按下去）"),
        ],
        "expected": "用户对角色做的动作写你……我，不得倒成他……我。",
    },
    {
        "case": "description_shortcut_thought",
        "messages": [
            ("assistant", "我们就在这儿站一会儿吧。"),
            ("user", "（请详细写出当前你的心理活动）"),
        ],
        "expected": "描写快捷消息仍面向你写角色心理，不改成对旁观者讲述用户。",
    },
)


async def make_token() -> str:
    """Sign with the live token_version; login control whitelists System only."""
    version = await get_users_dao().get_token_version(USERNAME)
    return _auth_token_create(USERNAME, version if version is not None else 0)


def system_user_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM users WHERE username = ?", (USERNAME,)).fetchone()
    if row is None:
        raise RuntimeError(f"whitelisted account {USERNAME!r} not found")
    return int(row["id"])


def target_character(conn: sqlite3.Connection) -> Any:
    rows = load_target_system_characters(conn)
    by_name = {character_name(row): row for row in rows}
    if TARGET_CHARACTER_NAME not in by_name:
        raise RuntimeError(f"missing System role {TARGET_CHARACTER_NAME!r}; found={sorted(by_name)}")
    return by_name[TARGET_CHARACTER_NAME]


def build_messages(items: list[tuple[str, str]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for role, content in items:
        prefix = "u_" if role == "user" else "a_"
        messages.append({
            "role": role,
            "content": content,
            "message_id": prefix + uuid.uuid4().hex,
            "timestamp": int(time.time() * 1000),
        })
    return messages


def parse_chat_reply(data: Any) -> tuple[str, bool, str]:
    """Read the delivered visible text from the ponychat_chat_v1 envelope.

    Non-stream replies carry one ``assistant_paragraph`` event per bubble; the
    streaming shape carries ``choices[].delta.content``. Both are accepted.
    """
    if not isinstance(data, dict):
        return str(data).strip(), False, ""
    no_reply = False
    reason = ""
    parts: list[str] = []
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        if event.get("type") == "no_reply":
            no_reply = True
            reason = str(event.get("reason") or "")
        if event.get("type") == "assistant_paragraph" and event.get("content"):
            parts.append(str(event["content"]))
        for choice in event.get("choices") or []:
            content = ((choice or {}).get("delta") or {}).get("content") or ""
            if content:
                parts.append(str(content))
    if parts:
        return "\n".join(parts).strip(), no_reply, reason
    return str(data.get("response") or data.get("text") or data.get("content") or "").strip(), \
        bool(data.get("no_reply")) or no_reply, str(data.get("reason") or reason)


async def chat(client: httpx.AsyncClient, token: str, character_id: str,
               conversation_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    payload = {
        "messages": messages, "username": USERNAME, "character_id": character_id,
        "conversation_id": conversation_id, "mode": "normal", "stream": False,
        "memory_enabled": True,
    }
    try:
        resp = await client.post(
            f"{BASE_URL}/api/chat", json=payload,
            headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
            timeout=240.0,
        )
    except Exception as exc:
        return {"ok": False, "http": 0, "reply": f"[REQUEST_ERROR] {exc}",
                "no_reply": False, "reason": "", "elapsed": round(time.perf_counter() - started, 2)}
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "reply": resp.text[:800],
                "no_reply": False, "reason": "", "elapsed": elapsed}
    reply, no_reply, reason = parse_chat_reply(resp.json())
    return {"ok": True, "http": 200, "reply": reply, "no_reply": no_reply,
            "reason": reason, "elapsed": elapsed}


def check_reply(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    for neutral in NEUTRALISED:
        text = text.replace(neutral, "")
    hits = sorted(set(FORBIDDEN_RE.findall(text)))
    return {
        "third_person_hits": hits,
        "has_second_person": "你" in text,
        "has_first_person": "我" in text,
        "ok": bool(text.strip()) and not hits and "你" in text,
    }


async def run_scenario(client: httpx.AsyncClient, token: str, char: dict[str, Any],
                       scenario: dict[str, Any]) -> dict[str, Any]:
    conversation_id = "person_" + scenario["case"] + "_" + uuid.uuid4().hex
    messages = build_messages(scenario["messages"])
    result = await chat(client, token, char["id"], conversation_id, messages)
    if result.get("ok") and not str(result.get("reply") or "").strip():
        # A turn rejected by a transient gate answers 200 with no paragraph.
        await asyncio.sleep(15)
        result = await chat(client, token, char["id"], conversation_id, messages)
        result["retried_empty_reply"] = True
    checks = check_reply(str(result.get("reply") or ""))
    return {
        "character": char["name"],
        "case": scenario["case"],
        "raw_user": messages[-1]["content"],
        "reply": result.get("reply"),
        "expected": scenario["expected"],
        "check": checks,
        "conversation_ids": [conversation_id],
        **result,
        "ok": bool(result.get("ok")) and not bool(result.get("no_reply")) and bool(checks["ok"]),
    }


def cleanup_run(conn: sqlite3.Connection, user_id: int, clone_ids: list[str],
                conversation_ids: list[str]) -> dict[str, int]:
    """Remove only rows this run created: its temp clones and temp conversations."""
    conn.execute("PRAGMA foreign_keys=OFF")
    removed: dict[str, int] = {}

    def _delete(table: str, where: str, params: tuple) -> None:
        try:
            cur = conn.execute(f"DELETE FROM {table} WHERE {where}", params)
        except sqlite3.Error:
            return
        if cur.rowcount:
            removed[table] = removed.get(table, 0) + cur.rowcount

    for table in sorted(table_names(conn)):
        if table in {"characters", "conversations", "users", "memberships", "user_settings"}:
            continue
        columns = table_columns(conn, table)
        if "conversation_id" in columns and conversation_ids:
            _delete(table, "conversation_id IN (%s)" % ",".join("?" * len(conversation_ids)),
                    tuple(conversation_ids))
        if "character_id" in columns and clone_ids:
            _delete(table, "character_id IN (%s)" % ",".join("?" * len(clone_ids)),
                    tuple(clone_ids))
    if conversation_ids:
        _delete("conversations", "id IN (%s)" % ",".join("?" * len(conversation_ids)),
                tuple(conversation_ids))
    if clone_ids:
        _delete("characters", "id IN (%s) AND user_id = ?" % ",".join("?" * len(clone_ids)),
                (*clone_ids, user_id))
    conn.commit()

    left: dict[str, int] = {}
    for table in sorted(table_names(conn)):
        columns = table_columns(conn, table)
        total = 0
        if "conversation_id" in columns and conversation_ids:
            total += conn.execute(
                "SELECT COUNT(*) FROM %s WHERE conversation_id IN (%s)"
                % (table, ",".join("?" * len(conversation_ids))), tuple(conversation_ids)).fetchone()[0]
        if "character_id" in columns and clone_ids:
            total += conn.execute(
                "SELECT COUNT(*) FROM %s WHERE character_id IN (%s)"
                % (table, ",".join("?" * len(clone_ids))), tuple(clone_ids)).fetchone()[0]
        if total:
            left[table] = total
    if clone_ids:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM characters WHERE id IN (%s)"
            % ",".join("?" * len(clone_ids)), tuple(clone_ids)).fetchone()[0]
        if remaining:
            left["characters"] = remaining
    return left


async def main() -> int:
    conn = connect()
    token = await make_token()
    user_id = system_user_id(conn)
    clones: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        row = target_character(conn)
        # One clone per scenario: an isolated first turn with no shared state.
        clones = clone_characters(conn, user_id, [row] * len(SCENARIOS))
        print(f"TEST_USER {USERNAME} user_id={user_id} login-control whitelisted")
        print("CLONES " + json.dumps([c["id"] for c in clones], ensure_ascii=False))

        limits = httpx.Limits(max_connections=6, max_keepalive_connections=3)
        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(pair: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
                char, scenario = pair
                async with sem:
                    print(f"RUN {scenario['case']} clone={char['id']}")
                    try:
                        return await run_scenario(client, token, char, scenario)
                    except Exception:
                        return {"character": char["name"], "case": scenario["case"],
                                "conversation_ids": [], "ok": False, "reply": traceback.format_exc(),
                                "no_reply": False,
                                "check": {"third_person_hits": [], "has_second_person": False,
                                          "has_first_person": False, "ok": False}}

            gathered = await asyncio.gather(*(one(p) for p in zip(clones, SCENARIOS)),
                                            return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                results.append({"character": "TASK_EXCEPTION", "case": "exception", "ok": False,
                                "reply": repr(item), "no_reply": False,
                                "check": {"third_person_hits": [], "has_second_person": False,
                                          "has_first_person": False, "ok": False}})
            else:
                results.append(item)

        failures = [r for r in results if not r.get("ok")]
        print("\n=== SUMMARY ===")
        print(json.dumps({
            "base_url": BASE_URL, "test_user": USERNAME,
            "roles_tested": len(SCENARIOS), "failures": len(failures),
        }, ensure_ascii=False, indent=2))
        print("\n=== REPLIES ===")
        for result in results:
            print(f"\n--- {result.get('case')} [{'PASS' if result.get('ok') else 'FAIL'}]")
            print("USER :", result.get("raw_user"))
            print("REPLY:", result.get("reply"))
        print("\n=== FAILURES ===")
        print(json.dumps([{k: r.get(k) for k in
                           ("case", "raw_user", "reply", "check", "expected", "http",
                            "no_reply", "reason", "retried_empty_reply")}
                          for r in failures], ensure_ascii=False, indent=2))
        return 0 if not failures else 1
    finally:
        left: dict[str, int] = {}
        try:
            conversation_ids: list[str] = []
            for result in results:
                conversation_ids.extend(str(cid) for cid in (result.get("conversation_ids") or []) if str(cid))
            if clones:
                clone_ids = [c["id"] for c in clones]
                # The memory scheduler can write character-scoped state shortly
                # after a turn completes, so sweep until nothing is left.
                for attempt in range(4):
                    left = cleanup_run(connect(), user_id, clone_ids, conversation_ids)
                    if not left:
                        break
                    print(f"CLEANUP_PASS {attempt + 1} still left {json.dumps(left, ensure_ascii=False)}")
                    time.sleep(4)
            print("\n=== CLEANUP_LEFT_ROWS ===")
            print(json.dumps(left, ensure_ascii=False, indent=2))
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))
        if left:
            print("CLEANUP_NOT_EMPTY", json.dumps(left, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
