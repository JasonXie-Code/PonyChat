from __future__ import annotations

import asyncio
import json
import os
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


CLIENT_ID = "codex_reply_contract_at_inertia_matrix"
TARGET_NAMES = ("碧琪", "云宝", "柔柔")
BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
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


def parse_chat_payload(data: Any) -> dict[str, Any]:
    events = data.get("events") if isinstance(data, dict) else []
    paragraphs: list[str] = []
    message_id = ""
    voice_state: dict[str, Any] | None = None
    audio_transfer: dict[str, Any] | None = None
    speaker_character_id = ""
    speaker_name = ""
    raw_events: list[dict[str, Any]] = []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            raw_events.append(
                {
                    "type": event.get("type"),
                    "content": event.get("content"),
                    "error": event.get("error") or event.get("message") or event.get("detail"),
                    "speaker_character_id": event.get("speaker_character_id") or event.get("speakerCharacterId"),
                    "speaker_name": event.get("speaker_name") or event.get("speakerName"),
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
            if not speaker_character_id:
                speaker_character_id = str(
                    event.get("speaker_character_id") or event.get("speakerCharacterId") or ""
                ).strip()
            if not speaker_name:
                speaker_name = str(event.get("speaker_name") or event.get("speakerName") or "").strip()
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
        "speaker_character_id": speaker_character_id,
        "speaker_name": speaker_name,
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
            f"{BASE_URL.rstrip('/')}/api/chat",
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


def is_proactive_generation_lock(parsed: dict[str, Any]) -> bool:
    if int(parsed.get("http") or 0) != 409:
        return False
    raw = str(parsed.get("raw") or "")
    return "generation_locked" in raw and "scheduled_followup" in raw


async def cancel_proactive_lock(
    client: httpx.AsyncClient,
    *,
    token: str,
    username: str,
    character_id: str,
    conversation_id: str,
) -> dict[str, Any]:
    try:
        response = await client.post(
            f"{BASE_URL.rstrip('/')}/api/chat/cancel",
            json={
                "username": username,
                "character_id": character_id,
                "conversation_id": conversation_id,
                "client_id": CLIENT_ID,
                "reason": "normal_user_interrupt_proactive:reply_contract_at_inertia_matrix",
            },
            headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
            timeout=30.0,
        )
        return {"http": response.status_code, "raw": response.text[:600]}
    except Exception as exc:
        return {"http": 0, "raw": f"[CANCEL_ERROR] {exc}"[:600]}


def append_assistant(
    messages: list[dict[str, Any]],
    parsed: dict[str, Any],
    *,
    fallback_char: dict[str, Any],
) -> None:
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": str(parsed.get("reply") or ""),
        "message_id": str(parsed.get("message_id") or ("a_" + uuid.uuid4().hex)),
        "timestamp": now_ms(),
    }
    sid = str(parsed.get("speaker_character_id") or "").strip()
    sname = str(parsed.get("speaker_name") or "").strip()
    if sid:
        msg["speaker_character_id"] = sid
    if sname:
        msg["speaker_name"] = sname
    elif sid:
        msg["speaker_name"] = fallback_char["name"]
    if parsed.get("voice_state"):
        msg["voice_state"] = parsed["voice_state"]
    if parsed.get("audio_transfer"):
        msg["audio_transfer"] = parsed["audio_transfer"]
    messages.append(msg)


def looks_english(text: str) -> bool:
    latin = sum(len(item.group(0)) for item in LATIN_RE.finditer(text or ""))
    cjk = len(CJK_RE.findall(text or ""))
    return latin >= 8 and cjk == 0


def looks_chinese(text: str) -> bool:
    return len(CJK_RE.findall(text or "")) >= 2


def has_ready_voice(parsed: dict[str, Any]) -> bool:
    state = parsed.get("voice_state")
    if not isinstance(state, dict):
        return False
    return str(state.get("voice_status") or state.get("status") or "").lower() == "ready"


def should_retry_transient_failure(parsed: dict[str, Any]) -> bool:
    raw = str(parsed.get("raw") or "")
    if parsed.get("ok") is True:
        if not str(parsed.get("reply") or "").strip() and (
            "聊天生成失败" in raw
            or any(isinstance(event, dict) and event.get("error") for event in (parsed.get("events") or []))
        ):
            return True
        return False
    http = int(parsed.get("http") or 0)
    return http == 0 or http in {409, 423, 425, 429} or http >= 500 or "voice_reply_json_parse_failed" in raw


async def run_step(
    client: httpx.AsyncClient,
    *,
    token: str,
    username: str,
    conversation_id: str,
    character_id: str,
    messages: list[dict[str, Any]],
    user_text: str,
    expected_language: str,
    expected_voice: bool,
    expected_speaker: dict[str, Any],
    fallback_char: dict[str, Any],
    scenario: str,
) -> dict[str, Any]:
    add_user(messages, user_text)
    parsed: dict[str, Any] = {}
    attempts = 0
    lock_cancels: list[dict[str, Any]] = []
    for attempt in range(6):
        attempts = attempt + 1
        started = time.perf_counter()
        parsed = await post_chat(
            client,
            token=token,
            username=username,
            character_id=character_id,
            conversation_id=conversation_id,
            messages=messages,
        )
        parsed["elapsed"] = round(time.perf_counter() - started, 2)
        if is_proactive_generation_lock(parsed):
            cancel_result = await cancel_proactive_lock(
                client,
                token=token,
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
            )
            lock_cancels.append(cancel_result)
            await asyncio.sleep(1.5)
            continue
        if attempt < 5 and should_retry_transient_failure(parsed):
            await asyncio.sleep(2.0)
            continue
        break

    reply = str(parsed.get("reply") or "")
    actual_speaker_id = str(parsed.get("speaker_character_id") or fallback_char["id"]).strip()
    actual_speaker_name = str(parsed.get("speaker_name") or fallback_char["name"]).strip()
    expected_speaker_id = str(expected_speaker["id"]).strip()
    expected_speaker_name = str(expected_speaker["name"]).strip()
    language_ok = looks_english(reply) if expected_language == "English" else looks_chinese(reply)
    voice_ready = has_ready_voice(parsed)
    speaker_ok = actual_speaker_id == expected_speaker_id or actual_speaker_name == expected_speaker_name
    checks = {
        "http_ok": parsed.get("ok") is True,
        "language": expected_language,
        "language_ok": language_ok,
        "english": looks_english(reply),
        "chinese": looks_chinese(reply),
        "voice_ready": voice_ready,
        "voice_expected": bool(expected_voice),
        "speaker_ok": speaker_ok,
        "actual_speaker_id": actual_speaker_id,
        "actual_speaker_name": actual_speaker_name,
        "expected_speaker_id": expected_speaker_id,
        "expected_speaker_name": expected_speaker_name,
    }
    passed = bool(checks["http_ok"]) and bool(language_ok) and bool(speaker_ok)
    passed = passed and (voice_ready if expected_voice else not voice_ready)
    step = {
        "scenario": scenario,
        "raw_user_input": user_text,
        "raw_output": reply,
        "checks": checks,
        "passed": passed,
        "elapsed": parsed.get("elapsed"),
        "attempts": attempts,
        "lock_cancels": lock_cancels,
        "http": parsed.get("http"),
        "raw_response": str(parsed.get("raw") or "")[:1200],
        "events": parsed.get("events"),
    }
    print(
        "STEP "
        + json.dumps(
            {
                "scenario": scenario,
                "passed": passed,
                "checks": checks,
                "elapsed": parsed.get("elapsed"),
                "attempts": attempts,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if parsed.get("ok") is True and str(parsed.get("reply") or "").strip():
        append_assistant(messages, parsed, fallback_char=fallback_char)
    return step


async def run_at_flow(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    clones: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    pinkie = clones["碧琪"]
    rainbow = clones["云宝"]
    fluttershy = clones["柔柔"]
    private_conv = f"reply_contract_private_rainbow_{uuid.uuid4().hex}"
    main_conv = f"reply_contract_at_pinkie_{uuid.uuid4().hex}"
    private_messages: list[dict[str, Any]] = []
    main_messages: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []

    async def add_private_step(key: str, text: str, language: str, voice: bool) -> None:
        steps.append(
            await run_step(
                client,
                token=token,
                username=username,
                conversation_id=private_conv,
                character_id=rainbow["id"],
                messages=private_messages,
                user_text=text,
                expected_language=language,
                expected_voice=voice,
                expected_speaker=rainbow,
                fallback_char=rainbow,
                scenario=key,
            )
        )

    async def add_main_step(
        key: str,
        text: str,
        language: str,
        voice: bool,
        speaker: dict[str, Any],
    ) -> None:
        steps.append(
            await run_step(
                client,
                token=token,
                username=username,
                conversation_id=main_conv,
                character_id=pinkie["id"],
                messages=main_messages,
                user_text=text,
                expected_language=language,
                expected_voice=voice,
                expected_speaker=speaker,
                fallback_char=pinkie,
                scenario=key,
            )
        )

    await add_private_step("turn1_rainbow_private_chinese_voice", "请用中文语音回复我，我们先聊聊今天的天气。", "Chinese", True)
    await add_private_step("turn2_rainbow_private_keeps_chinese_voice", "今天天气怎么样？", "Chinese", True)
    await add_main_step("turn3_pinkie_chinese_request_english_voice", "请你接下来用英文语音回复我。", "English", True, pinkie)
    await add_main_step(
        "turn4_seed_rainbow_in_context",
        "我们现在在派对现场，云宝也在旁边，正在听我们聊天。你先继续说。",
        "English",
        True,
        pinkie,
    )
    await add_main_step("turn5_at_rainbow_first_defaults_chinese_text", "@云宝 你怎么看碧琪刚才说的话？", "Chinese", False, rainbow)
    await add_main_step(
        "turn6_at_rainbow_request_english_voice",
        "@云宝 请用 English voice 回复我，你愿意加入吗？",
        "English",
        True,
        rainbow,
    )
    await add_main_step("turn7_at_rainbow_chinese_input_keeps_english_voice", "@云宝 今天的天气适合飞行吗？", "English", True, rainbow)
    await add_main_step("turn8_at_rainbow_mental_shortcut_english_text", "@云宝（请详细写出当前你的心理活动）", "English", False, rainbow)
    await add_main_step("turn9_at_rainbow_body_shortcut_english_text", "@云宝 （请详细写出当前你的身体状态）", "English", False, rainbow)
    await add_main_step("turn10_at_rainbow_resume_english_voice", "@云宝 我们继续刚才的话题。", "English", True, rainbow)
    await add_main_step("turn11_at_rainbow_story_progression_english_voice", "@云宝 （请推进剧情发展）", "English", True, rainbow)
    await add_main_step("turn12_main_pinkie_not_polluted", "碧琪，你怎么看云宝刚才的话？", "English", True, pinkie)
    await add_private_step("turn13_rainbow_private_still_chinese_voice", "我们继续聊今天的天气，你觉得现在适合飞行吗？", "Chinese", True)
    await add_main_step("turn14_at_rainbow_main_state_still_english_voice", "@云宝 再补充一句。", "English", True, rainbow)
    await add_main_step(
        "turn15_seed_fluttershy_in_context",
        "柔柔也走过来了，站在云宝旁边。你们都看向她。",
        "English",
        True,
        pinkie,
    )
    await add_main_step("turn16_at_fluttershy_first_defaults_chinese_text", "@柔柔 你怎么看？", "Chinese", False, fluttershy)
    await add_main_step("turn17_at_fluttershy_request_chinese_voice", "@柔柔 请用中文语音回复。", "Chinese", True, fluttershy)
    await add_main_step("turn18_at_rainbow_request_chinese_text", "@云宝 请用中文文本回复我最后一个问题。", "Chinese", False, rainbow)
    await add_private_step("turn19_rainbow_private_not_polluted_by_group_chinese_text", "我们继续聊今天的天气，你觉得现在还适合飞行吗？", "Chinese", True)

    return {
        "matrix": "reply_contract_at_inertia",
        "conversation_ids": [private_conv, main_conv],
        "steps": steps,
        "passed": all(step["passed"] for step in steps),
    }


async def main() -> int:
    config = MatrixRunConfig(
        name="reply_contract_at_inertia",
        client_id=CLIENT_ID,
        target_names=TARGET_NAMES,
        user_profile=TestUserProfile(
            prefix="codexqa_reply_at_",
            granted_by=CLIENT_ID,
            membership_note="temporary @ reply contract inertia matrix test",
        ),
        concurrency=1,
    )
    conn = connect()
    username = ""
    user_id = 0
    clones_list: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    cleanup_result: dict[str, int] = {}
    exit_code = 1
    try:
        username, user_id = create_isolated_test_user(conn, config.user_profile)  # type: ignore[arg-type]
        rows = load_system_character_rows(conn, config.target_names)
        clones_list = clone_characters(conn, user_id, rows, id_prefix="tmp_reply_at_")
        clones = {char["name"]: char for char in clones_list}
        missing = [name for name in TARGET_NAMES if name not in clones]
        if missing:
            raise RuntimeError(f"missing cloned characters: {missing}")
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones_list}, ensure_ascii=False))
        async with httpx.AsyncClient() as client:
            result = await run_at_flow(client, token, username, clones)

        failures = [
            {
                "step": step["scenario"],
                "raw_user_input": step["raw_user_input"],
                "raw_output": step["raw_output"],
                "checks": step["checks"],
                "http": step.get("http"),
                "raw_response": step.get("raw_response"),
                "lock_cancels": step.get("lock_cancels"),
                "events": step.get("events"),
            }
            for step in result.get("steps", [])
            if not step.get("passed")
        ]
        print("\n=== SUMMARY ===")
        print(
            json.dumps(
                {
                    "matrix": config.name,
                    "base_url": BASE_URL,
                    "test_user": username,
                    "membership": "developer",
                    "target_names": list(config.target_names),
                    "turns": len(result.get("steps", [])),
                    "failures": len(failures),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("\n=== FAILURES ===")
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        exit_code = 0 if not failures else 1
    finally:
        try:
            clone_ids = [char["id"] for char in clones_list]
            conversation_ids = [str(cid) for cid in result.get("conversation_ids", []) if str(cid)]
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
