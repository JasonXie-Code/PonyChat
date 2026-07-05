#!/usr/bin/env python3
"""
Repair historical message ordering issues across all chat modes.

What it does:
1. Rebuilds sequence_number as contiguous 0..N-1 per conversation/thread.
2. Rebuilds previous_message_id chain based on sorted order.
3. Uses stable sort order:
   COALESCE(timestamp, 0), COALESCE(sequence_number, 0), rowid

Default mode is dry-run. Use --apply to write changes.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from typing import List, Sequence, Tuple


@dataclass(frozen=True)
class TableSpec:
    table: str
    partition_cols: Sequence[str]


TABLE_SPECS: List[TableSpec] = [
    TableSpec(table="messages", partition_cols=("conversation_id",)),
    TableSpec(table="galgame_messages", partition_cols=("character_id", "user_id")),
    TableSpec(table="galgame_lock_messages", partition_cols=("character_id", "user_id")),
]


def _partition_key_expr(partition_cols: Sequence[str]) -> str:
    parts = []
    for col in partition_cols:
        parts.append(f"COALESCE(CAST({col} AS TEXT), '')")
    return " || '|' || ".join(parts)


def _build_select_sql(spec: TableSpec) -> str:
    cols = ", ".join(spec.partition_cols)
    partition_key = _partition_key_expr(spec.partition_cols)
    return f"""
        SELECT rowid, {cols}, message_id, id, timestamp, sequence_number
        FROM {spec.table}
        ORDER BY {partition_key} ASC,
                 COALESCE(timestamp, 0) ASC,
                 COALESCE(sequence_number, 0) ASC,
                 rowid ASC
    """


def _build_partition_values(row: Tuple, partition_count: int) -> Tuple:
    # 行布局：rowid、<partition...>、message_id、id、timestamp、sequence_number
    return tuple(row[1 : 1 + partition_count])


def repair_table(conn: sqlite3.Connection, spec: TableSpec, apply_changes: bool) -> Tuple[int, int]:
    cursor = conn.cursor()
    rows = cursor.execute(_build_select_sql(spec)).fetchall()
    if not rows:
        return 0, 0

    partition_count = len(spec.partition_cols)
    current_partition = None
    seq = 0
    prev_id = None
    updated_rows = 0
    groups = 0

    for row in rows:
        rowid = row[0]
        partition_values = _build_partition_values(row, partition_count)
        message_id = row[1 + partition_count]
        fallback_id = row[2 + partition_count]
        old_seq = row[4 + partition_count]

        if partition_values != current_partition:
            current_partition = partition_values
            seq = 0
            prev_id = None
            groups += 1

        # message_id 为空时，为保持链连续仅回退到 id。
        # 本脚本不修改 message_id。
        current_effective_id = message_id if message_id else fallback_id

        if old_seq != seq:
            updated_rows += 1
        # 始终更新 previous_message_id 以保持链一致。
        if apply_changes:
            cursor.execute(
                f"UPDATE {spec.table} SET sequence_number = ?, previous_message_id = ? WHERE rowid = ?",
                (seq, prev_id, rowid),
            )

        prev_id = current_effective_id
        seq += 1

    return updated_rows, groups


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair message ordering and sequence numbers.")
    parser.add_argument("--db-path", default="database/ponychat.db", help="SQLite database path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to database. Without this flag, runs in dry-run mode.",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    try:
        if args.apply:
            conn.execute("BEGIN IMMEDIATE")

        total_updated = 0
        total_groups = 0
        print(f"[mode] {'APPLY' if args.apply else 'DRY-RUN'}")
        print(f"[db] {args.db_path}")

        for spec in TABLE_SPECS:
            updated, groups = repair_table(conn, spec, apply_changes=args.apply)
            total_updated += updated
            total_groups += groups
            print(f"[table] {spec.table}: groups={groups}, rows_needing_seq_fix={updated}")

        if args.apply:
            conn.commit()
            print(f"[done] committed. groups={total_groups}, rows_fixed={total_updated}")
        else:
            print(f"[done] dry-run complete. groups={total_groups}, rows_needing_fix={total_updated}")
    except Exception:
        if args.apply:
            conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

