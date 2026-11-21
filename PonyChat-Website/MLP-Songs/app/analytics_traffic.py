"""Incrementally import Nginx body bytes, including Range/206 responses."""
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import hashlib
import os
import re

LOG_PATH = Path(os.environ.get('MLP_ANALYTICS_LOG', '/var/log/nginx/mlp-music-analytics.log'))
LINE = re.compile(rb'\[([^\]]+)\] "(?:GET|HEAD|POST|OPTIONS) ([^ ]+) [^"]+" (\d{3}) (\d+) ')
CATEGORIES = {'audio': '音频', 'scores': '乐谱', 'covers': '封面', 'charts': '曲谱图片', 'follow-media': '跟唱资源', 'api': '接口'}


def collect(db_path, log_path=LOG_PATH):
    from analytics_store import connect, day
    available = False
    skipped = 0
    try:
        # Standard nginx logrotate keeps the newest rotated file uncompressed.
        for path in (Path(str(log_path) + '.1'), log_path):
            if not path.is_file():
                continue
            available = True
            with path.open('rb') as log, connect(db_path) as conn, conn:
                stat = os.fstat(log.fileno())
                prefix = log.readline()
                # Prefix prevents inode reuse/copytruncate from retaining a stale cursor.
                identity = f'{stat.st_dev}:{stat.st_ino}:' + hashlib.sha256(prefix).hexdigest()
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute('SELECT offset FROM log_cursors WHERE identity=?', (identity,)).fetchone()
                offset = row['offset'] if row and row['offset'] <= stat.st_size else 0
                log.seek(offset)
                buckets = defaultdict(lambda: [0, 0])
                # Bound one refresh; the next refresh continues from the saved cursor.
                for _ in range(100000):
                    line = log.readline()
                    if not line or not line.endswith(b'\n'):
                        break
                    offset = log.tell()
                    match = LINE.search(line)
                    if not match:
                        skipped += 1
                        continue
                    stamp, uri, status, size = match.groups()
                    try:
                        date = day(datetime.strptime(stamp.decode(), '%d/%b/%Y:%H:%M:%S %z').timestamp())
                    except ValueError:
                        skipped += 1
                        continue
                    # Internal summary polling is not website traffic.
                    if uri.startswith(b'/api/analytics/summary'):
                        continue
                    category = CATEGORIES.get(uri.decode(errors='replace').lstrip('/').split('/')[0], '网页及其他')
                    bucket = buckets[date, category]
                    bucket[0] += int(size)
                    bucket[1] += 1
                for (date, category), (size, requests) in buckets.items():
                    conn.execute('INSERT INTO traffic VALUES(?,?,?,?) ON CONFLICT(day,category) DO UPDATE SET bytes=bytes+excluded.bytes,requests=requests+excluded.requests', (date, category, size, requests))
                conn.execute('INSERT OR REPLACE INTO log_cursors VALUES(?,?)', (identity, offset))
        return dict(available=available, error='' if available else '尚未接入音乐站 Nginx 流量日志', skipped=skipped)
    except OSError:
        return dict(available=False, error='无法读取音乐站 Nginx 流量日志，请检查权限', skipped=skipped)
