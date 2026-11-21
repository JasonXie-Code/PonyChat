import asyncio
import json
import sqlite3
import time
from Backend.chat_modules import provider_service_status as service


def test_notice_is_atomic_deduplicated_and_reaches_all_users(tmp_path):
    path = tmp_path / 'notices.sqlite'
    with sqlite3.connect(path) as conn:
        conn.executescript('CREATE TABLE users(id INTEGER,username TEXT);'
            'INSERT INTO users VALUES(1,"alice"),(2,"bob");'
            'CREATE TABLE message_outbox(id TEXT,user_id INTEGER,msg_type TEXT,payload_json TEXT,'
            'created_at REAL,delivered_at REAL,retry_count INTEGER);')
    failed = service.transition(path, True, time.time()-31)
    assert {u for u, _ in failed} == {'alice', 'bob'}
    assert not service.transition(path, True, time.time()-31)
    assert not service.transition(path, False, time.time()-32)
    recovered = service.transition(path, False, time.time()+1)
    assert len(recovered) == 2
    with sqlite3.connect(path) as conn:
        pending = conn.execute('SELECT payload_json FROM message_outbox WHERE delivered_at IS NULL').fetchall()
        assert len(pending) == 2
        assert all(json.loads(r[0])['state'] == 'recovered' for r in pending)


def test_timer_measures_one_model_call_and_ignores_tool_time():
    async def scenario():
        events = []
        async def publish(unavailable, started):
            events.append(unavailable)
        monitor = service.DeepSeekCallMonitor(publisher=publish, threshold=.03)
        monitor.event('step/start', {'turn':1,'step':1})
        monitor.event('assistant/message', {'turn':1,'step':1})
        await asyncio.sleep(.05)  # Tool execution after the model response is not API time.
        assert True not in events
        monitor.event('step/start', {'turn':1,'step':2})
        await asyncio.sleep(.05)
        assert events.count(True) == 1
        await monitor.close()
        await asyncio.sleep(.05)
        assert events.count(True) == 1
    asyncio.run(scenario())


def test_cancel_and_local_model_do_not_emit_faults():
    async def scenario():
        calls = []
        async def publish(*args):calls.append(args)
        local = service.DeepSeekCallMonitor(False, publisher=publish, threshold=.01)
        local.observe('step/start', {'turn':1,'step':1})
        remote = service.DeepSeekCallMonitor(publisher=publish, threshold=.01)
        remote.event('step/start', {'turn':1,'step':1})
        await remote.close()
        await asyncio.sleep(.03)
        await local.close()
        assert calls == []
    asyncio.run(scenario())
