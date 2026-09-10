"""UI projections and explicit user edits of the same Agent-owned memory store."""
import uuid
from contextlib import closing
from datetime import datetime, timezone

from .schema import connect, state
from .store import AgentMemoryStore, list_entries
from .evidence import LAYERS, resolve


def projection(row):
    category = row['category']
    return dict(row, memory_type=category if category in ('preference','relationship','activity') else 'episode',
                source='agent:'+row['certainty'], importance=row['importance'], is_active=row['status']!='retracted',
                last_recalled_at=None, recall_count=0, layer=LAYERS.get(category,0))


def memories(path,username,character_id,*,memory_type=None,layer=None):
    with closing(connect(path)) as conn:
        rows = [projection(r) for r in list_entries(conn,username,character_id,limit=500)]
    return [r for r in rows if r['category'] not in ('relationship_page','relationship_state') and (not memory_type or r['memory_type']==memory_type)
            and (layer is None or r['layer']==layer)]


def manual(path,username,character_id,*,memory_id=None,content=None,category=None,retract=False,importance=None):
    now=datetime.now(timezone.utc).isoformat()
    with closing(connect(path)) as conn:
        if not conn.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():
            raise LookupError('User not found')
        state(conn,username,character_id)
        row=None
        if memory_id is not None:
            row=next((r for r in list_entries(conn,username,character_id,include_stale=True,limit=500)
                      if r['id']==memory_id),None)
            if not row:
                raise LookupError('Memory not found')
        text=(content if content is not None else row['content'] if row else '').strip()
        if not text:
            raise ValueError('Memory content is empty')
        conn.commit()
    store=AgentMemoryStore(path,username=username,character_id=character_id,
                           conversation_id=(row['scope_conversation_id'] if row else '') or 'manual',
                           # A manual stage change must preserve incomplete/legacy page prose.
                           strict_relationship_pages=False)
    try:
        with closing(connect(path)) as conn:
            conn.execute('BEGIN IMMEDIATE')
            note='note:'+uuid.uuid4().hex
            conn.execute('INSERT INTO agent_memory_notes VALUES(?,?,?,?,?)',(note,username,character_id,text,now))
            store._allowed[note] = resolve(conn,username,character_id,note)
            draft=store.stage(kind=row['kind'] if row else 'fact',content=text,source_message_ids=[note],occurred_at=now,
                category=category or (row['category'] if row else 'episode'),
                status='retracted' if retract else (row['status'] if row else 'active'),
                certainty='inferred' if (category or (row['category'] if row else '')) in ('understanding','relationship_page','relationship_state') else 'explicit',
                importance=importance if importance is not None else row['importance'] if row else 5,
                entry_id=row['entry_id'] if row else None,expected_version=row['version'] if row else 0,
                period=row['period'] if row else None)
            saved=store.commit_on_connection(conn,generation_is_current=lambda:True,allow_disabled=True)
            rows=list_entries(conn,username,character_id,include_stale=True,limit=500)
            if saved:
                result=next(r for r in rows if r['entry_id']==saved[0]['entry_id'])
            else:
                result=next(r for r in rows if not r['stale'] and all(r[k]==draft[k]
                            for k in ('category','content','status','certainty')))
                conn.execute('DELETE FROM agent_memory_notes WHERE id=?',(note,))
            conn.commit()
            return projection(result)
    finally:
        store.discard()



async def reset_on_connection(conn,username,character_id):
    """Part of the existing reset transaction: invalidate all old and running work."""
    await conn.execute('INSERT OR IGNORE INTO agent_memory_state(username,character_id) VALUES(?,?)',(username,character_id))
    await conn.execute('''UPDATE agent_memory_state SET epoch=epoch+1,revision=revision+1,
      reviewed_revision=revision+1,lease=NULL,lease_until=0,target_period=NULL,relationship_requested=0,attempts=0,last_error=NULL,
      last_review_day=date('now','+8 hours') WHERE username=? AND character_id=?''',(username,character_id))
