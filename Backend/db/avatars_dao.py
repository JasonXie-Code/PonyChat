"""
头像数据访问对象（DAO）
处理头像的数据库存储和读取
"""
import aiosqlite
from typing import Optional, Tuple
from .database import Database, get_database
from ..config import logger


class AvatarsDAO:
    """头像数据访问对象"""

    def __init__(self, db: Database):
        self.db = db

    async def save_avatar(self, filename: str, data: bytes, mime_type: str = "image/jpeg") -> bool:
        """
        保存头像到数据库

        参数：
            filename: 头像文件名（唯一标识）
            data: 头像二进制数据
            mime_type: MIME 类型

        返回：
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute(
                    """INSERT OR REPLACE INTO avatars (filename, data, mime_type, created_at)
                       VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                    (filename, data, mime_type)
                )
                await conn.commit()
                logger.debug(f"💾 [DB] 保存头像: {filename} ({len(data)} bytes)")
                return True
        except Exception as e:
            logger.error(f"❌ [DB] 保存头像失败: {e}")
            return False

    async def get_avatar(self, filename: str) -> Optional[Tuple[bytes, str]]:
        """
        获取头像数据

        参数：
            filename: 头像文件名

        返回：
            (data, mime_type) 元组，不存在返回 None
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                async with conn.execute(
                    "SELECT data, mime_type FROM avatars WHERE filename = ?",
                    (filename,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return (row[0], row[1])
                    return None
        except Exception as e:
            logger.error(f"❌ [DB] 获取头像失败: {e}")
            return None

    async def delete_avatar(self, filename: str) -> bool:
        """删除头像"""
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("DELETE FROM avatars WHERE filename = ?", (filename,))
                await conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ [DB] 删除头像失败: {e}")
            return False

    async def avatar_exists(self, filename: str) -> bool:
        """检查头像是否存在"""
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                async with conn.execute(
                    "SELECT 1 FROM avatars WHERE filename = ? LIMIT 1",
                    (filename,)
                ) as cursor:
                    return await cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"❌ [DB] 检查头像失败: {e}")
            return False
