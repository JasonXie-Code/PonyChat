"""Music-site statistics, proxied through the authenticated admin API."""
import secrets
import base64
import binascii
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from datetime import date
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from .system import load_admin_config

router = APIRouter(prefix='/music')


def connection():
    path = Path(__file__).resolve().parents[3] / '.secrets/music-analytics.json'
    config = json.loads(path.read_text('utf-8')) if path.is_file() else {}
    url = os.environ.get('PONYCHAT_MUSIC_STATS_URL', config.get('url', 'http://127.0.0.1:8822/api/analytics/summary'))
    token = os.environ.get('PONYCHAT_MUSIC_STATS_TOKEN', config.get('token', ''))
    parsed = urlparse(url)
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', '::1')):
        raise ValueError('Music statistics must use HTTPS or loopback')
    return url, {'X-Music-Analytics-Token': token} if token else {}


def authenticate(authorization: str = Header(default='')):
    try:
        scheme, encoded = authorization.split(' ', 1)
        if scheme.lower() != 'basic':
            raise ValueError('Invalid scheme')
        supplied_user, supplied_password = base64.b64decode(encoded, validate=True).decode('utf-8').split(':', 1)
    except (ValueError, UnicodeError, binascii.Error):
        raise HTTPException(401, '请重新登录管理后台')
    config = load_admin_config()
    username = str(config.get('username', 'admin'))
    password = str(config.get('password', ''))
    if not password or not (secrets.compare_digest(supplied_user.encode(), username.encode()) and secrets.compare_digest(supplied_password.encode(), password.encode())):
        raise HTTPException(401, '管理员凭据无效，请重新登录')


@router.get('/stats', dependencies=[Depends(authenticate)])
async def stats(response_headers: Response, start: date | None = None, end: date | None = None, days: int = Query(7, ge=1, le=366)):
    response_headers.headers['Cache-Control'] = 'no-store'
    if start and end and (start > end or (end - start).days >= 366):
        raise HTTPException(400, '日期范围应为 1 至 366 天')
    params = {'days': days}
    if start:
        params['start'] = start.isoformat()
    if end:
        params['end'] = end.isoformat()
    try:
        url, headers = connection()
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(url, params=params, headers=headers)
        if response.status_code in (400, 422):
            raise HTTPException(response.status_code, '日期范围无效，应为 1 至 366 天')
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(503, '音乐站统计服务暂不可用，请确认已部署统计采集服务') from error
