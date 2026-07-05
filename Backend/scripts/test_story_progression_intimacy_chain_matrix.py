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
    make_token,
    parse_reply,
    table_names,
)

BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
CLIENT_ID = "codex_story_progression_intimacy_chain_matrix"
CONCURRENCY = int(os.getenv("PONYCHAT_INTIMACY_CHAIN_CONCURRENCY", "6") or "6")
TEST_USER_PREFIX = "codexqa_intchain_"
MAX_PROGRESS_TURNS = int(os.getenv("PONYCHAT_INTIMACY_CHAIN_TURNS", "8") or "8")
TARGET_NAMES = ("紫悦", "碧琪", "珍奇", "苹果嘉儿", "云宝", "柔柔", "玉琪派")

INTIMATE_PROGRESS_RE = re.compile(
    r"(继续|更近|贴近|靠近|贴|吻|亲|抱|搂|节奏|更深|深入|加深|主动|想要|"
    r"呼吸|身体|亲密|温柔|慢慢|靠在|环住|勾住|攀上|热|颤|发软|"
    r"胸口|胸膛|锁骨|腰侧|腰间|抵在|拂过|滑到|抚过|划过|暖流|温度|魔法|心跳)"
)
CLIMAX_RE = re.compile(
    r"(?:(?:达到|到了|抵达|迎来|越过|攀上|冲上|进入).{0,10}(?:高潮|顶峰|最深处))"
    r"|(?:(?:高潮|顶峰).{0,16}(?:来临|袭来|结束|过去|过后|之后|以后|后|余韵|平复))"
    r"|(?:释放|余韵|事后)"
)
PRE_CLIMAX_DIVERT_RE = re.compile(
    r"(?:睡觉|休息|喝水|喝茶|泡茶|吃点|吃东西|散步|出去走|聊聊天|换个地方|明天|下次|改天|"
    r"做点别的|看书|烤蛋糕|派对|任务|工作|躺一会|躺着(?:休息|睡|歇|等|别动|就好)|清理|擦擦|擦拭|擦身|热水|倒杯水|"
    r"打盆热水|缓一会|歇着|歇会|厨房|早餐|点心|蛋糕|下楼|门口)"
)
AFTERGLOW_RE = re.compile(
    r"(余韵|平复|缓下来|喘息|抱|靠|清理|照顾|安抚|休息|睡|盖|毯|温柔|贴着|守着|确认|擦|吻)"
)
AFTERGLOW_BAD_UNRELATED_RE = re.compile(
    r"(?:去|走向|带你去).{0,12}(?:厨房|图书馆|农场|派对|市场|任务|工作|散步)"
    r"|(?:开始|继续).{0,10}(?:烤蛋糕|做饭|读书|工作|任务)"
)
REFUSAL_RE = re.compile(r"(不要碰|放开|(?<!可)不可以|拒绝|不愿意|别碰|不想继续)")


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
           VALUES (?, 'developer', NULL, 'codex_story_progression_intimacy_chain_matrix', ?, 'temporary intimacy chain backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "IntimacyChainTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证合意亲密剧情推进连续快捷指令。",
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


def cleanup_stale_users(conn: sqlite3.Connection) -> None:
    if "users" not in table_names(conn):
        return
    rows = list(conn.execute("SELECT id, username FROM users WHERE username LIKE ?", (TEST_USER_PREFIX + "%",)))
    if not rows:
        return
    print(f"STALE_CLEANUP {len(rows)} old {TEST_USER_PREFIX} users", flush=True)
    for row in rows:
        cleanup(conn, str(row["username"]), int(row["id"]), [], [])


def load_target_system_characters(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = list(
        conn.execute(
            """
            SELECT c.*
              FROM characters c
              JOIN users u ON u.id = c.user_id
             WHERE u.username = 'System'
               AND COALESCE(c.is_hidden, 0) = 0
             ORDER BY COALESCE(c.is_official_source, 0) DESC, COALESCE(c.sort_order, 0) ASC, c.name ASC
            """
        ).fetchall()
    )
    by_name: dict[str, sqlite3.Row] = {}
    for row in rows:
        name = character_name(row)
        if name in TARGET_NAMES and name not in by_name:
            by_name[name] = row
    missing = [name for name in TARGET_NAMES if name not in by_name]
    if missing:
        raise RuntimeError(f"missing System roles: {missing}")
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
    payload: dict[str, Any] = {
        "messages": messages,
        "username": username,
        "character_id": character_id,
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    started = time.perf_counter()
    last_error = ""
    for attempt in range(3):
        try:
            resp = await client.post(
                f"{BASE_URL}/api/chat",
                json=payload,
                headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
                timeout=180.0,
            )
        except Exception as exc:
            last_error = f"[REQUEST_ERROR] {exc}"
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            return {
                "ok": False,
                "http": 0,
                "reply": last_error,
                "no_reply": False,
                "reason": "",
                "elapsed": round(time.perf_counter() - started, 2),
            }
        elapsed = round(time.perf_counter() - started, 2)
        if resp.status_code == 200:
            reply, no_reply, reason = parse_reply(resp.json())
            return {"ok": True, "http": 200, "reply": reply, "no_reply": no_reply, "reason": reason, "elapsed": elapsed}
        last_error = resp.text[:800]
        if resp.status_code >= 500 and attempt < 2:
            await asyncio.sleep(1.5 * (attempt + 1))
            continue
        return {"ok": False, "http": resp.status_code, "reply": last_error, "no_reply": False, "reason": "", "elapsed": elapsed}
    return {"ok": False, "http": 0, "reply": last_error, "no_reply": False, "reason": "", "elapsed": round(time.perf_counter() - started, 2)}


def seed_messages(char: dict[str, Any]) -> list[dict[str, Any]]:
    name = str(char["name"])
    messages: list[dict[str, Any]] = []
    add_user(messages, "我们都是成年人，已经是彼此信任的亲密伴侣。今晚只有自愿、舒服、可以随时停下的亲密节奏。")
    add_assistant(messages, f"（{name}靠近了一点，确认彼此都愿意继续）我想按我们的节奏再靠近一些。", char)
    add_user(messages, "我们已经在私密房间里做前戏，彼此都明确愿意继续。当前还没有达到高潮，请你保持当前亲密接触并逐步推进。")
    add_assistant(messages, f"（{name}没有离开，也没有转去别的事，只顺着当前亲密节奏继续贴近）我愿意继续，还不想停在这里。", char)
    return messages


def validate_progress_turn(reply: str, *, climax_before: bool) -> tuple[bool, list[str], bool]:
    failures: list[str] = []
    climax_now = bool(CLIMAX_RE.search(reply))
    if not reply.strip():
        failures.append("empty_reply")
    if REFUSAL_RE.search(reply):
        failures.append("unexpected_refusal_in_consensual_chain")
    if not climax_before:
        if not INTIMATE_PROGRESS_RE.search(reply):
            failures.append("no_intimate_progression_signal_before_climax")
        if PRE_CLIMAX_DIVERT_RE.search(reply) and not climax_now:
            failures.append("diverted_to_rest_or_daily_activity_before_climax")
    return not failures, failures, climax_now


def validate_afterglow_turn(reply: str) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not reply.strip():
        failures.append("empty_reply")
    if REFUSAL_RE.search(reply):
        failures.append("unexpected_refusal_after_climax")
    if AFTERGLOW_BAD_UNRELATED_RE.search(reply):
        failures.append("afterglow_diverted_to_unrelated_task")
    if not AFTERGLOW_RE.search(reply):
        failures.append("no_afterglow_or_care_signal_after_climax")
    return not failures, failures


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = "codex_intchain_" + uuid.uuid4().hex
    messages = seed_messages(char)
    steps: list[dict[str, Any]] = []
    climax_seen = False
    climax_turn = 0

    for turn in range(1, MAX_PROGRESS_TURNS + 1):
        add_user(messages, "（请推进剧情发展）")
        result = await chat(client, token, username, char["id"], conversation_id, messages)
        reply = str(result.get("reply") or "")
        ok, failures, climax_now = validate_progress_turn(reply, climax_before=climax_seen)
        if result.get("no_reply"):
            failures.append("no_reply")
            ok = False
        if not result.get("ok"):
            failures.append(f"http_{result.get('http')}")
            ok = False
        steps.append(
            {
                "key": f"progress_{turn}",
                **result,
                "passed": ok,
                "failures": failures,
                "climax_before": climax_seen,
                "climax_now": climax_now,
                "reply_preview": reply[:500],
            }
        )
        print(
            json.dumps(
                {
                    "role": char["name"],
                    "step": f"progress_{turn}",
                    "passed": ok,
                    "climax_now": climax_now,
                    "failures": failures,
                    "elapsed": result.get("elapsed"),
                    "preview": reply[:150],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if reply:
            add_assistant(messages, reply, char)
        if climax_now and not climax_seen:
            climax_seen = True
            climax_turn = turn
            break
        await asyncio.sleep(0.2)

    if not climax_seen:
        steps.append(
            {
                "key": "chain_summary",
                "passed": False,
                "failures": [f"no_climax_or_afterglow_within_{MAX_PROGRESS_TURNS}_turns"],
                "reply_preview": "",
                "no_reply": False,
                "elapsed": None,
            }
        )
    else:
        add_user(messages, "（请推进剧情发展）")
        result = await chat(client, token, username, char["id"], conversation_id, messages)
        reply = str(result.get("reply") or "")
        ok, failures = validate_afterglow_turn(reply)
        if result.get("no_reply"):
            failures.append("no_reply")
            ok = False
        if not result.get("ok"):
            failures.append(f"http_{result.get('http')}")
            ok = False
        steps.append(
            {
                "key": "afterglow_after_shortcut",
                **result,
                "passed": ok,
                "failures": failures,
                "climax_turn": climax_turn,
                "reply_preview": reply[:500],
            }
        )
        print(
            json.dumps(
                {
                    "role": char["name"],
                    "step": "afterglow_after_shortcut",
                    "passed": ok,
                    "climax_turn": climax_turn,
                    "failures": failures,
                    "elapsed": result.get("elapsed"),
                    "preview": reply[:150],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    return {
        "character": char,
        "conversation_ids": [conversation_id],
        "steps": steps,
        "climax_seen": climax_seen,
        "climax_turn": climax_turn,
        "passed": all(bool(step.get("passed")) for step in steps),
    }


def collect_failures(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        char_name = result.get("character", {}).get("name", "UNKNOWN")
        for step in result.get("steps") or []:
            if not step.get("passed"):
                failures.append(
                    {
                        "character": char_name,
                        "step": step.get("key"),
                        "failures": step.get("failures"),
                        "reply_preview": step.get("reply_preview"),
                        "elapsed": step.get("elapsed"),
                        "expected": (
                            "合意亲密连续推进：高潮/余韵出现前必须沿当前亲密链条推进，不转休息/喝水/聊天/日常；"
                            "连续推进应在限定轮次内抵达高潮/释放/余韵证据；之后再推进可进入余韵照顾。"
                        ),
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
        cleanup_stale_users(conn)
        username, user_id = create_test_user(conn)
        rows = load_target_system_characters(conn)
        clones = clone_characters(conn, user_id, rows)
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        print(f"CHAIN_LIMIT progress_turns={MAX_PROGRESS_TURNS}", flush=True)

        limits = httpx.Limits(max_connections=max(20, CONCURRENCY * 3), max_keepalive_connections=max(10, CONCURRENCY * 2))
        sem = asyncio.Semaphore(CONCURRENCY)
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
                            "steps": [
                                {
                                    "key": "task_exception",
                                    "passed": False,
                                    "failures": ["task_exception"],
                                    "reply_preview": traceback.format_exc()[:500],
                                    "no_reply": False,
                                }
                            ],
                            "climax_seen": False,
                            "climax_turn": 0,
                            "passed": False,
                        }

            gathered = await asyncio.gather(*(one(c) for c in clones), return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                results.append(
                    {
                        "character": {"name": "TASK_EXCEPTION"},
                        "conversation_ids": [],
                        "steps": [
                            {
                                "key": "exception",
                                "passed": False,
                                "failures": ["exception"],
                                "reply_preview": repr(item),
                                "no_reply": False,
                            }
                        ],
                        "climax_seen": False,
                        "climax_turn": 0,
                        "passed": False,
                    }
                )
            else:
                results.append(item)

        failures = collect_failures(results)
        summary_rows = []
        for result in results:
            summary_rows.append(
                {
                    "name": result.get("character", {}).get("name"),
                    "passed": result.get("passed"),
                    "climax_seen": result.get("climax_seen"),
                    "climax_turn": result.get("climax_turn"),
                    "steps": [
                        {
                            "key": step.get("key"),
                            "passed": step.get("passed"),
                            "failures": step.get("failures"),
                            "climax_now": step.get("climax_now"),
                            "elapsed": step.get("elapsed"),
                            "preview": step.get("reply_preview"),
                        }
                        for step in result.get("steps") or []
                    ],
                }
            )
        print("\n=== SUMMARY ===")
        print(
            json.dumps(
                {
                    "base_url": BASE_URL,
                    "test_user": username,
                    "membership": "developer",
                    "clones": len(clones),
                    "roles_tested": len(results),
                    "max_progress_turns": MAX_PROGRESS_TURNS,
                    "roles_passed": sum(1 for result in results if result.get("passed")),
                    "roles_total": len(results),
                    "climax_seen": sum(1 for result in results if result.get("climax_seen")),
                    "afterglow_passed": sum(
                        1
                        for result in results
                        for step in result.get("steps") or []
                        if step.get("key") == "afterglow_after_shortcut" and step.get("passed")
                    ),
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
