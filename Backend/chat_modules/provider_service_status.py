"""Durable, deduplicated service notices for slow DeepSeek model calls."""
import asyncio
from contextlib import closing
import json
import logging
import sqlite3
import time
import uuid
from urllib.parse import urlparse

THRESHOLD_SECONDS = 60.0


def transition(path, unavailable, request_started):
    now = time.time()
    with closing(sqlite3.connect(str(path), timeout=3)) as conn, conn:
        conn.execute('CREATE TABLE IF NOT EXISTS provider_service_state '
                     '(provider TEXT PRIMARY KEY, unavailable INTEGER, incident TEXT, changed REAL, last_failure REAL)')
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT unavailable,incident,changed,last_failure FROM provider_service_state WHERE provider='deepseek'").fetchone()
        if unavailable and row and row[0]:
            conn.execute("UPDATE provider_service_state SET last_failure=? WHERE provider='deepseek'", (now,))
            return []
        if not unavailable and (not row or not row[0] or request_started <= row[3]):
            return []  # An older in-flight success cannot announce recovery.
        incident = uuid.uuid4().hex if unavailable else row[1]
        conn.execute("INSERT OR REPLACE INTO provider_service_state VALUES('deepseek',?,?,?,?)",
                     (int(unavailable), incident, now, now if unavailable else row[3]))
        payload = {'incident_id': incident, 'state': 'unavailable' if unavailable else 'recovered',
            'timestamp': int(now*1000), 'title': 'PonyChat 服务通知',
            'message': ('DeepSeek 单次请求超过 60 秒未返回，服务暂不可用，请等待修复。'
                        if unavailable else 'DeepSeek 已恢复正常响应，可以继续聊天。')}
        # Offline phones receive the current state, never a stale outage after recovery.
        conn.execute("UPDATE message_outbox SET delivered_at=? WHERE msg_type='provider_notice' AND delivered_at IS NULL", (now,))
        pushed = []
        for user_id, username in conn.execute('SELECT id,username FROM users').fetchall():
            oid = str(uuid.uuid4())
            conn.execute('INSERT INTO message_outbox(id,user_id,msg_type,payload_json,created_at,delivered_at,retry_count) '
                "VALUES(?,?,'provider_notice',?,?,NULL,0)", (oid, user_id, json.dumps(payload, ensure_ascii=False), now))
            pushed.append((username, {**payload, 'type': 'provider_notice', 'outbox_id': oid}))
        return pushed


async def publish(unavailable, request_started):
    try:
        from .. import config
        from ..websocket import manager
        notices = await asyncio.to_thread(transition, config.DB_PATH, unavailable, request_started)
        async def send(username, payload):
            try:
                await asyncio.wait_for(manager.broadcast_to_user(username, payload), 3)
            except Exception:
                pass  # Durable outbox will deliver on reconnect.
        await asyncio.gather(*(send(user, payload) for user, payload in notices
                               if manager.get_connection_count(user)))
    except Exception:
        logging.getLogger(__name__).exception('Provider availability notice failed')


class DeepSeekCallMonitor:
    """Observe each SDK model step, not the whole chat/tool/background task."""
    def __init__(self, enabled=True, publisher=publish, threshold=THRESHOLD_SECONDS):
        self.loop = asyncio.get_running_loop()
        self.enabled, self.publisher, self.threshold = enabled, publisher, threshold
        self.calls, self.publications = {}, set()
        self.closed = False

    def observe(self, kind, data):
        if self.enabled and kind in ('step/start', 'step/end', 'assistant/message'):
            self.loop.call_soon_threadsafe(self.event, kind, dict(data))

    def emit(self, unavailable, started):
        task = self.loop.create_task(self.publisher(unavailable, started))
        self.publications.add(task)
        task.add_done_callback(self.publications.discard)

    def event(self, kind, data):
        if not self.enabled or self.closed or data.get('turn') is None or data.get('step') is None:
            return
        key = (str(data['turn']), str(data['step']))
        if kind == 'step/start':
            if key not in self.calls:
                started = time.time()
                handle = self.loop.call_later(self.threshold, self.emit, True, started)
                self.calls[key] = (started, handle)
        else:
            pending = self.calls.pop(key, None)
            if pending:
                pending[1].cancel()
                if kind == 'assistant/message':
                    self.emit(False, pending[0])

    async def close(self):
        self.closed = True
        for _, handle in self.calls.values():
            handle.cancel()
        self.calls.clear()
        if self.publications:
            await asyncio.gather(*self.publications, return_exceptions=True)


def monitor_for_url(url):
    return DeepSeekCallMonitor(enabled=urlparse(url).hostname == 'api.deepseek.com')


async def monitored_post(client, url, **kwargs):
    monitor = monitor_for_url(url)
    marker = {'turn': 1, 'step': 1}
    monitor.event('step/start', marker)
    try:
        from .local_model_queue import local_model_slot
        async with local_model_slot(url):
            response = await client.post(url, **kwargs)
        if response.status_code == 200:
            monitor.event('assistant/message', marker)
        return response
    finally:
        await monitor.close()
