"""
管理后台 — 对话管理 API

🗄️ [2026-02-06] 全面迁移到数据库：
   - 对话数据全部从数据库读取
"""
import html
import json
import re

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from typing import Optional
from ...config import logger

# 🗄️ [数据库] 导入数据库访问层
from ...db import get_database
from ...db.deletion_audit import write_deletion_audit

router = APIRouter()

MODE_LABELS = {
    "normal": "普通聊天",
    "galgame": "游戏模式",
    "galgame_lock": "锁分模式",
}


def _mode_label(mode: str) -> str:
    return MODE_LABELS.get(str(mode or "").strip(), str(mode or "").strip() or "未知模式")


def _synthetic_galgame_conversation_id(mode: str, user_id: int, character_id: str) -> str:
    return f"{mode}:{int(user_id)}:{character_id}"


def _parse_synthetic_galgame_conversation_id(conversation_id: str) -> Optional[tuple[str, int, str]]:
    raw = str(conversation_id or "").strip()
    if not raw:
        return None
    parts = raw.split(":", 2)
    if len(parts) != 3:
        return None
    mode, user_id_raw, character_id = parts
    if mode not in ("galgame", "galgame_lock"):
        return None
    try:
        user_id = int(user_id_raw)
    except Exception:
        return None
    character_id = character_id.strip()
    if not character_id:
        return None
    return mode, user_id, character_id


def _json_loads_maybe(value):
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return None


def _strip_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _galgame_message_preview(content: str, raw_content: str = "") -> str:
    source = (raw_content or "").strip() or (content or "").strip()
    parsed = _json_loads_maybe(source)
    if isinstance(parsed, dict):
        root = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
        scene = root.get("scene") if isinstance(root.get("scene"), dict) else {}
        candidates = [
            scene.get("response") if isinstance(scene, dict) else "",
            scene.get("env") if isinstance(scene, dict) else "",
            scene.get("thoughts") if isinstance(scene, dict) else "",
            root.get("text"),
        ]
        for item in candidates:
            text = str(item or "").strip()
            if text:
                return text[:50] + "..." if len(text) > 50 else text
    text = _strip_html(content or raw_content or "")
    return text[:50] + "..." if len(text) > 50 else text


def _admin_sort_time(value) -> float:
    if value is None or value == "":
        return 0.0
    try:
        numeric = float(value)
        if numeric > 0:
            return numeric if numeric > 1e12 else numeric * 1000
    except Exception:
        pass
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        normalized = text.replace(" ", "T").replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000
    except Exception:
        return 0.0


def _galgame_tables(mode: str) -> tuple[str, str]:
    if mode == "galgame":
        return "galgame_data", "galgame_messages"
    if mode == "galgame_lock":
        return "galgame_lock_data", "galgame_lock_messages"
    raise HTTPException(status_code=404, detail="Conversation not found")


def _json_list_maybe(value) -> list:
    parsed = _json_loads_maybe(value)
    return parsed if isinstance(parsed, list) else []


def _not_blank(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in ("null", "none") else text


async def _get_admin_galgame_conversation_detail(
    conn,
    mode: str,
    user_id: int,
    character_id: str,
    include_deleted: bool = False,
    limit: Optional[int] = None,
    offset: int = 0,
    from_latest: bool = False,
):
    data_table, messages_table = _galgame_tables(mode)
    synthetic_id = _synthetic_galgame_conversation_id(mode, user_id, character_id)
    lock_columns = (
        "g.char_vitals, g.char_mood, g.organ_fill, g.character_gender"
        if mode == "galgame_lock"
        else "NULL as char_vitals, NULL as char_mood, NULL as organ_fill, NULL as character_gender"
    )

    async with conn.execute(
        f"""
        SELECT g.character_id, g.score, g.status, g.updated_at, g.last_active_at, g.active_session_id,
               g.relationship_stage, g.mood, g.memory_tags, g.event_flags, g.score_delta_reason,
               {lock_columns},
               u.username,
               COALESCE(own_ch.name, any_ch.name) as char_name,
               COALESCE(own_ch.avatar, any_ch.avatar) as char_avatar
        FROM {data_table} g
        JOIN users u ON g.user_id = u.id
        LEFT JOIN characters own_ch ON g.character_id = own_ch.id AND g.user_id = own_ch.user_id
        LEFT JOIN characters any_ch ON g.character_id = any_ch.id
        WHERE g.user_id = ? AND g.character_id = ?
        """,
        (user_id, character_id),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")

    (
        char_id,
        score,
        status,
        updated_at,
        last_active_at,
        active_session_id,
        relationship_stage,
        mood,
        memory_tags,
        event_flags,
        score_delta_reason,
        char_vitals,
        char_mood,
        organ_fill,
        character_gender,
        username,
        char_name,
        char_avatar,
    ) = row

    deleted_clause = "" if include_deleted else "AND deleted_at IS NULL AND COALESCE(is_hidden, 0) = 0"
    session_clause = "AND COALESCE(session_id, '') = COALESCE(?, '')"
    base_params = (user_id, character_id, active_session_id)
    async with conn.execute(
        f"""SELECT COUNT(*)
            FROM {messages_table}
            WHERE user_id = ? AND character_id = ?
            {session_clause}
            {deleted_clause}""",
        base_params,
    ) as count_cursor:
        count_row = await count_cursor.fetchone()
        message_total = int(count_row[0] or 0) if count_row else 0

    page_limit: Optional[int] = None
    page_offset = max(0, int(offset or 0))
    if limit is not None:
        page_limit = max(1, min(500, int(limit or 100)))
        if from_latest:
            page_offset = max(0, message_total - page_limit)
        else:
            page_offset = min(page_offset, message_total)

    paging_sql = ""
    paging_params: tuple = ()
    if page_limit is not None:
        paging_sql = "LIMIT ? OFFSET ?"
        paging_params = (page_limit, page_offset)

    messages = []
    async with conn.execute(
        f"""SELECT role, content, raw_content, scene_metadata, image_url, timestamp, message_id,
                  deleted_at, delete_reason, COALESCE(is_hidden, 0), sequence_number,
                  previous_message_id, suggestions, suggestions_status, client_id,
                  generation_duration_ms, galgame_options
           FROM {messages_table}
           WHERE user_id = ? AND character_id = ?
           {session_clause}
           {deleted_clause}
           ORDER BY COALESCE(sequence_number, 0) ASC, COALESCE(timestamp, 0) ASC, rowid ASC
           {paging_sql}""",
        (*base_params, *paging_params),
    ) as msg_cursor:
        async for msg_row in msg_cursor:
            (
                role,
                content,
                raw_content,
                scene_metadata,
                image_url,
                msg_ts,
                msg_id,
                deleted_at,
                delete_reason,
                is_hidden,
                seq,
                prev_id,
                suggestions,
                suggestions_status,
                client_id,
                generation_duration_ms,
                galgame_options,
            ) = msg_row
            effective_raw = raw_content or (content if str(content or "").strip().startswith("{") else "")
            msg = {
                "role": role,
                "content": content,
                "rawContent": effective_raw or "",
                "raw_content": effective_raw or "",
                "scene_metadata": _json_loads_maybe(scene_metadata) or scene_metadata,
                "timestamp": msg_ts,
                "message_id": msg_id,
                "sequence_number": seq,
                "previous_message_id": prev_id,
                "is_deleted": bool(deleted_at),
                "deleted_at": deleted_at,
                "delete_reason": delete_reason,
                "is_hidden": bool(is_hidden),
                "suggestions": _json_list_maybe(suggestions),
                "suggestions_status": suggestions_status,
                "client_id": client_id,
                "generation_duration_ms": generation_duration_ms,
                "galgameOptions": _json_list_maybe(galgame_options),
                "galgame_options": _json_list_maybe(galgame_options),
            }
            if image_url:
                msg["image_url"] = image_url
            messages.append(msg)

    first_ts = messages[0]["timestamp"] if messages else None
    last_ts = messages[-1]["timestamp"] if messages else None
    return {
        "id": synthetic_id,
        "mode": mode,
        "mode_label": _mode_label(mode),
        "user": username,
        "character": char_name or char_id or "Unknown Character",
        "character_avatar": char_avatar or "",
        "character_id": char_id,
        "title": "锁分对话" if mode == "galgame_lock" else "游戏对话",
        "is_hidden": False,
        "messages": messages,
        "message_total": message_total,
        "message_offset": page_offset,
        "message_limit": page_limit,
        "messages_loaded": len(messages),
        "has_older": page_offset > 0,
        "has_newer": (page_offset + len(messages)) < message_total,
        "timestamp": last_ts or updated_at or last_active_at,
        "created_at": first_ts or updated_at or last_active_at,
        "updated_at": last_ts or updated_at or last_active_at,
        "score": score,
        "game_status": status,
        "active_session_id": active_session_id,
        "relationship_stage": _not_blank(relationship_stage),
        "mood": _not_blank(mood),
        "memory_tags": _json_loads_maybe(memory_tags) or memory_tags,
        "event_flags": _json_loads_maybe(event_flags) or event_flags,
        "score_delta_reason": _not_blank(score_delta_reason),
        "char_vitals": _json_loads_maybe(char_vitals) or char_vitals,
        "char_mood": _json_loads_maybe(char_mood) or char_mood,
        "organ_fill": _json_loads_maybe(organ_fill) or organ_fill,
        "character_gender": _not_blank(character_gender),
    }


@router.get("/deletion-audits")
async def get_deletion_audits(
    username: Optional[str] = None,
    action: Optional[str] = None,
    object_type: Optional[str] = None,
    character_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    operator: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    """管理后台：查询删除/恢复审计日志（支持过滤+分页）。"""
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be in [1, 1000]")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        filters = []
        params = []
        if username:
            filters.append("username = ?")
            params.append(username)
        if action:
            filters.append("action = ?")
            params.append(action)
        if object_type:
            filters.append("object_type = ?")
            params.append(object_type)
        if character_id:
            filters.append("character_id = ?")
            params.append(character_id)
        if conversation_id:
            filters.append("conversation_id = ?")
            params.append(conversation_id)
        if operator:
            filters.append("operator = ?")
            params.append(operator)

        where_sql = ("WHERE " + " AND ".join(filters)) if filters else ""
        query = f"""
            SELECT audit_id, action, object_type, object_id,
                   user_id, username, character_id, conversation_id, message_id,
                   operator, reason, source, details_json, created_at
            FROM deletion_audits
            {where_sql}
            ORDER BY created_at DESC, audit_id DESC
            LIMIT ? OFFSET ?
        """
        count_query = f"SELECT COUNT(*) FROM deletion_audits {where_sql}"

        items = []
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(count_query, tuple(params)) as cur:
                count_row = await cur.fetchone()
                total = count_row[0] if count_row else 0

            async with conn.execute(query, tuple([*params, limit, offset])) as cur:
                async for row in cur:
                    items.append(
                        {
                            "audit_id": row[0],
                            "action": row[1],
                            "object_type": row[2],
                            "object_id": row[3],
                            "user_id": row[4],
                            "username": row[5],
                            "character_id": row[6],
                            "conversation_id": row[7],
                            "message_id": row[8],
                            "operator": row[9],
                            "reason": row[10],
                            "source": row[11],
                            "details_json": row[12],
                            "created_at": row[13],
                        }
                    )
        return {
            "success": True,
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询删除审计日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations")
async def get_admin_conversations():
    """获取对话摘要列表"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        all_convs = []
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute("""
                SELECT c.id, c.character_id, c.title, c.timestamp, c.created_at, c.updated_at, COALESCE(c.is_hidden, 0),
                       u.username,
                       COALESCE(own_ch.name, any_ch.name) as char_name,
                       COALESCE(own_ch.avatar, any_ch.avatar) as char_avatar,
                       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND m.deleted_at IS NULL AND COALESCE(m.is_hidden, 0) = 0) as msg_count
                FROM conversations c
                JOIN users u ON c.user_id = u.id
                LEFT JOIN characters own_ch ON c.character_id = own_ch.id AND c.user_id = own_ch.user_id
                LEFT JOIN characters any_ch ON c.character_id = any_ch.id
                ORDER BY c.updated_at DESC
            """) as cursor:
                async for row in cursor:
                    conv_id, char_id, title, timestamp, created_at, updated_at, is_hidden, username, char_name, char_avatar, msg_count = row

                    # 获取最后一条消息预览
                    last_msg = ""
                    async with conn.execute(
                        "SELECT content FROM messages WHERE conversation_id = ? AND deleted_at IS NULL AND COALESCE(is_hidden, 0) = 0 ORDER BY sequence_number DESC LIMIT 1",
                        (conv_id,),
                    ) as msg_cursor:
                        msg_row = await msg_cursor.fetchone()
                        if msg_row and msg_row[0]:
                            content = msg_row[0]
                            last_msg = content[:50] + "..." if len(content) > 50 else content

                    all_convs.append({
                        "id": conv_id,
                        "mode": "normal",
                        "mode_label": _mode_label("normal"),
                        "user": username,
                        "character": char_name or char_id or "Unknown Character",
                        "character_avatar": char_avatar or "",
                        "character_id": char_id,
                        "title": title or "未命名对话",
                        "is_hidden": bool(is_hidden),
                        "messages": msg_count,
                        "last_message": last_msg,
                        "timestamp": timestamp,
                        "created_at": created_at or timestamp,
                        "updated_at": updated_at or timestamp,
                    })

            for mode, data_table, messages_table in (
                ("galgame", "galgame_data", "galgame_messages"),
                ("galgame_lock", "galgame_lock_data", "galgame_lock_messages"),
            ):
                async with conn.execute(
                    f"""
                    SELECT g.user_id, g.character_id, g.score, g.status, g.updated_at,
                           g.last_active_at, g.active_session_id, u.username,
                           COALESCE(own_ch.name, any_ch.name) as char_name,
                           COALESCE(own_ch.avatar, any_ch.avatar) as char_avatar,
                           (SELECT COUNT(*) FROM {messages_table} m
                              WHERE m.user_id = g.user_id
                                AND m.character_id = g.character_id
                                AND m.deleted_at IS NULL
                                AND COALESCE(m.is_hidden, 0) = 0
                                AND COALESCE(m.session_id, '') = COALESCE(g.active_session_id, '')) as msg_count,
                           (SELECT MIN(m.timestamp) FROM {messages_table} m
                              WHERE m.user_id = g.user_id
                                AND m.character_id = g.character_id
                                AND m.deleted_at IS NULL
                                AND COALESCE(m.is_hidden, 0) = 0
                                AND COALESCE(m.session_id, '') = COALESCE(g.active_session_id, '')) as first_ts,
                           (SELECT m.timestamp FROM {messages_table} m
                              WHERE m.user_id = g.user_id
                                AND m.character_id = g.character_id
                                AND m.deleted_at IS NULL
                                AND COALESCE(m.is_hidden, 0) = 0
                                AND COALESCE(m.session_id, '') = COALESCE(g.active_session_id, '')
                              ORDER BY COALESCE(m.sequence_number, 0) DESC, COALESCE(m.timestamp, 0) DESC, m.rowid DESC
                              LIMIT 1) as last_ts,
                           (SELECT m.content FROM {messages_table} m
                              WHERE m.user_id = g.user_id
                                AND m.character_id = g.character_id
                                AND m.deleted_at IS NULL
                                AND COALESCE(m.is_hidden, 0) = 0
                                AND COALESCE(m.session_id, '') = COALESCE(g.active_session_id, '')
                              ORDER BY COALESCE(m.sequence_number, 0) DESC, COALESCE(m.timestamp, 0) DESC, m.rowid DESC
                              LIMIT 1) as last_content,
                           (SELECT m.raw_content FROM {messages_table} m
                              WHERE m.user_id = g.user_id
                                AND m.character_id = g.character_id
                                AND m.deleted_at IS NULL
                                AND COALESCE(m.is_hidden, 0) = 0
                                AND COALESCE(m.session_id, '') = COALESCE(g.active_session_id, '')
                              ORDER BY COALESCE(m.sequence_number, 0) DESC, COALESCE(m.timestamp, 0) DESC, m.rowid DESC
                              LIMIT 1) as last_raw_content
                    FROM {data_table} g
                    JOIN users u ON g.user_id = u.id
                    LEFT JOIN characters own_ch ON g.character_id = own_ch.id AND g.user_id = own_ch.user_id
                    LEFT JOIN characters any_ch ON g.character_id = any_ch.id
                    ORDER BY COALESCE(last_ts, g.last_active_at, g.updated_at) DESC
                    """
                ) as cursor:
                    async for row in cursor:
                        (
                            user_id,
                            char_id,
                            score,
                            status,
                            updated_at,
                            last_active_at,
                            active_session_id,
                            username,
                            char_name,
                            char_avatar,
                            msg_count,
                            first_ts,
                            last_ts,
                            last_content,
                            last_raw_content,
                        ) = row
                        all_convs.append(
                            {
                                "id": _synthetic_galgame_conversation_id(mode, user_id, char_id),
                                "mode": mode,
                                "mode_label": _mode_label(mode),
                                "user": username,
                                "character": char_name or char_id or "Unknown Character",
                                "character_avatar": char_avatar or "",
                                "character_id": char_id,
                                "title": "锁分对话" if mode == "galgame_lock" else "游戏对话",
                                "is_hidden": False,
                                "messages": msg_count or 0,
                                "last_message": _galgame_message_preview(last_content or "", last_raw_content or ""),
                                "timestamp": last_ts or updated_at or last_active_at,
                                "created_at": first_ts or updated_at or last_active_at,
                                "updated_at": last_ts or updated_at or last_active_at,
                                "score": score,
                                "game_status": status,
                                "active_session_id": active_session_id,
                            }
                        )

        all_convs.sort(key=lambda item: _admin_sort_time(item.get("updated_at") or item.get("timestamp")), reverse=True)
        logger.info(f"📊 [DB] 管理后台加载了 {len(all_convs)} 个对话")
        return all_convs

    except Exception as e:
        logger.error(f"获取对话列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}")
async def get_conversation_detail(
    conversation_id: str,
    include_deleted: bool = False,
    limit: Optional[int] = None,
    offset: int = 0,
    from_latest: bool = False,
):
    """获取对话详细信息"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        async with aiosqlite.connect(db.db_path) as conn:
            synthetic = _parse_synthetic_galgame_conversation_id(conversation_id)
            if synthetic:
                mode, user_id, character_id = synthetic
                return await _get_admin_galgame_conversation_detail(
                    conn,
                    mode,
                    user_id,
                    character_id,
                    include_deleted=include_deleted,
                    limit=limit,
                    offset=offset,
                    from_latest=from_latest,
                )

            # 查找对话
            async with conn.execute("""
                SELECT c.id, c.character_id, c.timestamp,
                       u.username,
                       COALESCE(own_ch.name, any_ch.name) as char_name,
                       COALESCE(own_ch.avatar, any_ch.avatar) as char_avatar
                FROM conversations c
                JOIN users u ON c.user_id = u.id
                LEFT JOIN characters own_ch ON c.character_id = own_ch.id AND c.user_id = own_ch.user_id
                LEFT JOIN characters any_ch ON c.character_id = any_ch.id
                WHERE c.id = ?
            """, (conversation_id,)) as cursor:
                row = await cursor.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Conversation not found")

            conv_id, char_id, timestamp, username, char_name, char_avatar = row

            deleted_clause = "" if include_deleted else "AND deleted_at IS NULL AND COALESCE(is_hidden, 0) = 0"
            async with conn.execute(
                f"""SELECT COUNT(*)
                    FROM messages
                    WHERE conversation_id = ?
                    {deleted_clause}""",
                (conv_id,),
            ) as count_cursor:
                count_row = await count_cursor.fetchone()
                message_total = int(count_row[0] or 0) if count_row else 0

            page_limit: Optional[int] = None
            page_offset = max(0, int(offset or 0))
            if limit is not None:
                page_limit = max(1, min(500, int(limit or 100)))
                if from_latest:
                    page_offset = max(0, message_total - page_limit)
                else:
                    page_offset = min(page_offset, message_total)

            messages = []
            paging_sql = ""
            paging_params: tuple = ()
            if page_limit is not None:
                paging_sql = "LIMIT ? OFFSET ?"
                paging_params = (page_limit, page_offset)
            async with conn.execute(
                f"""SELECT role, content, image_url, timestamp, message_id, deleted_at, delete_reason,
                          COALESCE(is_hidden, 0), hidden_at, hidden_reason,
                          sequence_number, previous_message_id,
                          speaker_character_id, speaker_name, speaker_avatar
                   FROM messages WHERE conversation_id = ?
                   {deleted_clause}
                   ORDER BY sequence_number ASC
                   {paging_sql}""",
                (conv_id, *paging_params),
            ) as msg_cursor:
                async for msg_row in msg_cursor:
                    (
                        role,
                        content,
                        image_url,
                        msg_ts,
                        msg_id,
                        deleted_at,
                        delete_reason,
                        is_hidden,
                        hidden_at,
                        hidden_reason,
                        seq,
                        prev_id,
                        speaker_character_id,
                        speaker_name,
                        speaker_avatar,
                    ) = msg_row
                    msg = {
                        "role": role,
                        "content": content,
                        "timestamp": msg_ts,
                        "message_id": msg_id,
                        "sequence_number": seq,
                        "previous_message_id": prev_id,
                        "is_deleted": bool(deleted_at),
                        "deleted_at": deleted_at,
                        "delete_reason": delete_reason,
                        "is_hidden": bool(is_hidden),
                        "hidden_at": hidden_at,
                        "hidden_reason": hidden_reason,
                    }
                    if speaker_character_id:
                        msg["speaker_character_id"] = speaker_character_id
                    if speaker_name:
                        msg["speaker_name"] = speaker_name
                    if speaker_avatar:
                        msg["speaker_avatar"] = speaker_avatar
                    if image_url:
                        msg["image_url"] = image_url
                    messages.append(msg)

            return {
                "id": conv_id,
                "user": username,
                "character": char_name or char_id or "Unknown Character",
                "character_avatar": char_avatar or "",
                "character_id": char_id,
                "messages": messages,
                "message_total": message_total,
                "message_offset": page_offset,
                "message_limit": page_limit,
                "messages_loaded": len(messages),
                "has_older": page_offset > 0,
                "has_newer": (page_offset + len(messages)) < message_total,
                "timestamp": timestamp,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取对话详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation-recovery")
async def get_conversation_recovery_list(
    username: Optional[str] = None,
    character_id: Optional[str] = None,
    only_hidden: bool = True
):
    """列出可恢复对话（默认仅隐藏对话）。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        filters = []
        params = []
        if username:
            filters.append("u.username = ?")
            params.append(username)
        if character_id:
            filters.append("c.character_id = ?")
            params.append(character_id)
        if only_hidden:
            filters.append("COALESCE(c.is_hidden, 0) = 1")
        where_sql = ("WHERE " + " AND ".join(filters)) if filters else ""

        query = f"""
            SELECT c.id, c.character_id, c.title, c.timestamp, c.updated_at,
                   COALESCE(c.is_hidden, 0), c.hidden_at, c.hidden_reason,
                   u.username, COALESCE(own_ch.name, any_ch.name) as char_name,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND m.deleted_at IS NULL AND COALESCE(m.is_hidden, 0) = 0) as visible_count,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND (m.deleted_at IS NOT NULL OR COALESCE(m.is_hidden, 0) = 1)) as deleted_count,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) as total_count,
                   (SELECT m.role FROM messages m WHERE m.conversation_id = c.id ORDER BY COALESCE(m.sequence_number, 0) DESC, m.timestamp DESC LIMIT 1) as last_role,
                   (SELECT m.content FROM messages m WHERE m.conversation_id = c.id ORDER BY COALESCE(m.sequence_number, 0) DESC, m.timestamp DESC LIMIT 1) as last_content,
                   (SELECT m.timestamp FROM messages m WHERE m.conversation_id = c.id ORDER BY COALESCE(m.sequence_number, 0) DESC, m.timestamp DESC LIMIT 1) as last_message_at,
                   (SELECT m.content FROM messages m WHERE m.conversation_id = c.id AND (m.deleted_at IS NOT NULL OR COALESCE(m.is_hidden, 0) = 1) ORDER BY COALESCE(m.sequence_number, 0) DESC, m.timestamp DESC LIMIT 1) as last_deleted_content
            FROM conversations c
            JOIN users u ON c.user_id = u.id
            LEFT JOIN characters own_ch ON c.character_id = own_ch.id AND c.user_id = own_ch.user_id
            LEFT JOIN characters any_ch ON c.character_id = any_ch.id
            {where_sql}
            ORDER BY COALESCE(c.hidden_at, c.updated_at) DESC
            LIMIT 1000
        """

        rows = []
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(query, tuple(params)) as cursor:
                async for row in cursor:
                    rows.append({
                        "conversation_id": row[0],
                        "character_id": row[1],
                        "title": row[2] or "未命名对话",
                        "timestamp": row[3],
                        "updated_at": row[4],
                        "is_hidden": bool(row[5]),
                        "hidden_at": row[6],
                        "hidden_reason": row[7],
                        "username": row[8],
                        "character_name": row[9] or row[1],
                        "visible_message_count": row[10] or 0,
                        "deleted_message_count": row[11] or 0,
                        "total_message_count": row[12] or 0,
                        "last_role": row[13],
                        "last_message": (row[14][:140] + "...") if row[14] and len(row[14]) > 140 else row[14],
                        "last_message_at": row[15],
                        "last_deleted_message": (row[16][:140] + "...") if row[16] and len(row[16]) > 140 else row[16],
                    })
        return {"success": True, "items": rows}
    except Exception as e:
        logger.error(f"加载可恢复对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversation-recovery/{conversation_id}/restore")
async def restore_conversation(conversation_id: str):
    """恢复被隐藏的对话。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            user_id = None
            username = None
            character_id = None
            async with conn.execute(
                """SELECT c.user_id, u.username, c.character_id
                   FROM conversations c
                   LEFT JOIN users u ON c.user_id = u.id
                   WHERE c.id = ?""",
                (conversation_id,),
            ) as cur:
                meta = await cur.fetchone()
                if meta:
                    user_id, username, character_id = meta
            await conn.execute(
                """UPDATE conversations
                   SET is_hidden = 0, hidden_at = NULL, hidden_reason = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (conversation_id,)
            )
            if meta:
                await write_deletion_audit(
                    conn,
                    action="restore",
                    object_type="conversation",
                    object_id=conversation_id,
                    user_id=user_id,
                    username=username,
                    character_id=character_id,
                    conversation_id=conversation_id,
                    operator="admin:system",
                    reason="admin_restore_conversation",
                    source="admin_api",
                )
            await conn.commit()
        return {"success": True, "message": "对话已恢复"}
    except Exception as e:
        logger.error(f"恢复对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/messages/{message_id}/restore")
async def restore_conversation_message(conversation_id: str, message_id: str):
    """恢复对话中的单条已软删消息。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            user_id = None
            username = None
            character_id = None
            msg_pk = None
            async with conn.execute(
                """SELECT m.id, c.user_id, u.username, c.character_id
                   FROM messages m
                   JOIN conversations c ON m.conversation_id = c.id
                   LEFT JOIN users u ON c.user_id = u.id
                   WHERE m.conversation_id = ? AND m.message_id = ?
                   LIMIT 1""",
                (conversation_id, message_id),
            ) as cur:
                meta = await cur.fetchone()
                if meta:
                    msg_pk, user_id, username, character_id = meta
            await conn.execute(
                """UPDATE messages
                   SET deleted_at = NULL, delete_reason = NULL, is_hidden = 0, hidden_at = NULL, hidden_reason = NULL
                   WHERE conversation_id = ? AND message_id = ?""",
                (conversation_id, message_id)
            )
            await conn.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id,)
            )
            if meta:
                await write_deletion_audit(
                    conn,
                    action="restore",
                    object_type="message",
                    object_id=msg_pk or message_id,
                    user_id=user_id,
                    username=username,
                    character_id=character_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    operator="admin:system",
                    reason="admin_restore_message",
                    source="admin_api",
                )
            await conn.commit()
        return {"success": True, "message": "消息已恢复"}
    except Exception as e:
        logger.error(f"恢复对话消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/messages/{message_id}/soft-delete")
async def soft_delete_conversation_message(conversation_id: str, message_id: str):
    """管理后台：软隐藏对话中的单条消息，保留恢复能力与审计记录。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            user_id = None
            username = None
            character_id = None
            msg_pk = None
            is_hidden = 0
            deleted_at = None
            async with conn.execute(
                """SELECT m.id, c.user_id, u.username, c.character_id,
                          COALESCE(m.is_hidden, 0), m.deleted_at
                   FROM messages m
                   JOIN conversations c ON m.conversation_id = c.id
                   LEFT JOIN users u ON c.user_id = u.id
                   WHERE m.conversation_id = ? AND m.message_id = ?
                   LIMIT 1""",
                (conversation_id, message_id),
            ) as cur:
                meta = await cur.fetchone()
                if meta:
                    msg_pk, user_id, username, character_id, is_hidden, deleted_at = meta
            if not meta:
                raise HTTPException(status_code=404, detail="Message not found")

            already_hidden = bool(is_hidden) or deleted_at is not None
            if not already_hidden:
                await conn.execute(
                    """UPDATE messages
                       SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                           delete_reason = COALESCE(delete_reason, 'admin_soft_delete_message'),
                           is_hidden = 1,
                           hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                           hidden_reason = COALESCE(hidden_reason, 'admin_soft_delete_message')
                       WHERE conversation_id = ?
                         AND message_id = ?
                         AND deleted_at IS NULL
                         AND COALESCE(is_hidden, 0) = 0""",
                    (conversation_id, message_id),
                )
                await conn.execute(
                    "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (conversation_id,),
                )

            await write_deletion_audit(
                conn,
                action="soft_delete",
                object_type="message",
                object_id=str(msg_pk or message_id),
                user_id=user_id,
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
                message_id=message_id,
                operator="admin:system",
                reason="admin_soft_delete_message",
                source="admin_api",
                details={"already_hidden": already_hidden},
            )
            await conn.commit()
        return {
            "success": True,
            "message": "消息已软删除" if not already_hidden else "消息已处于隐藏状态",
            "already_hidden": already_hidden,
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"软删除对话消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/reset")
async def reset_admin_conversation(conversation_id: str):
    """管理后台：按当前模式重置一条用户-角色对话状态。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        mode = "normal"
        user_id = None
        username = None
        character_id = None
        synthetic = _parse_synthetic_galgame_conversation_id(conversation_id)

        async with aiosqlite.connect(db.db_path) as conn:
            if synthetic:
                mode, user_id, character_id = synthetic
                data_table, _ = _galgame_tables(mode)
                async with conn.execute(
                    f"""SELECT g.user_id, u.username, g.character_id
                        FROM {data_table} g
                        JOIN users u ON g.user_id = u.id
                        WHERE g.user_id = ? AND g.character_id = ?
                        LIMIT 1""",
                    (user_id, character_id),
                ) as cur:
                    meta = await cur.fetchone()
            else:
                async with conn.execute(
                    """SELECT c.user_id, u.username, c.character_id
                       FROM conversations c
                       JOIN users u ON c.user_id = u.id
                       WHERE c.id = ?
                       LIMIT 1""",
                    (conversation_id,),
                ) as cur:
                    meta = await cur.fetchone()

            if not meta:
                raise HTTPException(status_code=404, detail="Conversation not found")
            user_id, username, character_id = meta

        if mode == "normal":
            from ..characters import reset_character_chat

            result = await reset_character_chat(
                {"username": username, "character_id": character_id},
                x_client_id="admin",
            )
            message = "普通聊天已重置"
        else:
            from ...db import GalgameDAO
            from ...websocket import manager

            galgame_dao = GalgameDAO(db)
            ok = await galgame_dao.reset_galgame_data(username, character_id, game_type=mode)
            if not ok:
                raise HTTPException(status_code=500, detail="重置失败")
            await manager.broadcast_sync(
                username,
                "galgame_reset",
                source="admin",
                character_id=character_id,
                game_type=mode,
            )
            result = {"success": True, "status": "success", "game_type": mode}
            message = "锁分模式已重置" if mode == "galgame_lock" else "游戏模式已重置"

        async with aiosqlite.connect(db.db_path) as conn:
            await write_deletion_audit(
                conn,
                action="reset",
                object_type="conversation",
                object_id=conversation_id,
                user_id=user_id,
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
                operator="admin:system",
                reason=f"admin_reset_{mode}",
                source="admin_api",
                details={"mode": mode, "result": result},
            )
            await conn.commit()

        logger.info(
            f"🔄 [Admin-Reset] 重置对话: mode={mode}, user={username}, char={str(character_id)[:12]}..."
        )
        return {
            "success": True,
            "message": message,
            "mode": mode,
            "mode_label": _mode_label(mode),
            "conversation_id": conversation_id,
            "character_id": character_id,
            "result": result,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}/hard")
async def hard_delete_conversation(conversation_id: str):
    """
    管理后台专用：物理删除整个对话及其关联消息（不可恢复）。
    注意：用户侧删除仅允许软删除。
    """
    try:
        import aiosqlite
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            user_id = None
            username = None
            character_id = None
            async with conn.execute(
                """SELECT c.user_id, u.username, c.character_id
                   FROM conversations c
                   LEFT JOIN users u ON c.user_id = u.id
                   WHERE c.id = ?""",
                (conversation_id,),
            ) as cur:
                meta = await cur.fetchone()
                if meta:
                    user_id, username, character_id = meta

            # 先统计，便于审计日志
            async with conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ) as cur:
                row = await cur.fetchone()
                msg_count = row[0] if row else 0

            await conn.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            if meta:
                await write_deletion_audit(
                    conn,
                    action="hard_delete",
                    object_type="conversation",
                    object_id=conversation_id,
                    user_id=user_id,
                    username=username,
                    character_id=character_id,
                    conversation_id=conversation_id,
                    operator="admin:system",
                    reason="admin_hard_delete_conversation",
                    source="admin_api",
                    details={"deleted_messages": msg_count},
                )
            await conn.commit()

        logger.warning(f"🧨 [Admin-HardDelete] 物理删除对话: conv={conversation_id[:12]}..., messages={msg_count}")
        return {"success": True, "message": "对话已物理删除", "deleted_messages": msg_count}
    except Exception as e:
        logger.error(f"物理删除对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}/messages/{message_id}/hard")
async def hard_delete_conversation_message(conversation_id: str, message_id: str):
    """
    管理后台专用：物理删除单条消息（不可恢复）。
    注意：用户侧删除仅允许软删除。
    """
    try:
        import aiosqlite
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            user_id = None
            username = None
            character_id = None
            msg_pk = None
            async with conn.execute(
                """SELECT m.id, c.user_id, u.username, c.character_id
                   FROM messages m
                   JOIN conversations c ON m.conversation_id = c.id
                   LEFT JOIN users u ON c.user_id = u.id
                   WHERE m.conversation_id = ? AND m.message_id = ?
                   LIMIT 1""",
                (conversation_id, message_id),
            ) as cur:
                meta = await cur.fetchone()
                if meta:
                    msg_pk, user_id, username, character_id = meta
            await conn.execute(
                "DELETE FROM messages WHERE conversation_id = ? AND message_id = ?",
                (conversation_id, message_id),
            )
            await conn.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id,),
            )
            if meta:
                await write_deletion_audit(
                    conn,
                    action="hard_delete",
                    object_type="message",
                    object_id=msg_pk or message_id,
                    user_id=user_id,
                    username=username,
                    character_id=character_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    operator="admin:system",
                    reason="admin_hard_delete_message",
                    source="admin_api",
                )
            await conn.commit()

        logger.warning(
            f"🧨 [Admin-HardDelete] 物理删除消息: conv={conversation_id[:12]}..., msg={message_id[:12]}..."
        )
        return {"success": True, "message": "消息已物理删除"}
    except Exception as e:
        logger.error(f"物理删除消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retention/purge-soft-deleted")
async def purge_soft_deleted(
    days: int = 90,
    limit: int = 1000,
    dry_run: bool = True,
):
    """
    管理后台专用：按保留期批量物理清理软删除数据。
    - messages: deleted_at 超过 days 且其会话未隐藏
    - conversations: is_hidden=1 且 hidden_at 超过 days（级联删除消息/快照）
    """
    if days < 1:
        raise HTTPException(status_code=400, detail="days must be >= 1")
    if limit < 1 or limit > 5000:
        raise HTTPException(status_code=400, detail="limit must be in [1, 5000]")
    try:
        import aiosqlite
        db = get_database()
        await db.init()
        cutoff = f"-{days} days"
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")

            message_candidates = []
            async with conn.execute(
                """SELECT m.id, m.message_id, m.conversation_id, c.user_id, u.username, c.character_id
                   FROM messages m
                   JOIN conversations c ON m.conversation_id = c.id
                   LEFT JOIN users u ON c.user_id = u.id
                   WHERE m.deleted_at IS NOT NULL
                     AND datetime(m.deleted_at) <= datetime('now', ?)
                     AND COALESCE(c.is_hidden, 0) = 0
                   ORDER BY m.deleted_at ASC
                   LIMIT ?""",
                (cutoff, limit),
            ) as cur:
                async for row in cur:
                    message_candidates.append(row)

            conversation_candidates = []
            async with conn.execute(
                """SELECT c.id, c.user_id, u.username, c.character_id
                   FROM conversations c
                   LEFT JOIN users u ON c.user_id = u.id
                   WHERE COALESCE(c.is_hidden, 0) = 1
                     AND c.hidden_at IS NOT NULL
                     AND datetime(c.hidden_at) <= datetime('now', ?)
                   ORDER BY c.hidden_at ASC
                   LIMIT ?""",
                (cutoff, limit),
            ) as cur:
                async for row in cur:
                    conversation_candidates.append(row)

            if dry_run:
                return {
                    "success": True,
                    "dry_run": True,
                    "days": days,
                    "candidate_messages": len(message_candidates),
                    "candidate_conversations": len(conversation_candidates),
                }

            await conn.execute("BEGIN IMMEDIATE")
            deleted_messages = 0
            deleted_conversations = 0
            try:
                for msg_id_pk, msg_id, conv_id, user_id, username, char_id in message_candidates:
                    await conn.execute("DELETE FROM messages WHERE id = ?", (msg_id_pk,))
                    await write_deletion_audit(
                        conn,
                        action="hard_delete",
                        object_type="message",
                        object_id=msg_id_pk,
                        user_id=user_id,
                        username=username,
                        character_id=char_id,
                        conversation_id=conv_id,
                        message_id=msg_id,
                        operator="admin:retention",
                        reason=f"retention_{days}d",
                        source="retention_job",
                    )
                    deleted_messages += 1

                for conv_id, user_id, username, char_id in conversation_candidates:
                    await conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
                    await write_deletion_audit(
                        conn,
                        action="hard_delete",
                        object_type="conversation",
                        object_id=conv_id,
                        user_id=user_id,
                        username=username,
                        character_id=char_id,
                        conversation_id=conv_id,
                        operator="admin:retention",
                        reason=f"retention_{days}d",
                        source="retention_job",
                    )
                    deleted_conversations += 1

                await write_deletion_audit(
                    conn,
                    action="hard_delete",
                    object_type="batch_job",
                    object_id=f"retention_{days}d",
                    operator="admin:retention",
                    reason="retention_purge",
                    source="retention_job",
                    details={
                        "days": days,
                        "deleted_messages": deleted_messages,
                        "deleted_conversations": deleted_conversations,
                        "limit": limit,
                    },
                )
                await conn.execute("COMMIT")
            except Exception:
                await conn.execute("ROLLBACK")
                raise

            return {
                "success": True,
                "dry_run": False,
                "days": days,
                "deleted_messages": deleted_messages,
                "deleted_conversations": deleted_conversations,
            }
    except Exception as e:
        logger.error(f"批量清理软删除数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 对话合并迁移
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel


class _MergeMigrateRequest(_BaseModel):
    username: str
    character_id: Optional[str] = None


@router.post("/migrate_merge_conversations")
async def migrate_merge_conversations(body: _MergeMigrateRequest):
    """将用户某角色（或所有角色）的多个未隐藏对话合并为单个对话。

    - 若 character_id 为空，则处理该用户所有角色。
    - 每个角色仅有 1 条对话时跳过。
    - 合并后旧对话标记为 is_hidden=1，消息重新编排 sequence_number（从 1 开始）。
    """
    import aiosqlite
    import uuid as _uuid
    import time as _time

    username = (body.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")

    db = get_database()
    await db.init()

    try:
        results = []
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute("PRAGMA busy_timeout = 5000")

            # 查用户 ID
            async with conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"User '{username}' not found")
            user_id = row[0]

            # 确定要处理的角色列表
            if body.character_id:
                char_ids = [body.character_id]
            else:
                async with conn.execute(
                    """SELECT DISTINCT character_id FROM conversations
                       WHERE user_id = ? AND COALESCE(is_hidden, 0) = 0""",
                    (user_id,),
                ) as cur:
                    char_ids = [r[0] for r in await cur.fetchall()]

            for char_id in char_ids:
                # 查该用户+角色的所有未隐藏对话，按时间升序
                async with conn.execute(
                    """SELECT id, title, timestamp FROM conversations
                       WHERE user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0
                       ORDER BY timestamp ASC""",
                    (user_id, char_id),
                ) as cur:
                    convs = await cur.fetchall()

                if len(convs) <= 1:
                    results.append({
                        "character_id": char_id,
                        "status": "skipped",
                        "reason": "only_one_or_zero_conversations",
                        "count": len(convs),
                    })
                    continue

                # 取所有对话的消息，按时间、序号排序
                conv_ids = [c[0] for c in convs]
                placeholders = ",".join("?" * len(conv_ids))
                async with conn.execute(
                    f"""SELECT id FROM messages
                        WHERE conversation_id IN ({placeholders})
                        ORDER BY timestamp ASC, COALESCE(sequence_number, 0) ASC, id ASC""",
                    conv_ids,
                ) as cur:
                    all_msg_ids = [r[0] for r in await cur.fetchall()]

                # 建新合并对话（取最新对话标题）
                new_conv_id = str(_uuid.uuid4())
                latest_conv = convs[-1]
                title = (latest_conv[1] or "").strip() or "合并对话"
                new_timestamp = int(_time.time() * 1000)

                await conn.execute(
                    """INSERT INTO conversations
                           (id, character_id, user_id, title, timestamp, version,
                            is_hidden, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    (new_conv_id, char_id, user_id, title, new_timestamp),
                )

                # 更新消息：新 conversation_id + 重新分配连续 sequence_number
                for seq, msg_id in enumerate(all_msg_ids, start=1):
                    await conn.execute(
                        "UPDATE messages SET conversation_id = ?, sequence_number = ? WHERE id = ?",
                        (new_conv_id, seq, msg_id),
                    )

                # 旧对话标记为隐藏
                for conv_id, _, _ in convs:
                    await conn.execute(
                        """UPDATE conversations
                           SET is_hidden = 1,
                               hidden_at = CURRENT_TIMESTAMP,
                               hidden_reason = 'merged_by_admin',
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (conv_id,),
                    )

                await conn.commit()

                results.append({
                    "character_id": char_id,
                    "status": "merged",
                    "merged_conversations": len(convs),
                    "total_messages": len(all_msg_ids),
                    "new_conversation_id": new_conv_id,
                })
                logger.info(
                    f"[merge_conversations] user={username} char={char_id} "
                    f"merged {len(convs)} convs → {new_conv_id} ({len(all_msg_ids)} msgs)"
                )

        return {
            "success": True,
            "username": username,
            "processed_characters": len(results),
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"合并对话迁移失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
