"""Owned, durable creative sessions kept separate from chat and game history."""
from contextlib import contextmanager
import json
import sqlite3
import time
import uuid
from fastapi import HTTPException
from .context import validate_layout

SCHEMA = '''
CREATE TABLE IF NOT EXISTS creation_sessions (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
 title TEXT NOT NULL, instructions TEXT NOT NULL DEFAULT '', character_setting TEXT,
 version INTEGER NOT NULL DEFAULT 0, updated_ms INTEGER NOT NULL,
 active_request TEXT, busy_until REAL NOT NULL DEFAULT 0, last_error TEXT
);
CREATE INDEX IF NOT EXISTS creation_session_owner ON creation_sessions(user_id,character_id,updated_ms);
CREATE TABLE IF NOT EXISTS creation_messages (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES creation_sessions(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
 sequence INTEGER NOT NULL, timestamp INTEGER NOT NULL, request_id TEXT NOT NULL,
 incomplete INTEGER NOT NULL DEFAULT 0,
 UNIQUE(session_id,sequence), UNIQUE(session_id,request_id,role)
);
CREATE TABLE IF NOT EXISTS creation_reply_versions (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES creation_sessions(id) ON DELETE CASCADE,
 user_message_id TEXT NOT NULL REFERENCES creation_messages(id) ON DELETE CASCADE,
 content TEXT NOT NULL, timestamp INTEGER NOT NULL, request_id TEXT NOT NULL,
 incomplete INTEGER NOT NULL DEFAULT 0, ordinal INTEGER NOT NULL,
 UNIQUE(session_id,ordinal)
);
CREATE TABLE IF NOT EXISTS creation_context_usage (
 session_id TEXT PRIMARY KEY REFERENCES creation_sessions(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, used_tokens INTEGER, prompt_tokens INTEGER,
 completion_tokens INTEGER, recorded_ms INTEGER NOT NULL
);
'''


@contextmanager
def connect(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    connection.executescript(SCHEMA)
    columns = {row[1] for row in connection.execute('PRAGMA table_info(creation_messages)')}
    if 'incomplete' not in columns:
        connection.execute('ALTER TABLE creation_messages ADD COLUMN incomplete INTEGER NOT NULL DEFAULT 0')
    session_columns = {row[1] for row in connection.execute('PRAGMA table_info(creation_sessions)')}
    if 'context_layout' not in session_columns:
        connection.execute('ALTER TABLE creation_sessions ADD COLUMN context_layout TEXT')
    try:
        yield connection
    finally:
        connection.close()


def owner(conn, username, character_id=None):
    user = conn.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
    if not user:
        raise HTTPException(401, '登录状态已失效')
    if character_id and not conn.execute('SELECT 1 FROM characters WHERE id=? AND user_id=?',
                                         (character_id, user['id'])).fetchone():
        raise HTTPException(404, '角色不存在')
    return user['id']


def session_row(conn, username, session_id):
    row = conn.execute('SELECT * FROM creation_sessions WHERE id=? AND user_id=?',
                       (session_id, owner(conn, username))).fetchone()
    if not row:
        raise HTTPException(404, '创造会话不存在')
    owner(conn, username, row['character_id'])
    result = dict(row)
    result['context_layout'] = validate_layout(json.loads(result['context_layout']) if result.get('context_layout') else None)
    return result


def messages(conn, session_id):
    return [{**dict(row), 'incomplete': bool(row['incomplete'])} for row in conn.execute(
        'SELECT id,role,content,sequence,timestamp,request_id,incomplete FROM creation_messages WHERE session_id=? ORDER BY sequence',
        (session_id,))]


def view(conn, row):
    transcript = messages(conn, row['id'])
    latest = transcript[-1] if transcript and transcript[-1]['role'] == 'assistant' else None
    versions = []
    if latest:
        versions = [{**dict(item), 'role': 'assistant', 'incomplete': bool(item['incomplete'])} for item in conn.execute(
            'SELECT id,content,timestamp,request_id,incomplete FROM creation_reply_versions WHERE session_id=? ORDER BY ordinal',
            (row['id'],))]
        if not any(item['id'] == latest['id'] for item in versions):
            versions = [latest]
    return {**{k: v for k, v in row.items() if k not in ('user_id', 'active_request', 'busy_until')},
            'busy': row['busy_until'] > time.time(), 'messages': transcript, 'reply_versions': versions,
            'selected_reply_version': next((i for i, item in enumerate(versions) if latest and item['id'] == latest['id']), 0),
            'context_usage': context_usage(conn, row['id'])}


def get(path, username, session_id):
    with connect(path) as conn:
        return view(conn, session_row(conn, username, session_id))


def list_sessions(path, username, character_id):
    with connect(path) as conn:
        uid = owner(conn, username, character_id)
        return [dict(r) for r in conn.execute(
            'SELECT id,title,updated_ms FROM creation_sessions WHERE user_id=? AND character_id=? ORDER BY updated_ms DESC',
            (uid, character_id))]


def create(path, username, character_id):
    with connect(path) as conn, conn:
        uid = owner(conn, username, character_id)
        sid = str(uuid.uuid4())
        conn.execute('INSERT INTO creation_sessions(id,user_id,character_id,title,updated_ms) VALUES(?,?,?,?,?)',
                     (sid, uid, character_id, '新的创作', int(time.time() * 1000)))
        return view(conn, session_row(conn, username, sid))


def configure(path, username, sid, values, expected_version):
    with connect(path) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = session_row(conn, username, sid)
        if row['busy_until'] > time.time():
            raise HTTPException(409, '回复正在生成，请完成后再修改设定')
        if row['version'] != expected_version:
            raise HTTPException(409, '会话已在其他设备更新，请刷新后重试')
        conn.execute('UPDATE creation_sessions SET title=?,instructions=?,character_setting=?,version=version+1 WHERE id=?',
                     (values['title'], values['instructions'], values.get('character_setting'), sid))
        return view(conn, session_row(conn, username, sid))


def configure_context(path, username, sid, layout, expected_version):
    layout = validate_layout(layout)
    with connect(path) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = session_row(conn, username, sid)
        if row['busy_until'] > time.time():
            raise HTTPException(409, '请停止生成或等待完成后修改上下文')
        if row['version'] != expected_version:
            raise HTTPException(409, '会话已更新，请刷新后重试')
        conn.execute('UPDATE creation_sessions SET context_layout=?,version=version+1 WHERE id=?',
                     (json.dumps(layout, ensure_ascii=False), sid))
        return view(conn, session_row(conn, username, sid))


def claim(path, username, sid, request_id, content, regenerate, expected_version, edit_message_id=None, continue_story=False):
    with connect(path) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = session_row(conn, username, sid)
        completed = conn.execute("SELECT 1 FROM creation_messages WHERE session_id=? AND request_id=? AND role='assistant' AND incomplete=0",
                                 (sid, request_id)).fetchone()
        if completed or conn.execute('SELECT 1 FROM creation_reply_versions WHERE session_id=? AND request_id=? AND incomplete=0',
                                     (sid, request_id)).fetchone():
            return row, None
        if row['busy_until'] > time.time():
            raise HTTPException(409, '此会话正在生成回复，请稍后刷新')
        if row['version'] != expected_version:
            raise HTTPException(409, '会话已更新，请刷新后重试')
        history = messages(conn, sid)
        if continue_story and (regenerate or edit_message_id or content.strip()):
            raise HTTPException(400, '续写不能同时发送、编辑或重新生成消息')
        if edit_message_id:
            target = next((m for m in history if m['id'] == edit_message_id), None)
            if not target:
                raise HTTPException(404, '消息不存在')
            if target['role'] != 'user' or not content.strip() or regenerate:
                raise HTTPException(400, '只能编辑用户文字消息，且内容不能为空')
            conn.execute('DELETE FROM creation_reply_versions WHERE session_id=?', (sid,))
            conn.execute('UPDATE creation_messages SET content=?,request_id=? WHERE id=? AND session_id=?',
                         (content, request_id, edit_message_id, sid))
            conn.execute('DELETE FROM creation_messages WHERE session_id=? AND sequence>?', (sid, target['sequence']))
            conn.execute('UPDATE creation_sessions SET version=version+1,updated_ms=? WHERE id=?', (int(time.time()*1000), sid))
            history = messages(conn, sid)
        elif regenerate:
            if not history or not any(m['role'] == 'user' for m in history):
                raise HTTPException(400, '还没有可以重新生成的消息')
            # A continued story contains consecutive assistant replies. Replace only
            # the final step, preserving its preceding story and selected versions.
            history = history[:-1] if history[-1]['role'] == 'assistant' else history
        elif continue_story:
            partial = next((i for i, m in enumerate(history)
                            if m['request_id'] == request_id and m['role'] == 'assistant'), None)
            if partial is not None:
                history = history[:partial]
            if not history or history[-1]['role'] != 'assistant':
                raise HTTPException(400, '请先等待角色回复后再续写')
            conn.execute('DELETE FROM creation_reply_versions WHERE session_id=?', (sid,))
        else:
            existing = next((m for m in history if m['request_id'] == request_id and m['role'] == 'user'), None)
            if existing:
                if existing['content'] != content:
                    raise HTTPException(409, '同一次发送不能修改内容')
                history = [m for m in history if m['sequence'] <= existing['sequence']]
            else:
                if not content.strip():
                    raise HTTPException(400, '消息不能为空')
                conn.execute('DELETE FROM creation_reply_versions WHERE session_id=?', (sid,))
                seq = history[-1]['sequence'] + 1 if history else 0
                conn.execute('INSERT INTO creation_messages(id,session_id,role,content,sequence,timestamp,request_id) VALUES(?,?,?,?,?,?,?)',
                             (str(uuid.uuid4()), sid, 'user', content, seq, int(time.time()*1000), request_id))
                history = messages(conn, sid)
                if row['title'] == '新的创作':
                    conn.execute('UPDATE creation_sessions SET title=? WHERE id=?', (content[:24], sid))
        conn.execute('UPDATE creation_sessions SET active_request=?,busy_until=?,last_error=NULL WHERE id=?',
                     (request_id, time.time()+240, sid))
        return row, history


def finish(path, username, sid, request_id, history, text, incomplete=False, usage=None):
    with connect(path) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = session_row(conn, username, sid)
        if row['active_request'] != request_id:
            raise HTTPException(409, '本次生成已被更新的请求替代')
        last = history[-1]['sequence']
        # Legacy sessions acquire their first version without rewriting older turns.
        prior = conn.execute("SELECT * FROM creation_messages WHERE session_id=? AND sequence=? AND role='assistant'",
                             (sid, last+1)).fetchone()
        if prior and not prior['incomplete'] and not conn.execute('SELECT 1 FROM creation_reply_versions WHERE session_id=?', (sid,)).fetchone():
            conn.execute('INSERT INTO creation_reply_versions VALUES(?,?,?,?,?,?,?,?)',
                         (prior['id'], sid, history[-1]['id'], prior['content'], prior['timestamp'], prior['request_id'], prior['incomplete'], 0))
        conn.execute('DELETE FROM creation_messages WHERE session_id=? AND sequence>?', (sid, last))
        now = int(time.time()*1000)
        reply_id = str(uuid.uuid4())
        conn.execute('INSERT INTO creation_messages VALUES(?,?,?,?,?,?,?,?)',
                     (reply_id, sid, 'assistant', text, last+1, now, request_id, int(incomplete)))
        ordinal = conn.execute('SELECT COALESCE(MAX(ordinal),-1)+1 FROM creation_reply_versions WHERE session_id=?', (sid,)).fetchone()[0]
        if not incomplete:
            conn.execute('INSERT INTO creation_reply_versions VALUES(?,?,?,?,?,?,?,?)',
                         (reply_id, sid, history[-1]['id'], text, now, request_id, 0, ordinal))
        conn.execute('UPDATE creation_sessions SET active_request=NULL,busy_until=0,last_error=?,version=version+1,updated_ms=? WHERE id=?',
                     ('回复已中断，已保留生成内容' if incomplete else None, now, sid))
        from .usage import record_usage
        record_usage(conn, sid, request_id, usage, now)
        return view(conn, session_row(conn, username, sid))


def fail(path, sid, request_id, message):
    with connect(path) as conn, conn:
        conn.execute('UPDATE creation_sessions SET active_request=NULL,busy_until=0,last_error=? WHERE id=? AND active_request=?',
                     (message, sid, request_id))


def delete_message(path, username, sid, message_id, expected_version):
    with connect(path) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = session_row(conn, username, sid)
        if row['busy_until'] > time.time():
            raise HTTPException(409, '请停止生成或等待完成后删除消息')
        if row['version'] != expected_version:
            raise HTTPException(409, '会话已更新，请刷新后重试')
        latest = conn.execute('SELECT id FROM creation_messages WHERE session_id=? ORDER BY sequence DESC LIMIT 1', (sid,)).fetchone()
        if latest and latest['id'] == message_id:
            conn.execute('DELETE FROM creation_reply_versions WHERE session_id=?', (sid,))
        deleted = conn.execute('DELETE FROM creation_messages WHERE session_id=? AND id=?', (sid, message_id))
        if not deleted.rowcount:
            raise HTTPException(404, '消息不存在')
        conn.execute('UPDATE creation_sessions SET version=version+1,updated_ms=?,last_error=NULL WHERE id=?',
                     (int(time.time()*1000), sid))
        return view(conn, session_row(conn, username, sid))


def delete_session(path, username, sid, expected_version):
    with connect(path) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = session_row(conn, username, sid)
        if row['busy_until'] > time.time():
            raise HTTPException(409, '回复正在生成，请完成后再删除会话')
        if row['version'] != expected_version:
            raise HTTPException(409, '会话已在其他设备更新，请刷新后重试')
        conn.execute('DELETE FROM creation_sessions WHERE id=?', (sid,))
        return {'deleted': sid}


def select_reply_version(path, username, sid, reply_id, expected_version):
    with connect(path) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = session_row(conn, username, sid)
        if row['busy_until'] > time.time():
            raise HTTPException(409, '回复正在生成，请完成后再切换版本')
        if row['version'] != expected_version:
            raise HTTPException(409, '会话已更新，请刷新后重试')
        latest = conn.execute('SELECT * FROM creation_messages WHERE session_id=? ORDER BY sequence DESC LIMIT 1', (sid,)).fetchone()
        chosen = conn.execute('SELECT * FROM creation_reply_versions WHERE session_id=? AND id=?', (sid, reply_id)).fetchone()
        if not latest or latest['role'] != 'assistant' or not chosen or chosen['incomplete']:
            raise HTTPException(404, '回复版本不存在或尚未完成')
        conn.execute('UPDATE creation_messages SET id=?,content=?,timestamp=?,request_id=?,incomplete=0 WHERE id=? AND session_id=?',
                     (chosen['id'], chosen['content'], chosen['timestamp'], chosen['request_id'], latest['id'], sid))
        conn.execute('UPDATE creation_sessions SET version=version+1,updated_ms=?,last_error=NULL WHERE id=?', (int(time.time()*1000), sid))
        return view(conn, session_row(conn, username, sid))


def context_usage(conn, sid):
    row = conn.execute('SELECT request_id,used_tokens,prompt_tokens,completion_tokens,recorded_ms FROM creation_context_usage WHERE session_id=?', (sid,)).fetchone()
    return dict(row) if row else None
