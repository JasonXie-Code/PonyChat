"""Local requests serialize across entry points without leaking cancelled slots."""
import asyncio

from Backend.chat_modules.local_model_queue import local_model_slot, queued_local_turn, queued_local_stream

CONFIG = {'endpoint': 'http://127.0.0.1:8072/v1'}


def test_fifo_cancel_and_reentrant_calls():
    async def scenario():
        entered = []
        release = asyncio.Event()
        started = asyncio.Event()

        async def first():
            async with local_model_slot(CONFIG):
                started.set()
                await release.wait()

        async def waiter(index):
            async with local_model_slot('http://localhost:8072/v1/chat/completions'):
                entered.append(index)
                async with local_model_slot(CONFIG):
                    await asyncio.sleep(0)

        owner = asyncio.create_task(first())
        await started.wait()
        tasks = [asyncio.create_task(waiter(i)) for i in range(3)]
        await asyncio.sleep(0)
        tasks[1].cancel()
        await asyncio.gather(tasks[1], return_exceptions=True)
        assert entered == []
        release.set()
        await asyncio.wait_for(asyncio.gather(owner, tasks[0], tasks[2]), 1)
        assert entered == [0, 2]
        async with local_model_slot(CONFIG):
            pass
    asyncio.run(scenario())


def test_stream_close_releases_slot():
    @queued_local_stream
    async def stream(payload, model_cfg):
        yield 'first'
        await asyncio.sleep(60)

    async def scenario():
        output = stream({}, CONFIG)
        assert await anext(output) == 'first'
        acquired = asyncio.Event()

        async def waiting():
            async with local_model_slot(CONFIG):
                acquired.set()

        # Use a clean context: stream ownership belongs to the consuming task.
        import contextvars
        task = asyncio.create_task(waiting(), context=contextvars.Context())
        await asyncio.sleep(0)
        assert not acquired.is_set()
        await output.aclose()
        await asyncio.wait_for(task, 1)
        assert acquired.is_set()
    asyncio.run(scenario())


def test_execution_deadline_starts_after_queue():
    @queued_local_turn
    async def run(prompt, model_config):
        await asyncio.wait_for(asyncio.sleep(0), .01)
        return 'done'

    async def scenario():
        release = asyncio.Event()
        started = asyncio.Event()

        async def owner():
            async with local_model_slot(CONFIG):
                started.set()
                await release.wait()

        task = asyncio.create_task(owner())
        await started.wait()
        queued = asyncio.create_task(run('prompt', CONFIG))
        await asyncio.sleep(.03)
        assert not queued.done()
        # Cloud requests use an independent lane.
        assert await run('prompt', {'endpoint': 'https://api.deepseek.com'}) == 'done'
        release.set()
        assert await asyncio.wait_for(queued, 1) == 'done'
        await task
    asyncio.run(scenario())
