"""
对话数据访问对象（DAO）
处理对话和消息的数据库操作
"""
import aiosqlite
import os
import json
import time
import uuid
import hashlib
import base64 as b64_mod
import re
from typing import List, Dict, Optional
from datetime import datetime
from .database import Database, get_database
from .deletion_audit import write_deletion_audit
from .message_attachments import load_attachments_for_messages, replace_message_attachments
from .message_voice_states import attach_voice_state, load_voice_states_for_messages
from ..config import logger
from ..chat_image_transfer import store_chat_image_transfer
from ..utils import compress_image_to_jpg, create_image_thumbnail


def _is_placeholder_image(url: Optional[str]) -> bool:
    """判断是否为占位符图片（懒加载 SVG 等），不应覆盖数据库中的真实图片。"""
    if not url or not isinstance(url, str):
        return True
    lowered = url.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return False
    if lowered.startswith("/chat_images/"):
        return False
    if not lowered.startswith("data:image"):
        return True
    if "svg" in url.split(",", 1)[0].lower():
        return True
    if len(url) < 1000:
        return True
    return False


async def _store_b64_image_in_conn(conn: aiosqlite.Connection, data_uri: str) -> str:
    """将 base64 data URI 放入短期内存交付缓存，返回 /chat_images/tmp_...。
    聊天图片由客户端缓存，服务端不再写入 SQLite BLOB。"""
    if not data_uri or not isinstance(data_uri, str):
        return data_uri
    stripped = data_uri.strip()
    if not stripped.startswith('data:image'):
        return data_uri
    try:
        header, _, b64_part = stripped.partition(',')
        if not b64_part:
            return data_uri
        header_lower = header.lower()
        if 'png' in header_lower:
            mime, ext = 'image/png', 'png'
        elif 'webp' in header_lower:
            mime, ext = 'image/webp', 'webp'
        elif 'gif' in header_lower:
            mime, ext = 'image/gif', 'gif'
        else:
            mime, ext = 'image/jpeg', 'jpg'

        raw = b64_mod.b64decode(b64_part)
        if len(raw) < 100:
            return data_uri

        url = store_chat_image_transfer(raw, mime)
        logger.debug(f"📎 [ChatImg] base64→短期URL: {url} ({len(raw)} bytes)")
        return url
    except Exception as e:
        logger.warning(f"⚠️ [ChatImg] base64→URL 转换失败: {e}")
        return data_uri


_CONTENT_B64_RE = re.compile(
    r'data:image/(?:jpeg|jpg|png|webp|gif);base64,[A-Za-z0-9+/=\r\n]{1000,}'
)
_INLINE_MD_IMAGE_RE = re.compile(r'!\[[^\]]*]\(([^)]+)\)')
_CHAT_IMAGE_URL_RE = re.compile(r'/chat_images/[\w.-]+')


def _strip_ephemeral_user_images_from_content(content: str) -> str:
    """普通用户上传图只供当轮识别使用，保存时从用户消息正文移除。"""
    if not content or not isinstance(content, str):
        return content or ""
    stripped = _INLINE_MD_IMAGE_RE.sub("", content)
    stripped = _CONTENT_B64_RE.sub("", stripped)
    stripped = _CHAT_IMAGE_URL_RE.sub("", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip()
    return stripped


async def _replace_content_b64_images(conn: aiosqlite.Connection, content: str) -> str:
    """将消息 content 中内联的 base64 data URI 替换为 /chat_images/ URL。"""
    if not content or 'data:image' not in content:
        return content
    parts = []
    last_end = 0
    for match in _CONTENT_B64_RE.finditer(content):
        parts.append(content[last_end:match.start()])
        url = await _store_b64_image_in_conn(conn, match.group(0))
        parts.append(url)
        last_end = match.end()
    if not parts:
        return content
    parts.append(content[last_end:])
    return ''.join(parts)


class ConversationsDAO:
    """对话数据访问对象"""
    
    def __init__(self, db: Database):
        self.db = db

    def _stable_normal_conversation_id(self, user_id: int, char_id: str) -> str:
        digest = hashlib.sha1(f"{user_id}:{char_id}".encode("utf-8")).hexdigest()[:16]
        return f"normal_{user_id}_{digest}"

    async def _pick_single_visible_conversation(
        self,
        conn: aiosqlite.Connection,
        user_id: int,
        char_id: str,
        requested_conv_id: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """
        普通对话模式强约束：同一用户×角色只保留一个可见 conversation。

        返回值为 (canonical_id, duplicate_visible_ids)。调用方负责在事务中隐藏 duplicates。
        """
        requested = str(requested_conv_id or "").strip()
        cur = await conn.execute(
            """SELECT c.id,
                      COALESCE(MAX(m.timestamp), c.timestamp, 0) AS activity_ts,
                      c.updated_at
               FROM conversations c
               LEFT JOIN messages m
                      ON m.conversation_id = c.id
                     AND m.deleted_at IS NULL
                     AND COALESCE(m.is_hidden, 0) = 0
               WHERE c.user_id = ?
                 AND c.character_id = ?
                 AND COALESCE(c.is_hidden, 0) = 0
               GROUP BY c.id
               ORDER BY activity_ts DESC, c.updated_at DESC, c.rowid DESC""",
            (user_id, char_id),
        )
        rows = await cur.fetchall()
        if rows:
            canonical_id = str(rows[0][0])
            duplicate_ids = [str(r[0]) for r in rows[1:] if str(r[0]) != canonical_id]
            if requested and requested != canonical_id:
                logger.warning(
                    "🧷 [普通对话唯一化] 忽略客户端新/旧 conversation_id: user=%s char=%s %s -> %s",
                    user_id,
                    (char_id or "")[:8],
                    requested[:12],
                    canonical_id[:12],
                )
            return canonical_id, duplicate_ids

        if requested:
            cur = await conn.execute(
                """SELECT COALESCE(is_hidden, 0)
                   FROM conversations
                   WHERE id = ? AND user_id = ? AND character_id = ?""",
                (requested, user_id, char_id),
            )
            row = await cur.fetchone()
            if not row or int(row[0] or 0) == 0:
                return requested, []

        fallback = self._stable_normal_conversation_id(user_id, char_id)
        cur = await conn.execute(
            """SELECT COALESCE(is_hidden, 0)
               FROM conversations
               WHERE id = ? AND user_id = ? AND character_id = ?""",
            (fallback, user_id, char_id),
        )
        row = await cur.fetchone()
        if row and int(row[0] or 0) == 1:
            fallback = f"{fallback}_{int(time.time() * 1000)}"
        return fallback, []
    
    async def save_conversation(
        self,
        username: str,
        char_id: str,
        conversation: Dict
    ) -> bool:
        """
        保存对话到数据库
        
        参数：
            username: 用户名
            char_id: 角色ID
            conversation: 对话对象，包含 id, title, timestamp, messages 等
            
        返回：
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                busy_timeout_ms = int(os.getenv("PONYCHAT_SQLITE_BUSY_TIMEOUT_MS") or "30000")
                await conn.execute(f"PRAGMA busy_timeout = {max(5000, busy_timeout_ms)}")
                
                user_id = await self.db._get_user_id(conn, username)
                resolved_char_id = await self.db.resolve_character_id_alias(conn, user_id, char_id)
                if resolved_char_id != char_id:
                    logger.info(
                        "🔁 [DB] 角色 ID alias: %s/%s -> %s",
                        username,
                        char_id,
                        resolved_char_id,
                    )
                    char_id = resolved_char_id
                
                # 确保角色存在（如果不存在则创建占位符角色）
                async with conn.execute(
                    "SELECT id FROM characters WHERE id = ? AND user_id = ?",
                    (char_id, user_id)
                ) as cursor:
                    char_exists = await cursor.fetchone()
                    if not char_exists:
                        await conn.execute(
                            """INSERT OR IGNORE INTO characters 
                               (id, user_id, name, avatar, prompt, bio, data)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (char_id, user_id, '未知角色', None, '', '', json.dumps({'id': char_id}))
                        )
                        # 必须在此提交，否则 aiosqlite 的隐式事务会与后续
                        # BEGIN IMMEDIATE 冲突，导致 "cannot start a transaction
                        # within a transaction" 错误。
                        await conn.commit()
                        logger.warning(f"⚠️ [DB] 角色 {char_id[:8]}... 不存在，已创建占位符")
                
                requested_conv_id = conversation.get('id')
                conv_id, duplicate_conv_ids = await self._pick_single_visible_conversation(
                    conn,
                    user_id,
                    char_id,
                    requested_conv_id,
                )
                conversation['id'] = conv_id
                title = conversation.get('title', '新对话')
                timestamp = conversation.get('timestamp', 0)
                incoming_version = conversation.get('version', 1)
                # 摘要字段保护：前端 auto_sync 未携带摘要字段时，保留后端已落库摘要与 cutoff，
                # 避免“已总结状态”被空覆盖后回退成全量上下文。
                existing_summary = ''
                existing_cutoff_message_id = None
                existing_cutoff_timestamp = None
                existing_cutoff_sequence = None
                if conv_id:
                    async with conn.execute(
                        """SELECT summary, context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence
                           FROM conversations
                           WHERE id = ? AND character_id = ? AND user_id = ?""",
                        (conv_id, char_id, user_id)
                    ) as sc:
                        srow = await sc.fetchone()
                        if srow:
                            existing_summary = str(srow[0] or '').strip()
                            existing_cutoff_message_id = srow[1]
                            existing_cutoff_timestamp = srow[2]
                            existing_cutoff_sequence = srow[3]

                def _pick_payload_value(*keys, fallback=None):
                    for k in keys:
                        if k in conversation:
                            return conversation.get(k)
                    return fallback

                summary = str(
                    _pick_payload_value('contextSummary', 'summary', fallback=existing_summary) or ''
                ).strip()
                context_summary_cutoff_message_id = _pick_payload_value(
                    'contextSummaryCutoffMessageId', 'context_summary_cutoff_message_id',
                    fallback=existing_cutoff_message_id
                )
                context_summary_cutoff_timestamp = _pick_payload_value(
                    'contextSummaryCutoffTimestamp', 'context_summary_cutoff_timestamp',
                    fallback=existing_cutoff_timestamp
                )
                context_summary_cutoff_sequence = _pick_payload_value(
                    'contextSummaryCutoffSequence', 'context_summary_cutoff_sequence',
                    fallback=existing_cutoff_sequence
                )
                force_clear_requested = bool(
                    conversation.get('force_clear') is True
                    or conversation.get('force_reset') is True
                )
                
                # 🔧 [事务保护] 使用显式事务确保写入+软删除的原子性
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    if duplicate_conv_ids:
                        placeholders = ",".join("?" * len(duplicate_conv_ids))
                        await conn.execute(
                            f"""UPDATE conversations
                                SET is_hidden = 1,
                                    hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                                    hidden_reason = COALESCE(hidden_reason, 'normal_single_conversation_enforced'),
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE user_id = ?
                                  AND character_id = ?
                                  AND id IN ({placeholders})
                                  AND COALESCE(is_hidden, 0) = 0""",
                            (user_id, char_id, *duplicate_conv_ids),
                        )
                        for dup_id in duplicate_conv_ids:
                            await write_deletion_audit(
                                conn,
                                action="soft_delete",
                                object_type="conversation",
                                object_id=dup_id,
                                user_id=user_id,
                                username=username,
                                character_id=char_id,
                                conversation_id=dup_id,
                                operator="system",
                                reason="normal_single_conversation_enforced",
                                source="sync",
                                details={"canonical_conversation_id": conv_id},
                            )

                    # 🛡️ [防误恢复] 用户已软删除的对话不允许被普通保存操作复活
                    existing_version = 0
                    async with conn.execute(
                        "SELECT version, is_hidden FROM conversations WHERE id = ?", (conv_id,)
                    ) as vc:
                        row = await vc.fetchone()
                        if row:
                            existing_version = row[0] or 0
                            if row[1]:  # is_hidden = 1
                                logger.warning(f"🛡️ [DB] 跳过保存已删除对话 {conv_id[:8] if conv_id else '?'}... (is_hidden=1)")
                                await conn.execute("ROLLBACK")
                                return False
                    # 自动递增 version：取 max(已有版本, 前端版本) + 1，确保每次保存版本号单调递增
                    version = max(existing_version, incoming_version) + 1

                    # 此处不要用 INSERT OR REPLACE：SQLite 的 REPLACE 实际是
                    # DELETE+INSERT，会通过 FK 级联删除 messages。
                    cur = await conn.execute(
                        """UPDATE conversations
                           SET character_id = ?,
                               user_id = ?,
                               title = ?,
                               timestamp = ?,
                               version = ?,
                               summary = ?,
                               context_summary_cutoff_message_id = ?,
                               context_summary_cutoff_timestamp = ?,
                               context_summary_cutoff_sequence = ?,
                               is_hidden = 0,
                               hidden_at = NULL,
                               hidden_reason = NULL,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (
                            char_id, user_id, title, timestamp, version, summary,
                            context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence,
                            conv_id
                        )
                    )
                    if cur.rowcount == 0:
                        await conn.execute(
                            """INSERT INTO conversations
                               (id, character_id, user_id, title, timestamp, version, summary,
                                context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence,
                                is_hidden, hidden_at, hidden_reason, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, CURRENT_TIMESTAMP)""",
                            (
                                conv_id, char_id, user_id, title, timestamp, version, summary,
                                context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence
                            )
                        )
                    
                    # 🔧 [占位符保护] 删除前读取本对话下已有消息的图片，避免用占位符覆盖真实 4K 等大图
                    existing_images = {}
                    existing_speakers = {}
                    existing_message_ids = {}
                    occupied_message_row_ids = set()
                    async with conn.execute(
                        """SELECT id, message_id, image_url, image_thumbnail,
                                  speaker_character_id, speaker_name, speaker_avatar
                           FROM messages WHERE conversation_id = ?""",
                        (conv_id,)
                    ) as cur:
                        async for row in cur:
                            row_id, mid, iu, it = row[0], row[1], row[2], row[3]
                            if row_id:
                                occupied_message_row_ids.add(row_id)
                            if mid:
                                existing_message_ids[str(mid)] = row_id
                                if (iu or it) and not _is_placeholder_image(iu):
                                    existing_images[str(mid)] = (iu, it)
                                speaker_info = (row[4], row[5], row[6])
                                if any(speaker_info):
                                    existing_speakers[str(mid)] = speaker_info
                    
                    messages = conversation.get('messages', [])
                    seen_message_ids = set()
                    incoming_message_ids = []
                    for idx, msg in enumerate(messages):
                        message_id = msg.get('message_id')
                        if not message_id:
                            message_id = msg.get('id') or f"{conv_id}_msg_{idx}_{timestamp}"
                        
                        if message_id in seen_message_ids:
                            logger.warning(f"⚠️ [DB] 跳过重复消息ID: {message_id}")
                            continue
                        seen_message_ids.add(message_id)
                        incoming_message_ids.append(message_id)
                        
                        msg_id = msg.get('id') or existing_message_ids.get(str(message_id))
                        if not msg_id:
                            candidate_msg_id = f"{conv_id}_msg_{idx}"
                            if candidate_msg_id in occupied_message_row_ids:
                                msg_id = f"{conv_id}_msg_{idx}_{uuid.uuid4().hex[:12]}"
                                occupied_message_row_ids.add(msg_id)
                            else:
                                msg_id = candidate_msg_id
                                occupied_message_row_ids.add(msg_id)
                        role = msg.get('role', 'user')
                        content = msg.get('content', '')
                        raw_content = msg.get('rawContent', '')
                        if role == 'user':
                            # 用户上传图在进入此保存路径前已被视觉/模型一次性使用；
                            # 服务端不再持久化原图、缩略图或正文内联图引用。
                            content = _strip_ephemeral_user_images_from_content(content)
                            raw_content = _strip_ephemeral_user_images_from_content(raw_content)
                            msg['content'] = content
                            msg.pop('image_url', None)
                            msg.pop('images', None)
                            if raw_content:
                                msg['rawContent'] = raw_content
                            else:
                                msg.pop('rawContent', None)
                        else:
                            content = await _replace_content_b64_images(conn, content)
                        # 标记这次同步是否显式携带 image_url 字段
                        has_image_field = 'image_url' in msg
                        image_url = msg.get('image_url')
                        image_thumbnail = None
                        # 🔧 [图片保护]
                        # 1) 若前端没带 image_url 字段，视为“不同步图片”，保留库中已有真实图；
                        # 2) 若带的是占位符（懒加载 SVG 等），同样保留已有真实图；
                        # 3) 只有显式带入真实 data:image 时才更新并生成缩略图。
                        if role == 'user':
                            image_url = None
                            image_thumbnail = None
                        elif has_image_field:
                            if _is_placeholder_image(image_url):
                                existing = existing_images.get(message_id)
                                if existing:
                                    image_url, image_thumbnail = existing
                                    logger.debug(f"🖼️ [DB] 保留已有图片，不写入占位符: {message_id[:20]}...")
                                else:
                                    image_url = None
                                    image_thumbnail = None
                            elif image_url and isinstance(image_url, str) and image_url.startswith('data:image'):
                                is_draw = msg.get('is_draw_image') is True
                                image_url = compress_image_to_jpg(image_url, skip_compress=is_draw)
                                image_thumbnail = create_image_thumbnail(image_url)
                                image_url = await _store_b64_image_in_conn(conn, image_url)
                                image_thumbnail = await _store_b64_image_in_conn(conn, image_thumbnail)
                            else:
                                existing = existing_images.get(message_id)
                                if existing:
                                    image_thumbnail = existing[1]
                        else:
                            # 本次未同步图片字段：如果库里已有真实图，则沿用
                            existing = existing_images.get(message_id)
                            if existing:
                                image_url, image_thumbnail = existing
                        msg_timestamp = msg.get('timestamp', timestamp)
                        # 统一重建连续序号，避免历史脏数据/并发覆盖造成序号乱序后影响读取顺序
                        sequence_number = idx
                        previous_message_id = msg.get('previous_message_id')
                        suggestions = json.dumps(msg.get('suggestions', [])) if msg.get('suggestions') else None
                        suggestions_status = msg.get('suggestions_status')
                        if not suggestions_status:
                            suggestions_status = 'ready' if msg.get('suggestions') else 'none'
                        client_id = msg.get('client_id')
                        quoted_message = msg.get('quoted_message') or msg.get('quotedMessage')
                        quoted_message_json = json.dumps(quoted_message, ensure_ascii=False) if quoted_message else None
                        speaker_character_id = msg.get('speaker_character_id') or msg.get('speakerCharacterId')
                        speaker_name = msg.get('speaker_name') or msg.get('speakerName')
                        speaker_avatar = msg.get('speaker_avatar') or msg.get('speakerAvatar')
                        if role == 'assistant':
                            existing_speaker = existing_speakers.get(str(message_id))
                            if existing_speaker:
                                if not speaker_character_id:
                                    speaker_character_id = existing_speaker[0]
                                if not speaker_name:
                                    speaker_name = existing_speaker[1]
                                if not speaker_avatar:
                                    speaker_avatar = existing_speaker[2]
                        attachments = msg.get('attachments') if isinstance(msg.get('attachments'), list) else []
                        generation_duration_ms = msg.get('generation_duration_ms')
                        think_translations = json.dumps(msg.get('thinkTranslations', {})) if msg.get('thinkTranslations') else None
                        is_hidden = 1 if (msg.get('is_hidden') or msg.get('isHidden')) else 0
                        hidden_at = msg.get('hidden_at') or msg.get('hiddenAt')
                        hidden_reason = msg.get('hidden_reason') or msg.get('hiddenReason')
                        deleted_at = msg.get('deleted_at')
                        delete_reason = msg.get('delete_reason')
                        if is_hidden:
                            if not hidden_at:
                                hidden_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                            if not hidden_reason:
                                hidden_reason = delete_reason or 'hidden_by_client'
                            if not deleted_at:
                                deleted_at = hidden_at
                            if not delete_reason:
                                delete_reason = hidden_reason
                        
                        # 🛡️ [防覆盖隐藏态] 前端正常消息不带 is_hidden/deleted_at，
                        # 若库中该消息已被标记隐藏/软删除，则跳过写入，避免 INSERT OR REPLACE 把隐藏标记抹掉
                        if not is_hidden and not deleted_at:
                            async with conn.execute(
                                "SELECT COALESCE(is_hidden, 0), deleted_at FROM messages WHERE id = ? LIMIT 1",
                                (msg_id,)
                            ) as chk:
                                chk_row = await chk.fetchone()
                                if chk_row and (chk_row[0] == 1 or chk_row[1] is not None):
                                    # 库中已隐藏/删除，前端传入的是正常态——保留库中状态，只更新内容字段
                                    await conn.execute(
                                        """UPDATE messages SET
                                              role = ?, content = ?, raw_content = ?, image_url = ?, timestamp = ?,
                                              message_id = ?, sequence_number = ?, previous_message_id = ?,
                                              suggestions = ?, suggestions_status = ?, client_id = ?,
                                              image_thumbnail = ?, think_translations = ?, generation_duration_ms = ?,
                                              quoted_message_json = ?,
                                              speaker_character_id = ?, speaker_name = ?, speaker_avatar = ?
                                           WHERE id = ?""",
                                        (role, content, raw_content, image_url, msg_timestamp,
                                         message_id, sequence_number, previous_message_id,
                                         suggestions, suggestions_status, client_id,
                                         image_thumbnail, think_translations, generation_duration_ms,
                                         quoted_message_json,
                                         speaker_character_id, speaker_name, speaker_avatar,
                                         msg_id)
                                    )
                                    await replace_message_attachments(conn, conv_id, message_id, attachments)
                                    continue

                        await conn.execute(
                            """INSERT OR REPLACE INTO messages 
                               (id, conversation_id, role, content, raw_content, image_url, timestamp, 
                                message_id, sequence_number, previous_message_id, suggestions, suggestions_status, client_id, image_thumbnail, think_translations,
                                generation_duration_ms, quoted_message_json, speaker_character_id, speaker_name, speaker_avatar,
                                is_hidden, hidden_at, hidden_reason, deleted_at, delete_reason)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (msg_id, conv_id, role, content, raw_content, image_url, msg_timestamp,
                             message_id, sequence_number, previous_message_id, suggestions, suggestions_status, client_id, image_thumbnail, think_translations,
                             generation_duration_ms, quoted_message_json,
                             speaker_character_id, speaker_name, speaker_avatar,
                             is_hidden, hidden_at, hidden_reason, deleted_at, delete_reason)
                        )
                        await replace_message_attachments(conn, conv_id, message_id, attachments)
                    # 🛡️ [软删除] 对话中未再出现的历史消息仅做隐藏，不做物理删除
                    if incoming_message_ids:
                        async with conn.execute(
                            f"""SELECT COUNT(*) FROM messages
                                WHERE conversation_id = ?
                                  AND deleted_at IS NULL
                                  AND message_id NOT IN ({",".join(["?"] * len(incoming_message_ids))})""",
                            (conv_id, *incoming_message_ids),
                        ) as diff_cur:
                            diff_row = await diff_cur.fetchone()
                            diff_soft_delete_count = diff_row[0] if diff_row else 0
                        async with conn.execute(
                            """SELECT COUNT(*) FROM messages
                               WHERE conversation_id = ? AND deleted_at IS NULL AND message_id IS NULL""",
                            (conv_id,),
                        ) as legacy_cur:
                            legacy_row = await legacy_cur.fetchone()
                            legacy_soft_delete_count = legacy_row[0] if legacy_row else 0

                        mass_prune_guard = (
                            diff_soft_delete_count >= 50
                            and len(incoming_message_ids) < diff_soft_delete_count
                            and not force_clear_requested
                        )
                        if mass_prune_guard:
                            logger.warning(
                                f"🛡️ [防旧端小列表覆盖] 跳过大规模消息隐藏: {char_id[:8]}.../{conv_id[:8]}... "
                                f"(后端缺失候选 {diff_soft_delete_count} 条, 前端传入 {len(incoming_message_ids)} 条)"
                            )
                            await write_deletion_audit(
                                conn,
                                action="soft_delete",
                                object_type="conversation",
                                object_id=conv_id,
                                user_id=user_id,
                                username=username,
                                character_id=char_id,
                                conversation_id=conv_id,
                                operator=f"user:{username}",
                                reason="sync_prune_messages_skipped_mass_guard",
                                source="sync",
                                details={
                                    "would_soft_delete": diff_soft_delete_count,
                                    "incoming_messages": len(incoming_message_ids),
                                    "legacy_null_mid_soft_deleted": legacy_soft_delete_count,
                                },
                            )
                        else:
                            placeholders = ",".join(["?"] * len(incoming_message_ids))
                            await conn.execute(
                                f"""UPDATE messages
                                    SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                                        delete_reason = COALESCE(delete_reason, 'user_removed_from_conversation'),
                                        is_hidden = 1,
                                        hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                                        hidden_reason = COALESCE(hidden_reason, 'user_removed_from_conversation')
                                    WHERE conversation_id = ?
                                      AND deleted_at IS NULL
                                      AND message_id NOT IN ({placeholders})""",
                                (conv_id, *incoming_message_ids)
                            )
                            await conn.execute(
                                """UPDATE messages
                                   SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                                       delete_reason = COALESCE(delete_reason, 'legacy_null_message_id'),
                                       is_hidden = 1,
                                       hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                                       hidden_reason = COALESCE(hidden_reason, 'legacy_null_message_id')
                                   WHERE conversation_id = ? AND deleted_at IS NULL AND message_id IS NULL""",
                                (conv_id,)
                            )
                            if (diff_soft_delete_count + legacy_soft_delete_count) > 0:
                                await write_deletion_audit(
                                    conn,
                                    action="soft_delete",
                                    object_type="conversation",
                                    object_id=conv_id,
                                    user_id=user_id,
                                    username=username,
                                    character_id=char_id,
                                    conversation_id=conv_id,
                                    operator=f"user:{username}",
                                    reason="sync_prune_messages",
                                    source="sync",
                                    details={
                                        "diff_soft_deleted": diff_soft_delete_count,
                                        "legacy_null_mid_soft_deleted": legacy_soft_delete_count,
                                    },
                                )
                    else:
                        # 🛡️ [关键保护] 如果传入的消息列表为空，但后端已有未删除的消息，
                        # 拒绝全量软删除，避免前端异常（如模块双实例、空状态同步）导致数据丢失
                        existing_count_cur = await conn.execute(
                            "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND deleted_at IS NULL AND COALESCE(is_hidden, 0) = 0",
                            (conv_id,)
                        )
                        existing_count_row = await existing_count_cur.fetchone()
                        existing_active_count = existing_count_row[0] if existing_count_row else 0
                        
                        if existing_active_count > 0 and not force_clear_requested:
                            logger.warning(
                                f"🛡️ [防空覆盖] 拒绝清空对话消息: {char_id[:8]}.../{conv_id[:8]}... "
                                f"(后端有 {existing_active_count} 条活跃消息, 前端传入 0 条) — 跳过软删除"
                            )
                        else:
                            if existing_active_count > 0 and force_clear_requested:
                                logger.info(
                                    f"🗑️ [force_clear] 允许清空对话: {char_id[:8]}.../{conv_id[:8]}... "
                                    f"(后端有 {existing_active_count} 条活跃消息, 前端显式 force_clear)"
                                )
                            await conn.execute(
                                """UPDATE messages
                                   SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                                       delete_reason = COALESCE(delete_reason, 'conversation_cleared'),
                                       is_hidden = 1,
                                       hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                                       hidden_reason = COALESCE(hidden_reason, 'conversation_cleared')
                                   WHERE conversation_id = ? AND deleted_at IS NULL""",
                                (conv_id,)
                            )
                            # 全量清空时一并清除记忆缓存
                            await conn.execute(
                                "DELETE FROM normal_chat_memory WHERE username = ? AND character_id = ? AND conversation_id = ?",
                                (username, char_id, conv_id)
                            )
                            await conn.execute(
                                "DELETE FROM normal_emotion_state WHERE username = ? AND character_id = ? AND conversation_id = ?",
                                (username, char_id, conv_id)
                            )
                            await conn.execute(
                                "DELETE FROM normal_scene_state WHERE username = ? AND character_id = ? AND conversation_id = ?",
                                (username, char_id, conv_id)
                            )
                            if existing_active_count > 0:
                                await write_deletion_audit(
                                    conn,
                                    action="soft_delete",
                                    object_type="conversation",
                                    object_id=conv_id,
                                    user_id=user_id,
                                    username=username,
                                    character_id=char_id,
                                    conversation_id=conv_id,
                                    operator=f"user:{username}",
                                    reason="conversation_cleared",
                                    source="sync",
                                    details={
                                        "soft_deleted_messages": existing_active_count,
                                        "force_clear": force_clear_requested,
                                    },
                                )
                    
                    await conn.execute("COMMIT")
                except Exception:
                    await conn.execute("ROLLBACK")
                    raise
                
                logger.debug(f"💾 [DB] 保存对话: {char_id[:8]}.../{conv_id[:8]}... ({len(messages)} 条消息)")
                return True
                
        except Exception as e:
            logger.error(f"❌ [DB] 保存对话失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def load_conversations(
        self,
        username: str,
        char_id: str
    ) -> List[Dict]:
        """
        加载角色的所有对话
        
        参数：
            username: 用户名
            char_id: 角色ID
            
        返回：
            对话列表
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                # 启用外键约束
                await conn.execute("PRAGMA foreign_keys = ON")
                
                # 获取用户ID
                user_id = await self.db._get_user_id(conn, username)
                resolved_char_id = await self.db.resolve_character_id_alias(conn, user_id, char_id)
                if resolved_char_id != char_id:
                    logger.info(
                        "🔁 [DB] 加载对话使用角色 ID alias: %s/%s -> %s",
                        username,
                        char_id,
                        resolved_char_id,
                    )
                    char_id = resolved_char_id

                canonical_id, duplicate_conv_ids = await self._pick_single_visible_conversation(
                    conn,
                    user_id,
                    char_id,
                )
                if duplicate_conv_ids:
                    placeholders = ",".join("?" * len(duplicate_conv_ids))
                    await conn.execute(
                        f"""UPDATE conversations
                            SET is_hidden = 1,
                                hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                                hidden_reason = COALESCE(hidden_reason, 'normal_single_conversation_enforced'),
                                updated_at = CURRENT_TIMESTAMP
                            WHERE user_id = ?
                              AND character_id = ?
                              AND id IN ({placeholders})
                              AND COALESCE(is_hidden, 0) = 0""",
                        (user_id, char_id, *duplicate_conv_ids),
                    )
                    for dup_id in duplicate_conv_ids:
                        await write_deletion_audit(
                            conn,
                            action="soft_delete",
                            object_type="conversation",
                            object_id=dup_id,
                            user_id=user_id,
                            username=username,
                            character_id=char_id,
                            conversation_id=dup_id,
                            operator="system",
                            reason="normal_single_conversation_enforced",
                            source="load",
                            details={"canonical_conversation_id": canonical_id},
                        )
                    await conn.commit()
                
                # 查询对话（含 updated_at，供保存时按时间比较避免旧数据覆盖）
                async with conn.execute(
                    """SELECT id, title, timestamp, version, summary,
                              context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence,
                              updated_at 
                       FROM conversations 
                       WHERE user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0
                       ORDER BY timestamp DESC""",
                    (user_id, char_id)
                ) as cursor:
                    conversations = []
                    async for row in cursor:
                        conv_id, title, timestamp, version, summary = row[0], row[1], row[2], row[3], row[4]
                        context_summary_cutoff_message_id = row[5] if len(row) > 5 else None
                        context_summary_cutoff_timestamp = row[6] if len(row) > 6 else None
                        context_summary_cutoff_sequence = row[7] if len(row) > 7 else None
                        updated_at = row[8] if len(row) > 8 else None
                        
                        # 加载消息
                        messages = []
                        async with conn.execute(
                            """SELECT role, content, raw_content, image_url, timestamp, message_id, 
                                      sequence_number, previous_message_id, suggestions, suggestions_status, client_id, think_translations, generation_duration_ms, quoted_message_json,
                                      speaker_character_id, speaker_name, speaker_avatar,
                                      is_hidden, hidden_at, hidden_reason
                               FROM messages 
                               WHERE conversation_id = ? AND deleted_at IS NULL AND COALESCE(is_hidden, 0) = 0
                               ORDER BY COALESCE(timestamp, 0) ASC, COALESCE(sequence_number, 0) ASC, rowid ASC""",
                            (conv_id,)
                        ) as msg_cursor:
                            async for msg_row in msg_cursor:
                                role, content, raw_content, image_url, msg_timestamp, message_id, \
                                sequence_number, previous_message_id, suggestions_json, suggestions_status, client_id, think_translations_json, \
                                generation_duration_ms, quoted_message_json, speaker_character_id, speaker_name, speaker_avatar, \
                                is_hidden, hidden_at, hidden_reason = msg_row
                                
                                msg = {
                                    'role': role,
                                    'content': content,
                                    'timestamp': msg_timestamp,
                                    'message_id': message_id,
                                    'sequence_number': sequence_number,
                                    'previous_message_id': previous_message_id,
                                    'is_hidden': bool(is_hidden),
                                    'hidden_at': hidden_at,
                                    'hidden_reason': hidden_reason,
                                }
                                
                                # 🔧 [修复] 返回 rawContent（包含思考标签的原始内容）
                                if raw_content:
                                    msg['rawContent'] = raw_content
                                
                                if image_url:
                                    msg['image_url'] = image_url
                                if suggestions_json:
                                    try:
                                        msg['suggestions'] = json.loads(suggestions_json)
                                    except:
                                        msg['suggestions'] = []
                                msg['suggestions_status'] = suggestions_status or ('ready' if msg.get('suggestions') else 'none')
                                if client_id:
                                    msg['client_id'] = client_id
                                if think_translations_json:
                                    try:
                                        msg['thinkTranslations'] = json.loads(think_translations_json)
                                    except Exception:
                                        msg['thinkTranslations'] = {}
                                if generation_duration_ms is not None:
                                    msg['generation_duration_ms'] = int(generation_duration_ms)
                                if quoted_message_json:
                                    try:
                                        msg['quoted_message'] = json.loads(quoted_message_json)
                                    except Exception:
                                        pass
                                if speaker_character_id:
                                    msg['speaker_character_id'] = speaker_character_id
                                if speaker_name:
                                    msg['speaker_name'] = speaker_name
                                if speaker_avatar:
                                    msg['speaker_avatar'] = speaker_avatar
                                
                                messages.append(msg)
                        attachments_by_mid = await load_attachments_for_messages(
                            conn,
                            conv_id,
                            [str(m.get("message_id") or "") for m in messages],
                        )
                        for msg in messages:
                            atts = attachments_by_mid.get(str(msg.get("message_id") or ""))
                            if atts:
                                msg["attachments"] = atts
                        voice_states_by_mid = await load_voice_states_for_messages(
                            conn,
                            conv_id,
                            [str(m.get("message_id") or "") for m in messages],
                        )
                        for msg in messages:
                            attach_voice_state(msg, voice_states_by_mid.get(str(msg.get("message_id") or "")))
                        
                        conversations.append({
                            'id': conv_id,
                            'title': title,
                            'timestamp': timestamp,
                            'version': version,
                            'summary': summary or '',
                            'contextSummary': summary or '',
                            'contextSummaryTime': timestamp,
                            'contextSummaryCutoffMessageId': context_summary_cutoff_message_id,
                            'contextSummaryCutoffTimestamp': context_summary_cutoff_timestamp,
                            'contextSummaryCutoffSequence': context_summary_cutoff_sequence,
                            'messages': messages,
                            'updated_at': updated_at
                        })
                    
                    if conversations:
                        if char_id:
                            logger.debug(f"📥 [DB] 加载对话: {char_id[:8]}... ({len(conversations)} 个对话)")
                        else:
                            logger.debug(f"📥 [DB] 加载对话: 所有角色 ({len(conversations)} 个对话)")
                        return conversations

                    if char_id:
                        logger.debug(f"📥 [DB] 加载对话: {char_id[:8]}... (0 个对话)")
                    else:
                        logger.debug("📥 [DB] 加载对话: 所有角色 (0 个对话)")
                    return []
                    
        except Exception as e:
            logger.error(f"❌ [DB] 加载对话失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    async def load_conversations_by_char_id_prefix(
        self,
        username: str,
        char_id: str
    ) -> List[Dict]:
        """
        按角色 ID 或「角色ID_后缀」加载对话（用于从大厅添加的角色：id 为 originalId_timestamp，重进时可能只传 originalId）。
        WHERE character_id = ? OR character_id LIKE ?||'_%'
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                user_id = await self.db._get_user_id(conn, username)
                resolved_char_id = await self.db.resolve_character_id_alias(conn, user_id, char_id)
                if resolved_char_id != char_id:
                    char_id = resolved_char_id
                pattern = char_id + "_%"
                async with conn.execute(
                    """SELECT id, title, timestamp, version, summary,
                              context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence,
                              updated_at 
                       FROM conversations 
                       WHERE user_id = ? AND (character_id = ? OR character_id LIKE ?) AND COALESCE(is_hidden, 0) = 0
                       ORDER BY timestamp DESC""",
                    (user_id, char_id, pattern)
                ) as cursor:
                    conversations = []
                    async for row in cursor:
                        conv_id, title, timestamp, version, summary = row[0], row[1], row[2], row[3], row[4]
                        context_summary_cutoff_message_id = row[5] if len(row) > 5 else None
                        context_summary_cutoff_timestamp = row[6] if len(row) > 6 else None
                        context_summary_cutoff_sequence = row[7] if len(row) > 7 else None
                        updated_at = row[8] if len(row) > 8 else None
                        messages = []
                        async with conn.execute(
                            """SELECT role, content, raw_content, image_url, timestamp, message_id, 
                                      sequence_number, previous_message_id, suggestions, suggestions_status, client_id, think_translations, generation_duration_ms, quoted_message_json,
                                      speaker_character_id, speaker_name, speaker_avatar,
                                      is_hidden, hidden_at, hidden_reason
                               FROM messages 
                               WHERE conversation_id = ? AND deleted_at IS NULL AND COALESCE(is_hidden, 0) = 0
                               ORDER BY COALESCE(timestamp, 0) ASC, COALESCE(sequence_number, 0) ASC, rowid ASC""",
                            (conv_id,)
                        ) as msg_cursor:
                            async for msg_row in msg_cursor:
                                role, content, raw_content, image_url, msg_timestamp, message_id, \
                                sequence_number, previous_message_id, suggestions_json, suggestions_status, client_id, think_translations_json, \
                                generation_duration_ms, quoted_message_json, speaker_character_id, speaker_name, speaker_avatar, \
                                is_hidden, hidden_at, hidden_reason = msg_row
                                msg = {
                                    'role': role,
                                    'content': content,
                                    'timestamp': msg_timestamp,
                                    'message_id': message_id,
                                    'sequence_number': sequence_number,
                                    'previous_message_id': previous_message_id,
                                    'is_hidden': bool(is_hidden),
                                    'hidden_at': hidden_at,
                                    'hidden_reason': hidden_reason,
                                }
                                if raw_content:
                                    msg['rawContent'] = raw_content
                                if image_url:
                                    msg['image_url'] = image_url
                                if suggestions_json:
                                    try:
                                        msg['suggestions'] = json.loads(suggestions_json)
                                    except Exception:
                                        msg['suggestions'] = []
                                msg['suggestions_status'] = suggestions_status or ('ready' if msg.get('suggestions') else 'none')
                                if client_id:
                                    msg['client_id'] = client_id
                                if think_translations_json:
                                    try:
                                        msg['thinkTranslations'] = json.loads(think_translations_json)
                                    except Exception:
                                        msg['thinkTranslations'] = {}
                                if generation_duration_ms is not None:
                                    msg['generation_duration_ms'] = int(generation_duration_ms)
                                if quoted_message_json:
                                    try:
                                        msg['quoted_message'] = json.loads(quoted_message_json)
                                    except Exception:
                                        pass
                                if speaker_character_id:
                                    msg['speaker_character_id'] = speaker_character_id
                                if speaker_name:
                                    msg['speaker_name'] = speaker_name
                                if speaker_avatar:
                                    msg['speaker_avatar'] = speaker_avatar
                                messages.append(msg)
                        attachments_by_mid = await load_attachments_for_messages(
                            conn,
                            conv_id,
                            [str(m.get("message_id") or "") for m in messages],
                        )
                        for msg in messages:
                            atts = attachments_by_mid.get(str(msg.get("message_id") or ""))
                            if atts:
                                msg["attachments"] = atts
                        voice_states_by_mid = await load_voice_states_for_messages(
                            conn,
                            conv_id,
                            [str(m.get("message_id") or "") for m in messages],
                        )
                        for msg in messages:
                            attach_voice_state(msg, voice_states_by_mid.get(str(msg.get("message_id") or "")))
                        conversations.append({
                            'id': conv_id,
                            'title': title,
                            'timestamp': timestamp,
                            'version': version,
                            'summary': summary or '',
                            'contextSummary': summary or '',
                            'contextSummaryTime': timestamp,
                            'contextSummaryCutoffMessageId': context_summary_cutoff_message_id,
                            'contextSummaryCutoffTimestamp': context_summary_cutoff_timestamp,
                            'contextSummaryCutoffSequence': context_summary_cutoff_sequence,
                            'messages': messages,
                            'updated_at': updated_at
                        })
                    logger.debug(f"📥 [DB] 按前缀加载对话: {char_id[:8]}... ({len(conversations)} 个对话)")
                    return conversations
        except Exception as e:
            logger.error(f"❌ [DB] 按前缀加载对话失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    async def delete_conversation(
        self,
        username: str,
        char_id: str,
        conv_id: str
    ) -> bool:
        """
        删除对话
        
        参数：
            username: 用户名
            char_id: 角色ID
            conv_id: 对话ID
            
        返回：
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                user_id = await self.db._get_user_id(conn, username)
                resolved_char_id = await self.db.resolve_character_id_alias(conn, user_id, char_id)
                if resolved_char_id != char_id:
                    char_id = resolved_char_id
                
                # 🛡️ [软删除] 用户删除仅隐藏，不做物理删除，管理员可后续恢复
                await conn.execute(
                    """UPDATE conversations
                       SET is_hidden = 1,
                           hidden_at = CURRENT_TIMESTAMP,
                           hidden_reason = 'user_delete',
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND user_id = ?""",
                    (conv_id, user_id)
                )
                # 对话删除时同步清除记忆缓存（原始消息仍保留，下次需要时可重建）
                await conn.execute(
                    "DELETE FROM normal_chat_memory WHERE username = ? AND character_id = ? AND conversation_id = ?",
                    (username, char_id, conv_id)
                )
                await conn.execute(
                    "DELETE FROM normal_emotion_state WHERE username = ? AND character_id = ? AND conversation_id = ?",
                    (username, char_id, conv_id)
                )
                await conn.execute(
                    "DELETE FROM normal_scene_state WHERE username = ? AND character_id = ? AND conversation_id = ?",
                    (username, char_id, conv_id)
                )
                await write_deletion_audit(
                    conn,
                    action="soft_delete",
                    object_type="conversation",
                    object_id=conv_id,
                    user_id=user_id,
                    username=username,
                    character_id=char_id,
                    conversation_id=conv_id,
                    operator=f"user:{username}",
                    reason="user_delete",
                    source="api",
                )
                await conn.commit()
                
                logger.info(f"🗑️ [DB] 删除对话: {char_id[:8] if char_id else '?'}.../{conv_id[:8]}...")
                return True
                
        except Exception as e:
            logger.error(f"❌ [DB] 删除对话失败: {e}")
            return False
    
    async def get_conversation_count(
        self,
        username: str,
        char_id: Optional[str] = None
    ) -> int:
        """
        获取对话数量
        
        参数：
            username: 用户名
            char_id: 角色ID（可选，如果提供则只统计该角色的对话）
            
        返回：
            对话数量
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                user_id = await self.db._get_user_id(conn, username)
                
                if char_id:
                    resolved_char_id = await self.db.resolve_character_id_alias(conn, user_id, char_id)
                    if resolved_char_id != char_id:
                        char_id = resolved_char_id
                    async with conn.execute(
                        "SELECT COUNT(*) FROM conversations WHERE user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0",
                        (user_id, char_id)
                    ) as cursor:
                        row = await cursor.fetchone()
                        return row[0] if row else 0
                else:
                    async with conn.execute(
                        "SELECT COUNT(*) FROM conversations WHERE user_id = ? AND COALESCE(is_hidden, 0) = 0",
                        (user_id,)
                    ) as cursor:
                        row = await cursor.fetchone()
                        return row[0] if row else 0
                        
        except Exception as e:
            logger.error(f"❌ [DB] 获取对话数量失败: {e}")
            return 0

    async def get_sync_fingerprint(self, username: str) -> Dict[str, str]:
        """
        获取对话数据的同步指纹（按角色维度的最新 updated_at），用于定时同步时判断是否有变更。
        返回: { character_id: "updated_at 字符串", ... }
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                user_id = await self.db._get_user_id(conn, username)
                if user_id is None:
                    return {}
                async with conn.execute(
                    """SELECT character_id, max(updated_at) as updated
                       FROM conversations WHERE user_id = ? AND COALESCE(is_hidden, 0) = 0 GROUP BY character_id""",
                    (user_id,)
                ) as cursor:
                    result = {}
                    async for row in cursor:
                        char_id, updated = row
                        if char_id and updated:
                            result[char_id] = str(updated)
                    return result
        except Exception as e:
            logger.error(f"❌ [DB] 获取同步指纹失败: {e}")
            return {}
