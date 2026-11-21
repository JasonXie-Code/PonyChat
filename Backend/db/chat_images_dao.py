"""
聊天图片数据访问对象（DAO）
聊天消息图片默认走短期内存交付；需要长期展示的资料图可显式写入 SQLite BLOB。
"""
import hashlib
import aiosqlite
from typing import Optional, Tuple
from .database import Database
from ..config import logger
from ..chat_image_transfer import load_chat_image_transfer, store_chat_image_transfer


def mime_to_ext(mime: str) -> Optional[str]:
    m = (mime or "").lower().strip()
    if m in ("image/jpeg", "image/jpg"):
        return "jpg"
    if m == "image/png":
        return "png"
    if m == "image/webp":
        return "webp"
    return None


def detect_image_mime_from_magic(raw: bytes) -> Optional[str]:
    """根据文件头判断图片类型（与 multipart 声明交叉校验用）。"""
    if not raw or len(raw) < 12:
        return None
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(raw) >= 8 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


class ChatImagesDAO:
    """聊天图片数据访问对象"""

    def __init__(self, db: Database):
        self.db = db

    async def save_image(self, filename: str, data: bytes, mime_type: str = "image/jpeg") -> bool:
        try:
            store_chat_image_transfer(data, mime_type)
            logger.debug(f"📎 [ChatImg] 短期交付: {filename} ({len(data)} bytes)")
            return True
        except Exception as e:
            logger.error(f"❌ [ChatImg] 短期交付失败: {e}")
            return False

    async def get_image(self, filename: str) -> Optional[Tuple[bytes, str]]:
        transfer = load_chat_image_transfer(filename)
        if transfer:
            return transfer
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                async with conn.execute(
                    "SELECT data, mime_type FROM chat_images WHERE filename = ?",
                    (filename,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return (row[0], row[1])
                    return None
        except Exception as e:
            logger.error(f"❌ [ChatImg] 获取失败: {e}")
            return None

    async def image_exists(self, filename: str) -> bool:
        if load_chat_image_transfer(filename):
            return True
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                async with conn.execute(
                    "SELECT 1 FROM chat_images WHERE filename = ? LIMIT 1",
                    (filename,)
                ) as cursor:
                    return await cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"❌ [ChatImg] 检查失败: {e}")
            return False

    async def store_dedup_from_bytes(self, raw: bytes, mime_type: str) -> str:
        """
        将聊天图片放入短期内存交付缓存。
        返回相对路径，如 /chat_images/tmp_xxx.jpg。
        """
        ext = mime_to_ext(mime_type)
        if not ext:
            raise ValueError("不支持的图片 MIME 类型")
        return store_chat_image_transfer(raw, mime_type)

    async def store_persistent_from_bytes(self, raw: bytes, mime_type: str) -> str:
        """
        将需要长期展示的图片写入 chat_images 表。
        返回相对路径，如 /chat_images/ci_xxx.jpg。
        """
        ext = mime_to_ext(mime_type)
        if not ext:
            raise ValueError("不支持的图片 MIME 类型")
        digest = hashlib.sha256(raw).hexdigest()[:16]
        filename = f"ci_{digest}.{ext}"
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute(
                    """INSERT OR IGNORE INTO chat_images (filename, data, mime_type, size_bytes, created_at)
                       VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    (filename, raw, mime_type, len(raw)),
                )
                await conn.commit()
            logger.info(f"📎 [ChatImg] 持久保存: {filename} ({len(raw)} bytes)")
            return f"/chat_images/{filename}"
        except Exception as e:
            logger.error(f"❌ [ChatImg] 持久保存失败: {e}")
            raise
