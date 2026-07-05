#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backfill character_memories C/D/W/M/A layers from existing normal chat history.

Usage from project root:
  python Backend/scripts/backfill_character_memory_layers.py --all-pairs

The script is idempotent by default for extraction: pairs that already have
active C-layer memories with source="chat_backfill" are skipped unless --force
is supplied. Layer generation itself is period-aware and skips existing
Daily/Weekly/Monthly summaries.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite


if __package__ in (None, ""):
    backend_dir = Path(__file__).resolve().parents[1]
    project_root = backend_dir.parent
    sys.path.insert(0, str(project_root))
    if "Backend" not in sys.modules:
        pkg = types.ModuleType("Backend")
        pkg.__path__ = [str(backend_dir)]  # type: ignore[attr-defined]
        pkg.__file__ = str(backend_dir / "__init__.py")
        sys.modules["Backend"] = pkg

from Backend.config import DB_PATH, logger
from Backend.db.database import get_database
from Backend.memory.extractor import do_extract
from Backend.memory.scheduler import run_layer_cycle_once


BACKFILL_SOURCE = "chat_backfill"


def out(message: str = "") -> None:
    print(message, flush=True)


async def _ensure_state_table() -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA busy_timeout = 5000")
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS memory_consolidation_state (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_id INTEGER NOT NULL,
                   character_id TEXT NOT NULL,
                   last_consolidated_message_ts INTEGER DEFAULT 0,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE(user_id, character_id),
                   FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                   FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
               )"""
        )
        await conn.commit()


@dataclass
class Pair:
    username: str
    character_id: str
    char_name: str
    message_count: int
    user_turns: int
    first_ts: int
    last_ts: int


async def _list_pairs(max_pairs: Optional[int]) -> list[Pair]:
    db = get_database()
    conn = await db.acquire()
    try:
        limit_sql = "" if not max_pairs or max_pairs <= 0 else "LIMIT ?"
        params: tuple = () if not limit_sql else (int(max_pairs),)
        cursor = await conn.execute(
            f"""SELECT u.username,
                       c.character_id,
                       COALESCE(ch.name, c.character_id) AS char_name,
                       COUNT(m.id) AS message_count,
                       SUM(CASE WHEN m.role='user' THEN 1 ELSE 0 END) AS user_turns,
                       MIN(COALESCE(m.timestamp, 0)) AS first_ts,
                       MAX(COALESCE(m.timestamp, 0)) AS last_ts
                FROM conversations c
                JOIN users u ON c.user_id = u.id
                LEFT JOIN characters ch ON ch.id = c.character_id
                JOIN messages m ON m.conversation_id = c.id
                WHERE COALESCE(c.is_hidden, 0) = 0
                  AND COALESCE(m.is_hidden, 0) = 0
                  AND m.deleted_at IS NULL
                  AND m.role IN ('user', 'assistant')
                GROUP BY u.username, c.character_id, char_name
                HAVING user_turns >= 2
                ORDER BY last_ts DESC
                {limit_sql}""",
            params,
        )
        rows = await cursor.fetchall()
        return [
            Pair(
                username=str(r[0] or ""),
                character_id=str(r[1] or ""),
                char_name=str(r[2] or "角色"),
                message_count=int(r[3] or 0),
                user_turns=int(r[4] or 0),
                first_ts=int(r[5] or 0),
                last_ts=int(r[6] or 0),
            )
            for r in rows
        ]
    finally:
        await db.release(conn)


async def _has_backfill_source(username: str, character_id: str) -> bool:
    db = get_database()
    conn = await db.acquire()
    try:
        cursor = await conn.execute(
            """SELECT COUNT(*)
               FROM character_memories m
               JOIN users u ON m.user_id = u.id
               WHERE u.username = ?
                 AND m.character_id = ?
                 AND m.layer = 0
                 AND m.is_active = 1
                 AND m.source = ?""",
            (username, character_id, BACKFILL_SOURCE),
        )
        row = await cursor.fetchone()
        return bool(row and int(row[0] or 0) > 0)
    finally:
        await db.release(conn)


async def _reset_backfill(include_summaries: bool) -> None:
    db = get_database()
    conn = await db.acquire()
    try:
        await conn.execute(
            "UPDATE character_memories SET is_active=0 WHERE source=?",
            (BACKFILL_SOURCE,),
        )
        if include_summaries:
            await conn.execute(
                "UPDATE character_memories SET is_active=0 WHERE source='consolidator' AND layer>0"
            )
        await conn.commit()
    finally:
        await db.release(conn)


async def _set_pair_state(username: str, character_id: str, last_ms: int) -> None:
    if last_ms <= 0:
        return
    db = get_database()
    conn = await db.acquire()
    try:
        cur = await conn.execute("SELECT id FROM users WHERE username=?", (username,))
        row = await cur.fetchone()
        if not row:
            return
        user_id = int(row[0])
        await conn.execute(
            """INSERT INTO memory_consolidation_state
                   (user_id, character_id, last_consolidated_message_ts, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id, character_id) DO UPDATE SET
                   last_consolidated_message_ts=excluded.last_consolidated_message_ts,
                   updated_at=CURRENT_TIMESTAMP""",
            (user_id, character_id, int(last_ms)),
        )
        await conn.commit()
    finally:
        await db.release(conn)


async def _load_pair_messages(username: str, character_id: str) -> list[dict]:
    db = get_database()
    conn = await db.acquire()
    try:
        cur = await conn.execute("SELECT id FROM users WHERE username=?", (username,))
        user_row = await cur.fetchone()
        if not user_row:
            return []
        user_id = int(user_row[0])
        cursor = await conn.execute(
            """SELECT m.role, m.content, COALESCE(m.timestamp, 0)
               FROM messages m
               JOIN conversations c ON m.conversation_id = c.id
               WHERE c.user_id = ?
                 AND c.character_id = ?
                 AND COALESCE(c.is_hidden, 0) = 0
                 AND COALESCE(m.is_hidden, 0) = 0
                 AND m.deleted_at IS NULL
                 AND m.role IN ('user', 'assistant')
               ORDER BY COALESCE(m.timestamp, 0) ASC, COALESCE(m.sequence_number, 0) ASC, m.rowid ASC""",
            (user_id, character_id),
        )
        rows = await cursor.fetchall()
        return [
            {"role": r[0], "content": str(r[1] or ""), "timestamp": int(r[2] or 0)}
            for r in rows
        ]
    finally:
        await db.release(conn)


def _day_key(timestamp_ms: int) -> str:
    if timestamp_ms <= 0:
        return "1970-01-01"
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def _sqlite_utc(timestamp_ms: int) -> str:
    if timestamp_ms <= 0:
        timestamp_ms = 1
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _chunks(items: list[dict], size: int = 40) -> list[list[dict]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _extract_pair_by_history_day(pair: Pair) -> int:
    messages = await _load_pair_messages(pair.username, pair.character_id)
    if not messages:
        return 0

    by_day: dict[str, list[dict]] = {}
    for message in messages:
        by_day.setdefault(_day_key(int(message.get("timestamp") or 0)), []).append(message)

    total = 0
    for day, day_messages in sorted(by_day.items()):
        user_turns = sum(1 for m in day_messages if m.get("role") == "user")
        if user_turns < 1:
            continue
        for chunk in _chunks(day_messages, 40):
            chunk_ts = max(int(m.get("timestamp") or 0) for m in chunk)
            total += await do_extract(
                pair.username,
                pair.character_id,
                chunk,
                source=BACKFILL_SOURCE,
                created_at=_sqlite_utc(chunk_ts),
            )

    await _set_pair_state(pair.username, pair.character_id, pair.last_ts)
    return total


async def main_async(args: argparse.Namespace) -> int:
    try:
        await _ensure_state_table()

        pairs = await _list_pairs(args.max_pairs)
        out(f"[Backfill] DB={DB_PATH}")
        out(f"[Backfill] candidate pairs={len(pairs)}")
        if args.dry_run:
            for p in pairs:
                out(
                    f"  - {p.username}/{p.character_id[:8]}... "
                    f"messages={p.message_count} user_turns={p.user_turns}"
                )
            return 0

        if args.reset_backfill:
            out("[Backfill] resetting prior chat_backfill memories and generated summaries...")
            await _reset_backfill(include_summaries=True)

        extracted_pairs = 0
        skipped_pairs = 0
        total_written = 0

        if not args.layers_only:
            for idx, pair in enumerate(pairs, 1):
                if not args.force and await _has_backfill_source(pair.username, pair.character_id):
                    skipped_pairs += 1
                    out(f"[{idx}/{len(pairs)}] skip existing backfill {pair.username}/{pair.character_id[:8]}...")
                    continue
                out(
                    f"[{idx}/{len(pairs)}] extract {pair.username}/{pair.character_id[:8]}... "
                    f"messages={pair.message_count} user_turns={pair.user_turns}"
                )
                written = await _extract_pair_by_history_day(pair)
                total_written += written
                extracted_pairs += 1
                out(f"    wrote C-layer memories={written}")

        processed_layer_pairs = 0
        if not args.extract_only:
            out("[Backfill] generating D/W/M/A layers...")
            processed_layer_pairs = await run_layer_cycle_once(max_pairs=0 if args.all_pairs else args.max_pairs)

        out(
            "[Backfill] done "
            f"extracted_pairs={extracted_pairs} skipped_pairs={skipped_pairs} "
            f"c_memories_written={total_written} layer_pairs_scanned={processed_layer_pairs}"
        )
        return 0
    finally:
        await get_database().close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill PonyChat character memory layers.")
    parser.add_argument("--all-pairs", action="store_true", help="Process all user-character pairs.")
    parser.add_argument("--max-pairs", type=int, default=0, help="Limit pairs; 0 means all.")
    parser.add_argument("--force", action="store_true", help="Extract again even if chat_backfill C memories exist.")
    parser.add_argument("--reset-backfill", action="store_true", help="Deactivate prior chat_backfill C memories and generated summaries before running.")
    parser.add_argument("--dry-run", action="store_true", help="Only list candidate pairs.")
    parser.add_argument("--layers-only", action="store_true", help="Skip C extraction and only generate D/W/M/A layers.")
    parser.add_argument("--extract-only", action="store_true", help="Only extract C memories, skip D/W/M/A generation.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.all_pairs:
        args.max_pairs = 0
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        out("[Backfill] cancelled")
        return 130
    except Exception as exc:
        logger.exception("[Backfill] failed: %s", exc)
        out(f"[Backfill] failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
