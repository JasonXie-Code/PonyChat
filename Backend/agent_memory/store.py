"""One versioned store for facts, preferences, plans, scenes and derived summaries."""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import evidence
from .prose import clean_memory_prose
from .schema import connect, ensure, state, bump

CATEGORIES = ('fact','preference','episode','activity','commitment','relationship','understanding','current_scene',
              'daily','weekly','monthly','annual','relationship_page','relationship_state')
STATUSES = ('active','planned','completed','cancelled','retracted')
CERTAINTIES = ('explicit','observed','inferred')

class MemoryConflictError(RuntimeError):
    pass

class AgentMemoryStore:
    def __init__(self, db_path, *, username, character_id, conversation_id, allowed_sources=(),
                 strict_relationship_pages=True):
        self.path = Path(db_path).resolve()
        self.username, self.character_id, self.conversation_id = map(str,(username,character_id,conversation_id))
        if not all((self.username,self.character_id,self.conversation_id)):
            raise ValueError('Memory requires server-bound owner, character and conversation')
        self._drafts, self._allowed, self._closed = {}, {}, False
        self._strict_relationship_pages = strict_relationship_pages
        with closing(connect(self.path)) as conn:
            row = conn.execute('SELECT epoch FROM agent_memory_state WHERE username=? AND character_id=?', (self.username,self.character_id)).fetchone()
            self.epoch = int(row[0]) if row else 0
        self.allow_visible_sources(allowed_sources)

    def allow_visible_sources(self, refs):
        with closing(connect(self.path)) as conn:
            for ref in refs:
                ref = str(ref)
                value = evidence.resolve(conn,self.username,self.character_id,ref)
                if value:
                    self._allowed[ref] = value

    def has_allowed_source(self, ref):
        return not self._closed and str(ref) in self._allowed

    def stage(self, *, kind, content, source_message_ids, occurred_at, entry_id=None, expected_version=0,
              category=None, status='active', certainty='explicit', period=None, importance=5):
        if self._closed:
            raise RuntimeError('Memory task already finalized')
        category = category or ('current_scene' if kind=='current_scene' else 'fact')
        if type(importance) is not int or not 1<=importance<=10:
            raise ValueError('importance must be 1..10')
        if kind not in ('fact','current_scene') or category not in CATEGORIES or status not in STATUSES or certainty not in CERTAINTIES:
            raise ValueError('Invalid memory kind/category/status/certainty')
        if (kind=='current_scene') != (category=='current_scene'):
            raise ValueError('current_scene uses conversation scope; other categories use fact scope')
        if category in ('understanding','relationship_page','relationship_state') and certainty!='inferred':
            raise ValueError('Long-term understanding must remain inferred, not explicit user preference')
        if category=='relationship_page':
            from .relationship import validate_page
            content=json.dumps(validate_page(json.loads(content),strict=self._strict_relationship_pages),ensure_ascii=False)
        if category=='relationship_state':
            from .relationship import normalize_decision
            content=json.dumps(normalize_decision(json.loads(content),strict=True),ensure_ascii=False)
        if isinstance(content, str) and category not in ('relationship_page', 'relationship_state'):
            content = clean_memory_prose(content)
        if not isinstance(content,str) or not content.strip() or len(content)>8000:
            raise ValueError('content must contain 1..8000 characters')
        if isinstance(source_message_ids,(str,bytes)):
            raise ValueError('source_message_ids must be an array')
        refs = list(dict.fromkeys(map(str,source_message_ids)))
        if not 1<=len(refs)<=128 or not set(refs)<=self._allowed.keys():
            raise ValueError('Provide 1..128 previously read visible evidence IDs')
        if occurred_at is None:
            normalized_time = ''  # Legacy NOT NULL column; empty means unknown, never now.
        else:
            try:
                parsed = datetime.fromisoformat(occurred_at.replace('Z','+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError()
                normalized_time = parsed.isoformat()
            except (ValueError,AttributeError):
                raise ValueError('occurred_at must be null or ISO 8601 with time and timezone') from None
        if type(expected_version) is not int or expected_version<0 or (expected_version and not entry_id):
            raise ValueError('Updates require an entry_id and expected_version')
        if kind=='current_scene' and entry_id is None:
            staged=next((r for r in self._drafts.values() if r['kind']=='current_scene'),None)
            if staged:
                entry_id,expected_version=staged['entry_id'],staged['expected_version']
            else:
                with closing(connect(self.path)) as conn:
                    previous=conn.execute('''SELECT h.entry_id,h.version FROM agent_memory_heads h
                      JOIN agent_memory_versions v ON v.entry_id=h.entry_id AND v.version=h.version
                      WHERE h.username=? AND h.character_id=? AND h.epoch=? AND v.kind='current_scene'
                      AND v.scope_conversation_id=? ORDER BY h.id DESC LIMIT 1''',
                      (self.username,self.character_id,self.epoch,self.conversation_id)).fetchone()
                    if previous:
                        entry_id,expected_version=previous['entry_id'],previous['version']
        mid = entry_id or uuid.uuid4().hex
        if not isinstance(mid,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',mid):
            raise ValueError('Invalid entry_id')
        if any(ref.startswith('memory:'+mid+':') for ref in refs):
            raise ValueError('A memory cannot use its own earlier version as its sole evidence')
        if len(self._drafts)>=32 and mid not in self._drafts:
            raise ValueError('At most 32 memory drafts per task')
        old = self._drafts.get(mid)
        if old and (old['expected_version']!=expected_version or old['kind']!=kind):
            raise ValueError('A draft must keep its original expected version and scope')
        period_hash = None
        if category in evidence.LAYERS:
            if not period:
                raise ValueError('Summary requires period')
            with closing(connect(self.path)) as conn:
                period_hash = evidence.period_digest(conn,self.username,self.character_id,category,period)
        elif period:
            raise ValueError('Only summaries have a period')
        draft = dict(entry_id=mid,kind=kind,category=category,status=status,certainty=certainty,content=content.strip(),
                     source_message_ids=refs,occurred_at=normalized_time,expected_version=expected_version,
                     period=period,period_hash=period_hash,importance=importance,evidence_json={r:self._allowed[r] for r in refs})
        self._drafts[mid] = draft
        return {k:v for k,v in draft.items() if k not in ('evidence_json','period_hash')} | {'version':expected_version+1,'staged':True}

    def discard(self):
        self._closed = True
        self._drafts.clear()

    async def search(self, query='', *, kind=None, limit=8, category=None, include_stale=False):
        return await asyncio.to_thread(self.list,query=query,kind=kind,category=category,limit=limit,
                                       include_stale=include_stale,rank_by_importance=True)

    def list(self, *, query='', kind=None, category=None, limit=100, include_stale=False, all_scenes=False, periods=None,
             rank_by_importance=False):
        with closing(connect(self.path)) as conn:
            return list_entries(conn,self.username,self.character_id,conversation_id=None if all_scenes else self.conversation_id,
                                query=query,kind=kind,category=category,limit=limit,include_stale=include_stale,
                                periods=periods,rank_by_importance=rank_by_importance)

    def commit_on_connection(self, conn, *, generation_is_current, expected_revision=None, allow_disabled=False):
        """Write inside the caller's reply transaction; caller owns commit/rollback.

        This method must run on the SQLite connection's worker thread. It never
        exposes a remembered promise before both reply and memory are durable.
        """
        if self._closed or not generation_is_current():
            raise MemoryConflictError('Generation is no longer current')
        s = state(conn,self.username,self.character_id)
        if s['epoch']!=self.epoch or (expected_revision is not None and s['revision']!=expected_revision):
            raise MemoryConflictError('Memory scope changed or reset while task was running')
        if not allow_disabled and not s['enabled']:
            raise MemoryConflictError('Memory was disabled while task was running')
        saved = []
        for draft in self._drafts.values():
            for ref, value in draft['evidence_json'].items():
                if not evidence.matches(conn,self.username,self.character_id,ref,value):
                    raise MemoryConflictError('Evidence was edited, hidden or superseded')
            if draft['period_hash'] and evidence.period_digest(conn,self.username,self.character_id,draft['category'],draft['period'])!=draft['period_hash']:
                raise MemoryConflictError('Summary period changed while being read')
            head = conn.execute('SELECT * FROM agent_memory_heads WHERE entry_id=?',(draft['entry_id'],)).fetchone()
            if head and (head['username']!=self.username or head['character_id']!=self.character_id or head['epoch']!=self.epoch):
                raise MemoryConflictError('Memory is outside this owner or reset generation')
            if (head['version'] if head else 0)!=draft['expected_version']:
                raise MemoryConflictError('Memory version changed; retry using current versions')
            if not head and not draft['period']:
                duplicate=conn.execute('''SELECT v.* FROM agent_memory_heads h JOIN agent_memory_versions v
                  ON h.entry_id=v.entry_id AND h.version=v.version WHERE h.username=? AND h.character_id=?
                  AND h.epoch=? AND v.category=? AND v.content=? AND v.status=? AND v.certainty=?
                  AND v.scope_conversation_id=?''',(self.username,self.character_id,self.epoch,draft['category'],
                  draft['content'],draft['status'],draft['certainty'],self.conversation_id if draft['kind']=='current_scene' else '')).fetchall()
                if any(evidence.valid(conn,self.username,self.character_id,r) for r in duplicate):
                    continue
            if head:
                previous = conn.execute('SELECT scope_conversation_id,kind FROM agent_memory_versions WHERE entry_id=? AND version=?',
                                        (draft['entry_id'],head['version'])).fetchone()
                if previous['kind']!=draft['kind'] or (previous['scope_conversation_id'] and previous['scope_conversation_id']!=self.conversation_id):
                    raise MemoryConflictError('Cannot change memory scope')
            # Summaries have one stable identity per period, including stale versions.
            if draft['period']:
                duplicate = conn.execute('''SELECT h.entry_id FROM agent_memory_heads h JOIN agent_memory_versions v
                  ON v.entry_id=h.entry_id AND v.version=h.version WHERE h.username=? AND h.character_id=? AND h.epoch=?
                  AND v.category=? AND v.period=? AND h.entry_id<>? AND v.status<>'retracted' ''',
                  (self.username,self.character_id,self.epoch,draft['category'],draft['period'],draft['entry_id'])).fetchone()
                if duplicate:
                    raise MemoryConflictError('This summary period already exists; update its entry_id/version')
            version = draft['expected_version']+1
            if head:
                conn.execute('UPDATE agent_memory_heads SET version=? WHERE entry_id=?',(version,draft['entry_id']))
            else:
                conn.execute('INSERT INTO agent_memory_heads(entry_id,username,character_id,epoch,version) VALUES(?,?,?,?,?)',
                             (draft['entry_id'],self.username,self.character_id,self.epoch,version))
            conn.execute('INSERT INTO agent_memory_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (draft['entry_id'],version,draft['kind'],draft['category'],draft['status'],draft['certainty'],draft['content'],
                 json.dumps(draft['source_message_ids']),json.dumps(draft['evidence_json']),draft['occurred_at'],
                 datetime.now(timezone.utc).isoformat(),self.conversation_id,
                 self.conversation_id if draft['kind']=='current_scene' else '',draft['period'],draft['period_hash'],draft['importance']))
            saved.append({k:v for k,v in draft.items() if k not in ('evidence_json','period_hash')} | {'version':version,'staged':False})
        if saved:
            bump(conn,self.username,self.character_id)
        if not generation_is_current():
            raise MemoryConflictError('Generation was superseded before commit')
        return saved

    def commit(self, *, reply_succeeded, generation_is_current, expected_revision=None):
        if self._closed:
            return []
        try:
            if not reply_succeeded or _cancelling() or not generation_is_current():
                return []
            with closing(connect(self.path)) as conn:
                conn.execute('BEGIN IMMEDIATE')
                saved = self.commit_on_connection(conn, generation_is_current=generation_is_current,
                                                  expected_revision=expected_revision)
                if _cancelling() or not generation_is_current():
                    conn.rollback()
                    return []
                conn.commit()
                return saved
        finally:
            self.discard()



def _cancelling():
    try:
        task=asyncio.current_task()
        return bool(task and getattr(task, 'cancelling', lambda: task.cancelled() or getattr(task, '_must_cancel', False))())
    except RuntimeError:
        return False

def list_entries(conn, username, character_id, *, conversation_id=None, query='',kind=None,category=None,limit=100,
                 include_stale=False,periods=None,rank_by_importance=False):
    sql = '''SELECT h.id,h.epoch,v.*,COALESCE(ir.importance,v.importance) AS effective_importance
      FROM agent_memory_heads h JOIN agent_memory_versions v
      ON h.entry_id=v.entry_id AND h.version=v.version JOIN agent_memory_state s
      ON s.username=h.username AND s.character_id=h.character_id AND s.epoch=h.epoch
      LEFT JOIN agent_memory_importance_reviews ir ON ir.entry_id=v.entry_id AND ir.version=v.version
      WHERE h.username=? AND h.character_id=?'''
    args = [username,character_id]
    if conversation_id is not None:
        sql += " AND (v.scope_conversation_id='' OR v.scope_conversation_id=?)"; args.append(conversation_id)
    if kind:
        sql += ' AND v.kind=?'; args.append(kind)
    if category:
        sql += ' AND v.category=?'; args.append(category)
    if periods is not None:
        if not periods:return []
        sql += ' AND v.period IN ('+','.join('?' for _ in periods)+')'; args.extend(periods)
    if not include_stale:
        sql += " AND v.status<>'retracted'"
    terms = list(dict.fromkeys(t for segment in re.findall(r'[\u3400-\u9fff]+|[A-Za-z0-9]+',query)
                              for t in ([segment.lower()] if len(segment)<2 or segment.isascii() else [segment[i:i+2] for i in range(len(segment)-1)])))[:64]
    if terms:
        sql += ' AND ('+' OR '.join('instr(lower(v.content),?)>0' for _ in terms)+')'; args.extend(terms)
    order = 'v.created_at DESC,h.id DESC'
    if rank_by_importance:
        order = 'COALESCE(ir.importance,v.importance) DESC,' + order
        if terms:
            order = '(' + '+'.join('(instr(lower(v.content),?)>0)' for _ in terms) + ') DESC,' + order
            args.extend(terms)
    result_limit = max(1,min(500,int(limit)))
    rows = conn.execute(sql+' ORDER BY '+order+' LIMIT 500',args)
    results = []
    for row in rows:
        score = sum(t in row['content'].lower() for t in terms)
        if terms and not score:
            continue
        is_valid = evidence.valid(conn,username,character_id,row)
        if not is_valid and not include_stale:
            continue
        item = dict(row)
        if not item.get('occurred_at'):
            item['occurred_at'] = None
        item['importance'] = item.pop('effective_importance')
        item.pop('evidence_json'); item.pop('period_hash')
        item.update(source_message_ids=json.loads(row['source_message_ids']),staged=False,
                    stale=not is_valid,source_ref=f"memory:{row['entry_id']}:{row['version']}")
        results.append((score,item))
        # With no search terms SQL already has the final stable ordering.
        # Stop only after enough visible/valid rows; stale rows never consume
        # the requested result count. Keyword ranking still considers all 500.
        if not terms and len(results) >= result_limit:
            break
    results.sort(key=lambda r:(r[0],r[1]['importance'] if rank_by_importance else 0),reverse=True)
    return [item for _,item in results[:result_limit]]
