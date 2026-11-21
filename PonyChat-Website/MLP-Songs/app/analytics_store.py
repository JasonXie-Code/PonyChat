"""Durable, anonymous music usage counters. All calendar dates use Asia/Shanghai."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sqlite3
import time

ZONE = timezone(timedelta(hours=8))
DB_PATH = Path(os.environ.get('MLP_ANALYTICS_DB', str(Path(__file__).resolve().parents[1] / '.runtime/analytics.sqlite3')))


def day(stamp):
    return datetime.fromtimestamp(stamp, ZONE).date().isoformat()


@contextmanager
def connect(path=DB_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS visits(id TEXT PRIMARY KEY,visitor TEXT,day TEXT);
            CREATE INDEX IF NOT EXISTS visits_day ON visits(day,visitor);
            CREATE TABLE IF NOT EXISTS plays(id TEXT PRIMARY KEY,visitor TEXT,song TEXT,day TEXT,
                reported REAL DEFAULT 0,last_at REAL);
            CREATE INDEX IF NOT EXISTS plays_day ON plays(day,song);
            CREATE TABLE IF NOT EXISTS listening(day TEXT,song TEXT,seconds REAL,
                PRIMARY KEY(day,song));
            CREATE TABLE IF NOT EXISTS traffic(day TEXT,category TEXT,bytes INTEGER,requests INTEGER,
                PRIMARY KEY(day,category));
            CREATE TABLE IF NOT EXISTS log_cursors(identity TEXT PRIMARY KEY,offset INTEGER);
        ''')
        conn.execute("INSERT OR IGNORE INTO meta VALUES('since',?)", (datetime.now(ZONE).isoformat(),))
        conn.commit()
        yield conn
    finally:
        conn.close()


def record(event, path=DB_PATH, now=None):
    now = time.time() if now is None else now
    with connect(path) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        if event['kind'] == 'visit':
            conn.execute('INSERT OR IGNORE INTO visits VALUES(?,?,?)', (event['id'], event['visitor'], day(now)))
            return
        row = conn.execute('SELECT * FROM plays WHERE id=?', (event['id'],)).fetchone()
        if row is None:
            conn.execute('INSERT INTO plays(id,visitor,song,day,last_at) VALUES(?,?,?,?,?)',
                         (event['id'], event['visitor'], event['song'], day(now), now))
            # The first report starts a play; time before it cannot be verified.
            if event['seconds']:
                conn.execute('UPDATE plays SET reported=? WHERE id=?', (event['seconds'], event['id']))
            return
        if row['visitor'] != event['visitor'] or row['song'] != event['song']:
            raise ValueError('播放标识与歌曲不匹配')
        reported = event['seconds']
        if reported <= row['reported']:
            return
        delta = min(reported - row['reported'], max(0, now - row['last_at']) + 2, 120)
        conn.execute('UPDATE plays SET reported=?,last_at=? WHERE id=?', (reported, now, event['id']))
        # Split a heartbeat crossing midnight into the appropriate calendar days.
        cursor = now - delta
        while cursor < now:
            next_day = datetime.fromtimestamp(cursor, ZONE).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            end = min(now, next_day.timestamp())
            conn.execute('INSERT INTO listening VALUES(?,?,?) ON CONFLICT(day,song) DO UPDATE SET seconds=seconds+excluded.seconds',
                         (day(cursor), event['song'], end - cursor))
            cursor = end


def summary(start, end, songs, path=DB_PATH):
    from analytics_traffic import collect
    traffic_status = collect(path)
    with connect(path) as conn:
        daily = {}
        cursor = start
        while cursor <= end:
            daily[cursor.isoformat()] = dict(date=cursor.isoformat(), visitors=0, visits=0, plays=0, seconds=0, bytes=0, requests=0)
            cursor += timedelta(days=1)
        args = (start.isoformat(), end.isoformat())
        for row in conn.execute('SELECT day,COUNT(*) visits,COUNT(DISTINCT visitor) visitors FROM visits WHERE day BETWEEN ? AND ? GROUP BY day', args):
            daily[row['day']].update(visits=row['visits'], visitors=row['visitors'])
        for table, field, expr in [('plays', 'plays', 'COUNT(*)'), ('listening', 'seconds', 'SUM(seconds)'), ('traffic', 'bytes', 'SUM(bytes)')]:
            for row in conn.execute(f'SELECT day,{expr} value FROM {table} WHERE day BETWEEN ? AND ? GROUP BY day', args):
                daily[row['day']][field] = row['value']
        for row in conn.execute('SELECT day,SUM(requests) value FROM traffic WHERE day BETWEEN ? AND ? GROUP BY day', args):
            daily[row['day']]['requests'] = row['value']
        totals = {key: sum(r[key] for r in daily.values()) for key in ('visits', 'plays', 'seconds', 'bytes', 'requests')}
        totals['visitors'] = conn.execute('SELECT COUNT(DISTINCT visitor) FROM visits WHERE day BETWEEN ? AND ?', args).fetchone()[0]
        ranking = {}
        for row in conn.execute('SELECT song,COUNT(*) plays,COUNT(DISTINCT visitor) listeners FROM plays WHERE day BETWEEN ? AND ? GROUP BY song', args):
            ranking[row['song']] = dict(id=row['song'], title=songs.get(row['song'], row['song']), plays=row['plays'], listeners=row['listeners'], seconds=0)
        for row in conn.execute('SELECT song,SUM(seconds) seconds FROM listening WHERE day BETWEEN ? AND ? GROUP BY song', args):
            ranking.setdefault(row['song'], dict(id=row['song'], title=songs.get(row['song'], row['song']), plays=0, listeners=0, seconds=0))['seconds'] = row['seconds']
        categories = [dict(r) for r in conn.execute('SELECT category,SUM(bytes) bytes,SUM(requests) requests FROM traffic WHERE day BETWEEN ? AND ? GROUP BY category ORDER BY bytes DESC', args)]
        return dict(start=args[0], end=args[1], timezone='Asia/Shanghai', since=conn.execute("SELECT value FROM meta WHERE key='since'").fetchone()[0],
                    totals=totals, daily=list(daily.values()), songs=sorted(ranking.values(), key=lambda r: (-r['plays'], -r['seconds']))[:50],
                    traffic=dict(traffic_status, categories=categories))
