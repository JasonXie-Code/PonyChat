"""
邀请码数据访问对象（DAO）
处理邀请码的数据库操作
"""
import aiosqlite
import secrets
import string
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from .database import Database, get_database
from ..config import logger


class InviteCodesDAO:
    """邀请码数据访问对象"""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def generate_code() -> str:
        """生成8位邀请码"""
        chars = string.ascii_uppercase + string.digits
        chars = chars.replace('O', '').replace('0', '').replace('I', '').replace('1', '')
        return ''.join(secrets.choice(chars) for _ in range(8))

    async def create_codes(self, count: int = 1, note: Optional[str] = None, days: int = 30) -> List[str]:
        """
        批量生成邀请码

        参数：
            count: 生成数量
            note: 备注
            days: 有效天数

        返回：
            生成的邀请码列表
        """
        now = datetime.now()
        expires = now + timedelta(days=days)
        generated = []

        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA busy_timeout = 5000")
                # 🔧 [事务保护] 批量生成使用显式事务
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    for _ in range(count):
                        # 确保唯一
                        while True:
                            code = self.generate_code()
                            async with conn.execute(
                                "SELECT code FROM invite_codes WHERE code = ?", (code,)
                            ) as cursor:
                                if not await cursor.fetchone():
                                    break

                        await conn.execute(
                            """INSERT INTO invite_codes (code, created_at, expires_at, is_used, note)
                               VALUES (?, ?, ?, 0, ?)""",
                            (code, now.isoformat(), expires.isoformat(), note)
                        )
                        generated.append(code)
                    
                    await conn.execute("COMMIT")
                except Exception:
                    await conn.execute("ROLLBACK")
                    raise

                logger.info(f"✅ [DB] 生成了 {len(generated)} 个邀请码")
        except Exception as e:
            logger.error(f"❌ [DB] 生成邀请码失败: {e}")
        return generated

    async def get_all(self) -> Dict[str, dict]:
        """获取所有邀请码"""
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                codes = {}
                async with conn.execute(
                    "SELECT code, created_at, expires_at, is_used, used_by, used_at, note FROM invite_codes"
                ) as cursor:
                    async for row in cursor:
                        code, created_at, expires_at, is_used, used_by, used_at, note = row
                        codes[code] = {
                            "code": code,
                            "created_at": created_at,
                            "expires_at": expires_at,
                            "is_used": bool(is_used),
                            "used_by": used_by,
                            "used_at": used_at,
                            "note": note,
                        }
                return codes
        except Exception as e:
            logger.error(f"❌ [DB] 加载邀请码失败: {e}")
            return {}

    async def validate(self, code: str) -> dict:
        """
        验证邀请码

        返回：
            {"valid": bool, "message": str}
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                async with conn.execute(
                    "SELECT is_used, expires_at FROM invite_codes WHERE code = ?", (code,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return {"valid": False, "message": "邀请码不存在"}
                    is_used, expires_at = row
                    if is_used:
                        return {"valid": False, "message": "邀请码已被使用"}
                    if datetime.now() > datetime.fromisoformat(expires_at):
                        return {"valid": False, "message": "邀请码已过期"}
                    return {"valid": True, "message": "邀请码有效"}
        except Exception as e:
            logger.error(f"❌ [DB] 验证邀请码失败: {e}")
            return {"valid": False, "message": f"验证失败: {e}"}

    async def use(self, code: str, username: str) -> bool:
        """标记邀请码为已使用（原子操作，防止竞态条件）"""
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA busy_timeout = 5000")
                # 🔧 [竞态修复] 使用 BEGIN IMMEDIATE 确保验证与使用的原子性
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    # 先验证邀请码是否可用
                    async with conn.execute(
                        "SELECT is_used, expires_at FROM invite_codes WHERE code = ?", (code,)
                    ) as cursor:
                        row = await cursor.fetchone()
                        if not row:
                            await conn.execute("ROLLBACK")
                            logger.warning(f"⚠️ [DB] 邀请码不存在: {code}")
                            return False
                        is_used, expires_at = row
                        if is_used:
                            await conn.execute("ROLLBACK")
                            logger.warning(f"⚠️ [DB] 邀请码已被使用: {code}")
                            return False
                        if datetime.now() > datetime.fromisoformat(expires_at):
                            await conn.execute("ROLLBACK")
                            logger.warning(f"⚠️ [DB] 邀请码已过期: {code}")
                            return False
                    
                    # 原子标记为已使用
                    await conn.execute(
                        """UPDATE invite_codes SET is_used = 1, used_by = ?, used_at = ?
                           WHERE code = ? AND is_used = 0""",
                        (username, datetime.now().isoformat(), code)
                    )
                    await conn.execute("COMMIT")
                except Exception:
                    await conn.execute("ROLLBACK")
                    raise
                
                logger.info(f"✅ [DB] 邀请码 {code} 被用户 {username} 使用")
                return True
        except Exception as e:
            logger.error(f"❌ [DB] 使用邀请码失败: {e}")
            return False

    async def delete(self, code: str) -> bool:
        """删除邀请码"""
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("DELETE FROM invite_codes WHERE code = ?", (code,))
                await conn.commit()
                logger.info(f"🗑️ [DB] 删除邀请码 {code}")
                return True
        except Exception as e:
            logger.error(f"❌ [DB] 删除邀请码失败: {e}")
            return False

    async def migrate_from_file(self, file_path: str) -> int:
        """从 JSON 文件迁移邀请码到数据库"""
        import json
        from pathlib import Path

        fp = Path(file_path)
        if not fp.exists():
            return 0

        try:
            with open(fp, 'r', encoding='utf-8') as f:
                codes = json.load(f)

            count = 0
            async with aiosqlite.connect(self.db.db_path) as conn:
                for code, data in codes.items():
                    await conn.execute(
                        """INSERT OR IGNORE INTO invite_codes
                           (code, created_at, expires_at, is_used, used_by, used_at, note)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            code,
                            data.get("created_at", datetime.now().isoformat()),
                            data.get("expires_at", (datetime.now() + timedelta(days=30)).isoformat()),
                            1 if data.get("is_used") else 0,
                            data.get("used_by"),
                            data.get("used_at"),
                            data.get("note"),
                        )
                    )
                    count += 1
                await conn.commit()

            logger.info(f"✅ [DB] 从文件迁移了 {count} 个邀请码")
            return count
        except Exception as e:
            logger.error(f"❌ [DB] 迁移邀请码失败: {e}")
            return 0
