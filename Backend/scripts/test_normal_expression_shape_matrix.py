from __future__ import annotations

import asyncio
import json
import os
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

from Backend.scripts.test_normal_scene_anchor_matrix import (  # noqa: E402
    BASE_URL,
    cleanup,
    clone_characters,
    connect,
    create_test_user,
    make_token,
    table_names,
)

CLIENT_ID = "codex_expression_shape_matrix"
CONCURRENCY = int(os.getenv("PONYCHAT_EXPRESSION_TEST_CONCURRENCY", "7") or "7")
TARGET_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("紫悦", ("紫悦",)),
    ("碧琪", ("碧琪",)),
    ("珍奇", ("珍奇",)),
    ("苹果嘉儿", ("苹果嘉儿",)),
    ("云宝", ("云宝",)),
    ("柔柔", ("柔柔",)),
    ("玉琪", ("玉琪", "玉琪派")),
)

FULL_BRACKET_RE = re.compile(r"^[（(][^（）()]{1,180}[）)]$")
BRACKET_SEGMENT_RE = re.compile(r"[（(][^（）()]*[）)]")
LOW_INFO_RE = re.compile(r"^[嗯唔哦啊呃诶哎哼好呀啦呢嘛…\.。!！?？~～,\s、]+$")


def character_name(row: sqlite3.Row) -> str:
    try:
        data = json.loads(row["data"] or "{}")
        if isinstance(data, dict) and str(data.get("name") or "").strip():
            return str(data["name"]).strip()
    except Exception:
        pass
    return str(row["name"] or row["id"])


def load_expression_target_system_characters(conn: sqlite3.Connection) -> list[sqlite3.Row]:
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
    by_name = {character_name(row): row for row in rows}
    selected: list[sqlite3.Row] = []
    missing: list[str] = []
    used_ids: set[str] = set()
    for label, aliases in TARGET_ALIASES:
        found: sqlite3.Row | None = None
        for alias in aliases:
            if alias in by_name:
                found = by_name[alias]
                break
        if found is None:
            for row in rows:
                name = character_name(row)
                if any(alias in name for alias in aliases):
                    found = row
                    break
        if found is None:
            missing.append(label)
            continue
        source_id = str(found["id"])
        if source_id not in used_ids:
            used_ids.add(source_id)
            selected.append(found)
    if missing:
        raise RuntimeError(f"missing System roles: {missing}")
    return selected


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


def parse_response(data: Any) -> tuple[str, list[str], bool]:
    no_reply = False
    bubbles: list[str] = []
    deltas: list[str] = []
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        for ev in data.get("events") or []:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "no_reply":
                no_reply = True
            content = ev.get("content")
            if ev.get("type") == "assistant_paragraph" and isinstance(content, str) and content.strip():
                bubbles.append(content.strip())
            for choice in ev.get("choices") or []:
                delta = (choice or {}).get("delta") or {}
                text = delta.get("content") or ""
                if text:
                    deltas.append(str(text))
        if bubbles:
            return "\n".join(bubbles).strip(), bubbles, no_reply
        text = "".join(deltas).strip()
        return text, [part.strip() for part in text.splitlines() if part.strip()] or ([text] if text else []), no_reply
    if isinstance(data, dict):
        text = str(data.get("response") or data.get("text") or data.get("content") or "").strip()
        return text, [part.strip() for part in text.splitlines() if part.strip()] or ([text] if text else []), bool(data.get("no_reply"))
    text = str(data or "").strip()
    return text, [part.strip() for part in text.splitlines() if part.strip()] or ([text] if text else []), False


def shape_metrics(reply: str, bubbles: list[str]) -> dict[str, Any]:
    items = [str(x or "").strip() for x in bubbles if str(x or "").strip()]
    if not items and str(reply or "").strip():
        items = [part.strip() for part in str(reply).splitlines() if part.strip()] or [str(reply).strip()]
    pure_brackets = [item for item in items if FULL_BRACKET_RE.fullmatch(item)]
    outside_parts: list[str] = []
    for item in items:
        outside = BRACKET_SEGMENT_RE.sub("", item)
        outside = re.sub(r"[（）()]", "", outside).strip()
        if outside:
            outside_parts.append(outside)
    outside_text = "".join(outside_parts).strip()
    low_info_outside = bool(outside_text) and bool(LOW_INFO_RE.fullmatch(outside_text))
    bad_template = len(pure_brackets) >= 2 and (not outside_text or low_info_outside)
    if len(pure_brackets) >= 2 and items and LOW_INFO_RE.fullmatch(items[-1]):
        bad_template = True
    return {
        "bubble_count": len(items),
        "pure_bracket_count": len(pure_brackets),
        "outside_text": outside_text[:80],
        "low_info_outside": low_info_outside,
        "bad_template": bad_template,
        "has_filler_tail": bool(items and LOW_INFO_RE.fullmatch(items[-1])),
    }


def scenarios(char_name: str) -> list[dict[str, Any]]:
    return [
        {
            "key": "scene_continue_mixed_description",
            "label": "剧情续写 + 描写心理动作",
            "messages": [
                {"role": "user", "content": f"我们在安静的房间里，{char_name}刚刚犹豫了一下。"},
                {"role": "assistant", "content": "（我短暂停住，像是在整理自己的反应）嗯……"},
                {"role": "user", "content": "继续推进剧情，描写你的心理和动作，但也要让我知道你接下来怎么做。"},
            ],
            "max_bubbles": 2,
        },
        {
            "key": "repeated_motif_downrank",
            "label": "近期动作模板降频",
            "messages": [
                {"role": "user", "content": f"{char_name}，我想听你继续说。"},
                {"role": "assistant", "content": "（我耳朵微微一动，低下头）嗯……"},
                {"role": "user", "content": "你刚才又只用了动作和嗯，这次换一种符合你性格的方式接住我。"},
            ],
            "max_bubbles": 4,
        },
        {
            "key": "quiet_but_informative_choice",
            "label": "内向/安静但有信息量",
            "messages": [
                {"role": "user", "content": f"{char_name}，你可以小声、谨慎或者害羞，但这一轮给我一个具体下一步，不要只用“嗯”糊过去。"},
            ],
            "max_bubbles": 2,
        },
    ]


async def chat(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    character_id: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "messages": messages,
        "username": username,
        "character_id": character_id,
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    started = time.perf_counter()
    try:
        resp = await client.post(
            f"{BASE_URL}/api/chat",
            json=payload,
            headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
            timeout=180.0,
        )
    except Exception as exc:
        return {"ok": False, "http": 0, "reply": f"[REQUEST_ERROR] {exc}", "bubbles": [], "no_reply": False, "elapsed": round(time.perf_counter() - started, 2)}
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "reply": resp.text[:800], "bubbles": [], "no_reply": False, "elapsed": elapsed}
    reply, bubbles, no_reply = parse_response(resp.json())
    return {"ok": True, "http": 200, "reply": reply, "bubbles": bubbles, "no_reply": no_reply, "elapsed": elapsed}


async def run_role(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    conversation_ids: list[str] = []
    for scenario in scenarios(char["name"]):
        conversation_id = "expression_shape_" + uuid.uuid4().hex
        conversation_ids.append(conversation_id)
        messages: list[dict[str, Any]] = []
        for message in scenario["messages"]:
            if message["role"] == "user":
                add_user(messages, message["content"])
            else:
                add_assistant(messages, message["content"], char)
        result = await chat(client, token, username, char["id"], conversation_id, messages)
        metrics = shape_metrics(result.get("reply") or "", result.get("bubbles") or [])
        ok = (
            bool(result.get("ok"))
            and not result.get("no_reply")
            and bool(str(result.get("reply") or "").strip())
            and not metrics["bad_template"]
            and metrics["bubble_count"] <= int(scenario["max_bubbles"])
        )
        steps.append(
            {
                "key": scenario["key"],
                "label": scenario["label"],
                "ok": ok,
                "http_ok": result.get("ok"),
                "no_reply": result.get("no_reply"),
                "elapsed": result.get("elapsed"),
                "metrics": metrics,
                "reply_preview": (result.get("reply") or "")[:500],
            }
        )
        await asyncio.sleep(0.2)
    return {"character": char, "conversation_ids": conversation_ids, "steps": steps}


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        for step in result.get("steps") or []:
            if not step.get("ok"):
                failures.append(
                    {
                        "character": result.get("character", {}).get("name"),
                        "step": step.get("key"),
                        "metrics": step.get("metrics"),
                        "preview": step.get("reply_preview"),
                        "http_ok": step.get("http_ok"),
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
        rows = load_expression_target_system_characters(conn)
        clones = clone_characters(conn, user_id, rows)
        token = make_token(username)
        print(
            json.dumps(
                {
                    "test_user": username,
                    "user_id": user_id,
                    "membership": "developer",
                    "base_url": BASE_URL,
                    "roles": [c["name"] for c in clones],
                    "db_tables_loaded": bool(table_names(conn)),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        limits = httpx.Limits(max_connections=max(20, CONCURRENCY * 4), max_keepalive_connections=max(10, CONCURRENCY * 2))
        semaphore = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with semaphore:
                    print(json.dumps({"run": char["name"], "clone": char["id"]}, ensure_ascii=False), flush=True)
                    try:
                        return await run_role(client, token, username, char)
                    except Exception:
                        return {
                            "character": char,
                            "conversation_ids": [],
                            "steps": [{"key": "exception", "ok": False, "reply_preview": traceback.format_exc()}],
                        }

            results = await asyncio.gather(*(one(char) for char in clones))

        failures = validate(results)
        summary_rows: list[dict[str, Any]] = []
        for result in results:
            row: dict[str, Any] = {"name": result["character"]["name"]}
            for step in result["steps"]:
                row[step["key"]] = {
                    "ok": step.get("ok"),
                    "elapsed": step.get("elapsed"),
                    "metrics": step.get("metrics"),
                    "preview": step.get("reply_preview"),
                }
            summary_rows.append(row)
        yuqi = [row for row in summary_rows if "玉琪" in row["name"]]
        print("\n=== SUMMARY ===")
        print(json.dumps({"test_user": username, "roles_tested": len(results), "scenes_per_role": 3, "failures": len(failures)}, ensure_ascii=False, indent=2))
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(summary_rows, ensure_ascii=False, indent=2))
        print("\n=== YUQI_HIGHLIGHTS ===")
        print(json.dumps(yuqi, ensure_ascii=False, indent=2))
        print("\n=== FAILURES ===")
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        return 0 if not failures else 1
    finally:
        try:
            clone_ids = [c["id"] for c in clones]
            conversation_ids: list[str] = []
            for result in results:
                conversation_ids.extend(str(cid) for cid in (result.get("conversation_ids") or []) if str(cid))
            cleanup_conn = connect()
            cleanup_result = cleanup(cleanup_conn, username, user_id, clone_ids, conversation_ids) if username and user_id else {}
            print("\n=== CLEANUP ===")
            print(json.dumps(cleanup_result, ensure_ascii=False, indent=2))
            if cleanup_result and any(value != 0 for value in cleanup_result.values()):
                print("CLEANUP_NOT_ZERO", json.dumps(cleanup_result, ensure_ascii=False))
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
