#!/usr/bin/env python3
"""
一次性回填 Galgame 消息的 scene_metadata。

默认 dry-run，仅统计不写入。
执行写入请加: --apply
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import backend_package_dir, resolve_project_root

ROOT = resolve_project_root(Path(__file__))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.galgame_dao import (  # noqa: E402
    _parse_scene_metadata_from_raw,
    _parse_scene_metadata_from_content_html,
)


def ensure_scene_metadata_column(conn: sqlite3.Connection, table: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if "scene_metadata" not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN scene_metadata TEXT")
        print(f"[migrate] added {table}.scene_metadata")


def load_fallback_map(conn: sqlite3.Connection, data_table: str) -> Dict[Tuple[str, int], Dict]:
    result: Dict[Tuple[str, int], Dict] = {}
    rows = conn.execute(
        f"""SELECT character_id, user_id, score, relationship_stage, mood, memory_tags, event_flags, score_delta_reason
            FROM {data_table}"""
    ).fetchall()
    for char_id, user_id, score, rel, mood, memory_tags_json, event_flags_json, reason in rows:
        memory_tags = []
        event_flags = {}
        if memory_tags_json:
            try:
                parsed_tags = json.loads(memory_tags_json)
                if isinstance(parsed_tags, list):
                    memory_tags = parsed_tags
            except Exception:
                pass
        if event_flags_json:
            try:
                parsed_flags = json.loads(event_flags_json)
                if isinstance(parsed_flags, dict):
                    event_flags = parsed_flags
            except Exception:
                pass
        result[(str(char_id), int(user_id))] = {
            "relationship_stage": str(rel or "").strip(),
            "mood": str(mood or "").strip(),
            "memory_tags": memory_tags,
            "event_flags": event_flags,
            "score_delta_reason": str(reason or "").strip(),
            "scoreChange": 0,
            "currentScore": int(score or 0),
        }
    return result


def backfill_table(
    conn: sqlite3.Connection,
    messages_table: str,
    data_table: str,
    apply_changes: bool,
) -> Dict[str, int]:
    stats = {
        "rows_total": 0,
        "need_backfill": 0,
        "recovered_from_raw": 0,
        "recovered_from_html": 0,
        "written": 0,
        "skipped_no_data": 0,
        "failed_update": 0,
    }

    fallback_map = load_fallback_map(conn, data_table)
    rows = conn.execute(
        f"""SELECT id, character_id, user_id, role, content, raw_content, scene_metadata
            FROM {messages_table}
            WHERE role = 'assistant'"""
    ).fetchall()
    stats["rows_total"] = len(rows)

    for msg_id, char_id, user_id, role, content, raw_content, scene_metadata in rows:
        # 已有 scene_metadata 且可解析则不覆盖
        has_valid_scene_metadata = False
        if scene_metadata:
            try:
                parsed = json.loads(scene_metadata)
                has_valid_scene_metadata = isinstance(parsed, dict) and len(parsed) > 0
            except Exception:
                has_valid_scene_metadata = False
        if has_valid_scene_metadata:
            continue

        stats["need_backfill"] += 1
        recovered: Optional[Dict] = None

        if raw_content:
            recovered = _parse_scene_metadata_from_raw(raw_content)
            if recovered:
                stats["recovered_from_raw"] += 1

        if not recovered:
            fallback = fallback_map.get((str(char_id), int(user_id)), {})
            recovered = _parse_scene_metadata_from_content_html(content or "", fallback=fallback)
            if recovered:
                stats["recovered_from_html"] += 1

        if not recovered:
            stats["skipped_no_data"] += 1
            continue

        if apply_changes:
            try:
                conn.execute(
                    f"UPDATE {messages_table} SET scene_metadata = ? WHERE id = ?",
                    (json.dumps(recovered, ensure_ascii=False), msg_id),
                )
                stats["written"] += 1
            except Exception:
                stats["failed_update"] += 1

    return stats


def print_stats(table: str, stats: Dict[str, int]) -> None:
    print(f"\n[{table}]")
    for k in [
        "rows_total",
        "need_backfill",
        "recovered_from_raw",
        "recovered_from_html",
        "written",
        "skipped_no_data",
        "failed_update",
    ]:
        print(f"  - {k}: {stats.get(k, 0)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill scene_metadata for galgame messages")
    parser.add_argument(
        "--db-path",
        default=None,
        help="SQLite 数据库路径（默认 backend/database/ponychat.db；相对路径相对 backend 包根）",
    )
    parser.add_argument("--apply", action="store_true", help="Apply updates (default is dry-run)")
    args = parser.parse_args()

    _backend = backend_package_dir(ROOT)
    if args.db_path is None:
        db_path = _backend / "database" / "ponychat.db"
    else:
        db_path = Path(args.db_path)
        if not db_path.is_absolute():
            db_path = _backend / db_path
    if not db_path.exists():
        print(f"[error] db not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_scene_metadata_column(conn, "galgame_messages")
        ensure_scene_metadata_column(conn, "galgame_lock_messages")

        normal_stats = backfill_table(
            conn=conn,
            messages_table="galgame_messages",
            data_table="galgame_data",
            apply_changes=args.apply,
        )
        lock_stats = backfill_table(
            conn=conn,
            messages_table="galgame_lock_messages",
            data_table="galgame_lock_data",
            apply_changes=args.apply,
        )

        if args.apply:
            conn.commit()
            print("\n[done] apply mode: committed")
        else:
            conn.rollback()
            print("\n[done] dry-run mode: no data changed")

        print_stats("galgame_messages", normal_stats)
        print_stats("galgame_lock_messages", lock_stats)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

