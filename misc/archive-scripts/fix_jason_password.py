"""修复 Jason 用户的密码"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import asyncio
sys.path.insert(0, '.')

from backend.db import get_database, get_users_dao
import hashlib

async def fix_jason_password():
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
    
    # 如果没有密码，设置一个默认密码（需要用户确认）
    if not user.get("password_hash") and not user.get("password"):
        print('\nJason 用户没有密码数据。')
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
    else:
        print('Jason 用户已有密码数据')

if __name__ == '__main__':
    asyncio.run(fix_jason_password())
