"""Archive small files with verified same-volume directory renames instead of repacking."""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

from archive_local_runtime import ROOT, ARCHIVES, LOG_ROOTS, files, log_file, sha256, assert_stopped


def scan(directory: Path):
    result = {}
    pending = [(directory, "")]
    while pending:
        base, prefix = pending.pop()
        with os.scandir(base) as entries:
            for entry in entries:
                relative = prefix + entry.name
                if entry.is_symlink():
                    raise RuntimeError(f"Unexpected symlink: {entry.path}")
                if entry.is_dir(follow_symlinks=False):
                    pending.append((Path(entry.path), relative + "/"))
                elif entry.is_file(follow_symlinks=False):
                    info = entry.stat(follow_symlinks=False)
                    result[relative] = (info.st_size, info.st_mtime_ns)
    return result


def archive(destination: Path):
    assert_stopped()
    started = time.monotonic()
    destination.mkdir(parents=True, exist_ok=True)
    storage = destination / "files"
    storage.mkdir(exist_ok=False)
    source_db = ROOT / "Backend/database/ponychat.db"
    saved_db = destination / "ponychat.full-backup.db"
    metadata = destination / "database-before.json"
    if not metadata.exists():
        with sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as source:
            source.execute("PRAGMA mmap_size=2147483648")
            tables = [name for name, in source.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            counts = {name: source.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
                      for name in tables}
            users = source.execute("SELECT id,username FROM users ORDER BY id").fetchall()
        metadata.write_text(json.dumps({"users": users, "tables": counts}, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(source_db, saved_db)
    database_hash = sha256(source_db)
    if sha256(saved_db) != database_hash:
        raise RuntimeError("Full database backup differs")
    with sqlite3.connect(saved_db) as db:
        db.execute("PRAGMA mmap_size=2147483648")
        db.execute("PRAGMA cache_size=-262144")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("Restored database integrity failed")
        before = json.loads((destination / "database-before.json").read_text(encoding="utf-8"))
        for table, count in before["tables"].items():
            escaped = '"' + table.replace('"', '""') + '"'
            if db.execute(f"SELECT COUNT(*) FROM {escaped}").fetchone()[0] != count:
                raise RuntimeError(f"Restored table differs: {table}")
    print("Full database backup verified: all tables and bytes match.", flush=True)
    manifest = destination / "manifest.jsonl.gz"
    moved = []
    count = total = 0
    with gzip.open(manifest, "wt", encoding="utf-8", compresslevel=1) as rows:
        rows.write(json.dumps({"path": "Backend/database/ponychat.db", "bytes": saved_db.stat().st_size,
                               "sha256": database_hash, "log": False, "storage": "standalone"}) + "\n")
        count += 1
        total += saved_db.stat().st_size
        for relative in LOG_ROOTS:
            source = (ROOT / relative).resolve()
            target = (storage / relative).resolve()
            if not source.is_dir():
                continue
            if not source.is_relative_to(ROOT.resolve()) or source.is_relative_to(ARCHIVES.resolve()):
                raise RuntimeError("Source outside runtime")
            if not target.is_relative_to(storage.resolve()) or target.exists() or source.drive != target.drive:
                raise RuntimeError("Unsafe archive destination")
            entries = scan(source)
            identity = source.stat().st_ino
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            # Record the move immediately, making partial work recoverable if later verification fails.
            moved.append(relative)
            (destination / "relocated-roots.json").write_text(json.dumps(moved), encoding="utf-8")
            if target.stat().st_ino != identity or scan(target) != entries:
                raise RuntimeError(f"Directory changed during archive: {relative}")
            source.mkdir()
            for name, (size, mtime) in entries.items():
                rows.write(json.dumps({"path": relative + "/" + name, "bytes": size, "mtime_ns": mtime,
                                       "log": True, "storage": "renamed-directory"}) + "\n")
                count += 1
                total += size
            print(json.dumps({"archived_directory": relative, "files": len(entries),
                              "total_files": count, "bytes": total}), flush=True)
        # Original log directories are now empty; copy remaining database assets and loose logs.
        for path in files():
            relative = path.relative_to(ROOT).as_posix()
            if relative in {"Backend/database/ponychat.db", "Backend/database/ponychat.db-wal", "Backend/database/ponychat.db-shm"}:
                continue
            target = storage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            before_info = path.stat()
            shutil.copy2(path, target)
            digest = sha256(path)
            if digest != sha256(target) or path.stat().st_mtime_ns != before_info.st_mtime_ns:
                raise RuntimeError(f"Backup copy differs: {relative}")
            rows.write(json.dumps({"path": relative, "bytes": before_info.st_size, "mtime_ns": before_info.st_mtime_ns,
                                   "sha256": digest, "log": log_file(relative), "storage": "copy"}) + "\n")
            count += 1
            total += before_info.st_size
            if count % 1000 == 0:
                print(json.dumps({"total_files": count, "bytes": total}), flush=True)
    result = {"verified": True, "strategy": "same-volume-directory-archive", "files": count, "bytes": total,
              "database_sha256": database_hash, "manifest_sha256": sha256(manifest),
              "integrity": "ok", "all_table_counts_match": True, "relocated_roots": moved,
              "log_verification": "same NTFS directory identity and exact relative path/size/mtime inventory",
              "copied_files_verification": "source and backup SHA-256 match", "seconds": round(time.monotonic()-started)}
    (destination / "VERIFIED.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    destination = Path(sys.argv[1]).resolve()
    if not destination.is_relative_to(ARCHIVES.resolve()) or destination == ARCHIVES.resolve():
        raise RuntimeError("Destination must be under Backend/数据存档")
    archive(destination)
