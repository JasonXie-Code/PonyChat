"""
入队 + WebSocket 推送（带 outbox_id），供 AI 回复完成与主动消息共用。
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import aiosqlite

from .config import logger
from .db import get_database
from .db.outbox_dao import OutboxDAO
from .db.users_dao import UsersDAO
from .websocket import manager


async def mark_proactive_read_for_outbox_ack_before_deliver(user_id: int, outbox_ids: List[str]) -> None:
    """
    旧 proactive_message outbox 的清理钩子。

    新主动消息只发送 chat_complete；这里仅用于清理历史 outbox 里可能残留的 proactive_message。
    """
    if not outbox_ids:
        return
    ids = [str(x).strip() for x in outbox_ids if str(x).strip()]
    if not ids:
        return
    db = get_database()
    await db.init()
    placeholders = ",".join("?" * len(ids))
    sql = (
        f"SELECT msg_type, payload_json FROM message_outbox "
        f"WHERE user_id=? AND delivered_at IS NULL AND id IN ({placeholders})"
    )
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            async with conn.execute(sql, (user_id, *ids)) as cur:
                rows = await cur.fetchall()
            for msg_type, payload_json in rows:
                if msg_type != "proactive_message":
                    continue
                try:
                    payload = json.loads(payload_json) if payload_json else {}
                except Exception:
                    payload = {}
                raw_pid = payload.get("id")
                if raw_pid is None:
                    continue
                try:
                    proactive_pk = int(raw_pid)
                except (TypeError, ValueError):
                    continue
                await conn.execute(
                    """UPDATE proactive_messages SET is_read=1, read_at=CURRENT_TIMESTAMP
                       WHERE user_id=? AND id=? AND is_read=0""",
                    (user_id, proactive_pk),
                )
            await conn.commit()
    except Exception as e:
        logger.warning(f"⚠️ [outbox] mark_proactive_read_for_outbox_ack_before_deliver: {e}")


async def enqueue_and_push(username: str, msg_type: str, payload: Dict[str, Any]) -> Optional[str]:
    """
    写入 message_outbox 并向在线用户推送（payload 内勿含 type，由本函数合并）。
    返回 outbox_id；用户不存在时返回 None。
    """
    try:
        db = get_database()
        await db.init()
        users_dao = UsersDAO(db)
        user = await users_dao.get_user(username)
        if not user:
            return None
        user_id = user["id"]
        dao = OutboxDAO(db)
        oid = await dao.enqueue(user_id, msg_type, payload)
        message = {**payload, "type": msg_type, "outbox_id": oid}
        await manager.broadcast_to_user(username, message)
        return oid
    except Exception as e:
        logger.warning(f"⚠️ [outbox] enqueue_and_push 失败: {e}")
        return None


async def flush_outbox_to_websocket(websocket, username: str) -> None:
    """WebSocket 连接建立后，将未送达条目逐条推给客户端。"""
    try:
        db = get_database()
        await db.init()
        users_dao = UsersDAO(db)
        user = await users_dao.get_user(username)
        if not user:
            return
        dao = OutboxDAO(db)
        rows = await dao.list_undelivered(int(user["id"]), 200)
        for row in rows:
            payload = row.get("payload") or {}
            msg_type = row.get("msg_type") or ""
            oid = row.get("outbox_id")
            msg = {**payload, "type": msg_type, "outbox_id": oid}
            try:
                await websocket.send_json(msg)
            except Exception as e:
                logger.warning(f"⚠️ [outbox] 补推中断 {username}: {e}")
                break
    except Exception as e:
        logger.warning(f"⚠️ [outbox] flush_outbox_to_websocket: {e}")


async def enqueue_chat_complete(
    username: str,
    character_id: str,
    conversation_id: str,
    message_id: str,
    preview: str,
    mode: str = "normal",
    scene: Optional[Dict[str, Any]] = None,
    score_delta_reason: Optional[str] = None,
    completed_at_ms: Optional[int] = None,
    message_count: Optional[int] = None,
    assistant_message_ids: Optional[List[str]] = None,
    voice_state: Optional[Dict[str, Any]] = None,
    audio_transfer: Optional[Dict[str, Any]] = None,
) -> None:
    _ts = int(completed_at_ms) if completed_at_ms is not None else int(time.time() * 1000)
    payload: Dict[str, Any] = {
        "character_id": character_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "preview": (preview or "")[:500],
        "mode": mode or "normal",
        "completed_at_ms": _ts,
    }
    if scene:
        payload["scene"] = scene
    if score_delta_reason:
        s = str(score_delta_reason).strip()
        if s:
            payload["score_delta_reason"] = s[:500]
    if message_count is not None:
        try:
            count = int(message_count)
        except Exception:
            count = 0
        if count > 0:
            payload["message_count"] = min(count, 50)
            payload["bubble_count"] = min(count, 50)
    if assistant_message_ids:
        ids = [str(mid).strip() for mid in assistant_message_ids if str(mid).strip()]
        if ids:
            payload["assistant_message_ids"] = ids[:50]
    if isinstance(voice_state, dict) and voice_state:
        payload["voice_state"] = voice_state
    if isinstance(audio_transfer, dict) and audio_transfer:
        payload["audio_transfer"] = audio_transfer
    await enqueue_and_push(username, "chat_complete", payload)
