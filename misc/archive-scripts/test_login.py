"""测试登录功能"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import asyncio
sys.path.insert(0, '.')

from backend.db import get_database, get_users_dao

async def test_login(username, password):
    db = get_database('database/ponychat.db')
    await db.init()
    dao = get_users_dao()
    
    print(f'测试登录: {username}')
    
    # 先获取用户信息
    user = await dao.get_user(username)
    if not user:
        print(f'ERROR: 用户不存在: {username}')
        return
    
    print(f'OK: 用户存在: {username}')
    print(f'  password_hash: {user.get("password_hash")[:30] if user.get("password_hash") else "None"}...')
    print(f'  password: {user.get("password")[:10] if user.get("password") else "None"}...')
    
    # 测试密码验证
    result = await dao.verify_password(username, password)
    print(f'密码验证结果: {result}')
    
    if result:
        print(f'OK: 密码正确')
    else:
        print(f'ERROR: 密码错误')
        
        # 手动计算哈希看看
        import hashlib
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        print(f'输入的密码哈希: {password_hash[:30]}...')
        print(f'存储的密码哈希: {user.get("password_hash")[:30] if user.get("password_hash") else "None"}...')
        print(f'存储的明文密码: {user.get("password")[:10] if user.get("password") else "None"}...')

if __name__ == '__main__':
    # 测试几个用户
    asyncio.run(test_login('dukenukem', '1234'))
    print('\n' + '='*50 + '\n')
    asyncio.run(test_login('Jason', '271828'))
