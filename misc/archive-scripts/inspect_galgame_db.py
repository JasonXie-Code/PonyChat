#!/usr/bin/env python3
"""
查看数据库中 Galgame 数据：列出指定用户下所有有 Galgame 记录的角色 ID 及消息数。
用法（在项目根目录）: python misc/tmp-scripts/inspect_galgame_db.py [用户名]
默认用户: Jason
"""
import asyncio
import os
import sys

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

async def main():
    username = (sys.argv[1:] or ["Jason"])[0]
    db_path = os.path.join(ROOT, "database", "ponychat.db")
    if not os.path.isfile(db_path):
        print(f"数据库不存在: {db_path}")
        return

    import aiosqlite
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        # 查询 user_id
        async with conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            print(f"用户不存在: {username}")
            return
        user_id = row["id"]

        # 列出该用户所有 galgame_data
        async with conn.execute(
            """SELECT g.character_id, g.score, g.status, g.updated_at,
                      (SELECT COUNT(*) FROM galgame_messages m WHERE m.character_id = g.character_id AND m.user_id = g.user_id) AS msg_count
               FROM galgame_data g
               WHERE g.user_id = ?
               ORDER BY g.updated_at DESC""",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        print(f"用户 {username} 下没有任何 Galgame 记录。")
        print("说明：若之前玩过紫悦等角色的 Galgame，可能从未以当前 character_id 保存成功，或保存的是其他设备/会话。")
        return

    print(f"用户 {username} 的 Galgame 记录（共 {len(rows)} 条）:\n")
    for r in rows:
        cid = r["character_id"]
        msg_count = r["msg_count"] or 0
        score = r["score"]
        updated = r["updated_at"] or ""
        # 紫悦可能用的 id：5b35488a 开头
        mark = "  <-- 可能是紫悦" if cid.startswith("5b35488a") else ""
        print(f"  character_id: {cid}")
        print(f"    消息数: {msg_count}, 分数: {score}, 更新: {updated}{mark}\n")

    # 明确查一次 5b35488a 相关
    print("--- 按 character_id 前缀 5b35488a 查询（紫悦） ---")
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT character_id, score,
                (SELECT COUNT(*) FROM galgame_messages m WHERE m.character_id = g.character_id AND m.user_id = g.user_id) AS msg_count
             FROM galgame_data g
             WHERE user_id = ? AND (character_id = '5b35488a-241f-4679-86ca-4b0ac6e287e5' OR character_id LIKE '5b35488a%')""",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
    if rows:
        for r in rows:
            print(f"  找到: {r['character_id']}, 消息数: {r['msg_count']}, 分数: {r['score']}")
    else:
        print("  未找到 5b35488a 开头的 Galgame 记录（紫悦 NSFW 的 Galgame 从未写入过当前库）。")

if __name__ == "__main__":
    asyncio.run(main())
