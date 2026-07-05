#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate D/W/M memory layers for a specific calendar month."""

from __future__ import annotations

import argparse
import asyncio
import sys
import types
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable


if __package__ in (None, ""):
    backend_dir = Path(__file__).resolve().parents[1]
    project_root = backend_dir.parent
    sys.path.insert(0, str(project_root))
    if "Backend" not in sys.modules:
        pkg = types.ModuleType("Backend")
        pkg.__path__ = [str(backend_dir)]  # type: ignore[attr-defined]
        pkg.__file__ = str(backend_dir / "__init__.py")
        sys.modules["Backend"] = pkg

from Backend.config import DB_PATH
from Backend.db.database import get_database
from Backend.db.memory_dao import (
    LAYER_DAILY,
    LAYER_MONTHLY,
    LAYER_WEEKLY,
    get_c_memories_for_period,
    get_layer_memories_all,
    get_raw_chat_messages_for_day,
)
from Backend.memory.scheduler import _day_to_week, _generate_daily, _generate_monthly, _generate_weekly


@dataclass
class Pair:
    username: str
    character_id: str
    char_name: str


def out(message: str = "") -> None:
    print(message, flush=True)


def _parse_month(value: str) -> tuple[date, date, str]:
    start = datetime.strptime(value, "%Y-%m").date().replace(day=1)
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start, end, start.strftime("%Y-%m")


def _days(start: date, end: date) -> Iterable[str]:
    current = start
    while current < end:
        yield current.isoformat()
        current += timedelta(days=1)


def _iso_week_monday(week: str) -> date:
    year_num, week_num = int(week[:4]), int(week[6:])
    return date.fromisocalendar(year_num, week_num, 1)


async def _list_pairs_for_month(month: str) -> list[Pair]:
    db = get_database()
    conn = await db.acquire()
    try:
        cursor = await conn.execute(
            """SELECT username, character_id, char_name, MAX(last_seen) AS last_seen
               FROM (
                   SELECT u.username AS username,
                          c.character_id AS character_id,
                          COALESCE(ch.name, c.character_id) AS char_name,
                          MAX(COALESCE(m.timestamp, 0)) AS last_seen
                     FROM conversations c
                     JOIN users u ON c.user_id = u.id
                     LEFT JOIN characters ch ON ch.id = c.character_id
                     JOIN messages m ON m.conversation_id = c.id
                    WHERE COALESCE(c.is_hidden, 0) = 0
                      AND COALESCE(m.is_hidden, 0) = 0
                      AND m.deleted_at IS NULL
                      AND m.role IN ('user', 'assistant')
                      AND strftime('%Y-%m', COALESCE(m.timestamp, 0) / 1000, 'unixepoch') = ?
                    GROUP BY u.username, c.character_id, char_name
                   UNION ALL
                   SELECT u.username AS username,
                          m.character_id AS character_id,
                          COALESCE(ch.name, m.character_id) AS char_name,
                          MAX(strftime('%s', m.created_at) * 1000) AS last_seen
                     FROM character_memories m
                     JOIN users u ON m.user_id = u.id
                     LEFT JOIN characters ch ON ch.id = m.character_id
                    WHERE m.layer = 0
                      AND m.is_active = 1
                      AND strftime('%Y-%m', m.created_at) = ?
                    GROUP BY u.username, m.character_id, char_name
               )
               GROUP BY username, character_id, char_name
               ORDER BY last_seen DESC""",
            (month, month),
        )
        rows = await cursor.fetchall()
        return [Pair(str(r[0] or ""), str(r[1] or ""), str(r[2] or "角色")) for r in rows]
    finally:
        await db.release(conn)


async def _active_c_days_for_month(username: str, character_id: str, month: str) -> set[str]:
    db = get_database()
    conn = await db.acquire()
    try:
        cursor = await conn.execute(
            """SELECT DISTINCT strftime('%Y-%m-%d', m.created_at)
                 FROM character_memories m
                 JOIN users u ON m.user_id = u.id
                WHERE u.username = ?
                  AND m.character_id = ?
                  AND m.layer = 0
                  AND m.is_active = 1
                  AND strftime('%Y-%m', m.created_at) = ?
                ORDER BY 1 ASC""",
            (username, character_id, month),
        )
        return {str(r[0]) for r in await cursor.fetchall() if r[0]}
    finally:
        await db.release(conn)


async def _deactivate_layer_periods(username: str, character_id: str, layer: int, periods: list[str]) -> int:
    if not periods:
        return 0
    db = get_database()
    conn = await db.acquire()
    try:
        cursor = await conn.execute("SELECT id FROM users WHERE username=?", (username,))
        row = await cursor.fetchone()
        if not row:
            return 0
        placeholders = ",".join("?" * len(periods))
        result = await conn.execute(
            f"""UPDATE character_memories
                   SET is_active = 0
                 WHERE user_id = ?
                   AND character_id = ?
                   AND layer = ?
                   AND is_active = 1
                   AND period IN ({placeholders})""",
            (int(row[0]), character_id, layer, *periods),
        )
        await conn.commit()
        return int(result.rowcount or 0)
    finally:
        await db.release(conn)


async def _regenerate_pair(
    pair: Pair,
    month: str,
    start: date,
    end: date,
    reset_existing: bool,
    include_monthly: bool,
    only_monthly: bool,
) -> dict[str, int]:
    days_to_generate: list[str] = []
    weeks_to_generate: list[str] = []
    if not only_monthly:
        days_with_data = set(await _active_c_days_for_month(pair.username, pair.character_id, month))
        for day in _days(start, end):
            raw_messages = await get_raw_chat_messages_for_day(pair.username, pair.character_id, day)
            if raw_messages:
                days_with_data.add(day)

        days_to_generate = sorted(days_with_data)
        weeks_to_generate = sorted({_day_to_week(day) for day in days_to_generate})

    deactivated = 0
    if reset_existing:
        deactivated += await _deactivate_layer_periods(pair.username, pair.character_id, LAYER_DAILY, days_to_generate)
        deactivated += await _deactivate_layer_periods(pair.username, pair.character_id, LAYER_WEEKLY, weeks_to_generate)
        if include_monthly:
            deactivated += await _deactivate_layer_periods(pair.username, pair.character_id, LAYER_MONTHLY, [month])

    daily_ok = 0
    for day in days_to_generate:
        frag_mems = await get_c_memories_for_period(pair.username, pair.character_id, day, "day")
        raw_messages = await get_raw_chat_messages_for_day(pair.username, pair.character_id, day)
        if await _generate_daily(pair.username, pair.character_id, pair.char_name, day, frag_mems, raw_messages):
            daily_ok += 1

    all_daily = await get_layer_memories_all(pair.username, pair.character_id, LAYER_DAILY)
    weekly_ok = 0
    for week in weeks_to_generate:
        entries = [entry for entry in all_daily if _day_to_week(str(entry.get("period") or "")) == week]
        if entries and await _generate_weekly(pair.username, pair.character_id, pair.char_name, week, entries):
            weekly_ok += 1

    monthly_ok = 0
    if include_monthly:
        all_weekly = await get_layer_memories_all(pair.username, pair.character_id, LAYER_WEEKLY)
        monthly_entries = [
            entry
            for entry in all_weekly
            if _iso_week_monday(str(entry.get("period") or "")).strftime("%Y-%m") == month
        ]
        if monthly_entries and await _generate_monthly(pair.username, pair.character_id, pair.char_name, month, monthly_entries):
            monthly_ok = 1

    return {
        "days": len(days_to_generate),
        "weeks": len(weeks_to_generate),
        "deactivated": deactivated,
        "daily_ok": daily_ok,
        "weekly_ok": weekly_ok,
        "monthly_ok": monthly_ok,
    }


async def main_async(args: argparse.Namespace) -> int:
    try:
        start, end, month = _parse_month(args.month)
        pairs = await _list_pairs_for_month(month)
        out(f"[RegenerateLayers] DB={DB_PATH}")
        include_monthly = not args.skip_monthly
        out(
            f"[RegenerateLayers] month={month} pairs={len(pairs)} "
            f"reset_existing={args.reset_existing} include_monthly={include_monthly}"
        )
        if args.dry_run:
            for pair in pairs:
                out(f"  - {pair.username}/{pair.character_id[:8]}... {pair.char_name}")
            return 0

        totals = {"daily_ok": 0, "weekly_ok": 0, "monthly_ok": 0, "deactivated": 0}
        for idx, pair in enumerate(pairs, 1):
            out(f"[{idx}/{len(pairs)}] {pair.username}/{pair.character_id[:8]}... {pair.char_name}")
            stats = await _regenerate_pair(
                pair,
                month,
                start,
                end,
                args.reset_existing,
                include_monthly,
                args.only_monthly,
            )
            for key in totals:
                totals[key] += stats[key]
            out(
                "    "
                f"days={stats['days']} weeks={stats['weeks']} "
                f"daily={stats['daily_ok']} weekly={stats['weekly_ok']} monthly={stats['monthly_ok']} "
                f"deactivated={stats['deactivated']}"
            )

        out(
            "[RegenerateLayers] done "
            f"daily={totals['daily_ok']} weekly={totals['weekly_ok']} monthly={totals['monthly_ok']} "
            f"deactivated={totals['deactivated']}"
        )
        return 0
    finally:
        await get_database().close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Regenerate PonyChat memory D/W/M layers for one month.")
    parser.add_argument("--month", required=True, help="Calendar month, e.g. 2026-04.")
    parser.add_argument("--reset-existing", action="store_true", help="Deactivate existing D/W/M summaries for this month before regenerating.")
    parser.add_argument("--skip-monthly", action="store_true", help="Only regenerate daily and weekly layers.")
    parser.add_argument("--only-monthly", action="store_true", help="Only regenerate monthly layer from existing weekly summaries.")
    parser.add_argument("--dry-run", action="store_true", help="Only list candidate user-character pairs.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
