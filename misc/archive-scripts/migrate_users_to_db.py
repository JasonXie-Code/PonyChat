#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
迁移 users.json 到数据库
独立脚本，不依赖 backend 模块导入
"""
import json
import os
import sys
import asyncio
import logging
from pathlib import Path

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import backend_package_dir, resolve_project_root

ROOT = resolve_project_root(Path(__file__))
sys.path.insert(0, str(ROOT))

import aiosqlite

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

USER_DATA_ROOT = ROOT / "user_data"
DB_PATH = backend_package_dir(ROOT) / "database" / "ponychat.db"

async def migrate_users_to_db():
    """迁移 users.json 到数据库"""
    users_file = USER_DATA_ROOT / "users.json"
    
    if not users_file.exists():
        logger.warning(f"⚠️ users.json 不存在: {users_file}")
        return
    
    # 读取 users.json
    try:
        with open(users_file, 'r', encoding='utf-8') as f:
            users_data = json.load(f)
    except Exception as e:
        logger.error(f"❌ 读取 users.json 失败: {e}")
        return
    
    if not users_data:
        logger.info("ℹ️ users.json 为空，无需迁移")
        return
    
    # 确保数据库目录存在
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # 连接数据库
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        # 检查 users 表是否存在，如果不存在则创建
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'") as cursor:
            table_exists = await cursor.fetchone()
        
        if not table_exists:
            logger.info("📋 创建 users 表...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT,
                    password TEXT,
                    gender TEXT DEFAULT 'male',
                    theme TEXT DEFAULT 'dark',
                    role TEXT DEFAULT 'user',
                    created_at TEXT,
                    last_active TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.commit()
        else:
            # 表已存在，检查是否需要添加新字段
            logger.info("📋 检查 users 表结构...")
            async with conn.execute("PRAGMA table_info(users)") as cursor:
                columns = {row[1] for row in await cursor.fetchall()}
            
            # 添加缺失的字段
            if "password_hash" not in columns:
                logger.info("➕ 添加 password_hash 字段...")
                await conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            if "password" not in columns:
                logger.info("➕ 添加 password 字段...")
                await conn.execute("ALTER TABLE users ADD COLUMN password TEXT")
            if "gender" not in columns:
                logger.info("➕ 添加 gender 字段...")
                await conn.execute("ALTER TABLE users ADD COLUMN gender TEXT DEFAULT 'male'")
            if "theme" not in columns:
                logger.info("➕ 添加 theme 字段...")
                await conn.execute("ALTER TABLE users ADD COLUMN theme TEXT DEFAULT 'dark'")
            if "role" not in columns:
                logger.info("➕ 添加 role 字段...")
                await conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
            if "created_at" not in columns:
                logger.info("➕ 添加 created_at 字段...")
                await conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
            if "last_active" not in columns:
                logger.info("➕ 添加 last_active 字段...")
                await conn.execute("ALTER TABLE users ADD COLUMN last_active TEXT")
            
            await conn.commit()
        
        migrated_count = 0
        skipped_count = 0
        error_count = 0
        
        logger.info(f"📦 开始迁移 {len(users_data)} 个用户到数据库...")
        
        for username, user_info in users_data.items():
            try:
                # 检查用户是否已存在
                async with conn.execute("SELECT username FROM users WHERE username = ?", (username,)) as cursor:
                    exists = await cursor.fetchone()
                
                if exists:
                    logger.info(f"⏭️  用户已存在，跳过: {username}")
                    skipped_count += 1
                    continue
                
                # 准备数据
                password_hash = user_info.get("password_hash", "")
                password = user_info.get("password", None)
                gender = user_info.get("gender", "male")
                theme = user_info.get("theme", "dark")
                role = user_info.get("role", "user")
                created_at = user_info.get("created_at", None)
                last_active = user_info.get("last_active", None)
                
                # 如果 created_at 是路径字符串（旧数据），使用 None
                if created_at and (created_at.startswith("E:\\") or created_at.startswith("F:\\") or "\\" in created_at):
                    created_at = None
                
                # 插入用户
                await conn.execute(
                    """INSERT INTO users (username, password_hash, password, gender, theme, role, created_at, last_active)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (username, password_hash, password, gender, theme, role, created_at, last_active or created_at)
                )
                await conn.commit()
                
                migrated_count += 1
                logger.info(f"✅ 已迁移用户: {username}")
            
            except Exception as e:
                error_count += 1
                logger.error(f"❌ 迁移用户异常 {username}: {e}")
        
        logger.info("=" * 60)
        logger.info(f"📊 迁移完成:")
        logger.info(f"  成功: {migrated_count} 个")
        logger.info(f"  跳过: {skipped_count} 个")
        logger.info(f"  失败: {error_count} 个")
        logger.info("=" * 60)

if __name__ == "__main__":
    asyncio.run(migrate_users_to_db())
