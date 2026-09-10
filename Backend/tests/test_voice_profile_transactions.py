"""Voice writes must participate in the administrator's existing transaction."""
import asyncio
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
import pytest

from Backend import character_voice_registration as voice


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / 'voice.sqlite'
    schema = (Path(__file__).parents[1] / 'db/database_impl/schema.py').read_text(encoding='utf-8')
    with sqlite3.connect(path) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT)')
        conn.execute("INSERT INTO users VALUES(1,'System')")
        for table in ('character_voice_assets', 'character_voice_profiles'):
            conn.executescript(re.search(r'CREATE TABLE IF NOT EXISTS '+table+r'\s*\([\s\S]+?\);', schema)[0])
        conn.execute("INSERT INTO character_voice_assets(filename,user_id,data,transcript) VALUES('sample.mp3',1,?,?)",
                     (b'test-audio', 'reference text'))
    async def user_id(_):
        return 1
    async def register(**_):
        return SimpleNamespace(raw_voice_id='test-design')
    monkeypatch.setattr(voice, 'is_voice_feature_enabled', lambda: True)
    monkeypatch.setattr(voice, 'register_qwen3tts_design_voice', register)
    return SimpleNamespace(db_path=str(path), get_user_id=user_id)


@pytest.mark.parametrize('mode', ['instruct', 'clone'])
@pytest.mark.parametrize('commit', [False, True])
def test_existing_write_transaction_saves_or_rolls_back_voice_atomically(database, mode, commit):
    char = {'id':'test-role', 'name':'Test', 'voiceSourceMode':mode, 'voiceInstruct':'calm voice',
            'voiceCloneError':'OperationalError:database is locked',
            'voice_clone_error':'OperationalError:database is locked',
            'voiceReferenceAudioUrl':'/assets/sample.mp3', 'voiceReferenceText':'reference text'}
    async def scenario():
        async with aiosqlite.connect(database.db_path) as conn:
            await conn.execute('BEGIN IMMEDIATE')
            # An uncommitted user must be visible through the borrowed connection.
            await conn.execute("UPDATE users SET username='Editor' WHERE id=1")
            updated = await asyncio.wait_for(voice.ensure_character_voice_registered(
                database, username='Editor', char=char, connection=conn), 2)
            assert updated['voiceCloneStatus'] in ('recipe_ready', 'design_registered')
            assert updated['voiceCloneError'] == updated['voice_clone_error'] == ''
            assert conn.in_transaction
            async with conn.execute('SELECT user_id FROM character_voice_profiles') as cursor:
                assert (await cursor.fetchone())[0] == 1
            # Nested helpers must not commit the caller's pending writes.
            with sqlite3.connect(database.db_path) as other:
                assert other.execute('SELECT COUNT(*) FROM character_voice_profiles').fetchone()[0] == 0
            await (conn.commit() if commit else conn.rollback())
    asyncio.run(scenario())
    with sqlite3.connect(database.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM character_voice_profiles').fetchone()[0] == int(commit)
        assert conn.execute('SELECT voice_profile_id FROM character_voice_assets').fetchone()[0] == (
            'ponyvoice:test-role' if commit and mode == 'clone' else None)


def test_standalone_clone_still_commits_profile_and_asset(database):
    result = asyncio.run(voice.ensure_character_voice_registered(database, username='System', char={
        'id':'standalone', 'voiceSourceMode':'clone', 'voiceReferenceAudioUrl':'/sample.mp3',
        'voiceReferenceText':'reference text'}))
    assert result['voiceCloneStatus'] == 'recipe_ready'
    with sqlite3.connect(database.db_path) as conn:
        assert conn.execute('SELECT voice_profile_id FROM character_voice_assets').fetchone()[0] == 'ponyvoice:standalone'
        assert conn.execute('SELECT COUNT(*) FROM character_voice_profiles').fetchone()[0] == 1
