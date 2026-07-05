from __future__ import annotations

import asyncio
import json
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

from Backend.chat_modules.normal_planner import (  # noqa: E402
    format_normal_scene_anchor_card,
)
from Backend.scripts.test_normal_scene_anchor_matrix import (  # noqa: E402
    BASE_URL,
    CONCURRENCY,
    character_name,
    cleanup,
    clone_characters,
    connect,
    create_test_user,
    load_target_system_characters,
    make_token,
    parse_reply,
)

CLIENT_ID = "codex_stale_memory_current_action_matrix"
TARGET_TEST_ROLE_NAMES = ("紫悦", "碧琪", "柔柔")


SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "key": "long_term_old_action_vs_current_psychology",
        "shortcut": "（请详细写出当前你的心理活动）",
        "seed_long_term": "长期上下文摘要：昨天在旧阳台，用户拿着霜纹羽刷轻轻扫过角色的耳尖。",
        "current_message": "（我们在安静茶室里。我正握住你的前蹄，把红瓷茶杯递到你面前。）先接住当前动作就好。",
        "stale_terms": ("霜纹羽刷", "旧阳台"),
        "current_terms": ("红瓷茶杯", "茶杯", "杯茶", "前蹄", "蹄子", "茶香"),
    },
    {
        "key": "old_scene_observation_vs_current_vision",
        "shortcut": "（请详细写出当前你看到的画面）",
        "seed_observation": "旧门厅里，用户拿着蓝丝风铃绕着角色的肩膀晃动。",
        "current_message": "（我们在书房桌边。我把青铜地图筒递给你，桌面上有地图和台灯。）请看清现在的画面。",
        "stale_terms": ("蓝丝风铃", "旧门厅"),
        "current_terms": ("青铜地图筒", "地图筒", "地图", "台灯"),
    },
    {
        "key": "combined_old_material_vs_current_body",
        "shortcut": "（请详细写出当前你的身体状态）",
        "seed_long_term": "长期上下文摘要：很久前，用户把薄荷铜铃系在角色尾巴上，让铃声一路跟着摇晃。",
        "seed_observation": "旧走廊里，用户曾用琥珀梳反复梳过角色鬃毛。",
        "current_message": "（我把白棉毛巾递到你身边，你站在桌边看着桌面水渍。）请承接现在的身体状态。",
        "stale_terms": ("薄荷铜铃", "铜铃", "琥珀梳", "旧走廊", "青铜地图筒", "红瓷茶杯"),
        "current_terms": ("白棉毛巾", "毛巾", "水渍", "桌边"),
    },
    {
        "key": "current_scene_skiing_overrides_memory_preference",
        "kind": "qa",
        "seed_long_term": "长期上下文摘要：用户喜欢单板滑雪，也经常聊单板滑雪装备。角色以前开过雪橇车。角色喜欢雪山。",
        "setup_messages": (
            ("user", "（我们正在雪山上用双板滑雪，雪道很宽。）先慢慢滑一段。"),
            ("assistant", "好，我跟着你的节奏滑，雪道确实很宽。"),
            ("user", "今天雪质还不错。"),
            ("assistant", "嗯，脚下的雪很稳，转弯也不费劲。"),
            ("user", "我们沿着左边那条蓝道走。"),
            ("assistant", "行，我注意着坡度，跟你保持一点距离。"),
            ("user", "你看远处的缆车。"),
            ("assistant", "看到了，缆车正从雪道上方慢慢过去。"),
        ),
        "question": "我们在用什么滑雪？",
        "expected_terms": ("双板滑雪", "双板"),
        "wrong_terms": ("单板滑雪", "单板"),
    },
    {
        "key": "memory_probe_restaurant_dish_overrides_current_salad",
        "kind": "qa",
        "seed_long_term": "长期上下文摘要：以前用户和角色在“佳话”餐厅吃过“西红柿炒鸡蛋”，用户评价说很好吃。用户不喜欢吃凉拌西红柿。角色喜欢吃水煮蛋。用户和角色以前在“神话”餐厅吃过“蔬菜沙拉”。",
        "setup_messages": (
            ("user", "（我们正在“佳话”餐厅吃蔬菜沙拉，桌上有两杯温水。）这个沙拉还挺清爽。"),
            ("assistant", "是挺清爽的，菜叶看起来也很新鲜。"),
            ("user", "这家店环境还不错。"),
            ("assistant", "嗯，桌间距也舒服，不会太吵。"),
            ("user", "先慢慢吃吧。"),
            ("assistant", "好，我们不急，慢慢吃。"),
            ("user", "我好像想起以前也来过。"),
            ("assistant", "你像是记起了什么，我听着。"),
        ),
        "question": "我之前说过一个菜很好吃，是什么来着？",
        "expected_terms": ("西红柿炒鸡蛋",),
        "wrong_terms": (),
    },
)


def now_ms() -> int:
    return int(time.time() * 1000)


def add_user(messages: list[dict[str, Any]], content: str) -> None:
    messages.append(
        {
            "role": "user",
            "content": content,
            "message_id": "u_" + uuid.uuid4().hex,
            "timestamp": now_ms(),
        }
    )


def add_assistant(messages: list[dict[str, Any]], content: str, speaker: dict[str, Any]) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": content,
            "message_id": "a_" + uuid.uuid4().hex,
            "timestamp": now_ms(),
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


def seed_context_memory(
    conn: sqlite3.Connection,
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    text: str,
) -> None:
    if not text:
        return
    conn.execute(
        """INSERT OR REPLACE INTO normal_chat_memory
              (username, character_id, conversation_id, char_memory_json,
               short_term_memory, long_term_memory, entries_covered_count,
               lt_covered_count, updated_at)
           VALUES (?, ?, ?, '[]', '', ?, 24, 24, ?)""",
        (username, character_id, conversation_id, text, int(time.time())),
    )
    conn.commit()


def seed_scene_observation(
    conn: sqlite3.Connection,
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    char_name: str,
    observation: str,
) -> None:
    if not observation:
        return
    anchor = {
        "status": "active",
        "scene_time": {"value": "昨天傍晚", "relation_to_real_time": "历史场景"},
        "location": {
            "region": "测试区域",
            "site": "旧宅",
            "room": "旧门厅",
            "spot": "门边",
        },
        "current_character": {
            "name": char_name,
            "position": {"spot": "门边", "posture": "站着"},
            "evidence": "历史场景锚点",
        },
        "participants": [],
        "items": [],
        "observations": [observation],
        "continuity_rules": ["如果最近可见对话给出新的当前动作和地点，以最近可见对话为当前事实。"],
    }
    conn.execute(
        """INSERT OR REPLACE INTO normal_scene_state
              (username, character_id, conversation_id, scene_json, scene_card, updated_ms, source)
           VALUES (?, ?, ?, ?, ?, ?, 'codex_stale_memory_current_action_matrix')""",
        (
            username,
            character_id,
            conversation_id,
            json.dumps(anchor, ensure_ascii=False),
            format_normal_scene_anchor_card(anchor),
            now_ms() - 60_000,
        ),
    )
    conn.commit()


def validate_reply(scenario: dict[str, Any], first: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    first_reply = str(first.get("reply") or "")
    final_reply = str(final.get("reply") or "")
    combined = first_reply + "\n" + final_reply
    if not first.get("ok"):
        failures.append(f"first_http_{first.get('http')}")
    if not final.get("ok"):
        failures.append(f"final_http_{final.get('http')}")
    if final.get("no_reply"):
        failures.append("final_no_reply")
    if not final_reply.strip():
        failures.append("final_empty")
    stale_hits = [term for term in scenario.get("stale_terms", ()) if term and term in combined]
    if stale_hits:
        failures.append("stale_terms_in_reply:" + ",".join(stale_hits))
    current_terms = tuple(scenario.get("current_terms") or ())
    if current_terms and not any(term in final_reply for term in current_terms):
        failures.append("missing_current_anchor")
    expected_terms = tuple(scenario.get("expected_terms") or ())
    if expected_terms and not any(term in final_reply for term in expected_terms):
        failures.append("missing_expected_answer:" + ",".join(expected_terms))
    wrong_terms = tuple(scenario.get("wrong_terms") or ())
    wrong_hits = [term for term in wrong_terms if term and term in final_reply]
    if wrong_hits and expected_terms and not any(term in final_reply for term in expected_terms):
        failures.append("wrong_answer_terms:" + ",".join(wrong_hits))
    return {
        "passed": not failures,
        "failures": failures,
        "first_preview": first_reply[:240],
        "final_preview": final_reply[:420],
        "elapsed_first": first.get("elapsed"),
        "elapsed_final": final.get("elapsed"),
    }


async def run_scenario(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    conn: sqlite3.Connection,
    char: dict[str, Any],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = "stale_current_" + scenario["key"] + "_" + uuid.uuid4().hex
    seed_context_memory(
        conn,
        username=username,
        character_id=char["id"],
        conversation_id=conversation_id,
        text=str(scenario.get("seed_long_term") or ""),
    )
    seed_scene_observation(
        conn,
        username=username,
        character_id=char["id"],
        conversation_id=conversation_id,
        char_name=char["name"],
        observation=str(scenario.get("seed_observation") or ""),
    )
    messages: list[dict[str, Any]] = []
    if scenario.get("kind") == "qa":
        for role, content in scenario.get("setup_messages") or ():
            if role == "assistant":
                add_assistant(messages, str(content), char)
            else:
                add_user(messages, str(content))
        add_user(messages, str(scenario["question"]))
        first = {
            "ok": True,
            "http": 200,
            "reply": " / ".join(str(content) for role, content in (scenario.get("setup_messages") or ()) if role == "user")[:240],
            "no_reply": False,
            "reason": "",
            "elapsed": 0,
        }
        final = await chat(client, token, username, char["id"], conversation_id, messages)
    else:
        add_user(messages, str(scenario["current_message"]))
        first = await chat(client, token, username, char["id"], conversation_id, messages)
        add_assistant(messages, str(first.get("reply") or ""), char)
        add_user(messages, str(scenario["shortcut"]))
        final = await chat(client, token, username, char["id"], conversation_id, messages)
    check = validate_reply(scenario, first, final)
    return {
        "key": scenario["key"],
        "conversation_id": conversation_id,
        "first": first,
        "final": final,
        **check,
    }


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    conn: sqlite3.Connection,
    char: dict[str, Any],
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        steps.append(await run_scenario(client, token, username, conn, char, scenario))
        await asyncio.sleep(0.25)
    return {
        "character": char,
        "conversation_ids": [str(step["conversation_id"]) for step in steps],
        "steps": steps,
    }


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        name = (result.get("character") or {}).get("name", "UNKNOWN")
        for step in result.get("steps") or []:
            if not step.get("passed"):
                failures.append(
                    {
                        "character": name,
                        "step": step.get("key"),
                        "failures": step.get("failures"),
                        "first_preview": step.get("first_preview"),
                        "final_preview": step.get("final_preview"),
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
        rows = [row for row in rows if character_name(row) in TARGET_TEST_ROLE_NAMES]
        missing = [name for name in TARGET_TEST_ROLE_NAMES if name not in {character_name(row) for row in rows}]
        if missing:
            raise RuntimeError("missing target roles: " + ",".join(missing))
        clones = clone_characters(conn, user_id, rows)
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        limits = httpx.Limits(max_connections=max(24, CONCURRENCY * 4), max_keepalive_connections=max(12, CONCURRENCY * 2))
        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    print(f"RUN {char['name']} clone={char['id']}")
                    try:
                        return await run_character(client, token, username, conn, char)
                    except Exception:
                        tb = traceback.format_exc()
                        return {
                            "character": char,
                            "conversation_ids": [],
                            "steps": [
                                {
                                    "key": "task_exception",
                                    "passed": False,
                                    "failures": ["task_exception"],
                                    "first_preview": "",
                                    "final_preview": tb[:800],
                                }
                            ],
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
                                "first_preview": "",
                                "final_preview": repr(item),
                            }
                        ],
                    }
                )
            else:
                results.append(item)

        failures = validate(results)
        summary_rows = []
        for result in results:
            row: dict[str, Any] = {"name": result["character"]["name"]}
            for step in result["steps"]:
                row[step["key"]] = {
                    "passed": step.get("passed"),
                    "failures": step.get("failures"),
                    "elapsed_first": step.get("elapsed_first"),
                    "elapsed_final": step.get("elapsed_final"),
                    "first_preview": step.get("first_preview"),
                    "final_preview": step.get("final_preview"),
                }
            summary_rows.append(row)
        print("\n=== SUMMARY ===")
        print(
            json.dumps(
                {
                    "test_user": username,
                    "membership": "developer",
                    "clones": len(clones),
                    "roles_tested": len(results),
                    "scenes_per_role": len(SCENARIOS),
                    "failures": len(failures),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(summary_rows, ensure_ascii=False, indent=2))
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
