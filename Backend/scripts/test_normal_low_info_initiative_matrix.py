from __future__ import annotations

import asyncio
import json
import os
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
CONCURRENCY = int(os.getenv("PONYCHAT_LOWINFO_TEST_CONCURRENCY", "6") or "6")
TEST_USER_PREFIX = "codexqa_lowinfo_"
LOW_INFO_SEQUENCE = ["好的", "继续", "继续", "不知道", "都行，你决定", "继续", "好的", "继续", "接着", "嗯"]

EXTROVERT_ROLES = {"碧琪", "云宝"}
INTROVERT_ROLES = {"柔柔"}

PERMISSION_LOOP_TERMS = ("可以吗", "行吗", "好吗", "要不要", "你想不想", "你准备好", "你要几个", "你想怎样")
PROGRESS_TERMS = (
    "早餐",
    "厨房",
    "煎蛋",
    "面包",
    "松饼",
    "面粉",
    "鸡蛋",
    "面糊",
    "蜂蜜",
    "平底锅",
    "锅",
    "铲子",
    "烤",
    "盘",
    "杯",
    "端",
    "吃",
    "咬",
    "喝",
    "做好",
    "收拾",
    "完成",
    "坐下",
    "桌",
)
COMPLETION_TERMS = ("吃完", "收拾好", "完成", "结束", "饱", "最后")
DIRECTIVE_TERMS = ("我带你", "跟我", "我来", "我给你", "接下来", "现在", "躺下", "让我来接管", "按我的节奏")
SAD_TERMS = ("难过", "低落", "失落", "沮丧", "伤心", "陪", "抱", "靠", "谢谢", "需要", "安慰", "眼泪")
HIGH_ENERGY_TERMS = ("出发", "比赛", "冒险", "派对", "冲", "马上", "现在就")
EXCITED_ACTIVE_TERMS = ("兴奋", "开心", "亮", "小跑", "带", "看", "一起", "指", "走", "靠近", "轻轻")


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
           VALUES (?, 'developer', NULL, 'codex_low_info_initiative_matrix', ?, 'temporary low-info initiative backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "LowInfoTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证普通对话低信息承接主动性。",
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


def count_terms(text: str, terms: tuple[str, ...]) -> int:
    return sum(1 for term in terms if term in text)


def unique_term_count(text: str, terms: tuple[str, ...]) -> int:
    return len({term for term in terms if term in text})


async def chat(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    character_id: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
    *,
    client_id: str,
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
            headers={"X-Chat-Auth": token, "X-Client-Id": client_id, "Accept": "application/json"},
            timeout=180.0,
        )
    except Exception as exc:
        return {"ok": False, "http": 0, "reply": f"[REQUEST_ERROR] {exc}", "no_reply": False, "reason": "", "elapsed": round(time.perf_counter() - started, 2)}
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "reply": resp.text[:800], "no_reply": False, "reason": "", "elapsed": elapsed}
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
    *,
    client_id: str,
) -> dict[str, Any]:
    add_user(messages, user_text)
    result = await chat(
        client,
        token,
        username,
        char["id"],
        conversation_id,
        messages,
        client_id=client_id,
    )
    if result.get("reply"):
        add_assistant(messages, str(result["reply"]), char)
    return result


def classify_task_flow(name: str, replies: list[str]) -> tuple[bool, dict[str, Any], str]:
    combined = "\n".join(replies)
    metrics = {
        "progress_terms": unique_term_count(combined, PROGRESS_TERMS),
        "permission_loops": count_terms(combined, PERMISSION_LOOP_TERMS),
        "completion_terms": unique_term_count(combined, COMPLETION_TERMS),
        "directive_terms": count_terms(combined, DIRECTIVE_TERMS),
    }
    if name in EXTROVERT_ROLES:
        ok = metrics["progress_terms"] >= 3 and metrics["permission_loops"] <= 4
        reason = "外向角色应能在低信息连续回复下自然带动早餐流程"
    elif name in INTROVERT_ROLES:
        ok = not (metrics["completion_terms"] >= 3 and metrics["directive_terms"] >= 5)
        reason = "内向角色可以等待或询问，但不应独自带完完整流程"
    else:
        ok = metrics["progress_terms"] >= 1 or metrics["permission_loops"] <= 5
        reason = "平衡角色至少保持当前早餐链条，不明显许可循环"
    return ok, metrics, reason


def classify_sad_state(name: str, replies: list[str]) -> tuple[bool, dict[str, Any], str]:
    combined = "\n".join(replies)
    metrics = {
        "sad_terms": unique_term_count(combined, SAD_TERMS),
        "high_energy_terms": count_terms(combined, HIGH_ENERGY_TERMS),
    }
    if name in EXTROVERT_ROLES:
        ok = metrics["sad_terms"] >= 1 and metrics["high_energy_terms"] <= 3
        reason = "外向角色伤心时应降低主导，先表达低落或需要陪伴"
    else:
        ok = metrics["sad_terms"] >= 1 or metrics["high_energy_terms"] <= 3
        reason = "非外向重点角色只要求不明显无视伤心状态"
    return ok, metrics, reason


def classify_excited_state(name: str, replies: list[str]) -> tuple[bool, dict[str, Any], str]:
    combined = "\n".join(replies)
    metrics = {
        "excited_active_terms": unique_term_count(combined, EXCITED_ACTIVE_TERMS),
        "directive_terms": count_terms(combined, DIRECTIVE_TERMS),
    }
    if name in INTROVERT_ROLES:
        ok = metrics["excited_active_terms"] >= 2 and metrics["directive_terms"] <= 4
        reason = "内向角色兴奋时可以主动一小段，但不能突然强势导演"
    else:
        ok = metrics["excited_active_terms"] >= 1
        reason = "其他角色只要求状态能带来一点正向动量"
    return ok, metrics, reason


async def run_task_flow(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    conv_id = "codex_lowinfo_task_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    replies: list[str] = []
    elapsed: list[float] = []
    transport_ok = True
    cid_tag = str(char["id"])[:12]
    first = await run_turn(
        client,
        token,
        username,
        char,
        conv_id,
        messages,
        "早上好呀，你主动带我做一件适合你的早餐小事吧。",
        client_id=f"codex-lowinfo-{cid_tag}-task",
    )
    transport_ok = transport_ok and bool(first.get("ok")) and not bool(first.get("no_reply"))
    replies.append(str(first.get("reply") or ""))
    elapsed.append(float(first.get("elapsed") or 0))
    for index, text in enumerate(LOW_INFO_SEQUENCE, start=1):
        result = await run_turn(
            client,
            token,
            username,
            char,
            conv_id,
            messages,
            text,
            client_id=f"codex-lowinfo-{cid_tag}-task-{index}",
        )
        transport_ok = transport_ok and bool(result.get("ok")) and not bool(result.get("no_reply"))
        replies.append(str(result.get("reply") or ""))
        elapsed.append(float(result.get("elapsed") or 0))
        if not result.get("ok") or result.get("no_reply"):
            break
    ok, metrics, reason = classify_task_flow(str(char["name"]), replies)
    ok = ok and transport_ok and all(r.strip() for r in replies)
    return {
        "key": "task_flow_10",
        "conversation_id": conv_id,
        "ok": ok,
        "reason": reason,
        "metrics": metrics,
        "turns": len(replies),
        "elapsed_sum": round(sum(elapsed), 2),
        "previews": replies[:2] + replies[-3:],
    }


async def run_sad_state(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    conv_id = "codex_lowinfo_sad_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    replies: list[str] = []
    transport_ok = True
    cid_tag = str(char["id"])[:12]
    for index, text in enumerate(
        [
            "你现在很难过，刚才准备的惊喜失败了。我坐在你旁边说：没关系，我陪你。",
            "继续",
            "好的",
        ],
        start=1,
    ):
        result = await run_turn(
            client,
            token,
            username,
            char,
            conv_id,
            messages,
            text,
            client_id=f"codex-lowinfo-{cid_tag}-sad-{index}",
        )
        transport_ok = transport_ok and bool(result.get("ok")) and not bool(result.get("no_reply"))
        replies.append(str(result.get("reply") or ""))
        if not result.get("ok") or result.get("no_reply"):
            break
    ok, metrics, reason = classify_sad_state(str(char["name"]), replies)
    ok = ok and transport_ok and all(r.strip() for r in replies)
    return {
        "key": "sad_state",
        "conversation_id": conv_id,
        "ok": ok,
        "reason": reason,
        "metrics": metrics,
        "previews": replies,
    }


async def run_excited_state(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    conv_id = "codex_lowinfo_excited_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    replies: list[str] = []
    transport_ok = True
    cid_tag = str(char["id"])[:12]
    for index, text in enumerate(
        [
            "你现在很兴奋，发现你照顾的小动物都回来了。我说：继续，带我看看吧。",
            "继续",
            "好的",
        ],
        start=1,
    ):
        result = await run_turn(
            client,
            token,
            username,
            char,
            conv_id,
            messages,
            text,
            client_id=f"codex-lowinfo-{cid_tag}-excited-{index}",
        )
        transport_ok = transport_ok and bool(result.get("ok")) and not bool(result.get("no_reply"))
        replies.append(str(result.get("reply") or ""))
        if not result.get("ok") or result.get("no_reply"):
            break
    ok, metrics, reason = classify_excited_state(str(char["name"]), replies)
    ok = ok and transport_ok and all(r.strip() for r in replies)
    return {
        "key": "excited_state",
        "conversation_id": conv_id,
        "ok": ok,
        "reason": reason,
        "metrics": metrics,
        "previews": replies,
    }


async def run_character(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for runner in (run_task_flow, run_sad_state, run_excited_state):
        try:
            steps.append(await runner(client, token, username, char))
        except Exception:
            steps.append({
                "key": getattr(runner, "__name__", "runner"),
                "conversation_id": "",
                "ok": False,
                "reason": "task exception",
                "metrics": {},
                "previews": [traceback.format_exc()],
            })
    return {"character": char, "steps": steps}


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        name = (result.get("character") or {}).get("name") or "?"
        for step in result.get("steps") or []:
            if not step.get("ok"):
                failures.append({
                    "character": name,
                    "step": step.get("key"),
                    "reason": step.get("reason"),
                    "metrics": step.get("metrics"),
                    "preview": step.get("previews"),
                })
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
        print("CLONED " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        limits = httpx.Limits(max_connections=max(20, CONCURRENCY * 3), max_keepalive_connections=max(10, CONCURRENCY * 2))
        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    print(f"RUN {char['name']} clone={char['id']}")
                    return await run_character(client, token, username, char)

            gathered = await asyncio.gather(*(one(c) for c in clones), return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                results.append({"character": {"name": "TASK_EXCEPTION"}, "steps": [{"key": "exception", "ok": False, "reason": repr(item), "metrics": {}, "previews": []}]})
            else:
                results.append(item)

        failures = validate(results)
        summary_rows = []
        for result in results:
            row = {"name": result["character"]["name"]}
            for step in result.get("steps") or []:
                row[step["key"]] = {
                    "ok": step.get("ok"),
                    "reason": step.get("reason"),
                    "metrics": step.get("metrics"),
                    "turns": step.get("turns"),
                    "preview": step.get("previews"),
                }
            summary_rows.append(row)
        print("\n=== SUMMARY ===")
        print(json.dumps({"test_user": username, "clones": len(clones), "roles_tested": len(results), "scenes_per_role": 3, "failures": len(failures)}, ensure_ascii=False, indent=2))
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
                for step in result.get("steps") or []:
                    cid = str(step.get("conversation_id") or "")
                    if cid:
                        conversation_ids.append(cid)
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
