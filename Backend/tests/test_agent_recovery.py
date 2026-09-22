"""Transport disconnects must not own Agent tasks or game settlement."""
import asyncio
from collections import deque
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('tested_live_turn', ROOT / 'chat_modules/live_turn.py')
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


def test_failed_json_and_compact_sse_are_not_cached_as_successful_replies():
    from fastapi.responses import JSONResponse
    assert not live.has_saved_delivery(JSONResponse({'events': [{'type': 'error', 'message': 'retry'}]}), [])
    assert not live.has_saved_delivery(None, ['data: {"type":"error"}\n\n'])
    saved = 'data: {"type":"save_status","success":true}\n\n'
    assert live.has_saved_delivery(None, [saved, 'data: [DONE]\n\n'])
    assert not live.has_saved_delivery(None, [saved, 'data: {"type":"error"}\n\n'])


def test_inbox_deduplicates_and_does_not_seal_during_persistence():
    async def scenario():
        turn = live.LiveTurn(SimpleNamespace(messages=[]), 'android')
        turn.prepare_input = lambda rows: rows
        assert turn.reserve()
        assert not turn.try_seal()
        assert turn.add([{'message_id': 'a'}, {'message_id': 'b'}, {'message_id': 'b'}]) == [
            {'message_id': 'a'}, {'message_id': 'b'}]
        assert not turn.add([{'message_id': 'a'}])
        turn.snapshot_loaded([{'message_id': 'a'}])
        turn.release_input()
        assert not turn.try_seal()
        assert turn.take_pending() == [{'message_id': 'b'}]
        assert turn.try_seal()
        assert not turn.reserve()
    asyncio.run(scenario())


def test_subscriber_disconnect_keeps_owner_and_reconnect_replays_once():
    async def scenario():
        from fastapi.responses import StreamingResponse
        request = SimpleNamespace(messages=[], username='alice', character_id='pony')
        turn = live.LiveTurn(request, 'android')
        gate = asyncio.Event()
        saved = []
        async def handler():
            async def stream():
                yield 'data: {"type": "accepted"}\n\n'
                await gate.wait()
                saved.append('one')
                yield 'data: {"type": "reply", "message_id": "reply1"}\n\n'
            return StreamingResponse(stream())
        owner = asyncio.create_task(turn.pump(handler))
        response = await turn.subscribe()
        assert 'accepted' in await anext(response.body_iterator)
        await response.body_iterator.aclose()
        assert not owner.done()
        gate.set()
        await owner
        replay = await turn.subscribe()
        packets = [p async for p in replay.body_iterator]
        assert saved == ['one'] and sum('reply1' in p for p in packets) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("timeout", [2, None])
def test_live_sdk_waits_for_supplement_receipt_and_uses_same_session(monkeypatch, timeout):
    # 该适配器使用相对导入，必须以包内模块导入；SDK 在其内部按需导入，
    # 因此这里先导入模块、再注入 SDK 桩即可。
    from Backend.chat_modules import harness_live_input as adapter
    # Import path matches the pinned SDK; this explicitly guards its public API.
    monkeypatch.setitem(sys.modules, 'deepseek_harness.api', SimpleNamespace(
        normalize_input=lambda p: p, final_response=lambda events: events[-1]['data']['content'],
        finish_reason=lambda events: 'completed', RunResult=lambda **kw: SimpleNamespace(**kw)))
    async def scenario():
        turn = live.LiveTurn(SimpleNamespace(messages=[]), 'android')
        async def prepare(rows):
            return [{'type': 'text', 'text': 'updated'}]
        turn.prepare_input = prepare
        notifications = deque()
        prompts, observations = [], []
        def event(kind, data):
            return SimpleNamespace(method='session.event', payload={
                'sessionId': 'same-session', 'event': {'type': kind, 'data': data}})
        idle = SimpleNamespace(method='session.status', payload={'sessionId': 'same-session', 'status': 'idle'})
        class Subscription:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def drain(self, collect):
                if notifications:
                    collect(notifications.popleft())
        sub = Subscription()
        def prompt(session, value, **kwargs):
            prompts.append((session, value))
            mid = str(len(prompts))
            if mid == '1':
                turn.add([{'message_id': 'supplement'}])
                notifications.extend([event('agent/inbox/spliced', {'inserted': [{'id': mid}]}),
                                      event('assistant/message', {'content': 'old'}), idle])
            else:
                notifications.extend([event('agent/inbox/spliced', {'inserted': [{'id': mid}]}),
                                      event('assistant/message', {'content': 'updated'}), idle])
            return mid
        harness = SimpleNamespace(start=lambda: None, client=SimpleNamespace(
            session_prompt=prompt, subscribe_session_notifications=lambda sid: sub))
        result = await asyncio.to_thread(adapter.run_with_live_input, harness, 'original',
            session_id='same-session', turn=turn, loop=asyncio.get_running_loop(),
            observe=observations.append, timeout=timeout)
        assert result.final_response == 'updated'
        assert [p[0] for p in prompts] == ['same-session', 'same-session']
        assert turn.input_receipts[0]['message_ids'] == ['supplement']
        assert not turn.accepting
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['galgame', 'galgame_lock'])
@pytest.mark.parametrize('disconnect_at', ['before_stream', 'generating', 'saving'])
def test_both_game_modes_finish_once_and_release_only_after_save(monkeypatch, mode, disconnect_at):
    from Backend.galgame import sse_handler as game
    from Backend import background_jobs
    from Backend.chat_modules import state
    async def scenario():
        started, finish_model, saving, finish_save = [asyncio.Event() for _ in range(4)]
        tasks, actions = [], []
        def tracked(coro, **kwargs):
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task
        async def agent(*args, **kwargs):
            assert kwargs['mode'] == mode
            started.set()
            await finish_model.wait()
            return SimpleNamespace(text='synthetic')
        async def save(*args, **kwargs):
            saving.set()
            await finish_save.wait()
            actions.append('saved')
            return {'status': 'success'}
        async def release(): actions.append('released')
        async def noop(*args, **kwargs): pass
        monkeypatch.setattr(game, 'run_game_agent', agent)
        monkeypatch.setattr(game, '_handle_galgame_response', save)
        monkeypatch.setattr(game, 'save_chat_debug_log', noop)
        monkeypatch.setattr(background_jobs, 'create_tracked_task', tracked)
        monkeypatch.setattr(state, 'is_generation_cancelled', lambda *args: False)
        monkeypatch.setattr(state, 'clear_generation_cancelled', lambda *args: None)
        response = await game.handle_galgame_sse(request=SimpleNamespace(
            username='alice', character_id='pony', mode=mode), model_name='synthetic', payload={},
            api_url='', headers={}, provider=None, httpx_client=None, messages=[], request_tokens=0,
            username='alice', character_id='pony', client_id='android', effective_username='alice', release_lock=release)
        if disconnect_at != 'before_stream':
            assert 'step' in await anext(response.body_iterator)
        await started.wait()
        if disconnect_at == 'saving':
            finish_model.set()
            await saving.wait()
        await response.body_iterator.aclose()
        assert actions == [] and not tasks[0].done()
        finish_model.set()
        finish_save.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 1)
        assert actions == ['saved', 'released']
    asyncio.run(scenario())
