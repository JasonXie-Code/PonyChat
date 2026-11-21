"""检查数据库中的用户数据"""
import sys
import asyncio
sys.path.insert(0, '.')

from backend.db import get_database, get_users_dao

async def check_users():
    db = get_database('database/ponychat.db')
    await db.init()
    dao = get_users_dao()
    
    users = await dao.get_all_users()
    print(f'总用户数: {len(users)}')
    
    if len(users) == 0:
        print('⚠️ 数据库中没有用户！')
        return
    
    for username, user in users.items():
        has_hash = bool(user.get("password_hash"))
        has_password = bool(user.get("password"))
        print(f'  - {username}:')
        print(f'    password_hash: {has_hash}')
        print(f'    password: {has_password}')
        if has_hash:
            print(f'    password_hash值: {user.get("password_hash")[:20]}...')
        if has_password:
            print(f'    password值: {user.get("password")[:10]}...')

if __name__ == '__main__':
    asyncio.run(check_users())
