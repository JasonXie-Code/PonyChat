#!/usr/bin/env python3
"""删除某用户在所有角色下的 character_memories（碎片+日/周/月/年层），不动 normal_chat_memory 与对话。"""
from __future__ import annotations

import os
import sqlite3
import sys

def main() -> int:
    username = (sys.argv[1] if len(sys.argv) > 1 else "Jason").strip()
    if len(sys.argv) > 2 and (sys.argv[2] or "").strip():
        db = os.path.normpath((sys.argv[2] or "").strip())
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db = os.path.join(root, "database", "ponychat.db")
    if not os.path.isfile(db):
        print("DB not found:", db)
        return 1
    conn = sqlite3.connect(db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if not row:
            print("User not found:", username)
            return 2
        uid = row[0]
        cur.execute(
            "SELECT COUNT(*) FROM character_memories WHERE user_id = ?", (uid,)
        )
        before = cur.fetchone()[0]
        cur.execute("DELETE FROM character_memories WHERE user_id = ?", (uid,))
        deleted = cur.rowcount
        conn.commit()
        print(
            f"OK user_id={uid} username={username!r} "
            f"character_memories: deleted {deleted} row(s) (before={before})"
        )
    finally:
        conn.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
