#!/usr/bin/env python3
"""
当主库出现 "database disk image is malformed" 时：
1) 优先用通过完整性检查的 backup_*.db 覆盖主库；
2) 若无完好备份，尝试用 SQLite .recover 从损坏库中抢救数据。
使用前请先停止后端服务。
"""
import sqlite3
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Tuple
import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MISC = _REPO_ROOT / "misc"
sys.path.insert(0, str(_MISC))
from project_paths import backend_package_dir, default_backup_dir, default_database_path, resolve_project_root

PROJECT_ROOT = resolve_project_root(_REPO_ROOT)
_BACKEND = backend_package_dir(PROJECT_ROOT)
DB_PATH = default_database_path(PROJECT_ROOT)
BACKUP_DIR = default_backup_dir(PROJECT_ROOT)
_DB_DIR = _BACKEND / "database"


def integrity_check(db_path: Path) -> Tuple[bool, str]:
    """运行 PRAGMA integrity_check，返回 (是否通过, 结果信息)。"""
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        cur = conn.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        conn.close()
        if row and row[0] == "ok":
            return True, "ok"
        return False, (row[0] if row else "unknown")
    except Exception as e:
        return False, str(e)


def main():
    if not DB_PATH.exists():
        print(f"主库不存在: {DB_PATH}")
        return 1

    print("正在检查主库完整性...")
    ok, msg = integrity_check(DB_PATH)
    if ok:
        print("主库完整性正常，无需恢复。")
        return 0

    print(f"主库异常: {msg}")

    backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        print("backups 目录下没有 backup_*.db 文件，无法自动恢复。")
        return 1

    # 从新到旧逐个尝试，找到第一个通过完整性检查的备份
    good_backup = None
    for b in backups:
        ok_b, _ = integrity_check(b)
        if ok_b:
            good_backup = b
            break
        print(f"  跳过（异常）: {b.name}")

    if not good_backup:
        # 尝试用 SQLite .recover 从损坏的主库抢救数据
        print("所有 backup_*.db 均未通过完整性检查，尝试从损坏主库抢救数据...")
        return try_recover_corrupted_db()

    print(f"使用备份: {good_backup.name}")

    # 备份当前损坏的主库（便于排查）
    damaged_path = _DB_DIR / "ponychat_damaged.db"
    try:
        shutil.copy2(DB_PATH, damaged_path)
        print(f"已把当前主库另存为: {damaged_path}")
    except Exception as e:
        print(f"复制损坏文件失败: {e}")

    try:
        shutil.copy2(good_backup, DB_PATH)
        print("已用备份覆盖 database/ponychat.db")
    except Exception as e:
        print(f"覆盖失败: {e}")
        return 1

    ok2, msg2 = integrity_check(DB_PATH)
    if ok2:
        print("恢复后主库完整性检查通过。请重启后端服务。")
        return 0
    print(f"恢复后主库仍异常: {msg2}，请尝试更早的备份或联系维护。")
    return 1


def try_recover_corrupted_db() -> int:
    """用 sqlite3 .recover 从损坏库导出 SQL 再导入新库。需系统有 sqlite3 命令行。"""
    damaged_path = _DB_DIR / "ponychat_damaged.db"
    sql_file = _DB_DIR / "recovered.sql"
    new_db_path = _DB_DIR / "ponychat_new.db"

    if not damaged_path.exists() or damaged_path.stat().st_size == 0:
        try:
            shutil.copy2(DB_PATH, damaged_path)
            print(f"已把当前主库另存为: {damaged_path}")
        except Exception as e:
            print(f"复制损坏文件失败: {e}")

    sqlite3_cmd = shutil.which("sqlite3")
    if not sqlite3_cmd:
        print("未找到 sqlite3 命令行工具。可安装 SQLite 后重试，或从其他备份（如 manual_backup_*.zip）恢复。")
        return 1

    print("正在使用 sqlite3 .recover 抢救数据（可能需数十秒）...")
    try:
        with open(sql_file, "w", encoding="utf-8") as f:
            ret = subprocess.run(
                [sqlite3_cmd, str(DB_PATH), ".recover"],
                stdout=f,
                stderr=subprocess.PIPE,
                timeout=120,
                cwd=str(PROJECT_ROOT),
            )
        if ret.returncode != 0:
            err = (ret.stderr or b"").decode("utf-8", errors="replace").strip()
            print(f"recover 失败 (code={ret.returncode}): {err}")
            return 1
    except subprocess.TimeoutExpired:
        print("recover 超时。")
        return 1
    except Exception as e:
        print(f"recover 异常: {e}")
        return 1

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if new_db_path.exists():
        new_db_path.unlink()
    try:
        with open(sql_file, "r", encoding="utf-8") as f:
            ret2 = subprocess.run(
                [sqlite3_cmd, str(new_db_path)],
                stdin=f,
                timeout=120,
                cwd=str(PROJECT_ROOT),
            )
        if ret2.returncode != 0:
            print("导入 SQL 到新库失败。")
            return 1
    except Exception as e2:
        print(f"导入失败: {e2}")
        return 1

    ok3, _ = integrity_check(new_db_path)
    if not ok3:
        print("抢救出的数据库未通过完整性检查，可能部分数据仍不可用。")
    try:
        shutil.copy2(new_db_path, DB_PATH)
        print("已用抢救后的数据库覆盖 database/ponychat.db，请重启后端服务。")
    except Exception as e4:
        print(f"覆盖失败: {e4}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
