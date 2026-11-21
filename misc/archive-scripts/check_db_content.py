# -*- coding: utf-8 -*-
"""检查数据库内容"""
import sqlite3
import sys
import io

# Windows 控制台 UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

def main():
    db_path = "database/ponychat.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cursor.fetchall()
    print("=== 数据库表列表 ===")
    for t in tables:
        print(t[0])

    for t in tables:
        name = t[0]
        cursor.execute("SELECT COUNT(*) FROM " + name)
        count = cursor.fetchone()[0]
        cursor.execute("PRAGMA table_info(" + name + ")")
        cols = cursor.fetchall()
        print("\n=== %s (共%d条记录) ===" % (name, count))
        for c in cols:
            print("  %s (%s)" % (c[1], c[2]))
        if count > 0 and count <= 5:
            cursor.execute("SELECT * FROM " + name)
            rows = cursor.fetchall()
            for r in rows:
                short = repr(r[:5]) + ("..." if len(r) > 5 else "")
                print("  示例: " + short)
        elif count > 5:
            cursor.execute("SELECT * FROM " + name + " LIMIT 2")
            rows = cursor.fetchall()
            for r in rows:
                short = repr(r[:5]) + ("..." if len(r) > 5 else "")
                print("  示例: " + short)
            print("  ... 共%d条" % count)

    conn.close()

if __name__ == "__main__":
    main()
