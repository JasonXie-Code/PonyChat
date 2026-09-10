"""Inject calendar summaries every normal turn, with original evidence validation."""
from contextlib import closing
from datetime import datetime, timedelta
import json

from . import evidence
from .schema import connect


def calendar_periods(now):
    today = now.astimezone(evidence.LOCAL).date()
    monday = today - timedelta(days=today.weekday())
    daily = [(monday + timedelta(days=i)).isoformat() for i in range(today.weekday() + 1)]
    first = today.replace(day=1)
    week = first - timedelta(days=first.weekday())
    weekly = []
    while week <= today:
        year, number, _ = week.isocalendar()
        weekly.append(f"{year:04d}-W{number:02d}")
        week += timedelta(days=7)
    monthly = [f"{today.year:04d}-{month:02d}" for month in range(1, today.month + 1)]
    return today, {"daily": daily, "weekly": weekly, "monthly": monthly}


def build_calendar_context(store, *, now=None):
    now = now or datetime.now(evidence.LOCAL)
    today, periods = calendar_periods(now)
    result = {"as_of": now.astimezone(evidence.LOCAL).isoformat(), "timezone": "Asia/Shanghai",
              "week_starts_on": "Monday", "weekly_membership": "ISO weeks overlapping current month through today",
              "daily": [], "weekly": [], "monthly": [], "annual": []}
    with closing(connect(store.path)) as conn:
        # One read snapshot for heads, reset generation, raw evidence and period hashes.
        conn.execute('BEGIN')
        state = conn.execute('SELECT epoch,enabled FROM agent_memory_state WHERE username=? AND character_id=?',
                             (store.username, store.character_id)).fetchone()
        if not state or state['epoch'] != store.epoch or not state['enabled']:
            return None
        pairs = [(category, period) for category, values in periods.items() for period in values]
        conditions = " OR ".join("(v.category=? AND v.period=?)" for _ in pairs)
        rows = conn.execute('''SELECT v.* FROM agent_memory_heads h JOIN agent_memory_versions v
          ON h.entry_id=v.entry_id AND h.version=v.version
          WHERE h.username=? AND h.character_id=? AND h.epoch=? AND v.status<>'retracted'
          AND (v.category='annual' OR ''' + conditions + ') ORDER BY v.period,v.version',
          [store.username, store.character_id, store.epoch, *(v for pair in pairs for v in pair)]).fetchall()
        found = {}
        for row in rows:
            try:
                start, end = evidence.period_bounds(row['category'], row['period'])
                if start > int(now.timestamp() * 1000) or not evidence.valid(conn, store.username, store.character_id, row):
                    continue
            except (ValueError, TypeError):
                continue
            found[(row['category'], row['period'])] = {
                'period': row['period'], 'status': 'available', 'content': row['content'],
                'entry_id': row['entry_id'], 'version': row['version'],
                'source_ref': f"memory:{row['entry_id']}:{row['version']}",
                'source_message_ids': json.loads(row['source_message_ids']),
                'updated_at': row['created_at'], 'certainty': row['certainty'],
                'in_progress': end > int(now.timestamp() * 1000)}
        for category, values in periods.items():
            result[category] = [found.get((category, period), {'period': period, 'status': 'missing'}) for period in values]
        # All valid annual summaries, with no top-k or character truncation.
        result['annual'] = [value for (category, _), value in sorted(found.items()) if category == 'annual']
    return result
