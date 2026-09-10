"""Offline regressions for smoke instrumentation; no model or chat requests."""
import asyncio

import pytest

from scripts.ops.smoke_deployed_harness import ToolCallbackObserver


def test_nested_adapter_counts_once_without_deduplicating_real_calls():
    async def run():
        events, writes = [], []
        observer = ToolCallbackObserver(events)

        async def original(arguments):
            writes.append(arguments)
            return {"entry_id": "same-entry"}

        inner = observer.wrap(original, "memory")

        async def adapter(arguments):
            return await inner({**arguments, "mode": "instant_messaging"})

        outer = observer.wrap(adapter, "memory")
        for _ in range(9):
            assert await outer({"content": "same"}) == {"entry_id": "same-entry"}
        assert len(events) == len(writes) == 9
        assert all(w["mode"] == "instant_messaging" for w in writes)
        assert all(e["arguments"] == {"content": "same"} for e in events)
        assert 3 + len(events) == 12

    asyncio.run(run())


def test_concurrent_invocations_have_independent_depth():
    async def run():
        events = []
        observer = ToolCallbackObserver(events)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def callback(arguments):
            entered.set()
            await release.wait()
            return arguments["id"]

        wrapped = observer.wrap(callback, "tool")
        first = asyncio.create_task(wrapped({"id": 1}))
        await entered.wait()
        second = asyncio.create_task(wrapped({"id": 2}))
        await asyncio.sleep(0)
        assert len(events) == 2
        release.set()
        assert await asyncio.gather(first, second) == [1, 2]
        assert [e["result"] for e in events] == [1, 2]

    asyncio.run(run())


@pytest.mark.parametrize("error", [ValueError("failed"), asyncio.CancelledError()])
def test_error_propagates_and_observation_resumes(error):
    async def run():
        events = []
        observer = ToolCallbackObserver(events)

        async def fail(arguments):
            raise error

        inner = observer.wrap(fail, "inner")
        outer = observer.wrap(inner, "outer")
        with pytest.raises(type(error)):
            await outer({})
        assert len(events) == 1
        assert events[0]["error_type"] == type(error).__name__

        async def succeed(arguments):
            return "ok"

        assert await observer.wrap(succeed, "next")({}) == "ok"
        assert len(events) == 2
        assert events[1]["result"] == "ok"

    asyncio.run(run())
