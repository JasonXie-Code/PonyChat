"""Notification-driven indexing must preserve recovery, isolation and close order."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3

import aiosqlite
import pytest

from Backend import log_index_changes, utils
from test_log_index_recovery import setup, logs


@pytest.fixture
def journal(monkeypatch):
    value = log_index_changes.LogChanges()
    monkeypatch.setattr(log_index_changes, 'changes', value)
    return value


def extra(file, name):
    target = file.with_name(name + '.js')
    target.write_text(file.read_text(encoding='utf-8').replace('"test"', '"'+name+'"'), encoding='utf-8')
    return target


def test_idle_incremental_scan_has_no_disk_or_database_work(tmp_path, journal, monkeypatch):
    indexer, _ = setup(tmp_path)
    async def run():
        await indexer.init_schema()
        assert (await indexer.scan_incremental())['scan_mode'] == 'reconcile'
        def unexpected(*args, **kwargs):
            raise AssertionError('idle scan touched disk or SQLite')
        monkeypatch.setattr(indexer, '_iter_log_files', unexpected)
        monkeypatch.setattr(aiosqlite, 'connect', unexpected)
        result = await indexer.scan_incremental()
        assert result['scan_mode'] == 'changes' and result['entries_inserted'] == 0
    asyncio.run(run())


def test_notified_write_during_scan_stays_pending(tmp_path, journal, monkeypatch):
    indexer, file = setup(tmp_path)
    async def run():
        await indexer.init_schema()
        await indexer.scan_incremental()
        one = extra(file, 'one'); journal.publish(one)
        original = indexer._scan_file
        async def scan(path, **kwargs):
            result = await original(path, **kwargs)
            if Path(path).name == 'one.js':
                journal.publish(extra(file, 'two'))
            return result
        monkeypatch.setattr(indexer, '_scan_file', scan)
        assert (await indexer.scan_incremental())['entries_inserted'] == 1
        assert (await indexer.scan_incremental())['entries_inserted'] == 1
        assert (await indexer.scan_incremental())['entries_inserted'] == 0
    asyncio.run(run())


def test_failed_notification_is_retried_without_double_index(tmp_path, journal, monkeypatch):
    indexer, file = setup(tmp_path)
    async def run():
        await indexer.init_schema(); await indexer.scan_incremental()
        journal.publish(extra(file, 'retry'))
        original = indexer._save_progress
        async def broken(*args):
            raise sqlite3.OperationalError('database is locked')
        monkeypatch.setattr(indexer, '_save_progress', broken)
        assert not (await indexer.scan_incremental())['success']
        assert indexer._change_cursor == 0
        monkeypatch.setattr(indexer, '_save_progress', original)
        assert (await indexer.scan_incremental())['success']
        assert indexer._change_cursor == 1
    asyncio.run(run())
    with sqlite3.connect(indexer.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM llm_log_index').fetchone()[0] == 2


def test_overflow_reconciles_files_missing_from_journal(tmp_path, journal):
    journal.capacity = 1
    indexer, file = setup(tmp_path)
    async def run():
        await indexer.init_schema(); await indexer.scan_incremental()
        journal.publish(extra(file, 'one')); journal.publish(extra(file, 'two'))
        result = await indexer.scan_incremental()
        assert result['scan_mode'] == 'reconcile' and result['entries_inserted'] == 2
        assert (await indexer.scan_incremental())['scan_mode'] == 'changes'
    asyncio.run(run())


def test_external_write_and_restart_are_reconciled(tmp_path, journal):
    indexer, file = setup(tmp_path)
    async def run():
        await indexer.init_schema(); await indexer.scan_incremental()
        extra(file, 'external')
        assert (await indexer.scan_incremental())['entries_inserted'] == 0
        indexer._full_scan_at -= indexer._reconcile_interval
        assert (await indexer.scan_incremental())['entries_inserted'] == 1
        extra(file, 'restart')
        restored = logs.LLMLogIndexer(indexer.db_path); restored.logs_root = indexer.logs_root
        result = await restored.scan_incremental()
        assert result['scan_mode'] == 'reconcile' and result['entries_inserted'] == 1
    asyncio.run(run())


def test_other_root_notifications_do_not_index_private_files(tmp_path, journal):
    indexer, _ = setup(tmp_path)
    other, outside = setup(tmp_path / 'another')
    async def run():
        await indexer.init_schema(); await indexer.scan_incremental()
        journal.publish(outside)
        result = await indexer.scan_incremental()
        assert result['entries_inserted'] == 0 and result['files_scanned'] == 0
    asyncio.run(run())


def test_rebuild_and_incremental_scan_share_writer_lock(tmp_path, journal, monkeypatch):
    indexer, _ = setup(tmp_path)
    async def run():
        await indexer.init_schema(); await indexer.scan_incremental()
        entered, release = asyncio.Event(), asyncio.Event()
        async def rebuild():
            entered.set(); await release.wait(); return {'success':True}
        monkeypatch.setattr(indexer, '_rebuild_index_fast_locked', rebuild)
        task = asyncio.create_task(indexer.rebuild_index_fast())
        await entered.wait()
        scan = asyncio.create_task(indexer.scan_incremental())
        await asyncio.sleep(.02)
        assert not scan.done()
        release.set(); await task; assert (await scan)['success']
    asyncio.run(run())


def test_journal_is_bounded_coalesces_and_supports_independent_cursors(tmp_path):
    journal = log_index_changes.LogChanges(capacity=2)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: journal.publish(tmp_path / 'same.js'), range(100)))
    sequence, paths, overflow = journal.since(0)
    assert sequence == 100 and len(paths) == 1 and not overflow
    assert journal.since(0) == journal.since(0)
    journal.publish(tmp_path/'second.js'); journal.publish(tmp_path/'third.js')
    assert len(journal.pending) == 2 and journal.since(0)[2]
    assert journal.since(sequence)[2] is False


def test_writer_publishes_complete_file_and_failed_write_publishes_nothing(tmp_path, journal, monkeypatch):
    original = journal.publish
    def publish(path):
        assert Path(path).read_text(encoding='utf-8') == 'complete'
        original(path)
    monkeypatch.setattr(journal, 'publish', publish)
    target = tmp_path/'logs'/'file.js'
    utils._write_chat_debug_log(str(target), 'complete')
    assert journal.sequence == 1
    with pytest.raises(IsADirectoryError if __import__('os').name!='nt' else PermissionError):
        utils._write_chat_debug_log(str(target.parent), 'complete')
    assert journal.sequence == 1


def test_transient_stat_failure_keeps_notification_pending(tmp_path, journal, monkeypatch):
    indexer, file = setup(tmp_path)
    async def run():
        await indexer.init_schema(); await indexer.scan_incremental()
        target = extra(file, 'permission'); journal.publish(target)
        stat = logs.os.stat
        def broken(path, *args, **kwargs):
            if str(path) == str(target):
                raise PermissionError('temporarily unreadable')
            return stat(path, *args, **kwargs)
        monkeypatch.setattr(logs.os, 'stat', broken)
        assert not (await indexer.scan_incremental())['success']
        assert indexer._change_cursor == 0
        monkeypatch.setattr(logs.os, 'stat', stat)
        assert (await indexer.scan_incremental())['entries_inserted'] == 1
    asyncio.run(run())


def test_cancelled_waiter_does_not_lose_completed_write(tmp_path, journal, monkeypatch):
    import threading
    entered, release, written = threading.Event(), threading.Event(), threading.Event()
    original = utils._write_chat_debug_log
    def writer(path, content):
        entered.set(); assert release.wait(2)
        original(path, content); written.set()
    async def run():
        target = tmp_path/'cancelled.js'
        task = asyncio.create_task(asyncio.to_thread(writer, str(target), 'complete'))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        assert await asyncio.to_thread(written.wait, 1)
        assert journal.since(0)[1] == [str(target)]
    asyncio.run(run())
