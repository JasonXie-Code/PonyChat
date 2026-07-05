#!/usr/bin/env python3
"""快速查看 database/ponychat.db 中的数据概况（用户、角色、对话、消息、Galgame）"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "database", "ponychat.db")

def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("=" * 60)
    print("[DB] database/ponychat.db")
    print("=" * 60)

    # 用户
    cur.execute("SELECT id, username, role FROM users ORDER BY id")
    users = cur.fetchall()
    print(f"\n[Users] {len(users)}")
    for u in users:
        print(f"   - id={u['id']} username={u['username']} role={u['role']}")

    if not users:
        print("   (无用户数据)")
        conn.close()
        return

    # 角色（按用户）
    cur.execute("""
        SELECT c.id, c.user_id, c.name, u.username
        FROM characters c
        JOIN users u ON u.id = c.user_id
        ORDER BY u.username, c.sort_order, c.id
    """)
    chars = cur.fetchall()
    print(f"\n[Characters] {len(chars)}")
    by_user = {}
    for c in chars:
        uname = c["username"]
        by_user.setdefault(uname, []).append(c)
    for uname, list_c in by_user.items():
        print(f"   用户 [{uname}]: {len(list_c)} 个角色")
        for c in list_c[:15]:
            print(f"      - {c['id'][:20]}... name={c['name']}")
        if len(list_c) > 15:
            print(f"      ... 等共 {len(list_c)} 个")

    # 对话（普通模式）：按角色统计
    cur.execute("""
        SELECT conv.character_id, conv.user_id, ch.name AS character_name, u.username,
               COUNT(DISTINCT conv.id) AS conv_count
        FROM conversations conv
        JOIN characters ch ON ch.id = conv.character_id
        JOIN users u ON u.id = conv.user_id
        GROUP BY conv.character_id, conv.user_id
        ORDER BY u.username
    """)
    conv_rows = cur.fetchall()
    cur.execute("""
        SELECT c.character_id, c.user_id, COUNT(m.id) AS msg_count
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        GROUP BY c.character_id, c.user_id
    """)
    msg_counts = {(r["character_id"], r["user_id"]): r["msg_count"] for r in cur.fetchall()}
    print(f"\n[Conversations + Messages]")
    if not conv_rows:
        print("   (无对话数据)")
    else:
        total_conv = sum(r["conv_count"] for r in conv_rows)
        total_msg = 0
        for r in conv_rows:
            key = (r["character_id"], r["user_id"])
            cnt = msg_counts.get(key, 0)
            total_msg += cnt
            name = (r["character_name"] or "未命名")[:12]
            print(f"   - 角色 [{name}] ({r['character_id'][:16]}...) 用户={r['username']} 对话数={r['conv_count']} 消息数={cnt}")
        print(f"   合计: 对话 {total_conv} 条, 消息 {total_msg} 条")

    # Galgame：按角色统计
    cur.execute("""
        SELECT g.character_id, ch.name AS character_name, u.username,
               g.score, g.status,
               (SELECT COUNT(*) FROM galgame_messages gm WHERE gm.character_id = g.character_id AND gm.user_id = g.user_id) AS msg_count
        FROM galgame_data g
        JOIN characters ch ON ch.id = g.character_id
        JOIN users u ON u.id = g.user_id
        ORDER BY u.username, msg_count DESC
    """)
    gal_stats = cur.fetchall()
    print(f"\n[Galgame]")
    if not gal_stats:
        print("   (无 Galgame 数据)")
    else:
        total_gal_msg = sum(r["msg_count"] or 0 for r in gal_stats)
        print(f"   总 Galgame 消息数: {total_gal_msg}")
        for r in gal_stats:
            name = (r["character_name"] or "未命名")[:12]
            print(f"   - 角色 [{name}] ({r['character_id'][:16]}...) 用户={r['username']} 分数={r['score']} 状态={r['status']} 消息数={r['msg_count'] or 0}")

    # 各表总行数
    print("\n[Table row counts]")
    for table in ("users", "characters", "conversations", "messages", "galgame_data", "galgame_messages"):
        cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
        n = cur.fetchone()["n"]
        print(f"   {table}: {n}")

    print("\n" + "=" * 60)
    conn.close()

if __name__ == "__main__":
    main()
