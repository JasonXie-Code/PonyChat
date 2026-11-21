"""检查对话记录和设置的迁移状态"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import asyncio
import os
import json
from pathlib import Path
sys.path.insert(0, '.')

from backend.db import get_database, ConversationsDAO, SettingsDAO, get_users_dao

async def check_migration_status():
    db = get_database('database/ponychat.db')
    await db.init()
    
    users_dao = get_users_dao()
    convs_dao = ConversationsDAO(db)
    settings_dao = SettingsDAO(db)
    
    # 获取所有用户
    users = await users_dao.get_all_users()
    
    print(f'总用户数: {len(users)}')
    print('=' * 60)
    
    total_convs_db = 0
    total_convs_fs = 0
    total_settings_db = 0
    total_settings_fs = 0
    
    for username in users.keys():
        # 检查对话记录
        try:
            convs_in_db = await convs_dao.load_conversations(username, None)  # None 表示加载所有角色的对话
            if isinstance(convs_in_db, dict):
                convs_count_db = sum(len(convs) for convs in convs_in_db.values())
            elif isinstance(convs_in_db, list):
                convs_count_db = len(convs_in_db)
            else:
                convs_count_db = 0
        except Exception as e:
            print(f'  检查对话记录时出错: {e}')
            convs_count_db = 0
        
        # 检查文件系统中的对话
        conv_dir = os.path.join("user_data", username, "conversations")
        convs_count_fs = 0
        if os.path.exists(conv_dir):
            for char_id_dir in os.listdir(conv_dir):
                char_path = os.path.join(conv_dir, char_id_dir)
                if os.path.isdir(char_path):
                    convs_count_fs += len([f for f in os.listdir(char_path) if f.endswith('.json')])
        
        # 检查设置
        settings_in_db = await settings_dao.load_settings(username)
        has_settings_db = settings_in_db is not None
        
        settings_file = os.path.join("user_data", username, "settings.json")
        has_settings_fs = os.path.exists(settings_file)
        
        if convs_count_db > 0 or convs_count_fs > 0 or has_settings_db or has_settings_fs:
            print(f'\n用户: {username}')
            print(f'  对话记录:')
            print(f'    数据库: {convs_count_db} 个')
            print(f'    文件系统: {convs_count_fs} 个')
            if convs_count_db > 0 and convs_count_fs == 0:
                print(f'    ✅ 已完全迁移到数据库')
            elif convs_count_db > 0 and convs_count_fs > 0:
                print(f'    ⚠️ 数据库和文件系统都有数据（需要清理文件系统）')
            elif convs_count_db == 0 and convs_count_fs > 0:
                print(f'    ❌ 仅在文件系统中，未迁移到数据库')
            
            print(f'  用户设置:')
            print(f'    数据库: {"有" if has_settings_db else "无"}')
            print(f'    文件系统: {"有" if has_settings_fs else "无"}')
            if has_settings_db and not has_settings_fs:
                print(f'    ✅ 已完全迁移到数据库')
            elif has_settings_db and has_settings_fs:
                print(f'    ⚠️ 数据库和文件系统都有数据（需要清理文件系统）')
            elif not has_settings_db and has_settings_fs:
                print(f'    ❌ 仅在文件系统中，未迁移到数据库')
        
        total_convs_db += convs_count_db
        total_convs_fs += convs_count_fs
        if has_settings_db:
            total_settings_db += 1
        if has_settings_fs:
            total_settings_fs += 1
    
    print('\n' + '=' * 60)
    print('汇总统计:')
    print(f'  对话记录总数:')
    print(f'    数据库: {total_convs_db} 个')
    print(f'    文件系统: {total_convs_fs} 个')
    print(f'  用户设置:')
    print(f'    数据库: {total_settings_db} 个用户')
    print(f'    文件系统: {total_settings_fs} 个用户')
    
    if total_convs_db > 0 and total_convs_fs == 0 and total_settings_db > 0 and total_settings_fs == 0:
        print('\n✅ 所有数据已完全迁移到数据库')
    elif total_convs_fs > 0 or total_settings_fs > 0:
        print('\n⚠️ 仍有数据在文件系统中，建议运行迁移脚本')

if __name__ == '__main__':
    asyncio.run(check_migration_status())
