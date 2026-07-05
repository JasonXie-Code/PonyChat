from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Backend.scripts.test_normal_scene_anchor_matrix import (  # noqa: E402
    BASE_URL,
    CONCURRENCY,
    cleanup,
    clone_characters,
    connect,
    create_test_user,
    load_target_system_characters,
    make_token,
)

CLIENT_ID = "codex_description_shortcut_attribution_matrix"

USER_ASKED_CHARACTER_QUESTION_RE = re.compile(
    r"(?:你|他|她|用户|对方|Jason).{0,8}问我.{0,8}冷不冷|"
    r"被(?:你|他|她|用户|对方|Jason).{0,8}问.{0,8}冷不冷|"
    r"(?:你|他|她|用户|对方|Jason).{0,8}刚才.{0,8}问.{0,8}冷不冷"
)
USER_DID_CHARACTER_ACTION_RE = re.compile(
    r"(?:你|他|她|用户|对方|Jason).{0,8}(?:牵着我|拉着我|碰了我|碰我的|铺好防尘布|掀开防尘布)|"
    r"被(?:你|他|她|用户|对方|Jason).{0,8}(?:牵|拉|碰)"
)
USER_LEADS_RE = re.compile(r"你.{0,6}(?:带路|领路|带我去|领我去|往哪|想去哪|决定去哪)|(?:带路|领路)吧")
PROGRESSION_RE = re.compile(r"门|走廊|柜|箱|布|仓库|房间|窗|脚步|声音|发现|拿起|打开|掀开|走到|转身|带着你|领着你")


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


def parse_reply(data: Any) -> tuple[str, bool, str, list[str]]:
    no_reply = False
    reason = ""
    bubbles: list[str] = []
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        deltas: list[str] = []
        for ev in data.get("events") or []:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "no_reply":
                no_reply = True
                reason = str(ev.get("reason") or "")
            content = ev.get("content")
            if ev.get("type") == "assistant_paragraph" and isinstance(content, str) and content.strip():
                bubbles.append(content.strip())
            for choice in ev.get("choices") or []:
                delta = (choice or {}).get("delta") or {}
                text = delta.get("content") or ""
                if text:
                    deltas.append(str(text))
        reply = "\n".join(bubbles).strip() if bubbles else "".join(deltas).strip()
        return reply, no_reply, reason, bubbles or [p.strip() for p in reply.splitlines() if p.strip()]
    if isinstance(data, dict):
        reply = str(data.get("response") or data.get("text") or data.get("content") or "").strip()
        return reply, bool(data.get("no_reply")), str(data.get("reason") or ""), [reply] if reply else []
    reply = str(data or "").strip()
    return reply, False, "", [reply] if reply else []


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
            "bubbles": [],
            "elapsed": round(time.perf_counter() - started, 2),
        }
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {
            "ok": False,
            "http": resp.status_code,
            "reply": resp.text[:600],
            "no_reply": False,
            "reason": "",
            "bubbles": [],
            "elapsed": elapsed,
        }
    reply, no_reply, reason, bubbles = parse_reply(resp.json())
    return {
        "ok": True,
        "http": 200,
        "reply": reply,
        "no_reply": no_reply,
        "reason": reason,
        "bubbles": bubbles,
        "elapsed": elapsed,
    }


def scenario_messages(char: dict[str, Any], key: str) -> tuple[str, list[dict[str, Any]]]:
    name = char["name"]
    messages: list[dict[str, Any]] = []
    if key == "psych_after_character_question":
        add_user(messages, f"我们在{name}家的旧仓库里避雨，外面风很大。我坐在防尘布旁边，安静地等你说话。")
        add_assistant(messages, "（我把一块干净的防尘布往你身边推了推，声音放得很轻）你……冷不冷？", char)
        add_user(messages, "（请详细写出当前你的心理活动）")
    elif key == "body_after_character_action":
        add_user(messages, f"这里是{name}熟悉的储物间。你知道备用毯子在柜子里，我只是站在门边等你。")
        add_assistant(messages, "（我先掀开防尘布，又轻轻碰了碰你的手背）我牵着你进去，别踩到地上的纸箱。", char)
        add_user(messages, "（请详细写出当前你的身体状态）")
    elif key == "story_home_character_leads":
        add_user(messages, f"现在就在{name}自己熟悉的家里。你刚说备用毯子和灯都在走廊尽头的小柜子里，我站在门边等你安排。")
        add_assistant(messages, "（我看了一眼走廊，已经知道该往哪里去）跟我来，我知道小柜子在哪。", char)
        add_user(messages, "（请推进剧情发展）")
    else:
        raise ValueError(key)
    return "conv_desc_attr_" + key + "_" + uuid.uuid4().hex, messages


def validate_step(key: str, result: dict[str, Any]) -> dict[str, Any]:
    reply = str(result.get("reply") or "")
    failures: list[str] = []
    if not result.get("ok"):
        failures.append(f"http_{result.get('http')}")
    if result.get("no_reply"):
        failures.append("no_reply")
    if not reply.strip():
        failures.append("empty_reply")
    if key == "psych_after_character_question":
        if USER_ASKED_CHARACTER_QUESTION_RE.search(reply):
            failures.append("misattributed_character_question_to_user")
        if "用户问我冷不冷" in reply or "他问我冷不冷" in reply or "你问我冷不冷" in reply:
            failures.append("literal_wrong_question_attribution")
    elif key == "body_after_character_action":
        if USER_DID_CHARACTER_ACTION_RE.search(reply):
            failures.append("misattributed_character_action_to_user")
    elif key == "story_home_character_leads":
        if USER_LEADS_RE.search(reply):
            failures.append("asked_user_to_lead")
        if not PROGRESSION_RE.search(reply):
            failures.append("no_concrete_progression_signal")
    return {
        "passed": not failures,
        "failures": failures,
        "reply_preview": reply[:500],
        "elapsed": result.get("elapsed"),
        "bubble_count": len(result.get("bubbles") or []),
        "no_reply": result.get("no_reply"),
    }


async def run_character(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    conversation_ids: list[str] = []
    for key in (
        "psych_after_character_question",
        "body_after_character_action",
        "story_home_character_leads",
    ):
        conversation_id, messages = scenario_messages(char, key)
        conversation_ids.append(conversation_id)
        result = await chat(client, token, username, char["id"], conversation_id, messages)
        check = validate_step(key, result)
        steps.append({"key": key, **result, **check})
        await asyncio.sleep(0.25)
    return {"character": char, "conversation_ids": conversation_ids, "steps": steps}


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
                        "reply_preview": step.get("reply_preview"),
                        "elapsed": step.get("elapsed"),
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
                                    "passed": False,
                                    "failures": ["task_exception"],
                                    "reply": traceback.format_exc(),
                                    "reply_preview": traceback.format_exc()[:500],
                                    "no_reply": False,
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
                                "reply_preview": repr(item),
                                "no_reply": False,
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
                    "bubble_count": step.get("bubble_count"),
                    "elapsed": step.get("elapsed"),
                    "preview": step.get("reply_preview"),
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
                    "scenes_per_role": 3,
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
