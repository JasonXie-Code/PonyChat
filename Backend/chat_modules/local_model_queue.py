"""Serialize local inference; queued waiting is separate from execution deadlines."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from urllib.parse import urlparse
import weakref

_gates = weakref.WeakKeyDictionary()
_held = ContextVar('local_model_queue_held', default=frozenset())


def local_endpoint(config):
    if isinstance(config, str):
        endpoint = config
    else:
        endpoint = str((config or {}).get('endpoint') or (config or {}).get('base_url') or '')
    parsed = urlparse(endpoint)
    if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.port != 8072:
        return None
    return 'gemma-local:8072'


@asynccontextmanager
async def local_model_slot(config):
    key = local_endpoint(config)
    if key is None or key in _held.get():
        yield
        return
    loop = asyncio.get_running_loop()
    gates = _gates.setdefault(loop, {})
    gate = gates.setdefault(key, asyncio.Semaphore(1))
    # asyncio's semaphore queues waiters in FIFO order and removes cancelled ones.
    await gate.acquire()
    token = _held.set(_held.get() | {key})
    try:
        yield
    finally:
        _held.reset(token)
        gate.release()


def queued_local_turn(function):
    @wraps(function)
    async def run(prompt, model_config, *args, **kwargs):
        async with local_model_slot(model_config):
            return await function(prompt, model_config, *args, **kwargs)
    return run


def queued_local_stream(function):
    @wraps(function)
    async def run(payload, model_cfg, *args, **kwargs):
        async with local_model_slot(model_cfg):
            stream = function(payload, model_cfg, *args, **kwargs)
            try:
                async for part in stream:
                    yield part
            finally:
                await stream.aclose()
    return run
