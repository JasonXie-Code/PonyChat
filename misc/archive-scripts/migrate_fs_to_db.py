"""
文件系统 → 数据库 迁移脚本
将 user_data/ 目录下所有用户的对话数据迁移到 SQLite 数据库中。

支持的数据源格式：
  1. 新格式分文件: user_data/{user}/conversations/{charId}/{convId}.json
  2. 旧格式单文件: user_data/{user}/conversations/{charId}.json
  3. 遗留大文件:   user_data/{user}/conversations.json
  4. Galgame 分文件: user_data/{user}/galgame/{charId}.json

用法:
  python migrate_fs_to_db.py          # 预览模式（不写入）
  python migrate_fs_to_db.py --apply  # 正式迁移
"""

import sqlite3
import json
import os
import sys
import io

# 修复 Windows GBK 控制台编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─── 路径配置 ───
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_ROOT, "database", "ponychat.db")
USER_DATA_ROOT = os.path.join(PROJECT_ROOT, "user_data")

DRY_RUN = "--apply" not in sys.argv


def get_user_id(conn, username):
    """获取用户 ID，不存在则返回 None"""
    cur = conn.execute("SELECT id FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    return row[0] if row else None


def ensure_character_exists(conn, char_id, user_id, char_name="迁移角色"):
    """确保角色在数据库中存在，不存在则创建占位符"""
    cur = conn.execute(
        "SELECT id FROM characters WHERE id = ? AND user_id = ?",
        (char_id, user_id)
    )
    if cur.fetchone():
        return True
    # 创建占位符角色
    conn.execute(
        """INSERT OR IGNORE INTO characters
           (id, user_id, name, avatar, prompt, bio, data)
           VALUES (?, ?, ?, NULL, '', '', ?)""",
        (char_id, user_id, char_name, json.dumps({"id": char_id}))
    )
    return False


def conversation_exists_in_db(conn, conv_id):
    """检查对话是否已存在于数据库"""
    cur = conn.execute("SELECT id FROM conversations WHERE id = ?", (conv_id,))
    return cur.fetchone() is not None


def insert_conversation(conn, user_id, char_id, conv_data):
    """
    插入一个对话及其所有消息到数据库。
    返回 (inserted_conv, inserted_msgs) 数量。
    """
    conv_id = conv_data.get("id")
    if not conv_id:
        return 0, 0

    # 已存在则跳过
    if conversation_exists_in_db(conn, conv_id):
        return 0, 0

    title = conv_data.get("title", "迁移对话")
    timestamp = conv_data.get("timestamp", 0)
    version = conv_data.get("version", 1)
    summary = conv_data.get("summary", "")

    conn.execute(
        """INSERT OR IGNORE INTO conversations
           (id, character_id, user_id, title, timestamp, version, summary, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (conv_id, char_id, user_id, title, timestamp, version, summary)
    )

    messages = conv_data.get("messages", [])
    inserted_msgs = 0
    seen_msg_ids = set()

    for idx, msg in enumerate(messages):
        message_id = msg.get("message_id") or msg.get("id") or f"{conv_id}_msg_{idx}_{timestamp}"
        if message_id in seen_msg_ids:
            continue
        seen_msg_ids.add(message_id)

        msg_id = msg.get("id") or f"{conv_id}_msg_{idx}"
        role = msg.get("role", "user")
        content = msg.get("content", "")
        raw_content = msg.get("rawContent", "")
        image_url = msg.get("image_url")
        # 如果 image_url 不是 base64 data URI 就置空（可能是 null 或相对路径）
        if image_url and not (isinstance(image_url, str) and image_url.startswith("data:image")):
            image_url = None
        image_thumbnail = msg.get("image_thumbnail")
        msg_timestamp = msg.get("timestamp", timestamp)
        sequence_number = msg.get("sequence_number", idx)
        previous_message_id = msg.get("previous_message_id")
        suggestions = json.dumps(msg.get("suggestions", [])) if msg.get("suggestions") else None
        client_id = msg.get("client_id")

        try:
            conn.execute(
                """INSERT OR IGNORE INTO messages
                   (id, conversation_id, role, content, raw_content, image_url,
                    timestamp, message_id, sequence_number, previous_message_id,
                    suggestions, client_id, image_thumbnail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (msg_id, conv_id, role, content, raw_content, image_url,
                 msg_timestamp, message_id, sequence_number, previous_message_id,
                 suggestions, client_id, image_thumbnail)
            )
            inserted_msgs += 1
        except sqlite3.IntegrityError as e:
            # message_id UNIQUE 冲突，跳过
            print(f"    ⚠️ 消息冲突跳过: {message_id} ({e})")

    return 1, inserted_msgs


def galgame_exists_in_db(conn, char_id, user_id):
    """检查 Galgame 数据是否已存在"""
    cur = conn.execute(
        "SELECT character_id FROM galgame_data WHERE character_id = ? AND user_id = ?",
        (char_id, user_id)
    )
    return cur.fetchone() is not None


def insert_galgame(conn, user_id, char_id, galgame_data):
    """插入 Galgame 数据及其消息，返回插入消息数。"""
    if galgame_exists_in_db(conn, char_id, user_id):
        return 0

    score = galgame_data.get("score", 40)
    status = galgame_data.get("status", "playing")
    version = galgame_data.get("version", 1)

    conn.execute(
        """INSERT OR REPLACE INTO galgame_data
           (character_id, user_id, score, status, version, updated_at)
           VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (char_id, user_id, score, status, version)
    )

    messages = galgame_data.get("messages", [])
    inserted = 0
    seen_msg_ids = set()

    for idx, msg in enumerate(messages):
        message_id = msg.get("message_id") or msg.get("id") or f"gal_{char_id}_msg_{idx}"
        if message_id in seen_msg_ids:
            continue
        seen_msg_ids.add(message_id)

        msg_id = msg.get("id") or f"gal_{char_id}_msg_{idx}"
        role = msg.get("role", "user")
        content = msg.get("content", "")
        raw_content = msg.get("rawContent", "")
        image_url = msg.get("image_url")
        if image_url and not (isinstance(image_url, str) and image_url.startswith("data:image")):
            image_url = None
        image_thumbnail = msg.get("image_thumbnail")
        msg_timestamp = msg.get("timestamp", 0)
        sequence_number = msg.get("sequence_number", idx)
        previous_message_id = msg.get("previous_message_id")
        is_hidden = 1 if msg.get("isHidden") else 0
        suggestions = json.dumps(msg.get("suggestions", [])) if msg.get("suggestions") else None
        client_id = msg.get("client_id")

        try:
            conn.execute(
                """INSERT OR IGNORE INTO galgame_messages
                   (id, character_id, user_id, role, content, raw_content, image_url,
                    timestamp, message_id, sequence_number, previous_message_id,
                    is_hidden, suggestions, client_id, image_thumbnail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (msg_id, char_id, user_id, role, content, raw_content, image_url,
                 msg_timestamp, message_id, sequence_number, previous_message_id,
                 is_hidden, suggestions, client_id, image_thumbnail)
            )
            inserted += 1
        except sqlite3.IntegrityError as e:
            print(f"    ⚠️ Galgame 消息冲突跳过: {message_id} ({e})")

    return inserted


def migrate_user(conn, username, user_dir):
    """迁移单个用户的所有文件系统数据"""
    user_id = get_user_id(conn, username)
    if user_id is None:
        print(f"  ⚠️ 用户 {username} 不在数据库中，跳过")
        return 0, 0, 0

    total_convs = 0
    total_msgs = 0
    total_galgame_msgs = 0

    # ──────────────────────────────────────────────
    # 1. 新格式：conversations/{charId}/{convId}.json
    # ──────────────────────────────────────────────
    convs_dir = os.path.join(user_dir, "conversations")
    if os.path.isdir(convs_dir):
        for char_id in os.listdir(convs_dir):
            char_path = os.path.join(convs_dir, char_id)

            # 1a. 子目录结构: conversations/{charId}/{convId}.json
            if os.path.isdir(char_path):
                ensure_character_exists(conn, char_id, user_id)
                for fname in os.listdir(char_path):
                    if not fname.endswith(".json"):
                        continue
                    fpath = os.path.join(char_path, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            conv_data = json.load(f)
                        if isinstance(conv_data, dict) and conv_data.get("id"):
                            c, m = insert_conversation(conn, user_id, char_id, conv_data)
                            if c > 0:
                                print(f"    ✅ [{username}] {char_id[:16]}... / {conv_data['id']} → {m} 条消息")
                            total_convs += c
                            total_msgs += m
                    except Exception as e:
                        print(f"    ❌ 读取失败: {fpath} ({e})")

            # 1b. 旧格式单文件: conversations/{charId}.json
            elif char_path.endswith(".json") and os.path.isfile(char_path):
                cid = char_id.replace(".json", "")
                ensure_character_exists(conn, cid, user_id)
                try:
                    with open(char_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        # 检查是 conversations 结构 还是 消息列表
                        if len(data) > 0 and isinstance(data[0], dict):
                            if data[0].get("id") and data[0].get("messages") is not None:
                                # conversations 结构
                                for conv_data in data:
                                    c, m = insert_conversation(conn, user_id, cid, conv_data)
                                    if c > 0:
                                        print(f"    ✅ [{username}] {cid[:16]}... / {conv_data.get('id','')} → {m} 条消息")
                                    total_convs += c
                                    total_msgs += m
                            else:
                                # 旧格式消息列表，包装成对话
                                conv_id = f"migrated_{cid}"
                                ts = data[-1].get("timestamp", 0) if data else 0
                                wrapped = {
                                    "id": conv_id,
                                    "title": "历史对话",
                                    "timestamp": ts,
                                    "messages": data
                                }
                                c, m = insert_conversation(conn, user_id, cid, wrapped)
                                if c > 0:
                                    print(f"    ✅ [{username}] {cid[:16]}... / {conv_id} → {m} 条消息 (旧格式)")
                                total_convs += c
                                total_msgs += m
                except Exception as e:
                    print(f"    ❌ 读取失败: {char_path} ({e})")

    # ──────────────────────────────────────────────
    # 2. 遗留大文件: conversations.json
    # ──────────────────────────────────────────────
    legacy_file = os.path.join(user_dir, "conversations.json")
    if os.path.isfile(legacy_file):
        try:
            with open(legacy_file, "r", encoding="utf-8") as f:
                all_convs = json.load(f)
            if isinstance(all_convs, dict):
                for cid, char_convs in all_convs.items():
                    ensure_character_exists(conn, cid, user_id)
                    if isinstance(char_convs, list) and len(char_convs) > 0:
                        if isinstance(char_convs[0], dict) and char_convs[0].get("id") and char_convs[0].get("messages") is not None:
                            for conv_data in char_convs:
                                c, m = insert_conversation(conn, user_id, cid, conv_data)
                                if c > 0:
                                    print(f"    ✅ [{username}] {cid[:16]}... / {conv_data.get('id','')} → {m} 条消息 (legacy)")
                                total_convs += c
                                total_msgs += m
                        else:
                            conv_id = f"migrated_{cid}"
                            ts = char_convs[-1].get("timestamp", 0) if char_convs else 0
                            wrapped = {
                                "id": conv_id,
                                "title": "历史对话",
                                "timestamp": ts,
                                "messages": char_convs
                            }
                            c, m = insert_conversation(conn, user_id, cid, wrapped)
                            if c > 0:
                                print(f"    ✅ [{username}] {cid[:16]}... / {conv_id} → {m} 条消息 (legacy)")
                            total_convs += c
                            total_msgs += m
        except Exception as e:
            print(f"    ❌ 读取 conversations.json 失败: {e}")

    # ──────────────────────────────────────────────
    # 3. Galgame：galgame/{charId}.json
    # ──────────────────────────────────────────────
    galgame_dir = os.path.join(user_dir, "galgame")
    if os.path.isdir(galgame_dir):
        for fname in os.listdir(galgame_dir):
            if not fname.endswith(".json"):
                continue
            cid = fname.replace(".json", "")
            fpath = os.path.join(galgame_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    gal_data = json.load(f)
                ensure_character_exists(conn, cid, user_id)
                gm = insert_galgame(conn, user_id, cid, gal_data)
                if gm > 0:
                    print(f"    ✅ [{username}] Galgame {cid[:16]}... → {gm} 条消息, 分数: {gal_data.get('score', 40)}")
                total_galgame_msgs += gm
            except Exception as e:
                print(f"    ❌ 读取 Galgame 失败: {fpath} ({e})")

    return total_convs, total_msgs, total_galgame_msgs


def main():
    mode = "预览模式 (添加 --apply 参数执行实际迁移)" if DRY_RUN else "🔥 正式迁移模式"
    print(f"\n{'='*60}")
    print(f"  文件系统 → 数据库 迁移工具")
    print(f"  模式: {mode}")
    print(f"  数据库: {DB_PATH}")
    print(f"  用户数据: {USER_DATA_ROOT}")
    print(f"{'='*60}\n")

    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        sys.exit(1)

    if not os.path.isdir(USER_DATA_ROOT):
        print(f"❌ 用户数据目录不存在: {USER_DATA_ROOT}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    # ─── 迁移前统计 ───
    before_convs = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    before_msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    before_gal = conn.execute("SELECT COUNT(*) FROM galgame_messages").fetchone()[0]
    print(f"📊 迁移前数据库: {before_convs} 个对话, {before_msgs} 条消息, {before_gal} 条 Galgame 消息\n")

    grand_convs = 0
    grand_msgs = 0
    grand_galgame = 0

    # ─── 遍历所有用户目录 ───
    for username in sorted(os.listdir(USER_DATA_ROOT)):
        user_dir = os.path.join(USER_DATA_ROOT, username)
        if not os.path.isdir(user_dir):
            continue
        # 检查是否有需要迁移的数据
        has_convs = os.path.isdir(os.path.join(user_dir, "conversations"))
        has_legacy = os.path.isfile(os.path.join(user_dir, "conversations.json"))
        has_galgame = os.path.isdir(os.path.join(user_dir, "galgame"))
        if not (has_convs or has_legacy or has_galgame):
            continue

        print(f"👤 迁移用户: {username}")
        c, m, g = migrate_user(conn, username, user_dir)
        grand_convs += c
        grand_msgs += m
        grand_galgame += g

        if c == 0 and m == 0 and g == 0:
            print(f"    ℹ️ 无新数据需要迁移（已全部存在于数据库中）")
        print()

    # ─── 提交或回滚 ───
    if DRY_RUN:
        conn.rollback()
        print(f"{'='*60}")
        print(f"  📋 预览结果: 将迁移 {grand_convs} 个对话, {grand_msgs} 条消息, {grand_galgame} 条 Galgame 消息")
        print(f"  ⚠️ 预览模式，未写入数据库。使用 --apply 参数执行实际迁移。")
        print(f"{'='*60}\n")
    else:
        conn.commit()
        after_convs = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        after_msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        after_gal = conn.execute("SELECT COUNT(*) FROM galgame_messages").fetchone()[0]
        print(f"{'='*60}")
        print(f"  ✅ 迁移完成！")
        print(f"  新增: {grand_convs} 个对话, {grand_msgs} 条消息, {grand_galgame} 条 Galgame 消息")
        print(f"  迁移后数据库: {after_convs} 个对话, {after_msgs} 条消息, {after_gal} 条 Galgame 消息")
        print(f"{'='*60}\n")

    conn.close()


if __name__ == "__main__":
    main()
