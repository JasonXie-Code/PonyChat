"""Durable normal input batches, closed by the first visible reply, not generation."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi.responses import JSONResponse, StreamingResponse

from .live_turn import LiveTurn


def clean_request(request):
    # Never clone runtime locks, staged memory or a previous speaker's caches.
    from ..utils import ChatRequest
    clean = ChatRequest(**{name: request.__dict__[name] for name in ChatRequest.model_fields}).model_copy(deep=True)
    clean._supports_web_image_receipts = bool(getattr(request, '_supports_web_image_receipts', False))
    return clean


class ReplyBatch(LiveTurn):
    def __init__(self, request, client_id):
        super().__init__(request, client_id)
        self.template = clean_request(request)
        self.template.messages = []
        self.known.clear()
        self.revision = 0
        self.delivered = False
        self.delivery_gate = asyncio.Lock()
        self.attempt = None
        self.wake = asyncio.Event()
        self.predecessor = None
        # The batch is the transport owner even when speaker routing creates children.
        self.delivery_owner_only = True

    def current(self, revision):
        return revision == self.revision

    def receipt(self, rows):
        return {'type': 'accepted', 'job_id': self.job_id,
                'conversation_id': self.template.conversation_id,
                'client_message_id': rows[-1].message_id if rows else None,
                'accepted_at_ms': int(time.time() * 1000), 'supplemental': len(self.known) > 1}

    def close_failed_input(self):
        # A cancelled attempt is being replaced; its cleanup must not close the batch.
        if self.attempt is not None and self.attempt.cancelling():
            return
        super().close_failed_input()

    async def admit(self, request):
        from .service import _persist_android_normal_user_delta, _latest_visible_user_batch
        from fastapi import HTTPException
        rows = _latest_visible_user_batch(list(request.messages or []))
        if any(not row.message_id for row in rows):
            raise HTTPException(400, '消息缺少 message_id')
        async with self.delivery_gate:
            if self.delivered or self.done.is_set() or self.input_failed:
                return None
            fresh = [row for row in rows if row.message_id not in self.known]
            if fresh:
                saved = clean_request(request)
                saved.conversation_id = self.template.conversation_id
                saved._normal_autonomous_harness_requested = True
                await _persist_android_normal_user_delta(saved, client_id=self.client_id)
                self.template.conversation_id = saved.conversation_id
                request.conversation_id = saved.conversation_id
                self.request.conversation_id = saved.conversation_id
                if not self.known:
                    self.template.messages = list(clean_request(request).messages)
                else:
                    self.template.messages.extend(row.model_copy(deep=True) for row in fresh)
                if request.reply_character_id or request.reply_character_ids:
                    self.template.reply_character_id = request.reply_character_id
                    self.template.reply_character_ids = request.reply_character_ids
                self.known.update(row.message_id for row in fresh)
                self.revision += 1
                # Cancel only once: repeated cancellation would interrupt cleanup.
                if self.attempt and not self.attempt.done() and not self.attempt.cancelling():
                    self.attempt.cancel()
                self.wake.set()
            return self.receipt(rows)

    async def run(self, handler, auth, model):
        async def response():
            return StreamingResponse(self.generate(handler, auth, model), media_type='text/event-stream')
        await super().pump(response)

    async def generate(self, handler, auth, model):
        if self.predecessor is not None:
            await self.predecessor.done.wait()
        while True:
            # Briefly collect a burst to avoid starting a model for each tap.
            # This is an optimization only; admission stays open until delivery.
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), .15)
                continue
            except asyncio.TimeoutError:
                pass
            async with self.delivery_gate:
                revision = self.revision
                request = clean_request(self.template)
                request._normal_live_turn = self
                request._normal_reply_batch = self
                request._normal_reply_revision = revision
                request._normal_accepted_job_id = self.job_id
                request._normal_accepted_already_streamed = True
                self.request = request
                self.input_failed = False
                self.accepting = True
                self.prepare_input = None
                self.input_ready.clear()
                self.pending.clear()
            queue = asyncio.Queue()

            async def attempt():
                try:
                    result = await handler(request, self.client_id, auth, model, use_json_protocol=False)
                    if isinstance(result, JSONResponse):
                        for event in json.loads(result.body).get('events', []):
                            queue.put_nowait('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n')
                    else:
                        async for packet in result.body_iterator:
                            queue.put_nowait(packet.decode() if isinstance(packet, bytes) else str(packet))
                finally:
                    queue.put_nowait(None)

            self.attempt = asyncio.create_task(attempt())
            buffered = []
            try:
                while True:
                    packet = await queue.get()
                    if packet is None:
                        break
                    if not self.current(revision):
                        continue
                    if '"type": "accepted"' in packet:
                        continue
                    buffered.append(packet)
                    if self.delivered:
                        for value in buffered:
                            yield value
                        buffered.clear()
                await self.attempt
            except asyncio.CancelledError:
                if self.current(revision):
                    raise
            finally:
                if not self.attempt.done():
                    self.attempt.cancel()
                    await asyncio.gather(self.attempt, return_exceptions=True)
            if not self.current(revision):
                continue
            for value in buffered:
                yield value
            yield 'data: [DONE]\n\n'
            return


async def batch_intake(request, client_id, auth, model, *, use_json, handler):
    from .live_turn import registry, completed_turns
    from .service import _latest_visible_user_batch
    from ..background_jobs import create_tracked_task
    rows = _latest_visible_user_batch(list(request.messages or []))
    if not rows:
        return None
    key = (request.username, request.character_id)
    ids = {row.message_id for row in rows}
    while True:
        cached = completed_turns().get(key)
        if cached and None not in ids and ids <= cached[1].known:
            previous = cached[1]
            if not request.conversation_id or request.conversation_id == previous.request.conversation_id:
                return await previous.subscribe(accepted=previous.receipt(rows) if isinstance(previous, ReplyBatch) else None,
                                                use_json=use_json)
        batch = registry().get(key)
        if batch is None:
            batch = ReplyBatch(request, client_id)
            registry()[key] = batch
        if not isinstance(batch, ReplyBatch):
            # Older in-process owners retain their existing cleanup contract.
            from .live_turn import _normal_authenticated_intake
            return await _normal_authenticated_intake(request, client_id, auth, model,
                                                       use_json=use_json, handler=handler)
        if request.conversation_id and batch.request.conversation_id and request.conversation_id != batch.request.conversation_id:
            successor = ReplyBatch(request, client_id)
            successor.predecessor = batch
            registry()[key] = successor
            continue
        if ids <= batch.known:
            return await batch.subscribe(accepted=batch.receipt(rows), use_json=use_json)
        try:
            accepted = await batch.admit(request)
        except BaseException:
            if batch.task is None:
                if registry().get(key) is batch:
                    registry().pop(key, None)
                batch.done.set()
            raise
        if accepted is None:
            if registry().get(key) is not batch:
                continue
            if not batch.done.is_set():
                # A new round is acknowledged now, while the previous reply is
                # still being delivered. Later inputs join this queued batch.
                successor = ReplyBatch(request, client_id)
                successor.predecessor = batch
                batch.defer_speaker_change()
                registry()[key] = successor
            else:
                await batch.done.wait()
            continue
        if batch.task is None:
            batch.task = create_tracked_task(batch.run(handler, auth, model),
                                            job_id=batch.job_id + ':owner', kind='normal_chat')
        return await batch.subscribe(accepted=accepted, use_json=use_json)
