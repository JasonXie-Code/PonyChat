"""Public event ingestion and loopback-only administrative aggregation."""
from datetime import date, datetime, timedelta
from functools import lru_cache
import json
import time
import os
from pathlib import Path
import secrets
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from analytics_store import ZONE, record, summary
from runtime_paths import data_root

router = APIRouter(prefix='/api/analytics')
DATA = data_root()


@lru_cache(maxsize=1)
def song_catalog(minute):
    # Analytics needs only the index allowlist and catalog title overrides.
    # Never trigger lyrics, follow certification, frontend hashing or media scans.
    index_path, catalog_path = DATA / 'index.json', DATA / 'catalog.json'
    index = json.loads(index_path.read_bytes()) if index_path.is_file() else {'songs': []}
    catalog = json.loads(catalog_path.read_bytes()) if catalog_path.is_file() else {}
    return {song['id']: catalog.get(song['id'], {}).get('title', song.get('title', song['id']))
            for song in index.get('songs', [])}


class Event(BaseModel):
    kind: Literal['visit', 'play']
    id: str = Field(pattern=r'^[a-zA-Z0-9-]{16,80}$')
    visitor: str = Field(pattern=r'^[a-zA-Z0-9-]{16,80}$')
    song: str = Field(default='', max_length=200)
    seconds: float = Field(default=0, ge=0, le=604800, allow_inf_nan=False)


@router.post('/events', status_code=204)
def events(body: Event):
    if body.kind == 'play' and body.song not in song_catalog(int(time.monotonic() // 60)):
        raise HTTPException(400, '歌曲不存在')
    try:
        record(body.model_dump())
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.get('/summary')
def stats(request: Request, start: date | None = None, end: date | None = None, days: int = Query(7, ge=1, le=366)):
    local = bool(request.client and request.client.host in ('127.0.0.1', '::1') and not any(h in request.headers for h in ('x-forwarded-for', 'x-real-ip', 'forwarded')))
    if not local:
        token_file = os.environ.get('MLP_ANALYTICS_TOKEN_FILE', '')
        try:
            expected = Path(token_file).read_text('utf-8').strip() if token_file else ''
        except OSError:
            expected = ''
        supplied = request.headers.get('x-music-analytics-token', '')
        if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(403, '仅允许管理服务访问')
    end = end or datetime.now(ZONE).date()
    start = start or end - timedelta(days=days - 1)
    if start > end or (end - start).days >= 366:
        raise HTTPException(400, '日期范围应为 1 至 366 天')
    songs = song_catalog(int(time.monotonic() // 60))
    return summary(start, end, songs)
