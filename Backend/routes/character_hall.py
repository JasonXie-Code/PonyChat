"""
角色大厅 API（重构版）

设计原则：
  - hall_characters 表是公开入口与快照索引；source_character_id 指向创建者手中的源角色
  - 内容哈希（content_hash）用于：
      1. 大厅去重：不允许两条大厅条目内容完全相同
      2. "已添加"判断：用户本地任意一个角色哈希与大厅条目哈希相同则视为已添加
  - 发布/编辑/删除 操作源角色与大厅入口；源角色保存后服务端自动同步引用者
  - 添加：将大厅条目复制为用户引用，ID 使用 源角色ID__u_用户ID，冲突时追加序号
"""
from fastapi import APIRouter, HTTPException, Query, Header, Body
from typing import Optional
import json
import uuid
from datetime import date, datetime

from ..config import logger
from ..utils import load_users_async, compute_character_hash
from ..official_characters import (
    build_official_reference_data,
    make_official_reference_id,
)

from ..db import get_database, CharactersDAO, get_users_dao
from ..websocket import galgame_locker

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# 身份校验辅助
# ---------------------------------------------------------------------------

async def _validate_username(username: str, x_username: Optional[str]) -> str:
    normalized = (username or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Missing username")
    if x_username and x_username.strip() and x_username.strip() != normalized:
        raise HTTPException(status_code=403, detail="Username mismatch")
    users_dao = get_users_dao()
    if not await users_dao.user_exists(normalized):
        raise HTTPException(status_code=401, detail="User not found")
    return normalized


async def _is_official_source_character(conn, source_character_id: str) -> bool:
    source_id = str(source_character_id or "").strip()
    if not source_id:
        return False
    async with conn.execute(
        """SELECT COALESCE(c.is_official_source, 0), u.username
           FROM characters c
           JOIN users u ON u.id = c.user_id
           WHERE c.id = ?
           LIMIT 1""",
        (source_id,),
    ) as cur:
        row = await cur.fetchone()
    return bool(row and (int(row[0] or 0) == 1 or row[1] == "System"))


async def _make_unique_reference_id(conn, base_id: str) -> str:
    base = str(base_id or "").strip() or str(uuid.uuid4())
    candidate = base
    suffix = 2
    while True:
        async with conn.execute("SELECT 1 FROM characters WHERE id = ? LIMIT 1", (candidate,)) as cur:
            if not await cur.fetchone():
                return candidate
        candidate = f"{base}_{suffix}"
        suffix += 1


async def _liked_today(conn, hall_id: str, username: str, like_date: str) -> bool:
    if not username:
        return False
    async with conn.execute(
        """SELECT 1 FROM hall_character_likes
           WHERE hall_id = ? AND username = ? AND like_date = ?
           LIMIT 1""",
        (hall_id, username, like_date),
    ) as cur:
        return await cur.fetchone() is not None


# ---------------------------------------------------------------------------
# GET /api/character-hall  —— 获取大厅列表
# ---------------------------------------------------------------------------

@router.get("/character-hall")
async def get_character_hall(
    search: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
):
    """获取角色大厅列表，每条记录含 contentHash 供客户端做「已添加」判断。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()
        users = await load_users_async()

        results = []
        async with aiosqlite.connect(db.db_path) as conn:
            hall_reference_counts: dict[str, int] = {}
            official_reference_counts: dict[str, int] = {}
            async with conn.execute(
                """SELECT c.data,
                          c.official_source_id,
                          COALESCE(c.is_official_reference, 0)
                   FROM characters c
                   JOIN users u ON u.id = c.user_id
                   WHERE COALESCE(c.is_hidden, 0) = 0
                     AND u.username != 'System'"""
            ) as ref_cursor:
                async for ref_row in ref_cursor:
                    data_json, official_source_id, is_official_reference = ref_row
                    official_source_id = str(official_source_id or "").strip()
                    if official_source_id and int(is_official_reference or 0) == 1:
                        official_reference_counts[official_source_id] = official_reference_counts.get(official_source_id, 0) + 1
                    try:
                        ref_data = json.loads(data_json) if data_json else {}
                    except Exception:
                        ref_data = {}
                    if isinstance(ref_data, dict):
                        hall_ref_id = str(ref_data.get("sourceId") or ref_data.get("originalId") or "").strip()
                        if hall_ref_id:
                            hall_reference_counts[hall_ref_id] = hall_reference_counts.get(hall_ref_id, 0) + 1

            async with conn.execute(
                "SELECT id, publisher_username, name, avatar, content_hash, data, "
                "       published_at, updated_at, times_added, COALESCE(like_count, 0) "
                "       , source_character_id "
                "FROM hall_characters "
                "ORDER BY published_at DESC"
            ) as cursor:
                async for row in cursor:
                    (hid, pub_user, name, avatar, content_hash,
                     data_json, published_at, updated_at, times_added, like_count, source_character_id) = row
                    try:
                        char = json.loads(data_json)
                    except Exception:
                        continue

                    reference_count = hall_reference_counts.get(str(hid), 0)
                    source_id = str(source_character_id or "").strip()
                    if source_id:
                        reference_count = max(reference_count, official_reference_counts.get(source_id, 0))

                    # 将大厅元数据注入 char 字典
                    char['id'] = hid
                    char['contentHash'] = content_hash
                    char['publishedAt'] = published_at
                    char['updatedAt'] = updated_at
                    char['timesAdded'] = max(int(times_added or 0), int(reference_count or 0))
                    char['likeCount'] = like_count or 0
                    char['likedToday'] = await _liked_today(
                        conn,
                        hid,
                        (username or "").strip(),
                        date.today().isoformat(),
                    )

                    # 发布者显示信息
                    user_info = users.get(pub_user, {})
                    species_preset = user_info.get("species_preset", "人类")
                    species_custom = user_info.get("species_custom", "")
                    species_cn = species_custom if species_custom else species_preset
                    char['owner'] = pub_user
                    char['owner_raw'] = pub_user
                    char['isCertified'] = str(pub_user or "").strip().lower() == "system"

                    # 搜索过滤
                    if search:
                        sl = search.lower()
                        if not (
                            sl in (char.get('name') or '').lower() or
                            sl in (char.get('description') or '').lower() or
                            sl in (char.get('bio') or '').lower() or
                            sl in pub_user.lower() or
                            sl in species_cn.lower()
                        ):
                            continue

                    results.append(char)

        logger.info(f"📚 角色大厅: 返回 {len(results)} 个公开角色")
        return results

    except Exception as e:
        logger.error(f"获取角色大厅失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/character-hall/{hall_id}/likes  —— 点赞统计
# ---------------------------------------------------------------------------

@router.get("/character-hall/{hall_id}/likes")
async def get_hall_character_likes(
    hall_id: str,
    username: str = Query(...),
    x_username: Optional[str] = Header(None),
):
    """返回大厅角色真实点赞数，以及当前用户今天是否已经点过。"""
    try:
        username = await _validate_username(username, x_username)
        db = get_database()
        await db.init()

        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT COALESCE(like_count, 0) FROM hall_characters WHERE id = ?",
                (hall_id,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Hall entry not found")

            today = date.today().isoformat()
            liked = await _liked_today(conn, hall_id, username, today)
            return {
                "status": "success",
                "likeCount": int(row[0] or 0),
                "likedToday": liked,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取大厅角色点赞失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /api/character-hall/{hall_id}/like  —— 点赞（每天一次）
# ---------------------------------------------------------------------------

@router.post("/character-hall/{hall_id}/like")
async def like_hall_character(
    hall_id: str,
    username: str = Query(...),
    x_username: Optional[str] = Header(None),
):
    """给大厅角色点赞。数据库主键校验同一用户同一天只能成功一次。"""
    try:
        username = await _validate_username(username, x_username)
        db = get_database()
        await db.init()

        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT COALESCE(like_count, 0) FROM hall_characters WHERE id = ?",
                (hall_id,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Hall entry not found")

            today = date.today().isoformat()
            insert_cur = await conn.execute(
                """INSERT OR IGNORE INTO hall_character_likes
                   (hall_id, username, like_date, created_at)
                   VALUES (?, ?, ?, ?)""",
                (hall_id, username, today, datetime.now().isoformat()),
            )
            if insert_cur.rowcount == 0:
                return {
                    "status": "already_liked",
                    "message": "请明天再试",
                    "likeCount": int(row[0] or 0),
                    "likedToday": True,
                }

            await conn.execute(
                """UPDATE hall_characters
                   SET like_count = COALESCE(like_count, 0) + 1
                   WHERE id = ?""",
                (hall_id,),
            )
            async with conn.execute(
                "SELECT COALESCE(like_count, 0) FROM hall_characters WHERE id = ?",
                (hall_id,),
            ) as cur:
                updated = await cur.fetchone()
            await conn.commit()

            like_count = int((updated or row)[0] or 0)
            logger.info(f"💗 用户 {username} 点赞大厅角色: hallId={hall_id} count={like_count}")
            return {
                "status": "success",
                "message": "已喜欢",
                "likeCount": like_count,
                "likedToday": True,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"大厅角色点赞失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /api/characters/{character_id}/publish  —— 发布到大厅
# ---------------------------------------------------------------------------

@router.post("/characters/{character_id}/publish")
async def publish_character(
    character_id: str,
    username: str = Query(...),
    x_username: Optional[str] = Header(None)
):
    """将用户列表里的角色发布到大厅（大厅存独立副本）。"""
    try:
        username = await _validate_username(username, x_username)
        db = get_database()
        await db.init()
        chars_dao = CharactersDAO(db)
        all_chars = await chars_dao.load_characters(username)
        char = next((c for c in all_chars if c.get('id') == character_id), None)
        if not char:
            raise HTTPException(status_code=404, detail="Character not found")
        if char.get("canEdit") is False:
            raise HTTPException(status_code=403, detail="not_character_creator")

        content_hash = compute_character_hash(char)

        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            # 检查此用户是否已经发布过该角色（同一 source_character_id）
            async with conn.execute(
                "SELECT id FROM hall_characters "
                "WHERE source_character_id = ? AND publisher_username = ?",
                (character_id, username)
            ) as cur:
                existing_own = await cur.fetchone()
            if existing_own:
                raise HTTPException(
                    status_code=400,
                    detail="already_published"
                )

            # 检查大厅内容去重（任何人发布的完全相同内容）
            async with conn.execute(
                "SELECT id FROM hall_characters WHERE content_hash = ?",
                (content_hash,)
            ) as cur:
                dup = await cur.fetchone()
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail="duplicate_content"
                )

            # 构建大厅存储的内容 JSON（排除元数据字段）
            META_FIELDS = {'id', 'owner', 'owner_raw', 'originalId', 'sourceId',
                           'addedFrom', 'publishedAt', 'timesAdded', 'isPublic',
                           'lastChatTime', 'hallId', 'contentHash'}
            hall_data = {k: v for k, v in char.items() if k not in META_FIELDS}

            hall_id = str(uuid.uuid4())
            now = datetime.now().isoformat()
            await conn.execute(
                """INSERT INTO hall_characters
                   (id, source_character_id, publisher_username, name, avatar,
                    content_hash, data, published_at, updated_at, times_added)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (hall_id, character_id, username,
                 char.get('name', '未命名'), char.get('avatar'),
                 content_hash,
                 json.dumps(hall_data, ensure_ascii=False),
                 now, now)
            )
            await conn.commit()

        # 同步更新用户自己角色列表里的 isPublic/hallId（仅标记，不影响内容）
        updated_char = {**char, 'isPublic': True, 'hallId': hall_id, 'publishedAt': now}
        new_list = [updated_char if c.get('id') == character_id else c for c in all_chars]
        await chars_dao.save_characters(username, new_list)

        logger.info(f"✅ 角色已发布到大厅: {char.get('name', '?')} by {username} (hallId={hall_id})")
        return {
            "message": "角色已发布到大厅",
            "hallId": hall_id,
            "contentHash": content_hash
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"发布角色失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# DELETE /api/characters/{character_id}/unpublish  —— 从大厅下架
# ---------------------------------------------------------------------------

@router.delete("/characters/{character_id}/unpublish")
async def unpublish_character(
    character_id: str,
    username: str = Query(...),
    x_username: Optional[str] = Header(None)
):
    """从大厅下架（删除 hall_characters 条目），用户自己的角色列表不受影响。"""
    try:
        username = await _validate_username(username, x_username)
        db = get_database()
        await db.init()

        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            # 支持两种方式定位：source_character_id 或 hall entry id
            async with conn.execute(
                """SELECT id FROM hall_characters
                   WHERE publisher_username = ?
                     AND (source_character_id = ? OR id = ?)""",
                (username, character_id, character_id)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Hall entry not found")

            hall_id = row[0]
            await conn.execute("DELETE FROM hall_characters WHERE id = ?", (hall_id,))
            await conn.commit()

        # 清除用户角色列表里的 isPublic/hallId 标记
        chars_dao = CharactersDAO(db)
        all_chars = await chars_dao.load_characters(username)
        updated = False
        new_list = []
        for c in all_chars:
            if c.get('hallId') == hall_id or c.get('id') == character_id:
                new_list.append({**c, 'isPublic': False, 'hallId': None, 'publishedAt': None})
                updated = True
            else:
                new_list.append(c)
        if updated:
            await chars_dao.save_characters(username, new_list)

        logger.info(f"✅ 已取消发布: hallId={hall_id} by {username}")
        return {"message": "已从大厅下架"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消发布失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# PUT /api/character-hall/{hall_id}  —— 编辑大厅条目
# ---------------------------------------------------------------------------

@router.put("/character-hall/{hall_id}")
async def edit_hall_character(
    hall_id: str,
    username: str = Query(...),
    x_username: Optional[str] = Header(None),
    body: dict = Body(...)
):
    """发布者编辑大厅里的角色内容（独立版本，不影响用户自己的角色列表）。"""
    try:
        username = await _validate_username(username, x_username)
        db = get_database()
        await db.init()

        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT publisher_username, data FROM hall_characters WHERE id = ?",
                (hall_id,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Hall entry not found")
            if row[0] != username:
                raise HTTPException(status_code=403, detail="Not the publisher")

            new_content = body.get('character', body)
            META_FIELDS = {'id', 'owner', 'owner_raw', 'originalId', 'sourceId',
                           'addedFrom', 'publishedAt', 'timesAdded', 'isPublic',
                           'lastChatTime', 'hallId', 'contentHash'}
            hall_data = {k: v for k, v in new_content.items() if k not in META_FIELDS}

            new_hash = compute_character_hash(hall_data)

            # 检查新哈希是否与其他大厅条目重复
            async with conn.execute(
                "SELECT id FROM hall_characters WHERE content_hash = ? AND id != ?",
                (new_hash, hall_id)
            ) as cur:
                dup = await cur.fetchone()
            if dup:
                raise HTTPException(status_code=409, detail="duplicate_content")

            now = datetime.now().isoformat()
            await conn.execute(
                """UPDATE hall_characters
                   SET name = ?, avatar = ?, content_hash = ?, data = ?, updated_at = ?
                   WHERE id = ?""",
                (hall_data.get('name', '未命名'), hall_data.get('avatar'),
                 new_hash, json.dumps(hall_data, ensure_ascii=False), now, hall_id)
            )
            await conn.commit()

        logger.info(f"✅ 大厅角色已更新: hallId={hall_id} by {username}")
        return {"message": "大厅角色已更新", "contentHash": new_hash}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"编辑大厅角色失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /api/character-hall/{hall_id}/add  —— 从大厅添加角色
# ---------------------------------------------------------------------------

@router.post("/character-hall/{hall_id}/add")
async def add_character_from_hall(
    hall_id: str,
    username: str = Query(...),
    x_username: Optional[str] = Header(None)
):
    """从大厅添加角色到自己的账户。发布者自己的源角色视为已拥有，不创建额外引用。"""
    try:
        username = await _validate_username(username, x_username)

        async with galgame_locker.acquire(username, "character_hall_add"):
            import aiosqlite
            db = get_database()
            await db.init()

            async with aiosqlite.connect(db.db_path) as conn:
                async with conn.execute(
                    "SELECT publisher_username, name, content_hash, data, times_added, source_character_id "
                    "FROM hall_characters WHERE id = ?",
                    (hall_id,)
                ) as cur:
                    row = await cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Character not found in hall")

                pub_user, name, content_hash, data_json, times_added, source_character_id = row

                hall_data = json.loads(data_json)

                # "已添加"判断：用户列表中是否已有哈希相同的角色
                chars_dao = CharactersDAO(db)
                user_chars = await chars_dao.load_characters(username)

                user_id = await db._get_user_id(conn, username)
                official_source_id = str(source_character_id or "").strip()
                if pub_user == username and official_source_id and any(c.get("id") == official_source_id for c in user_chars):
                    return {"status": "already_exists", "message": "这是你发布的源角色"}
                if await _is_official_source_character(conn, official_source_id):
                    ref_base_id = make_official_reference_id(official_source_id, user_id)
                    async with conn.execute(
                        """SELECT id, COALESCE(is_hidden, 0)
                           FROM characters
                           WHERE user_id = ?
                             AND official_source_id = ?
                             AND COALESCE(is_official_reference, 0) = 1
                           LIMIT 1""",
                        (user_id, official_source_id),
                    ) as ref_cur:
                        existing_ref = await ref_cur.fetchone()
                    if existing_ref:
                        if int(existing_ref[1] or 0) != 0:
                            await conn.execute(
                                """UPDATE characters
                                   SET is_hidden = 0,
                                       hidden_at = NULL,
                                       hidden_reason = NULL,
                                       updated_at = CURRENT_TIMESTAMP
                                   WHERE id = ? AND user_id = ?""",
                                (existing_ref[0], user_id),
                            )
                            await conn.commit()
                            from ..chat_modules.opening_greeting import schedule_opening_greeting

                            schedule_opening_greeting(
                                username,
                                str(existing_ref[0]),
                                source="character_hall_unhide_existing_reference",
                            )
                        return {"status": "already_exists", "message": "已添加官方角色"}

                    ref_id = await _make_unique_reference_id(conn, ref_base_id)
                    ref_char = build_official_reference_data(
                        ref_id=ref_id,
                        source_id=official_source_id,
                        username=username,
                        source_data=hall_data,
                        hall_id=hall_id,
                        source_content_hash=content_hash,
                    )
                    user_chars.append(ref_char)
                    ok = await chars_dao.save_characters(username, user_chars)
                    if not ok:
                        raise HTTPException(status_code=500, detail="Failed to save character")
                    if pub_user != username:
                        await conn.execute(
                            "UPDATE hall_characters SET times_added = ?, updated_at = CURRENT_TIMESTAMP "
                            "WHERE id = ?",
                            ((times_added or 0) + 1, hall_id)
                        )
                    await conn.commit()
                    from ..chat_modules.opening_greeting import schedule_opening_greeting

                    schedule_opening_greeting(
                        username,
                        str(ref_char.get("id") or ""),
                        source="character_hall_add_official_reference",
                    )
                    logger.info(f"✅ 用户 {username} 添加官方引用角色: {name} (source={official_source_id})")
                    return {"status": "success", "message": "官方角色已添加", "character": ref_char}

                from ..utils import compute_character_hash as _hash
                for c in user_chars:
                    if _hash(c) == content_hash:
                        return {"status": "already_exists", "message": "已添加相同角色"}

                new_char = {**hall_data}
                source_for_id = str(source_character_id or "").strip() or str(hall_data.get("id") or hall_id).strip()
                new_char['id'] = await _make_unique_reference_id(
                    conn,
                    make_official_reference_id(source_for_id, user_id),
                )
                new_char['isPublic'] = False
                new_char['originalId'] = hall_id
                new_char['sourceId'] = hall_id
                new_char['owner'] = username
                new_char['owner_raw'] = username
                new_char['addedFrom'] = pub_user
                new_char['canEdit'] = False
                new_char['sourceContentHash'] = content_hash  # 版本快照：用于检测大厅是否有新版本
                new_char.pop('publishedAt', None)
                new_char.pop('hallId', None)
                new_char.pop('contentHash', None)

                user_chars.append(new_char)
                ok = await chars_dao.save_characters(username, user_chars)
                if not ok:
                    raise HTTPException(status_code=500, detail="Failed to save character")

                # 递增被添加次数；作者自添加通常用于误删恢复/复制，不计入大厅热度。
                if pub_user != username:
                    await conn.execute(
                        "UPDATE hall_characters SET times_added = ?, updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = ?",
                        ((times_added or 0) + 1, hall_id)
                    )
                await conn.commit()

            logger.info(f"✅ 用户 {username} 从大厅添加了角色: {name} (hallId={hall_id})")
            from ..chat_modules.opening_greeting import schedule_opening_greeting

            schedule_opening_greeting(
                username,
                str(new_char.get("id") or ""),
                source="character_hall_add",
            )
            return {"status": "success", "message": "角色已添加", "character": new_char}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加角色失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))



# ---------------------------------------------------------------------------
# POST /api/character-hall/{hall_id}/update-local  —— 旧客户端兼容：自动同步后无需手动更新
# ---------------------------------------------------------------------------

@router.post("/character-hall/{hall_id}/update-local")
async def update_local_from_hall(
    hall_id: str,
    username: str = Query(...),
    x_username: Optional[str] = Header(None)
):
    """兼容旧客户端：角色引用已由服务端自动同步，无需手动更新。"""
    try:
        username = await _validate_username(username, x_username)
        return {
            "status": "success",
            "message": "角色引用会自动同步，无需手动更新",
            "autoSynced": True,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新角色失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ['router']
