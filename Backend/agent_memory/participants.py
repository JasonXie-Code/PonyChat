"""Server-authorized, per-message group evidence. Never grant a whole conversation."""
from contextlib import closing

from .schema import connect, state, bump
from .evidence import RAW_SELECT


def grant_turn(path, *, username, main_character_id, speaker_character_id, conversation_id, message_ids):
    """Only call after the chat router has authorized the effective speaker.

    Grant only visible messages actually supplied to that participant. Future
    messages, other accounts, hidden conversations and a reset epoch stay private.
    """
    if main_character_id == speaker_character_id:
        return
    with closing(connect(path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        epoch = state(conn, username, speaker_character_id)['epoch']
        for mid in dict.fromkeys(map(str, message_ids)):
            row = conn.execute(RAW_SELECT + ' AND c.id=? AND c.character_id=? '
                "AND COALESCE(NULLIF(m.message_id,''),m.id)=?",
                (username, main_character_id, conversation_id, main_character_id, mid)).fetchone()
            if row:
                conn.execute('INSERT OR IGNORE INTO agent_memory_participants VALUES(?,?,?,?,?)',
                    (username, speaker_character_id, epoch, conversation_id, mid))
        conn.commit()


def read_sources(path, *, username, character_id, message_ids):
    if not isinstance(message_ids, list) or not 1 <= len(message_ids) <= 40:
        raise ValueError('Read 1..40 original message IDs')
    with closing(connect(path)) as conn:
        refs = list(dict.fromkeys(map(str, message_ids)))
        rows = conn.execute(RAW_SELECT + " AND COALESCE(NULLIF(m.message_id,''),m.id) IN ("
            + ','.join('?' for _ in refs) + ') ORDER BY m.timestamp,m.rowid',
            (username, character_id, *refs)).fetchall()
        return [dict(row) for row in rows]


def share_reply_experience_on_connection(conn, request):
    """Authorize old-style 8-before/2-after group windows with the reply commit."""
    if getattr(request, 'memory_enabled', True) is False:
        return
    pending = set(getattr(request, '_autonomous_pending_reply_message_ids', ()) or ())
    if not pending:
        return
    username, main, conversation = request.username, request.character_id, request.conversation_id
    current_speaker = getattr(request, '_normal_speaker_character_id', None) or main
    if current_speaker != main:
        current_state = state(conn, username, current_speaker)
        if current_state['enabled']:
            for mid in pending:
                conn.execute('''INSERT OR IGNORE INTO agent_memory_group_turns
                    SELECT ?,?,?,?,COALESCE(NULLIF(m.message_id,''),m.id) FROM messages m
                    WHERE m.conversation_id=? AND COALESCE(NULLIF(m.message_id,''),m.id)=?
                    AND m.role='assistant' AND m.speaker_character_id=? AND m.deleted_at IS NULL
                    AND COALESCE(m.is_hidden,0)=0''',
                    (username, current_speaker, current_state['epoch'], conversation, conversation, mid, current_speaker))
    rows = conn.execute('''SELECT COALESCE(NULLIF(m.message_id,''),m.id) AS message_id,
        m.role,m.speaker_character_id FROM messages m JOIN conversations c ON c.id=m.conversation_id
        JOIN users u ON u.id=c.user_id WHERE u.username=? AND c.character_id=? AND c.id=?
        AND COALESCE(c.is_hidden,0)=0 AND COALESCE(m.is_hidden,0)=0 AND m.deleted_at IS NULL
        AND m.role IN ('user','assistant')
        ORDER BY COALESCE(m.timestamp,0) DESC,COALESCE(m.sequence_number,0) DESC,m.rowid DESC LIMIT 240''',
        (username, main, conversation)).fetchall()
    utterances = []
    for row in reversed(rows):
        speaker = (row['speaker_character_id'] or main) if row['role'] == 'assistant' else ''
        if utterances and speaker and utterances[-1]['speaker'] == speaker:
            utterances[-1]['ids'].append(row['message_id'])
        else:
            utterances.append({'speaker': speaker, 'ids': [row['message_id']]})
    changed = set()
    for index, anchor in enumerate(utterances):
        speaker = anchor['speaker']
        if not speaker or speaker == main:
            continue
        owner = state(conn, username, speaker)
        if not owner['enabled']:
            continue
        is_current = speaker == current_speaker and bool(set(anchor['ids']) & pending)
        known_anchor = any(conn.execute('''SELECT 1 FROM agent_memory_group_turns
            WHERE username=? AND character_id=? AND epoch=? AND conversation_id=? AND message_id=?''',
            (username, speaker, owner['epoch'], conversation, mid)).fetchone() for mid in anchor['ids'])
        if not is_current and not known_anchor:
            # Context grants may include an old self-utterance after reset.
            # Only an actual reply receipt in this epoch proves participation.
            continue
        for utterance in utterances[max(0, index - 8):index + 3]:
            for mid in utterance['ids']:
                inserted = conn.execute('INSERT OR IGNORE INTO agent_memory_participants VALUES(?,?,?,?,?)',
                    (username, speaker, owner['epoch'], conversation, mid)).rowcount
                if inserted:
                    changed.add(speaker)
    for speaker in changed:
        # The existing review Agent writes any episode/summary from these real
        # sources. No template text or synthetic first-person memory is added.
        bump(conn, username, speaker, delay=0)


def group_scene_rows(rows, *, main_character_id, max_utterances=8):
    """Bound newly shared scene context; one speaker's adjacent bubbles are one turn."""
    utterances = []
    for row in rows:
        speaker = (row.get('speaker_character_id') or main_character_id) if row.get('role') == 'assistant' else ''
        if utterances and speaker and utterances[-1][0] == speaker:
            utterances[-1][1].append(row)
        else:
            utterances.append((speaker, [row]))
    return [row for _, group in utterances[-max_utterances:] for row in group]


def read_group_experience(path, *, username, character_id, query='', before_message_id=None,
                          before_sequence=None, conversation_id=None, limit=20):
    """Discover only visible original rows granted to this guest, across windows."""
    limit = max(1, min(40, int(limit)))
    with closing(connect(path)) as conn:
        sql = RAW_SELECT.replace('m.speaker_character_id\n',
            'm.speaker_character_id,m.speaker_name,c.character_id AS main_character_id,c.title AS conversation_title\n')
        sql += ' AND c.character_id<>?'
        args = [username, character_id, character_id]
        if conversation_id:
            sql += ' AND c.id=?'
            args.append(conversation_id)
        if before_sequence is not None:
            sql += ' AND m.sequence_number<?'
            args.append(before_sequence)
        if query:
            escaped = str(query).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            sql += " AND m.content LIKE ? ESCAPE '\\'"
            args.append('%' + escaped + '%')
        if before_message_id:
            anchor = conn.execute(sql + " AND COALESCE(NULLIF(m.message_id,''),m.id)=?",
                                  [*args, before_message_id]).fetchone()
            if not anchor:
                return []
            rowid = conn.execute("SELECT rowid FROM messages WHERE conversation_id=? AND "
                "COALESCE(NULLIF(message_id,''),id)=?", (anchor['conversation_id'], before_message_id)).fetchone()[0]
            sql += ' AND (COALESCE(m.timestamp,0),m.rowid)<(?,?)'
            args.extend([anchor['timestamp'] or 0, rowid])
        rows = conn.execute(sql + ' ORDER BY COALESCE(m.timestamp,0) DESC,m.rowid DESC LIMIT ?',
                            [*args, limit]).fetchall()
        return [dict(row) for row in reversed(rows)]
