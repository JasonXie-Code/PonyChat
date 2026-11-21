"""Archive a stopped local runtime and verify every archived file before cleanup."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
ARCHIVES = ROOT / "Backend/数据存档"
FULL_ROOTS = [
    "Backend/database", "Backend/data", "var/.chatlogs", "var/backlogs", "var/applogs",
    "var/chatlogs", "var/test_results", "var/local-stack", "var/agent-status.sqlite3",
    "var/drive", "var/recovery_snapshots", "var/startup_logs", "var/ChatMonitor",
    "var/services/cosyvoice/outputs", "var/services/cosyvoice/uploads",
    "var/services/cosyvoice/generation_logs", "var/services/cosyvoice/logs",
    "PonyChat-Website/TTS/generation_logs", ".ChatLogs", ".BackLogs", ".AppLogs",
]
LOG_ROOTS = [
    "var/.chatlogs", "var/backlogs", "var/applogs", "var/chatlogs", "var/test_results",
    "var/startup_logs", "var/ChatMonitor", "var/services/cosyvoice/generation_logs",
    "var/services/cosyvoice/logs", "PonyChat-Website/TTS/generation_logs",
    ".ChatLogs", ".BackLogs", ".AppLogs",
]


def log_file(relative: str) -> bool:
    path = Path(relative)
    if any(path == Path(base) or Path(base) in path.parents for base in LOG_ROOTS):
        return True
    # Knowledge-page titles and JSONL datasets are content, not logs. Substring
    # matching incorrectly caught titles such as "Slog" and "chronology".
    if Path("Backend/data/mlp/pages") in path.parents:
        return False
    if path.suffix.lower() == ".log":
        return True
    if path.suffix.lower() in {".txt", ".jsonl", ".ndjson"}:
        if re.search(r"(?:^|[_ .-])(?:logs?|logcat)\d*(?:$|[_ .-])", path.stem, re.IGNORECASE):
            return True
    return (path == Path("Backend/database/admin_uptime_samples.json")
            or (path.parent == Path("Backend/database")
                and path.name.startswith("daily_summary_clean_") and path.suffix == ".jsonl"))


def files():
    seen = set()
    for base in FULL_ROOTS:
        target = ROOT / base
        walk = [(target.parent, [], [target.name])] if target.is_file() else os.walk(target)
        for directory, dirs, names in walk:
            dirs[:] = [name for name in dirs if name not in {"backups", "__pycache__", ".venv", ".git"}]
            for name in names:
                path = Path(directory) / name
                if path.suffix in {".py", ".pyc", ".md"} or path.is_symlink():
                    continue
                relative = path.relative_to(ROOT).as_posix()
                if relative not in seen:
                    seen.add(relative)
                    yield path
    # Include loose runtime diagnostics while preserving prior backups and migration archives.
    for directory, dirs, names in os.walk(ROOT / "var"):
        dirs[:] = [name for name in dirs if name not in {
            "backups", "migration-20260909", "__pycache__", ".venv", "node_modules", "releases", "runtime"}
            and (Path(directory) / name).relative_to(ROOT).as_posix() not in FULL_ROOTS]
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(ROOT).as_posix()
            if relative not in seen and log_file(relative) and not path.is_symlink():
                seen.add(relative)
                yield path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_stopped():
    import psutil

    state = json.loads((ROOT / "var/local-stack/status.json").read_text(encoding="utf-8"))
    for name, item in state.items():
        pid = item.get("pid") if isinstance(item, dict) else item if name == "supervisor_pid" else None
        if not pid:
            continue
        try:
            process = psutil.Process(pid)
            command = " ".join(process.cmdline()).lower()
            if "ponychat" in command or "local_stack.py" in command:
                raise RuntimeError(f"Runtime process still running: {name} pid={pid}")
        except psutil.NoSuchProcess:
            pass


def inventory():
    counts = {}
    for path in files():
        relative = path.relative_to(ROOT).as_posix()
        group = "/".join(relative.split("/")[:2])
        row = counts.setdefault(group, {"files": 0, "bytes": 0})
        row["files"] += 1
        row["bytes"] += path.stat().st_size
    print(json.dumps(counts, ensure_ascii=False, indent=2), flush=True)


def archive(destination: Path):
    assert_stopped()
    destination = destination.resolve()
    if not destination.is_relative_to(ARCHIVES.resolve()) or destination == ARCHIVES.resolve():
        raise RuntimeError("Archive must be a new version directory under Backend/数据存档")
    destination.mkdir(parents=True, exist_ok=False)
    database = ROOT / "Backend/database/ponychat.db"
    for dbpath in (database, ROOT / "var/agent-status.sqlite3"):
        with sqlite3.connect(dbpath, timeout=30) as db:
            result = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if result[0]:
                raise RuntimeError(f"Database is busy: {dbpath}")
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError(f"Database integrity failed: {dbpath}")
    with sqlite3.connect(database) as db:
        users = db.execute("SELECT id,username FROM users ORDER BY id").fetchall()
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        counts = {table: db.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
                  for table in tables}
    (destination / "database-before.json").write_text(json.dumps({"users": users, "tables": counts},
        ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = destination / "manifest.jsonl.gz"
    archive_path = destination / "runtime.zip"
    count = size = 0
    started = time.monotonic()
    with gzip.open(manifest, "wt", encoding="utf-8", compresslevel=1) as rows, \
            zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1,
                            allowZip64=True, strict_timestamps=False) as out:
        for path in files():
            relative = path.relative_to(ROOT).as_posix()
            before = path.stat()
            digest = hashlib.sha256()
            info = zipfile.ZipInfo.from_file(path, arcname=relative, strict_timestamps=False)
            info.compress_type = zipfile.ZIP_DEFLATED
            info._compresslevel = 1
            with path.open("rb") as source, out.open(info, "w", force_zip64=True) as target:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(block)
                    digest.update(block)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f"Source changed during archive: {relative}")
            rows.write(json.dumps({"path": relative, "bytes": before.st_size, "mtime_ns": before.st_mtime_ns,
                                   "sha256": digest.hexdigest(), "log": log_file(relative)}) + "\n")
            count += 1
            size += before.st_size
            if count % 25000 == 0:
                print(json.dumps({"archived": count, "bytes": size, "seconds": round(time.monotonic()-started)}), flush=True)
    verified = 0
    with zipfile.ZipFile(archive_path) as saved, gzip.open(manifest, "rt", encoding="utf-8") as rows:
        for line in rows:
            row = json.loads(line)
            digest = hashlib.sha256()
            with saved.open(row["path"]) as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != row["sha256"]:
                raise RuntimeError(f"Archive hash mismatch: {row['path']}")
            verified += 1
            if verified % 50000 == 0:
                print(json.dumps({"verified": verified}), flush=True)
        if verified != len(saved.infolist()) or verified != count:
            raise RuntimeError("Archive member count mismatch")
        restored = destination / "ponychat.full-backup.db"
        with saved.open("Backend/database/ponychat.db") as source, restored.open("wb") as target:
            import shutil
            shutil.copyfileobj(source, target, 1024 * 1024)
    with sqlite3.connect(restored) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("Restored database integrity failed")
        for table, expected in counts.items():
            actual = db.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
            if actual != expected:
                raise RuntimeError(f"Restored row-count mismatch: {table}")
    result = {"verified": True, "files": count, "bytes": size, "archive_bytes": archive_path.stat().st_size,
              "archive_sha256": sha256(archive_path), "database_sha256": sha256(restored),
              "integrity": "ok", "all_table_counts_match": True, "seconds": round(time.monotonic()-started)}
    (destination / "VERIFIED.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inventory", "archive"])
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.action == "inventory":
        inventory()
    else:
        if args.destination is None:
            parser.error("--destination is required")
        archive(args.destination)
