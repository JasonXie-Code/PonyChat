#!/usr/bin/env python3
"""
临时脚本：删除 Jason 用户与紫悦 NSFW 游戏模式的最新一条消息，并将分数设置为 100。
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# 紫悦 NSFW 的 character_id（来自 ChatLogs）
CHAR_ID_ZIYUE_NSFW = "5b35488a-241f-4679-86ca-4b0ac6e287e5"

async def main():
    username = "Jason"
    db_path = os.path.join(ROOT, "database", "ponychat.db")
    if not os.path.isfile(db_path):
        print(f"数据库不存在: {db_path}")
        return

    import aiosqlite
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        # 获取 user_id
        async with conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            print(f"用户不存在: {username}")
            return
        user_id = row["id"]

        # 查找该用户+角色下 sequence_number 最大的消息（最新一条）
        async with conn.execute(
            """SELECT id, role, content, sequence_number
               FROM galgame_messages
               WHERE character_id = ? AND user_id = ?
               ORDER BY sequence_number DESC
               LIMIT 1""",
            (CHAR_ID_ZIYUE_NSFW, user_id),
        ) as cur:
            latest = await cur.fetchone()

        if not latest:
            print(f"未找到 Jason 与紫悦 NSFW 的 Galgame 消息记录。")
            # 仍然尝试更新分数
            await conn.execute(
                """UPDATE galgame_data SET score = 100, updated_at = CURRENT_TIMESTAMP
                   WHERE character_id = ? AND user_id = ?""",
                (CHAR_ID_ZIYUE_NSFW, user_id),
            )
            await conn.commit()
            print("已将分数更新为 100（无消息可删）。")
            return

        msg_id = latest["id"]
        role = latest["role"]
        seq = latest["sequence_number"]
        content_preview = (latest["content"] or "")[:60] + ("..." if len(latest["content"] or "") > 60 else "")
        print(f"即将删除最新消息: id={msg_id}, role={role}, seq={seq}")
        print(f"  内容预览: {content_preview}")

        # 删除该消息
        await conn.execute(
            "DELETE FROM galgame_messages WHERE id = ?",
            (msg_id,),
        )

        # 更新 galgame_data 分数为 100
        await conn.execute(
            """UPDATE galgame_data SET score = 100, updated_at = CURRENT_TIMESTAMP
               WHERE character_id = ? AND user_id = ?""",
            (CHAR_ID_ZIYUE_NSFW, user_id),
        )

        await conn.commit()
        print("[OK] 已删除最新一条消息，并将分数设置为 100。")

if __name__ == "__main__":
    asyncio.run(main())
