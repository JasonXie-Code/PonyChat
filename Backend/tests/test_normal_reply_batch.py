"""First-visible-reply boundary and immediate durable receipts with slow generation."""
import asyncio
import json

import pytest
from fastapi.responses import StreamingResponse

from Backend.chat_modules import live_turn, service
from Backend.chat_modules.normal_delivery import NormalDeliverySession
from Backend.utils import ChatMessage, ChatRequest


def request(text, mid, conversation='scene'):
    return ChatRequest(username='batch-user', character_id='main', conversation_id=conversation,
                       mode='normal', messages=[ChatMessage(role='user', content=text, message_id=mid)])


@pytest.fixture
def intake(monkeypatch):
    from Backend.routes import auth
    from Backend import background_jobs
    saved = []
    async def verify(_): return 'batch-user'
    async def persist(req, **kwargs):
        saved.extend(m.message_id for m in req.messages if m.message_id not in saved)
    monkeypatch.setattr(auth, 'auth_token_verify', verify)
    monkeypatch.setattr(service, '_persist_android_normal_user_delta', persist)
    monkeypatch.setattr(background_jobs, 'create_tracked_task', lambda coro, **kw: asyncio.create_task(coro))
    async def send(req, handler):
        return await asyncio.wait_for(live_turn.normal_live_response(req, 'android', 'token', {},
                                      use_json=False, handler=handler), .5)
    return send, saved


async def received(response, mid, saved):
    iterator = response.body_iterator
    packet = await asyncio.wait_for(anext(iterator), .2)
    event = json.loads(packet[6:])
    assert event['type'] == 'accepted' and event['client_message_id'] == mid
    assert mid in saved
    return iterator, event


def reply(req, text, gate=None):
    async def lines():
        delivery = NormalDeliverySession()
        try:
            event = dict(type='assistant_paragraph', content=text, id='reply-' + str(req._normal_reply_revision))
            await delivery.release(event, req, delay_seconds=0)
            yield 'data: ' + json.dumps(event) + '\n\n'
            if gate:
                await gate.wait()
            yield 'data: {"type":"save_status","success":true}\n\n'
        finally:
            await delivery.finish()
    return StreamingResponse(lines())


@pytest.mark.parametrize('supplement', ['@碧琪', '补充评论'])
def test_received_during_generation_restarts_whole_batch_before_reply(intake, supplement):
    send, saved = intake
    async def scenario():
        started, cancelled = asyncio.Event(), asyncio.Event()
        attempts = []
        async def handler(req, *args, **kwargs):
            texts = [m.content for m in req.messages]
            attempts.append(texts)
            if len(texts) == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return reply(req, '|'.join(texts))
        first, first_ack = await received(await send(request('评论内容', 'one'), handler), 'one', saved)
        await asyncio.wait_for(started.wait(), 1)
        second, second_ack = await received(await send(request(supplement, 'two'), handler), 'two', saved)
        assert first_ack['job_id'] == second_ack['job_id']
        async def drain(iterator): return ''.join([p async for p in iterator])
        outputs = await asyncio.wait_for(asyncio.gather(drain(first), drain(second)), 2)
        assert cancelled.is_set() and attempts == [['评论内容'], ['评论内容', supplement]]
        assert all(out.count('assistant_paragraph') == 1 for out in outputs)
        assert saved == ['one', 'two']
        assert not live_turn.registry()
    asyncio.run(scenario())


def test_after_first_visible_reply_next_round_is_acknowledged_without_waiting(intake):
    send, saved = intake
    async def scenario():
        finish = asyncio.Event()
        attempts = []
        async def handler(req, *args, **kwargs):
            attempts.append([m.message_id for m in req.messages])
            return reply(req, req.messages[-1].content, finish if len(attempts) == 1 else None)
        first, ack1 = await received(await send(request('first', 'one'), handler), 'one', saved)
        visible = await asyncio.wait_for(anext(first), 1)
        assert 'assistant_paragraph' in visible
        old = live_turn.active_turn('batch-user', 'main')
        await old.delivery_gate.acquire()
        waiting2 = asyncio.create_task(send(request('@碧琪', 'two'), handler))
        waiting3 = asyncio.create_task(send(request('补充', 'three'), handler))
        await asyncio.sleep(.01)
        old.delivery_gate.release()
        response2, response3 = await asyncio.gather(waiting2, waiting3)
        second, ack2 = await received(response2, 'two', saved)
        third, ack3 = await received(response3, 'three', saved)
        assert ack1['job_id'] != ack2['job_id'] == ack3['job_id']
        assert attempts == [['one']]
        finish.set()
        async def drain(it): return [p async for p in it]
        await asyncio.wait_for(asyncio.gather(drain(first), drain(second), drain(third)), 2)
        assert attempts == [['one'], ['two', 'three']]
    asyncio.run(scenario())


def test_disconnect_and_duplicate_do_not_duplicate_generation(intake):
    send, saved = intake
    async def scenario():
        calls = []
        async def handler(req, *args, **kwargs):
            calls.append([m.message_id for m in req.messages])
            return reply(req, 'complete')
        first, _ = await received(await send(request('comment', 'one'), handler), 'one', saved)
        await first.aclose()
        second, _ = await received(await send(request('@碧琪', 'two'), handler), 'two', saved)
        duplicate = await send(request('@碧琪', 'two'), handler)
        async def drain(it): return [p async for p in it]
        await asyncio.wait_for(asyncio.gather(drain(second), drain(duplicate.body_iterator)), 2)
        assert calls == [['one', 'two']] and saved == ['one', 'two']
    asyncio.run(scenario())


def test_second_supplement_does_not_interrupt_superseded_cleanup(intake):
    send, saved = intake
    async def scenario():
        started, cleaning, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = []
        async def handler(req, *args, **kwargs):
            calls.append([m.message_id for m in req.messages])
            if len(calls) == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await asyncio.sleep(.1)
                    cleaned.set()
            assert cleaned.is_set()
            return reply(req, 'merged')
        one, _ = await received(await send(request('comment', 'one'), handler), 'one', saved)
        await asyncio.wait_for(started.wait(), 1)
        two, _ = await received(await send(request('@碧琪', 'two'), handler), 'two', saved)
        await asyncio.wait_for(cleaning.wait(), 1)
        three, _ = await received(await send(request('detail', 'three'), handler), 'three', saved)
        async def drain(it): return [p async for p in it]
        await asyncio.wait_for(asyncio.gather(*map(drain, [one, two, three])), 2)
        assert calls == [['one'], ['one', 'two', 'three']]
    asyncio.run(scenario())


def test_save_failure_is_not_acknowledged_and_retry_can_start(intake, monkeypatch):
    send, saved = intake
    original = service._persist_android_normal_user_delta
    async def fail(*args, **kwargs): raise RuntimeError('storage unavailable')
    async def scenario():
        async def handler(req, *args, **kwargs): return reply(req, 'ok')
        monkeypatch.setattr(service, '_persist_android_normal_user_delta', fail)
        with pytest.raises(RuntimeError, match='storage unavailable'):
            await send(request('comment', 'one'), handler)
        assert not live_turn.registry() and not saved
        monkeypatch.setattr(service, '_persist_android_normal_user_delta', original)
        iterator, _ = await received(await send(request('comment', 'one'), handler), 'one', saved)
        assert [p async for p in iterator]
    asyncio.run(scenario())


def test_http_receipt_arrives_before_slow_model_finishes(intake):
    import socket
    import httpx
    import uvicorn
    from fastapi import FastAPI
    _, saved = intake
    async def scenario():
        started = asyncio.Event()
        app = FastAPI()
        async def handler(req, *args, **kwargs):
            if len(req.messages) == 1:
                started.set()
                await asyncio.Event().wait()
            return reply(req, 'merged')
        @app.post('/chat')
        async def chat(req: ChatRequest):
            return await live_turn.normal_live_response(req, 'android', 'token', {},
                                                        use_json=False, handler=handler)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
        owner = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            while not server.started:
                await asyncio.sleep(.01)
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                async with client.stream('POST', f'http://127.0.0.1:{port}/chat',
                                         json=request('comment', 'one').model_dump()) as first:
                    assert first.status_code == 200
                    event1 = json.loads((await anext(first.aiter_lines()))[6:])
                    assert event1['client_message_id'] == 'one' and 'one' in saved
                    await asyncio.wait_for(started.wait(), 1)
                    async with client.stream('POST', f'http://127.0.0.1:{port}/chat',
                                             json=request('@碧琪', 'two').model_dump()) as second:
                        lines = second.aiter_lines()
                        event2 = json.loads((await anext(lines))[6:])
                        assert event2['client_message_id'] == 'two' and 'two' in saved
                        assert event1['job_id'] == event2['job_id']
                        packets = [line async for line in lines]
                        assert any('assistant_paragraph' in line for line in packets)
        finally:
            server.should_exit = True
            await asyncio.wait_for(owner, 3)
            sock.close()
    asyncio.run(scenario())
