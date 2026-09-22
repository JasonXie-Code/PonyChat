"""Bounded memory retrieval, single-snapshot routing, and useful stall evidence."""
import asyncio
import sqlite3
import threading
import time

import pytest

from Backend.loop_watchdog import LoopWatchdog
from Backend.model_manager import ModelManager
from test_unified_agent_memory import db, store, stage, commit, evidence


@pytest.mark.parametrize('rank', [False, True])
@pytest.mark.parametrize('include_stale', [False, True])
def test_memory_limit_checks_only_needed_candidates(db, monkeypatch, rank, include_stale):
    s = store(db)
    for i in range(20):
        stage(s, content=f'记忆 {i}', importance=i % 10 + 1)
    commit(s)
    original = evidence.valid
    invalid = {r['entry_id'] for r in s.list(limit=3, rank_by_importance=rank)}
    calls = []
    def valid(conn, username, character, row, **kwargs):
        calls.append(row['entry_id'])
        return row['entry_id'] not in invalid and original(conn, username, character, row, **kwargs)
    monkeypatch.setattr(evidence, 'valid', valid)
    expected = s.list(limit=500, include_stale=include_stale, rank_by_importance=rank)[:2]
    assert len(calls) == 20
    calls.clear()
    assert s.list(limit=2, include_stale=include_stale, rank_by_importance=rank) == expected
    assert len(calls) == (2 if include_stale else 5)


def test_keyword_ranking_keeps_older_more_relevant_candidate(db):
    s = store(db)
    stage(s, content='绿茶 桂花 两个关键词')
    for i in range(10):
        stage(s, content=f'绿茶 {i}')
    commit(s)
    assert s.list(query='绿茶 桂花', limit=1)[0]['content'] == '绿茶 桂花 两个关键词'


@pytest.mark.parametrize('task', ['chat','normal','unused'])
def test_model_routing_loads_one_current_snapshot(task):
    manager = ModelManager.__new__(ModelManager)
    models = [{'id':'active', 'for_chat':True, 'api_key':'test'},
              {'id':'dedicated', 'for_normal':True, 'api_key':'test'}]
    calls = []
    def load():
        calls.append(True)
        return {'active_model':'active', 'models':models}
    manager._load_config = load
    assert manager.get_model_for_task(task)['id'] == ('dedicated' if task=='normal' else 'active')
    assert len(calls) == 1
    models[0]['enabled'] = False
    assert manager.get_model_for_task(task)['id'] == 'dedicated'
    assert len(calls) == 2  # updates are checked on the next public call


def test_watchdog_captures_blocking_frame_without_locals_and_throttles():
    reports, captured = [], threading.Event()
    def report(*args):
        reports.append(args)
        captured.set()
    def deliberately_block_loop():
        private_request_body = 'MUST_NOT_APPEAR_IN_LOG'
        assert captured.wait(2), private_request_body
        time.sleep(.08)
    async def scenario():
        watcher = LoopWatchdog(asyncio.get_running_loop(), report,
                               interval=.005, threshold=.02, cooldown=1).start()
        try:
            await asyncio.sleep(.025)
            assert not reports
            deliberately_block_loop()
            assert len(reports) == 1
            assert 'deliberately_block_loop' in str(reports)
            assert 'MUST_NOT_APPEAR_IN_LOG' not in str(reports)
        finally:
            watcher.stop()
            await asyncio.to_thread(watcher.thread.join, 1)
        assert not watcher.thread.is_alive()
    asyncio.run(scenario())
