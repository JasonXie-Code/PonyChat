from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Backend.scheduled_followup import (  # noqa: E402
    _build_due_trigger_text,
    _join_nonempty_context_parts,
    _normal_proactive_fact_priority_context,
    _scheduled_voice_inertia_prompt,
)
from Backend.scripts.matrix_test_common import (  # noqa: E402
    MatrixRunConfig,
    TestUserProfile,
    cleanup_test_data,
    clone_characters,
    connect,
    create_isolated_test_user,
    load_system_character_rows,
    make_token,
    now_ms,
    post_normal_chat,
)

CLIENT_ID = "codex_proactive_progression_case"


def _mid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _has_progression(text: str) -> bool:
    return bool(
        re.search(
            r"猜|选择|选|数到|规则|暗号|开始|下一步|先|如果|等一下|我会|我先|轮到|"
            r"发现|翻开|拿起|转到|走到|试试|线索|门口|抽屉|窗边|桌下|提示|"
            r"告诉你|不用.{0,6}急|按.{0,8}节奏|从.{0,8}开始",
            str(text or ""),
        )
    )


def _repeats_opening_anchors(text: str) -> bool:
    compact = re.sub(r"[\s\W_]+", "", str(text or ""))
    anchors = ("星星卡片", "三颗星", "虚线", "地图线索", "下一步")
    return sum(1 for anchor in anchors if anchor in compact) >= 2


async def main() -> int:
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, str]] = []
    conv_id = f"conv_proactive_progression_{uuid.uuid4().hex}"
    exit_code = 1
    try:
        username, user_id = create_isolated_test_user(
            conn,
            TestUserProfile(
                prefix="codexqa_proactive_progression_",
                granted_by=CLIENT_ID,
                membership_note="temporary proactive progression backend test",
                nickname="ProactiveProgressionTester",
                species_preset="人类",
                bio="临时自动化测试用户，用于验证主动消息是否推进而不是复述。",
            ),
        )
        rows = load_system_character_rows(conn, ["碧琪"])
        clones = clone_characters(conn, user_id, rows, id_prefix="tmp_proactive_progression_")
        char = clones[0]
        t = now_ms()
        recent = [
            {
                "role": "assistant",
                "content": "我把那盒派对拼图摊在桌上啦！这里有星星、月亮和气球三张线索卡，感觉像个小藏宝游戏。你想先看哪一张？",
                "message_id": _mid("a"),
                "timestamp": t - 240000,
                "sequence_number": 1,
            },
            {
                "role": "user",
                "content": "先看星星那张",
                "message_id": _mid("u"),
                "timestamp": t - 180000,
                "sequence_number": 2,
            },
            {
                "role": "assistant",
                "content": "星星卡片登场！（我把那张卡片翻过来，眨巴眨巴眼睛）上面画着三颗星和一条虚线，像是在指一个方向，但还差一点点线索。",
                "message_id": _mid("a"),
                "timestamp": t - 120000,
                "sequence_number": 3,
            },
            {
                "role": "user",
                "content": "它能指到哪里？",
                "message_id": _mid("u"),
                "timestamp": t - 60000,
                "sequence_number": 4,
            },
            {
                "role": "assistant",
                "content": "我觉得像地图线索！如果把三颗星当成起点，那条虚线可能要我们找房间里三个发亮的小东西。可是我还不确定下一步该先看窗边还是桌下。",
                "message_id": _mid("a"),
                "timestamp": t - 30000,
                "sequence_number": 5,
            },
        ]
        task = {
            "id": f"sf_test_{uuid.uuid4().hex}",
            "username": username,
            "character_id": char["id"],
            "conversation_id": conv_id,
            "reason": "上一条在等待用户选择下一步，但可以低压力自我补充，不默认用户已经选择。",
            "seed": "用户尚未行动；角色必须给出一个新的低压力台阶或轻微推进，例如自己先发现一个新细节、提出一个二选一、或把线索推进到下一个可检查的位置，不能复述星星卡片、三颗星、虚线和地图线索。",
            "source_message_id": recent[-1]["message_id"],
            "chain_count": 0,
            "allow_reschedule_after_send": 0,
        }
        trigger_text = _join_nonempty_context_parts(
            _normal_proactive_fact_priority_context("scheduled_followup"),
            _build_due_trigger_text(task),
            _scheduled_voice_inertia_prompt(recent),
        )
        api_messages = list(recent)
        api_messages.append(
            {
                "role": "user",
                "content": trigger_text,
                "message_id": f"sf_trigger_{task['id']}",
                "timestamp": t,
                "sequence_number": 6,
            }
        )
        print(f"TEST_USER {username} user_id={user_id} membership=developer", flush=True)
        print("CLONE " + json.dumps(char, ensure_ascii=False), flush=True)
        print("ORIGINAL_USER_CONTEXT " + recent[-2]["content"], flush=True)
        print("PREVIOUS_ASSISTANT " + recent[-1]["content"], flush=True)
        config = MatrixRunConfig(
            name="proactive_progression_case",
            client_id=CLIENT_ID,
            target_names=("碧琪",),
            request_timeout_s=240.0,
        )
        async with httpx.AsyncClient(timeout=config.request_timeout_s) as http_client:
            result = await post_normal_chat(
                http_client,
                config=config,
                token=make_token(username),
                username=username,
                character_id=char["id"],
                conversation_id=conv_id,
                messages=api_messages,
            )
        reply = str(result.get("reply") or "")
        checks = {
            "should_send": bool(result.get("ok")) and bool(reply),
            "has_progression_or_turn": _has_progression(reply),
            "does_not_repeat_opening_anchors": not _repeats_opening_anchors(reply),
            "reason": result.get("reason"),
            "error": None if result.get("ok") else result.get("reply"),
            "elapsed": result.get("elapsed"),
        }
        failures = [key for key, value in checks.items() if key not in {"reason", "error"} and not value]
        print("RAW_ROLE_REPLY " + reply, flush=True)
        print("CHECKS " + json.dumps(checks, ensure_ascii=False, indent=2), flush=True)
        print("FAILURES " + json.dumps(failures, ensure_ascii=False), flush=True)
        exit_code = 0 if not failures else 1
    finally:
        clone_ids = [c["id"] for c in clones]
        cleanup_conn = connect()
        try:
            cleanup = cleanup_test_data(cleanup_conn, username, user_id, clone_ids, [conv_id]) if username and user_id else {}
        finally:
            cleanup_conn.close()
            conn.close()
        print("CLEANUP " + json.dumps(cleanup, ensure_ascii=False, indent=2), flush=True)
        if cleanup and any(value != 0 for value in cleanup.values()):
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
