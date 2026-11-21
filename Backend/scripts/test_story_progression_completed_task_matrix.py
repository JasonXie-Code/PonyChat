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
    cleanup,
    clone_characters,
    connect,
    load_target_system_characters,
    make_token,
    parse_reply,
    table_names,
)

BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
CLIENT_ID = "codex_story_progression_completed_task_matrix"
CONCURRENCY = int(os.getenv("PONYCHAT_STORY_TEST_CONCURRENCY", "6") or "6")
TEST_USER_PREFIX = "codexqa_story_"

PLAN_TERMS = ("计划A", "计划", "长期项目", "第一步")
NEXT_STAGE_TERMS = ("下一步", "下一阶段", "新计划", "新场景", "开始", "继续", "推进", "接下来", "出发")
STAGE_ACTION_RE = re.compile(
    r"(?:现在|接下来|这就|正好|先).{0,16}(?:开始|出发|干|做|去|拿|看|练|试)"
    r"|(?:我|我们|咱们).{0,10}(?:冲到|走到|拿|拽出|翻开|递给|出发|开始|继续)"
)
STAGE_PROPOSAL_RE = re.compile(r"(?:要不要|我们可以|可以).{0,18}(?:去|走|开始|继续|看看|试试|做)")
BAD_RETURN_TO_DONE_TASK_RE = re.compile(
    r"(?:继续|再|重新|回去|回到).{0,10}(?:事情A|插入事项)"
    r"|(?:处理|完成|收尾)(?:一下|掉|完)?(?:事情A|插入事项)"
    r"|(?:事情A|插入事项).{0,10}(?:还没|还要|需要继续|没有完成|未完成)"
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
           VALUES (?, 'developer', NULL, 'codex_story_progression_completed_task_matrix', ?, 'temporary story progression backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "StoryProgressionTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证普通对话剧情推进工具。",
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


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
    retried_empty_reply = False
    if result.get("ok") and not result.get("no_reply") and not str(result.get("reply") or "").strip():
        retried_empty_reply = True
        await asyncio.sleep(1.0)
        result = await chat(client, token, username, char["id"], conversation_id, messages)
    if result.get("reply"):
        add_assistant(messages, str(result["reply"]), char)
    return {"key": key, **result, "retried_empty_reply": retried_empty_reply, "reply_preview": str(result.get("reply") or "")[:240]}


def classify_final_reply(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    has_plan = any(term in text for term in PLAN_TERMS)
    has_next_stage = any(term in text for term in NEXT_STAGE_TERMS)
    has_stage_action = bool(STAGE_ACTION_RE.search(text))
    has_stage_proposal = bool(STAGE_PROPOSAL_RE.search(text))
    bad_done_task_current = bool(BAD_RETURN_TO_DONE_TASK_RE.search(text))
    too_weak = len(text.strip()) < 8 or text.strip("。！？!?. ") in {"嗯", "好", "可以", "行", "走吧"}
    return {
        "has_plan_signal": has_plan,
        "has_next_stage_signal": has_next_stage,
        "has_stage_action": has_stage_action,
        "has_stage_proposal": has_stage_proposal,
        "bad_done_task_current": bad_done_task_current,
        "too_weak": too_weak,
        "ok": (has_plan or has_next_stage or has_stage_action or has_stage_proposal) and not bad_done_task_current and not too_weak,
    }


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = "story_progression_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []

    turns = [
        (
            "plan_a_discussed",
            "我们先定一个计划A：等会儿一起开始那个长期项目，先确认第一步。你觉得可以吗？",
        ),
        (
            "thing_a_discussed",
            "不过先处理事情A，处理完再回到计划A。你先帮我把这件插入事项收尾。",
        ),
        (
            "thing_a_completed",
            "事情A已经处理完了，不需要再处理A。刚才那个插入事项结束了。",
        ),
        ("story_progression_shortcut", "（请推进剧情发展）"),
    ]
    for key, user_text in turns:
        step = await run_turn(client, token, username, char, conversation_id, messages, user_text, key)
        steps.append(step)

    final_reply = str(steps[-1].get("reply") or "") if steps else ""
    final_check = classify_final_reply(final_reply)
    steps[-1]["final_check"] = final_check
    return {
        "character": char,
        "conversation_ids": [conversation_id],
        "steps": steps,
        "final_ok": bool(steps[-1].get("ok")) and not bool(steps[-1].get("no_reply")) and bool(final_check["ok"]),
    }


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        char_name = result.get("character", {}).get("name", "UNKNOWN")
        if not result.get("final_ok"):
            failures.append(
                {
                    "character": char_name,
                    "step": "story_progression_shortcut",
                    "detail": (result.get("steps") or [])[-1] if result.get("steps") else {},
                    "expected": "完成插入事项后，推进剧情应回到计划A，或开启/推进新的下一阶段；不应重新处理已完成的事情A。",
                }
            )
        for step in result.get("steps") or []:
            if not step.get("ok") or step.get("no_reply"):
                failures.append(
                    {
                        "character": char_name,
                        "step": step.get("key"),
                        "detail": step,
                        "expected": "每轮后端请求应成功并产出角色回复。",
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
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        limits = httpx.Limits(max_connections=max(20, CONCURRENCY * 3), max_keepalive_connections=max(10, CONCURRENCY * 2))
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
                            "steps": [
                                {
                                    "key": "task_exception",
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
                        "steps": [{"key": "exception", "ok": False, "reply": repr(item), "no_reply": False}],
                        "final_ok": False,
                    }
                )
            else:
                results.append(item)

        failures = validate(results)
        summary_rows = []
        for result in results:
            final_step = (result.get("steps") or [{}])[-1]
            summary_rows.append(
                {
                    "name": result.get("character", {}).get("name"),
                    "final_ok": result.get("final_ok"),
                    "turns": [
                        {
                            "key": step.get("key"),
                            "ok": step.get("ok"),
                            "no_reply": step.get("no_reply"),
                            "elapsed": step.get("elapsed"),
                            "preview": step.get("reply_preview") or str(step.get("reply") or "")[:240],
                        }
                        for step in result.get("steps") or []
                    ],
                    "final_check": final_step.get("final_check"),
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
                    "scenario_per_role": "计划A -> 事情A -> 事情A已处理 -> 剧情推进",
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
