"""Exclusive, exact-configuration SDK reuse with fresh session-scoped capabilities.

Only idle runtimes are reused. A failed/cancelled turn destroys its runtime;
system prompts, schemas, model credentials and token limits never change in it.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import weakref

_pools = weakref.WeakKeyDictionary()
DISABLED_TOOLS = ('persistent-bash', 'persistent-pwsh', 'str-replace-editor',
                  'terminal-bash', 'terminal-pwsh', 'fs-local')


def memory_allows_start(reserve_mib=224):
    """Admission based on non-reclaimable usage, without counting file cache twice."""
    try:
        relative = Path('/proc/self/cgroup').read_text().split('0::', 1)[1].strip()
        group = Path('/sys/fs/cgroup') / relative.lstrip('/')
        high = (group/'memory.high').read_text().strip()
        if high == 'max':
            return True
        stats = dict(line.split() for line in (group/'memory.stat').read_text().splitlines())
        used = int(stats['anon']) + int(stats.get('kernel', '0'))
        return used + reserve_mib*1048576 <= int(high)
    except (OSError, ValueError, KeyError, IndexError):
        return True


class Entry:
    def __init__(self, key):
        self.key = key
        from .harness_temp import scratch_parent
        self.home = tempfile.TemporaryDirectory(prefix='ponychat-harness-pool-', dir=scratch_parent())
        self.token = secrets.token_urlsafe(32)
        self.routes = {}
        self.server = None
        self.harness = None
        self.close_task = None
        self.used = 0
        self.busy = True
        self.born = self.last_used = time.monotonic()

    def alive(self):
        # The pinned SDK exposes its process through client; test doubles may not.
        client = getattr(self.harness, 'client', None)
        process = getattr(client, '_proc', None)
        return client is None or (process is not None and process.poll() is None)

    async def relay(self, reader, writer):
        upstream = None
        try:
            header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            lines = header.decode('ascii').split('\r\n')
            method, path, _ = lines[0].split(' ')
            headers = {k.lower(): v.strip() for k, v in
                       (line.split(':', 1) for line in lines[1:] if ':' in line)}
            route = self.routes.get(headers.get('x-ponychat-session', ''))
            authorized = hmac.compare_digest(headers.get('authorization', ''), 'Bearer '+self.token)
            body = None
            if not headers.get('transfer-encoding') and headers.get('content-length', '').isdigit():
                length = int(headers['content-length'])
                if 2 <= length <= 65536:
                    # Read bounded request bodies even for expired sessions;
                    # otherwise Windows can reset the socket before delivering 403.
                    body = await asyncio.wait_for(reader.readexactly(length), 5)
            if not authorized or route is None:
                writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            elif method != 'POST' or headers.get('transfer-encoding') or not headers.get('content-length', '').isdigit():
                writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            else:
                length = int(headers['content-length'])
                if not 2 <= length <= 65536 or not path.startswith('/') or '\r' in path or '\n' in path:
                    raise ValueError('Invalid bridge request')
                if body is None:
                    raise ValueError('Invalid bridge body')
                # A lease carries a trusted loopback port and a new per-turn token.
                # Neither endpoint nor account scope is supplied by model arguments.
                port, token = route
                upstream_reader, upstream = await asyncio.open_connection('127.0.0.1', port)
                upstream.write((f'POST {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {token}\r\n'
                                f'Content-Length: {length}\r\nConnection: close\r\n\r\n').encode()+body)
                await upstream.drain()
                while chunk := await upstream_reader.read(65536):
                    writer.write(chunk)
                    await writer.drain()
            await writer.drain()
        except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            pass
        finally:
            if upstream is not None:
                upstream.close()
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def _close(self):
        self.routes.clear()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        try:
            if self.harness is not None:
                await asyncio.to_thread(self.harness.close)
        finally:
            self.home.cleanup()

    async def close(self):
        if self.close_task is None:
            self.close_task = asyncio.create_task(self._close())
        await asyncio.shield(self.close_task)


class Lease:
    def __init__(self, pool, entry, port, token, reused):
        self.pool, self.entry, self.reused = pool, entry, reused
        self.session_id = 'ponychat-'+secrets.token_hex(24)
        entry.routes[self.session_id] = (port, token)
        self.harness = entry.harness

    async def release(self, healthy):
        self.entry.routes.pop(self.session_id, None)
        await self.pool.release(self.entry, healthy)


class Pool:
    def __init__(self):
        self.entries = set()
        self.spawn_lock = asyncio.Lock()
        self.reaper = asyncio.create_task(self.reap())

    async def retire(self, entry):
        self.entries.discard(entry)
        await entry.close()

    async def reap(self):
        try:
            while True:
                await asyncio.sleep(1)
                now = time.monotonic()
                for entry in list(self.entries):
                    if not entry.busy and (now-entry.last_used >= 15 or not memory_allows_start(64)):
                        await self.retire(entry)
        finally:
            await asyncio.gather(*(self.retire(entry) for entry in list(self.entries)), return_exceptions=True)

    async def acquire(self, factory, config, registered, system_prompt, max_tokens, timeout, port, token, model,
                      reasoning_effort='low'):
        # Hash credentials/prompt material in keys; never emit these keys or inputs to logs.
        options = {'model': model, 'reasoning_effort': reasoning_effort, 'max_tokens': max_tokens,
                   'api_key': config.get('api_key') or config.get('apiKey'),
                   'base_url': (config.get('base_url') or config.get('baseUrl') or config.get('endpoint') or
                                'https://api.deepseek.com').removesuffix('/chat/completions').rstrip('/')}
        from .harness_model import provider, provider_patch
        options['provider'] = provider(config)
        model_patch = provider_patch(config)
        key = (factory, hashlib.sha256(json.dumps([options, model_patch, list(registered.values()), system_prompt],
                   sort_keys=True, ensure_ascii=False).encode()).digest())
        deadline = time.monotonic()+timeout
        async with self.spawn_lock:
            for entry in list(self.entries):
                if not entry.busy and entry.key == key and entry.alive() and time.monotonic()-entry.last_used < 15:
                    entry.busy = True
                    return Lease(self, entry, port, token, True)
            # Discard incompatible idle processes before allocating another runtime.
            for entry in list(self.entries):
                if not entry.busy:
                    await self.retire(entry)
            while not memory_allows_start() and self.entries:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Harness memory admission deadline')
                await asyncio.sleep(.1)
                for entry in list(self.entries):
                    if not entry.busy:
                        if entry.key == key and entry.alive():
                            entry.busy = True
                            return Lease(self, entry, port, token, True)
                        await self.retire(entry)
            entry = Entry(key)
            self.entries.add(entry)
            try:
                entry.server = await asyncio.start_server(entry.relay, '127.0.0.1', 0, limit=8192)
                endpoint = 'http://127.0.0.1:'+str(entry.server.sockets[0].getsockname()[1])
                plugin = Path(__file__).with_name('harness_plugin')/'chat-tools.mjs'
                patch = [{'id': name, 'disabled': True} for name in DISABLED_TOOLS]
                # Match the deployed adapter: native image blocks need this store.
                patch.append({'insert': [{'id': 'attachment-local', 'name': '@deepseek-ai/dsh-attachment-local'}]})
                patch.extend(model_patch)
                patch.append({'insert': [{'id': 'ponychat-tools', 'name': plugin.resolve().as_uri(),
                    'config': {'endpoint': endpoint, 'tools': list(registered.values()), 'sessionRouting': True}}]})
                patch_path = Path(entry.home.name)/'chat.patch.yml'
                patch_path.write_text(json.dumps(patch), encoding='utf-8')
                entry.harness = factory(dsh_home=entry.home.name, cwd=entry.home.name, profile='sdk-minimal',
                    patches=(str(patch_path),), **options,
                    env={'DSH_SYSTEM_PROMPT': system_prompt, 'PONYCHAT_HARNESS_TOKEN': entry.token},
                    initialize_timeout_seconds=min(60, timeout), request_timeout_seconds=None, shutdown_timeout_seconds=1)
                # Single-file startup prevents concurrent cold starts from thrashing the page cache.
                starter = asyncio.create_task(asyncio.to_thread(entry.harness.start))
                try:
                    await asyncio.wait_for(asyncio.shield(starter), max(.001, deadline-time.monotonic()))
                except BaseException:
                    # Interrupt initialization first, then close again after its
                    # thread settles (it may have spawned just after the first close).
                    await asyncio.to_thread(entry.harness.close)
                    await asyncio.gather(starter, return_exceptions=True)
                    raise
                return Lease(self, entry, port, token, False)
            except BaseException:
                await self.retire(entry)
                raise

    async def release(self, entry, healthy):
        entry.busy = False
        entry.used += 1
        entry.last_used = time.monotonic()
        # Keep at most one warm runtime on the shared 2 GiB host. Recycling also
        # bounds retained SDK sessions and their temporary logs.
        if (not healthy or entry.used >= 16 or time.monotonic()-entry.born >= 120
                or not memory_allows_start(64)):
            await self.retire(entry)
        else:
            for other in list(self.entries):
                if other is not entry and not other.busy:
                    await self.retire(other)


async def acquire_harness(**kwargs):
    loop = asyncio.get_running_loop()
    pool = _pools.get(loop)
    if pool is None:
        pool = _pools[loop] = Pool()
    return await asyncio.wait_for(pool.acquire(**kwargs), kwargs['timeout'])
