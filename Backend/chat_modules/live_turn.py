"""One normal-chat task with a thread-safe inbox and reconnectable delivery."""
from __future__ import annotations

import asyncio
from collections import deque, OrderedDict
import json
import threading
import time
import uuid
import weakref

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

_turns = weakref.WeakKeyDictionary()
_completed = weakref.WeakKeyDictionary()
_RETRY_INTAKE = object()


def registry():
    return _turns.setdefault(asyncio.get_running_loop(), {})


def active_turn(username, character_id):
    return registry().get((username, character_id))


def completed_turns():
    cache = _completed.setdefault(asyncio.get_running_loop(), OrderedDict())
    now = time.monotonic()
    while cache and (len(cache) > 64 or next(iter(cache.values()))[0] < now - 300):
        cache.popitem(last=False)
    return cache


def has_saved_delivery(response, packets):
    """Only replay a successfully saved result; errors must remain retryable."""
    try:
        if isinstance(response, JSONResponse):
            if response.status_code >= 400:
                return False
            events = json.loads(response.body).get('events', [])
        else:
            events = [json.loads(line[6:]) for packet in packets for line in packet.splitlines()
                      if line.startswith('data: ') and line[6:] != '[DONE]']
        return (any(e.get('type') == 'save_status' and e.get('success') for e in events)
                and not any(e.get('type') == 'error' or e.get('error') for e in events))
    except (ValueError, TypeError, AttributeError):
        return False


class LiveTurn:
    def __init__(self, request, client_id):
        self.request, self.client_id = request, client_id
        self.job_id = 'chatjob_' + str(int(time.time()*1000)) + '_' + uuid.uuid4().hex[:8]
        self.guard = threading.Lock()
        self.pending = deque()
        self.inflight = 0
        self.accepting = True
        self.input_failed = False
        self.routing_waiting = False
        self.delivery_owner_only = False
        self.known = set()
        self.known.update(m.message_id for m in (request.messages or []) if m.role == 'user' and m.message_id)
        self.prepare_input = None
        self.input_lock = asyncio.Lock()
        self.ready, self.done = asyncio.Event(), asyncio.Event()
        self.input_ready = asyncio.Event()
        self.changed = asyncio.Condition()
        self.packets = []
        self.response = None
        self.failure = None
        self.task = None
        self.input_receipts = []

    def reserve(self):
        with self.guard:
            if not self.accepting:
                return False
            self.inflight += 1
            return True

    def defer_speaker_change(self):
        """Finish the current speaker before routing a new addressed turn."""
        with self.guard:
            self.routing_waiting = True
            self.accepting = False

    def close_failed_input(self):
        """Stop accepting supplements before failure cleanup has finished."""
        with self.guard:
            self.input_failed = True
            self.accepting = False
        self.input_ready.set()

    def release_input(self):
        with self.guard:
            self.inflight -= 1

    def add(self, rows):
        with self.guard:
            fresh = []
            for row in rows:
                mid = row.get('message_id')
                if mid and mid not in self.known:
                    self.known.add(mid)
                    fresh.append(row)
            self.pending.extend(fresh)
            return fresh

    def snapshot_loaded(self, rows):
        with self.guard:
            included = {row.get('message_id') for row in rows}
            self.known.update(included - {None})
            self.pending = deque(row for row in self.pending if row.get('message_id') not in included)

    def take_pending(self):
        with self.guard:
            if self.prepare_input is None:
                return []
            rows = list(self.pending)
            self.pending.clear()
            return rows

    def try_seal(self):
        with self.guard:
            if self.pending or self.inflight:
                return False
            self.accepting = False
            return True

    async def publish(self, packet):
        async with self.changed:
            self.packets.append(packet)
            self.changed.notify_all()

    async def pump(self, handler, *args, **kwargs):
        try:
            self.response = await handler(*args, **kwargs)
            self.ready.set()
            iterator = getattr(self.response, 'body_iterator', None)
            if iterator is not None:
                async for packet in iterator:
                    await self.publish(packet.decode() if isinstance(packet, bytes) else str(packet))
        except BaseException as exc:
            self.failure = exc
            self.close_failed_input()
        finally:
            with self.guard:
                self.accepting = False
            self.ready.set()
            self.input_ready.set()
            self.done.set()
            async with self.changed:
                self.changed.notify_all()
            key = (self.request.username, self.request.character_id)
            if registry().get(key) is self:
                registry().pop(key, None)
            if ((self.prepare_input or self.delivery_owner_only) and not self.failure
                    and has_saved_delivery(self.response, self.packets)):
                cache = completed_turns()
                cache[key] = (time.monotonic(), self)
                cache.move_to_end(key)
                completed_turns()

    async def subscribe(self, *, accepted=None, use_json=False):
        await self.ready.wait()
        if self.failure and not self.packets:
            raise self.failure
        if isinstance(self.response, JSONResponse):
            await self.done.wait()
            if accepted:
                payload = json.loads(self.response.body)
                payload['events'] = [accepted, *[e for e in payload.get('events', []) if e.get('type') != 'accepted']]
                return JSONResponse(payload, status_code=self.response.status_code)
            return self.response

        async def lines():
            if accepted:
                yield 'data: ' + json.dumps(accepted, ensure_ascii=False) + '\n\n'
            index = 0
            while True:
                async with self.changed:
                    if index >= len(self.packets) and not self.done.is_set():
                        try:
                            await asyncio.wait_for(self.changed.wait(), 10)
                        except asyncio.TimeoutError:
                            pass
                    packets = self.packets[index:]
                    index = len(self.packets)
                    done = self.done.is_set()
                for packet in packets:
                    if accepted and '"type": "accepted"' in packet:
                        continue
                    yield packet
                if done:
                    if self.failure:
                        yield 'data: ' + json.dumps({'type': 'error', 'message': '本次回复未能完成，请重试。'}, ensure_ascii=False) + '\n\n'
                        yield 'data: [DONE]\n\n'
                    break
                if not packets:
                    yield ': keep-alive\n\n'

        if use_json:
            events = []
            async for packet in lines():
                for line in packet.splitlines():
                    if line.startswith('data: ') and line[6:] != '[DONE]':
                        events.append(json.loads(line[6:]))
            return JSONResponse({'protocol': 'ponychat_chat_v1', 'mode': 'normal', 'events': events})
        return StreamingResponse(lines(), media_type='text/event-stream',
                                 headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'})


async def join_turn(turn, request, client_id, use_json):
    """Persist first, then feed only new canonical user messages to the inbox."""
    from .service import _persist_android_normal_user_delta, _latest_visible_user_batch
    from .autonomous_normal import visible_messages
    try:
        await turn.input_ready.wait()
        if turn.input_failed or turn.failure or turn.done.is_set():
            return _RETRY_INTAKE
        if turn.prepare_input is None:
            # A quota/shortcut response can finish without creating an Agent.
            # Do not acknowledge a new message as consumed by that old response.
            return _RETRY_INTAKE
        request.conversation_id = turn.request.conversation_id
        async with turn.input_lock:
            # Capture IDs before the existing persistence helper rebuilds history.
            batch = _latest_visible_user_batch(list(request.messages or []))
            if any(not m.message_id for m in batch):
                raise HTTPException(400, '补充消息缺少 message_id')
            ids = {m.message_id for m in batch}
            await _persist_android_normal_user_delta(request, client_id='android')
            # Persistence awaits I/O: the old owner may have failed or finished
            # in the meantime. Never acknowledge a fresh input on its old job.
            if turn.input_failed or turn.failure or turn.done.is_set():
                return _RETRY_INTAKE
            rows = [m for m in visible_messages(request.messages) if m.get('message_id') in ids]
            turn.add(rows)
            accepted = {'type': 'accepted', 'job_id': turn.job_id,
                'conversation_id': turn.request.conversation_id,
                'client_message_id': batch[-1].message_id if batch else None,
                'accepted_at_ms': int(time.time()*1000), 'supplemental': True}
    finally:
        turn.release_input()
    return await turn.subscribe(accepted=accepted, use_json=use_json)


async def normal_live_response(request, client_id, auth, model, *, use_json, handler):
    """Share ordinary supplements; route addressed turns after the current owner."""
    if request.mode != 'normal' or request.is_summary_request:
        return None
    if (client_id or '').strip() not in {'android', 'single', 'companion_external'}:
        return None
    from ..routes.auth import auth_token_verify
    verified = await auth_token_verify((auth or '').strip())
    if not verified or verified != request.username:
        # Preserve the route's existing authentication error response.
        return None
    from ..background_jobs import create_tracked_task
    # An addressed turn may wait behind the current speaker for a while. Own
    # that wait and its later dispatch independently of the HTTP connection.
    intake = create_tracked_task(_normal_authenticated_intake(
        request, client_id, auth, model, use_json=use_json, handler=handler),
        job_id='normal_intake_' + uuid.uuid4().hex, kind='normal_input')
    return await asyncio.shield(intake)


async def _normal_authenticated_intake(request, client_id, auth, model, *, use_json, handler):
    from .service import _latest_visible_user_batch
    from .normal_speaker import extract_at_mention_names, requested_reply_character_ids
    batch = _latest_visible_user_batch(list(request.messages or []))
    if not batch:
        return None
    key = (request.username, request.character_id)
    ids = {m.message_id for m in batch}
    addressed = bool(requested_reply_character_ids(request) or any(
        extract_at_mention_names(m.content) for m in batch))
    while True:
        # A prior waiter can finish while this intake waits. Check replay on
        # every wake-up so a concurrent retry never starts a duplicate guest.
        cached = completed_turns().get(key)
        if cached and None not in ids and ids <= cached[1].known:
            previous = cached[1]
            if not request.conversation_id or request.conversation_id == previous.request.conversation_id:
                return await previous.subscribe(use_json=use_json)
        existing = registry().get(key)
        if existing is None:
            break
        if existing.input_failed:
            await existing.done.wait()
            continue
        if request.conversation_id and existing.request.conversation_id and request.conversation_id != existing.request.conversation_id:
            # Different conversation: wait without mixing its messages or cancelling.
            await existing.done.wait()
            continue
        if None not in ids and ids <= existing.known:
            return await existing.subscribe(use_json=use_json)
        if addressed:
            # An @ or quoted guest reply changes who owns the next answer.
            # It must pass speaker resolution, not the current Agent's inbox.
            existing.defer_speaker_change()
            await existing.done.wait()
            continue
        if existing.reserve():
            from ..background_jobs import create_tracked_task
            intake = create_tracked_task(join_turn(existing, request, client_id, use_json),
                job_id=existing.job_id + ':input:' + uuid.uuid4().hex[:8], kind='normal_input')
            response = await asyncio.shield(intake)
            if response is _RETRY_INTAKE:
                await existing.done.wait()
                continue
            return response
        if existing.delivery_owner_only:
            # Any new user input ends the autonomous role-to-role chain once
            # its current speaker completes, including text without an @.
            existing.defer_speaker_change()
        await existing.done.wait()
    turn = LiveTurn(request, client_id)
    registry()[key] = turn
    request._normal_live_turn = turn
    request._normal_accepted_job_id = turn.job_id
    from ..background_jobs import create_tracked_task
    turn.task = create_tracked_task(turn.pump(handler, request, client_id, auth, model,
        use_json_protocol=use_json), job_id=turn.job_id + ':owner', kind='normal_chat')
    return await turn.subscribe(use_json=use_json)
