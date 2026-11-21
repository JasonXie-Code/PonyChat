"""更新 Jason 用户的密码（从备份文件或手动设置）"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import asyncio
import json
import hashlib
from pathlib import Path
sys.path.insert(0, '.')

from backend.db import get_database, get_users_dao

async def update_jason_password():
    db = get_database('database/ponychat.db')
    await db.init()
    dao = get_users_dao()
    
    # 检查 Jason 用户
    user = await dao.get_user('Jason')
    if not user:
        print('ERROR: Jason 用户不存在')
        return
    
    print(f'当前 Jason 用户数据:')
    print(f'  password_hash: {user.get("password_hash")}')
    print(f'  password: {user.get("password")}')
    
    # 尝试从备份文件读取
    backup_file = Path('backups/用户信息备份/users.json')
    if backup_file.exists():
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                backup_users = json.load(f)
            
            if 'Jason' in backup_users:
                backup_data = backup_users['Jason']
                backup_hash = backup_data.get('password_hash')
                backup_password = backup_data.get('password')
                
                print(f'\n从备份文件找到 Jason 用户数据:')
                print(f'  password_hash: {backup_hash[:30] if backup_hash else "None"}...')
                print(f'  password: {backup_password[:10] if backup_password else "None"}...')
                
                if backup_hash or backup_password:
                    # 更新数据库
                    success = await dao.update_user(
                        'Jason',
                        password_hash=backup_hash,
                        password=backup_password,
                        gender=backup_data.get('gender', 'male'),
                        theme=backup_data.get('theme', 'dark')
                    )
                    if success:
                        print(f'OK: Jason 用户密码已从备份恢复')
                    else:
                        print(f'ERROR: 更新密码失败')
                    return
        
        except Exception as e:
            print(f'WARNING: 读取备份文件失败: {e}')
    
    # 如果没有备份，提示用户手动设置
    print('\n未找到备份数据，需要手动设置密码')
    print('请输入要为 Jason 用户设置的新密码（留空则跳过）:')
    new_password = input().strip()
    
    if new_password:
        password_hash = hashlib.sha256(new_password.encode()).hexdigest()
        success = await dao.update_user('Jason', password_hash=password_hash, password=new_password)
        if success:
            print(f'OK: Jason 用户密码已更新')
        else:
            print(f'ERROR: 更新密码失败')
    else:
        print('跳过密码设置')

if __name__ == '__main__':
    asyncio.run(update_jason_password())
