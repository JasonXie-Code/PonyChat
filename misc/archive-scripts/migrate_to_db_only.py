"""
迁移脚本：清空对话 + 迁移头像到数据库 + 清理文件系统
运行方式：python migrate_to_db_only.py
"""
import os
import sys
import sqlite3
import shutil

DB_PATH = "database/ponychat.db"
AVATARS_ROOT = "database/avatars"
USER_AVATARS_ROOT = os.path.join(AVATARS_ROOT, "user_data")
CHARACTER_AVATARS_ROOT = os.path.join(AVATARS_ROOT, "character_data")
USER_DATA_ROOT = "user_data"


def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 启用外键
    cursor.execute("PRAGMA foreign_keys = ON")

    # ============================================================
    # 1. 创建 avatars 表（如果不存在）
    # ============================================================
    print("\n📦 [1/4] 创建 avatars 表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS avatars (
            filename TEXT PRIMARY KEY,
            data BLOB NOT NULL,
            mime_type TEXT DEFAULT 'image/jpeg',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("   ✅ avatars 表已就绪")

    # ============================================================
    # 2. 清空所有对话内容
    # ============================================================
    print("\n🗑️ [2/4] 清空所有对话内容...")

    # 统计当前数据
    cursor.execute("SELECT COUNT(*) FROM messages")
    msg_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM conversations")
    conv_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM galgame_messages")
    gal_msg_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM galgame_data")
    gal_data_count = cursor.fetchone()[0]

    print(f"   当前数据: {msg_count} 条消息, {conv_count} 个对话, {gal_msg_count} 条游戏消息, {gal_data_count} 个游戏状态")

    cursor.execute("DELETE FROM messages")
    cursor.execute("DELETE FROM conversations")
    cursor.execute("DELETE FROM galgame_messages")
    cursor.execute("DELETE FROM galgame_data")
    conn.commit()

    print(f"   ✅ 已清空所有对话内容")

    # ============================================================
    # 3. 迁移头像文件到数据库
    # ============================================================
    print("\n📸 [3/4] 迁移头像文件到数据库...")
    avatar_count = 0

    # 迁移用户头像
    if os.path.exists(USER_AVATARS_ROOT):
        for username in os.listdir(USER_AVATARS_ROOT):
            user_avatar_dir = os.path.join(USER_AVATARS_ROOT, username)
            if not os.path.isdir(user_avatar_dir):
                continue
            for filename in os.listdir(user_avatar_dir):
                filepath = os.path.join(user_avatar_dir, filename)
                if not os.path.isfile(filepath):
                    continue
                try:
                    with open(filepath, 'rb') as f:
                        data = f.read()
                    # 判断 MIME 类型
                    mime = "image/jpeg"
                    if filename.lower().endswith(".png"):
                        mime = "image/png"
                    elif filename.lower().endswith(".webp"):
                        mime = "image/webp"
                    # 使用完整相对路径作为key，方便查找
                    avatar_key = filename
                    cursor.execute(
                        "INSERT OR REPLACE INTO avatars (filename, data, mime_type) VALUES (?, ?, ?)",
                        (avatar_key, data, mime)
                    )
                    avatar_count += 1
                    print(f"   📸 用户头像: {username}/{filename} ({len(data)} bytes)")
                except Exception as e:
                    print(f"   ⚠️ 迁移失败: {filepath}: {e}")

    # 迁移角色头像
    if os.path.exists(CHARACTER_AVATARS_ROOT):
        for filename in os.listdir(CHARACTER_AVATARS_ROOT):
            filepath = os.path.join(CHARACTER_AVATARS_ROOT, filename)
            if not os.path.isfile(filepath):
                continue
            try:
                with open(filepath, 'rb') as f:
                    data = f.read()
                mime = "image/jpeg"
                if filename.lower().endswith(".png"):
                    mime = "image/png"
                elif filename.lower().endswith(".webp"):
                    mime = "image/webp"
                avatar_key = filename
                cursor.execute(
                    "INSERT OR REPLACE INTO avatars (filename, data, mime_type) VALUES (?, ?, ?)",
                    (avatar_key, data, mime)
                )
                avatar_count += 1
                print(f"   📸 角色头像: {filename} ({len(data)} bytes)")
            except Exception as e:
                print(f"   ⚠️ 迁移失败: {filepath}: {e}")

    conn.commit()
    print(f"   ✅ 已迁移 {avatar_count} 个头像到数据库")

    # ============================================================
    # 4. 清理文件系统目录
    # ============================================================
    print("\n🧹 [4/4] 清理文件系统目录...")

    # 清理 user_data 目录
    if os.path.exists(USER_DATA_ROOT):
        shutil.rmtree(USER_DATA_ROOT)
        print(f"   🗑️ 已删除: {USER_DATA_ROOT}/")

    # 清理头像文件目录（数据已迁移到数据库）
    if os.path.exists(AVATARS_ROOT):
        shutil.rmtree(AVATARS_ROOT)
        print(f"   🗑️ 已删除: {AVATARS_ROOT}/")

    # VACUUM 压缩数据库
    print("\n💾 压缩数据库...")
    cursor.execute("VACUUM")
    conn.commit()

    # 打印最终统计
    cursor.execute("SELECT COUNT(*) FROM avatars")
    final_avatar_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM characters")
    char_count = cursor.fetchone()[0]

    db_size = os.path.getsize(DB_PATH)
    if db_size < 1024:
        size_str = f"{db_size} B"
    elif db_size < 1024 * 1024:
        size_str = f"{db_size / 1024:.1f} KB"
    else:
        size_str = f"{db_size / (1024 * 1024):.1f} MB"

    print(f"\n{'='*50}")
    print(f"✅ 迁移完成！")
    print(f"   数据库: {DB_PATH} ({size_str})")
    print(f"   用户: {user_count}")
    print(f"   角色: {char_count}")
    print(f"   头像: {final_avatar_count}")
    print(f"   对话: 0 (已清空)")
    print(f"   游戏数据: 0 (已清空)")
    print(f"{'='*50}")

    conn.close()


if __name__ == "__main__":
    # 切换到项目根目录
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
