#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清除所有用户的陪玩记录和陪玩长期记忆（由陪玩运行异常产生的垃圾数据）。

删除范围（仅限以下两张表，其余用户数据完全不动）：
  - companion_sessions  : 所有陪玩会话记录
  - character_memories  : 所有陪玩长期记忆（分层记忆）

不删除：
  - normal_chat_memory  : 普通对话上下文记忆
  - conversations / messages / galgame_data 等所有正常对话数据
  - users / characters 等基础数据

用法（仓库根）:
  python Backend/scripts/clear_companion_data_all_users.py [db_path]
"""
from __future__ import annotations

import os
import sqlite3
import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        db = os.path.normpath(sys.argv[1].strip())
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db = os.path.join(root, "database", "ponychat.db")

    if not os.path.isfile(db):
        print(f"DB not found: {db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db)
    try:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM companion_sessions")
        cs_before = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM character_memories")
        cm_before = cur.fetchone()[0]

        cur.execute("DELETE FROM companion_sessions")
        cs_deleted = cur.rowcount

        cur.execute("DELETE FROM character_memories")
        cm_deleted = cur.rowcount

        conn.commit()

        print(f"companion_sessions : deleted {cs_deleted} / {cs_before} rows")
        print(f"character_memories : deleted {cm_deleted} / {cm_before} rows")
        print("OK - 其余用户数据未修改")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
