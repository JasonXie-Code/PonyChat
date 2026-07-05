#!/usr/bin/env python3
"""
数据库紧急抢救脚本：
1) 检查所有候选 .db 文件的完整性
2) 尝试 WAL checkpoint
3) 用 Python 逐表从损坏库中读取可读数据，写入干净新库
"""
import sqlite3
import shutil
import sys
import os
from pathlib import Path
import sys

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import (
    backend_package_dir,
    default_backup_dir,
    default_database_path,
    resolve_project_root,
)

PROJECT_ROOT = resolve_project_root(Path(__file__))
_BACKEND = backend_package_dir(PROJECT_ROOT)
DB_PATH = default_database_path(PROJECT_ROOT)
BACKUP_DIR = default_backup_dir(PROJECT_ROOT)

# 从 backend/db/database.py 中提取建表 SQL
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    settings TEXT,
    avatar TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS characters (
    id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    avatar TEXT,
    prompt TEXT,
    bio TEXT,
    data TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, user_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    title TEXT,
    timestamp INTEGER,
    version INTEGER DEFAULT 1,
    summary TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, user_id),
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    raw_content TEXT,
    image_url TEXT,
    timestamp INTEGER NOT NULL,
    message_id TEXT UNIQUE,
    sequence_number INTEGER,
    previous_message_id TEXT,
    is_hidden INTEGER DEFAULT 0,
    suggestions TEXT,
    client_id TEXT,
    image_thumbnail TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS galgame_data (
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER DEFAULT 40,
    status TEXT DEFAULT 'playing',
    version INTEGER DEFAULT 1,
    force_clear INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (character_id, user_id),
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS galgame_messages (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    raw_content TEXT,
    image_url TEXT,
    timestamp INTEGER NOT NULL,
    message_id TEXT UNIQUE,
    sequence_number INTEGER,
    previous_message_id TEXT,
    is_hidden INTEGER DEFAULT 0,
    suggestions TEXT,
    client_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS galgame_lock_data (
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER DEFAULT 40,
    status TEXT DEFAULT 'playing',
    version INTEGER DEFAULT 1,
    force_clear INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (character_id, user_id),
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS galgame_lock_messages (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    raw_content TEXT,
    image_url TEXT,
    timestamp INTEGER NOT NULL,
    message_id TEXT UNIQUE,
    sequence_number INTEGER,
    previous_message_id TEXT,
    is_hidden INTEGER DEFAULT 0,
    suggestions TEXT,
    client_id TEXT,
    image_thumbnail TEXT,
    galgame_options TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS avatars (
    filename TEXT PRIMARY KEY,
    data BLOB NOT NULL,
    content_type TEXT DEFAULT 'image/jpeg',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def check(path):
    """返回 (ok, msg, readable_tables, total_rows)"""
    if not path.exists():
        return False, "not found", [], 0
    try:
        conn = sqlite3.connect(str(path), timeout=5)
        cur = conn.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        ok = row and row[0] == "ok"
        msg = row[0] if row else "unknown"
    except Exception as e:
        ok = False
        msg = str(e)
        try:
            conn.close()
        except:
            pass
        return ok, msg, [], 0

    # 即使 integrity_check 不通过，也试着读表
    tables = []
    total = 0
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tnames = [r[0] for r in cur.fetchall()]
        for t in tnames:
            try:
                c = conn.execute(f"SELECT COUNT(*) FROM [{t}]")
                n = c.fetchone()[0]
                tables.append((t, n))
                total += n
            except:
                tables.append((t, -1))  # 不可读
    except:
        pass
    conn.close()
    return ok, msg, tables, total


def rescue_from(src_path, dst_path):
    """从 src_path（可能损坏）逐表读取数据写入 dst_path（干净新库）。返回抢救到的总行数。"""
    if dst_path.exists():
        dst_path.unlink()

    conn_dst = sqlite3.connect(str(dst_path))
    # 创建 schema
    for stmt in SCHEMA_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn_dst.execute(stmt)
            except:
                pass
    conn_dst.commit()

    conn_src = sqlite3.connect(str(src_path), timeout=10)
    total_rescued = 0

    try:
        cur = conn_src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tnames = [r[0] for r in cur.fetchall()]
    except:
        tnames = []

    for t in tnames:
        try:
            cur = conn_src.execute(f"PRAGMA table_info([{t}])")
            cols = [r[1] for r in cur.fetchall()]
            if not cols:
                continue
            placeholders = ",".join("?" * len(cols))

            cur = conn_src.execute(f"SELECT * FROM [{t}]")
            rows = cur.fetchall()
            if not rows:
                continue

            for row in rows:
                try:
                    conn_dst.execute(f"INSERT OR REPLACE INTO [{t}] VALUES ({placeholders})", row)
                except:
                    pass
            conn_dst.commit()
            total_rescued += len(rows)
            print(f"    {t}: {len(rows)} rows")
        except Exception as e:
            print(f"    {t}: FAILED ({e})")

    conn_src.close()
    conn_dst.close()
    return total_rescued


def main():
    print("=" * 60)
    print("  PonyChat 数据库紧急抢救")
    print("=" * 60)

    # 1. 列出所有候选 .db
    candidates = []
    candidates.append(("ponychat.db (main)", DB_PATH))
    for p in sorted((_BACKEND / "database").glob("*.db")):
        if p != DB_PATH:
            candidates.append((p.name, p))
    candidates.append(("emergency_20260213_012100.db", BACKUP_DIR / "emergency_20260213_012100.db"))
    candidates.append(("ponychat_before_restore_20260214.db", BACKUP_DIR / "ponychat_before_restore_20260214.db"))

    print("\n[1/3] 检查所有候选数据库文件...\n")
    best_intact = None
    best_readable = None
    best_rows = 0

    for label, path in candidates:
        if not path.exists():
            continue
        ok, msg, tables, total = check(path)
        status = "OK" if ok else "DAMAGED"
        size_mb = path.stat().st_size / 1024 / 1024
        print(f"  {label} ({size_mb:.1f}MB) -> {status}, {total} rows readable")
        if ok and (best_intact is None):
            best_intact = (label, path, total)
        if total > best_rows:
            best_rows = total
            best_readable = (label, path, total)

    # 2. WAL checkpoint 检查点
    print("\n[2/3] 尝试 WAL checkpoint...")
    wal_path = DB_PATH.parent / (DB_PATH.name + "-wal")
    if wal_path.exists() and wal_path.stat().st_size > 0:
        print(f"  WAL 文件存在 ({wal_path.stat().st_size / 1024:.1f}KB)")
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            print("  WAL checkpoint 成功")
            # 重新检查
            ok, msg, tables, total = check(DB_PATH)
            if ok:
                print("  checkpoint 后主库完整性恢复正常!")
                best_intact = ("ponychat.db (after checkpoint)", DB_PATH, total)
        except Exception as e:
            print(f"  WAL checkpoint 失败: {e}")
    else:
        print("  无 WAL 文件或为空")

    # 3. 选择恢复策略
    print("\n[3/3] 恢复策略...\n")

    if best_intact:
        label, path, total = best_intact
        print(f"  找到完好数据库: {label} ({total} rows)")
        if path != DB_PATH:
            damaged = DB_PATH.parent / "ponychat_damaged.db"
            if not damaged.exists():
                shutil.copy2(DB_PATH, damaged)
            shutil.copy2(path, DB_PATH)
            print(f"  已用 {label} 覆盖主库")
        print("  请重启后端服务。")
        return 0

    if best_readable:
        label, path, total = best_readable
        print(f"  无完好数据库，从最多数据的文件抢救: {label} ({total} rows)")
        new_db = DB_PATH.parent / "ponychat_rescued.db"
        print(f"  正在逐表抢救数据...")
        rescued = rescue_from(path, new_db)
        print(f"  共抢救 {rescued} 行数据")
        ok, _, _, _ = check(new_db)
        print(f"  新库完整性: {'OK' if ok else 'partial'}")
        damaged = DB_PATH.parent / "ponychat_damaged.db"
        if not damaged.exists():
            shutil.copy2(DB_PATH, damaged)
        shutil.copy2(new_db, DB_PATH)
        print(f"  已用抢救后的数据库覆盖主库，请重启后端服务。")
        return 0

    print("  无法读取任何数据。请手动从 manual_backup_*.zip 中恢复。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
