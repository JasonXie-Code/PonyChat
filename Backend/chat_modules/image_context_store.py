"""普通对话：近期用户图片识图结果持久化存储，供多轮纯文字追问时由导演选择是否注入主回复。"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from ..config import logger
from ..db import get_database

# 池内保留的「发图轮次」上限
POOL_MAX_ENTRIES = 10
# 主回复可注入的最近组数
INJECT_MAX = 4


@dataclass
class StoredImageContext:
    entry_id: str
    created_ms: int
    user_text: str
    image_count: int
    should_refuse: bool
    image_summary: str
    visible_text: str
    identified_entities: List[str] = field(default_factory=list)
    uncertainty: str = ""
    error: str = ""


def _norm_user(v: Optional[str]) -> str:
    return (v or "").strip() or "anonymous"


def _norm_char(v: Optional[str]) -> str:
    return (v or "").strip() or "none"


def _norm_conv(v: Optional[str]) -> str:
    return (v or "").strip() or "default"


async def get_last_reply_based_on_image(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
) -> bool:
    db = get_database()
    await db.init()
    conn = await db.acquire()
    try:
        cur = await conn.execute(
            """SELECT last_reply_based_on_image
               FROM normal_image_context_state
               WHERE username=? AND character_id=? AND conversation_id=?""",
            (_norm_user(username), _norm_char(character_id), _norm_conv(conversation_id)),
        )
        row = await cur.fetchone()
        return bool(row and row[0])
    except Exception as e:
        logger.warning("[NormalImage] 读取 last_reply_based_on_image 失败: %s", e)
        return False
    finally:
        await db.release(conn)


async def set_last_reply_based_on_image(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
    value: bool,
) -> None:
    db = get_database()
    await db.init()
    conn = await db.acquire()
    try:
        await conn.execute(
            """INSERT INTO normal_image_context_state
                   (username, character_id, conversation_id, last_reply_based_on_image, updated_ms)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(username, character_id, conversation_id)
               DO UPDATE SET
                   last_reply_based_on_image=excluded.last_reply_based_on_image,
                   updated_ms=excluded.updated_ms""",
            (
                _norm_user(username),
                _norm_char(character_id),
                _norm_conv(conversation_id),
                1 if value else 0,
                int(time.time() * 1000),
            ),
        )
        await conn.commit()
    except Exception as e:
        logger.warning("[NormalImage] 写入 last_reply_based_on_image 失败: %s", e)
    finally:
        await db.release(conn)


async def append_from_vision_fields(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
    *,
    user_text: str,
    image_count: int,
    should_refuse: bool = False,
    image_summary: str = "",
    visible_text: str = "",
    identified_entities: Optional[List[str]] = None,
    uncertainty: str = "",
    error: str = "",
) -> None:
    """一轮用户发图并成功跑完识图后调用，由 service / normal_nonstream 在适当时机写入。"""
    db = get_database()
    await db.init()
    conn = await db.acquire()
    u = _norm_user(username)
    c = _norm_char(character_id)
    conv = _norm_conv(conversation_id)
    try:
        created_ms = int(time.time() * 1000)
        await conn.execute(
            """INSERT INTO normal_image_contexts
                   (entry_id, username, character_id, conversation_id, created_ms,
                    user_text, image_count, should_refuse, image_summary, visible_text,
                    identified_entities_json, uncertainty, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"imgctx_{created_ms}_{uuid.uuid4().hex[:8]}",
                u,
                c,
                conv,
                created_ms,
                (user_text or "").strip()[:2000],
                max(0, int(image_count or 0)),
                1 if should_refuse else 0,
                (image_summary or "")[:4000],
                (visible_text or "")[:4000],
                json.dumps(list(identified_entities or [])[:20], ensure_ascii=False),
                (uncertainty or "")[:2000],
                (error or "")[:500],
            ),
        )
        await conn.execute(
            """DELETE FROM normal_image_contexts
               WHERE username=? AND character_id=? AND conversation_id=?
                 AND entry_id NOT IN (
                     SELECT entry_id FROM normal_image_contexts
                     WHERE username=? AND character_id=? AND conversation_id=?
                     ORDER BY created_ms DESC
                     LIMIT ?
                 )""",
            (u, c, conv, u, c, conv, POOL_MAX_ENTRIES),
        )
        await conn.commit()
    except Exception as e:
        logger.warning("[NormalImage] 写入图片上下文失败: %s", e)
    finally:
        await db.release(conn)


async def count_stored(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
) -> int:
    db = get_database()
    await db.init()
    conn = await db.acquire()
    try:
        cur = await conn.execute(
            """SELECT COUNT(*)
               FROM normal_image_contexts
               WHERE username=? AND character_id=? AND conversation_id=?""",
            (_norm_user(username), _norm_char(character_id), _norm_conv(conversation_id)),
        )
        row = await cur.fetchone()
        return int(row[0] if row else 0)
    except Exception as e:
        logger.warning("[NormalImage] 统计图片上下文失败: %s", e)
        return 0
    finally:
        await db.release(conn)


async def get_last_n_for_injection(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
    n: int = INJECT_MAX,
) -> List[StoredImageContext]:
    """返回最近 n 个条目，**从新到旧**（[0]=最近一组）。"""
    db = get_database()
    await db.init()
    conn = await db.acquire()
    try:
        cur = await conn.execute(
            """SELECT entry_id, created_ms, user_text, image_count, should_refuse,
                      image_summary, visible_text, identified_entities_json, uncertainty, error
               FROM normal_image_contexts
               WHERE username=? AND character_id=? AND conversation_id=?
               ORDER BY created_ms DESC
               LIMIT ?""",
            (
                _norm_user(username),
                _norm_char(character_id),
                _norm_conv(conversation_id),
                max(1, int(n or INJECT_MAX)),
            ),
        )
        rows = await cur.fetchall()
    except Exception as e:
        logger.warning("[NormalImage] 读取图片上下文失败: %s", e)
        return []
    finally:
        await db.release(conn)

    out: List[StoredImageContext] = []
    for row in rows:
        ents: List[str] = []
        try:
            parsed = json.loads(row[7] or "[]")
            if isinstance(parsed, list):
                ents = [str(x) for x in parsed if str(x).strip()][:20]
        except Exception:
            ents = []
        out.append(
            StoredImageContext(
                entry_id=row[0],
                created_ms=int(row[1] or 0),
                user_text=row[2] or "",
                image_count=int(row[3] or 0),
                should_refuse=bool(row[4]),
                image_summary=row[5] or "",
                visible_text=row[6] or "",
                identified_entities=ents,
                uncertainty=row[8] or "",
                error=row[9] or "",
            )
        )
    return out


def format_prior_injection_block(entries: List[StoredImageContext]) -> str:
    if not entries:
        return ""
    lines: List[str] = [
        "【历史图片上下文（系统内部，主模型无视觉。以下来自此前用户发图时的识图结果，按**最新→较早**排列；"
        "仅当与当前用户问题相关时使用，可自然引用细节，不要复述系统标签。）】"
    ]
    for i, e in enumerate(entries, start=1):
        label = f"最近第{i}组"
        lines.append(f"[{label}] id={e.entry_id}")
        lines.append(f"用户发图时附言（若有）：{e.user_text or '（无文字）'}")
        lines.append(f"发图张数：{e.image_count}")
        if e.should_refuse:
            lines.append("该组图片被系统拒绝识别，不得向下游补细节，仅可让人设自然地说明被拦截并转移话题。")
        elif e.error and not (e.image_summary or "").strip():
            lines.append(f"识图未完全成功：{e.error}。勿编造画外细节。")
        else:
            if e.image_summary:
                lines.append("画面说明：" + e.image_summary)
            if e.visible_text:
                lines.append("图中可读文字：" + e.visible_text)
            if e.identified_entities:
                lines.append("实体：" + "、".join(e.identified_entities))
            if e.uncertainty:
                lines.append("不确定点：" + e.uncertainty)
        lines.append("")
    return "\n".join(lines).rstrip()
