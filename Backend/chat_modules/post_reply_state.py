"""Durable state work queued atomically with an immutable delivered reply."""
from __future__ import annotations

import asyncio
from contextlib import closing
import hashlib
import json
import logging
import sqlite3
import time
import weakref

_locks = weakref.WeakKeyDictionary()
_running = weakref.WeakKeyDictionary()
log = logging.getLogger(__name__)


class PendingReplyState(RuntimeError):
    pass


def ensure(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS normal_post_reply_jobs(
        id TEXT PRIMARY KEY, username TEXT NOT NULL, character_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, created_ms INTEGER NOT NULL,
        updated_ms INTEGER NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS normal_post_reply_scope '
                 'ON normal_post_reply_jobs(username,conversation_id,status,created_ms)')


def connect(path):
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    ensure(conn)
    return conn


def enqueue_on_connection(conn, request, store):
    draft = getattr(request, '_post_reply_state_payload', None)
    if not draft or store is None:
        return
    from ..agent_memory.evidence import resolve
    reply_ids = list(getattr(request, '_autonomous_pending_reply_message_ids', ()) or ())
    scope = [request.username, store.character_id, request.conversation_id, store.epoch]
    ids = [m['message_id'] for m in draft['messages'] if m.get('message_id')]
    job_id = hashlib.sha256(json.dumps([scope, ids, reply_ids]).encode()).hexdigest()
    allowed = dict(store._allowed)
    for mid in ids + reply_ids:
        if mid not in allowed:
            ref = resolve(conn, store.username, store.character_id, mid)
            if ref:
                allowed[mid] = ref
    payload = {**draft, 'epoch': store.epoch, 'reply_ids': reply_ids, 'evidence': allowed,
               'main_character_id': request.character_id}
    now = int(time.time()*1000)
    ensure(conn)
    conn.execute('INSERT OR IGNORE INTO normal_post_reply_jobs '
                 '(id,username,character_id,conversation_id,payload,status,created_ms,updated_ms) '
                 "VALUES(?,?,?,?,?,'waiting_delivery',?,?)",
                 (job_id, *scope[:2], request.conversation_id, json.dumps(payload, ensure_ascii=False), now, now))
    request._post_reply_job_id = job_id


def activate(path, job_id):
    with closing(connect(path)) as conn, conn:
        conn.execute("UPDATE normal_post_reply_jobs SET status='pending',updated_ms=? "
                     "WHERE id=? AND status='waiting_delivery'", (int(time.time()*1000), job_id))


def pending(path, username=None, conversation_id=None):
    with closing(connect(path)) as conn:
        sql = "SELECT * FROM normal_post_reply_jobs WHERE status NOT IN ('done','cancelled')"
        args = []
        if username is not None:
            sql += ' AND username=? AND conversation_id=?'
            args = [username, conversation_id]
        return [dict(r) for r in conn.execute(sql + ' ORDER BY created_ms,rowid', args)]


def mark(path, job_id, status, *, error=None, attempt=False):
    with closing(connect(path)) as conn, conn:
        conn.execute('UPDATE normal_post_reply_jobs SET status=?,last_error=?,updated_ms=?, '
                     "attempts=attempts+?,payload=CASE WHEN ? IN ('done','cancelled') THEN '{}' ELSE payload END "
                     "WHERE id=? AND status NOT IN ('done','cancelled')",
                     (status, error, int(time.time()*1000), int(attempt), status, job_id))


def terminal(path, job_id):
    with closing(connect(path)) as conn:
        row = conn.execute('SELECT status FROM normal_post_reply_jobs WHERE id=?', (job_id,)).fetchone()
        return not row or row['status'] in ('done', 'cancelled')


async def drain(path, username, conversation_id, *, processor=None, retry_failed=False):
    """One ordered state writer per conversation; an error never permits a stale next turn."""
    loop = asyncio.get_running_loop()
    key = (str(path), username, conversation_id)
    lock = _locks.setdefault(loop, weakref.WeakValueDictionary()).setdefault(key, asyncio.Lock())
    async with lock:
        jobs = await asyncio.to_thread(pending, path, username, conversation_id)
        for job in jobs:
            if job['status'] == 'waiting_delivery':
                raise PendingReplyState('上一条回复仍在交付，请稍后重试。')
            if job['status'] == 'failed' and not retry_failed:
                raise PendingReplyState('上一条回复的状态更新失败，消息已保留，请重试。')
            if processor is None:
                from .post_reply_state_worker import process
                run = process
            else:
                run = processor
            for attempt in range(3):
                try:
                    from .. import config
                    from .local_model_queue import local_model_slot
                    model = config.model_manager.get_model_for_task('normal')
                    async with local_model_slot(model):
                        await asyncio.to_thread(mark, path, job['id'], 'running', attempt=True)
                        await asyncio.wait_for(run(path, job), 75)
                    break
                except asyncio.CancelledError:
                    await asyncio.shield(asyncio.to_thread(mark, path, job['id'], 'pending'))
                    raise
                except Exception as exc:
                    if await asyncio.to_thread(terminal, path, job['id']):
                        log.warning('State committed; post-commit bookkeeping failed: %s', type(exc).__name__)
                        break
                    message = str(exc)[:700]
                    job['last_error'] = message
                    await asyncio.to_thread(mark, path, job['id'], 'failed', error=message)
                    if attempt == 2:
                        raise PendingReplyState('上一条回复的状态更新失败，消息已保留，请重试。') from exc
                    await asyncio.sleep(.25 * (attempt + 1))


def launch(path, username, conversation_id):
    loop = asyncio.get_running_loop()
    key = (str(path), username, conversation_id)
    running = _running.setdefault(loop, {})
    task = running.get(key)
    if task is None or task.done():
        from ..background_jobs import create_tracked_task
        async def work():
            try:
                await drain(path, username, conversation_id)
            except PendingReplyState as exc:
                log.warning('Post-reply state pending: %s', exc)
        task = create_tracked_task(work(), job_id='post_reply:' + hashlib.sha256(str(key).encode()).hexdigest(),
                                   kind='post_reply_state')
        running[key] = task
        def finished(done):
            if running.get(key) is done:
                running.pop(key, None)
        task.add_done_callback(finished)
    return task


async def finish_delivery(request):
    job_id = getattr(request, '_post_reply_job_id', None)
    if not job_id:
        return
    from .. import config
    await asyncio.to_thread(activate, config.DB_PATH, job_id)
    return launch(config.DB_PATH, request.username, request.conversation_id)


async def wait_for_conversation(path, username, conversation_id, *, retry_failed=False):
    if username and conversation_id:
        await drain(path, username, conversation_id, retry_failed=retry_failed)


async def recovery_loop(path):
    # After process restart, committed replies are visible through history;
    # in-process delivery gates no longer exist. Their durable work can resume.
    with closing(connect(path)) as conn, conn:
        conn.execute("UPDATE normal_post_reply_jobs SET status='pending' "
                     "WHERE status IN ('running','waiting_delivery')")
    while True:
        try:
            jobs = await asyncio.to_thread(pending, path)
            scopes = {(j['username'], j['conversation_id']) for j in jobs if j['status'] == 'pending'}
            for username, conversation_id in scopes:
                launch(path, username, conversation_id)
        except Exception:
            log.exception('Post-reply recovery scan failed')
        await asyncio.sleep(5)
