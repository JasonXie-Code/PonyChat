"""One delivery owner per normal turn, shared by any guest generators.

Pending IDs affect UI reads only, never Agent/DAO history. This process-local
gate matches the single-worker server and disappears on restart so committed
history remains recoverable. Multiple workers require a shared gate instead.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)
DISPLAY_TYPES = frozenset({'assistant_paragraph', 'assistant_asset', 'assistant_message'})
_sessions: set['NormalDeliverySession'] = set()


def normal_text_bubble_delay_seconds(content: str) -> float:
    """Shared typing interval for normal replies and opening greetings."""
    return max(0.3, min(len(str(content or "")) / 10.0, 8.0)) + random.uniform(1.0, 3.0)


class DeliveryCancelled(RuntimeError):
    pass


@dataclass
class PendingMessage:
    request: object
    conversation_id: str
    db_path: str


def pending_message_ids(username: str, character_id: str, conversation_id: str | None = None) -> set[str]:
    return {mid for session in tuple(_sessions) for mid, item in tuple(session.pending.items())
            if (item.request.username, item.request.character_id) == (username, character_id)
            and (conversation_id is None or item.conversation_id == conversation_id)}


class NormalDeliverySession:
    def __init__(self):
        self.pending: dict[str, PendingMessage] = {}
        self.sources: dict[str, object] = {}
        self.last_sent: float | None = None
        self.cancelled = False
        self.background_task = None
        _sessions.add(self)

    def register(self, request, ids, db_path: str) -> None:
        for mid in ids:
            self.pending[mid] = PendingMessage(request, request.conversation_id, str(db_path))
            self.sources[mid] = request

    @staticmethod
    def message_id(event) -> str:
        return str(event.get('message_id') or event.get('id') or '')

    def check_current(self, request) -> None:
        batch = getattr(request, '_normal_reply_batch', None)
        if batch is not None and not batch.current(request._normal_reply_revision):
            self.cancelled = True
            raise DeliveryCancelled('superseded_by_new_user_message')
        guard = getattr(request, '_autonomous_generation_is_current', lambda: True)
        if not guard():
            self.cancelled = True
            raise DeliveryCancelled('superseded_by_new_user_message')

    async def check_persisted(self, mid: str, *, release: bool = False) -> None:
        item = self.pending.get(mid)
        if item is None:
            return
        import aiosqlite
        from .normal_speaker import effective_speaker_character_id, explicit_user_at_reply_requested
        request = item.request
        speaker = effective_speaker_character_id(request) or request.character_id
        async with aiosqlite.connect(item.db_path) as conn:
            await conn.execute('BEGIN IMMEDIATE')
            row = await (await conn.execute(
                'SELECT state,death_message_id FROM normal_character_lifecycle '
                'WHERE username=? AND character_id=? AND conversation_id=?',
                (request.username, speaker, item.conversation_id))).fetchone()
            own_death = str(getattr(request, '_normal_committed_death_message_id', '') or '')
            if row and row[0] == 'dead' and not (explicit_user_at_reply_requested(request, speaker)
                                               or own_death and own_death == row[1]):
                self.cancelled = True
                raise DeliveryCancelled('character_is_dead')
            row = await (await conn.execute(
                'SELECT m.is_hidden,m.deleted_at,c.is_hidden FROM messages m '
                'JOIN conversations c ON c.id=m.conversation_id '
                'WHERE m.conversation_id=? AND m.message_id=?', (item.conversation_id, mid))).fetchone()
            if not row or row[0] or row[1] is not None or row[2]:
                self.cancelled = True
                raise DeliveryCancelled('message_or_conversation_was_removed')
            self.check_current(request)
            if release:
                self.pending.pop(mid, None)
            await conn.commit()

    async def release(self, event: dict, request, *, delay_seconds: float) -> None:
        source = self.sources.get(self.message_id(event), request)
        batch = getattr(source, '_normal_reply_batch', None)
        if batch is not None and not batch.delivered:
            # Serialize the first visibility change with durable input admission.
            async with batch.delivery_gate:
                await self._release(event, request, delay_seconds=delay_seconds)
                batch.delivered = True
            return
        await self._release(event, request, delay_seconds=delay_seconds)

    async def _release(self, event: dict, request, *, delay_seconds: float) -> None:
        """Wait from the last actual send; preparation time counts toward delay."""
        mid = self.message_id(event)
        source = self.sources.get(mid, request)
        self.check_current(source)
        deadline = (self.last_sent + max(0.0, delay_seconds)) if self.last_sent is not None else time.monotonic()
        while (remaining := deadline - time.monotonic()) > 0:
            await asyncio.sleep(min(remaining, 0.1))
            self.check_current(source)
        await self.check_persisted(mid, release=True)
        self.check_current(source)
        self.pending.pop(mid, None)
        await self.notify(event, source)
        now_ms = int(time.time() * 1000)
        event.update(delivery_paced=True, display_at_server_ms=now_ms, server_now_ms=now_ms)
        self.last_sent = time.monotonic()

    async def notify(self, event: dict, request) -> None:
        from ..delivery_outbox import enqueue_chat_complete
        mid = self.message_id(event)
        if not mid:
            return
        payloads = list(getattr(request, '_deferred_chat_complete_payloads', None) or [])
        item = next((p for p in payloads if str(p.get('message_id') or '') == mid), None)
        if item is None and mid not in self.sources:
            return
        item = dict(item) if item else {
            'username': request.username, 'character_id': request.character_id,
            'conversation_id': request.conversation_id, 'message_id': mid,
            'preview': str(event.get('content') or '')[:500], 'mode': 'normal',
            'completed_at_ms': int(time.time() * 1000),
        }
        for key in ('voice_state', 'audio_transfer'):
            if isinstance(event.get(key), dict):
                item[key] = event[key]
        try:
            await enqueue_chat_complete(**item)
            request._deferred_chat_complete_payloads = [p for p in payloads if p.get('message_id') != mid]
        except Exception:
            # The row is already visible and reconnect/history can recover it.
            logger.exception('Normal delivery notification failed mid=%s', mid)

    async def finish(self) -> None:
        for mid, item in tuple(self.pending.items()):
            try:
                self.check_current(item.request)
                await self.check_persisted(mid)
            except DeliveryCancelled:
                break
            except Exception:
                # A transient infrastructure error is not a semantic reason to
                # delete a committed reply. Release its recoverable history.
                logger.exception('Normal pending delivery check unavailable')
        if self.cancelled and self.pending:
            try:
                await self.hide_cancelled_pending()
            except Exception:
                # Keep a confirmed forbidden tail gated until SQLite recovers;
                # retry autonomously so it cannot become a permanent UI gate.
                logger.exception('Retrying cancelled normal delivery cleanup')
                from ..background_jobs import create_tracked_task
                self.background_task = create_tracked_task(self.retry_cancelled_cleanup(),
                    job_id=f'normal_delivery_cleanup:{id(self)}', kind='normal_delivery_cleanup')
                return
        self.clear()

    def clear(self) -> None:
        self.pending.clear()
        self.sources.clear()
        _sessions.discard(self)

    async def hide_cancelled_pending(self) -> None:
        import aiosqlite
        for mid, item in tuple(self.pending.items()):
            async with aiosqlite.connect(item.db_path) as conn:
                await conn.execute(
                    "UPDATE messages SET is_hidden=1,hidden_reason='cancelled_before_delivery' "
                    'WHERE conversation_id=? AND message_id=?', (item.conversation_id, mid))
                await conn.commit()
            self.pending.pop(mid, None)

    async def retry_cancelled_cleanup(self) -> None:
        delay = 0.1
        while self.pending:
            await asyncio.sleep(delay)
            try:
                await self.hide_cancelled_pending()
            except Exception:
                delay = min(5.0, delay * 2)
                continue
        self.clear()

    def dispatch_json(self, events: list[dict], request) -> None:
        """Return a fresh client schedule; publish the same plan asynchronously."""
        planned = []
        now_ms = int(time.time() * 1000)
        scheduled_ms = now_ms
        for event in events:
            if event.get('type') not in DISPLAY_TYPES:
                continue
            delay = max(0.0, float(event.get('display_delay_seconds') or 0))
            if not planned:
                delay = 0.0
            scheduled_ms += int(delay * 1000)
            event.update(display_at_server_ms=scheduled_ms, server_now_ms=now_ms,
                         display_delay_seconds=delay, display_delay_ms=int(delay * 1000))
            event.pop('delivery_paced', None)
            planned.append((dict(event), delay))

        async def dispatch():
            try:
                for event, delay in planned:
                    await self.release(event, request, delay_seconds=delay)
            except DeliveryCancelled:
                pass
            except Exception:
                logger.exception('Normal JSON delivery failed')
            finally:
                await self.finish()

        from ..background_jobs import create_tracked_task
        self.background_task = create_tracked_task(dispatch(), job_id=f'normal_delivery:{id(self)}', kind='normal_delivery')
