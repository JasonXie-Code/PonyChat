"""
会员管理数据访问对象（DAO）
负责处理会员等级、到期时间、今日积分等相关数据库操作
"""
import aiosqlite
from typing import Optional, Dict, Any
from datetime import datetime, date, timedelta
from .database import Database, get_database
from ..config import logger


def _parse_expire_dt(s: str) -> datetime:
    """
    解析多种格式的 ISO 时间字符串为 naive datetime（兼容 Python 3.10）

    JavaScript toISOString() 生成带 Z 后缀的 UTC 时间，如 2026-03-31T16:00:00.000Z
    Python 3.10 的 datetime.fromisoformat() 不支持 Z 后缀，截取前 19 位
    """
    return datetime.fromisoformat(str(s).strip()[:19])


# ── 会员等级配额 ──────────────────────────────────────────────────────────────────────────────
MEMBERSHIP_LIMITS: Dict[str, int] = {
    "free":      100,   # 免费用户 100 分/天
    "pro":       400,   # Pro 会员 400 分/天
    "pro_plus":  800,   # Pro+ 会员 800 分/天
    "developer": 10000,  # 开发者 10000 分/天
}
MEMBERSHIP_LABELS: Dict[str, str] = {
    "free":      "免费",
    "pro":       "Pro",
    "pro_plus":  "Pro+",
    "developer": "开发者",
}

# role = 'admin' 时不限积分
ADMIN_DAILY_LIMIT = 999999


class MembershipDAO:
    """会员数据访问对象"""

    def __init__(self, db: Database):
        self.db = db

    # ── 工具方法 ───────────────────────────────────────────────────────────────────────────────

    async def _get_user_id(self, conn: aiosqlite.Connection, username: str) -> Optional[int]:
        async with conn.execute("SELECT id FROM users WHERE username = ?", (username,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def _get_user_role(self, conn: aiosqlite.Connection, user_id: int) -> str:
        async with conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return (row[0] or "user") if row else "user"

    # ── 会员信息 ───────────────────────────────────────────────────────────────────────────────

    async def get_membership(self, user_id: int) -> Dict[str, Any]:
        """获取指定用户的会员信息，默认返回 free"""
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            async with conn.execute(
                "SELECT membership_type, expire_at, granted_by, granted_at, note FROM memberships WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()

        if not row:
            return {
                "membership_type": "free",
                "expire_at": None,
                "is_expired": False,
                "granted_by": None,
                "granted_at": None,
                "note": None,
                "daily_limit": MEMBERSHIP_LIMITS["free"],
            }

        mtype = row[0] or "free"
        expire_at = row[1]
        is_expired = False

        if mtype != "free" and expire_at:
            try:
                exp_dt = _parse_expire_dt(expire_at)
                if datetime.now() > exp_dt:
                    is_expired = True
                    mtype = "free"
            except Exception:
                pass

        return {
            "membership_type": mtype,
            "expire_at": expire_at,
            "is_expired": is_expired,
            "granted_by": row[2],
            "granted_at": row[3],
            "note": row[4],
            "daily_limit": MEMBERSHIP_LIMITS.get(mtype, MEMBERSHIP_LIMITS["free"]),
        }

    async def get_membership_by_username(self, username: str) -> Dict[str, Any]:
        """通过用户名获取会员信息"""
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            user_id = await self._get_user_id(conn, username)
        if user_id is None:
            return {"membership_type": "free", "daily_limit": MEMBERSHIP_LIMITS["free"]}
        return await self.get_membership(user_id)

    async def set_membership(
        self,
        user_id: int,
        membership_type: str,
        expire_at: Optional[str],
        granted_by: str = "admin",
        note: str = "",
    ) -> bool:
        """设置或更新用户会员等级"""
        if membership_type not in MEMBERSHIP_LIMITS:
            logger.warning(f"⚠️ [Membership] 无效会员类型: {membership_type}")
            return False
        now = datetime.now().isoformat()
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                await conn.execute(
                    """INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(user_id) DO UPDATE SET
                           membership_type = excluded.membership_type,
                           expire_at = excluded.expire_at,
                           granted_by = excluded.granted_by,
                           granted_at = excluded.granted_at,
                           note = excluded.note,
                           updated_at = excluded.updated_at""",
                    (user_id, membership_type, expire_at, granted_by, now, note, now, now),
                )
                await conn.commit()
            logger.info(f"✅ [Membership] 已设置 {user_id} 的会员为 {membership_type}，到期: {expire_at or '永久'}")
            return True
        except Exception as e:
            logger.error(f"❌ [Membership] 设置会员失败: {e}")
            return False

    async def set_membership_by_username(
        self,
        username: str,
        membership_type: str,
        expire_at: Optional[str],
        granted_by: str = "admin",
        note: str = "",
    ) -> bool:
        """通过用户名设置会员等级"""
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            user_id = await self._get_user_id(conn, username)
        if user_id is None:
            logger.warning(f"⚠️ [Membership] 用户不存在: {username}")
            return False
        return await self.set_membership(user_id, membership_type, expire_at, granted_by, note)

    # ── 每日用量 ───────────────────────────────────────────────────────────────────────────────

    async def get_daily_usage(self, user_id: int, usage_date: Optional[str] = None) -> Dict[str, Any]:
        """获取用户指定日期的每日用量"""
        if usage_date is None:
            usage_date = date.today().isoformat()
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            async with conn.execute(
                "SELECT usage_count, last_used_at FROM daily_chat_usage WHERE user_id = ? AND usage_date = ?",
                (user_id, usage_date),
            ) as cur:
                row = await cur.fetchone()
        return {
            "usage_date": usage_date,
            "usage_count": row[0] if row else 0,
            "last_used_at": row[1] if row else None,
        }

    async def check_and_increment(self, username: str) -> Dict[str, Any]:
        """
        检查并递增用户每日用量
        返回:
          allowed  bool  是否允许请求
          remaining int  剩余积分
          limit     int  每日积分上限
          membership_type str
        """
        today = date.today().isoformat()
        now = datetime.now().isoformat()

        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout = 3000")
            await conn.execute("PRAGMA foreign_keys = ON")

            # 获取 user_id 和 role
            async with conn.execute(
                "SELECT id, role FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return {"allowed": False, "remaining": 0, "limit": 0, "membership_type": "free", "reason": "用户不存在"}

            user_id, role = row[0], (row[1] or "user")

            # 管理员不限次数
            if role == "admin":
                return {"allowed": True, "remaining": ADMIN_DAILY_LIMIT, "limit": ADMIN_DAILY_LIMIT, "membership_type": "admin"}

            # 查询会员等级及到期时间
            async with conn.execute(
                "SELECT membership_type, expire_at FROM memberships WHERE user_id = ?", (user_id,)
            ) as cur:
                m_row = await cur.fetchone()

            mtype = "free"
            if m_row:
                mtype = m_row[0] or "free"
                expire_at = m_row[1]
                if mtype != "free" and expire_at:
                    try:
                        if datetime.now() > _parse_expire_dt(expire_at):
                            mtype = "free"
                    except Exception:
                        mtype = "free"

            limit = MEMBERSHIP_LIMITS.get(mtype, MEMBERSHIP_LIMITS["free"])

            # 查询用量
            async with conn.execute(
                "SELECT usage_count FROM daily_chat_usage WHERE user_id = ? AND usage_date = ?",
                (user_id, today),
            ) as cur:
                u_row = await cur.fetchone()
            current_count = u_row[0] if u_row else 0

            if current_count >= limit:
                return {
                    "allowed": False,
                    "remaining": 0,
                    "limit": limit,
                    "membership_type": mtype,
                    "reason": f"今日积分已用完（上限 {limit} 分）",
                }

            # 插入/更新用量记录
            await conn.execute(
                """INSERT INTO daily_chat_usage (user_id, usage_date, usage_count, last_used_at)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(user_id, usage_date) DO UPDATE SET
                       usage_count = usage_count + 1,
                       last_used_at = excluded.last_used_at""",
                (user_id, today, now),
            )
            await conn.commit()

        new_count = current_count + 1
        return {
            "allowed": True,
            "remaining": limit - new_count,
            "limit": limit,
            "membership_type": mtype,
        }

    async def check_daily_quota(self, username: str) -> Dict[str, Any]:
        """
        仅检查今日是否未满额（不写入 daily_chat_usage）。
        用于 galgame / galgame_lock：会员「今日积分」在每次 LLM 成功后由 llm_call 按模型调用逐次 increment_by。
        """
        today = date.today().isoformat()
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout = 3000")
            await conn.execute("PRAGMA foreign_keys = ON")

            async with conn.execute(
                "SELECT id, role FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return {"allowed": False, "remaining": 0, "limit": 0, "membership_type": "free", "reason": "用户不存在"}

            user_id, role = row[0], (row[1] or "user")

            if role == "admin":
                return {"allowed": True, "remaining": ADMIN_DAILY_LIMIT, "limit": ADMIN_DAILY_LIMIT, "membership_type": "admin"}

            async with conn.execute(
                "SELECT membership_type, expire_at FROM memberships WHERE user_id = ?", (user_id,)
            ) as cur:
                m_row = await cur.fetchone()

            mtype = "free"
            if m_row:
                mtype = m_row[0] or "free"
                expire_at = m_row[1]
                if mtype != "free" and expire_at:
                    try:
                        if datetime.now() > _parse_expire_dt(expire_at):
                            mtype = "free"
                    except Exception:
                        mtype = "free"

            limit = MEMBERSHIP_LIMITS.get(mtype, MEMBERSHIP_LIMITS["free"])

            async with conn.execute(
                "SELECT usage_count FROM daily_chat_usage WHERE user_id = ? AND usage_date = ?",
                (user_id, today),
            ) as cur:
                u_row = await cur.fetchone()
            current_count = u_row[0] if u_row else 0

            if current_count >= limit:
                return {
                    "allowed": False,
                    "remaining": 0,
                    "limit": limit,
                    "membership_type": mtype,
                    "reason": f"今日积分已用完（上限 {limit} 分）",
                }

        return {
            "allowed": True,
            "remaining": limit - current_count,
            "limit": limit,
            "membership_type": mtype,
        }

    async def increment_by(self, username: str, count: int) -> bool:
        """直接增加用户今日积分 count 分（不校验上限；由 llm_call 等在每次模型调用成功后按需累加）"""
        if count <= 0:
            return True
        today = date.today().isoformat()
        now = datetime.now().isoformat()
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA busy_timeout = 3000")
                async with conn.execute(
                    "SELECT id, role FROM users WHERE username = ?", (username,)
                ) as cur:
                    row = await cur.fetchone()
                if not row:
                    return False
                user_id, role = row[0], (row[1] or "user")
                if role == "admin":
                    return True  # 管理员不限次数，无需累加
                await conn.execute(
                    """INSERT INTO daily_chat_usage (user_id, usage_date, usage_count, last_used_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(user_id, usage_date) DO UPDATE SET
                           usage_count = usage_count + ?,
                           last_used_at = excluded.last_used_at""",
                    (user_id, today, count, now, count),
                )
                await conn.commit()
            return True
        except Exception as e:
            logger.warning(f"⚠️ [Membership] increment_by 失败: {e}")
            return False

    async def get_quota_info(self, username: str) -> Dict[str, Any]:
        """获取用户的配额信息（会员等级+每日用量）"""
        today = date.today().isoformat()
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            async with conn.execute(
                "SELECT id, role FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                free_limit = MEMBERSHIP_LIMITS["free"]
                return {"membership_type": "free", "daily_limit": free_limit, "used_today": 0, "remaining": free_limit}

            user_id, role = row[0], (row[1] or "user")
            if role == "admin":
                return {"membership_type": "admin", "daily_limit": ADMIN_DAILY_LIMIT, "used_today": 0, "remaining": ADMIN_DAILY_LIMIT}

            async with conn.execute(
                "SELECT membership_type, expire_at FROM memberships WHERE user_id = ?", (user_id,)
            ) as cur:
                m_row = await cur.fetchone()

            mtype = "free"
            expire_at = None
            if m_row:
                mtype = m_row[0] or "free"
                expire_at = m_row[1]
                if mtype != "free" and expire_at:
                    try:
                        if datetime.now() > _parse_expire_dt(expire_at):
                            mtype = "free"
                            expire_at = None
                    except Exception:
                        mtype = "free"

            limit = MEMBERSHIP_LIMITS.get(mtype, MEMBERSHIP_LIMITS["free"])

            async with conn.execute(
                "SELECT usage_count FROM daily_chat_usage WHERE user_id = ? AND usage_date = ?",
                (user_id, today),
            ) as cur:
                u_row = await cur.fetchone()
            used = u_row[0] if u_row else 0

        return {
            "membership_type": mtype,
            "membership_label": MEMBERSHIP_LABELS.get(mtype, mtype),
            "daily_limit": limit,
            "used_today": used,
            "remaining": max(0, limit - used),
            "expire_at": expire_at,
        }

    async def admin_reset_daily_usage(self, user_id: int, usage_date: Optional[str] = None) -> bool:
        """管理员重置指定用户当天的用量"""
        if usage_date is None:
            usage_date = date.today().isoformat()
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute(
                    "UPDATE daily_chat_usage SET usage_count = 0 WHERE user_id = ? AND usage_date = ?",
                    (user_id, usage_date),
                )
                await conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ [Membership] 重置用量失败: {e}")
            return False

    async def admin_reset_all_daily_usage(self, usage_date: Optional[str] = None) -> int:
        """管理员重置所有用户当天的用量，返回受影响行数"""
        if usage_date is None:
            usage_date = date.today().isoformat()
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                cur = await conn.execute(
                    "UPDATE daily_chat_usage SET usage_count = 0 WHERE usage_date = ?",
                    (usage_date,),
                )
                await conn.commit()
                return cur.rowcount
        except Exception as e:
            logger.error(f"❌ [Membership] 重置全员用量失败: {e}")
            return -1

    async def get_all_memberships_summary(self) -> list:
        """获取所有用户的会员摘要信息"""
        today = date.today().isoformat()
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                async with conn.execute(
                    """SELECT u.id, u.username, u.role,
                              COALESCE(m.membership_type, 'free') as mtype,
                              m.expire_at,
                              COALESCE(d.usage_count, 0) as used_today
                       FROM users u
                       LEFT JOIN memberships m ON u.id = m.user_id
                       LEFT JOIN daily_chat_usage d ON u.id = d.user_id AND d.usage_date = ?
                       ORDER BY u.id""",
                    (today,),
                ) as cur:
                    rows = await cur.fetchall()
            result = []
            for row in rows:
                user_id, username, role, mtype, expire_at, used_today = row
                if role == "admin":
                    mtype = "admin"
                    limit = ADMIN_DAILY_LIMIT
                else:
                    if mtype != "free" and expire_at:
                        try:
                            if datetime.now() > _parse_expire_dt(expire_at):
                                mtype = "free"
                        except Exception:
                            mtype = "free"
                    limit = MEMBERSHIP_LIMITS.get(mtype, MEMBERSHIP_LIMITS["free"])
                result.append({
                    "user_id": user_id,
                    "username": username,
                    "membership_type": mtype,
                    "membership_label": MEMBERSHIP_LABELS.get(mtype, mtype),
                    "expire_at": expire_at,
                    "daily_limit": limit,
                    "used_today": used_today,
                    "remaining_today": max(0, limit - used_today) if limit != ADMIN_DAILY_LIMIT else ADMIN_DAILY_LIMIT,
                })
            return result
        except Exception as e:
            logger.error(f"❌ [Membership] 获取会员摘要失败: {e}")
            return []


# ── 单例 ────────────────────────────────────────────────────────────────────────────────────
_membership_dao: Optional[MembershipDAO] = None


def get_membership_dao() -> MembershipDAO:
    global _membership_dao
    if _membership_dao is None:
        _membership_dao = MembershipDAO(get_database())
    return _membership_dao
