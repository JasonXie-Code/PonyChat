"""Prepare and verify a database retaining Jason/System; apply only after verified archive."""
from __future__ import annotations

import argparse
from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time

from archive_local_runtime import ROOT, ARCHIVES, assert_stopped, log_file, sha256

KEEP_IDS = (1, 73)
KEEP_NAMES = ("Jason", "System")
LOG_TABLES = {"llm_log_index", "llm_log_index_progress", "llm_log_index_errors",
              "deletion_audits", "agent_memory_attempts", "agent_memory_reviews"}
META_TABLES = {"_schema_patches", "agent_memory_migrations", "sqlite_sequence"}
CHILD_TABLES = {"messages", "message_attachments", "message_voice_states"}


def quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def schema(db):
    return {name: [row[1] for row in db.execute(f"PRAGMA table_info({quoted(name)})")]
            for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def predicates(db, removed_characters=()):
    result = {}
    removed_sql = ",".join("'" + value.replace("'", "''") + "'" for value in removed_characters) or "NULL"
    character_filter = f"(character_id IS NULL OR character_id NOT IN ({removed_sql}))" if removed_characters else "1"
    kept_conversations = f"SELECT id FROM conversations WHERE user_id IN (1,73) AND {character_filter}"
    for table, columns in schema(db).items():
        if table.startswith("llm_log_fts"):
            continue
        if table in LOG_TABLES:
            result[table] = "0"
        elif table in META_TABLES:
            result[table] = "1"
        elif table == "users":
            result[table] = "id IN (1,73)"
        elif table == "media_assets":
            result[table] = "uploader_id IS NULL OR uploader_id IN (1,73)"
        elif "user_id" in columns:
            result[table] = "user_id IN (1,73)"
        elif "publisher_username" in columns:
            result[table] = "publisher_username COLLATE BINARY IN ('Jason','System')"
        elif "username" in columns:
            result[table] = "username COLLATE BINARY IN ('Jason','System')"
            if table == "hall_character_likes":
                result[table] += " AND hall_id IN (SELECT id FROM hall_characters WHERE publisher_username COLLATE BINARY IN ('Jason','System'))"
        elif table in CHILD_TABLES:
            result[table] = f"conversation_id IN ({kept_conversations})"
        elif table == "agent_memory_versions":
            result[table] = f"entry_id IN (SELECT entry_id FROM agent_memory_heads WHERE username COLLATE BINARY IN ('Jason','System') AND {character_filter} UNION SELECT entry_id FROM agent_memory_entries WHERE username COLLATE BINARY IN ('Jason','System') AND {character_filter})"
        elif table == "invite_codes":
            result[table] = "used_by IS NULL OR used_by COLLATE BINARY IN ('Jason','System')"
        elif table not in {"avatars", "chat_images"}:
            raise RuntimeError(f"Unclassified table: {table}")
        if table in result and removed_characters and "character_id" in columns:
            result[table] = f"({result[table]}) AND {character_filter}"
        if table in result and removed_characters and "character_key" in columns:
            for character in removed_characters:
                result[table] += " AND character_key NOT LIKE '%" + character.replace("'", "''") + "%'"
    # BLOB tables do not record owners. Keep every asset referenced anywhere in retained content.
    text = []
    structure = schema(db)
    for table, condition in result.items():
        if table in LOG_TABLES or table in META_TABLES:
            continue
        columns = [name for name in structure[table] if name not in {"data", "file_data", "audio_data"}]
        # characters.data and hall_characters.data are JSON, not binary.
        if table in {"characters", "hall_characters"}:
            columns.append("data")
        for row in db.execute(f"SELECT {','.join(map(quoted, columns))} FROM {quoted(table)} WHERE {condition}"):
            text.extend(value for value in row if isinstance(value, str))
    retained_text = "\n".join(text)
    for table in ("avatars", "chat_images"):
        filenames = [name for name, in db.execute(f"SELECT filename FROM {quoted(table)}") if name in retained_text]
        result[table] = ("filename IN (" + ",".join("'" + name.replace("'", "''") + "'" for name in filenames) + ")") if filenames else "0"
    return result


def fingerprint(db, table, condition):
    digest = hashlib.sha256()
    count = 0
    for row in db.execute(f"SELECT * FROM {quoted(table)} WHERE {condition} ORDER BY rowid"):
        for value in row:
            data = value if isinstance(value, bytes) else repr(value).encode("utf-8")
            digest.update(type(value).__name__.encode() + b":" + str(len(data)).encode() + b":" + data)
        count += 1
    return {"rows": count, "sha256": digest.hexdigest()}


def prepare(destination: Path, *, removed_characters=()):
    assert_stopped()
    source = ROOT / "Backend/database/ponychat.db"
    candidate = destination / "ponychat.cleaned-candidate.db"
    if candidate.exists():
        raise RuntimeError("Candidate already exists")
    original_hash = sha256(source)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(":memory:") as db:
        original.execute("PRAGMA mmap_size=2147483648")
        original.execute("PRAGMA cache_size=-262144")
        users = dict(original.execute("SELECT id,username FROM users WHERE id IN (1,73)"))
        if users != {1: "Jason", 73: "System"}:
            raise RuntimeError("Retained account identities do not match")
        if removed_characters != () and tuple(removed_characters) != ("9d66f982-c09c-43be-baa3-433058d425b8",):
            raise RuntimeError("Additional retained-account character deletion needs explicit review")
        choices = predicates(original, removed_characters)
        before = {table: fingerprint(original, table, condition) for table, condition in choices.items()
                  if table not in LOG_TABLES}
        original_counts = {table: original.execute(f"SELECT COUNT(*) FROM {quoted(table)}").fetchone()[0]
                           for table in choices}
        original_schema = original.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        # Reconstruct only retained rows in memory. This avoids millions of tiny NTFS WAL
        # writes and does not reuse the historical, inconsistent external-content FTS index.
        db.execute("PRAGMA journal_mode=OFF")
        for kind, name, statement in original_schema:
            if kind == "table" and not name.startswith(("sqlite_", "llm_log_fts")):
                db.execute(statement)
        fts_sql = next(statement for kind, name, statement in original_schema if name == "llm_log_fts")
        db.execute(fts_sql)
        structure = schema(original)
        for table, condition in choices.items():
            if table == "sqlite_sequence":
                db.execute("DELETE FROM sqlite_sequence")
            columns = ["rowid", *structure[table]]
            query = f"SELECT {','.join(map(quoted, columns))} FROM {quoted(table)} WHERE {condition} ORDER BY rowid"
            insert = f"INSERT INTO {quoted(table)} ({','.join(map(quoted, columns))}) VALUES ({','.join('?' for _ in columns)})"
            db.executemany(insert, original.execute(query))
        for kind, name, statement in original_schema:
            if kind == "index" and statement:
                db.execute(statement)
        for kind, name, statement in original_schema:
            if kind == "trigger":
                db.execute(statement)
        db.commit()
        after = {table: fingerprint(db, table, "1") for table in before}
        differences = [table for table in before if before[table] != after[table]]
        if differences:
            raise RuntimeError(f"Retained records changed: {differences}")
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Foreign-key violations remain: {violations[:10]}")
        if original_schema != db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall():
            raise RuntimeError("Database schema changed")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("Candidate integrity failed")
        db.execute("INSERT INTO llm_log_fts(llm_log_fts) VALUES('integrity-check')")
        db.commit()
        counts = {table: db.execute(f"SELECT COUNT(*) FROM {quoted(table)}").fetchone()[0] for table in choices}
        candidate.write_bytes(db.serialize())
    with sqlite3.connect(candidate.as_uri() + "?mode=ro", uri=True) as saved:
        saved.execute("PRAGMA mmap_size=2147483648")
        if saved.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("Saved candidate integrity failed")
        if any(fingerprint(saved, table, "1") != before[table] for table in before):
            raise RuntimeError("Saved candidate content differs")
    result = {"verified": True, "source_sha256": original_hash, "candidate_sha256": sha256(candidate),
              "explicitly_removed_referenced_characters": list(removed_characters),
              "retained_accounts": users, "before_counts": original_counts, "after_counts": counts,
              "retained_records_unchanged": True, "retained_fingerprints": before,
              "foreign_key_check": "ok", "integrity_check": "ok", "candidate_bytes": candidate.stat().st_size}
    (destination / "CLEANUP-PREPARED.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"retained_fingerprints", "before_counts", "after_counts"}}, ensure_ascii=False), flush=True)


def should_remove_file(row, removed_characters=()):
    relative = Path(row["path"])
    recovery = (len(relative.parts) >= 4 and relative.parts[:3] == ("var", "recovery_snapshots", "galgame")
                and (relative.parts[3] not in KEEP_NAMES or any(
                    character in relative.name for character in removed_characters)))
    # Reclassify old manifests too: previous versions marked JSONL data and
    # knowledge titles containing "log" as logs.
    return (row["log"] and log_file(row["path"])) or recovery


def apply(destination: Path):
    assert_stopped()
    verified = json.loads((destination / "VERIFIED.json").read_text())
    prepared = json.loads((destination / "CLEANUP-PREPARED.json").read_text(encoding="utf-8"))
    if not verified["verified"] or not prepared["verified"]:
        raise RuntimeError("Backup and candidate must both be verified")
    if sha256(destination / "ponychat.full-backup.db") != verified["database_sha256"]:
        raise RuntimeError("Full database backup changed before cleanup")
    if verified.get("strategy") == "same-volume-directory-archive":
        if sha256(destination / "manifest.jsonl.gz") != verified["manifest_sha256"]:
            raise RuntimeError("Verified manifest changed before cleanup")
        for relative in verified["relocated_roots"]:
            source = (ROOT / relative).resolve()
            saved = (destination / "files" / relative).resolve()
            if not saved.is_relative_to(destination.resolve()) or not saved.is_dir():
                raise RuntimeError("Archived log directory is missing")
            if not source.is_dir() or any(source.iterdir()):
                raise RuntimeError("New logs appeared during maintenance")
    elif sha256(destination / "runtime.zip") != verified["archive_sha256"]:
        raise RuntimeError("Verified archive changed before cleanup")
    database = ROOT / "Backend/database/ponychat.db"
    candidate = destination / "ponychat.cleaned-candidate.db"
    if sha256(database) != verified["database_sha256"] or sha256(database) != prepared["source_sha256"]:
        raise RuntimeError("Live database changed after backup")
    if sha256(candidate) != prepared["candidate_sha256"]:
        raise RuntimeError("Candidate changed after verification")
    # Validate every deletion path and original fingerprint before any deletion or replacement.
    deletions = []
    archived_logs = archived_log_bytes = 0
    with gzip.open(destination / "manifest.jsonl.gz", "rt", encoding="utf-8") as rows:
        for line in rows:
            row = json.loads(line)
            if row.get("storage") == "renamed-directory":
                archived_logs += 1
                archived_log_bytes += row["bytes"]
                continue  # The original directory itself is already safely stored in the archive.
            relative = Path(row["path"])
            if not should_remove_file(row, prepared["explicitly_removed_referenced_characters"]):
                continue
            path = (ROOT / relative).resolve()
            if not path.is_relative_to(ROOT.resolve()) or path.is_relative_to(ARCHIVES.resolve()):
                raise RuntimeError(f"Deletion target outside runtime: {relative}")
            info = path.stat()
            if info.st_size != row["bytes"] or info.st_mtime_ns != row["mtime_ns"]:
                raise RuntimeError(f"File changed after verified archive: {relative}")
            deletions.append((path, row))
    # Close the old WAL cleanly, then atomically install already verified bytes while stopped.
    pending = database.with_name("ponychat.db.retention-new")
    if pending.exists():
        raise RuntimeError("A pending database replacement already exists")
    shutil.copy2(candidate, pending)
    if sha256(pending) != prepared["candidate_sha256"]:
        raise RuntimeError("Pending database copy differs")
    with closing(sqlite3.connect(database, timeout=30)) as target:
        if target.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
            raise RuntimeError("Original database still has active writers")
        if target.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
            raise RuntimeError("Cannot close the original WAL safely")
    pending.replace(database)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as target:
        target.execute("PRAGMA mmap_size=2147483648")
        if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("Live database integrity failed after replacement")
    aux = ROOT / "var/agent-status.sqlite3"
    with sqlite3.connect(aux) as db:
        db.execute("PRAGMA secure_delete=ON")
        db.execute("DELETE FROM progress")
        db.commit()
        db.execute("VACUUM")
    removed_bytes = 0
    for number, (path, row) in enumerate(deletions, 1):
        path.unlink()
        removed_bytes += row["bytes"]
        if number % 25000 == 0:
            print(json.dumps({"deleted_files": number, "bytes": removed_bytes}), flush=True)
    # Remove only now-empty directories under the explicit log/recovery roots.
    from archive_local_runtime import LOG_ROOTS
    for relative in LOG_ROOTS + ["var/recovery_snapshots"]:
        base = (ROOT / relative).resolve()
        if not base.is_relative_to(ROOT.resolve()) or base.is_relative_to(ARCHIVES.resolve()):
            raise RuntimeError("Unexpected directory root")
        if base.is_dir():
            import os
            for directory, _, _ in os.walk(base, topdown=False):
                path = Path(directory)
                if path != base and not any(path.iterdir()):
                    path.rmdir()
    result = {"complete": True, "deleted_files": len(deletions), "deleted_bytes": removed_bytes,
              "archived_logs_removed_from_runtime": archived_logs, "archived_log_bytes": archived_log_bytes,
              "retained_accounts": prepared["retained_accounts"], "finished_at": time.time()}
    (destination / "CLEANUP-COMPLETED.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "apply"])
    parser.add_argument("destination", type=Path)
    parser.add_argument("--remove-referenced-character", action="append", default=[])
    args = parser.parse_args()
    destination = args.destination.resolve()
    if not destination.is_relative_to(ARCHIVES.resolve()) or destination == ARCHIVES.resolve():
        parser.error("Destination must be a versioned archive directory")
    if args.action == "prepare":
        prepare(destination, removed_characters=tuple(args.remove_referenced_character))
    else:
        apply(destination)
