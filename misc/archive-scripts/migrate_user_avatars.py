"""从备份文件迁移用户头像数据到数据库"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import asyncio
import json
from pathlib import Path
sys.path.insert(0, '.')

from backend.db import get_database, get_users_dao

async def migrate_user_avatars():
    db = get_database('database/ponychat.db')
    await db.init()
    dao = get_users_dao()
    
    # 从备份文件读取
    backup_file = Path('backups/用户信息备份/users.json')
    if not backup_file.exists():
        print('ERROR: 备份文件不存在')
        return
    
    with open(backup_file, 'r', encoding='utf-8') as f:
        backup_users = json.load(f)
    
    migrated_count = 0
    for username, user_data in backup_users.items():
        avatar = user_data.get('avatar')
        if avatar:
            # 更新数据库
            success = await dao.update_user(username, avatar=avatar)
            if success:
                print(f'OK: 已迁移 {username} 的头像: {avatar[:50]}...')
                migrated_count += 1
            else:
                print(f'ERROR: 迁移 {username} 的头像失败')
    
    print(f'\n总计: 迁移了 {migrated_count} 个用户的头像')

if __name__ == '__main__':
    asyncio.run(migrate_user_avatars())
