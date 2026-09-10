"""Bind explicit reminders to the user's existing normal-chat container."""
import time


async def resolve_task_conversation(conn, db, username, character_id, requested_id='', *, allow_create=True):
    owner = await (await conn.execute(
        'SELECT u.id,c.name FROM characters c JOIN users u ON u.id=c.user_id WHERE u.username=? AND c.id=?',
        (username, character_id),
    )).fetchone()
    if not owner:
        raise ValueError('character_not_found')
    if requested_id:
        row = await (await conn.execute(
            'SELECT id FROM conversations WHERE id=? AND user_id=? AND character_id=? AND COALESCE(is_hidden,0)=0',
            (requested_id, owner[0], character_id),
        )).fetchone()
        if not row:
            raise ValueError('conversation_not_found')
        return row[0]
    from .db.conversations_dao import ConversationsDAO
    canonical, _ = await ConversationsDAO(db)._pick_single_visible_conversation(conn, owner[0], character_id)
    exists = await (await conn.execute('SELECT id FROM conversations WHERE id=?', (canonical,))).fetchone()
    if not exists:
        if not allow_create:
            raise ValueError('conversation_not_found')
        await conn.execute(
            'INSERT INTO conversations(id,user_id,character_id,title,timestamp) VALUES(?,?,?,?,?)',
            (canonical, owner[0], character_id, owner[1] or '新对话', int(time.time()*1000)),
        )
    return canonical
