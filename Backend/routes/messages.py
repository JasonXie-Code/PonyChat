"""
客户端推送 outbox：未送达列表与 ACK。

主动消息现已收敛为普通 normal assistant reply 的触发方式；客户端只需要从
`GET /api/messages/undelivered` 获取 message_outbox 中尚未 ACK 的 chat_complete 等出站事件。
`/api/proactive/pending` 已退役，不再作为客户端展示消息源。
"""
from typing import Any, Dict, List, Optional
import json
import time

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..db import get_database
from ..db.deletion_audit import write_deletion_audit
from ..db.message_attachments import load_attachments_for_messages
from ..db.message_voice_states import attach_voice_state, load_voice_states_for_messages
from ..db.outbox_dao import OutboxDAO
from ..routes.auth import auth_token_verify

router = APIRouter()


class AckBody(BaseModel):
    outbox_ids: List[str]


class HideMessageBody(BaseModel):
    username: str
    character_id: str
    conversation_id: str
    message_id: str
    reason: Optional[str] = None


class VoiceSynthesizeBody(BaseModel):
    username: str
    character_id: str
    conversation_id: str
    message_id: str
    content: Optional[str] = None
    voice_id: Optional[str] = None
    instruct: Optional[str] = None
    voice_sentences: Optional[List[Dict[str, Any]]] = None
    reply_language: Optional[str] = None


class VoiceAudioAckBody(BaseModel):
    username: str
    character_id: str
    conversation_id: str
    message_id: str
    voice_cache_key: str


def _json_list(value, default=None):
    if default is None:
        default = []
    if not value:
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except Exception:
        return default


async def _enrich_search_attachment_metadata(conn, attachments: list[dict]) -> None:
    """Attach sticker descriptions used by the search UI preview."""
    for att in attachments:
        if not isinstance(att, dict):
            continue
        user_sticker_id = str(att.get("user_sticker_id") or "").strip()
        asset_id = str(att.get("asset_id") or "").strip()
        row = None
        if user_sticker_id:
            async with conn.execute(
                """SELECT name, intro, detail, image_text, custom_tags
                   FROM user_sticker_assets WHERE id = ?""",
                (user_sticker_id,),
            ) as cur:
                row = await cur.fetchone()
            if not att.get("url"):
                att["url"] = f"/api/assets/stickers/{user_sticker_id}/file"
        elif asset_id:
            async with conn.execute(
                """SELECT name, intro, detail, image_text, custom_tags
                   FROM media_assets WHERE id = ?""",
                (asset_id,),
            ) as cur:
                row = await cur.fetchone()
            if not att.get("url"):
                att["url"] = f"/api/admin/assets/{asset_id}/file"
        if not row:
            continue
        name, intro, detail, image_text, custom_tags = row
        if not att.get("name") and name:
            att["name"] = name
        meta = att.get("metadata") if isinstance(att.get("metadata"), dict) else {}
        meta = dict(meta)
        for key, value in (
            ("intro", intro or ""),
            ("detail", detail or ""),
            ("image_text", image_text or ""),
            ("custom_tags", _json_list(custom_tags)),
        ):
            if not meta.get(key) and value:
                meta[key] = value
        att["metadata"] = meta


@router.get("/api/messages/undelivered")
async def get_undelivered(
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    username = await auth_token_verify((x_chat_auth or "").strip())
    if not username:
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "unauthorized"},
        )

    db = get_database()
    await db.init()
    from ..db.users_dao import UsersDAO

    users_dao = UsersDAO(db)
    user = await users_dao.get_user(username)
    if not user:
        return {"status": "ok", "messages": []}

    dao = OutboxDAO(db)
    rows = await dao.list_undelivered(int(user["id"]), 200)
    # 仅 outbox；不含 proactive_messages 表中尚未入队或已单独轮询的未读
    return {"status": "ok", "messages": rows}


@router.post("/api/messages/ack")
async def post_ack(
    body: AckBody,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    username = await auth_token_verify((x_chat_auth or "").strip())
    if not username:
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "unauthorized"},
        )

    ids = [str(x).strip() for x in (body.outbox_ids or []) if str(x).strip()]
    if not ids:
        return {"status": "ok", "acked": 0}

    db = get_database()
    await db.init()
    from ..db.users_dao import UsersDAO

    users_dao = UsersDAO(db)
    user = await users_dao.get_user(username)
    if not user:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "user_not_found"},
        )

    from ..delivery_outbox import mark_proactive_read_for_outbox_ack_before_deliver

    uid = int(user["id"])
    await mark_proactive_read_for_outbox_ack_before_deliver(uid, ids)
    dao = OutboxDAO(db)
    n = await dao.ack(uid, ids)
    return {"status": "ok", "acked": n}


@router.post("/api/messages/voice/synthesize")
async def synthesize_message_voice_api(
    body: VoiceSynthesizeBody,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """Return cached voice audio when available, otherwise synthesize it.

    The server keeps a temporary audio cache until the Android app confirms that
    it has saved the returned audio_transfer locally.
    """
    import aiosqlite

    auth_user = await auth_token_verify((x_chat_auth or "").strip())
    if not auth_user:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})
    if auth_user != body.username:
        return JSONResponse(status_code=403, content={"status": "error", "message": "forbidden"})

    db = get_database()
    await db.init()
    content = (body.content or "").strip()
    try:
        existing_voice_state = None
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout = 30000")
            async with conn.execute(
                """SELECT m.content
                   FROM messages m
                   JOIN conversations c ON c.id = m.conversation_id
                   JOIN users u ON u.id = c.user_id
                   WHERE u.username = ?
                     AND c.character_id = ?
                     AND c.id = ?
                     AND m.message_id = ?
                     AND m.role = 'assistant'
                     AND m.deleted_at IS NULL
                     AND COALESCE(m.is_hidden, 0) = 0
                   LIMIT 1""",
                (body.username, body.character_id, body.conversation_id, body.message_id),
            ) as cur:
                row = await cur.fetchone()
            existing_states = await load_voice_states_for_messages(conn, body.conversation_id, [body.message_id])
            existing_voice_state = existing_states.get(body.message_id)
        if not row and not content:
            return JSONResponse(status_code=404, content={"status": "error", "message": "message_not_found"})
        if not content:
            content = str((existing_voice_state or {}).get("tts_text") or row[0] or "").strip()
        if not content:
            return JSONResponse(status_code=400, content={"status": "error", "message": "empty_content"})

        from ..chat_modules.voice_messages import synthesize_message_voice

        result = await synthesize_message_voice(
            username=body.username,
            character_id=body.character_id,
            conversation_id=body.conversation_id,
            message_id=body.message_id,
            content=content,
            voice_id=body.voice_id,
            instruct=body.instruct,
            voice_sentences=body.voice_sentences
            if body.voice_sentences is not None
            else (existing_voice_state or {}).get("voice_sentences") or [],
            reply_language=body.reply_language,
            push_update=False,
        )
        disabled_message = result.get("message") if result.get("error") == "voice_paused" else ""
        status_code = 200 if result.get("ok") else (503 if disabled_message else 502)
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok" if result.get("ok") else "error",
                "success": bool(result.get("ok")),
                "voice_state": result.get("voice_state") or {},
                "audio_transfer": result.get("audio_transfer"),
                "error": result.get("error") or "",
                "message": disabled_message or result.get("error") or "",
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/api/messages/voice/ack")
async def ack_message_voice_audio_api(
    body: VoiceAudioAckBody,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    auth_user = await auth_token_verify((x_chat_auth or "").strip())
    if not auth_user:
        return JSONResponse(status_code=401, content={"status": "error", "success": False, "message": "unauthorized"})
    if auth_user != body.username:
        return JSONResponse(status_code=403, content={"status": "error", "success": False, "message": "forbidden"})

    from ..db.message_voice_audio_cache import acknowledge_voice_audio_cache

    try:
        removed = await acknowledge_voice_audio_cache(
            get_database(),
            username=body.username,
            character_id=body.character_id,
            conversation_id=body.conversation_id,
            message_id=body.message_id,
            voice_cache_key=body.voice_cache_key,
        )
        return {"status": "ok", "success": True, "removed": removed}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "success": False, "message": str(e)})


# ---------------------------------------------------------------------------
# 分页消息接口
# ---------------------------------------------------------------------------

@router.post("/api/messages/hide")
async def hide_message(
    body: HideMessageBody,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """User-side soft hide for a single normal conversation message."""
    import aiosqlite

    auth_user = await auth_token_verify((x_chat_auth or "").strip())
    if not auth_user:
        return JSONResponse(status_code=401, content={"status": "error", "success": False, "message": "unauthorized"})
    if auth_user != body.username:
        return JSONResponse(status_code=403, content={"status": "error", "success": False, "message": "forbidden"})

    username = (body.username or "").strip()
    character_id = (body.character_id or "").strip()
    conversation_id = (body.conversation_id or "").strip()
    message_id = (body.message_id or "").strip()
    reason = (body.reason or "user_hide_message").strip() or "user_hide_message"
    if not username or not character_id or not conversation_id or not message_id:
        return JSONResponse(status_code=400, content={"status": "error", "success": False, "message": "missing_required_fields"})

    db = get_database()
    await db.init()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            async with conn.execute(
                """SELECT m.id, c.user_id, COALESCE(m.is_hidden, 0), m.deleted_at
                   FROM messages m
                   JOIN conversations c ON c.id = m.conversation_id
                   JOIN users u ON u.id = c.user_id
                   WHERE u.username = ?
                     AND c.character_id = ?
                     AND c.id = ?
                     AND m.message_id = ?
                   LIMIT 1""",
                (username, character_id, conversation_id, message_id),
            ) as cur:
                row = await cur.fetchone()

            if not row:
                return JSONResponse(status_code=404, content={"status": "error", "success": False, "message": "message_not_found"})

            msg_pk, user_id, is_hidden, deleted_at = row
            already_hidden = bool(is_hidden) or deleted_at is not None
            if not already_hidden:
                await conn.execute(
                    """UPDATE messages
                       SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                           delete_reason = COALESCE(delete_reason, ?),
                           is_hidden = 1,
                           hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                           hidden_reason = COALESCE(hidden_reason, ?)
                       WHERE conversation_id = ?
                         AND message_id = ?
                         AND deleted_at IS NULL
                         AND COALESCE(is_hidden, 0) = 0""",
                    (reason, reason, conversation_id, message_id),
                )
                await conn.execute(
                    """UPDATE conversations
                       SET updated_at = CURRENT_TIMESTAMP,
                           timestamp = MAX(COALESCE(timestamp, 0), ?),
                           version = COALESCE(version, 0) + 1
                       WHERE id = ?""",
                    (int(time.time() * 1000), conversation_id),
                )
                await write_deletion_audit(
                    conn,
                    action="soft_delete",
                    object_type="message",
                    object_id=str(msg_pk or message_id),
                    user_id=int(user_id) if user_id is not None else None,
                    username=username,
                    character_id=character_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    operator=f"user:{username}",
                    reason=reason,
                    source="app_api",
                    details={"endpoint": "/api/messages/hide"},
                )
                await conn.commit()

        return {
            "status": "ok",
            "success": True,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "hidden": True,
            "already_hidden": already_hidden,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "success": False, "message": str(e)})


@router.get("/api/conversation/messages")
async def get_conversation_messages_paged(
    username: str,
    character_id: str,
    conversation_id: Optional[str] = None,
    before_seq: Optional[int] = None,
    after_seq: Optional[int] = None,
    sender: str = "all",
    date_from: Optional[int] = None,
    date_to: Optional[int] = None,
    limit: int = 50,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """按 sequence_number 分页加载消息（懒加载 / 历史滚动）。

    - 若不提供 conversation_id，自动使用该角色最新的未隐藏对话。
    - before_seq: 加载 sequence_number < before_seq 的消息；不提供则返回最新一批。
    - after_seq: 加载 sequence_number > after_seq 的新消息，用于弱网恢复后的增量补拉。
    - sender: all / user / character（映射到 role=user / role=assistant）。
    - date_from / date_to: 毫秒时间戳过滤。
    - 返回结果按 sequence_number ASC 排序，has_more 表示是否还有更早消息。
    """
    import aiosqlite

    auth_user = await auth_token_verify((x_chat_auth or "").strip())
    if not auth_user:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})

    limit = max(1, min(limit, 100))
    if before_seq is not None and after_seq is not None:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "before_seq and after_seq cannot be used together"},
        )

    db = get_database()
    await db.init()

    try:
        async with aiosqlite.connect(db.db_path) as conn:
            # 查用户 ID
            async with conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"status": "error", "message": "user_not_found"})
            user_id = row[0]

            # 若未指定对话，取该角色最新未隐藏对话
            if not conversation_id:
                async with conn.execute(
                    """SELECT id FROM conversations
                       WHERE user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0
                       ORDER BY timestamp DESC
                       LIMIT 1""",
                    (user_id, character_id),
                ) as cur:
                    conv_row = await cur.fetchone()
                if not conv_row:
                    return {"messages": [], "has_more": False, "min_seq": None}
                conversation_id = conv_row[0]
            else:
                async with conn.execute(
                    """SELECT id FROM conversations
                       WHERE id = ? AND user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0
                       LIMIT 1""",
                    (conversation_id, user_id, character_id),
                ) as cur:
                    conv_row = await cur.fetchone()
                if not conv_row:
                    return {"messages": [], "has_more": False, "min_seq": None, "max_seq": None, "conversation_id": conversation_id}

            # 构建查询（只取未隐藏、未删除的消息）
            base_where = (
                "conversation_id = ? AND COALESCE(is_hidden, 0) = 0 AND deleted_at IS NULL"
            )
            params_base: list = [conversation_id]

            if sender == "user":
                base_where += " AND role = ?"
                params_base.append("user")
            elif sender == "character":
                base_where += " AND role = ?"
                params_base.append("assistant")
            if date_from is not None:
                base_where += " AND timestamp >= ?"
                params_base.append(date_from)
            if date_to is not None:
                base_where += " AND timestamp <= ?"
                params_base.append(date_to)

            if after_seq is not None:
                seq_filter = f" AND sequence_number > ?"
                params_query = params_base + [after_seq]
                order_sql = "ORDER BY sequence_number ASC"
            elif before_seq is not None:
                seq_filter = f" AND sequence_number < ?"
                params_query = params_base + [before_seq]
                order_sql = "ORDER BY sequence_number DESC"
            else:
                seq_filter = ""
                params_query = params_base[:]
                order_sql = "ORDER BY sequence_number DESC"

            # 取 limit+1 条以判断 has_more（是否还有更多）
            query = f"""
                SELECT id, conversation_id, role, content, image_url,
                       timestamp, message_id, sequence_number, quoted_message_json,
                       speaker_character_id, speaker_name, speaker_avatar
                FROM messages
                WHERE {base_where}{seq_filter}
                {order_sql}
                LIMIT ?
            """
            async with conn.execute(query, params_query + [limit + 1]) as cur:
                rows = await cur.fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]
        # 按 sequence_number ASC 返回给客户端
        rows.sort(key=lambda r: (r[7] if r[7] is not None else 0))

        messages = []
        for r in rows:
            item = {
                "id": r[0],
                "conversation_id": r[1],
                "role": r[2],
                "content": r[3],
                "image_url": r[4],
                "timestamp": r[5],
                "message_id": r[6],
                "sequence_number": r[7],
            }
            if r[8]:
                try:
                    item["quoted_message"] = json.loads(r[8])
                except Exception:
                    pass
            if r[9]:
                item["speaker_character_id"] = r[9]
            if r[10]:
                item["speaker_name"] = r[10]
            if r[11]:
                item["speaker_avatar"] = r[11]
            messages.append(item)
        if messages:
            async with aiosqlite.connect(db.db_path) as conn:
                attachments_by_mid = await load_attachments_for_messages(
                    conn,
                    conversation_id,
                    [str(m.get("message_id") or "") for m in messages],
                )
                voice_states_by_mid = await load_voice_states_for_messages(
                    conn,
                    conversation_id,
                    [str(m.get("message_id") or "") for m in messages],
                )
            for item in messages:
                atts = attachments_by_mid.get(str(item.get("message_id") or ""))
                if atts:
                    item["attachments"] = atts
                attach_voice_state(item, voice_states_by_mid.get(str(item.get("message_id") or "")))
        min_seq = rows[0][7] if rows else None
        max_seq = rows[-1][7] if rows else None

        return {
            "messages": messages,
            "has_more": has_more,
            "min_seq": min_seq,
            "max_seq": max_seq,
            "conversation_id": conversation_id,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.get("/api/messages/count")
async def count_visible_messages(
    username: str,
    character_id: str,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """统计某角色普通对话模式中可见的消息气泡数量。"""
    import aiosqlite

    auth_user = await auth_token_verify((x_chat_auth or "").strip())
    if not auth_user:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})

    db = get_database()
    await db.init()

    try:
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"status": "error", "message": "user_not_found"})
            user_id = row[0]

            async with conn.execute(
                """
                SELECT COUNT(*)
                  FROM messages m
                  JOIN conversations c ON m.conversation_id = c.id
                 WHERE c.user_id = ?
                   AND c.character_id = ?
                   AND COALESCE(c.is_hidden, 0) = 0
                   AND COALESCE(m.is_hidden, 0) = 0
                   AND m.deleted_at IS NULL
                   AND m.role IN ('user', 'assistant')
                """,
                (user_id, character_id),
            ) as cur:
                count_row = await cur.fetchone()
            total = int(count_row[0] if count_row else 0)
        return {"status": "ok", "total": total}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# 消息搜索接口
# ---------------------------------------------------------------------------

@router.get("/api/messages/search")
async def search_messages(
    username: str,
    character_id: str,
    query: str,
    sender: str = "all",
    date_from: Optional[int] = None,
    date_to: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """在用户与某角色的对话消息中全文搜索（SQLite LIKE）。

    - sender: all / user / character（映射到 role=user / role=assistant）
    - date_from / date_to: 毫秒时间戳过滤
    - 返回 results、total、has_more
    """
    import aiosqlite

    auth_user = await auth_token_verify((x_chat_auth or "").strip())
    if not auth_user:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})

    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    query_str = (query or "").strip()
    if not query_str:
        return JSONResponse(status_code=400, content={"status": "error", "message": "query is required"})

    # sender → role 映射
    role_filter: Optional[str] = None
    if sender == "user":
        role_filter = "user"
    elif sender == "character":
        role_filter = "assistant"

    db = get_database()
    await db.init()

    try:
        async with aiosqlite.connect(db.db_path) as conn:
            # 查用户 ID
            async with conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"status": "error", "message": "user_not_found"})
            user_id = row[0]

            q = f"%{query_str}%"
            sticker_match_sql = """
                EXISTS (
                    SELECT 1
                    FROM message_attachments ma
                    LEFT JOIN media_assets pa ON pa.id = ma.asset_id
                    LEFT JOIN user_sticker_assets ua ON ua.id = ma.user_sticker_id
                    WHERE ma.conversation_id = m.conversation_id
                      AND ma.message_id = m.message_id
                      AND (
                          ma.name LIKE ?
                          OR ma.metadata_json LIKE ?
                          OR pa.name LIKE ?
                          OR pa.intro LIKE ?
                          OR pa.detail LIKE ?
                          OR pa.image_text LIKE ?
                          OR pa.custom_tags LIKE ?
                          OR ua.name LIKE ?
                          OR ua.intro LIKE ?
                          OR ua.detail LIKE ?
                          OR ua.image_text LIKE ?
                          OR ua.custom_tags LIKE ?
                      )
                )
            """

            # 构建过滤条件
            filters = [
                "c.user_id = ?",
                "c.character_id = ?",
                "COALESCE(c.is_hidden, 0) = 0",
                "COALESCE(m.is_hidden, 0) = 0",
                "m.deleted_at IS NULL",
                f"""(m.content LIKE ?
                    OR {sticker_match_sql}
                    OR EXISTS (
                        SELECT 1
                        FROM message_voice_states mvs
                        WHERE mvs.conversation_id = m.conversation_id
                          AND mvs.message_id = m.message_id
                          AND (
                              mvs.tts_text LIKE ?
                              OR mvs.transcript LIKE ?
                              OR mvs.text_fragments_json LIKE ?
                          )
                    ))""",
            ]
            params: list = [user_id, character_id, q, *([q] * 12), q, q, q]

            if role_filter:
                filters.append("m.role = ?")
                params.append(role_filter)
            if date_from is not None:
                filters.append("m.timestamp >= ?")
                params.append(date_from)
            if date_to is not None:
                filters.append("m.timestamp <= ?")
                params.append(date_to)

            where_sql = " AND ".join(filters)

            join_sql = (
                "FROM messages m "
                "JOIN conversations c ON m.conversation_id = c.id "
                f"WHERE {where_sql}"
            )

            # 总计数
            async with conn.execute(f"SELECT COUNT(*) {join_sql}", params) as cur:
                count_row = await cur.fetchone()
            total = count_row[0] if count_row else 0

            # 结果集
            data_query = f"""
                SELECT m.message_id, m.sequence_number, m.conversation_id,
                       m.role, m.content, m.timestamp
                {join_sql}
                ORDER BY m.timestamp DESC, m.sequence_number DESC
                LIMIT ? OFFSET ?
            """
            async with conn.execute(data_query, params + [limit, offset]) as cur:
                rows = await cur.fetchall()

            attachments_by_conv_mid: dict[tuple[str, str], list[dict]] = {}
            message_ids_by_conv: dict[str, list[str]] = {}
            for r in rows:
                conv_id = str(r[2] or "")
                msg_id = str(r[0] or "")
                if conv_id and msg_id:
                    message_ids_by_conv.setdefault(conv_id, []).append(msg_id)
            for conv_id, mids in message_ids_by_conv.items():
                by_mid = await load_attachments_for_messages(conn, conv_id, mids)
                for mid, atts in by_mid.items():
                    await _enrich_search_attachment_metadata(conn, atts)
                    attachments_by_conv_mid[(conv_id, mid)] = atts

        results = []
        for r in rows:
            conv_id = str(r[2] or "")
            msg_id = str(r[0] or "")
            results.append(
                {
                    "message_id": r[0],
                    "sequence_number": r[1],
                    "conversation_id": r[2],
                    "role": r[3],
                    "content": r[4],
                    "timestamp": r[5],
                    "attachments": attachments_by_conv_mid.get((conv_id, msg_id), []),
                }
            )

        return {
            "results": results,
            "total": total,
            "has_more": (offset + len(results)) < total,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
