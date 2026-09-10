"""Regression coverage for SQLite event-loop stalls and accepted mobile failures."""
import ast
import asyncio
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest

from test_unified_agent_memory import db, jobs

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('android_accept_test', ROOT / 'chat_modules/service_impl/android_normal_accept.py')
accept = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accept)


@pytest.fixture(autouse=True)
def tracked_jobs(monkeypatch):
    tasks = []
    def create(awaitable, **kwargs):
        task = asyncio.create_task(awaitable)
        tasks.append(task)
        return task
    monkeypatch.setattr(accept, '_create_tracked_task', create)
    return tasks


def test_relationship_lock_wait_does_not_block_the_writer_commit(db):
    tree = ast.parse((ROOT / 'relationship_insights.py').read_text(encoding='utf8'))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'load_relationship_state')
    function.body = [node for node in function.body if not isinstance(node, ast.ImportFrom)]
    env = {'asyncio': asyncio, 'Optional': __import__('typing').Optional, 'Dict': dict, 'Any': object,
           'project': lambda *args: None, 'complete_page': lambda value: False,
           'get_database': lambda: SimpleNamespace(db_path=db),
           'request_relationship': jobs.request_relationship, 'status': jobs.status}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<relationship>', 'exec'), env)

    async def exercise():
        holder = sqlite3.connect(db)
        holder.execute('BEGIN IMMEDIATE')
        async def release():
            await asyncio.sleep(.03)
            holder.rollback()
        releasing = asyncio.create_task(release())
        try:
            result = await asyncio.wait_for(env['load_relationship_state']('alice', 'twilight'), 1)
            assert result['generation_status'] == 'queued'
        finally:
            holder.rollback()
            holder.close()
            await releasing
    asyncio.run(exercise())


async def response_for(handler):
    async def persisted(*args, **kwargs):
        pass
    request = SimpleNamespace(mode='normal', is_summary_request=False, conversation_id='c',
                              messages=[SimpleNamespace(role='user', isHidden=False, message_id='m')])
    return await accept.maybe_early_android_normal_accepted_response(
        request, 'android', 'token', {}, False, 'android', False, {'android'},
        lambda messages: messages, persisted, handler, SimpleNamespace(exception=lambda *args: None))


def test_accepted_request_has_keepalive_and_terminal_public_error(monkeypatch):
    monkeypatch.setattr(accept, 'KEEPALIVE_SECONDS', .005)
    async def exercise():
        async def fail(*args, **kwargs):
            await asyncio.sleep(.02)
            raise RuntimeError('Private evidence review internal detail')
        response = await response_for(fail)
        chunks = [chunk async for chunk in response.body_iterator]
        assert '"type": "accepted"' in chunks[0]
        assert ': keep-alive\n\n' in chunks
        event = json.loads(chunks[-2][6:])
        assert event['type'] == 'error' and event['message'] == event['error']
        assert 'Private' not in ''.join(chunks)
        assert chunks[-1] == 'data: [DONE]\n\n'
    asyncio.run(exercise())


@pytest.mark.parametrize('disconnect_at', ['before_stream', 'accepted', 'generating', 'delivery'])
def test_disconnect_preserves_generation_and_lazy_persistence(monkeypatch, tracked_jobs, disconnect_at):
    monkeypatch.setattr(accept, 'KEEPALIVE_SECONDS', .005)
    async def exercise():
        from fastapi.responses import StreamingResponse
        started, finish = asyncio.Event(), asyncio.Event()
        persisted = []
        async def pending(*args, **kwargs):
            started.set()
            await finish.wait()
            async def delivery():
                yield 'data: {"type":"reply"}\n\n'
                await asyncio.sleep(.01)
                persisted.append('saved')
                yield 'data: [DONE]\n\n'
            return StreamingResponse(delivery())
        response = await response_for(pending)
        stream = response.body_iterator
        if disconnect_at != 'before_stream':
            await anext(stream)
        if disconnect_at == 'generating':
            await anext(stream)
        if disconnect_at == 'delivery':
            finish.set()
            while '"reply"' not in await anext(stream):
                pass
        await stream.aclose()
        await started.wait()
        finish.set()
        await asyncio.wait_for(asyncio.gather(*tracked_jobs), 1)
        assert persisted == ['saved']
    asyncio.run(exercise())
