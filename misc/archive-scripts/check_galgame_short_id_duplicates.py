#!/usr/bin/env python3
"""
检查 galgame_data / galgame_messages 中是否存在「短 id」记录及与完整 UUID 的重复。
若存在同一角色两条记录（如 5b35488a 0 条 + 5b35488a-241f-... 50 条），说明曾因 id 不一致误写过，短 id 空记录可清理。
用法（项目根目录）:
  python misc/tmp-scripts/check_galgame_short_id_duplicates.py [用户名]
  不传用户则检查所有用户。
Windows 控制台乱码时可在运行前设置: set PYTHONIOENCODING=utf-8
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# 视为「短 id」：无连字符的纯数字或短字符串（如 5b35488a、1766940497360），或长度 < 20
def is_likely_short_id(cid: str) -> bool:
    if not cid or len(cid) >= 36:
        return False
    if "-" in cid and len(cid) >= 30:
        return False  # 完整 UUID
    if "_" in cid:
        return False  # 大厅添加格式 originalId_timestamp 保留
    return True

async def main():
    username = (sys.argv[1:] or [None])[0] if sys.argv[1:] else None
    db_path = os.path.join(ROOT, "database", "ponychat.db")
    if not os.path.isfile(db_path):
        print(f"数据库不存在: {db_path}")
        return

    import aiosqlite
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        if username:
            async with conn.execute("SELECT id FROM users WHERE username = ?", (username,)) as cur:
                row = await cur.fetchone()
            if not row:
                print(f"用户不存在: {username}")
                return
            user_ids = [row["id"]]
            user_names = [username]
        else:
            async with conn.execute("SELECT id, username FROM users") as cur:
                rows = await cur.fetchall()
            user_ids = [r["id"] for r in rows]
            user_names = [r["username"] for r in rows]

        for uid, uname in zip(user_ids, user_names):
            async with conn.execute(
                """SELECT g.character_id, g.score, g.updated_at,
                          (SELECT COUNT(*) FROM galgame_messages m WHERE m.character_id = g.character_id AND m.user_id = g.user_id) AS msg_count
                   FROM galgame_data g WHERE g.user_id = ? ORDER BY g.character_id""",
                (uid,),
            ) as cur:
                rows = await cur.fetchall()

            if not rows:
                continue
            print(f"\n=== 用户 {uname} (user_id={uid}) Galgame 记录 ===\n")
            for r in rows:
                cid = r["character_id"]
                msg_count = r["msg_count"] or 0
                score = r["score"]
                updated = r["updated_at"] or ""
                short = " [短 id]" if is_likely_short_id(cid) else ""
                empty = " [0 条，可能误写]" if is_likely_short_id(cid) and msg_count == 0 else ""
                print(f"  character_id: {cid}  消息数: {msg_count}  分数: {score}  更新: {updated}{short}{empty}")
            # 同前缀多条：如 5b35488a 与 5b35488a-241f-...
            prefixes = {}
            for r in rows:
                cid = r["character_id"]
                pre = (cid.split("-")[0] if "-" in cid else cid).split("_")[0]
                if len(pre) < 20:
                    prefixes.setdefault(pre, []).append(r)
            for pre, list_r in prefixes.items():
                if len(list_r) < 2:
                    continue
                short_empty = [r for r in list_r if is_likely_short_id(r["character_id"]) and (r["msg_count"] or 0) == 0]
                long_with_data = [r for r in list_r if not is_likely_short_id(r["character_id"]) or (r["msg_count"] or 0) > 0]
                if short_empty and long_with_data:
                    print(f"\n  [同前缀重复] 前缀 {pre}: 短 id 空记录 {[r['character_id'] for r in short_empty]}, 有数据记录 {[r['character_id'] for r in long_with_data]}")

    print("\n--- 说明 ---")
    print("若存在「同一角色两条：一条短 id 0 条、一条完整 UUID 多条」，说明曾因 character_id 不一致误写过。")
    print("修复后新保存会写到解析出的那条（完整 UUID）。短 id 空记录可用管理端或脚本删除，避免加载时被错误命中。")

if __name__ == "__main__":
    asyncio.run(main())
