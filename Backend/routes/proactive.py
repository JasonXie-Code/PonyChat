"""
主动消息推送 API
GET  /api/proactive/pending  — 旧客户端轮询入口；主动消息现统一走 chat_complete，返回空列表
POST /api/proactive/read     — 将指定消息（或全部）标记为已读
"""
from typing import List, Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel

import aiosqlite

from ..config import logger
from ..db.database import get_database

router = APIRouter()


async def _verify(x_chat_auth: Optional[str]) -> Optional[str]:
    """复用 auth 模块的 token 验证，返回 username 或 None。"""
    if not x_chat_auth:
        return None
    try:
        from .auth import auth_token_verify
        return await auth_token_verify(x_chat_auth.strip())
    except Exception:
        return None


# ── GET /api/proactive/pending（待读主动消息） ──────────────────────────────────

@router.get("/api/proactive/pending")
async def get_pending_proactive(
    character_id: Optional[str] = None,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """
    旧版本曾从 proactive_messages 单独返回待展示消息。现在主动消息只是 normal assistant
    reply 的一种触发方式，客户端展示统一从 message_outbox 的 chat_complete 事件触发后补拉
    messages 真源；proactive_messages 仅保留审计/任务记录语义。
    """
    username = await _verify(x_chat_auth)
    if not username:
        return {"status": "error", "message": "unauthorized"}, 401
    return {"status": "ok", "messages": []}


# ── POST /api/proactive/read（标记已读） ────────────────────────────────────────

class ReadRequest(BaseModel):
    ids: Optional[List[int]] = None   # None 或空列表表示标记全部已读
    character_id: Optional[str] = None  # 配合 ids=None 时，只标记该角色的消息


@router.post("/api/proactive/read")
async def mark_proactive_read(
    body: ReadRequest,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """将指定 id 列表的主动消息标记为已读；ids 为空则标记全部（可按 character_id 过滤）。"""
    username = await _verify(x_chat_auth)
    if not username:
        return {"status": "error", "message": "unauthorized"}, 401

    db = get_database()
    try:
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute("PRAGMA busy_timeout = 500")
            cursor = await conn.execute("SELECT id FROM users WHERE username=?", (username,))
            row = await cursor.fetchone()
            if not row:
                return {"status": "ok", "updated": 0}
            user_id = row[0]

            if body.ids:
                placeholders = ",".join("?" * len(body.ids))
                await conn.execute(
                    f"""UPDATE proactive_messages
                        SET is_read=1, read_at=CURRENT_TIMESTAMP
                        WHERE user_id=? AND id IN ({placeholders})""",
                    (user_id, *body.ids),
                )
            elif body.character_id:
                await conn.execute(
                    """UPDATE proactive_messages
                       SET is_read=1, read_at=CURRENT_TIMESTAMP
                       WHERE user_id=? AND character_id=? AND is_read=0""",
                    (user_id, body.character_id),
                )
            else:
                await conn.execute(
                    "UPDATE proactive_messages SET is_read=1, read_at=CURRENT_TIMESTAMP WHERE user_id=? AND is_read=0",
                    (user_id,),
                )

            await conn.commit()
        return {"status": "ok"}
    except Exception as e:
        if "database is locked" in str(e).lower():
            logger.debug("⚠️ [ProactiveAPI] mark_read skipped: database is locked")
        else:
            logger.warning(f"⚠️ [ProactiveAPI] mark_read 失败: {e}")
        return {"status": "error", "message": "internal error"}
