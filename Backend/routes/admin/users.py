"""
管理后台 — 用户管理 API（纯数据库模式）
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import aiosqlite
from ...config import DB_PATH, logger

from ...db import SettingsDAO, get_database, get_users_dao, get_membership_dao, MEMBERSHIP_LIMITS
from ...user_identity import clean_display_name, normalize_known_user_names_in_memories

_DB_PATH = DB_PATH


async def _batch_user_stats() -> dict:
    """一次性查出所有用户的可见角色数、可见对话数和可见消息总数。"""
    try:
        async with aiosqlite.connect(_DB_PATH) as conn:
            async def _load_count_map(query: str) -> dict:
                counts: dict = {}
                async with conn.execute(query) as cur:
                    async for row in cur:
                        counts[row[0]] = int(row[1] or 0)
                return counts

            char_map: dict = {}
            async with conn.execute(
                """SELECT user_id, COUNT(*)
                   FROM characters
                   WHERE COALESCE(is_hidden, 0) = 0
                   GROUP BY user_id"""
            ) as cur:
                async for row in cur:
                    char_map[row[0]] = int(row[1] or 0)

            conv_map: dict = {}
            async with conn.execute(
                """SELECT c.user_id, COUNT(*)
                   FROM conversations c
                   JOIN characters ch
                     ON ch.id = c.character_id
                    AND ch.user_id = c.user_id
                   WHERE COALESCE(c.is_hidden, 0) = 0
                     AND COALESCE(ch.is_hidden, 0) = 0
                   GROUP BY c.user_id"""
            ) as cur:
                async for row in cur:
                    conv_map[row[0]] = int(row[1] or 0)

            message_map: dict = {}
            normal_message_map = await _load_count_map(
                """SELECT c.user_id, COUNT(m.id)
                   FROM conversations c
                   JOIN messages m ON m.conversation_id = c.id
                   JOIN characters ch
                     ON ch.id = c.character_id
                    AND ch.user_id = c.user_id
                   WHERE COALESCE(c.is_hidden, 0) = 0
                     AND COALESCE(ch.is_hidden, 0) = 0
                     AND COALESCE(m.is_hidden, 0) = 0
                     AND m.deleted_at IS NULL
                   GROUP BY c.user_id"""
            )
            for uid, count in normal_message_map.items():
                message_map[uid] = message_map.get(uid, 0) + count

            for data_table, messages_table in (
                ("galgame_data", "galgame_messages"),
                ("galgame_lock_data", "galgame_lock_messages"),
            ):
                game_message_map = await _load_count_map(
                    f"""SELECT g.user_id, COUNT(m.id)
                        FROM {data_table} g
                        JOIN {messages_table} m
                          ON m.user_id = g.user_id
                         AND m.character_id = g.character_id
                         AND COALESCE(m.session_id, '') = COALESCE(g.active_session_id, '')
                        JOIN characters ch
                          ON ch.id = g.character_id
                         AND ch.user_id = g.user_id
                        WHERE COALESCE(ch.is_hidden, 0) = 0
                          AND COALESCE(m.is_hidden, 0) = 0
                          AND m.deleted_at IS NULL
                        GROUP BY g.user_id"""
                )
                for uid, count in game_message_map.items():
                    message_map[uid] = message_map.get(uid, 0) + count

            uid_map: dict = {}
            async with conn.execute("SELECT id, username FROM users") as cur:
                async for row in cur:
                    uid_map[row[1]] = row[0]

        return {
            uname: {
                "char_count": char_map.get(uid, 0),
                "conv_count": conv_map.get(uid, 0),
                "message_count": message_map.get(uid, 0),
            }
            for uname, uid in uid_map.items()
        }
    except Exception as e:
        logger.error(f"_batch_user_stats failed: {e}")
        return {}

router = APIRouter(prefix="/users")


class MembershipUpdateRequest(BaseModel):
    membership_type: str           # free / pro / pro_plus / developer
    expire_at: Optional[str] = None  # ISO 格式日期时间，None = 永久
    note: Optional[str] = ""


@router.get("")
async def list_users():
    """获取所有用户信息并包含实时在线状态与会员信息"""
    try:
        from ...websocket import manager
        users_dao = get_users_dao()
        users_data = await users_dao.get_all_users()
        user_list = []

        active_usernames = {u.lower() for u in manager.active_connections.keys()}
        _now = datetime.now()

        # 批量获取会员摘要（一次查询，性能更好）
        membership_dao = get_membership_dao()
        memberships_summary = await membership_dao.get_all_memberships_summary()
        membership_map = {m["username"]: m for m in memberships_summary}

        # 批量获取可见角色数和可见消息总数（普通聊天 + 游戏 + 锁分）
        stats_map = await _batch_user_stats()

        for username, info in users_data.items():
            # WebSocket 长连接（Web端）OR 10 分钟内有 last_active（App端）均视为在线
            is_connected = username.lower() in active_usernames
            if not is_connected:
                last_active_str = info.get("last_active", "")
                if last_active_str and last_active_str != "未知":
                    try:
                        last_dt = datetime.fromisoformat(str(last_active_str)[:19])
                        is_connected = (_now - last_dt).total_seconds() < 10 * 60
                    except Exception:
                        pass
            m_info = membership_map.get(username, {})

            u_stats = stats_map.get(username, {})
            role = info.get("role") or "user"
            user_list.append({
                "username": username,
                "password": info.get("password", ""),
                "role": role,
                "disabled": role == "disabled",
                "created_at": info.get("created_at", "未知"),
                "last_active": info.get("last_active", "未知"),
                "gender": info.get("gender", "male"),
                "is_online": is_connected,
                "membership_type": m_info.get("membership_type", "free"),
                "membership_label": m_info.get("membership_label", "免费"),
                "membership_expire_at": m_info.get("expire_at"),
                "daily_limit": m_info.get("daily_limit", MEMBERSHIP_LIMITS["free"]),
                "used_today": m_info.get("used_today", 0),
                "remaining_today": m_info.get("remaining_today", MEMBERSHIP_LIMITS["free"]),
                "character_count": u_stats.get("char_count", 0),
                "message_count": u_stats.get("message_count", 0),
                "conversation_count": u_stats.get("conv_count", 0),
            })

        return user_list

    except Exception as e:
        logger.error(f"加载用户列表失败: {e}")
        return []


@router.post("/{username}/disable")
async def disable_user(username: str):
    """禁用用户"""
    users_dao = get_users_dao()
    user = await users_dao.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await users_dao.update_user(username, role="disabled")
    logger.info(f"🚫 用户已禁用: {username}")
    return {"success": True}


@router.post("/{username}/enable")
async def enable_user(username: str):
    """启用用户（将 disabled 角色恢复为 user）"""
    users_dao = get_users_dao()
    user = await users_dao.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await users_dao.update_user(username, role="user")
    logger.info(f"✅ 用户已启用: {username}")
    return {"success": True, "message": "用户已启用"}


@router.get("/{username}/membership")
async def get_user_membership(username: str):
    """获取用户会员信息（配额展示 + 库内会员记录，供管理端表单编辑）"""
    users_dao = get_users_dao()
    user = await users_dao.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    membership_dao = get_membership_dao()
    info = await membership_dao.get_quota_info(username)
    raw = await membership_dao.get_membership_by_username(username)
    return {
        "success": True,
        "username": username,
        "user_role": (user.get("role") or "user"),
        **info,
        "record_membership_type": raw.get("membership_type") or "free",
        "record_expire_at": raw.get("expire_at"),
        "record_note": raw.get("note") or "",
    }


@router.post("/{username}/membership")
async def set_user_membership(username: str, body: MembershipUpdateRequest):
    """设置用户会员等级（管理员操作）"""
    if body.membership_type not in MEMBERSHIP_LIMITS and body.membership_type != "free":
        raise HTTPException(status_code=400, detail=f"无效的会员等级: {body.membership_type}")

    users_dao = get_users_dao()
    user = await users_dao.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    membership_dao = get_membership_dao()
    ok = await membership_dao.set_membership_by_username(
        username=username,
        membership_type=body.membership_type,
        expire_at=body.expire_at,
        granted_by="admin",
        note=body.note or "",
    )
    if not ok:
        raise HTTPException(status_code=500, detail="设置会员失败")

    logger.info(f"👑 管理员设置 {username} 为 {body.membership_type}，到期: {body.expire_at or '永久'}")
    return {
        "success": True,
        "message": f"已设置 {username} 为 {body.membership_type} 会员",
        "expire_at": body.expire_at,
    }


@router.post("/{username}/membership/reset-usage")
async def reset_user_daily_usage(username: str):
    """重置用户今日积分使用量（管理员操作）"""
    users_dao = get_users_dao()
    user = await users_dao.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    membership_dao = get_membership_dao()
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT id FROM users WHERE username = ?", (username,)) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")

    ok = await membership_dao.admin_reset_daily_usage(row[0])
    if not ok:
        raise HTTPException(status_code=500, detail="重置失败")

    logger.info(f"🔄 管理员重置 {username} 今日积分")
    return {"success": True, "message": f"已重置 {username} 今日积分"}


@router.post("/reset-all-usage")
async def reset_all_daily_usage():
    """重置所有用户今日积分使用量（管理员操作）"""
    membership_dao = get_membership_dao()
    affected = await membership_dao.admin_reset_all_daily_usage()
    if affected < 0:
        raise HTTPException(status_code=500, detail="重置失败")
    logger.info(f"🔄 管理员重置全员今日积分，共影响 {affected} 条记录")
    return {"success": True, "message": f"已重置所有用户今日积分，共影响 {affected} 条记录", "affected": affected}


@router.post("/edit")
async def edit_user(body: dict):
    """编辑用户信息（重命名、改性别、改密码）"""
    old_username = (body.get("old_username") or "").strip()
    new_username = (body.get("new_username") or "").strip()
    new_gender = body.get("gender")
    new_password = (body.get("new_password") or "").strip()

    if not old_username:
        raise HTTPException(status_code=400, detail="缺少原用户名")

    users_dao = get_users_dao()
    user = await users_dao.get_user(old_username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if new_username and new_username != old_username:
        try:
            settings = await SettingsDAO(get_database()).load_settings(old_username) or {}
        except Exception:
            settings = {}
        ok = await users_dao.rename_user(old_username, new_username)
        if not ok:
            return {"success": False, "message": "用户名已存在或重命名失败"}
        old_nickname = clean_display_name(settings.get("nickname"))
        aliases = [old_username]
        if old_nickname and old_nickname != new_username:
            aliases.append(old_nickname)
        await normalize_known_user_names_in_memories(new_username, aliases)
        old_username = new_username

    if new_gender:
        await users_dao.update_user(old_username, gender=new_gender)

    if new_password:
        if len(new_password) < 4:
            return {"success": False, "message": "密码不能少于4位"}
        await users_dao.update_user(old_username, password=new_password)

    return {"success": True, "message": "用户信息已更新"}


@router.delete("/{username}")
async def delete_user(username: str):
    """删除用户（纯数据库操作，CASCADE 自动删除关联数据）"""
    users_dao = get_users_dao()
    user = await users_dao.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    success = await users_dao.delete_user(username)
    if not success:
        raise HTTPException(status_code=500, detail="数据库删除失败")

    logger.info(f"✅ 用户已删除: {username}")
    return {"success": True}
