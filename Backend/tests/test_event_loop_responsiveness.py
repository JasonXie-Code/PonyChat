"""Slow production I/O must leave the event loop available for network requests."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from Backend.agent_memory.review import ReviewTools
from Backend.routes.admin import llm_log_indexer as logs
from test_log_index_recovery import setup
from test_harness_pool import pool


async def network_during_blocked(operation, entered, release):
    async def respond(reader, writer):
        await reader.read(1)
        writer.write(b'ok')
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_server(respond, '127.0.0.1', 0)
    task = asyncio.create_task(operation())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert not task.done(), 'slow I/O finished before network could be scheduled'
        async def request():
            reader, writer = await asyncio.open_connection('127.0.0.1', server.sockets[0].getsockname()[1])
            writer.write(b'x')
            await writer.drain()
            assert await reader.readexactly(2) == b'ok'
            writer.close()
            await writer.wait_closed()
        await asyncio.wait_for(request(), .5)
    finally:
        release.set()
        await task
        server.close()
        await server.wait_closed()


def slow_call(original, entered, release):
    def call(*args, **kwargs):
        entered.set()
        assert release.wait(3), 'event loop was blocked by synchronous I/O'
        return original(*args, **kwargs)
    return call


@pytest.mark.parametrize('phase', ['enumerate', 'parse'])
def test_index_scan_serves_network_during_slow_disk(tmp_path, monkeypatch, phase):
    indexer, _ = setup(tmp_path)
    entered, release = threading.Event(), threading.Event()
    if phase == 'enumerate':
        original = indexer._changed_files
        monkeypatch.setattr(indexer, '_changed_files', slow_call(original, entered, release))
    else:
        monkeypatch.setattr(logs, '_parse_log_file', slow_call(logs._parse_log_file, entered, release))
    async def scenario():
        await indexer.init_schema()
        await network_during_blocked(indexer.scan_all, entered, release)
        assert (await indexer.scan_all())['files_skipped'] == 1
    asyncio.run(scenario())


def test_harness_cleanup_serves_network():
    entered, release = threading.Event(), threading.Event()
    async def scenario():
        entry = pool.Entry('test')
        cleanup = entry.home.cleanup
        entry.home = SimpleNamespace(cleanup=slow_call(cleanup, entered, release))
        await network_during_blocked(entry.close, entered, release)
        await entry.close()  # idempotent shutdown remains valid
    asyncio.run(scenario())


def test_memory_evidence_serves_network():
    entered, release = threading.Event(), threading.Event()
    store = SimpleNamespace(list=lambda **kwargs: [{'source_ref':'m1','stale':False,'status':'active'}],
        allow_visible_sources=slow_call(lambda refs: list(refs), entered, release))
    async def scenario():
        tools = ReviewTools(None, {}, store)
        await network_during_blocked(lambda: tools.memories({}), entered, release)
    asyncio.run(scenario())


def test_cancelled_memory_tool_drains_before_next_tool():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def allow(refs):
        calls.append(list(refs))
        entered.set()
        assert release.wait(3)
    store = SimpleNamespace(list=lambda **kwargs: [{'source_ref':'m1','stale':False,'status':'active'}],
                            allow_visible_sources=allow)
    async def scenario():
        tools = ReviewTools(None, {}, store)
        first = asyncio.create_task(tools.memories({}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            first.cancel()
            second = asyncio.create_task(tools.memories({}))
            await asyncio.sleep(.05)
            assert not first.done() and not second.done()
            assert len(calls) == 1
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second
        assert len(calls) == 2
    asyncio.run(scenario())
