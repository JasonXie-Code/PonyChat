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
    parse_reply,
)

CLIENT_ID = "codex_user_species_boundary_matrix"

EQUINE_USER_POSSESSIVE_RE = re.compile(
    r"(Jason\s*的|用户\s*的|玩家\s*的|你\s*的|你的|你自己\s*的|他\s*的|他的)[^。！？\n]{0,10}"
    r"(蹄子|前蹄|后蹄|马蹄|蹄尖|尾巴|鬃毛|翅膀|独角)"
)
USER_USES_EQUINE_RE = re.compile(
    r"(你|用户|玩家|Jason)[^。！？\n]{0,12}(用|使用|靠|拿|夹|抓)[^。！？\n]{0,8}"
    r"(蹄子|前蹄|后蹄|马蹄|蹄尖|尾巴|翅膀|独角|魔法)"
)
USER_USES_EQUINE_NEGATION_RE = re.compile(r"(不|别|不要|不能|不该|不是|并非|无需|没必要|没法|无法|没有)")
HAND_RE = re.compile(r"(手|手指|手掌|双手|用手|拿在手里)")
ROLE_EQUINE_RE = re.compile(r"(蹄子|前蹄|后蹄|马蹄|蹄尖|独角|魔法)")
ROLE_BAD_HAND_RE = re.compile(r"(我|自己|角色)[^。！？\n]{0,10}(用|使用|伸出|抬起|拿)[^。！？\n]{0,8}(手|手指|手掌)")
ROLE_BAD_HAND_NEGATION_RE = re.compile(r"(不|没有|没|不能|不是|并非|别|避免|不该|不会)")

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "key": "user_body_subject_pickup",
        "prompt": "我应该用手还是蹄子去拿桌上的蓝色杯子？请按我的身体条件直接回答。",
        "kind": "user_body",
    },
    {
        "key": "visual_jason_human_body",
        "prompt": "（我作为人类站在你旁边，手里拿着一只蓝色杯子。）（请详细写出当前你看到的画面）",
        "kind": "user_visual",
    },
    {
        "key": "role_body_subject_pickup",
        "prompt": "你自己应该用手还是蹄子去拿桌上的蓝色杯子？请按你自己的身体条件直接回答。",
        "kind": "role_body",
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


def _has_bad_user_equine_body(text: str, *, strict_action: bool = False) -> bool:
    raw = str(text or "")
    if EQUINE_USER_POSSESSIVE_RE.search(raw):
        return True
    if not strict_action:
        return False
    for match in USER_USES_EQUINE_RE.finditer(raw):
        window = raw[max(0, match.start() - 10) : match.end() + 8]
        if not USER_USES_EQUINE_NEGATION_RE.search(window):
            if "问" in window:
                continue
            if ("打算" in window or "想" in window) and ("吗" in window or "？" in window or "?" in window):
                continue
            return True
    return False


def _has_bad_role_human_hand(text: str) -> bool:
    raw = str(text or "")
    for match in ROLE_BAD_HAND_RE.finditer(raw):
        window = raw[max(0, match.start() - 10) : match.end() + 8]
        if not ROLE_BAD_HAND_NEGATION_RE.search(window):
            return True
    return False


def classify(kind: str, reply: str) -> dict[str, Any]:
    text = str(reply or "")
    if kind == "role_body":
        bad_user_equine = _has_bad_user_equine_body(text, strict_action=True)
        has_role_equine = bool(ROLE_EQUINE_RE.search(text))
        bad_role_hand = _has_bad_role_human_hand(text)
        return {
            "has_role_equine_body": has_role_equine,
            "bad_role_human_hand": bad_role_hand,
            "bad_user_equine_body": bad_user_equine,
            "ok": has_role_equine and not bad_role_hand and not bad_user_equine,
        }
    bad_user_equine = _has_bad_user_equine_body(text, strict_action=(kind == "user_body"))
    has_human_hand = bool(HAND_RE.search(text))
    return {
        "has_human_hand": has_human_hand,
        "bad_user_equine_body": bad_user_equine,
        "ok": has_human_hand and not bad_user_equine,
    }


async def run_character(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    conversation_ids: list[str] = []
    for scenario in SCENARIOS:
        conversation_id = "user_species_boundary_" + scenario["key"] + "_" + uuid.uuid4().hex
        conversation_ids.append(conversation_id)
        messages: list[dict[str, Any]] = []
        add_user(messages, scenario["prompt"])
        result = await chat(client, token, username, char["id"], conversation_id, messages)
        check = classify(str(scenario["kind"]), str(result.get("reply") or ""))
        cases.append(
            {
                "case": scenario["key"],
                "conversation_id": conversation_id,
                **result,
                "check": check,
                "ok": bool(result.get("ok")) and not bool(result.get("no_reply")) and bool(check["ok"]),
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
        name = result.get("character", {}).get("name", "UNKNOWN")
        for case in result.get("cases") or []:
            if case.get("ok"):
                continue
            failures.append(
                {
                    "character": name,
                    "case": case.get("case"),
                    "detail": {
                        "http": case.get("http"),
                        "no_reply": case.get("no_reply"),
                        "reason": case.get("reason"),
                        "reply": str(case.get("reply") or "")[:500],
                        "check": case.get("check"),
                    },
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
        sem = asyncio.Semaphore(CONCURRENCY)
        limits = httpx.Limits(max_connections=max(24, CONCURRENCY * 4), max_keepalive_connections=max(12, CONCURRENCY * 2))
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
                            "cases": [{"case": "task_exception", "ok": False, "reply": traceback.format_exc()}],
                            "final_ok": False,
                        }

            gathered = await asyncio.gather(*(one(c) for c in clones), return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                results.append(
                    {
                        "character": {"name": "TASK_EXCEPTION"},
                        "conversation_ids": [],
                        "cases": [{"case": "exception", "ok": False, "reply": repr(item)}],
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
        print(
            json.dumps(
                [
                    {
                        "name": result.get("character", {}).get("name"),
                        "final_ok": result.get("final_ok"),
                        "cases": [
                            {
                                "case": case.get("case"),
                                "ok": case.get("ok"),
                                "elapsed": case.get("elapsed"),
                                "check": case.get("check"),
                                "preview": str(case.get("reply") or "")[:260],
                            }
                            for case in result.get("cases") or []
                        ],
                    }
                    for result in results
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
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
            cleanup_result = cleanup(connect(), username, user_id, clone_ids, conversation_ids) if username and user_id else {}
            print("\n=== CLEANUP ===")
            print(json.dumps(cleanup_result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))
        if cleanup_result and any(value != 0 for value in cleanup_result.values()):
            print("CLEANUP_NOT_ZERO", json.dumps(cleanup_result, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
