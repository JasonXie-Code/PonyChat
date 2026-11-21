"""Exact-key process reuse must not reuse session history or capability scope."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import threading
import types
import urllib.error
import urllib.request

import pytest

package = types.ModuleType('pooled_harness_under_test')
package.__path__ = [str(Path(__file__).parents[1]/'chat_modules')]
sys.modules[package.__name__] = package
runtime = importlib.import_module(package.__name__+'.harness_runtime')
pool = importlib.import_module(package.__name__+'.harness_pool')


class FakeHarness:
    instances = []

    def __init__(self, **config):
        self.config = config
        self.sessions = []
        self.closed = False
        self.instances.append(self)

    def start(self):
        pass

    def request(self, session, name='read_value', body=b'{}'):
        patch = json.loads(Path(self.config['patches'][0]).read_text())[-1]['insert'][0]['config']
        request = urllib.request.Request(patch['endpoint']+'/'+name, data=body,
            headers={'Authorization': 'Bearer '+self.config['env']['PONYCHAT_HARNESS_TOKEN'],
                     'X-PonyChat-Session': session})
        return json.load(urllib.request.urlopen(request, timeout=3))

    def run(self, prompt, session_id, on_notification=None):
        if self.sessions:
            with pytest.raises(urllib.error.HTTPError) as error:
                self.request(self.sessions[-1])
            assert error.value.code == 403
        self.sessions.append(session_id)
        value = self.request(session_id)['value']
        return types.SimpleNamespace(final_response=value, finish_reason='completed', events=[])

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def configure(monkeypatch):
    FakeHarness.instances = []
    monkeypatch.setenv('PONYCHAT_HARNESS_POOL', '1')
    monkeypatch.setenv('PONYCHAT_HARNESS_CONCURRENCY', '4')
    monkeypatch.setenv('PONYCHAT_HARNESS_MAX_IDLE', '1')
    monkeypatch.setattr(pool, 'memory_allows_start', lambda *args: True)
    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=FakeHarness))


def test_longer_idle_and_two_configurations_keep_primary_runtime(monkeypatch):
    monkeypatch.setenv('PONYCHAT_HARNESS_MAX_IDLE', '2')
    async def callback(): return 'fresh-account-scope'
    async def scenario():
        await runtime.run_harness_turn('first', {}, {'read_value': callback}, system_prompt='primary')
        await runtime.run_harness_turn('repair', {}, {'read_value': callback}, system_prompt='repair')
        owner = pool._pools[asyncio.get_running_loop()]
        for entry in owner.entries:
            entry.last_used -= 30
        result = await runtime.run_harness_turn('next', {}, {'read_value': callback}, system_prompt='primary')
        assert result['runtime_reused'] and result['final_response'] == 'fresh-account-scope'
        assert len(FakeHarness.instances) == 2
    asyncio.run(scenario())
    assert all(h.closed for h in FakeHarness.instances)


def test_fresh_session_and_callback_on_reuse():
    async def scenario():
        async def first(): return 'first-account'
        async def second(): return 'second-account'
        a = await runtime.run_harness_turn('one', {}, {'read_value': first}, max_tool_calls=1)
        b = await runtime.run_harness_turn('two', {}, {'read_value': second}, max_tool_calls=1)
        assert (a['final_response'], b['final_response']) == ('first-account', 'second-account')
        assert a['runtime_reused'] is False and b['runtime_reused'] is True
        assert a['tool_call_count'] == b['tool_call_count'] == 1
        assert len(FakeHarness.instances) == 1
        assert len(set(FakeHarness.instances[0].sessions)) == 2
    asyncio.run(scenario())
    assert all(instance.closed for instance in FakeHarness.instances)
    assert all(not Path(instance.config['dsh_home']).exists() for instance in FakeHarness.instances)


@pytest.mark.parametrize('changed', ['system_prompt', 'max_tokens', 'credentials', 'schema', 'reasoning_effort'])
def test_changed_configuration_never_reuses_runtime(changed):
    async def callback(): return 'ok'
    async def scenario():
        await runtime.run_harness_turn('one', {}, {'read_value': callback})
        options = {'system_prompt': 'different'} if changed == 'system_prompt' else (
            {'max_tokens': 100} if changed == 'max_tokens' else {})
        if changed == 'reasoning_effort':
            options['reasoning_effort'] = 'high'
        config = {'api_key': 'other-key'} if changed == 'credentials' else {}
        tools = {'read_value': callback}
        if changed == 'schema':
            tools = {'read_value': runtime.HarnessTool(lambda args: callback(), 'different description', {'type': 'object'})}
        result = await runtime.run_harness_turn('two', config, tools, **options)
        if changed == 'reasoning_effort':
            assert result['runtime_reused'] is True
            assert len(FakeHarness.instances) == 1
            assert FakeHarness.instances[0].config['reasoning_effort'] == 'low'
            assert result['reasoning_effort'] == 'low'
            return
        assert result['runtime_reused'] is False
        assert len(FakeHarness.instances) == 2 and FakeHarness.instances[0].closed
        assert all(instance.config['model'] == 'deepseek-flash' for instance in FakeHarness.instances)
        assert result['model'] == 'deepseek-flash'
    asyncio.run(scenario())


@pytest.mark.parametrize('cancel', [False, True])
def test_timeout_or_cancel_destroys_only_its_runtime(monkeypatch, cancel):
    released = threading.Event()
    started = threading.Event()
    class Blocking(FakeHarness):
        def run(self, *args, **kwargs):
            started.set()
            released.wait(3)
            raise RuntimeError('closed')
        def close(self):
            super().close()
            released.set()
    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Blocking))
    async def scenario():
        task = asyncio.create_task(runtime.run_harness_turn('one', {}, {}, timeout_seconds=2 if cancel else .3))
        if cancel:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else asyncio.TimeoutError):
            await task
    asyncio.run(scenario())
    assert released.is_set() and all(item.closed for item in FakeHarness.instances)


def test_memory_admission_queues_and_reuses_finished_runtime(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    class Busy(FakeHarness):
        def run(self, *args, **kwargs):
            entered.set()
            release.wait(2)
            return super().run(*args, **kwargs)
    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Busy))
    monkeypatch.setattr(pool, 'memory_allows_start', lambda reserve=224: reserve < 224 or not FakeHarness.instances)
    async def callback(): return 'ok'
    async def scenario():
        a = asyncio.create_task(runtime.run_harness_turn('one', {}, {'read_value': callback}))
        await asyncio.to_thread(entered.wait, 1)
        b = asyncio.create_task(runtime.run_harness_turn('two', {}, {'read_value': callback}))
        await asyncio.sleep(.04)
        assert len(FakeHarness.instances) == 1 and not b.done()
        release.set()
        results = await asyncio.gather(a, b)
        assert results[1]['runtime_reused']
    asyncio.run(scenario())


def test_native_images_reach_reused_sdk_without_transformation(monkeypatch):
    blocks = [{'type': 'text', 'text': 'image'}, {'type': 'image', 'mediaType': 'image/png', 'data': 'cG5n'}]
    class Images(FakeHarness):
        def run(self, prompt, **kwargs):
            assert prompt is blocks
            return super().run(prompt, **kwargs)
    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=Images))
    async def callback(): return 'image-result'
    async def scenario():
        for _ in range(2):
            result = await runtime.run_harness_turn(blocks, {}, {'read_value': callback})
            assert result['final_response'] == 'image-result'
    asyncio.run(scenario())


def test_cancelled_lease_cannot_close_other_active_account():
    async def scenario():
        entered_a, entered_b, finish_b = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def first():
            entered_a.set()
            await asyncio.Event().wait()
        async def second():
            entered_b.set()
            await finish_b.wait()
            return 'unaffected-account'
        a = asyncio.create_task(runtime.run_harness_turn('a', {}, {'read_value': first}))
        b = asyncio.create_task(runtime.run_harness_turn('b', {}, {'read_value': second}))
        await asyncio.wait_for(asyncio.gather(entered_a.wait(), entered_b.wait()), 2)
        assert len(FakeHarness.instances) == 2
        a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await a
        assert not b.done()
        finish_b.set()
        assert (await b)['final_response'] == 'unaffected-account'
    asyncio.run(scenario())


def test_expired_entry_is_not_reused(monkeypatch):
    monkeypatch.setenv('PONYCHAT_HARNESS_IDLE_SECONDS', '15')
    async def callback(): return 'ok'
    async def scenario():
        await runtime.run_harness_turn('one', {}, {'read_value': callback})
        current = pool._pools[asyncio.get_running_loop()]
        entry = next(iter(current.entries))
        entry.last_used -= current.idle_seconds + 5
        result = await runtime.run_harness_turn('two', {}, {'read_value': callback})
        assert not result['runtime_reused'] and FakeHarness.instances[0].closed
    asyncio.run(scenario())


def test_default_idle_has_no_time_expiry():
    async def callback(): return 'fresh scope'
    async def scenario():
        await runtime.run_harness_turn('one', {}, {'read_value': callback})
        owner = pool._pools[asyncio.get_running_loop()]
        assert owner.idle_seconds == 0
        entry = next(iter(owner.entries))
        entry.last_used -= 7200
        entry.born -= 7200
        result = await runtime.run_harness_turn('two', {}, {'read_value': callback})
        assert result['runtime_reused'] and not FakeHarness.instances[0].closed
        entry.used = 15
        await runtime.run_harness_turn('last retained session', {}, {'read_value': callback})
        assert FakeHarness.instances[0].closed
        result = await runtime.run_harness_turn('new runtime', {}, {'read_value': callback})
        assert not result['runtime_reused']
    asyncio.run(scenario())


@pytest.mark.parametrize('high', ['600000000', 'max'])
def test_memory_admission_counts_scratch_tmpfs_memory(monkeypatch, high):
    files = {'/proc/self/cgroup': '0::/test\n', '/sys/fs/cgroup/test/memory.high': high,
        '/sys/fs/cgroup/test/memory.max': '600000000',
        '/sys/fs/cgroup/test/memory.stat': 'anon 300000000\nkernel 20000000\nshmem 100000000\nfile 200000000\n'}
    class FakePath:
        def __init__(self, path): self.path = str(path)
        def __truediv__(self, other): return FakePath(self.path + '/' + str(other))
        def read_text(self): return files[self.path]
    monkeypatch.setattr(pool, 'Path', FakePath)
    # Restore the real function hidden by the isolation fixture.
    source = Path(__file__).parents[1] / 'chat_modules/harness_pool.py'
    isolated = types.ModuleType('memory_admission_test')
    exec(compile(source.read_text(encoding='utf-8'), str(source), 'exec'), isolated.__dict__)
    isolated.Path = FakePath
    assert not isolated.memory_allows_start(224)
    assert isolated.memory_allows_start(64)


def test_dead_idle_runtime_is_replaced_before_next_account():
    async def callback(): return 'ok'
    async def scenario():
        await runtime.run_harness_turn('one', {}, {'read_value': callback})
        FakeHarness.instances[0].client = types.SimpleNamespace(_proc=types.SimpleNamespace(poll=lambda: 1))
        result = await runtime.run_harness_turn('two', {}, {'read_value': callback})
        assert not result['runtime_reused']
        assert len(FakeHarness.instances) == 2 and FakeHarness.instances[0].closed
    asyncio.run(scenario())


def test_unbounded_delivery_pool_initializes_without_deadline(monkeypatch):
    class DeliveryHarness(FakeHarness):
        def run(self, *args, **kwargs):
            assert self.config['request_timeout_seconds'] is None
            return types.SimpleNamespace(final_response='done', finish_reason='completed', events=[])
    monkeypatch.setitem(sys.modules, 'deepseek_harness', types.SimpleNamespace(DeepSeekHarness=DeliveryHarness))
    async def scenario():
        result = await runtime.run_harness_turn('hi', {}, {}, timeout_seconds=None,
            delivery_only=True, delivery_timeout_seconds=None)
        assert result['final_response'] == 'done'
        for current in list(pool._pools.values()):
            for entry in list(current.entries): await current.retire(entry)
    asyncio.run(scenario())
