"""为 users 表添加 avatar 字段"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import asyncio
import aiosqlite
sys.path.insert(0, '.')

async def add_avatar_column():
    db_path = 'database/ponychat.db'
    
    async with aiosqlite.connect(db_path) as conn:
        # 检查 avatar 字段是否存在
        async with conn.execute("PRAGMA table_info(users)") as cursor:
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            if 'avatar' in column_names:
                print('OK: avatar 字段已存在')
                return
            
            # 添加 avatar 字段
            try:
                await conn.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
                await conn.commit()
                print('OK: avatar 字段已添加')
            except Exception as e:
                print(f'ERROR: 添加 avatar 字段失败: {e}')

if __name__ == '__main__':
    asyncio.run(add_avatar_column())
