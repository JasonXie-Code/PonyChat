import os
import sqlite3
import sys
from pathlib import Path

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import default_database_path, resolve_project_root

_db = os.environ.get("PONYCHAT_DB_PATH") or str(
    default_database_path(resolve_project_root(Path(__file__)))
)
db = sqlite3.connect(_db)
c = db.cursor()

tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Tables:", tables)

if 'characters' in tables:
    # 各用户角色数（含隐藏状态分类）
    rows = c.execute("""
        SELECT u.username,
               COUNT(*) as total,
               SUM(CASE WHEN COALESCE(c.is_hidden,0)=0 THEN 1 ELSE 0 END) as visible,
               SUM(CASE WHEN c.is_hidden=1 THEN 1 ELSE 0 END) as hidden
        FROM characters c
        JOIN users u ON u.id = c.user_id
        GROUP BY u.username
        ORDER BY total DESC
    """).fetchall()
    print("\nusername | total | visible | hidden")
    for r in rows:
        print(r)

    # 检查是否有 user_id 为 NULL 或 0 的记录
    orphans = c.execute("""
        SELECT COUNT(*) FROM characters
        WHERE user_id IS NULL OR user_id NOT IN (SELECT id FROM users)
    """).fetchone()[0]
    print(f"\nOrphaned characters (no valid user_id): {orphans}")

db.close()
