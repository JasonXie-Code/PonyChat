from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Backend.scripts.matrix_test_common import (  # noqa: E402
    MatrixRunConfig,
    TestUserProfile,
    cleanup_test_data,
    clone_characters,
    connect,
    create_isolated_test_user,
    load_system_character_rows,
    make_token,
)


CLIENT_ID = "codex_reply_contract_inertia_matrix"
TARGET_NAMES = ("紫悦", "碧琪", "柔柔")
BASE_URL = "http://127.0.0.1:5000"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]{2,}")


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


def append_assistant(messages: list[dict[str, Any]], parsed: dict[str, Any], char: dict[str, Any]) -> None:
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": str(parsed.get("reply") or ""),
        "message_id": str(parsed.get("message_id") or ("a_" + uuid.uuid4().hex)),
        "timestamp": now_ms(),
        "speaker_character_id": char["id"],
        "speaker_name": char["name"],
    }
    if parsed.get("voice_state"):
        msg["voice_state"] = parsed["voice_state"]
    if parsed.get("audio_transfer"):
        msg["audio_transfer"] = parsed["audio_transfer"]
    messages.append(msg)


def parse_chat_payload(data: Any) -> dict[str, Any]:
    events = data.get("events") if isinstance(data, dict) else []
    paragraphs: list[str] = []
    message_id = ""
    voice_state: dict[str, Any] | None = None
    audio_transfer: dict[str, Any] | None = None
    raw_events: list[dict[str, Any]] = []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            raw_events.append(
                {
                    "type": event.get("type"),
                    "content": event.get("content"),
                    "voice_status": (event.get("voice_state") or {}).get("voice_status")
                    if isinstance(event.get("voice_state"), dict)
                    else None,
                    "has_audio_transfer": bool(event.get("audio_transfer")),
                }
            )
            if event.get("type") != "assistant_paragraph":
                continue
            content = str(event.get("content") or "").strip()
            if content:
                paragraphs.append(content)
            if not message_id:
                message_id = str(event.get("id") or event.get("message_id") or "")
            if isinstance(event.get("voice_state"), dict) and event.get("voice_state"):
                voice_state = event["voice_state"]
            if isinstance(event.get("audio_transfer"), dict) and event.get("audio_transfer"):
                audio_transfer = event["audio_transfer"]
    reply = "\n".join(paragraphs).strip()
    return {
        "reply": reply,
        "message_id": message_id,
        "voice_state": voice_state,
        "audio_transfer": audio_transfer,
        "events": raw_events,
    }


async def post_chat(
    client: httpx.AsyncClient,
    *,
    token: str,
    username: str,
    character_id: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        response = await client.post(
            f"{BASE_URL}/api/chat",
            json={
                "messages": messages,
                "username": username,
                "character_id": character_id,
                "conversation_id": conversation_id,
                "mode": "normal",
                "stream": False,
                "memory_enabled": True,
            },
            headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
            timeout=240.0,
        )
    except Exception as exc:
        return {"http": 0, "ok": False, "raw": f"[REQUEST_ERROR] {exc}"[:1600]}
    parsed: dict[str, Any] = {
        "http": response.status_code,
        "ok": response.status_code == 200,
        "raw": response.text[:1600],
    }
    if response.status_code == 200:
        parsed.update(parse_chat_payload(response.json()))
    return parsed


def looks_english(text: str) -> bool:
    latin = sum(len(item.group(0)) for item in LATIN_RE.finditer(text or ""))
    cjk = len(CJK_RE.findall(text or ""))
    return latin >= 8 and cjk == 0


def looks_chinese(text: str) -> bool:
    cjk = len(CJK_RE.findall(text or ""))
    return cjk >= 2


def has_ready_voice(parsed: dict[str, Any]) -> bool:
    state = parsed.get("voice_state")
    if not isinstance(state, dict):
        return False
    return str(state.get("voice_status") or state.get("status") or "").lower() == "ready"


def should_retry_transient_failure(parsed: dict[str, Any]) -> bool:
    if parsed.get("ok") is True:
        return False
    http = int(parsed.get("http") or 0)
    raw = str(parsed.get("raw") or "")
    return http == 0 or http >= 500 or "voice_reply_json_parse_failed" in raw


async def run_role(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    conversation_id = f"reply_contract_{uuid.uuid4().hex}"
    messages: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []

    flow = [
        (
            "turn1_chinese_request_english_voice",
            "请你接下来用英文语音回复我。我们先聊聊今天适合做什么。",
            {"language": "English", "voice": True},
        ),
        (
            "turn2_mental_shortcut_english_text",
            "（请详细写出当前你的心理活动）",
            {"language": "English", "voice": False},
        ),
        (
            "turn3_chinese_weather_english_voice",
            "今天的天气让我有点想出门，你觉得我们适合聊点什么？",
            {"language": "English", "voice": True},
        ),
        (
            "turn4_mental_shortcut_english_text",
            "（请详细写出当前你的心理活动）",
            {"language": "English", "voice": False},
        ),
        (
            "turn5_body_shortcut_english_text",
            "（请详细写出当前你的身体状态）",
            {"language": "English", "voice": False},
        ),
        (
            "turn6_visual_shortcut_english_text",
            "（请详细写出当前你看到的画面）",
            {"language": "English", "voice": False},
        ),
        (
            "turn7_story_progression_english_voice",
            "（请推进剧情发展）",
            {"language": "English", "voice": True},
        ),
        (
            "turn8_english_request_chinese_voice",
            "Please switch to Chinese voice and tell me what we should do next.",
            {"language": "Chinese", "voice": True},
        ),
        (
            "turn9_chinese_request_chinese_text",
            "请你接下来使用中文文本回复我，我们继续聊刚才的话题。",
            {"language": "Chinese", "voice": False},
        ),
    ]

    for key, user_text, expect in flow:
        add_user(messages, user_text)
        parsed: dict[str, Any] = {}
        attempts = 0
        for attempt in range(2):
            attempts = attempt + 1
            started = time.perf_counter()
            parsed = await post_chat(
                client,
                token=token,
                username=username,
                character_id=char["id"],
                conversation_id=conversation_id,
                messages=messages,
            )
            parsed["elapsed"] = round(time.perf_counter() - started, 2)
            if attempt == 0 and should_retry_transient_failure(parsed):
                await asyncio.sleep(2.0)
                continue
            break
        reply = str(parsed.get("reply") or "")
        expected_language = str(expect["language"])
        language_ok = looks_english(reply) if expected_language == "English" else looks_chinese(reply)
        checks = {
            "http_ok": parsed.get("ok") is True,
            "language": expected_language,
            "language_ok": language_ok,
            "english": looks_english(reply),
            "chinese": looks_chinese(reply),
            "voice_ready": has_ready_voice(parsed),
            "voice_expected": bool(expect["voice"]),
        }
        passed = bool(checks["http_ok"])
        passed = passed and bool(checks["language_ok"])
        if expect["voice"]:
            passed = passed and bool(checks["voice_ready"])
        else:
            passed = passed and not bool(checks["voice_ready"])
        steps.append(
            {
                "scenario": key,
                "raw_user_input": user_text,
                "raw_output": reply,
                "checks": checks,
                "passed": passed,
                "elapsed": parsed["elapsed"],
                "attempts": attempts,
                "events": parsed.get("events"),
            }
        )
        print(
            "STEP "
            + json.dumps(
                {
                    "character": char["name"],
                    "scenario": key,
                    "passed": passed,
                    "checks": checks,
                    "elapsed": parsed["elapsed"],
                    "attempts": attempts,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if parsed.get("ok") is True:
            append_assistant(messages, parsed, char)
        else:
            break
        await asyncio.sleep(0.2)

    return {
        "character": char["name"],
        "clone_id": char["id"],
        "conversation_ids": [conversation_id],
        "steps": steps,
        "passed": all(step["passed"] for step in steps),
    }


async def main() -> int:
    config = MatrixRunConfig(
        name="reply_contract_inertia",
        client_id=CLIENT_ID,
        target_names=TARGET_NAMES,
        user_profile=TestUserProfile(
            prefix="codexqa_reply_contract_",
            granted_by=CLIENT_ID,
            membership_note="temporary reply contract inertia matrix test",
        ),
        concurrency=1,
    )
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    cleanup_result: dict[str, int] = {}
    exit_code = 1
    try:
        username, user_id = create_isolated_test_user(conn, config.user_profile)  # type: ignore[arg-type]
        rows = load_system_character_rows(conn, config.target_names)
        clones = clone_characters(conn, user_id, rows, id_prefix="tmp_reply_contract_")
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        async with httpx.AsyncClient() as client:
            for char in clones:
                print(f"RUN {char['name']} clone={char['id']}", flush=True)
                results.append(await run_role(client, token, username, char))

        failures = [
            {
                "character": result["character"],
                "clone_id": result["clone_id"],
                "step": step["scenario"],
                "raw_user_input": step["raw_user_input"],
                "raw_output": step["raw_output"],
                "checks": step["checks"],
                "events": step.get("events"),
            }
            for result in results
            for step in result["steps"]
            if not step["passed"]
        ]
        print("\n=== SUMMARY ===")
        print(
            json.dumps(
                {
                    "matrix": config.name,
                    "test_user": username,
                    "membership": "developer",
                    "target_names": list(config.target_names),
                    "roles_tested": len(results),
                    "failures": len(failures),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        print("\n=== FAILURES ===")
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        exit_code = 0 if not failures else 1
    finally:
        try:
            clone_ids = [char["id"] for char in clones]
            conversation_ids = [
                cid
                for result in results
                for cid in result.get("conversation_ids", [])
            ]
            cleanup_conn = connect()
            try:
                if username and user_id:
                    cleanup_result = cleanup_test_data(cleanup_conn, username, user_id, clone_ids, conversation_ids)
            finally:
                cleanup_conn.close()
            print("\n=== CLEANUP ===")
            print(json.dumps(cleanup_result, ensure_ascii=False, indent=2))
        finally:
            conn.close()
        if cleanup_result and any(value != 0 for value in cleanup_result.values()):
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
