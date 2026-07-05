"""
用户设置数据访问对象（DAO）
处理用户设置的数据库操作
"""
import aiosqlite
import json
from typing import Any, Dict, Optional
from .database import Database, get_database
from ..config import logger


class SettingsDAO:
    """用户设置数据访问对象"""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def save_settings(
        self,
        username: str,
        settings: Dict
    ) -> bool:
        """
        保存用户设置到数据库
        
        参数：
            username: 用户名
            settings: 设置字典
            
        返回：
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                user_id = await self.db._get_user_id(conn, username)
                
                settings_json = json.dumps(settings, ensure_ascii=False)
                
                await conn.execute(
                    """INSERT OR REPLACE INTO user_settings 
                       (user_id, settings, updated_at)
                       VALUES (?, ?, CURRENT_TIMESTAMP)""",
                    (user_id, settings_json)
                )
                await conn.commit()
                
                logger.debug(f"💾 [DB] 保存设置: {username}")
                return True
                
        except Exception as e:
            logger.error(f"❌ [DB] 保存设置失败: {e}")
            return False

    def _deep_merge_settings(self, base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        """递归合并设置字典，避免局部更新覆盖掉其他模块写入的字段。"""
        merged: Dict[str, Any] = dict(base or {})
        for key, value in (patch or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge_settings(merged[key], value)
            else:
                merged[key] = value
        return merged

    async def merge_settings(
        self,
        username: str,
        settings_patch: Dict[str, Any]
    ) -> bool:
        """
        将局部设置 patch 合并进现有用户设置后再保存。

        适用于 /api/user/settings 这类只提交部分字段的入口，
        避免把 model_overrides / model_visibility 等其他模块维护的键覆盖掉。
        """
        try:
            current_settings = await self.load_settings(username) or {}
            merged_settings = self._deep_merge_settings(current_settings, settings_patch or {})
            return await self.save_settings(username, merged_settings)
        except Exception as e:
            logger.error(f"❌ [DB] 合并保存设置失败: {e}")
            return False
    
    async def load_settings(
        self,
        username: str
    ) -> Optional[Dict]:
        """
        加载用户设置
        
        参数：
            username: 用户名
            
        返回：
            设置字典，如果不存在则返回 None
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                user_id = await self.db._get_user_id(conn, username)
                
                async with conn.execute(
                    "SELECT settings FROM user_settings WHERE user_id = ?",
                    (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        settings_json = row[0]
                        try:
                            settings = json.loads(settings_json)
                            logger.debug(f"📥 [DB] 加载设置: {username}")
                            return settings
                        except json.JSONDecodeError as e:
                            logger.warning(
                                f"⚠️ [DB] 用户设置 JSON 损坏 (username={username}, 长度={len(settings_json) if settings_json else 0}): {e}"
                            )
                            return None
                    else:
                        logger.debug(f"📥 [DB] 用户设置不存在: {username}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ [DB] 加载设置失败: {e}")
            return None
