"""检查对话记录和设置的迁移状态（简化版）"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import asyncio
import os
import json
import aiosqlite
sys.path.insert(0, '.')

from backend.db import get_database, SettingsDAO, get_users_dao

async def check_migration_status():
    db = get_database('database/ponychat.db')
    await db.init()
    
    users_dao = get_users_dao()
    settings_dao = SettingsDAO(db)
    
    # 获取所有用户
    users = await users_dao.get_all_users()
    
    print(f'总用户数: {len(users)}')
    print('=' * 60)
    
    # 直接查询数据库统计对话记录
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute("SELECT COUNT(*) FROM conversations") as cursor:
            total_convs_db = (await cursor.fetchone())[0]
        
        async with conn.execute("SELECT COUNT(*) FROM messages") as cursor:
            total_messages_db = (await cursor.fetchone())[0]
        
        async with conn.execute("SELECT COUNT(*) FROM user_settings") as cursor:
            total_settings_db = (await cursor.fetchone())[0]
    
    # 检查文件系统中的数据
    total_convs_fs = 0
    total_settings_fs = 0
    
    if os.path.exists("user_data"):
        for username in os.listdir("user_data"):
            user_dir = os.path.join("user_data", username)
            if os.path.isdir(user_dir):
                # 检查对话
                conv_dir = os.path.join(user_dir, "conversations")
                if os.path.exists(conv_dir):
                    for char_id_dir in os.listdir(conv_dir):
                        char_path = os.path.join(conv_dir, char_id_dir)
                        if os.path.isdir(char_path):
                            total_convs_fs += len([f for f in os.listdir(char_path) if f.endswith('.json')])
                
                # 检查设置
                if os.path.exists(os.path.join(user_dir, "settings.json")):
                    total_settings_fs += 1
    
    print('\n数据库统计:')
    print(f'  对话记录: {total_convs_db} 个')
    print(f'  消息总数: {total_messages_db} 条')
    print(f'  用户设置: {total_settings_db} 个用户')
    
    print('\n文件系统统计:')
    print(f'  对话记录: {total_convs_fs} 个')
    print(f'  用户设置: {total_settings_fs} 个用户')
    
    print('\n' + '=' * 60)
    print('迁移状态分析:')
    
    if total_convs_db > 0:
        print(f'✅ 对话记录已迁移到数据库 ({total_convs_db} 个)')
    elif total_convs_fs > 0:
        print(f'❌ 对话记录仍在文件系统中 ({total_convs_fs} 个)，需要迁移')
    else:
        print(f'ℹ️ 没有对话记录需要迁移')
    
    if total_settings_db > 0:
        print(f'✅ 用户设置已迁移到数据库 ({total_settings_db} 个用户)')
    elif total_settings_fs > 0:
        print(f'❌ 用户设置仍在文件系统中 ({total_settings_fs} 个用户)，需要迁移')
    else:
        print(f'ℹ️ 没有用户设置需要迁移')
    
    if total_convs_fs == 0 and total_settings_fs == 0:
        print('\n✅ 所有数据已完全迁移到数据库！')
    elif total_convs_fs > 0 or total_settings_fs > 0:
        print('\n⚠️ 仍有数据在文件系统中，建议运行迁移脚本:')
        print('  python -m backend.db.migrate')

if __name__ == '__main__':
    asyncio.run(check_migration_status())
