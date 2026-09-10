"""Incremental indexing, retry after lock errors, and concurrent scan safety."""
import asyncio
import json
import sqlite3
from datetime import datetime, timedelta

import aiosqlite
import pytest

from Backend.routes.admin import llm_log_indexer as logs


def setup(tmp_path, *, old=False):
    root = tmp_path / 'logs'
    now = datetime.now() - timedelta(hours=3 if old else 0)
    file = root / now.strftime('%Y-%m-%d/%H') / 'sample.js'
    file.parent.mkdir(parents=True)
    file.write_text('const debug_log = '+json.dumps({'timestamp':now.isoformat(), 'model':'test',
        'stage':'AGENT_RUN_RESPONSE', 'params':{'trace_id':'test'},
        'data':{'status':'success','usage':{'prompt_tokens':7}}})+';', encoding='utf-8')
    indexer = logs.LLMLogIndexer(str(tmp_path / 'index.sqlite'))
    indexer.logs_root = str(root)
    return indexer, file


@pytest.mark.parametrize('old', [False, True])
def test_unchanged_files_skip_parsing_and_per_file_connections(tmp_path, monkeypatch, old):
    indexer, file = setup(tmp_path, old=old)
    async def scenario():
        await indexer.init_schema()
        assert (await indexer.scan_all())['entries_inserted'] == 1
        # A fresh indexer proves that the fast path survives process restarts.
        restored = logs.LLMLogIndexer(indexer.db_path)
        restored.logs_root = indexer.logs_root
        def unexpected(*_):
            raise AssertionError('unchanged file parsed again')
        monkeypatch.setattr(logs, '_parse_log_file', unexpected)
        connect = aiosqlite.connect
        connections = []
        def tracked(*args, **kwargs):
            connections.append(args)
            return connect(*args, **kwargs)
        monkeypatch.setattr(aiosqlite, 'connect', tracked)
        result = await restored.scan_all()
        assert result['success'] and result['files_skipped'] == 1
        assert len(connections) == 1
    asyncio.run(scenario())


def test_failed_historical_insert_remains_retryable(tmp_path, monkeypatch):
    indexer, file = setup(tmp_path, old=True)
    insert = indexer._insert_entries
    async def blocked(_):
        return 0, 1
    async def scenario():
        await indexer.init_schema()
        monkeypatch.setattr(indexer, '_insert_entries', blocked)
        result = await indexer.scan_all()
        assert not result['success'] and result['status'] == 'partial'
        assert (await indexer._get_progress(str(file)))[0] == 0
        monkeypatch.setattr(indexer, '_insert_entries', insert)
        assert (await indexer.scan_all())['entries_inserted'] == 1
        assert (await indexer.scan_all())['entries_inserted'] == 0
    asyncio.run(scenario())


def test_progress_lock_failure_does_not_duplicate_tokens_on_retry(tmp_path, monkeypatch):
    indexer, file = setup(tmp_path)
    save = indexer._save_progress
    async def blocked(*_):
        raise sqlite3.OperationalError('database is locked')
    async def scenario():
        await indexer.init_schema()
        monkeypatch.setattr(indexer, '_save_progress', blocked)
        assert not (await indexer.scan_all())['success']
        monkeypatch.setattr(indexer, '_save_progress', save)
        assert (await indexer.scan_all())['success']
    asyncio.run(scenario())
    with sqlite3.connect(indexer.db_path) as conn:
        assert conn.execute('SELECT COUNT(*),SUM(prompt_tokens) FROM llm_log_index').fetchone() == (1, 7)


def test_overlapping_scans_do_not_insert_twice(tmp_path):
    indexer, _ = setup(tmp_path)
    async def scenario():
        await indexer.init_schema()
        results = await asyncio.gather(indexer.scan_all(), indexer.scan_all())
        assert sum(r['entries_inserted'] for r in results) == 1
    asyncio.run(scenario())


def test_partial_log_is_retried_after_writer_finishes(tmp_path):
    indexer, file = setup(tmp_path)
    complete = file.read_text(encoding='utf-8')
    file.write_text('const debug_log = {', encoding='utf-8')
    async def scenario():
        await indexer.init_schema()
        assert not (await indexer.scan_all())['success']
        file.write_text(complete, encoding='utf-8')
        assert (await indexer.scan_all())['entries_inserted'] == 1
    asyncio.run(scenario())


def test_old_failed_progress_is_repaired_even_after_hour_rollover(tmp_path):
    indexer, file = setup(tmp_path, old=True)
    async def scenario():
        await indexer.init_schema()
        stat = file.stat()
        # Previous releases advanced the offset even when insertion failed.
        await indexer._save_progress(str(file), stat.st_size, stat.st_mtime, stat.st_size, 0, 1)
        result = await indexer.scan_all()
        assert result['success'] and result['entries_inserted'] == 1
        assert (await indexer.scan_all())['entries_inserted'] == 0
    asyncio.run(scenario())


def test_template_parser_preserves_backticks_inside_quoted_sdk_chunks():
    from Backend.utils import _to_js_literal
    data = {'prompt':'first line\nsecond line',
            'chunks':['`', '```', '\\`"', '${not_code}', 'normal'],
            'tail':{'status':'success'}}
    assert logs._loads_debug_log_literal(_to_js_literal(data)) == data
