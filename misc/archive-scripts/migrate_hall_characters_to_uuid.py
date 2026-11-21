#!/usr/bin/env python3
"""
将「从角色大厅添加」的旧角色 id 迁移为唯一 UUID（一角色一 id）。

迁移对象：data JSON 中含有 originalId 的角色（即当年用 originalId_timestamp 作为 id 添加的）。
操作：为每个这样的角色生成新 UUID，更新 characters / conversations / galgame_data / galgame_messages，
     然后删除旧 character 行，保证全链路只用一个 id。

用法（项目根目录）:
  python misc/tmp-scripts/migrate_hall_characters_to_uuid.py              # 迁移所有用户
  python misc/tmp-scripts/migrate_hall_characters_to_uuid.py Jason        # 仅迁移指定用户
  python misc/tmp-scripts/migrate_hall_characters_to_uuid.py --dry-run    # 仅预览，不写库

Windows 控制台乱码时可在运行前设置: set PYTHONIOENCODING=utf-8
"""
import asyncio
import json
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

DB_PATH = os.path.join(ROOT, "database", "ponychat.db")


def is_plain_uuid(s: str) -> bool:
    """标准 UUID 格式 8-4-4-4-12，已是新 id 的不再迁移。"""
    if not s or len(s) != 36:
        return False
    parts = s.split("-")
    if len(parts) != 5:
        return False
    if len(parts[0]) != 8 or len(parts[1]) != 4 or len(parts[2]) != 4 or len(parts[3]) != 4 or len(parts[4]) != 12:
        return False
    hex_chars = set("0123456789abcdef")
    return all(len(p) == len(set(p) & hex_chars) for p in parts)


def need_migrate(char_id: str, data_json: str) -> bool:
    """仅当 id 仍为旧格式（含 _ 时间戳或短 id）且非已迁移的 UUID 时才迁移。"""
    if not char_id:
        return False
    if is_plain_uuid(char_id):
        return False
    try:
        data = json.loads(data_json or "{}")
        if not data.get("originalId"):
            return False
    except Exception:
        return False
    # 旧格式：xxx_timestamp（例如 UUID_1766940497360 或短 id_1766940497360）
    if "_" in char_id:
        tail = char_id.split("_")[-1]
        if tail.isdigit() and len(tail) >= 10:
            return True
    # 短 id（无 _ 但来自大厅，originalId 存在则可能是旧数据里的短 id 记录）
    if len(char_id) < 36 and "_" not in char_id:
        return True
    return False


async def migrate_one(conn, old_id: str, user_id: int, name: str, avatar, prompt: str, bio: str, data_json: str, sort_order, created_at, updated_at) -> str:
    """将一名角色从 old_id 迁移到新 UUID。返回 new_id。"""
    new_id = str(uuid.uuid4())
    data = json.loads(data_json)
    data["id"] = new_id
    new_data_json = json.dumps(data, ensure_ascii=False)

    await conn.execute(
        """INSERT INTO characters (id, user_id, name, avatar, prompt, bio, data, sort_order, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (new_id, user_id, name, avatar, prompt, bio, new_data_json, sort_order, created_at, updated_at),
    )

    await conn.execute("UPDATE conversations SET character_id = ? WHERE character_id = ? AND user_id = ?", (new_id, old_id, user_id))

    # galgame_data: PK (character_id, user_id)，需先插新行再删旧行
    async with conn.execute(
        "SELECT score, status, version, COALESCE(force_clear, 0) FROM galgame_data WHERE character_id = ? AND user_id = ?",
        (old_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    if row:
        score, status, version, force_clear = row
        await conn.execute(
            """INSERT OR REPLACE INTO galgame_data (character_id, user_id, score, status, version, force_clear, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (new_id, user_id, score, status, version, force_clear),
        )
        await conn.execute("DELETE FROM galgame_data WHERE character_id = ? AND user_id = ?", (old_id, user_id))

    await conn.execute("UPDATE galgame_messages SET character_id = ? WHERE character_id = ? AND user_id = ?", (new_id, old_id, user_id))
    await conn.execute("DELETE FROM characters WHERE id = ? AND user_id = ?", (old_id, user_id))
    return new_id


async def main():
    dry_run = "--dry-run" in sys.argv
    argv = [a for a in sys.argv[1:] if a != "--dry-run"]
    username_filter = argv[0] if argv else None

    if not os.path.isfile(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        return

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")

        if username_filter:
            async with conn.execute("SELECT id, username FROM users WHERE username = ?", (username_filter,)) as cur:
                rows = await cur.fetchall()
            if not rows:
                print(f"用户不存在: {username_filter}")
                return
            user_list = [(r[0], r[1]) for r in rows]
        else:
            async with conn.execute("SELECT id, username FROM users") as cur:
                user_list = await cur.fetchall()

        to_migrate = []
        async with conn.execute(
            """SELECT c.id, c.user_id, u.username, c.name, c.avatar, c.prompt, c.bio, c.data,
                      c.sort_order, c.created_at, c.updated_at
               FROM characters c
               JOIN users u ON c.user_id = u.id"""
        ) as cur:
            async for row in cur:
                char_id, user_id, username, name, avatar, prompt, bio, data_json, sort_order, created_at, updated_at = row
                if not need_migrate(char_id, data_json or "{}"):
                    continue
                if username_filter and username_filter != username:
                    continue
                to_migrate.append((char_id, user_id, username, name, avatar, prompt, bio, data_json, sort_order, created_at, updated_at))

        if not to_migrate:
            print("没有需要迁移的角色（无 originalId 或非 originalId_timestamp 格式）。")
            return

        print(f"共 {len(to_migrate)} 个角色待迁移。" + (" [dry-run 仅预览]" if dry_run else ""))
        for t in to_migrate:
            old_id, user_id, username, name, *_ = t
            print(f"  - {username} / {name or '?'}  id: {old_id[:24]}...")

        if dry_run:
            print("dry-run 结束，未写入数据库。")
            return

        migrated = 0
        await conn.execute("BEGIN IMMEDIATE")
        try:
            for t in to_migrate:
                old_id, user_id, username, name, avatar, prompt, bio, data_json, sort_order, created_at, updated_at = t
                new_id = await migrate_one(
                    conn, old_id, user_id, name, avatar, prompt, bio, data_json,
                    sort_order, created_at, updated_at,
                )
                migrated += 1
                print(f"  [OK] {username} / {name or '?'}  {old_id[:16]}... -> {new_id[:16]}...")
            await conn.commit()
        except Exception as e:
            await conn.execute("ROLLBACK")
            print("Migration rolled back:", e)
            raise
        print(f"Done. Migrated {migrated} character(s) to new UUID.")


if __name__ == "__main__":
    asyncio.run(main())
