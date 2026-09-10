"""Durable coalesced jobs and leases; only the review Agent interprets content."""
import asyncio
import json
import time
import uuid
from contextlib import closing
from datetime import datetime

from .schema import connect, ensure, state, bump
from .evidence import LOCAL

_worker_waiters = []


def _wake_workers():
    for loop, event in tuple(_worker_waiters):
        if not loop.is_closed():
            loop.call_soon_threadsafe(event.set)

def initialize(path):
    with closing(connect(path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        ensure(conn)
        columns = {r[1] for r in conn.execute('PRAGMA table_info(agent_memory_state)')}
        for name,definition in [('enabled','INTEGER NOT NULL DEFAULT 1'),('target_period','TEXT')]:
            if name not in columns:
                conn.execute(f'ALTER TABLE agent_memory_state ADD COLUMN {name} {definition}')
        # Visibility/content changes invalidate an in-flight snapshot immediately.
        for suffix,event,record in [('insert','INSERT','NEW'),('update','UPDATE OF content,is_hidden,deleted_at','NEW'),('delete','DELETE','OLD')]:
            changed="WHEN OLD.content IS NOT NEW.content OR OLD.is_hidden IS NOT NEW.is_hidden OR OLD.deleted_at IS NOT NEW.deleted_at" if suffix=='update' else ''
            conn.execute(f'DROP TRIGGER IF EXISTS agent_memory_messages_{suffix}')
            conn.execute(f'''CREATE TRIGGER agent_memory_messages_{suffix} AFTER {event} ON messages {changed} BEGIN
              INSERT INTO agent_memory_state(username,character_id,revision,due_at,activated)
                SELECT u.username,c.character_id,1,unixepoch()+180,1 FROM conversations c JOIN users u ON u.id=c.user_id
                WHERE c.id={record}.conversation_id
              ON CONFLICT(username,character_id) DO UPDATE SET revision=revision+1,activated=1,due_at=unixepoch()+180,attempts=0;
            END''')
        conn.execute('''CREATE TRIGGER IF NOT EXISTS agent_memory_conversation_visibility AFTER UPDATE OF is_hidden ON conversations BEGIN
          UPDATE agent_memory_state SET revision=revision+1,due_at=unixepoch()+180
          WHERE username=(SELECT username FROM users WHERE id=NEW.user_id) AND character_id=NEW.character_id;
        END''')
        # Older histories are opened lazily when the character is used again.
        conn.execute('''INSERT OR IGNORE INTO agent_memory_state(username,character_id,revision,due_at)
          SELECT u.username,c.character_id,0,0 FROM conversations c JOIN users u ON u.id=c.user_id
          WHERE COALESCE(c.is_hidden,0)=0 AND EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=c.id
            AND m.deleted_at IS NULL AND COALESCE(m.is_hidden,0)=0) GROUP BY u.username,c.character_id''')
        conn.execute("UPDATE agent_memory_state SET last_review_day=date('now','+8 hours') WHERE last_review_day IS NULL")
        migration='lazy-initial-history-v1'
        if not conn.execute('SELECT 1 FROM agent_memory_migrations WHERE name=?',(migration,)).fetchone():
            conn.execute('UPDATE agent_memory_state SET activated=1 WHERE revision>1 OR reviewed_revision>0')
            # Early rollout queued all old pairs at revision 1. Retire only untouched
            # bootstrap jobs; any new message/edit/request has already advanced them.
            conn.execute('''UPDATE agent_memory_state SET reviewed_revision=revision,lease=NULL,lease_until=0,
              last_error=NULL,attempts=0 WHERE revision=1 AND reviewed_revision=0 AND target_period IS NULL''')
            conn.execute("INSERT INTO agent_memory_migrations VALUES(?,datetime('now'))",(migration,))
        conn.commit()

def configure(path,username,character_id,enabled):
    with closing(connect(path)) as conn:
        state(conn,username,character_id)
        conn.execute('UPDATE agent_memory_state SET enabled=? WHERE username=? AND character_id=?', (int(enabled),username,character_id))
        conn.commit()

def enqueue(path,username,character_id,*,immediate=False,target_period=None):
    with closing(connect(path)) as conn:
        bump(conn,username,character_id,delay=0 if immediate else 180)
        if target_period:
            conn.execute('UPDATE agent_memory_state SET target_period=? WHERE username=? AND character_id=?',
                         (json.dumps(target_period),username,character_id))
        conn.commit()

def status(path,username,character_id):
    with closing(connect(path)) as conn:
        row = conn.execute('SELECT * FROM agent_memory_state WHERE username=? AND character_id=?',(username,character_id)).fetchone()
        if not row:
            return {'pending':False,'running':False}
        return {'pending':row['revision']>row['reviewed_revision'],'running':bool(row['lease'] and row['lease_until']>time.time()),
                'revision':row['revision'],'reviewed_revision':row['reviewed_revision'],'last_error':row['last_error'],
                'attempts':row['attempts'],'enabled':bool(row['enabled']),'epoch':row['epoch'],
                'relationship_requested':bool(row['relationship_requested'])}

def request_relationship(path,username,character_id,*,retry=False):
    """Coalesce page requests: polling must never invalidate an in-flight review."""
    from .evidence import RAW_SELECT
    with closing(connect(path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=state(conn,username,character_id)
        if not conn.execute(RAW_SELECT+" AND m.role='user' LIMIT 1",(username,character_id)).fetchone():
            conn.commit(); return 'no_history'
        if not row['enabled']:
            conn.commit(); return 'disabled'
        if not row['relationship_requested']:
            # A display request is not a source edit. Preserve a running review's
            # revision so merely opening the page cannot invalidate its commit.
            if row['revision'] <= row['reviewed_revision']:
                bump(conn,username,character_id,delay=0)
            conn.execute('UPDATE agent_memory_state SET relationship_requested=1,last_error=NULL,due_at=unixepoch() WHERE username=? AND character_id=?',
                         (username,character_id))
        elif retry and row['last_error'] and row['lease_until']<=time.time():
            conn.execute('UPDATE agent_memory_state SET last_error=NULL,attempts=0,due_at=unixepoch() WHERE username=? AND character_id=?',
                         (username,character_id))
        conn.commit()
        _wake_workers()
        return 'queued'

def claim(path, *, username=None,character_id=None,relationship_only=None):
    today = datetime.now(LOCAL).date().isoformat()
    with closing(connect(path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('''UPDATE agent_memory_state SET revision=revision+1,due_at=unixepoch(),last_review_day=?
          WHERE enabled=1 AND activated=1 AND (last_review_day IS NULL OR last_review_day<>?)''',(today,today))
        sql = 'SELECT * FROM agent_memory_state WHERE enabled=1 AND revision>reviewed_revision AND due_at<=? AND lease_until<=?'
        args = [time.time(),time.time()]
        if relationship_only is not None:
            sql += ' AND relationship_requested=?'; args.append(int(relationship_only))
        if username:
            sql += ' AND username=? AND character_id=?'; args.extend([username,character_id])
        row = conn.execute(sql+' ORDER BY relationship_requested DESC,(target_period IS NOT NULL) DESC,due_at LIMIT 1',args).fetchone()
        if not row:
            conn.commit(); return None
        lease = uuid.uuid4().hex
        conn.execute('UPDATE agent_memory_state SET lease=?,lease_until=?,last_error=NULL WHERE username=? AND character_id=?',
                     (lease,time.time()+240,row['username'],row['character_id']))
        conn.commit()
        return dict(row)|{'lease':lease}

def finish(path,job,*,saved_count=0,needs_more=False,error=None,relationship_saved=False):
    with closing(connect(path)) as conn:
        row = conn.execute('SELECT * FROM agent_memory_state WHERE username=? AND character_id=?', (job['username'],job['character_id'])).fetchone()
        if not row or row['lease']!=job['lease']:
            return
        expected = job['revision'] + bool(saved_count)
        if error and row['relationship_requested'] and row['revision'] != expected and row['epoch'] == job['epoch']:
            # New chat evidence superseded this snapshot: regenerate promptly,
            # rather than treating ordinary contention as a two-minute failure.
            conn.execute('UPDATE agent_memory_state SET lease=NULL,lease_until=0,last_error=NULL,due_at=unixepoch() WHERE username=? AND character_id=?',
                         (job['username'],job['character_id']))
            conn.commit()
            _wake_workers()
            return
        completed = not error and not needs_more and row['revision']==expected and row['epoch']==job['epoch']
        if relationship_saved and not error and row['revision']==expected and row['epoch']==job['epoch']:
            conn.execute('UPDATE agent_memory_state SET relationship_requested=0 WHERE username=? AND character_id=?',
                         (job['username'],job['character_id']))
        conn.execute('''UPDATE agent_memory_state SET lease=NULL,lease_until=0,reviewed_revision=?,
          attempts=?,last_error=?,due_at=?,target_period=CASE WHEN ? THEN NULL ELSE target_period END
          WHERE username=? AND character_id=? AND lease=?''',
          (row['revision'] if completed else row['reviewed_revision'],row['attempts']+bool(error),
           str(error)[:300] if error else None,time.time()+(min(21600,120*2**min(row['attempts'],7)) if error else 120),
           completed,job['username'],job['character_id'],job['lease']))
        conn.commit()

def _record_completed_review(path, job, result):
    with closing(connect(path)) as conn:
        conn.execute('INSERT INTO agent_memory_reviews VALUES(?,?,?,?,?,?,?,?,?,?)',
          (job['lease'],job['username'],job['character_id'],job['epoch'],job['revision'],
           datetime.now(LOCAL).isoformat(),len(result['saved']),int(result['needs_more']),
           result['llm_api_calls'],json.dumps(result['tools'])))
        conn.commit()
    finish(path,job,saved_count=len(result['saved']),needs_more=result['needs_more'],
           relationship_saved=any(d['category']=='relationship_page' for d in result['saved']))


async def run_one(path,model_config,profile_loader,*,username=None,character_id=None,harness_runner=None,relationship_only=None):
    job = await asyncio.to_thread(claim,path,username=username,character_id=character_id,relationship_only=relationship_only)
    if not job:
        return None
    try:
        from .review import review
        profile = await profile_loader(job['username'],job['character_id'])
        result = await review(path,job,model_config,profile,harness_runner=harness_runner)
        await asyncio.to_thread(_record_completed_review, path, job, result)
        return result
    except asyncio.CancelledError:
        await asyncio.to_thread(finish,path,job,error='cancelled; safe to retry'); raise
    except Exception as exc:
        await asyncio.to_thread(finish,path,job,error=type(exc).__name__+': '+str(exc)[:200])
        raise

async def worker_loop():
    from .. import config
    from ..shutdown_state import is_shutdown_requested
    async def profile(username,character_id):
        from ..chat_modules.character import build_character_profile_prompt_block
        from ..chat_modules.character import load_character_from_db
        return build_character_profile_prompt_block(load_character_from_db(username,character_id) or {})
    async def lane(relationship_only):
        event = asyncio.Event()
        waiter = (asyncio.get_running_loop(), event)
        _worker_waiters.append(waiter)
        try:
            while not is_shutdown_requested():
                event.clear()
                try:
                    cfg = config.model_manager.get_model_for_task('normal')
                    if cfg and await run_one(config.DB_PATH,cfg,profile,relationship_only=relationship_only) is not None:
                        continue
                except Exception as exc:
                    config.logger.warning('[AgentMemoryReview] %s',type(exc).__name__)
                try:
                    await asyncio.wait_for(event.wait(), timeout=15)
                except asyncio.TimeoutError:
                    pass
        finally:
            _worker_waiters.remove(waiter)
    # Visible page requests need not wait behind another pair's archive review.
    async with asyncio.TaskGroup() as group:
        group.create_task(lane(True))
        group.create_task(lane(False))
