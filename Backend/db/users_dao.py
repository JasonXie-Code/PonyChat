"""
用户认证数据访问层（DAO）
处理用户注册、登录、密码验证等认证相关操作
"""
import asyncio
import aiosqlite
from typing import Optional, Dict, Any
from datetime import datetime, date
from .database import Database, get_database
from ..config import logger

class UsersDAO:
    """用户认证数据访问对象"""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            try:
                async with conn.execute(
                    "SELECT id, username, password, gender, theme, role, avatar, created_at, last_active, updated_at FROM users WHERE username = ?",
                    (username,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return {
                            "id": row[0],
                            "username": row[1],
                            "password": row[2],
                            "gender": row[3] or "male",
                            "theme": row[4] or "dark",
                            "role": row[5] or "user",
                            "avatar": row[6],
                            "created_at": row[7],
                            "last_active": row[8],
                            "updated_at": row[9]
                        }
            except Exception:
                # 兼容旧表结构
                async with conn.execute(
                    "SELECT id, username, password, gender, theme, role, created_at, last_active, updated_at FROM users WHERE username = ?",
                    (username,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return {
                            "id": row[0],
                            "username": row[1],
                            "password": row[2],
                            "gender": row[3] or "male",
                            "theme": row[4] or "dark",
                            "role": row[5] or "user",
                            "avatar": None,
                            "created_at": row[6],
                            "last_active": row[7],
                            "updated_at": row[8]
                        }
            return None
    
    async def get_all_users(self) -> Dict[str, Dict[str, Any]]:
        """获取所有用户（返回字典格式，兼容旧代码）"""
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            try:
                async with conn.execute(
                    "SELECT username, password, gender, theme, role, avatar, created_at, last_active FROM users"
                ) as cursor:
                    rows = await cursor.fetchall()
                    users = {}
                    for row in rows:
                        users[row[0]] = {
                            "password": row[1],
                            "gender": row[2] or "male",
                            "theme": row[3] or "dark",
                            "role": row[4] or "user",
                            "avatar": row[5],
                            "created_at": row[6],
                            "last_active": row[7]
                        }
                    return users
            except Exception:
                # 兼容旧表结构
                async with conn.execute(
                    "SELECT username, password, gender, theme, role, created_at, last_active FROM users"
                ) as cursor:
                    rows = await cursor.fetchall()
                    users = {}
                    for row in rows:
                        users[row[0]] = {
                            "password": row[1],
                            "gender": row[2] or "male",
                            "theme": row[3] or "dark",
                            "role": row[4] or "user",
                            "avatar": None,
                            "created_at": row[5],
                            "last_active": row[6]
                        }
                    return users
    
    async def create_user(self, username: str, password: str, 
                         gender: str = "male", theme: str = "dark", role: str = "user", 
                         avatar: Optional[str] = None, created_at: Optional[str] = None) -> bool:
        """创建新用户（明文密码存储）"""
        if created_at is None:
            created_at = datetime.now().isoformat()
        
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            try:
                await conn.execute(
                    """INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (username, password, gender, theme, role, avatar, created_at, created_at)
                )
                await conn.commit()
                logger.info(f"✅ 用户已创建: {username}")
                return True
            except Exception as e:
                logger.error(f"❌ 创建用户失败 {username}: {e}")
                return False
    
    async def _execute_with_retry(self, sql: str, params: list, username: str, max_retries: int = 3) -> bool:
        """
        带重试的执行器，缓解 SQLite 'database is locked' 问题
        """
        attempt = 0
        while attempt < max_retries:
            try:
                async with aiosqlite.connect(self.db.db_path) as conn:
                    # 避免长时间占用锁：设置 busy_timeout + 打开外键约束
                    await conn.execute("PRAGMA busy_timeout = 3000")
                    await conn.execute("PRAGMA foreign_keys = ON")
                    await conn.execute(sql, params)
                    await conn.commit()
                return True
            except aiosqlite.OperationalError as e:
                # 只针对锁冲突做有限重试
                if "database is locked" in str(e).lower():
                    attempt += 1
                    logger.warning(f"⚠️ 更新用户 {username} 发生锁冲突 (第 {attempt} 次), 准备重试...")
                    await asyncio.sleep(0.2 * attempt)
                    continue
                logger.error(f"❌ 更新用户失败 {username}: {e}")
                return False
            except Exception as e:
                logger.error(f"❌ 更新用户失败 {username}: {e}")
                return False
        logger.error(f"❌ 更新用户失败 {username}: 多次重试后仍然 database is locked")
        return False

    async def update_user(self, username: str, **kwargs) -> bool:
        """更新用户信息"""
        allowed_fields = ["password", "gender", "theme", "role", "avatar", "last_active"]
        updates = []
        values = []
        
        for key, value in kwargs.items():
            if key in allowed_fields:
                updates.append(f"{key} = ?")
                values.append(value)
        
        if not updates:
            return False
        
        values.append(username)

        sql = f"UPDATE users SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE username = ?"
        return await self._execute_with_retry(sql, values, username)
    
    async def update_last_active(self, username: str) -> bool:
        """更新用户最后活跃时间"""
        return await self.update_user(username, last_active=datetime.now().isoformat())

    async def get_token_version(self, username: str) -> int:
        """获取用户 token 版本（单设备：用于登录互踢）"""
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            try:
                async with conn.execute(
                    "SELECT token_version FROM users WHERE username = ?",
                    (username,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return int(row[0]) if row and row[0] is not None else 0
            except Exception:
                return 0

    async def increment_usage(
        self,
        username: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        *,
        llm_api_calls: int = 0,
    ) -> bool:
        """累计用户 token 用量（主对话大模型）。llm_api_calls>0 时按该值累加当日调用次数；否则在 token>0 时视为 1 次调用。"""
        resolved_calls = llm_api_calls if llm_api_calls > 0 else (
            1 if (input_tokens or output_tokens) else 0
        )
        if input_tokens == 0 and output_tokens == 0 and resolved_calls <= 0:
            return True
        ok = True
        if input_tokens or output_tokens:
            sql = """
                UPDATE users SET
                    total_input_tokens = COALESCE(total_input_tokens, 0) + ?,
                    total_output_tokens = COALESCE(total_output_tokens, 0) + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE username = ?
            """
            ok = await self._execute_with_retry(
                sql, [input_tokens, output_tokens, username], username
            )
        if ok:
            await self._bump_daily_token_usage(
                username,
                input_tokens,
                output_tokens,
                0,
                0,
                resolved_calls,
            )
        return ok

    async def increment_companion_usage(
        self,
        username: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        *,
        llm_api_calls: int = 0,
    ) -> bool:
        """累计陪玩模式 token 用量；llm_api_calls 规则同 increment_usage。"""
        resolved_calls = llm_api_calls if llm_api_calls > 0 else (
            1 if (input_tokens or output_tokens) else 0
        )
        if input_tokens == 0 and output_tokens == 0 and resolved_calls <= 0:
            return True
        ok = True
        if input_tokens or output_tokens:
            sql = """
                UPDATE users SET
                    companion_input_tokens = COALESCE(companion_input_tokens, 0) + ?,
                    companion_output_tokens = COALESCE(companion_output_tokens, 0) + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE username = ?
            """
            ok = await self._execute_with_retry(
                sql, [input_tokens, output_tokens, username], username
            )
        if ok:
            await self._bump_daily_token_usage(
                username,
                0,
                0,
                input_tokens,
                output_tokens,
                resolved_calls,
            )
        return ok

    async def _bump_daily_token_usage(
        self,
        username: str,
        main_in: int,
        main_out: int,
        companion_in: int,
        companion_out: int,
        llm_calls: int,
    ) -> None:
        """合并写入 daily_token_usage（主对话 / 陪玩 / 调用次数可部分为 0）。"""
        if (
            main_in == 0
            and main_out == 0
            and companion_in == 0
            and companion_out == 0
            and llm_calls <= 0
        ):
            return
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                async with conn.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ) as c:
                    row = await c.fetchone()
                    if not row:
                        return
                    uid = row[0]
                today = date.today().isoformat()
                await conn.execute(
                    """
                    INSERT INTO daily_token_usage (
                        user_id, usage_date, input_tokens, output_tokens,
                        companion_in, companion_out, llm_calls
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, usage_date) DO UPDATE SET
                        input_tokens = daily_token_usage.input_tokens + excluded.input_tokens,
                        output_tokens = daily_token_usage.output_tokens + excluded.output_tokens,
                        companion_in = daily_token_usage.companion_in + excluded.companion_in,
                        companion_out = daily_token_usage.companion_out + excluded.companion_out,
                        llm_calls = COALESCE(daily_token_usage.llm_calls, 0) + excluded.llm_calls
                    """,
                    (
                        uid,
                        today,
                        main_in,
                        main_out,
                        companion_in,
                        companion_out,
                        llm_calls,
                    ),
                )
                await conn.commit()
        except Exception as e:
            logger.warning(f"⚠️ [daily_token] bump 失败 {username}: {e}")

    async def get_usage(self, username: str) -> Dict[str, Any]:
        """获取用户累计 token 用量：仅输入/输出（主对话与陪玩、历史缓存列均并入输入侧）。"""
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            try:
                async with conn.execute(
                    """SELECT total_input_tokens, total_output_tokens, total_cache_read_tokens,
                              companion_input_tokens, companion_output_tokens, companion_cache_read_tokens
                       FROM users WHERE username = ?""",
                    (username,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        inp, out, cache = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
                        ci, co, cc = int(row[3] or 0), int(row[4] or 0), int(row[5] or 0)
                        merged_in = inp + cache + ci + cc
                        merged_out = out + co
                        return {
                            "input_tokens": merged_in,
                            "output_tokens": merged_out,
                            "total_tokens": merged_in + merged_out,
                        }
            except Exception:
                pass
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    async def increment_token_version(self, username: str) -> int:
        """递增 token 版本并返回新值（新登录使旧设备 token 失效）"""
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                await conn.execute(
                    "UPDATE users SET token_version = COALESCE(token_version, 0) + 1, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                    (username,)
                )
                await conn.commit()
            return await self.get_token_version(username)
        except Exception as e:
            logger.warning(f"⚠️ [DB] increment_token_version 失败: {e}")
            return 0
    
    async def rename_user(self, old_username: str, new_username: str) -> bool:
        """
        重命名用户。

        大多数业务表通过 user_id 关联，会随 users.id 自动保持归属；
        少数普通对话缓存/大厅发布信息直接冗余 username，需要同步迁移。
        """
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            try:
                await conn.execute("BEGIN")
                # 获取旧用户的 id
                async with conn.execute(
                    "SELECT id FROM users WHERE username = ?", (old_username,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        logger.error(f"❌ 重命名失败: 用户 {old_username} 不存在")
                        await conn.rollback()
                        return False

                # 检查新用户名是否已存在
                async with conn.execute(
                    "SELECT id FROM users WHERE username = ?", (new_username,)
                ) as cursor:
                    if await cursor.fetchone():
                        logger.error(f"❌ 重命名失败: 用户名 {new_username} 已存在")
                        await conn.rollback()
                        return False

                # 更新 username
                await conn.execute(
                    "UPDATE users SET username = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                    (new_username, old_username)
                )
                for table in (
                    "normal_chat_memory",
                    "normal_scene_state",
                    "normal_image_contexts",
                    "normal_image_context_state",
                ):
                    await conn.execute(
                        f"UPDATE {table} SET username = ? WHERE username = ?",
                        (new_username, old_username),
                    )
                await conn.execute(
                    "UPDATE hall_characters SET publisher_username = ? WHERE publisher_username = ?",
                    (new_username, old_username),
                )
                await conn.commit()
                logger.info(f"✅ 用户重命名: {old_username} -> {new_username}")
                return True
            except Exception as e:
                try:
                    await conn.rollback()
                except Exception:
                    pass
                logger.error(f"❌ 重命名用户失败: {e}")
                return False

    async def delete_user(self, username: str) -> bool:
        """删除用户"""
        async with aiosqlite.connect(self.db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            try:
                await conn.execute("DELETE FROM normal_scene_state WHERE username = ?", (username,))
                await conn.execute("DELETE FROM users WHERE username = ?", (username,))
                await conn.commit()
                logger.info(f"✅ 用户已删除: {username}")
                return True
            except Exception as e:
                logger.error(f"❌ 删除用户失败 {username}: {e}")
                return False
    
    async def user_exists(self, username: str) -> bool:
        """检查用户是否存在"""
        user = await self.get_user(username)
        return user is not None
    
    async def verify_password(self, username: str, password: str) -> bool:
        """验证密码（明文比对）"""
        user = await self.get_user(username)
        if not user:
            logger.warning(f"⚠️ 密码验证失败: 用户不存在 - {username}")
            return False
        
        stored_password = user.get("password")
        if stored_password and stored_password == password:
            logger.debug(f"✅ 密码验证成功: {username}")
            return True
        
        logger.warning(f"⚠️ 密码验证失败: 密码不匹配 - {username}")
        return False

# 全局实例
_users_dao: Optional[UsersDAO] = None

def get_users_dao() -> UsersDAO:
    """获取 UsersDAO 实例（单例）"""
    global _users_dao
    if _users_dao is None:
        _users_dao = UsersDAO(get_database())
    return _users_dao
