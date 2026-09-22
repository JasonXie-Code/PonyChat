"""Read-only, owner-scoped projection of committed normal-chat continuation plans."""
import json
from pathlib import Path
import time

import aiosqlite

from .db import get_database
from .proactive_send_guard import proactive_reply_limit_reached


async def read_conversation_activity(username, character_id, mode, conversation_id, *, now_ms=None):
    now = int(time.time() * 1000) if now_ms is None else now_ms
    result = {'state': 'none', 'server_now_ms': now}
    if mode != 'normal':
        return {**result, 'state': 'unsupported'}
    if not conversation_id:
        return {**result, 'state': 'no_conversation'}
    uri = Path(get_database().db_path).resolve().as_uri() + '?mode=ro'
    async with aiosqlite.connect(uri, uri=True, timeout=1) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute('BEGIN')
        # Never infer ownership from a supplied conversation ID or character alone.
        row = await (await conn.execute('''SELECT u.id, s.settings FROM conversations c
            JOIN users u ON u.id=c.user_id LEFT JOIN user_settings s ON s.user_id=u.id
            WHERE c.id=? AND c.character_id=? AND u.username=? AND COALESCE(c.is_hidden,0)=0''',
            (conversation_id, character_id, username))).fetchone()
        if row is None:
            return {**result, 'state': 'no_conversation'}
        settings = json.loads(row['settings'] or '{}')
        memory_enabled = settings.get('memory_enabled') is not False
        enabled = memory_enabled and settings.get('proactive_messages_enabled') is not False
        limit = await proactive_reply_limit_reached(conn, conversation_id)
        result.update(proactive_enabled=enabled, memory_enabled=memory_enabled,
                      consecutive_count=limit['count'], consecutive_limit=limit['limit'])
        task = await (await conn.execute('''SELECT status, due_at_ms, expires_at_ms, source_message_id,
            cancel_if_user_replies, updated_at_ms FROM scheduled_followups
            WHERE username=? AND character_id=? AND conversation_id=?
            ORDER BY CASE WHEN status IN ('pending','processing') THEN 0 ELSE 1 END,
                updated_at_ms DESC, created_at_ms DESC LIMIT 1''',
            (username, character_id, conversation_id))).fetchone()
        if not enabled:
            return {**result, 'state': 'disabled'}
        if limit['reached']:
            return {**result, 'state': 'limit_reached'}
        if task is None:
            return result
        state = task['status']
        if state in ('pending', 'processing') and 0 < task['expires_at_ms'] <= now:
            state = 'expired'
        if state in ('pending', 'processing') and task['cancel_if_user_replies']:
            from .scheduled_followup import _source_has_user_reply_after_message
            if await _source_has_user_reply_after_message(conn, conversation_id, task['source_message_id']):
                state = 'cancelled'
        if state not in ('pending', 'processing', 'sent', 'cancelled', 'expired', 'failed'):
            state = 'unknown'
        result.update(state=state, updated_at_ms=task['updated_at_ms'])
        if state in ('pending', 'processing'):
            result.update(due_at_ms=task['due_at_ms'], expires_at_ms=task['expires_at_ms'],
                          cancel_if_user_replies=bool(task['cancel_if_user_replies']))
        return result
