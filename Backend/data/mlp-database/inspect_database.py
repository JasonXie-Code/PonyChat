# -*- coding: utf-8 -*-
"""Inspect the local G4 S1-S3 MLP keyword database."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from query_database import format_result, query_database


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "mlp_world.db"


def scalar(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0] or 0) if row else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--samples", action="store_true")
    args = parser.parse_args()
    db_path = Path(args.db)
    conn = sqlite3.connect(db_path)

    print(f"Database: {db_path}")
    print(f"Episodes: {scalar(conn, 'SELECT COUNT(*) FROM episodes')}")
    print(f"Entries: {scalar(conn, 'SELECT COUNT(*) FROM entries')}")
    print(f"Aliases: {scalar(conn, 'SELECT COUNT(*) FROM entity_aliases')}")
    print(f"Facts: {scalar(conn, 'SELECT COUNT(*) FROM facts')}")
    print("\nBy type:")
    for entity_type, count in conn.execute(
        "SELECT entity_type, COUNT(*) FROM entries GROUP BY entity_type ORDER BY COUNT(*) DESC, entity_type"
    ):
        print(f"  {entity_type:12s} {count}")
    print("\nSample aliases:")
    for alias in ["紫色聪明", "紫悦", "Rainbow Dash", "cutie mark", "Ponyville Schoolhouse", "Cloudsdale"]:
        row = conn.execute(
            """
            SELECT a.alias, e.canonical_name, e.entity_type
              FROM entity_aliases a
              JOIN entries e ON e.id=a.entry_id
             WHERE a.alias_norm=?
             LIMIT 1
            """,
            (__import__("query_database").norm_key(alias),),
        ).fetchone()
        print(f"  {alias}: {row[1] + ' / ' + row[2] if row else 'MISS'}")
    conn.close()

    if args.samples:
        print("\nSample queries:")
        for query in ["紫色聪明,小马镇", "可爱标记,小马镇学校", "云宝,云中城"]:
            print("\n" + "=" * 60)
            print(format_result(query_database(query, budget=300, db_path=db_path)))


if __name__ == "__main__":
    main()
