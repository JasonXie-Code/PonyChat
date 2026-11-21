"""Bound SDK child processes on small servers, including cancellation-safe waiting."""
import asyncio
import os
import weakref
from contextlib import asynccontextmanager

_gates=weakref.WeakKeyDictionary()


@asynccontextmanager
async def harness_slot(timeout_seconds):
    loop=asyncio.get_running_loop()
    gate=_gates.get(loop)
    if gate is None:
        try:limit=max(1,min(20,int(os.getenv('PONYCHAT_HARNESS_CONCURRENCY','1'))))
        except ValueError:limit=1
        gate=asyncio.Semaphore(limit)
        _gates[loop]=gate
    await asyncio.wait_for(gate.acquire(),timeout=timeout_seconds)
    try:
        yield
    finally:
        gate.release()
