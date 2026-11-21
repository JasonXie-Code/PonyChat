#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fuse normal-mode conversations so each user-character pair has one main container.

The migration moves messages from every conversation for the same user/character into
one canonical conversation. Messages that came from a hidden conversation remain
hidden after the move; visible messages from visible conversations stay visible.

It does not touch Galgame tables.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path


def now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def quick_check(db_path: Path) -> str:
    with sqlite3.connect(str(db_path), timeout=30) as conn:
        row = conn.execute("PRAGMA quick_check").fetchone()
        return str(row[0] if row else "")


def backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.stem}.pre_normal_fuse.{now_stamp()}.db"
    with sqlite3.connect(str(db_path), timeout=30) as src:
        with sqlite3.connect(str(backup_path), timeout=30) as dst:
            src.backup(dst)
    check = quick_check(backup_path)
    if check.lower() != "ok":
        raise RuntimeError(f"backup quick_check failed: {check}")
    return backup_path


def fetch_groups(conn: sqlite3.Connection) -> list[tuple[int, str, int, int]]:
    return conn.execute(
        """SELECT user_id,
                  character_id,
                  COUNT(*) AS conv_count,
                  SUM(CASE WHEN COALESCE(is_hidden, 0) = 0 THEN 1 ELSE 0 END) AS visible_count
           FROM conversations
           GROUP BY user_id, character_id
           HAVING COUNT(*) > 1
           ORDER BY conv_count DESC, user_id ASC, character_id ASC"""
    ).fetchall()


def fetch_group_conversations(conn: sqlite3.Connection, user_id: int, character_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT c.id,
                  COALESCE(c.is_hidden, 0) AS is_hidden,
                  COALESCE(MAX(m.timestamp), c.timestamp, 0) AS activity_ts,
                  c.updated_at,
                  c.rowid,
                  COUNT(m.id) AS message_count
           FROM conversations c
           LEFT JOIN messages m ON m.conversation_id = c.id
           WHERE c.user_id = ? AND c.character_id = ?
           GROUP BY c.id
           ORDER BY
             CASE WHEN COALESCE(c.is_hidden, 0) = 0 THEN 0 ELSE 1 END,
             activity_ts DESC,
             c.updated_at DESC,
             c.rowid DESC""",
        (user_id, character_id),
    ).fetchall()


def username_for(conn: sqlite3.Connection, user_id: int) -> str:
    row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    return str(row[0] if row else user_id)


def renumber_messages(conn: sqlite3.Connection, canonical_id: str) -> int:
    rows = conn.execute(
        """SELECT id, message_id
           FROM messages
           WHERE conversation_id = ?
           ORDER BY COALESCE(timestamp, 0) ASC,
                    COALESCE(sequence_number, 0) ASC,
                    rowid ASC""",
        (canonical_id,),
    ).fetchall()
    prev_mid = None
    for idx, row in enumerate(rows):
        msg_id = str(row["message_id"] or "")
        conn.execute(
            "UPDATE messages SET sequence_number = ?, previous_message_id = ? WHERE id = ?",
            (idx, prev_mid, row["id"]),
        )
        prev_mid = msg_id or prev_mid
    return len(rows)


def migrate(conn: sqlite3.Connection, dry_run: bool) -> dict:
    groups = fetch_groups(conn)
    stats = {
        "groups_seen": len(groups),
        "groups_changed": 0,
        "conversations_hidden": 0,
        "messages_moved": 0,
        "messages_hidden_from_hidden_conversations": 0,
        "attachments_moved": 0,
        "normal_context_rows_deleted": 0,
        "emotion_rows_deleted": 0,
        "image_context_rows_deleted": 0,
        "image_context_state_rows_deleted": 0,
        "sample_groups": [],
    }
    if dry_run:
        for user_id, character_id, conv_count, visible_count in groups[:20]:
            rows = fetch_group_conversations(conn, user_id, character_id)
            stats["sample_groups"].append(
                {
                    "username": username_for(conn, user_id),
                    "character_id": character_id,
                    "conversation_count": conv_count,
                    "visible_count": visible_count,
                    "canonical_id": rows[0]["id"] if rows else None,
                    "canonical_hidden": bool(rows[0]["is_hidden"]) if rows else None,
                    "message_count": sum(int(r["message_count"] or 0) for r in rows),
                }
            )
        return stats

    for user_id, character_id, _conv_count, _visible_count in groups:
        rows = fetch_group_conversations(conn, user_id, character_id)
        if len(rows) <= 1:
            continue

        canonical = rows[0]
        canonical_id = str(canonical["id"])
        duplicate_ids = [str(r["id"]) for r in rows[1:]]
        original_hidden_ids = [str(r["id"]) for r in rows if int(r["is_hidden"] or 0) == 1]
        username = username_for(conn, user_id)

        if original_hidden_ids:
            placeholders = ",".join("?" for _ in original_hidden_ids)
            cur = conn.execute(
                f"""UPDATE messages
                    SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                        delete_reason = COALESCE(delete_reason, 'source_conversation_hidden_before_fuse'),
                        is_hidden = 1,
                        hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                        hidden_reason = COALESCE(hidden_reason, 'source_conversation_hidden_before_fuse')
                    WHERE conversation_id IN ({placeholders})
                      AND deleted_at IS NULL
                      AND COALESCE(is_hidden, 0) = 0""",
                original_hidden_ids,
            )
            stats["messages_hidden_from_hidden_conversations"] += max(0, cur.rowcount or 0)

        if duplicate_ids:
            placeholders = ",".join("?" for _ in duplicate_ids)
            move_msg = conn.execute(
                f"UPDATE messages SET conversation_id = ? WHERE conversation_id IN ({placeholders})",
                (canonical_id, *duplicate_ids),
            )
            stats["messages_moved"] += max(0, move_msg.rowcount or 0)

            move_att = conn.execute(
                f"UPDATE message_attachments SET conversation_id = ? WHERE conversation_id IN ({placeholders})",
                (canonical_id, *duplicate_ids),
            )
            stats["attachments_moved"] += max(0, move_att.rowcount or 0)

            hide_conv = conn.execute(
                f"""UPDATE conversations
                    SET is_hidden = 1,
                        hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                        hidden_reason = COALESCE(hidden_reason, 'merged_into_single_normal_conversation'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id IN ({placeholders})""",
                duplicate_ids,
            )
            stats["conversations_hidden"] += max(0, hide_conv.rowcount or 0)

        merged_count = renumber_messages(conn, canonical_id)
        latest_ts_row = conn.execute(
            "SELECT MAX(COALESCE(timestamp, 0)) FROM messages WHERE conversation_id = ?",
            (canonical_id,),
        ).fetchone()
        latest_ts = int((latest_ts_row[0] if latest_ts_row else 0) or 0)
        conn.execute(
            """UPDATE conversations
               SET timestamp = CASE WHEN ? > 0 THEN ? ELSE timestamp END,
                   version = COALESCE(version, 0) + 1,
                   summary = '',
                   context_summary_cutoff_message_id = NULL,
                   context_summary_cutoff_timestamp = NULL,
                   context_summary_cutoff_sequence = NULL,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (latest_ts, latest_ts, canonical_id),
        )

        for table, stat_key in (
            ("normal_chat_memory", "normal_context_rows_deleted"),
            ("normal_emotion_state", "emotion_rows_deleted"),
            ("normal_image_contexts", "image_context_rows_deleted"),
            ("normal_image_context_state", "image_context_state_rows_deleted"),
        ):
            cur = conn.execute(
                f"DELETE FROM {table} WHERE username = ? AND character_id = ?",
                (username, character_id),
            )
            stats[stat_key] += max(0, cur.rowcount or 0)

        conn.execute(
            """INSERT INTO deletion_audits
                 (action, object_type, object_id, user_id, username, character_id,
                  conversation_id, operator, reason, source, details_json)
               VALUES
                 ('soft_delete', 'conversation_batch', ?, ?, ?, ?, ?, 'system',
                  'merged_into_single_normal_conversation', 'maintenance', ?)""",
            (
                canonical_id,
                user_id,
                username,
                character_id,
                canonical_id,
                json.dumps(
                    {
                        "canonical_conversation_id": canonical_id,
                        "merged_conversation_ids": duplicate_ids,
                        "original_hidden_conversation_ids": original_hidden_ids,
                        "merged_message_count": merged_count,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        stats["groups_changed"] += 1

    return stats


def post_check(conn: sqlite3.Connection) -> dict:
    visible_multi = conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT user_id, character_id
             FROM conversations
             WHERE COALESCE(is_hidden, 0) = 0
             GROUP BY user_id, character_id
             HAVING COUNT(*) > 1
           )"""
    ).fetchone()[0]
    all_multi = conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT user_id, character_id
             FROM conversations
             GROUP BY user_id, character_id
             HAVING COUNT(*) > 1
           )"""
    ).fetchone()[0]
    duplicate_nonempty = conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT user_id, character_id
             FROM conversations c
             WHERE EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)
             GROUP BY user_id, character_id
             HAVING COUNT(*) > 1
           )"""
    ).fetchone()[0]
    visible_hidden_source_msgs = conn.execute(
        """SELECT COUNT(*)
           FROM messages
           WHERE hidden_reason = 'source_conversation_hidden_before_fuse'
             AND deleted_at IS NULL
             AND COALESCE(is_hidden, 0) = 0"""
    ).fetchone()[0]
    return {
        "visible_multi_groups": int(visible_multi or 0),
        "all_multi_groups_including_empty_hidden_containers": int(all_multi or 0),
        "multi_groups_with_messages": int(duplicate_nonempty or 0),
        "hidden_source_messages_accidentally_visible": int(visible_hidden_source_msgs or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Path to ponychat.db")
    parser.add_argument("--backup-dir", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        print(f"[X] database not found: {db_path}", file=sys.stderr)
        return 2
    if not args.dry_run and not args.apply:
        print("[X] pass --dry-run or --apply", file=sys.stderr)
        return 2

    print(f"database={db_path}")
    print(f"quick_check_before={quick_check(db_path)}")
    backup_path = None
    if args.apply:
        backup_dir = Path(args.backup_dir).resolve() if args.backup_dir else db_path.parent / "backups"
        backup_path = backup_database(db_path, backup_dir)
        print(f"backup={backup_path}")

    with sqlite3.connect(str(db_path), timeout=60) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 60000")
        if args.apply:
            conn.execute("BEGIN IMMEDIATE")
        try:
            stats = migrate(conn, dry_run=args.dry_run)
            checks = post_check(conn)
            if args.apply:
                conn.commit()
            else:
                conn.rollback()
        except Exception:
            if args.apply:
                conn.rollback()
            raise

    print("stats=" + json.dumps(stats, ensure_ascii=False, indent=2))
    print("post_check=" + json.dumps(checks, ensure_ascii=False, indent=2))
    print(f"quick_check_after={quick_check(db_path)}")
    if backup_path:
        print(f"backup_quick_check={quick_check(backup_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
