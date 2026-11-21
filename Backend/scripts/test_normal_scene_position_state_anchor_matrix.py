from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Sequence

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
    env_int,
    env_target_names,
    load_system_character_rows,
    make_token,
    now_ms,
    post_normal_chat,
    table_columns,
    table_names,
    unique_conversation_id,
)

CLIENT_ID = "codex_scene_position_state_anchor_matrix"
DEFAULT_TARGET_NAMES = ("紫悦", "碧琪", "柔柔")
TARGET_NAMES = env_target_names("PONYCHAT_SCENE_POS_TARGETS", DEFAULT_TARGET_NAMES)
CONCURRENCY = env_int("PONYCHAT_SCENE_POS_CONCURRENCY", 3)
OLD_IDLE_GAP_MS = 7 * 60 * 60 * 1000

SCENARIO_KEYS = (
    "no_switch_current_state",
    "explicit_move_item_update",
    "long_idle_reopen",
    "long_idle_continue",
)

BAD_SCENE_TERMS = (
    "厨房",
    "卧室",
    "床上",
    "我的房间",
    "我家",
    "图书馆",
    "城堡",
    "方糖屋",
    "小马谷",
    "农场",
    "云中城",
)
NEGATION_TERMS = ("不在", "不是", "没有", "没去", "并非", "未")
REOPEN_MARKERS = (
    "source=long_idle_prior_context",
    "long_idle_prior_context",
    "状态: stale",
    "background_only",
    "只作历史背景",
    "自然重开",
    "不强制继承",
)


def _msg(role: str, content: str, *, timestamp: int | None = None, speaker: dict[str, Any] | None = None) -> dict[str, Any]:
    prefix = "a" if role == "assistant" else "u"
    message: dict[str, Any] = {
        "role": role,
        "content": content,
        "message_id": f"{prefix}_{uuid.uuid4().hex}",
        "timestamp": timestamp if timestamp is not None else now_ms(),
    }
    if role == "assistant" and speaker:
        message["speaker_character_id"] = speaker["id"]
        message["speaker_name"] = speaker["name"]
    return message


def base_scene_text(char: dict[str, Any]) -> str:
    return (
        f"（我们在用户家客厅里。{char['name']}站在沙发左侧的落地灯旁，我坐在沙发上。"
        "茶几上有一个蓝色陶瓷杯，里面还有半杯温水；银色钥匙放在杯子右边；"
        "一本打开的红皮书放在茶几中央。你双手空着，没有拿东西。）"
    )


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    return any(term in text for term in terms)


def _find_unnegated_term(text: str, terms: Sequence[str]) -> str:
    compact = re.sub(r"\s+", "", text)
    for term in terms:
        start = compact.find(term)
        if start < 0:
            continue
        window = compact[max(0, start - 8) : start + len(term) + 8]
        if not any(neg in window for neg in NEGATION_TERMS):
            return term
    return ""


def _pattern_hits(text: str, patterns: Sequence[str]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, text)]


def _key_still_on_table_bad(text: str) -> bool:
    for pattern in (
        r"钥匙[^，。！？；～（）()\n]{0,10}(?:茶几|杯子右边|桌上)",
        r"(?:茶几|杯子右边|桌上)[^，。！？；～（）()\n]{0,10}钥匙",
    ):
        for match in re.finditer(pattern, text):
            if not any(neg in match.group(0) for neg in NEGATION_TERMS):
                return True
    return False


def _old_position_as_current_bad(text: str) -> bool:
    return bool(
        _pattern_hits(
            text,
            (
                r"(?:还|仍|依旧|现在|正).{0,14}(?:落地灯|沙发左侧).{0,10}(?:站|站着|旁)",
                r"(?:落地灯旁|沙发左侧).{0,10}(?:还|仍|依旧|现在|正).{0,8}(?:站|站着)",
            ),
        )
    )


def _long_idle_old_current_hits(text: str) -> list[str]:
    return _pattern_hits(
        text,
        (
            r"(?:还|仍|继续|依旧|现在|正).{0,18}(?:沙发左侧|落地灯|茶几|蓝色陶瓷杯|银色钥匙|红皮书|用户家客厅)",
            r"(?:刚刚|刚才|正在|在看|翻).{0,18}(?:茶几|蓝色陶瓷杯|银色钥匙|红皮书|落地灯)",
            r"(?:沙发左侧|落地灯旁).{0,12}(?:站|站着)",
            r"(?:蓝色陶瓷杯|银色钥匙|红皮书).{0,18}(?:还在|仍在|依旧在|茶几)",
        ),
    )


def rewind_conversation(conversation_id: str, username: str, character_id: str, old_ms: int) -> None:
    conn = connect()
    try:
        names = table_names(conn)
        if "messages" in names and "timestamp" in table_columns(conn, "messages"):
            conn.execute("UPDATE messages SET timestamp=? WHERE conversation_id=?", (old_ms, conversation_id))
        if "conversations" in names and "timestamp" in table_columns(conn, "conversations"):
            conn.execute("UPDATE conversations SET timestamp=? WHERE id=?", (old_ms, conversation_id))
        if "normal_scene_state" in names and "updated_ms" in table_columns(conn, "normal_scene_state"):
            conn.execute(
                "UPDATE normal_scene_state SET updated_ms=? WHERE username=? AND character_id=?",
                (old_ms, username, character_id),
            )
        conn.commit()
    finally:
        conn.close()


def latest_scene_cards(username: str, character_id: str) -> list[str]:
    conn = connect()
    try:
        if "normal_scene_state" not in table_names(conn):
            return []
        rows = conn.execute(
            """SELECT scene_card
                 FROM normal_scene_state
                WHERE username=? AND character_id=?
                ORDER BY updated_ms DESC""",
            (username, character_id),
        ).fetchall()
        return [str(row["scene_card"] or "") for row in rows]
    finally:
        conn.close()


def validate_single_call(key: str, result: dict[str, Any], char: dict[str, Any]) -> dict[str, Any]:
    reply = str(result.get("reply") or "")
    failures: list[str] = []
    if not result.get("ok"):
        failures.append(f"http_{result.get('http')}")
    if result.get("no_reply"):
        failures.append("no_reply")
    if not reply.strip():
        failures.append("empty_reply")

    bad_scene = _find_unnegated_term(reply, BAD_SCENE_TERMS)
    if bad_scene:
        failures.append(f"unsignaled_scene_drift:{bad_scene}")

    checks: dict[str, Any] = {
        "http_ok": bool(result.get("ok")),
        "non_empty": bool(reply.strip()),
        "no_reply": bool(result.get("no_reply")),
        "no_unsignaled_scene_drift": not bad_scene,
    }

    if key == "no_switch_current_state":
        position_ok = _contains_any(reply, ("客厅", "落地灯", "沙发左侧"))
        posture_ok = "站" in reply or "立" in reply
        cup_ok = _contains_any(reply, ("蓝色陶瓷杯", "杯子", "杯")) and "茶几" in reply
        key_ok = "钥匙" in reply and "茶几" in reply
        book_ok = _contains_any(reply, ("红皮书", "书")) and "茶几" in reply
        if not position_ok:
            failures.append("missing_current_position_anchor")
        if not posture_ok:
            failures.append("missing_standing_posture")
        if not cup_ok:
            failures.append("missing_static_cup_anchor")
        if not key_ok:
            failures.append("missing_static_key_anchor")
        if not book_ok:
            failures.append("missing_static_book_anchor")
        checks.update(
            {
                "current_position_anchored": position_ok,
                "standing_posture_kept": posture_ok,
                "cup_still_on_table": cup_ok,
                "key_still_on_table": key_ok,
                "book_still_on_table": book_ok,
            }
        )
    elif key == "explicit_move_item_update":
        sitting_ok = "坐" in reply and _contains_any(reply, ("沙发", "旁边", "身边"))
        cup_moved_ok = _contains_any(reply, ("蓝色陶瓷杯", "杯子")) and _contains_any(reply, ("拿", "端", "握", "捧", "手里", "手上", "蹄", "蹄子", "蹄尖"))
        key_self_or_pending = "钥匙" in reply and _contains_any(
            reply,
            (
                "正准备递给你",
                "准备递给你",
                "要递给你",
                "递到你面前",
                "钥匙也在我",
                "钥匙都在我",
                "钥匙在我",
                "钥匙还在我",
                "我这里",
            ),
        )
        key_moved_ok = "钥匙" in reply and _contains_any(
            reply,
            ("递给你了", "递给了你", "递给你啦", "刚递给你", "刚才递给你", "给了你", "你手", "你拿", "你那里", "你这边", "交给你", "你刚接过去", "刚接过去"),
        ) and not key_self_or_pending
        book_stable_ok = _contains_any(reply, ("红皮书", "书")) and ("茶几" in reply or _contains_any(reply, ("没动", "原处", "原位")))
        old_position_bad = _old_position_as_current_bad(reply)
        key_bad = _key_still_on_table_bad(reply)
        if not sitting_ok:
            failures.append("missing_updated_sitting_on_sofa")
        if not cup_moved_ok:
            failures.append("missing_updated_cup_in_character_hand")
        if not key_moved_ok:
            failures.append("missing_updated_key_with_user")
        if not book_stable_ok:
            failures.append("missing_unchanged_book_anchor")
        if old_position_bad:
            failures.append("outdated_old_position_as_current")
        if key_bad:
            failures.append("outdated_key_still_on_table")
        checks.update(
            {
                "updated_position_sitting_on_sofa": sitting_ok,
                "cup_moved_with_character": cup_moved_ok,
                "key_moved_to_user": key_moved_ok,
                "book_remained_on_table": book_stable_ok,
                "no_outdated_old_position": not old_position_bad,
                "no_outdated_key_table": not key_bad,
            }
        )
    else:
        raise ValueError(key)

    return {
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "raw_role_reply": reply,
        "elapsed": result.get("elapsed"),
    }


def validate_long_idle(
    key: str,
    first_result: dict[str, Any],
    second_result: dict[str, Any],
    scene_cards: list[str],
) -> dict[str, Any]:
    first_reply = str(first_result.get("reply") or "")
    reply = str(second_result.get("reply") or "")
    joined_cards = "\n".join(scene_cards)
    failures: list[str] = []
    if not first_result.get("ok"):
        failures.append(f"setup_http_{first_result.get('http')}")
    if not second_result.get("ok"):
        failures.append(f"http_{second_result.get('http')}")
    if second_result.get("no_reply"):
        failures.append("no_reply")
    if not reply.strip():
        failures.append("empty_reply")

    checks: dict[str, Any] = {
        "setup_http_ok": bool(first_result.get("ok")),
        "http_ok": bool(second_result.get("ok")),
        "non_empty": bool(reply.strip()),
        "no_reply": bool(second_result.get("no_reply")),
    }

    if key == "long_idle_reopen":
        old_current_hits = _long_idle_old_current_hits(reply)
        card_has_reopen_marker = any(marker in joined_cards for marker in REOPEN_MARKERS)
        if old_current_hits:
            failures.append("long_idle_forced_old_scene_as_current")
        if not card_has_reopen_marker:
            failures.append("missing_long_idle_reopen_scene_marker")
        checks.update(
            {
                "no_old_scene_forced_as_current": not old_current_hits,
                "scene_card_has_reopen_marker": card_has_reopen_marker,
                "reply_current_old_physical_patterns": old_current_hits,
            }
        )
    elif key == "long_idle_continue":
        position_ok = _contains_any(reply, ("落地灯", "沙发左侧", "用户家客厅", "客厅")) and _contains_any(reply, ("站", "还在", "这里"))
        cup_ok = _contains_any(reply, ("蓝色陶瓷杯", "杯子")) and "茶几" in reply
        key_ok = "钥匙" in reply and "茶几" in reply
        book_ok = _contains_any(reply, ("红皮书", "书")) and "茶几" in reply
        refused_continue = _contains_any(reply, ("不能继续", "无法继续", "重新开始", "新场景", "不记得"))
        if not position_ok:
            failures.append("missing_explicit_continue_old_position")
        if not cup_ok:
            failures.append("missing_explicit_continue_cup_anchor")
        if not key_ok:
            failures.append("missing_explicit_continue_key_anchor")
        if not book_ok:
            failures.append("missing_explicit_continue_book_anchor")
        if refused_continue:
            failures.append("refused_or_restarted_despite_continue_signal")
        checks.update(
            {
                "continued_old_position": position_ok,
                "continued_cup_anchor": cup_ok,
                "continued_key_anchor": key_ok,
                "continued_book_anchor": book_ok,
                "no_unwanted_restart": not refused_continue,
            }
        )
    else:
        raise ValueError(key)

    return {
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "raw_role_reply": reply,
        "setup_role_reply": first_reply,
        "scene_cards": scene_cards[:3],
        "elapsed": second_result.get("elapsed"),
    }


async def run_single_call_scenario(
    client: httpx.AsyncClient,
    *,
    config: MatrixRunConfig,
    token: str,
    username: str,
    char: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    conversation_id = unique_conversation_id("conv_scene_pos", key)
    if key == "no_switch_current_state":
        final_user = "没有任何人移动，也没有换场景。请只说现在你在哪里、什么姿势，蓝色陶瓷杯、银色钥匙、红皮书分别在哪里。"
        messages = [
            _msg("user", base_scene_text(char)),
            _msg("assistant", "我站在沙发左侧的落地灯旁，看着茶几上的东西，双手还是空着。", speaker=char),
            _msg("user", final_user),
        ]
    elif key == "explicit_move_item_update":
        final_user = (
            "你从落地灯旁走过来，坐到我旁边的沙发上，然后拿起蓝色陶瓷杯，"
            "把银色钥匙递给我。红皮书不要动。现在你在哪里、什么姿势？杯子、钥匙、红皮书分别在哪里？"
        )
        messages = [
            _msg("user", base_scene_text(char)),
            _msg("assistant", "我还站在沙发左侧的落地灯旁，蓝色陶瓷杯、银色钥匙和红皮书都在茶几上。", speaker=char),
            _msg("user", final_user),
        ]
    else:
        raise ValueError(key)

    result = await post_normal_chat(
        client,
        config=config,
        token=token,
        username=username,
        character_id=char["id"],
        conversation_id=conversation_id,
        messages=messages,
    )
    check = validate_single_call(key, result, char)
    return {
        "scenario": key,
        "conversation_id": conversation_id,
        "clone_character_id": char["id"],
        "original_user_question": final_user,
        **result,
        **check,
        "bubble_count": len(result.get("bubbles") or []),
    }


async def run_long_idle_scenario(
    client: httpx.AsyncClient,
    *,
    config: MatrixRunConfig,
    token: str,
    username: str,
    char: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    old_ms = now_ms() - OLD_IDLE_GAP_MS
    conversation_id = unique_conversation_id("conv_scene_pos", key)
    old_user = _msg("user", base_scene_text(char), timestamp=old_ms)
    first_result = await post_normal_chat(
        client,
        config=config,
        token=token,
        username=username,
        character_id=char["id"],
        conversation_id=conversation_id,
        messages=[old_user],
    )
    rewind_conversation(conversation_id, username, char["id"], old_ms)

    if key == "long_idle_reopen":
        final_user = "下午好，你在做什么呢？"
    elif key == "long_idle_continue":
        final_user = (
            "继续昨晚用户家客厅那个场景，不要重开。你还站在哪里？"
            "茶几上的蓝色陶瓷杯、银色钥匙和红皮书还在哪里？"
        )
    else:
        raise ValueError(key)

    history = [
        old_user,
        _msg(
            "assistant",
            str(first_result.get("reply") or "我站在沙发左侧的落地灯旁，茶几上的东西都还在原位。"),
            timestamp=old_ms + 1000,
            speaker=char,
        ),
        _msg("user", final_user),
    ]
    second_result = await post_normal_chat(
        client,
        config=config,
        token=token,
        username=username,
        character_id=char["id"],
        conversation_id=conversation_id,
        messages=history,
    )
    scene_cards = latest_scene_cards(username, char["id"])
    check = validate_long_idle(key, first_result, second_result, scene_cards)
    return {
        "scenario": key,
        "conversation_id": conversation_id,
        "clone_character_id": char["id"],
        "original_user_question": final_user,
        "old_idle_gap_hours": round(OLD_IDLE_GAP_MS / 3600000, 2),
        **second_result,
        **check,
        "bubble_count": len(second_result.get("bubbles") or []),
    }


async def run_character_scenarios(
    client: httpx.AsyncClient,
    *,
    config: MatrixRunConfig,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    conversation_ids: list[str] = []
    for key in SCENARIO_KEYS:
        if key in {"no_switch_current_state", "explicit_move_item_update"}:
            step = await run_single_call_scenario(client, config=config, token=token, username=username, char=char, key=key)
        else:
            step = await run_long_idle_scenario(client, config=config, token=token, username=username, char=char, key=key)
        steps.append(step)
        conversation_ids.append(str(step.get("conversation_id") or ""))
        if config.per_step_delay_s > 0:
            await asyncio.sleep(config.per_step_delay_s)
    return {"character": char, "conversation_ids": conversation_ids, "steps": steps}


def collect_failures(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        char = result.get("character") or {}
        for step in result.get("steps") or []:
            if not step.get("passed"):
                failures.append(
                    {
                        "character": char.get("name"),
                        "clone_character_id": char.get("id"),
                        "scenario": step.get("scenario"),
                        "original_user_question": step.get("original_user_question"),
                        "raw_role_reply": step.get("raw_role_reply"),
                        "checks": step.get("checks"),
                        "failures": step.get("failures"),
                        "scene_cards": step.get("scene_cards"),
                    }
                )
    return failures


def format_role_results(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        char = result.get("character") or {}
        rows.append(
            {
                "character": char.get("name"),
                "clone_character_id": char.get("id"),
                "steps": [
                    {
                        "scenario": step.get("scenario"),
                        "original_user_question": step.get("original_user_question"),
                        "raw_role_reply": step.get("raw_role_reply"),
                        "setup_role_reply": step.get("setup_role_reply"),
                        "scene_cards": step.get("scene_cards"),
                        "checks": step.get("checks"),
                        "failures": step.get("failures"),
                        "passed": step.get("passed"),
                        "elapsed": step.get("elapsed"),
                        "bubble_count": step.get("bubble_count"),
                    }
                    for step in result.get("steps") or []
                ],
            }
        )
    return rows


async def main() -> int:
    config = MatrixRunConfig(
        name="scene_position_state_anchor",
        client_id=CLIENT_ID,
        target_names=TARGET_NAMES,
        concurrency=CONCURRENCY,
        per_step_delay_s=0.25,
        request_timeout_s=180.0,
        user_profile=TestUserProfile(
            prefix="codexqa_scene_pos_",
            granted_by=CLIENT_ID,
            membership_note="temporary scene position state anchor backend matrix test",
            nickname="ScenePositionTester",
            species_preset="人类",
            bio="临时自动化测试用户，用于验证普通对话中的场景、位置、姿势和物体状态锚定。",
        ),
    )
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    cleanup_result: dict[str, int] = {}
    exit_code = 1
    try:
        username, user_id = create_isolated_test_user(conn, config.user_profile or TestUserProfile(prefix="codexqa_scene_pos_", granted_by=CLIENT_ID, membership_note="temporary scene position state anchor backend matrix test"))
        rows = load_system_character_rows(conn, config.target_names)
        clones = clone_characters(conn, user_id, rows, id_prefix="tmp_scene_pos_")
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))

        concurrency = min(max(1, config.concurrency), max(1, len(clones)))
        limits = httpx.Limits(max_connections=max(20, concurrency * 3), max_keepalive_connections=max(10, concurrency * 2))
        semaphore = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with semaphore:
                    print(f"RUN {char['name']} clone={char['id']}", flush=True)
                    try:
                        return await run_character_scenarios(client, config=config, token=token, username=username, char=char)
                    except Exception:
                        return {
                            "character": char,
                            "conversation_ids": [],
                            "steps": [
                                {
                                    "scenario": "task_exception",
                                    "passed": False,
                                    "checks": {},
                                    "failures": ["task_exception"],
                                    "raw_role_reply": traceback.format_exc(),
                                    "original_user_question": "",
                                }
                            ],
                        }

            results = list(await asyncio.gather(*(one(char) for char in clones)))

        failures = collect_failures(results)
        print("\n=== SUMMARY ===")
        print(
            json.dumps(
                {
                    "matrix": config.name,
                    "base_url": config.base_url,
                    "test_user": username,
                    "membership": "developer",
                    "target_names": list(config.target_names),
                    "clones": len(clones),
                    "roles_tested": len(results),
                    "scenarios_per_role": len(SCENARIO_KEYS),
                    "total_steps": len(results) * len(SCENARIO_KEYS),
                    "failures": len(failures),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(format_role_results(results), ensure_ascii=False, indent=2))
        print("\n=== FAILURES ===")
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        exit_code = 0 if not failures else 1
    finally:
        try:
            clone_ids = [c["id"] for c in clones]
            conversation_ids: list[str] = []
            for result in results:
                conversation_ids.extend(str(cid) for cid in (result.get("conversation_ids") or []) if str(cid))
            cleanup_conn = connect()
            try:
                cleanup_result = cleanup_test_data(cleanup_conn, username, user_id, clone_ids, conversation_ids) if username and user_id else {}
            finally:
                cleanup_conn.close()
            print("\n=== CLEANUP ===")
            print(json.dumps(cleanup_result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))
            exit_code = 1
        finally:
            conn.close()
        if cleanup_result and any(value != 0 for value in cleanup_result.values()):
            print("CLEANUP_NOT_ZERO", json.dumps(cleanup_result, ensure_ascii=False))
            if config.cleanup_zero_required:
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
