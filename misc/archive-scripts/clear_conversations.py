# -*- coding: utf-8 -*-
"""清空数据库中的所有对话内容、游戏内容"""
import sqlite3
import sys
import os
import io

# Windows 控制台 UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    db_path = "database/ponychat.db"
    if not os.path.exists(db_path):
        print(f"[ERROR] 数据库不存在: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    tables_to_clear = [
        ("messages", "消息"),
        ("galgame_messages", "Galgame 消息"),
        ("conversations", "对话"),
        ("galgame_data", "Galgame 数据"),
    ]

    for table, name in tables_to_clear:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            cursor.execute(f"DELETE FROM {table}")
            conn.commit()
            print(f"[OK] 已清空 {name} ({table}): {count} 条记录")
        except Exception as e:
            print(f"[WARN] 清空 {table} 失败: {e}")

    conn.close()
    print("\n[OK] 数据库对话内容已全部清空")
    return 0

if __name__ == "__main__":
    sys.exit(main())
