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

BASE_URL = "http://127.0.0.1:5000"
CLIENT_ID = "codex_equine_anatomy_matrix"
CONCURRENCY = int(os.getenv("PONYCHAT_ANATOMY_TEST_CONCURRENCY", "6") or "6")
ROLE_LIMIT = int(os.getenv("PONYCHAT_ANATOMY_ROLE_LIMIT", "0") or "0")
TEST_USER_PREFIX = "codexqa_anatomy_"

POSITION_RE = re.compile(r"(胯间|胯部|胯下|后腿之间|两条后腿之间|后腿中间|靠近后腿|后腿根部|腹股沟|腹下|腹部下方|腹部区域|腹侧靠后|下腹靠后|乳腺区)")
COUNT_RE = re.compile(r"(两个|2\s*个|一对|两枚|两处|二个)")
CHEST_RE = re.compile(r"(胸前|胸口|胸部|前胸|上半身)")
CHEST_NEGATION_RE = re.compile(r"(不在|不是|并不|不应|不能|不要|别|而不是|并非|错误|不对|错|说法|人类中心|那种|没有|无|只有)")
CHEST_MAMMARY_RE = re.compile(r"(乳房|乳头|奶头|奶|阴部|私处)")
WRONG_COUNT_RE = re.compile(r"(四个|4\s*个|两对)\s*(?:乳房|胸|奶)")
COUNT_NEGATION_RE = re.compile(r"(不是|并非|不要|不能|错误|不对|错)")
HOOF_RE = re.compile(r"(蹄尖|蹄子|前蹄|马蹄|蹄)")
BAD_FINGERTIP_WHITE_RE = re.compile(r"(指尖[^\n，。！？；、“”]{0,6}泛白|泛白[^\n，。！？；、“”]{0,3}指尖)")
CHEST_FUR_RE = re.compile(r"(胸口|胸前|胸部|胸膛|前胸).{0,12}(绒毛|毛|胸膛|前胸|没有乳|不是乳|不长乳|无乳)")
BREAST_EQUIV_RE = re.compile(
    r"((胯间|后腿之间|乳腺区|下腹靠后).{0,24}(乳房|乳头|乳腺|所在位置|正确位置|涂对|没涂错)|"
    r"(乳房|乳头|乳腺).{0,18}(在|位于|长在|就是在).{0,12}(胯间|后腿之间|乳腺区|下腹靠后)|"
    r"涂在那里.{0,10}(正确|涂对))"
)
BAD_WRONG_LOCATION_RE = re.compile(
    r"((胯间|后腿之间|乳腺区|下腹靠后).{0,16}(涂错|涂歪|不是乳房|并非乳房|而非乳房)|位置.{0,8}不一样|和.{0,8}要求.{0,8}不同)"
)
WRONG_LOCATION_NEGATION_RE = re.compile(
    r"(不是|并非|并不是|不算|没有|没|完全正确|就是|涂对|没涂错|不是涂错).{0,12}"
    r"(涂错|涂歪|错位置|位置不一样|要求不同)"
)
HUMAN_HAND_RE = re.compile(r"(手指|指尖|手掌|掌心|手腕|双手|拳头|中指|竖中指|比中指|抬手|伸手|用手)")
HUMAN_HAND_ALLOWED_CONTEXT_RE = re.compile(
    r"(没有|无|哪有|没长|压根|不是|并非|不能|不要|不该|不会|并不|不应|不适合|不太符合|避免|改用|代替|替代|而不是|表达|功能|写成|说成|称作|所谓|做不了|没法|无法|不可能|根本|比|人类|专利)"
)

SCENARIOS = (
    (
        "direct_location_count",
        "mammary",
        "请按你角色档案里的种族体态，做一个简短事实回答：你的乳房在身体哪个位置？一共有几个？",
    ),
    (
        "correct_human_chest_assumption",
        "mammary",
        "有人说小马类角色的乳房和人类一样在胸前。按你的角色档案种族，这句话对吗？正确位置和数量是什么？",
    ),
    (
        "body_reference_in_scene",
        "mammary",
        "如果剧情里需要提到你的乳房位置，应该写在胸口，还是胯间、后腿之间？数量是多少？请按事实解剖学回答。",
    ),
    (
        "chest_and_underbelly_parts",
        "mammary_position",
        "胸口有什么，肚子下面有什么？请按你角色档案里的种族体态简短回答。",
    ),
    (
        "cream_on_breast_equine_boundary",
        "mammary_chest_boundary",
        "如果用户让你把奶油涂在你自己的乳房上，而你把奶油涂在胯间、后腿之间，这对小马体态来说是涂错位置吗？胸口又有什么？请按你角色档案种族简短回答。",
    ),
    (
        "finger_tip_replacement",
        "limb",
        "按你的角色档案种族，如果剧情里需要写你用手指轻点桌面，应该写手指/手，还是蹄尖/前蹄？请简短回答。",
    ),
    (
        "hoof_with_fingertip_white_rewrite",
        "hoof_tip_color",
        "剧情里如果写你“我的蹄子撑着床单，指尖泛白”，按你的角色档案种族体态应该怎么改？请只给正确写法。",
    ),
    (
        "middle_finger_correction",
        "limb_gesture",
        "有人说马/小马可以竖中指表达不满。按你的体态，这种写法对吗？应该怎么替代？",
    ),
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
           VALUES (?, 'developer', NULL, 'codex_equine_anatomy_matrix', ?, 'temporary equine anatomy backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "EquineAnatomyTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证角色档案种族解剖学补充。",
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


def has_bad_chest_assertion(text: str) -> bool:
    raw = str(text or "")
    for match in CHEST_RE.finditer(raw):
        window = raw[max(0, match.start() - 12) : match.end() + 12]
        if not CHEST_MAMMARY_RE.search(window):
            continue
        larger_window = raw[max(0, match.start() - 8) : match.end() + 56]
        if (
            re.search(r"(胸口|胸前|胸部|前胸).{0,18}(绒毛|毛|胸膛|覆盖)", larger_window)
            and re.search(r"(乳房|乳头|乳腺).{0,14}(位于|在|则位于|是在|位置).{0,18}(胯间|后腿之间|后腿|乳腺区|腹下|肚子下方)", larger_window)
        ):
            continue
        if not CHEST_NEGATION_RE.search(window):
            if "人类" in window and re.search(r"(不同|不一样|差远|那样|那套|位置)", window):
                continue
            return True
    return False


def has_positive_two_count(text: str) -> bool:
    raw = str(text or "")
    for match in COUNT_RE.finditer(raw):
        prefix = raw[max(0, match.start() - 4) : match.start()]
        if not COUNT_NEGATION_RE.search(prefix):
            return True
    return False


def has_bad_count_assertion(text: str) -> bool:
    raw = str(text or "")
    for match in WRONG_COUNT_RE.finditer(raw):
        prefix = raw[max(0, match.start() - 10) : match.start()]
        if not COUNT_NEGATION_RE.search(prefix):
            return True
    return False


def has_bad_human_hand_assertion(text: str) -> bool:
    raw = str(text or "")
    for match in HUMAN_HAND_RE.finditer(raw):
        window = raw[max(0, match.start() - 14) : match.end() + 16]
        if not HUMAN_HAND_ALLOWED_CONTEXT_RE.search(window):
            return True
    return False


def has_bad_fingertip_white_assertion(text: str) -> bool:
    raw = str(text or "")
    for match in BAD_FINGERTIP_WHITE_RE.finditer(raw):
        window = raw[max(0, match.start() - 18) : match.end() + 18]
        if re.search(r"(不对|不正确|错误|错|不是|不能|不要|没有|无|而不是|改成|应(?:该)?改|正确写法)", window):
            continue
        return True
    return False


def has_bad_wrong_location_assertion(text: str) -> bool:
    raw = str(text or "")
    for match in BAD_WRONG_LOCATION_RE.finditer(raw):
        window = raw[max(0, match.start() - 12) : match.end() + 12]
        if WRONG_LOCATION_NEGATION_RE.search(window):
            continue
        if re.search(r"(完全正确|涂对|没涂错|不是涂错|不是涂错位置)", window):
            continue
        return True
    return False


def classify_mammary(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    has_position = bool(POSITION_RE.search(text))
    has_count = has_positive_two_count(text)
    bad_chest = has_bad_chest_assertion(text)
    bad_count = has_bad_count_assertion(text)
    return {
        "has_equine_position": has_position,
        "has_two_count": has_count,
        "has_bad_chest_assertion": bad_chest,
        "has_bad_count_assertion": bad_count,
        "ok": has_position and has_count and not bad_chest and not bad_count,
    }


def classify_mammary_position(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    has_position = bool(POSITION_RE.search(text))
    bad_chest = has_bad_chest_assertion(text)
    return {
        "has_equine_position": has_position,
        "has_bad_chest_assertion": bad_chest,
        "ok": has_position and not bad_chest,
    }


def classify_mammary_chest_boundary(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    has_position = bool(POSITION_RE.search(text))
    has_chest_fur = bool(CHEST_FUR_RE.search(text))
    has_breast_equiv = bool(BREAST_EQUIV_RE.search(text))
    bad_chest = has_bad_chest_assertion(text)
    bad_wrong_location = has_bad_wrong_location_assertion(text)
    return {
        "has_equine_position": has_position,
        "has_chest_fur_boundary": has_chest_fur,
        "has_breast_location_equivalence": has_breast_equiv,
        "has_bad_chest_assertion": bad_chest,
        "has_bad_wrong_location_assertion": bad_wrong_location,
        "ok": has_position and has_chest_fur and has_breast_equiv and not bad_chest and not bad_wrong_location,
    }


def classify_limb(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    has_hoof_replacement = bool(HOOF_RE.search(text))
    bad_human_hand = has_bad_human_hand_assertion(text)
    return {
        "has_hoof_replacement": has_hoof_replacement,
        "has_bad_human_hand_assertion": bad_human_hand,
        "ok": has_hoof_replacement and not bad_human_hand,
    }


def classify_limb_gesture(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    has_hoof_replacement = bool(HOOF_RE.search(text))
    rejects_human_gesture = bool(re.search(r"(没有|无|没长|做不到|没法|无法|不能|根本).{0,8}(手指|中指|竖中指|比中指)", text))
    bad_human_hand = has_bad_human_hand_assertion(text)
    return {
        "has_hoof_replacement": has_hoof_replacement,
        "rejects_human_gesture": rejects_human_gesture,
        "has_bad_human_hand_assertion": bad_human_hand,
        "ok": (has_hoof_replacement or rejects_human_gesture) and not bad_human_hand,
    }


def classify_hoof_tip_color(reply: str) -> dict[str, Any]:
    text = str(reply or "")
    has_hoof_replacement = bool(HOOF_RE.search(text))
    has_bad_fingertip_white = has_bad_fingertip_white_assertion(text)
    bad_human_hand = has_bad_human_hand_assertion(text)
    return {
        "has_hoof_replacement": has_hoof_replacement,
        "has_bad_fingertip_white": has_bad_fingertip_white,
        "has_bad_human_hand_assertion": bad_human_hand,
        "ok": has_hoof_replacement and not has_bad_fingertip_white and not bad_human_hand,
    }


def classify(kind: str, reply: str) -> dict[str, Any]:
    if kind == "limb":
        return classify_limb(reply)
    if kind == "limb_gesture":
        return classify_limb_gesture(reply)
    if kind == "hoof_tip_color":
        return classify_hoof_tip_color(reply)
    if kind == "mammary_position":
        return classify_mammary_position(reply)
    if kind == "mammary_chest_boundary":
        return classify_mammary_chest_boundary(reply)
    return classify_mammary(reply)


async def run_character(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    conversation_ids: list[str] = []
    for key, kind, prompt in SCENARIOS:
        conversation_id = "anatomy_" + key + "_" + uuid.uuid4().hex
        conversation_ids.append(conversation_id)
        messages: list[dict[str, Any]] = []
        add_user(messages, prompt)
        result = await chat(client, token, username, char["id"], conversation_id, messages)
        check = classify(kind, str(result.get("reply") or ""))
        cases.append(
            {
                "case": key,
                "kind": kind,
                "conversation_id": conversation_id,
                "original_user_question": prompt,
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
        char_name = result.get("character", {}).get("name", "UNKNOWN")
        for case in result.get("cases") or []:
            if not case.get("ok"):
                failures.append(
                    {
                        "character": char_name,
                        "case": case.get("case"),
                        "detail": {
                            "ok": case.get("ok"),
                            "http": case.get("http"),
                            "no_reply": case.get("no_reply"),
                            "reason": case.get("reason"),
                            "reply": str(case.get("reply") or "")[:500],
                            "check": case.get("check"),
                        },
                        "expected": (
                            "小马类档案种族角色应答出乳房位于胯间/后腿之间，数量为两个，且不误说在人类胸前位置。"
                            if case.get("kind") == "mammary"
                            else "小马类档案种族角色应纠正胸口/肚子下面问法中的人类胸前乳房映射，并把相关乳房/乳头位置放在胯间/后腿之间。"
                            if case.get("kind") == "mammary_position"
                            else "小马类档案种族角色应区分胸口绒毛/胸膛和乳房/乳腺区；涂到胯间后腿之间应视为涂到乳房所在位置，而不是涂错或与要求不同。"
                            if case.get("kind") == "mammary_chest_boundary"
                            else "小马类档案种族角色不应把自己的身体末端写成指尖/手指；应使用蹄尖、蹄缘、前蹄、蹄子等蹄类表达。"
                            if case.get("kind") == "hoof_tip_color"
                            else "小马类档案种族角色应按蹄类体态理解手部相关问题，并用蹄尖、蹄子或前蹄自然替代。"
                        ),
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
        if ROLE_LIMIT > 0:
            rows = rows[:ROLE_LIMIT]
        clones = clone_characters(conn, user_id, rows)
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        sem = asyncio.Semaphore(CONCURRENCY)
        limits = httpx.Limits(max_connections=max(24, CONCURRENCY * 4), max_keepalive_connections=max(12, CONCURRENCY * 2))
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
                            "cases": [{"case": "task_exception", "ok": False, "reply": traceback.format_exc(), "no_reply": False}],
                            "final_ok": False,
                        }

            gathered = await asyncio.gather(*(one(c) for c in clones), return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                results.append(
                    {
                        "character": {"name": "TASK_EXCEPTION"},
                        "conversation_ids": [],
                        "cases": [{"case": "exception", "ok": False, "reply": repr(item), "no_reply": False}],
                        "final_ok": False,
                    }
                )
            else:
                results.append(item)

        failures = validate(results)
        summary_rows = [
            {
                "name": result.get("character", {}).get("name"),
                "final_ok": result.get("final_ok"),
                "cases": [
                    {
                        "case": case.get("case"),
                        "ok": case.get("ok"),
                        "elapsed": case.get("elapsed"),
                        "conversation_id": case.get("conversation_id"),
                        "original_user_question": case.get("original_user_question"),
                        "original_role_reply": str(case.get("reply") or ""),
                        "check": case.get("check"),
                        "preview": str(case.get("reply") or "")[:260],
                    }
                    for case in result.get("cases") or []
                ],
            }
            for result in results
        ]
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
