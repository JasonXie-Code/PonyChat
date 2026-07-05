"""
数据库定时备份：每 N 分钟检查一次，若数据库有变化才执行备份，最多保留 K 个备份。
与 admin 的备份/恢复共用 backups 目录，恢复可通过 API 指定文件名或索引。
"""
import asyncio
import hashlib
import sqlite3
import os
from pathlib import Path
from datetime import datetime
from ..runtime_paths import resolve_backup_dir, resolve_database_path

# 默认与 admin system 一致
_THIS_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = resolve_database_path(str(_THIS_DIR))
DEFAULT_BACKUP_DIR = Path(resolve_backup_dir(str(_THIS_DIR), DEFAULT_DB_PATH))
BACKUP_KEEP_COUNT = 5
BACKUP_INTERVAL_SEC = 8 * 3600  # 8 小时
_scheduler_started_in_process = False


def check_db_integrity(db_path: str) -> tuple[bool, str]:
    """
    检查 SQLite 数据库完整性。
    返回 (is_ok, message)。is_ok 为 True 表示数据库完好。
    """
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        cur = conn.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        conn.close()
        if row and row[0] == "ok":
            return True, "ok"
        return False, row[0] if row else "integrity_check 返回空结果"
    except Exception as e:
        return False, f"integrity_check 异常: {e}"


def format_file_size(file_size: int) -> str:
    if file_size < 1024:
        return f"{file_size} B"
    if file_size < 1024 * 1024:
        return f"{file_size / 1024:.1f} KB"
    if file_size < 1024 * 1024 * 1024:
        return f"{file_size / (1024 * 1024):.1f} MB"
    return f"{file_size / (1024 * 1024 * 1024):.2f} GB"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files_identical(left: Path, right: Path) -> bool:
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        return _file_sha256(left) == _file_sha256(right)
    except OSError:
        return False


def create_backup_if_changed(db_path: str, backup_dir: Path) -> tuple[str | None, str | None, bool]:
    """
    同步执行一次 SQLite 备份。在 asyncio 中请用 to_thread 调用。
    返回 (backup_filename, error_message, skipped)，成功时 error_message 为 None。
    备份前会执行 PRAGMA integrity_check，若数据库损坏则拒绝备份。
    若新备份与最新备份内容完全一致，则删除临时文件并返回 skipped=True。
    """
    tmp_path = None
    try:
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_filename = f"backup_{timestamp}.db"
        backup_path = backup_dir / backup_filename
        tmp_path = backup_dir / f"{backup_filename}.tmp"

        if not Path(db_path).exists():
            return None, "数据库文件不存在", False

        # 备份前检查数据库完整性，防止备份损坏的数据库
        is_ok, integrity_msg = check_db_integrity(db_path)
        if not is_ok:
            return None, f"数据库完整性检查失败，已跳过备份（{integrity_msg}）", False

        source = sqlite3.connect(db_path)
        try:
            dest = sqlite3.connect(str(tmp_path))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()

        is_ok, integrity_msg = check_db_integrity(str(tmp_path))
        if not is_ok:
            tmp_path.unlink(missing_ok=True)
            return None, f"新备份完整性检查失败，已丢弃临时备份（{integrity_msg}）", False

        latest_backup = next(iter(get_sorted_backup_files(backup_dir)), None)
        if latest_backup and _files_identical(tmp_path, latest_backup):
            tmp_path.unlink(missing_ok=True)
            return None, None, True

        os.replace(tmp_path, backup_path)
        return backup_filename, None, False
    except Exception as e:
        try:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        return None, str(e), False


def prune_backups(backup_dir: Path, keep: int = BACKUP_KEEP_COUNT) -> int:
    """
    保留最新 keep 个 backup_*.db，按修改时间降序，删除其余。
    返回删除的文件数量。
    """
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return 0
    files = list(backup_dir.glob("backup_*.db"))
    if len(files) <= keep:
        return 0
    # 按修改时间降序，新的在前
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    deleted = 0
    for f in files[keep:]:
        try:
            f.unlink()
            deleted += 1
        except OSError:
            pass
    return deleted


async def run_backup_once(
    db_path: str = DEFAULT_DB_PATH,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    keep: int = BACKUP_KEEP_COUNT,
    logger=None,
):
    """执行一次备份并修剪数量（异步，内部用 to_thread 执行同步备份）。"""
    loop = asyncio.get_event_loop()
    filename, err, skipped = await loop.run_in_executor(
        None,
        lambda: create_backup_if_changed(db_path, backup_dir),
    )
    if err:
        if logger:
            logger.warning(f"⏱️ [定时备份] 失败: {err}")
        return
    if skipped:
        if logger:
            logger.info("⏱️ [定时备份] 数据库内容无变化，跳过创建新备份")
    elif logger:
        logger.info(f"⏱️ [定时备份] 已创建: {filename}")
    # 修剪：保留最多 keep 个
    deleted = await loop.run_in_executor(
        None,
        lambda: prune_backups(backup_dir, keep),
    )
    if deleted and logger:
        logger.info(f"⏱️ [定时备份] 已删除 {deleted} 个旧备份，保留最多 {keep} 个")


async def backup_scheduler_loop(
    interval_sec: int = BACKUP_INTERVAL_SEC,
    db_path: str = DEFAULT_DB_PATH,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    keep: int = BACKUP_KEEP_COUNT,
    logger=None,
):
    """后台循环：每 interval_sec 执行一次备份检查，内容未变化时不保留新备份。"""
    global _scheduler_started_in_process
    if _scheduler_started_in_process:
        if logger:
            logger.info("⏱️ [定时备份] 检测到当前进程内调度器已启动，跳过重复启动")
        return
    _scheduler_started_in_process = True

    lock_fp = _acquire_scheduler_lock(Path(backup_dir) / ".backup_scheduler.lock")
    if not lock_fp:
        if logger:
            logger.info("⏱️ [定时备份] 检测到已有调度器实例在运行，当前实例跳过启动")
        _scheduler_started_in_process = False
        return

    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                db_path_obj = Path(db_path)
                if not db_path_obj.exists():
                    continue
                await run_backup_once(db_path=db_path, backup_dir=backup_dir, keep=keep, logger=logger)
            except asyncio.CancelledError:
                if logger:
                    logger.info("⏱️ [定时备份] 调度器已停止")
                raise
            except Exception as e:
                if logger:
                    logger.warning(f"⏱️ [定时备份] 异常: {e}")
    finally:
        _release_scheduler_lock(lock_fp)
        _scheduler_started_in_process = False


def get_sorted_backup_files(backup_dir: Path):
    """返回按修改时间降序排列的 backup_*.db 路径列表（最新在前）。"""
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    files = list(backup_dir.glob("backup_*.db"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _acquire_scheduler_lock(lock_path: Path):
    """
    获取跨进程调度锁；失败返回 None。
    目的：防止多个进程同时运行定时备份循环导致重复备份。
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # 使用原子创建锁文件（O_EXCL）做跨进程互斥，避免 Windows 下文件字节锁不稳定导致重复调度。
    # 返回值为 (fd, lock_path)；释放时会 close + unlink。
    try:
        # 如果锁文件已存在，尝试清理“僵尸锁”（持有进程已不存在）
        if lock_path.exists():
            stale_pid = None
            try:
                stale_pid = int(lock_path.read_text(encoding="utf-8").strip() or "0")
            except Exception:
                stale_pid = None
            if stale_pid and not _is_pid_alive(stale_pid):
                try:
                    lock_path.unlink()
                except Exception:
                    pass

        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        try:
            os.fsync(fd)
        except Exception:
            pass
        return (fd, lock_path)
    except FileExistsError:
        return None
    except Exception:
        return None


def _release_scheduler_lock(fp):
    if not fp:
        return
    fd = None
    lock_path = None
    if isinstance(fp, tuple) and len(fp) == 2:
        fd, lock_path = fp
    try:
        if fd is not None:
            os.close(fd)
    except Exception:
        pass
    try:
        if lock_path is not None and Path(lock_path).exists():
            Path(lock_path).unlink()
    except Exception:
        pass


def _is_pid_alive(pid: int) -> bool:
    """跨平台检查 PID 是否存活。"""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # 存在但无权限视为存活
        return True
    except OSError:
        return False
