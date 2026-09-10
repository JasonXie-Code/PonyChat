"""A supplemental message must not be attached to a failed owner during cleanup."""
import asyncio
import json

import pytest
from fastapi.responses import JSONResponse

from Backend.chat_modules import live_turn as live, service
from Backend.utils import ChatMessage, ChatRequest


def request(mid):
    return ChatRequest(username='timeout-test', character_id='pony', conversation_id='scene',
                       mode='normal', messages=[ChatMessage(role='user', content='普通聊天', message_id=mid)])


@pytest.mark.parametrize('failure_point', ['before_ready', 'during_persist', 'error_response'])
def test_new_message_dispatches_after_previous_owner_fails(monkeypatch, failure_point):
    from Backend import background_jobs
    from Backend.routes import auth

    async def verify(_):
        return 'timeout-test'

    monkeypatch.setattr(auth, 'auth_token_verify', verify)
    monkeypatch.setattr(background_jobs, 'create_tracked_task', lambda coro, **kw: asyncio.create_task(coro))
    monkeypatch.setattr(service, '_latest_visible_user_batch', lambda rows: rows[-1:])

    async def scenario():
        old = live.LiveTurn(request('first'), 'android')
        live.registry()[('timeout-test', 'pony')] = old
        entered, finish_old, persist_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        if failure_point != 'before_ready':
            old.prepare_input = lambda rows: rows
            old.input_ready.set()

        async def previous_handler():
            entered.set()
            await finish_old.wait()
            if failure_point == 'error_response':
                return JSONResponse({'events': [{'type': 'error', 'message': 'timed out'}]})
            raise TimeoutError('first round timed out')

        async def persist(r, **kw):
            persist_started.set()
            if failure_point != 'before_ready':
                await old.done.wait()

        monkeypatch.setattr(service, '_persist_android_normal_user_delta', persist)
        dispatched = []

        async def next_handler(r, *args, **kw):
            dispatched.append(r.messages[-1].message_id)
            return JSONResponse({'events': [
                {'type': 'accepted', 'client_message_id': 'second', 'job_id': r._normal_accepted_job_id},
                {'type': 'save_status', 'success': True}]})

        owner = asyncio.create_task(old.pump(previous_handler))
        await entered.wait()
        incoming = request('second')
        send = asyncio.create_task(live.normal_live_response(incoming, 'android', 'token', {},
                                  use_json=True, handler=next_handler))
        if failure_point == 'before_ready':
            for _ in range(20):
                if old.inflight:
                    break
                await asyncio.sleep(0)
            assert old.inflight == 1
        else:
            await asyncio.wait_for(persist_started.wait(), 1)
        finish_old.set()
        await owner
        response = await asyncio.wait_for(send, 1)
        assert response.status_code == 200
        events = json.loads(response.body)['events']
        assert not any(e['type'] == 'error' for e in events)
        assert dispatched == ['second']
        assert incoming._normal_accepted_job_id != old.job_id
        assert old.inflight == 0
        assert not old.pending
        assert not live.registry()

    asyncio.run(scenario())


def test_failure_closes_intake_before_slow_cleanup_finishes(monkeypatch):
    from Backend import background_jobs
    from Backend.routes import auth

    async def verify(_):
        return 'timeout-test'

    monkeypatch.setattr(auth, 'auth_token_verify', verify)
    monkeypatch.setattr(background_jobs, 'create_tracked_task', lambda coro, **kw: asyncio.create_task(coro))
    monkeypatch.setattr(service, '_latest_visible_user_batch', lambda rows: rows[-1:])

    async def scenario():
        old = live.LiveTurn(request('first'), 'android')
        live.registry()[('timeout-test', 'pony')] = old
        old.close_failed_input()
        assert not old.reserve() and old.input_ready.is_set() and not old.done.is_set()
        dispatched = []

        async def handler(r, *args, **kwargs):
            dispatched.append(r.messages[-1].message_id)
            return JSONResponse({'events': [{'type': 'save_status', 'success': True}]})

        send = asyncio.create_task(live.normal_live_response(request('second'), 'android', 'token', {},
                                  use_json=True, handler=handler))
        await asyncio.sleep(0.01)
        assert not send.done() and not dispatched and old.inflight == 0
        live.registry().pop(('timeout-test', 'pony'))
        old.done.set()
        response = await asyncio.wait_for(send, 1)
        assert response.status_code == 200 and dispatched == ['second']

    asyncio.run(scenario())
