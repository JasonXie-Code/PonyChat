#!/usr/bin/env python3
"""Delete one character's memory content for one user; dry-run unless --apply.

Scope (memory content only):
  character_memories, agent_memory_heads + agent_memory_versions,
  agent_memory_entries, normal_chat_memory, agent_memory_notes,
  agent_memory_importance_reviews.

Deliberately preserved (relationship/scene/scheduling state):
  agent_memory_state, agent_memory_reviews, agent_memory_attempts,
  agent_memory_participants, agent_memory_group_turns,
  normal_agent_scene_cards, normal_scene_state,
  relationship_controls, relationship_presence_states.

--advance-review-cursor additionally sets agent_memory_state.reviewed_revision
to revision, so a pending background review cannot rebuild memories from the
history that was just cleared. It changes one scheduling field only.

Examples:
  python scripts/ops/clear_character_memories.py --username Jason --character-id fluttershy__u_1
  python scripts/ops/clear_character_memories.py --username Jason --character-id fluttershy__u_1 \\
      --apply --confirm Jason/fluttershy__u_1 --advance-review-cursor
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "Backend/database/ponychat.db"

# (table, statement, params-builder)
DELETE_BY_USERNAME = (
    ("agent_memory_heads",
     "DELETE FROM agent_memory_heads WHERE username=? AND character_id=?"),
    ("agent_memory_entries",
     "DELETE FROM agent_memory_entries WHERE username=? AND character_id=?"),
    ("normal_chat_memory",
     "DELETE FROM normal_chat_memory WHERE username=? AND character_id=?"),
    ("agent_memory_notes",
     "DELETE FROM agent_memory_notes WHERE username=? AND character_id=?"),
)
# Scoped through agent_memory_heads: these tables have no username column.
DELETE_VIA_HEADS = (
    ("agent_memory_importance_reviews",
     "DELETE FROM agent_memory_importance_reviews WHERE entry_id IN "
     "(SELECT entry_id FROM agent_memory_heads WHERE username=? AND character_id=?)"),
    ("agent_memory_versions",
     "DELETE FROM agent_memory_versions WHERE entry_id IN "
     "(SELECT entry_id FROM agent_memory_heads WHERE username=? AND character_id=?)"),
)
COUNT_VIA_HEADS = "SELECT COUNT(*) FROM {table} WHERE entry_id IN " \
                  "(SELECT entry_id FROM agent_memory_heads WHERE username=? AND character_id=?)"
DELETE_BY_USER_ID = (
    ("character_memories",
     "DELETE FROM character_memories WHERE user_id=? AND character_id=?"),
)
PRESERVED = (
    ("agent_memory_state", "SELECT COUNT(*) FROM agent_memory_state WHERE username=? AND character_id=?"),
    ("agent_memory_reviews", "SELECT COUNT(*) FROM agent_memory_reviews WHERE username=? AND character_id=?"),
    ("agent_memory_attempts", "SELECT COUNT(*) FROM agent_memory_attempts WHERE username=? AND character_id=?"),
    ("agent_memory_participants", "SELECT COUNT(*) FROM agent_memory_participants WHERE username=? AND character_id=?"),
    ("agent_memory_group_turns", "SELECT COUNT(*) FROM agent_memory_group_turns WHERE username=? AND character_id=?"),
    ("normal_agent_scene_cards", "SELECT COUNT(*) FROM normal_agent_scene_cards WHERE username=? AND character_id=?"),
    ("normal_scene_state", "SELECT COUNT(*) FROM normal_scene_state WHERE username=? AND character_id=?"),
    ("relationship_controls", "SELECT COUNT(*) FROM relationship_controls WHERE username=? AND character_id=?"),
    ("relationship_presence_states", "SELECT COUNT(*) FROM relationship_presence_states WHERE username=? AND character_id=?"),
)
DUMP_QUERIES = {
    "character_memories": ("SELECT * FROM character_memories WHERE user_id=? AND character_id=?", "user"),
    "agent_memory_heads": ("SELECT * FROM agent_memory_heads WHERE username=? AND character_id=?", "username"),
    "agent_memory_versions": ("SELECT v.* FROM agent_memory_versions v JOIN agent_memory_heads h "
                              "ON h.entry_id=v.entry_id WHERE h.username=? AND h.character_id=?", "username"),
    "agent_memory_entries": ("SELECT * FROM agent_memory_entries WHERE username=? AND character_id=?", "username"),
    "normal_chat_memory": ("SELECT * FROM normal_chat_memory WHERE username=? AND character_id=?", "username"),
    "agent_memory_notes": ("SELECT * FROM agent_memory_notes WHERE username=? AND character_id=?", "username"),
}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _count(conn: sqlite3.Connection, table: str, where: str, params: tuple) -> int:
    if not _table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])


def _dump(conn: sqlite3.Connection, sql: str, params: tuple) -> list[dict]:
    table = sql.split("FROM", 1)[1].split()[0]
    if not _table_exists(conn, table):
        return []
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.row_factory = None
    return [dict(row) for row in rows]


def collect_counts(conn: sqlite3.Connection, username: str, user_id: int, character_id: str) -> dict:
    counts = {}
    for table, _sql in DELETE_BY_USERNAME:
        counts[table] = _count(conn, table, "username=? AND character_id=?", (username, character_id))
    for table, _sql in DELETE_VIA_HEADS:
        counts[table] = (_count_via_heads(conn, table, username, character_id)
                         if _table_exists(conn, table) else 0)
    for table, _sql in DELETE_BY_USER_ID:
        counts[table] = _count(conn, table, "user_id=? AND character_id=?", (user_id, character_id))
    return counts


def _count_via_heads(conn: sqlite3.Connection, table: str, username: str, character_id: str) -> int:
    return int(conn.execute(COUNT_VIA_HEADS.format(table=table), (username, character_id)).fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", required=True)
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true", help="perform the deletion; default is read-only")
    parser.add_argument("--confirm", help="must equal '<username>/<character-id>' when --apply is used")
    parser.add_argument("--advance-review-cursor", action="store_true",
                        help="also set agent_memory_state.reviewed_revision=revision for this character")
    args = parser.parse_args()

    if not args.db.is_file():
        print("DB not found:", args.db)
        return 1
    if args.apply and args.confirm != f"{args.username}/{args.character_id}":
        print(f"--apply requires --confirm {args.username}/{args.character_id}")
        return 2

    conn = sqlite3.connect(str(args.db))
    try:
        user = conn.execute("SELECT id, username FROM users WHERE username=?", (args.username,)).fetchone()
        if not user:
            print("User not found:", args.username)
            return 1
        user_id = int(user[0])
        owned = conn.execute("SELECT id, name FROM characters WHERE user_id=? AND id=?",
                             (user_id, args.character_id)).fetchone()
        if not owned:
            print(f"Character {args.character_id!r} does not belong to {args.username!r}; refusing.")
            return 3
        before = collect_counts(conn, args.username, user_id, args.character_id)
        preserved_before = {t: _count(conn, t, "username=? AND character_id=?", (args.username, args.character_id))
                            for t, _sql in PRESERVED}
        print(f"user_id={user_id} username={args.username!r} character={args.character_id!r} name={owned[1]!r}")
        print("--- to delete ---")
        for table, count in before.items():
            print(f"  {table:34} {count}")
        print("--- preserved ---")
        for table, count in preserved_before.items():
            print(f"  {table:34} {count}")

        if not args.apply:
            print("\nDRY RUN: nothing deleted. Re-run with --apply --confirm "
                  f"{args.username}/{args.character_id}")
            return 0

        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = args.backup_dir or (ROOT / "var/backups" / f"character-memory-clear-{stamp}")
        backup.mkdir(parents=True, exist_ok=True)
        dumps = {}
        for table, (sql, kind) in DUMP_QUERIES.items():
            params = (user_id, args.character_id) if kind == "user" else (args.username, args.character_id)
            dumps[table] = _dump(conn, sql, params)
        (backup / "deleted-rows.json").write_text(
            json.dumps(dumps, ensure_ascii=False, indent=2), encoding="utf-8")

        snapshot = backup / "ponychat.db"
        with sqlite3.connect(str(snapshot)) as target:
            conn.backup(target)

        deleted = {}
        conn.execute("BEGIN IMMEDIATE")
        try:
            for table, sql in DELETE_VIA_HEADS:
                if not _table_exists(conn, table):
                    deleted[table] = 0
                    continue
                cur = conn.execute(sql, (args.username, args.character_id))
                deleted[table] = cur.rowcount
            for table, sql in DELETE_BY_USERNAME:
                if not _table_exists(conn, table):
                    deleted[table] = 0
                    continue
                cur = conn.execute(sql, (args.username, args.character_id))
                deleted[table] = cur.rowcount
            for table, sql in DELETE_BY_USER_ID:
                if not _table_exists(conn, table):
                    deleted[table] = 0
                    continue
                cur = conn.execute(sql, (user_id, args.character_id))
                deleted[table] = cur.rowcount
            cursor_change = None
            if args.advance_review_cursor and _table_exists(conn, "agent_memory_state"):
                row = conn.execute("SELECT revision, reviewed_revision FROM agent_memory_state "
                                   "WHERE username=? AND character_id=?",
                                   (args.username, args.character_id)).fetchone()
                if row:
                    cursor_change = {"revision": int(row[0]), "reviewed_revision_before": int(row[1])}
                    conn.execute("UPDATE agent_memory_state SET reviewed_revision=revision "
                                 "WHERE username=? AND character_id=?",
                                 (args.username, args.character_id))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

        after = collect_counts(conn, args.username, user_id, args.character_id)
        preserved_after = {t: _count(conn, t, "username=? AND character_id=?", (args.username, args.character_id))
                           for t, _sql in PRESERVED}
        manifest = {
            "applied_at": stamp, "db": str(args.db), "username": args.username, "user_id": user_id,
            "character_id": args.character_id, "character_name": owned[1],
            "counts_before": before, "deleted": deleted, "counts_after": after,
            "preserved_before": preserved_before, "preserved_after": preserved_after,
            "review_cursor_change": cursor_change,
            "backup": str(backup),
            "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        }
        (backup / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8")
        print("\n--- deleted ---")
        for table, count in deleted.items():
            print(f"  {table:34} {count}")
        print("\n--- remaining memory rows (must be 0) ---")
        for table, count in after.items():
            print(f"  {table:34} {count}")
        print("\n--- preserved after ---")
        for table, count in preserved_after.items():
            flag = "unchanged" if preserved_before[table] == count else "CHANGED"
            print(f"  {table:34} {count}  ({flag})")
        if cursor_change:
            print(f"\nreview cursor advanced: {cursor_change}")
        print(f"\nbackup: {backup}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
