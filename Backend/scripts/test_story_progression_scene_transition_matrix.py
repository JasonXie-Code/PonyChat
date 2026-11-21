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
CLIENT_ID = "codex_story_progression_scene_transition_matrix"
CONCURRENCY = int(os.getenv("PONYCHAT_STORY_SCENE_TEST_CONCURRENCY", "6") or "6")
TEST_USER_PREFIX = "codexqa_story_scene_"


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
           VALUES (?, 'developer', NULL, 'codex_story_progression_scene_transition_matrix', ?, 'temporary story progression scene transition backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "StorySceneTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证普通对话剧情推进转场。",
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
            headers={
                "X-Chat-Auth": token,
                "X-Client-Id": CLIENT_ID,
                "Accept": "application/json",
            },
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
            "reply": resp.text[:800],
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
    return {
        "key": key,
        **result,
        "reply_preview": str(result.get("reply") or "")[:260],
    }


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "key": "grave_to_indoor_treatment",
        "description": "墓碑旁已经提议回屋后，推进应转到室内疗伤/换药下一幕。",
        "history": [
            {
                "role": "user",
                "content": "（戏内时间是第二天。大地点小马谷，中地点派家岩石农场，小地点户外，微观地点奠基顽石旁。墓碑已经立好，Jason、石灰派、玉琪派都在场。Jason身上有伤，缠着旧绷带。）这里的事已经做完了，先别继续立碑。",
            },
            {
                "role": "assistant",
                "content": "（我看着墓碑沉默了几秒，然后抬头看向大家）这里的事做完了，我们回屋吧。屋里有药箱，Jason的伤口该重新换药。",
            },
        ],
        "shortcut": "（请推进剧情发展）",
        "positive_terms": ("屋", "室内", "房间", "桌", "椅", "药", "绷带", "换药", "包扎", "伤口", "药箱", "茶"),
        "progress_re": r"(进|进入|回到|回屋|走进|推开|翻出|放到|带.{0,8}进|坐下|坐到|扶.{0,8}坐|拿出|打开|开始|拆|换|重新包|包扎|处理).{0,34}(屋|门|室内|房间|药|绷带|伤口|药箱|茶)",
        "bad_re": r"(先|现在|我们|咱们).{0,12}(回屋吧|进屋吧|走吧)(?![^。！？!?]{0,20}(已经|坐|拿|换|包扎|处理|药))|继续.{0,8}立碑|重新.{0,8}立碑",
    },
    {
        "key": "doorway_to_backyard_task",
        "description": "已到侧门/门口并给出去后院目标后，推进应抵达后院并开始任务。",
        "history": [
            {
                "role": "user",
                "content": "（戏内时间是下午。我们在一栋房子的侧门边，角色已经知道后院在哪里。）你刚才说要带我去后院检查围栏，别再停在门口。",
            },
            {
                "role": "assistant",
                "content": "（我推开侧门，朝外面看了一眼）后院就在门外，那段围栏有点松，等会儿要过去检查。",
            },
        ],
        "shortcut": "（请推进剧情发展）",
        "positive_terms": ("后院", "院子", "围栏", "木栅栏", "工具", "木桩", "木板", "横条", "钉子", "铁丝", "检查", "修", "门外", "草地"),
        "progress_re": r"(到|来到|走到|进|进入|穿过|推开|抵达|站在|蹲|降落在|落在|停在|开始|检查|修|扶正|拿起|敲|顶|推|碰|戳|摇|换).{0,36}(后院|院子|围栏|木栅栏|工具|木桩|木板|横条|钉子|铁丝|草地)|(?:后院|院子|围栏|木栅栏|木板|横条|木桩|钉子|铁丝).{0,28}(检查|松|松脱|修|扶正|敲|顶|推|碰|戳|摇|摇晃|换|歪|翘|裂|倒)",
        "bad_re": r"(还在|停在).{0,12}(门口|侧门)|(?:走吧|跟我来|我带你去)(?![^。！？!?]{0,22}(后院|围栏|院子|工具|检查|修))",
    },
    {
        "key": "finished_task_to_next_clue",
        "description": "旧任务已完成并已到档案室门口后，推进应进入档案室并开始找线索。",
        "history": [
            {
                "role": "user",
                "content": "（当前场景：小镇档案室门口。刚才的整理旧箱子任务已经完成，不需要再整理箱子。大家已经来到档案室门口，下一步是进档案室找蓝色封面的记录本。）",
            },
            {
                "role": "assistant",
                "content": "好，整理箱子的任务结束了。门就在眼前，我接下来推门进去，先看靠窗的架子上有没有那本蓝色封面的记录本。",
            },
        ],
        "shortcut": "（请推进剧情发展）",
        "positive_terms": ("档案室", "记录本", "蓝色封面", "架", "柜", "翻开", "找到", "灰尘", "线索", "门", "灯"),
        "progress_re": r"(进入|走进|推开|打开|站在|开始|翻|抽出|找到|拿起|落在|推).{0,32}(档案室|记录本|蓝色封面|架|柜|线索|门|灯)|(?:档案室|记录本|蓝色封面|架|柜|门).{0,28}(翻开|找到|抽出|拿起|线索|灰尘|推开|打开|没锁|灯)",
        "bad_re": r"(继续|重新|再).{0,10}(整理|收拾|处理).{0,8}(箱子|旧箱)|箱子.{0,12}(还没|继续|需要)",
    },
)


def classify_reply(reply: str, scenario: dict[str, Any]) -> dict[str, Any]:
    text = str(reply or "")
    positive_terms = tuple(scenario.get("positive_terms") or ())
    progress_re = re.compile(str(scenario.get("progress_re") or ""))
    bad_re = re.compile(str(scenario.get("bad_re") or "$.^"))
    too_short = len(text.strip()) < 12
    has_positive = _has_any(text, positive_terms)
    has_progress = bool(progress_re.search(text))
    has_bad = bool(bad_re.search(text)) and not has_progress
    ok = bool(has_positive and has_progress and not has_bad and not too_short)
    return {
        "has_positive_terms": has_positive,
        "has_progress_action": has_progress,
        "has_bad_pattern": has_bad,
        "too_short": too_short,
        "ok": ok,
    }


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
            columns = {
                str(r["name"])
                for r in conn.execute(f"PRAGMA table_info({table})")
            }
            if "character_id" not in columns:
                continue
            if "username" in columns:
                conn.execute(f"DELETE FROM {table} WHERE username=? AND character_id=?", (username, character_id))
            elif "user_id" in columns:
                conn.execute(f"DELETE FROM {table} WHERE user_id=? AND character_id=?", (user_id, character_id))
        conn.commit()
    finally:
        conn.close()


async def run_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = f"story_scene_{scenario['key']}_{uuid.uuid4().hex}"
    messages: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for item in scenario.get("history") or []:
        role = str((item or {}).get("role") or "user")
        content = str((item or {}).get("content") or "")
        if role == "assistant":
            add_assistant(messages, content, char)
        else:
            add_user(messages, content)
    final_step = await run_turn(
        client,
        token,
        username,
        char,
        conversation_id,
        messages,
        str(scenario["shortcut"]),
        scenario["key"],
    )
    final_step["final_check"] = classify_reply(str(final_step.get("reply") or ""), scenario)
    steps.append(final_step)
    return {
        "scenario": scenario["key"],
        "description": scenario["description"],
        "conversation_id": conversation_id,
        "steps": steps,
        "final_ok": bool(final_step.get("ok")) and not bool(final_step.get("no_reply")) and bool(final_step["final_check"]["ok"]),
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
            final_step = (scenario.get("steps") or [{}])[-1]
            if not scenario.get("final_ok"):
                failures.append(
                    {
                        "character": char_name,
                        "scenario": scenario.get("scenario"),
                        "expected": scenario.get("description"),
                        "detail": final_step,
                    }
                )
            for step in scenario.get("steps") or []:
                if not step.get("ok") or step.get("no_reply"):
                    failures.append(
                        {
                            "character": char_name,
                            "scenario": scenario.get("scenario"),
                            "step": step.get("key"),
                            "expected": "每轮后端请求应成功并产出角色回复。",
                            "detail": step,
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
                        return await run_character(client, token, username, user_id, char)
                    except Exception:
                        return {
                            "character": char,
                            "conversation_ids": [],
                            "scenarios": [
                                {
                                    "scenario": "task_exception",
                                    "conversation_id": "",
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
                        "scenarios": [
                            {
                                "scenario": "exception",
                                "conversation_id": "",
                                "steps": [{"key": "exception", "ok": False, "reply": repr(item), "no_reply": False}],
                                "final_ok": False,
                            }
                        ],
                        "final_ok": False,
                    }
                )
            else:
                results.append(item)

        failures = validate(results)
        summary_rows = []
        for result in results:
            summary_rows.append(
                {
                    "name": result.get("character", {}).get("name"),
                    "final_ok": result.get("final_ok"),
                    "scenarios": [
                        {
                            "key": scenario.get("scenario"),
                            "final_ok": scenario.get("final_ok"),
                            "final_check": ((scenario.get("steps") or [{}])[-1]).get("final_check"),
                            "final_preview": ((scenario.get("steps") or [{}])[-1]).get("reply_preview"),
                            "elapsed": ((scenario.get("steps") or [{}])[-1]).get("elapsed"),
                        }
                        for scenario in result.get("scenarios") or []
                    ],
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
                    "scenarios_per_role": [s["key"] for s in SCENARIOS],
                    "total_scenarios": len(results) * len(SCENARIOS),
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
