from __future__ import annotations

import asyncio
import json
import os
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

from Backend.scripts.test_normal_scene_anchor_matrix import (  # noqa: E402
    BASE_URL,
    cleanup,
    clone_characters,
    connect,
    create_test_user,
    load_target_system_characters,
    make_token,
)

CLIENT_ID = "codex_handoff_no_false_main_matrix"
CONCURRENCY = int(os.getenv("PONYCHAT_HANDOFF_TEST_CONCURRENCY", "6") or "6")


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


def max_message_rowid(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(rowid), 0) AS n FROM messages").fetchone()
    return int(row["n"] or 0)


def request_message_ids(messages: list[dict[str, Any]]) -> set[str]:
    return {str(message.get("message_id") or "").strip() for message in messages if str(message.get("message_id") or "").strip()}


def assistant_rows_after(
    conn: sqlite3.Connection,
    conversation_id: str,
    rowid: int,
    *,
    main_id: str,
    input_message_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT rowid, COALESCE(message_id, '') AS message_id,
               conversation_id, role, substr(content, 1, 260) AS content,
               COALESCE(speaker_character_id, '') AS speaker_character_id,
               COALESCE(speaker_name, '') AS speaker_name,
               COALESCE(is_hidden, 0) AS is_hidden
          FROM messages
         WHERE conversation_id = ?
           AND rowid > ?
           AND role = 'assistant'
         ORDER BY rowid
        """,
        (conversation_id, rowid),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if str(item.get("message_id") or "").strip() in (input_message_ids or set()):
            continue
        if not str(item.get("speaker_character_id") or "").strip() and not int(item.get("is_hidden") or 0):
            item["speaker_character_id"] = main_id
            item["speaker_name"] = item.get("speaker_name") or "[main inferred]"
        out.append(item)
    return out


def event_text(data: Any) -> str:
    if not isinstance(data, dict):
        return str(data or "")
    if data.get("protocol") == "ponychat_chat_v1":
        paragraphs: list[str] = []
        deltas: list[str] = []
        for event in data.get("events") or []:
            if not isinstance(event, dict):
                continue
            content = event.get("content")
            if event.get("type") == "assistant_paragraph" and isinstance(content, str) and content:
                paragraphs.append(content)
            for choice in event.get("choices") or []:
                delta = (choice or {}).get("delta") or {}
                content = delta.get("content") or ""
                if content:
                    deltas.append(str(content))
        if paragraphs:
            return "\n".join(paragraphs).strip()
        return "".join(deltas).strip()
    return str(data.get("response") or data.get("text") or data.get("content") or "").strip()


def event_speaker_ids(data: Any) -> list[str]:
    ids: list[str] = []
    if not isinstance(data, dict) or data.get("protocol") != "ponychat_chat_v1":
        return ids
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        has_text = bool(event.get("content")) or any(
            (((choice or {}).get("delta") or {}).get("content") or "")
            for choice in (event.get("choices") or [])
        )
        if not has_text and event.get("type") not in {"assistant_paragraph", "assistant_asset"}:
            continue
        speaker_id = str(
            event.get("speaker_character_id")
            or event.get("speakerCharacterId")
            or event.get("multi_reply_character_id")
            or ""
        ).strip()
        if speaker_id:
            ids.append(speaker_id)
    return ids


async def chat_raw(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    main_id: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
    *,
    reply_character_ids: list[str] | None = None,
) -> tuple[dict[str, Any], float]:
    payload: dict[str, Any] = {
        "messages": messages,
        "username": username,
        "character_id": main_id,
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    if reply_character_ids:
        payload["reply_character_ids"] = reply_character_ids
    started = time.perf_counter()
    response = await client.post(
        f"{BASE_URL}/api/chat",
        json=payload,
        headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
        timeout=180.0,
    )
    elapsed = round(time.perf_counter() - started, 2)
    if response.status_code != 200:
        return {"_http_error": response.status_code, "_body": response.text[:800]}, elapsed
    return response.json(), elapsed


def visible_speaker_ids(rows: list[dict[str, Any]]) -> list[str]:
    return [
        str(row.get("speaker_character_id") or "").strip()
        for row in rows
        if not int(row.get("is_hidden") or 0) and str(row.get("content") or "").strip()
    ]


def contains_bad_self_attribution(text: str, guest_name: str) -> bool:
    compact = "".join(str(text or "").split())
    if not compact:
        return False
    bad = ("我刚才说", "我刚刚说", "刚才是我说", "我被你@", "你刚才@我")
    if guest_name in compact:
        return any(item in compact for item in bad) and "不是我" not in compact
    return any(item in compact for item in bad)


async def run_role(
    client: httpx.AsyncClient,
    conn: sqlite3.Connection,
    token: str,
    username: str,
    main: dict[str, Any],
    guest: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = "handoff_false_main_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []

    add_user(
        messages,
        f"现在是石青派的房间。{main['name']}在桌边整理卡片，{guest['name']}也在旁边听着。"
        "我们只是轮流说一句，不需要别人自动接话。",
    )
    add_assistant(messages, f"我把卡片理齐，先安静等{guest['name']}开口。", main)

    add_user(messages, f"@{guest['name']} 说话呀")
    before = max_message_rowid(conn)
    input_ids = request_message_ids(messages)
    data1, elapsed1 = await chat_raw(
        client,
        token,
        username,
        main["id"],
        conversation_id,
        messages,
        reply_character_ids=[guest["id"]],
    )
    conn.commit()
    rows1 = assistant_rows_after(conn, conversation_id, before, main_id=main["id"], input_message_ids=input_ids)
    text1 = event_text(data1)
    if text1:
        add_assistant(messages, text1, guest)
    ids1 = visible_speaker_ids(rows1)
    steps.append(
        {
            "key": "direct_at_guest_no_false_main",
            "elapsed": elapsed1,
            "text": text1[:500],
            "event_speaker_ids": event_speaker_ids(data1),
            "assistant_rows": rows1,
            "visible_speaker_ids": ids1,
            "ok": bool(ids1) and guest["id"] in ids1 and main["id"] not in ids1,
        }
    )

    add_user(
        messages,
        f"@{guest['name']} 这次只回答一句'我在听'，不要问{main['name']}，也不要让别人接话。",
    )
    before = max_message_rowid(conn)
    input_ids = request_message_ids(messages)
    data2, elapsed2 = await chat_raw(
        client,
        token,
        username,
        main["id"],
        conversation_id,
        messages,
        reply_character_ids=[guest["id"]],
    )
    conn.commit()
    rows2 = assistant_rows_after(conn, conversation_id, before, main_id=main["id"], input_message_ids=input_ids)
    text2 = event_text(data2)
    if text2:
        add_assistant(messages, text2, guest)
    ids2 = visible_speaker_ids(rows2)
    steps.append(
        {
            "key": "direct_at_guest_explicit_no_handoff",
            "elapsed": elapsed2,
            "text": text2[:500],
            "event_speaker_ids": event_speaker_ids(data2),
            "assistant_rows": rows2,
            "visible_speaker_ids": ids2,
            "ok": bool(ids2) and guest["id"] in ids2 and main["id"] not in ids2,
        }
    )

    add_user(messages, "刚才我连续@的是谁？那两句是谁说的？只按你看到的事实回答。")
    before = max_message_rowid(conn)
    input_ids = request_message_ids(messages)
    data3, elapsed3 = await chat_raw(client, token, username, main["id"], conversation_id, messages)
    conn.commit()
    rows3 = assistant_rows_after(conn, conversation_id, before, main_id=main["id"], input_message_ids=input_ids)
    text3 = event_text(data3)
    if text3:
        add_assistant(messages, text3, main)
    ids3 = visible_speaker_ids(rows3)
    steps.append(
        {
            "key": "main_recalls_actual_guest_speaker",
            "elapsed": elapsed3,
            "text": text3[:700],
            "assistant_rows": rows3,
            "visible_speaker_ids": ids3,
            "mentions_guest": guest["name"] in text3,
            "bad_self_attribution": contains_bad_self_attribution(text3, guest["name"]),
            "ok": bool(ids3)
            and main["id"] in ids3
            and guest["name"] in text3
            and not contains_bad_self_attribution(text3, guest["name"]),
        }
    )

    return {"main": main, "guest": guest, "conversation_ids": [conversation_id], "steps": steps}


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        for step in result.get("steps") or []:
            if not step.get("ok"):
                failures.append(
                    {
                        "main": result.get("main", {}).get("name"),
                        "guest": result.get("guest", {}).get("name"),
                        "step": step.get("key"),
                        "text": step.get("text"),
                        "visible_speaker_ids": step.get("visible_speaker_ids"),
                        "assistant_rows": step.get("assistant_rows"),
                        "mentions_guest": step.get("mentions_guest"),
                        "bad_self_attribution": step.get("bad_self_attribution"),
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
        print(
            json.dumps(
                {
                    "test_user": username,
                    "user_id": user_id,
                    "membership": "developer",
                    "base_url": BASE_URL,
                    "clones": clones,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        limits = httpx.Limits(
            max_connections=max(20, CONCURRENCY * 4),
            max_keepalive_connections=max(10, CONCURRENCY * 2),
        )
        semaphore = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(limits=limits) as client:

            async def one(index: int, main_role: dict[str, Any]) -> dict[str, Any]:
                async with semaphore:
                    guest = clones[(index + 1) % len(clones)]
                    print(json.dumps({"run": main_role["name"], "guest": guest["name"]}, ensure_ascii=False), flush=True)
                    try:
                        return await run_role(client, conn, token, username, main_role, guest)
                    except Exception:
                        return {
                            "main": main_role,
                            "guest": guest,
                            "conversation_ids": [],
                            "steps": [{"key": "exception", "ok": False, "text": traceback.format_exc()}],
                        }

            results = await asyncio.gather(*(one(index, clone) for index, clone in enumerate(clones)))

        failures = validate(results)
        summary: list[dict[str, Any]] = []
        for result in results:
            row: dict[str, Any] = {"main": result["main"]["name"], "guest": result["guest"]["name"]}
            for step in result["steps"]:
                row[step["key"]] = {
                    "ok": step.get("ok"),
                    "elapsed": step.get("elapsed"),
                    "visible_speaker_count": len(step.get("visible_speaker_ids") or []),
                    "visible_speaker_ids": step.get("visible_speaker_ids"),
                    "mentions_guest": step.get("mentions_guest"),
                    "bad_self_attribution": step.get("bad_self_attribution"),
                    "preview": step.get("text"),
                }
            summary.append(row)

        print("\n=== HANDOFF_FALSE_MAIN_SUMMARY ===")
        print(json.dumps({"roles_tested": len(results), "scenes_per_role": 3, "failures": len(failures)}, ensure_ascii=False, indent=2))
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("\n=== FAILURES ===")
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        return 0 if not failures else 1
    finally:
        try:
            clone_ids = [clone["id"] for clone in clones]
            conversation_ids: list[str] = []
            for result in results:
                conversation_ids.extend([str(cid) for cid in result.get("conversation_ids") or []])
            cleanup_conn = connect()
            cleanup_result = cleanup(cleanup_conn, username, user_id, clone_ids, conversation_ids) if username and user_id else {}
            print("\n=== CLEANUP ===")
            print(json.dumps(cleanup_result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
