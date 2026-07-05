"""
角色数据访问对象（DAO）
处理角色信息的数据库操作
"""
import aiosqlite
import json
from typing import List, Dict, Optional
from .database import Database, get_database
from ..config import logger
from ..utils import compute_character_hash
from .character_content_permissions import (
    apply_character_content_creator_permissions,
    load_character_content_creator_map,
)
from ..official_characters import (
    build_official_reference_data,
    char_marks_official_reference,
    extract_official_source_id,
    merge_official_source_into_reference,
)
PUBLIC_PROFILE_FIELDS = (
    "name",
    "avatar",
    "bio",
    "description",
    "preview",
    "profileCover",
    "profilePhotos",
    "profileGender",
    "profileSpecies",
    "profileAge",
    "profilePersonality",
    "profileInterests",
    "profileIntro",
    "profileMbti",
    "tags",
)

_HALL_META_FIELDS = frozenset(
    {
        "id",
        "owner",
        "owner_raw",
        "originalId",
        "sourceId",
        "addedFrom",
        "publishedAt",
        "timesAdded",
        "likeCount",
        "isPublic",
        "lastChatTime",
        "hallId",
        "contentHash",
        "latestSourceContentHash",
        "sourceContentHash",
        "canEdit",
    }
)


def _with_canonical_prompt(data: Dict, prompt) -> Dict:
    """Return character payload with top-level prompt from the canonical column."""
    payload = dict(data or {})
    payload["prompt"] = "" if prompt is None else str(prompt)
    return payload


def _strip_character_data_prompt(data: Dict) -> Dict:
    payload = dict(data or {})
    payload.pop("prompt", None)
    return payload


def _hall_snapshot_from_source(source_data: Dict, source_id: str) -> Dict:
    snapshot = {k: v for k, v in dict(source_data or {}).items() if k not in _HALL_META_FIELDS}
    snapshot["id"] = source_id
    return snapshot


def _merge_source_into_hall_reference(
    *,
    ref_id: str,
    username: str,
    reference_data: Dict,
    source_data: Dict,
    hall_id: str,
    publisher_username: str,
    source_content_hash: str,
) -> Dict:
    ref = dict(reference_data or {})
    source = dict(source_data or {})
    merged = dict(source)
    merged["id"] = ref_id
    merged["owner"] = username
    merged["owner_raw"] = username
    merged["publicOwner"] = publisher_username or ref.get("publicOwner") or ref.get("addedFrom") or ""
    merged["addedFrom"] = publisher_username or ref.get("addedFrom") or ref.get("publicOwner") or ""
    merged["isPublic"] = False
    merged["sourceId"] = hall_id
    merged["originalId"] = hall_id
    merged["canEdit"] = False
    merged["sourceContentHash"] = source_content_hash
    for key in ("lastChatTime",):
        if ref.get(key) not in (None, ""):
            merged[key] = ref.get(key)
    merged.pop("hallId", None)
    merged.pop("publishedAt", None)
    merged.pop("contentHash", None)
    merged.pop("latestSourceContentHash", None)
    return merged


class CharactersDAO:
    """角色数据访问对象"""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def save_characters(
        self,
        username: str,
        characters: List[Dict]
    ) -> bool:
        """
        保存角色列表到数据库
        
        参数：
            username: 用户名
            characters: 角色列表
            
        返回：
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                await conn.execute("PRAGMA busy_timeout = 5000")
                user_id = await self.db._get_user_id(conn, username)
                is_system_owner = (username or "").strip().lower() == "system"
                saved_source_ids: set[str] = set()
                
                # 🔧 [事务保护] 批量插入使用显式事务，确保原子性
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    existing_chars: Dict[str, Dict] = {}
                    existing_official_refs: Dict[str, Dict] = {}
                    existing_official_sources: set[str] = set()
                    incoming_ids = [c.get("id") for c in characters if c.get("id")]
                    if incoming_ids:
                        placeholders = ",".join("?" for _ in incoming_ids)
                        async with conn.execute(
                            f"""SELECT id, data, prompt, official_source_id,
                                      COALESCE(is_official_reference, 0),
                                      official_content_hash_at_link,
                                      COALESCE(is_official_source, 0)
                               FROM characters
                               WHERE user_id = ? AND id IN ({placeholders})""",
                            (user_id, *incoming_ids),
                        ) as cursor:
                            for row in await cursor.fetchall():
                                try:
                                    existing_char = json.loads(row[1]) if row[1] else {}
                                    if isinstance(existing_char, dict):
                                        existing_char = _with_canonical_prompt(existing_char, row[2])
                                        existing_chars[row[0]] = existing_char
                                    if int(row[4] or 0) == 1 and row[3]:
                                        existing_official_refs[row[0]] = {
                                            "data": existing_char if isinstance(existing_char, dict) else {},
                                            "official_source_id": row[3],
                                            "official_content_hash_at_link": row[5],
                                        }
                                    if int(row[6] or 0) == 1:
                                        existing_official_sources.add(row[0])
                                except Exception:
                                    continue

                    source_cache: Dict[str, Dict] = {}
                    creator_map = await load_character_content_creator_map(conn)

                    async def load_official_source(source_id: str) -> Dict:
                        if not source_id:
                            return {}
                        if source_id in source_cache:
                            return source_cache[source_id]
                        async with conn.execute(
                            "SELECT data, prompt FROM characters WHERE id = ? AND COALESCE(is_official_source, 0) = 1",
                            (source_id,),
                        ) as source_cursor:
                            source_row = await source_cursor.fetchone()
                        source_data: Dict = {}
                        if source_row and source_row[0]:
                            try:
                                parsed = json.loads(source_row[0])
                                if isinstance(parsed, dict):
                                    source_data = parsed
                            except Exception:
                                source_data = {}
                        if source_row:
                            source_data = _with_canonical_prompt(source_data, source_row[1])
                        source_cache[source_id] = source_data
                        return source_data

                    for idx, char in enumerate(characters):
                        if not isinstance(char, dict):
                            continue
                        char = dict(char)
                        char_id = char.get('id')
                        if not char_id:
                            continue
                        saved_source_ids.add(str(char_id))
                        existing_char = existing_chars.get(char_id)
                        if existing_char and not is_system_owner:
                            try:
                                old_hash = compute_character_hash(existing_char)
                            except Exception:
                                old_hash = ""
                            creator = str((creator_map.get(old_hash) or {}).get("creator") or "").strip()
                            if creator and creator.lower() != (username or "").strip().lower():
                                char = dict(existing_char)

                        existing_ref = existing_official_refs.get(char_id)
                        official_source_id = (
                            extract_official_source_id(char)
                            or (existing_ref or {}).get("official_source_id")
                        )
                        is_official_reference = bool(existing_ref) or char_marks_official_reference(char)
                        if is_official_reference and official_source_id:
                            source_data = await load_official_source(official_source_id)
                            source_hash = compute_character_hash(source_data) if source_data else None
                            ref_data = build_official_reference_data(
                                ref_id=char_id,
                                source_id=official_source_id,
                                username=username,
                                source_data=source_data,
                                existing_data=(existing_ref or {}).get("data") or char,
                                hall_id=char.get("sourceId") or char.get("originalId"),
                                source_content_hash=(
                                    source_hash
                                    or (existing_ref or {}).get("official_content_hash_at_link")
                                    or char.get("sourceContentHash")
                                ),
                            )
                            name = ref_data.get("name", "未命名角色")
                            avatar = ref_data.get("avatar")
                            prompt = ""
                            bio = ref_data.get("bio", "")
                            data_json = json.dumps(_strip_character_data_prompt(ref_data), ensure_ascii=False)
                            sort_order = idx
                            await conn.execute(
                                """INSERT INTO characters
                                   (id, user_id, name, avatar, prompt, bio, data, sort_order,
                                    memory_identity_profile, official_source_id, is_official_reference,
                                    is_official_source, official_content_hash_at_link,
                                    is_hidden, hidden_at, hidden_reason, updated_at)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, 0, ?, 0, NULL, NULL, CURRENT_TIMESTAMP)
                                   ON CONFLICT(id) DO UPDATE SET
                                       user_id = excluded.user_id,
                                       name = excluded.name,
                                       avatar = excluded.avatar,
                                       prompt = excluded.prompt,
                                       bio = excluded.bio,
                                       data = excluded.data,
                                       sort_order = excluded.sort_order,
                                       official_source_id = excluded.official_source_id,
                                       is_official_reference = 1,
                                       is_official_source = 0,
                                       official_content_hash_at_link = excluded.official_content_hash_at_link,
                                       is_hidden = 0,
                                       hidden_at = NULL,
                                       hidden_reason = NULL,
                                       updated_at = CURRENT_TIMESTAMP""",
                                (
                                    char_id,
                                    user_id,
                                    name,
                                    avatar,
                                    prompt,
                                    bio,
                                    data_json,
                                    sort_order,
                                    official_source_id,
                                    source_hash or char.get("sourceContentHash"),
                                ),
                            )
                            continue

                        name = char.get('name', '未命名角色')
                        avatar = char.get('avatar')
                        prompt = char.get('prompt', char.get('persona', ''))
                        char["prompt"] = "" if prompt is None else str(prompt)
                        bio = char.get('bio', '')
                        if is_system_owner:
                            char["isOfficialSource"] = True
                            char["canEdit"] = True
                            char["owner"] = "System"
                            char["owner_raw"] = "System"
                        data_json = json.dumps(_strip_character_data_prompt(char), ensure_ascii=False)
                        sort_order = idx
                        is_official_source_value = 1 if (
                            is_system_owner or char.get("isOfficialSource") is True or char_id in existing_official_sources
                        ) else 0
                        
                        # 关键：不能使用 INSERT OR REPLACE。
                        # REPLACE 会先 DELETE 再 INSERT，触发 conversations/messages 外键级联删除，
                        # 导致“历史对话列表始终只剩当前一条”。
                        await conn.execute(
                            """INSERT INTO characters
                               (id, user_id, name, avatar, prompt, bio, data, sort_order,
                                memory_identity_profile, official_source_id, is_official_reference,
                                is_official_source, official_content_hash_at_link,
                                is_hidden, hidden_at, hidden_reason, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, NULL, 0, NULL, NULL, CURRENT_TIMESTAMP)
                               ON CONFLICT(id) DO UPDATE SET
                                   user_id = excluded.user_id,
                                   name = excluded.name,
                                   avatar = excluded.avatar,
                                   prompt = excluded.prompt,
                                   bio = excluded.bio,
                                   data = excluded.data,
                                   sort_order = excluded.sort_order,
                                   memory_identity_profile = excluded.memory_identity_profile,
                                   official_source_id = NULL,
                                   is_official_reference = 0,
                                   is_official_source = excluded.is_official_source,
                                   official_content_hash_at_link = NULL,
                                   is_hidden = 0,
                                   hidden_at = NULL,
                                   hidden_reason = NULL,
                                   updated_at = CURRENT_TIMESTAMP""",
                            (char_id, user_id, name, avatar, prompt, bio, data_json, sort_order, None, is_official_source_value)
                        )

                    if saved_source_ids:
                        await self._sync_published_sources_locked(conn, saved_source_ids)
                    
                    await conn.execute("COMMIT")
                except Exception:
                    await conn.execute("ROLLBACK")
                    raise
                
                logger.debug(f"💾 [DB] 保存角色: {username} ({len(characters)} 个角色)")
                return True
                
        except Exception as e:
            err_msg = str(e)
            logger.error(f"❌ [DB] 保存角色失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # 🛡️ [数据库损坏] 提示从备份恢复
            if "malformed" in err_msg.lower() or "disk image" in err_msg.lower():
                logger.critical(
                    "⚠️ [DB] 数据库文件已损坏 (database disk image is malformed)。"
                    "请先停止后端，运行: python scripts/ops/restore_db_from_backup.py ，再重启后端。"
                )
                return False

    async def _sync_published_sources_locked(self, conn, source_ids: set[str]) -> int:
        """Sync published source characters to hall rows and all reference entries."""
        if not source_ids:
            return 0
        synced = 0
        placeholders = ",".join("?" for _ in source_ids)
        async with conn.execute(
            f"""SELECT h.id, h.source_character_id, h.publisher_username,
                       c.data, c.prompt, c.name, c.avatar
                FROM hall_characters h
                JOIN characters c ON c.id = h.source_character_id
                WHERE h.source_character_id IN ({placeholders})""",
            tuple(source_ids),
        ) as cur:
            hall_rows = await cur.fetchall()

        for hall_id, source_id, publisher_username, source_json, source_prompt, source_name, source_avatar in hall_rows:
            try:
                source_data = json.loads(source_json) if source_json else {}
                if not isinstance(source_data, dict):
                    source_data = {}
            except Exception:
                source_data = {}
            source_data = _with_canonical_prompt(source_data, source_prompt)
            source_data["id"] = source_id
            source_data.setdefault("name", source_name or "未命名角色")
            if source_avatar and not source_data.get("avatar"):
                source_data["avatar"] = source_avatar

            source_hash = compute_character_hash(source_data)
            hall_snapshot = _hall_snapshot_from_source(source_data, str(source_id))
            await conn.execute(
                """UPDATE hall_characters
                   SET name = ?, avatar = ?, content_hash = ?, data = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (
                    source_data.get("name") or source_name or "未命名角色",
                    source_data.get("avatar") or source_avatar,
                    source_hash,
                    json.dumps(hall_snapshot, ensure_ascii=False),
                    hall_id,
                ),
            )
            synced += 1

            like_pattern = f"{source_id}__u_%"
            async with conn.execute(
                """SELECT c.id, c.user_id, u.username, c.data,
                          c.official_source_id, COALESCE(c.is_official_reference, 0)
                   FROM characters c
                   JOIN users u ON u.id = c.user_id
                   WHERE c.id != ?
                     AND (
                         c.id LIKE ?
                         OR c.official_source_id = ?
                         OR c.data LIKE ?
                     )""",
                (source_id, like_pattern, source_id, f"%{hall_id}%"),
            ) as ref_cur:
                ref_rows = await ref_cur.fetchall()

            for ref_id, ref_user_id, ref_username, ref_json, official_source_id, is_official_reference in ref_rows:
                try:
                    ref_data = json.loads(ref_json) if ref_json else {}
                    if not isinstance(ref_data, dict):
                        ref_data = {}
                except Exception:
                    ref_data = {}

                is_official_ref = bool(is_official_reference) and str(official_source_id or "") == str(source_id)
                is_hall_ref = (
                    str(ref_data.get("sourceId") or "").strip() == str(hall_id)
                    or str(ref_data.get("originalId") or "").strip() == str(hall_id)
                )
                is_local_ref = str(ref_id or "").startswith(f"{source_id}__u_")
                if not (is_official_ref or is_hall_ref or is_local_ref):
                    continue

                if is_official_ref:
                    merged = merge_official_source_into_reference(
                        reference_id=str(ref_id),
                        source_id=str(source_id),
                        reference_data=ref_data,
                        source_data=source_data,
                        username=str(ref_username or ""),
                    )
                    merged["sourceContentHash"] = source_hash
                    new_official_source_id = str(source_id)
                    new_is_official_reference = 1
                    new_hash = source_hash
                else:
                    merged = _merge_source_into_hall_reference(
                        ref_id=str(ref_id),
                        username=str(ref_username or ""),
                        reference_data=ref_data,
                        source_data=source_data,
                        hall_id=str(hall_id),
                        publisher_username=str(publisher_username or ""),
                        source_content_hash=source_hash,
                    )
                    new_official_source_id = None
                    new_is_official_reference = 0
                    new_hash = None

                await conn.execute(
                    """UPDATE characters
                       SET name = ?, avatar = ?, prompt = ?, bio = ?, data = ?,
                           official_source_id = ?, is_official_reference = ?,
                           is_official_source = 0,
                           official_content_hash_at_link = ?,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND user_id = ?""",
                    (
                        merged.get("name") or source_data.get("name") or "未命名角色",
                        merged.get("avatar") or source_data.get("avatar"),
                        "" if is_official_ref else (merged.get("prompt") or ""),
                        merged.get("bio") or merged.get("description") or "",
                        json.dumps(_strip_character_data_prompt(merged), ensure_ascii=False),
                        new_official_source_id,
                        new_is_official_reference,
                        new_hash,
                        ref_id,
                        ref_user_id,
                    ),
                )
                synced += 1
        if synced:
            logger.info("🔄 [DB] 已自动同步公开源角色及引用: sources=%s rows=%s", len(source_ids), synced)
        return synced
    
    async def load_characters(
        self,
        username: str
    ) -> List[Dict]:
        """
        加载用户的所有角色
        
        参数：
            username: 用户名
            
        返回：
            角色列表
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                user_id = await self.db._get_user_id(conn, username)
                display_username = username
                try:
                    async with conn.execute(
                        "SELECT settings FROM user_settings WHERE user_id = ?",
                        (user_id,),
                    ) as settings_cursor:
                        settings_row = await settings_cursor.fetchone()
                    if settings_row and settings_row[0]:
                        settings = json.loads(settings_row[0])
                        nickname = str((settings or {}).get("nickname") or "").strip()
                        if nickname:
                            display_username = nickname
                except Exception:
                    display_username = username
                
                characters = []
                repaired = 0
                skipped = 0
                # 🔧 [排序修复] 按 sort_order ASC 保持用户拖拽顺序；无 sort_order 的旧数据排在后面
                # 同时联查 conversations 表获取该角色的最近对话时间（lastChatTime）
                async with conn.execute(
                    """SELECT c.id, c.name, c.avatar, c.prompt, c.data,
                              c.official_source_id,
                              COALESCE(c.is_official_reference, 0),
                              COALESCE(c.is_official_source, 0),
                              c.official_content_hash_at_link,
                              (SELECT MAX(conv.updated_at)
                               FROM conversations conv
                               WHERE conv.character_id = c.id
                                 AND conv.user_id = c.user_id
                                 AND COALESCE(conv.is_hidden, 0) = 0) as last_chat_time
                       FROM characters c
                       WHERE c.user_id = ? AND COALESCE(c.is_hidden, 0) = 0
                       ORDER BY COALESCE(c.sort_order, 999999) ASC, c.updated_at ASC""",
                    (user_id,)
                ) as cursor:
                    rows = await cursor.fetchall()
                creator_map = await load_character_content_creator_map(conn)

                source_cache: Dict[str, Dict] = {}

                async def load_official_source(source_id: str) -> Dict:
                    if not source_id:
                        return {}
                    if source_id in source_cache:
                        return source_cache[source_id]
                    async with conn.execute(
                        "SELECT data, prompt FROM characters WHERE id = ? AND COALESCE(is_official_source, 0) = 1",
                        (source_id,),
                    ) as source_cursor:
                        source_row = await source_cursor.fetchone()
                    source_data: Dict = {}
                    if source_row and source_row[0]:
                        try:
                            parsed = json.loads(source_row[0])
                            if isinstance(parsed, dict):
                                source_data = parsed
                        except Exception:
                            source_data = {}
                    if source_row:
                        source_data = _with_canonical_prompt(source_data, source_row[1])
                    source_cache[source_id] = source_data
                    return source_data

                hall_source_cache: Dict[str, Dict] = {}

                async def load_hall_public_source(hall_id: str) -> Dict:
                    if not hall_id:
                        return {}
                    if hall_id in hall_source_cache:
                        return hall_source_cache[hall_id]
                    async with conn.execute(
                        """SELECT publisher_username, content_hash, data,
                                  published_at, updated_at, times_added,
                                  COALESCE(like_count, 0)
                           FROM hall_characters
                           WHERE id = ?
                           LIMIT 1""",
                        (hall_id,),
                    ) as hall_cursor:
                        hall_row = await hall_cursor.fetchone()
                    hall_data: Dict = {}
                    if hall_row and hall_row[2]:
                        try:
                            parsed = json.loads(hall_row[2])
                            if isinstance(parsed, dict):
                                hall_data = parsed
                                hall_data["owner"] = hall_row[0]
                                hall_data["owner_raw"] = hall_row[0]
                                hall_data["contentHash"] = hall_row[1]
                                hall_data["publishedAt"] = hall_row[3]
                                hall_data["updatedAt"] = hall_row[4]
                                hall_data["timesAdded"] = int(hall_row[5] or 0)
                                hall_data["likeCount"] = int(hall_row[6] or 0)
                        except Exception:
                            hall_data = {}
                    hall_source_cache[hall_id] = hall_data
                    return hall_data

                def merge_hall_public_profile(local_char: Dict, hall_data: Dict) -> Dict:
                    if not hall_data:
                        return local_char
                    merged = dict(local_char)
                    for key in PUBLIC_PROFILE_FIELDS:
                        if key in hall_data:
                            merged[key] = hall_data.get(key)
                    for key in ("publishedAt", "updatedAt", "timesAdded", "likeCount"):
                        if key in hall_data:
                            merged[key] = hall_data.get(key)
                    if hall_data.get("owner_raw") or hall_data.get("owner"):
                        merged["publicOwner"] = hall_data.get("owner_raw") or hall_data.get("owner")
                    if hall_data.get("contentHash"):
                        merged["latestSourceContentHash"] = hall_data.get("contentHash")
                    return merged

                for row in rows:
                        db_id, db_name, db_avatar, db_prompt, data_json, official_source_id, is_official_reference, is_official_source, official_hash_at_link, last_chat_time = row
                        try:
                            char = json.loads(data_json)
                            
                            # 🛡️ [数据校验] 跳过没有 id 的无效角色
                            if not char.get('id'):
                                skipped += 1
                                logger.warning(f"⚠️ [DB] 跳过无效角色: db_id={db_id}, 缺少 id 字段")
                                continue
                            if int(is_official_reference or 0) == 1 and official_source_id:
                                source_data = await load_official_source(str(official_source_id))
                                if source_data:
                                    char = merge_official_source_into_reference(
                                        reference_id=db_id,
                                        source_id=str(official_source_id),
                                        reference_data=char,
                                        source_data=source_data,
                                        username=username,
                                    )
                                    if official_hash_at_link:
                                        char["sourceContentHash"] = official_hash_at_link
                            elif int(is_official_source or 0) != 1:
                                is_hall_reference = bool(str(char.get("sourceId") or "").strip())
                                hall_id = (
                                    char.get("sourceId")
                                    or char.get("originalId")
                                    or char.get("hallId")
                                    or ""
                                )
                                if hall_id:
                                    hall_data = await load_hall_public_source(str(hall_id))
                                    if is_hall_reference:
                                        char = _merge_source_into_hall_reference(
                                            ref_id=db_id,
                                            username=username,
                                            reference_data=char,
                                            source_data=hall_data,
                                            hall_id=str(hall_id),
                                            publisher_username=str(hall_data.get("owner_raw") or hall_data.get("owner") or ""),
                                            source_content_hash=str(hall_data.get("contentHash") or ""),
                                        )
                                    else:
                                        char = merge_hall_public_profile(char, hall_data)
                            # 🔧 [根因修复] 以表主键 id 为唯一真相源，避免 data JSON 中存了短 id/旧 id 导致前端用错 key 参与同步
                            if char.get('id') != db_id:
                                logger.debug(f"📎 [DB] 角色 id 统一为表主键: data 中 {char.get('id', '')[:12]}... → 表 id {db_id[:12]}...")
                                char['id'] = db_id
                            if int(is_official_reference or 0) != 1:
                                char = _with_canonical_prompt(char, db_prompt)
                            # 🔧 [自动修复] 如果 data JSON 中缺少 name，从 DB 列中恢复返回值。
                            # 读取角色列表时不要顺手写库；否则 App 刷列表会和聊天/语音写入抢 SQLite 写锁。
                            if not char.get('name'):
                                repaired += 1
                                fallback_name = db_name or char.get('bio') or char.get('preview') or '未命名角色'
                                char['name'] = fallback_name
                                logger.warning(f"⚠️ [DB] 修复角色缺失 name: id={db_id[:12]}... → name={fallback_name}")
                            
                            # 注入最近对话时间供客户端排序
                            char['lastChatTime'] = last_chat_time
                            if int(is_official_source or 0) == 1:
                                char["isOfficialSource"] = True
                                char["canEdit"] = True
                            elif not char.get("sourceId") and not char.get("officialSourceId"):
                                char["owner"] = username
                                char["owner_raw"] = username
                                char["publicOwner"] = display_username
                                char["addedFrom"] = display_username
                            # 注入内容哈希，供大厅「已添加」判断
                            char['contentHash'] = compute_character_hash(char)
                            characters.append(char)
                        except Exception as e:
                            skipped += 1
                            logger.warning(f"⚠️ [DB] 解析角色数据失败: id={db_id}, error={e}")
                
                if repaired > 0:
                    logger.info(f"🔧 [DB] 本次读取补全了 {repaired} 个角色的缺失 name 字段（未写库）")
                if skipped > 0:
                    logger.warning(f"⚠️ [DB] 跳过了 {skipped} 个无效角色记录")
                
                # 🔧 [角色大厅去重] 同一 originalId 只保留列表中第一条，避免多端重复添加导致「两个入口、数据分散」
                seen_original_ids = set()
                deduped = []
                for char in characters:
                    oid = char.get('originalId')
                    if oid:
                        if oid in seen_original_ids:
                            logger.debug(f"📎 [DB] 角色大厅去重: 跳过重复 originalId={oid[:12]}... (保留列表中第一条)")
                            continue
                        seen_original_ids.add(oid)
                    deduped.append(char)
                characters = deduped
                apply_character_content_creator_permissions(
                    characters,
                    creator_map,
                    current_username=username,
                )
                
                logger.debug(f"📥 [DB] 加载角色: {username} ({len(characters)} 个角色)")
                return characters
                
        except Exception as e:
            logger.error(f"❌ [DB] 加载角色失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    async def delete_character(
        self,
        username: str,
        char_id: str
    ) -> bool:
        """
        软删除角色（仅从用户角色列表隐藏，不物理删除）
        
        参数：
            username: 用户名
            char_id: 角色ID
            
        返回：
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                user_id = await self.db._get_user_id(conn, username)
                
                # 🛡️ [软删除] 用户删除角色时仅隐藏，保留对话/Galgame等历史数据供后台恢复
                await conn.execute(
                    """UPDATE characters
                       SET is_hidden = 1,
                           hidden_at = CURRENT_TIMESTAMP,
                           hidden_reason = 'user_remove_from_list',
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND user_id = ?""",
                    (char_id, user_id)
                )
                await conn.commit()
                
                logger.info(f"🗑️ [DB] 删除角色: {char_id[:8]}...")
                return True
                
        except Exception as e:
            logger.error(f"❌ [DB] 删除角色失败: {e}")
            return False

    async def migrate_enable_jailbreak_for_all_users(self) -> int:
        """
        一次性迁移：将所有用户的所有角色 jailbreak 打开。

        返回：
            实际被更新的角色数量
        """
        updated_count = 0
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                async with conn.execute("SELECT id, data FROM characters") as cursor:
                    async for row in cursor:
                        char_id, data_json = row
                        try:
                            char = json.loads(data_json) if data_json else {}
                            if not isinstance(char, dict):
                                continue
                            if char.get("jailbreak") is True:
                                continue
                            char["jailbreak"] = True
                            fixed_json = json.dumps(_strip_character_data_prompt(char), ensure_ascii=False)
                            await conn.execute(
                                "UPDATE characters SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (fixed_json, char_id)
                            )
                            updated_count += 1
                        except Exception as item_err:
                            logger.warning(f"⚠️ [DB] 跳过迁移异常角色: id={char_id}, err={item_err}")
                await conn.commit()
            if updated_count > 0:
                logger.info(f"🔓 [Jailbreak-Migration] 已开启 {updated_count} 个角色的破限开关")
            else:
                logger.info("🔓 [Jailbreak-Migration] 无需更新，所有角色已开启破限")
        except Exception as e:
            logger.error(f"❌ [Jailbreak-Migration] 迁移失败: {e}")
            return 0
        return updated_count
