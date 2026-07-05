from __future__ import annotations

import re
import time
from typing import Any

import aiosqlite

from ..db import get_database
from ..utils import ChatRequest


_HYPOTHETICAL_RE = re.compile(
    r"(如果|假如|假设|比如|要是|会不会|能不能|可以不可以|想象|梦到|梦见|如果我|假设我|what if|suppose|imagine)",
    re.IGNORECASE,
)

_LETHAL_CN_RE = re.compile(
    r"(我|本人|老子|爷|咱).{0,18}"
    r"(杀了你|杀死你|杀掉你|弄死你|打死你|砍死你|刺死你|掐死你|把你杀了|把你杀死|把你杀掉|把你弄死|把你打死|把你砍死|把你刺死|把你掐死|"
    r"杀了她|杀死她|杀掉她|弄死她|打死她|砍死她|刺死她|掐死她|把她杀了|把她杀死|把她杀掉|把她弄死|把她打死|把她砍死|把她刺死|把她掐死|"
    r"杀了他|杀死他|杀掉他|弄死他|打死他|砍死他|刺死他|掐死他|把他杀了|把他杀死|把他杀掉|把他弄死|把他打死|把他砍死|把他刺死|把他掐死)",
)
_LETHAL_PASSIVE_CN_RE = re.compile(
    r"(你|她|他|角色).{0,8}(被我|让我|给我).{0,8}(杀死|杀了|杀掉|弄死|打死|砍死|刺死|掐死)"
)
_LETHAL_ASPECT_CN_RE = re.compile(
    r"(我|本人|老子|爷|咱).{0,18}(杀死|杀掉|弄死|打死|砍死|刺死|掐死)了?(你|她|他)"
)
_FATAL_WOUND_CN_RE = re.compile(
    r"(我|本人|老子|爷|咱).{0,24}"
    r"(爆头|打爆.{0,4}头|击穿.{0,4}头|射穿.{0,4}头|贯穿.{0,4}头|"
    r"刺穿.{0,4}心脏|击穿.{0,4}心脏|射穿.{0,4}心脏|贯穿.{0,4}心脏|捏碎.{0,4}心脏|"
    r"砍下.{0,4}头|斩首|割断.{0,4}喉咙|拧断.{0,4}脖子)"
)
_FATAL_WOUND_PASSIVE_CN_RE = re.compile(
    r"(你|她|他|角色).{0,10}(被我|让我|给我).{0,10}"
    r"(爆头|打爆.{0,4}头|击穿.{0,4}头|射穿.{0,4}头|贯穿.{0,4}头|"
    r"刺穿.{0,4}心脏|击穿.{0,4}心脏|射穿.{0,4}心脏|贯穿.{0,4}心脏|捏碎.{0,4}心脏|"
    r"砍下.{0,4}头|斩首|割断.{0,4}喉咙|拧断.{0,4}脖子)"
)
_FATAL_WOUND_EN_RE = re.compile(
    r"\b(i|me)\b.{0,50}\b(headshot|shot .*head|shot .*heart|stabbed .*heart|pierced .*heart|"
    r"blew .*head|crushed .*heart|decapitated|cut .*head off|broke .*neck|slit .*throat)\b",
    re.IGNORECASE,
)
_LETHAL_EN_RE = re.compile(
    r"\b(i|me)\b.{0,40}\b(killed|kill|murdered|murder|slain|slay)\b"
    r".{0,30}\b(you|her|him|the character)\b|\b(i|me)\b.{0,40}\b(beat|stabbed|shot|choked)\b.{0,20}\b(you|her|him)\b.{0,20}\bto death\b",
    re.IGNORECASE,
)
_PROXY_OR_FAKE_DEATH_CN_RE = re.compile(
    r"(假死|装死|伪装死亡|"
    r"(杀死|杀掉|弄死|打死|砍死|刺死|掐死|击碎|打碎|击散|打散)了?(你|她|他)?的?"
    r"(分身|替身|幻象|幻影|投影|影子|假身|化身|复制体|克隆体)|"
    r"(死的|倒下的|被杀死的|被打死的).{0,10}(只是|不过是)?(你|她|他)?的?"
    r"(分身|替身|幻象|幻影|投影|影子|假身|化身|复制体|克隆体))"
)
_PROXY_ACTUALLY_KILLS_BODY_CN_RE = re.compile(
    r"((再|又|然后|接着|同时).{0,12}(杀死|杀掉|弄死|打死|砍死|刺死|掐死)了?(你|她|他)|"
    r"(本体|真身).{0,8}(也|同样|一起|已经|被).{0,8}(死了|死亡|杀死|杀了|杀掉|弄死|打死))"
)
_PROXY_OR_FAKE_DEATH_EN_RE = re.compile(
    r"\b(fake death|faked death|played dead|your clone|her clone|his clone|"
    r"body double|decoy|illusion|projection|avatar)\b",
    re.IGNORECASE,
)


def now_ms() -> int:
    return int(time.time() * 1000)


def latest_user_message(request: ChatRequest) -> Any | None:
    return next(
        (
            m
            for m in reversed(getattr(request, "messages", None) or [])
            if getattr(m, "role", None) == "user" and not getattr(m, "isHidden", False)
        ),
        None,
    )


def latest_user_text(request: ChatRequest) -> str:
    msg = latest_user_message(request)
    return str(getattr(msg, "content", "") or "") if msg is not None else ""


def latest_user_message_id(request: ChatRequest) -> str:
    msg = latest_user_message(request)
    return str(getattr(msg, "message_id", "") or "") if msg is not None else ""


def is_explicit_character_death_action(text: str, *, character_name: str = "") -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    compact = re.sub(r"\s+", "", raw)
    lowered = raw.lower()
    if _HYPOTHETICAL_RE.search(raw):
        return False
    if _PROXY_OR_FAKE_DEATH_CN_RE.search(compact) and not _PROXY_ACTUALLY_KILLS_BODY_CN_RE.search(compact):
        return False
    if _PROXY_OR_FAKE_DEATH_EN_RE.search(raw) and not re.search(
        r"\b(then|also|again)\b.{0,30}\b(kill|killed|murder|murdered|slay|slain)\b.{0,30}\b(you|her|him)\b",
        raw,
        re.IGNORECASE,
    ):
        return False
    if (
        _LETHAL_CN_RE.search(compact)
        or _LETHAL_PASSIVE_CN_RE.search(compact)
        or _LETHAL_ASPECT_CN_RE.search(compact)
        or _FATAL_WOUND_CN_RE.search(compact)
        or _FATAL_WOUND_PASSIVE_CN_RE.search(compact)
    ):
        return True
    if _LETHAL_EN_RE.search(lowered) or _FATAL_WOUND_EN_RE.search(lowered):
        return True
    name = re.sub(r"\s+", "", str(character_name or ""))
    if name and name in compact and re.search(r"(我|本人).{0,18}(杀死|杀了|杀掉|弄死|打死|砍死|刺死|掐死)", compact):
        return True
    if name and re.search(rf"{re.escape(name)}.{{0,8}}(死了|被我杀死|被我杀了|被我打死)", compact):
        return True
    return False


async def ensure_normal_lifecycle_table() -> None:
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await ensure_normal_lifecycle_table_on_connection(conn)
        await conn.commit()


async def ensure_normal_lifecycle_table_on_connection(conn: aiosqlite.Connection) -> None:
    await conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS normal_character_lifecycle (
            username TEXT NOT NULL,
            character_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'alive',
            death_message_id TEXT DEFAULT '',
            death_reason TEXT DEFAULT '',
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            PRIMARY KEY (username, character_id, conversation_id)
        );
        CREATE INDEX IF NOT EXISTS idx_normal_character_lifecycle_state
            ON normal_character_lifecycle(username, character_id, state);
        """
    )


async def reset_normal_character_lifecycle_on_connection(
    conn: aiosqlite.Connection,
    username: str,
    character_id: str,
) -> int:
    if not username or not character_id:
        return 0
    await ensure_normal_lifecycle_table_on_connection(conn)
    cur = await conn.execute(
        """
        UPDATE normal_character_lifecycle
           SET state='alive',
               death_message_id='',
               death_reason='',
               updated_at_ms=?
         WHERE username=?
           AND character_id=?
           AND (
                COALESCE(state, '') <> 'alive'
                OR COALESCE(death_message_id, '') <> ''
                OR COALESCE(death_reason, '') <> ''
           )
        """,
        (now_ms(), username, character_id),
    )
    return max(0, cur.rowcount or 0)


async def get_normal_character_state(username: str, character_id: str, conversation_id: str) -> str:
    if not username or not character_id:
        return "alive"
    await ensure_normal_lifecycle_table()
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute(
            """
            SELECT state
              FROM normal_character_lifecycle
             WHERE username=? AND character_id=? AND conversation_id=?
             LIMIT 1
            """,
            (username, character_id, conversation_id or ""),
        ) as cur:
            row = await cur.fetchone()
    return str(row[0] or "alive") if row else "alive"


async def mark_normal_character_dead(
    username: str,
    character_id: str,
    conversation_id: str,
    *,
    message_id: str = "",
    reason: str = "",
) -> None:
    if not username or not character_id:
        return
    await ensure_normal_lifecycle_table()
    ts = now_ms()
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            INSERT INTO normal_character_lifecycle (
                username, character_id, conversation_id, state,
                death_message_id, death_reason, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, 'dead', ?, ?, ?, ?)
            ON CONFLICT(username, character_id, conversation_id) DO UPDATE SET
                state='dead',
                death_message_id=excluded.death_message_id,
                death_reason=excluded.death_reason,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                username,
                character_id,
                conversation_id or "",
                message_id or "",
                reason[:300],
                ts,
                ts,
            ),
        )
        await conn.commit()
