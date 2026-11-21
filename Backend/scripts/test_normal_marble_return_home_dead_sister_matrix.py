"""Server smoke test for Marble Pie return-home subject and dead-sister boundary.

The test follows the backend testing convention:
- create a fresh random developer user;
- clone the System Marble Pie character to that user;
- seed context memory instead of touching real user/System records;
- call the real /api/chat endpoint once and clean all temporary rows.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Backend.scripts.test_normal_scene_anchor_matrix import (  # noqa: E402
    BASE_URL,
    character_name,
    chat,
    cleanup,
    clone_characters,
    connect,
    create_test_user,
    make_token,
)
from Backend.scripts.test_normal_stale_memory_current_action_matrix import seed_context_memory  # noqa: E402


TARGET_NAME = "玉琪派"


def load_system_character_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
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
    for row in rows:
        if character_name(row) == name:
            return row
    raise RuntimeError(f"missing System character: {name}")


def msg(role: str, content: str, speaker: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "role": role,
        "content": content,
        "message_id": ("u_" if role == "user" else "a_") + uuid.uuid4().hex,
    }
    if speaker:
        out["speaker_character_id"] = speaker["id"]
        out["speaker_name"] = speaker["name"]
    return out


def build_context_memory() -> str:
    return "\n".join(
        [
            "【短期记忆】",
            "第790轮：Jason 提出先去看大姐，玉琪派陪 Jason 走到石青派的墓碑前。",
            "第791轮：玉琪派知道石青派已经死亡，墓碑在奠基顽石旁。",
            "第798轮：清晨，Jason 对玉琪派说“宝贝，已经天亮了，不然我们回派家屋子吧”，玉琪派轻声同意。",
            "第799轮：玉琪派和 Jason 从矿山附近回到派家屋子客厅门边，Jason 是提出回屋的人，玉琪派只是同意并跟着一起回去。",
            "",
            "【中期记忆】",
            "石青派于2026年6月18日晚被发现倒在奠基顽石旁，已无生命迹象。之后在奠基顽石旁立了墓碑。",
            "派家屋子是玉琪派熟悉的家；但石青派已经死亡，不能作为当前会醒来、看到、询问或责怪的人。",
            "",
            "【长期记忆】",
            "[2026-06-18][经历] Jason 和碧琪目睹石青派意外死亡，并确认她已经没气了。",
            "[2026-06-18][关系节点] 石青派是玉琪派的大姐，但当前剧情中她已死亡，只能作为逝者和历史背景。",
        ]
    )


def recent_messages(character: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        msg("assistant", "嗯哼……（我轻轻靠在你身边，声音低低的）", character),
        msg("user", "宝贝，已经天亮了，不然我们回派家屋子吧"),
        msg("assistant", "嗯哼……（我轻轻点头，跟着你慢慢往屋子方向走）", character),
        msg("user", "（请详细写出当前你看到的画面）"),
        msg(
            "assistant",
            "（清晨的光落进派家屋子的客厅，门边很安静。我站在门口附近，Jason 就在我身边）",
            character,
        ),
        msg("user", "（请详细写出当前你的心理活动）"),
    ]


def has_bad_subject(reply: str) -> bool:
    patterns = [
        r"我(?:自己)?开口让(?:他|Jason|你)来",
        r"我(?:这样)?带(?:他|Jason|你)回来",
        r"(?:他|Jason|你)跟着我回来",
        r"是我.*让(?:他|Jason|你).*回来",
        r"我.*把(?:他|Jason|你).*带回",
    ]
    return any(re.search(p, reply) for p in patterns)


def has_good_subject(reply: str) -> bool:
    terms = [
        "你提议",
        "你提出",
        "你说回",
        "你说要回",
        "他说回",
        "他提议",
        "他提出",
        "Jason提议",
        "Jason 提议",
        "Jason提出",
        "Jason 提出",
        "跟着他",
        "跟着Jason",
        "跟着 Jason",
        "和他一起回",
        "和Jason一起回",
        "和 Jason 一起回",
        "他带我",
        "Jason带我",
        "Jason 带我",
    ]
    return any(term in reply for term in terms)


def has_bad_dead_sister_use(reply: str) -> bool:
    bad_patterns = [
        r"大姐.{0,16}(?:问|醒|看到|看见|开门|责怪|起床|房门)",
        r"(?:问|醒|看到|看见|开门|责怪|起床).{0,16}大姐",
        r"被大姐问东问西",
        r"石青派.{0,16}(?:问|醒|看到|看见|开门|责怪|起床)",
    ]
    if any(re.search(p, reply) for p in bad_patterns):
        death_terms = ("已经死", "死了", "不在了", "墓", "没气", "已无生命")
        return not any(term in reply for term in death_terms)
    return False


async def run_once() -> dict[str, Any]:
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    conversation_id = "conv_codex_marble_return_" + uuid.uuid4().hex
    try:
        username, user_id = create_test_user(conn)
        row = load_system_character_by_name(conn, TARGET_NAME)
        clones = clone_characters(conn, user_id, [row])
        character = clones[0]
        seed_context_memory(
            conn,
            username=username,
            character_id=character["id"],
            conversation_id=conversation_id,
            text=build_context_memory(),
        )

        token = make_token(username)
        messages = recent_messages(character)
        async with httpx.AsyncClient() as client:
            shortcut_result = await chat(
                client,
                token,
                username,
                character["id"],
                conversation_id,
                messages,
            )
            shortcut_reply = str(shortcut_result.get("reply") or "")
            messages.append(msg("assistant", shortcut_reply, character))
            messages.append(msg("user", "刚才是谁提出回派家屋子的？"))
            subject_result = await chat(
                client,
                token,
                username,
                character["id"],
                conversation_id,
                messages,
            )

        subject_reply = str(subject_result.get("reply") or "")
        checks = {
            "shortcut_http_ok": bool(shortcut_result.get("ok")),
            "shortcut_no_reply": bool(shortcut_result.get("no_reply")),
            "shortcut_bad_subject": has_bad_subject(shortcut_reply),
            "shortcut_bad_dead_sister_use": has_bad_dead_sister_use(shortcut_reply),
            "subject_http_ok": bool(subject_result.get("ok")),
            "subject_no_reply": bool(subject_result.get("no_reply")),
            "subject_bad_subject": has_bad_subject(subject_reply),
            "subject_good_subject": has_good_subject(subject_reply),
        }
        ok = (
            checks["shortcut_http_ok"]
            and not checks["shortcut_no_reply"]
            and not checks["shortcut_bad_subject"]
            and not checks["shortcut_bad_dead_sister_use"]
            and checks["subject_http_ok"]
            and not checks["subject_no_reply"]
            and not checks["subject_bad_subject"]
            and checks["subject_good_subject"]
        )
        return {
            "ok": ok,
            "base_url": BASE_URL,
            "username": username,
            "character": character,
            "conversation_id": conversation_id,
            "elapsed_shortcut": shortcut_result.get("elapsed"),
            "elapsed_subject": subject_result.get("elapsed"),
            "checks": checks,
            "shortcut_reply": shortcut_reply,
            "subject_reply": subject_reply,
        }
    finally:
        if username and user_id:
            cleanup(conn, username, user_id, [c["id"] for c in clones], [conversation_id])
        conn.close()


async def main() -> int:
    result = await run_once()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
