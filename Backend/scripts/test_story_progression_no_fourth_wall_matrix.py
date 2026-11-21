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
CLIENT_ID = "codex_story_progression_no_fourth_wall_matrix"
TEST_USER_PREFIX = "codexqa_story_nowall_"
TARGET_NAMES = ("云宝", "紫悦", "碧琪")
CONCURRENCY = int(os.getenv("PONYCHAT_STORY_NOWALL_CONCURRENCY", "3") or "3")

META_RE = re.compile(r"(剧情|推进剧情|剧情发展|快捷指令)")
WEAK_RE = re.compile(r"^(嗯|好|走吧|跟我来|我们走|咱们走)[。！？!?. ]*$")
WORLD_PROGRESS_RE = re.compile(
    r"(走到|来到|跑到|蹦到|小跑|靠近|绕到|停在|蹲在|站在|指向|拿起|拿出|发现|看见|打开|翻开|碰了碰|开始|已经|突然|伸进|摸索|拨开|露出|勾出来).{0,36}"
    r"(树|树洞|广场|烟花|彩虹|闪光粉|线索|东西|目标|门|房间|后院|围栏)"
    r"|(?:树洞|烟花|彩虹|闪光粉|线索|围栏|后院|房间).{0,36}(出现|发现|拿|看|响|动|亮|掉|打开|松|摸到|碰到|露出|伸进|拨开|勾出)"
)
BAD_THIRD_PARTY_FORMAT_RE = re.compile(
    r"(她自言自语地说着|咦[？?].{0,18}这玩意儿好像不是我的|这玩意儿好像不是我的啊)"
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
           VALUES (?, 'developer', NULL, 'codex_story_progression_no_fourth_wall_matrix', ?, 'temporary no-fourth-wall backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "StoryNoWallTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证推进快捷消息不打破第四面墙以及第三方发言格式。",
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
    payload = {
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


def remove_parenthetical(text: str) -> str:
    return re.sub(r"（[^）]*）", "", str(text or ""))


def classify_no_meta(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    return {
        "no_meta_terms": not bool(META_RE.search(text)),
        "has_world_progress": bool(WORLD_PROGRESS_RE.search(text)),
        "not_weak_ack": not bool(WEAK_RE.search(text.strip())),
        "ok": not bool(META_RE.search(text)) and bool(WORLD_PROGRESS_RE.search(text)) and not bool(WEAK_RE.search(text.strip())),
    }


def classify_third_party_format(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    outside = remove_parenthetical(text)
    bad_third_party_outside = bool(BAD_THIRD_PARTY_FORMAT_RE.search(outside))
    mentions_pinkie = "碧琪" in text or "她" in text
    mentions_firework = "烟花" in text or "彩虹" in text or "闪光粉" in text
    return {
        "no_meta_terms": not bool(META_RE.search(text)),
        "mentions_third_party": mentions_pinkie,
        "mentions_firework_or_clue": mentions_firework,
        "no_bad_third_party_quote_outside_parentheses": not bad_third_party_outside,
        "ok": not bool(META_RE.search(text)) and mentions_pinkie and mentions_firework and not bad_third_party_outside,
    }


async def run_no_meta_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = "story_nowall_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    add_user(messages, "（当前场景：小马谷广场边，远处有一棵歪脖子树。你刚说那棵树洞里藏着一个小玩意儿，等会儿要带我去看看。）")
    add_assistant(messages, "看到广场那边那棵歪脖子树没？我把一个秘密小玩意儿藏树洞里了，等会儿我们去取。", char)
    step = await run_turn(client, token, username, char, conversation_id, messages, "（请推进剧情发展）", "story_shortcut_no_fourth_wall")
    check = classify_no_meta(str(step.get("reply") or ""))
    step["checks"] = check
    return {
        "scenario": "story_shortcut_no_fourth_wall",
        "conversation_id": conversation_id,
        "character": char,
        "steps": [step],
        "final_ok": bool(step.get("ok")) and not bool(step.get("no_reply")) and bool(check["ok"]),
    }


async def run_third_party_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = "story_third_party_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    add_user(messages, "（当前场景：小马谷广场边的歪脖子树后。你是云宝，我和你躲在树根旁。碧琪就在前方，正低头摆弄一枚迷你彩虹烟雾烟花，还没发现我们。）")
    add_assistant(messages, "嘘，你看那边碧琪手里拿的……那形状绝对是我的迷你彩虹烟雾烟花。", char)
    step = await run_turn(client, token, username, char, conversation_id, messages, "（请推进剧情发展）", "third_party_firework_format")
    check = classify_third_party_format(str(step.get("reply") or ""))
    step["checks"] = check
    return {
        "scenario": "third_party_firework_format",
        "conversation_id": conversation_id,
        "character": char,
        "steps": [step],
        "final_ok": bool(step.get("ok")) and not bool(step.get("no_reply")) and bool(check["ok"]),
    }


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    scenarios = [await run_no_meta_scenario(client, token, username, char)]
    if char.get("name") == "云宝":
        scenarios.append(await run_third_party_scenario(client, token, username, char))
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
                        return await run_character(client, token, username, char)
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
                        "character": result.get("character", {}).get("name"),
                        "clone_id": result.get("character", {}).get("id"),
                        "scenario": scenario.get("scenario"),
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
        print(json.dumps({"base_url": BASE_URL, "test_user": username, "roles": TARGET_NAMES, "failures": len(failures)}, ensure_ascii=False, indent=2))
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
