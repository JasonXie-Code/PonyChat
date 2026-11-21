"""Read-only migration clues. Legacy summaries never grant new evidence IDs."""
from contextlib import closing
from .schema import connect


def read_legacy(path, username, character_id, query='', *, offset=0, limit=30):
    offset, limit = max(0, int(offset)), max(1, min(40, int(limit)))
    terms = str(query or '').strip()[:300]
    with closing(connect(path)) as conn:
        state = conn.execute('SELECT epoch FROM agent_memory_state WHERE username=? AND character_id=?',
                             (username,character_id)).fetchone()
        if state and state['epoch']:
            return {'unverified_legacy_material': [], 'has_more':False, 'usable_as_new_evidence':False}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        selects = []
        if 'character_memories' in tables:
            selects.append(("SELECT m.content FROM character_memories m JOIN users u ON u.id=m.user_id "
                "WHERE u.username=? AND m.character_id=? AND m.is_active=1", 'character_memories'))
        for table, columns in [('normal_chat_memory',['char_memory_json','short_term_memory','long_term_memory']),
                               ('normal_scene_state',['scene_json','scene_card'])]:
            if table in tables:
                for column in columns:
                    selects.append((f'SELECT m.{column} AS content FROM {table} m WHERE m.username=? AND m.character_id=? '
                        'AND EXISTS(SELECT 1 FROM conversations c JOIN users u ON c.user_id=u.id WHERE c.id=m.conversation_id '
                        'AND u.username=m.username AND COALESCE(c.is_hidden,0)=0)', table))
        rows = []
        # Apply the keyword before pagination, including old material far beyond
        # the former newest-30 window. Bound each chunk, with explicit continuation.
        for sql, origin in selects:
            query_sql = 'SELECT content FROM (' + sql + ') WHERE length(content)>0'
            args = [username, character_id]
            if terms:
                query_sql += ' AND instr(content,?)>0'
                args.append(terms)
            for row in conn.execute(query_sql + ' LIMIT ? OFFSET ?', [*args, limit+1, offset]):
                rows.append({'source_table':origin, 'content':row['content'][:12000]})
        return {'unverified_legacy_material':rows, 'has_more':any(
            sum(r['source_table']==origin for r in rows)>limit for _,origin in selects),
            'next_offset':offset+limit, 'usable_as_new_evidence':False}
