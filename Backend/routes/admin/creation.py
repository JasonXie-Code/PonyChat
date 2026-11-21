"""Administrative access to durable creative sessions."""
import asyncio
import time
from fastapi import APIRouter, HTTPException, Query
from ...creation import store
from ..creation import Settings
from ...config import DB_PATH

router = APIRouter(prefix='/creation')


def listing(path, q='', page=1, limit=30):
    with store.connect(path) as conn:
        where = "WHERE (?='' OR instr(lower(u.username || ' ' || ch.name || ' ' || s.title),lower(?))>0)"
        joins = 'FROM creation_sessions s JOIN users u ON u.id=s.user_id JOIN characters ch ON ch.id=s.character_id '
        total = conn.execute('SELECT COUNT(*) ' + joins + where, (q, q)).fetchone()[0]
        rows = conn.execute('SELECT s.id,s.title,s.version,s.updated_ms,s.busy_until,s.last_error,'
            'u.username,ch.name AS character_name,ch.avatar AS character_avatar,s.character_id,'
            '(SELECT COUNT(*) FROM creation_messages m WHERE m.session_id=s.id) AS message_count,'
            '(SELECT MIN(timestamp) FROM creation_messages m WHERE m.session_id=s.id) AS created_ms,'
            '(SELECT substr(content,1,200) FROM creation_messages m WHERE m.session_id=s.id ORDER BY sequence DESC LIMIT 1) AS last_message '
            + joins + where + ' ORDER BY s.updated_ms DESC,s.id LIMIT ? OFFSET ?',
            (q, q, limit, (page-1)*limit))
        return {'sessions': [{**dict(r), 'busy': r['busy_until'] > time.time()} for r in rows],
                'total': total, 'page': page, 'limit': limit}


def detail(conn, sid):
    row = conn.execute('SELECT s.*,u.username,ch.name AS character_name,ch.avatar AS character_avatar FROM creation_sessions s '
        'JOIN users u ON u.id=s.user_id JOIN characters ch ON ch.id=s.character_id WHERE s.id=?', (sid,)).fetchone()
    if not row:
        raise HTTPException(404, '创造会话不存在')
    data = store.session_row(conn, row['username'], sid)
    return {**store.view(conn, data), 'username': row['username'], 'character_name': row['character_name'],
            'character_avatar': row['character_avatar'] or ''}


def operate(path, sid, action='get', version=None, values=None, message_id=None):
    with store.connect(path) as conn, conn:
        if action != 'get':
            conn.execute('BEGIN IMMEDIATE')
        data = detail(conn, sid)
        if action == 'get':
            return data
        if data['busy'] or data['version'] != version:
            raise HTTPException(409, '会话正在生成或已更新，请刷新后重试')
        now = int(time.time()*1000)
        if action == 'settings':
            conn.execute('UPDATE creation_sessions SET title=?,instructions=?,character_setting=?,version=version+1,updated_ms=? WHERE id=?',
                (values['title'], values['instructions'], values.get('character_setting'), now, sid))
        elif action == 'message':
            if not conn.execute('DELETE FROM creation_messages WHERE session_id=? AND id=?', (sid, message_id)).rowcount:
                raise HTTPException(404, '消息不存在')
            conn.execute('UPDATE creation_sessions SET version=version+1,updated_ms=?,last_error=NULL WHERE id=?', (now, sid))
        elif action == 'delete':
            conn.execute('DELETE FROM creation_sessions WHERE id=?', (sid,))
            return {'success': True}
        return detail(conn, sid)


@router.get('/sessions')
async def sessions(q: str = Query('', max_length=200), page: int = Query(1, ge=1), limit: int = Query(30, ge=1, le=100)):
    return await asyncio.to_thread(listing, DB_PATH, q.strip(), page, limit)


@router.get('/sessions/{sid}')
async def get_session(sid: str):
    return await asyncio.to_thread(operate, DB_PATH, sid)


@router.patch('/sessions/{sid}')
async def settings(sid: str, body: Settings):
    return await asyncio.to_thread(operate, DB_PATH, sid, 'settings', body.version, body.model_dump())


@router.delete('/sessions/{sid}')
async def delete_session(sid: str, version: int = Query(..., ge=0)):
    return await asyncio.to_thread(operate, DB_PATH, sid, 'delete', version)


@router.delete('/sessions/{sid}/messages/{message_id}')
async def delete_message(sid: str, message_id: str, version: int = Query(..., ge=0)):
    return await asyncio.to_thread(operate, DB_PATH, sid, 'message', version, None, message_id)
