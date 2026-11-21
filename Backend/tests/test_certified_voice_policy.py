import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from Backend.certified_voice_policy import (
    character_supports_voice, require_voice_administrator, strip_voice_settings,
)
from Backend.scripts.remove_uncertified_voices import clean_database


@pytest.fixture
def voice_db(tmp_path):
    path = tmp_path / 'voice.db'
    with sqlite3.connect(path) as conn:
        conn.executescript('''
            CREATE TABLE users(id INTEGER,username TEXT);
            INSERT INTO users VALUES(1,'System'),(2,'ordinary');
            CREATE TABLE characters(id TEXT,user_id INTEGER,data TEXT,official_source_id TEXT);
            CREATE TABLE hall_characters(id TEXT,publisher_username TEXT,data TEXT);
            CREATE TABLE character_voice_profiles(voice_profile_id TEXT,character_id TEXT,qwen_voice_id TEXT,qwen_cached_voice_id TEXT);
            CREATE TABLE character_voice_assets(filename TEXT,character_id TEXT,voice_profile_id TEXT);
            CREATE TABLE conversations(id TEXT,character_id TEXT);
            CREATE TABLE messages(conversation_id TEXT,message_id TEXT,speaker_character_id TEXT,content TEXT);
            CREATE TABLE message_voice_states(conversation_id TEXT,message_id TEXT);
            CREATE TABLE message_voice_audio_cache(voice_cache_key TEXT,character_id TEXT);
            INSERT INTO hall_characters VALUES('hall-system','System','{}'),('hall-user','ordinary','{}');
            INSERT INTO conversations VALUES('normal-conv','custom'),('certified-conv','source');
            INSERT INTO messages VALUES('normal-conv','normal-msg','','keep text'),('normal-conv','guest-msg','source','keep certified guest');
            INSERT INTO message_voice_states VALUES('normal-conv','normal-msg'),('normal-conv','guest-msg');
            INSERT INTO message_voice_audio_cache VALUES('normal-audio','custom'),('certified-audio','source');
            INSERT INTO character_voice_profiles VALUES('shared','source','qwen3tts:source-voice',''),('custom-profile','custom','qwen3tts:custom-voice','');
            INSERT INTO character_voice_assets VALUES('keep.wav','reference','shared'),('delete.wav','custom','custom-profile');
        ''')
        for cid, owner, source, data in (
            ('source', 1, None, {'voiceId':'shared'}),
            ('reference', 2, 'source', {'voiceId':'shared'}),
            ('custom', 2, None, {'voiceEnabled':True,'voiceId':'custom-profile','owner':'System','isOfficialReference':True}),
            ('hall-reference', 2, None, {'sourceId':'hall-system'}),
            ('user-hall-reference', 2, None, {'sourceId':'hall-user'}),
        ):
            conn.execute('INSERT INTO characters VALUES(?,?,?,?)', (cid,owner,json.dumps(data),source))
    return SimpleNamespace(db_path=str(path))


def test_database_ownership_not_spoofed_client_flags(voice_db):
    for cid in ('source','reference','hall-reference'):
        assert character_supports_voice('ordinary',cid,db=voice_db)
    for cid in ('custom','user-hall-reference','missing'):
        assert not character_supports_voice('ordinary',cid,db=voice_db)


def test_cleanup_preserves_certified_guest_audio_and_all_text(voice_db, tmp_path):
    result = clean_database(voice_db.db_path, str(tmp_path/'backup.db'))
    assert result['voice_profiles_deleted'] == 1
    assert result['voice_assets_deleted'] == 1
    assert result['voice_states_deleted'] == 1
    assert result['audio_cache_deleted'] == 1
    assert result['removed_renderer_ids'] == ['custom-voice']
    with sqlite3.connect(voice_db.db_path) as conn:
        assert conn.execute('SELECT content FROM messages').fetchall() == [('keep text',),('keep certified guest',)]
        assert conn.execute('SELECT message_id FROM message_voice_states').fetchall() == [('guest-msg',)]
        data = json.loads(conn.execute("SELECT data FROM characters WHERE id='custom'").fetchone()[0])
        assert data['voiceEnabled'] is False and 'voiceId' not in data
    assert clean_database(voice_db.db_path)['voice_profiles_deleted'] == 0


def test_non_admin_cannot_create_tones():
    require_voice_administrator('System')
    with pytest.raises(HTTPException) as denied:
        require_voice_administrator('ordinary')
    assert denied.value.status_code == 403


def test_old_client_cannot_force_voice_or_read_audio(monkeypatch):
    from Backend.chat_modules import voice_messages
    from Backend import certified_voice_policy
    monkeypatch.setattr(certified_voice_policy,'character_supports_voice',lambda *a,**kw:False)
    async def scenario():
        result = await voice_messages.synthesize_message_voice(username='ordinary',character_id='custom',
            conversation_id='conv',message_id='msg',content='hello',voice_id='qwen3tts:source',persist=False)
        assert result['audio_transfer'] is None
        assert result['error'] == 'character_voice_unavailable'
        assert await voice_messages.get_cached_message_voice_audio(username='ordinary',character_id='custom',
            conversation_id='conv',message_id='msg') is None
    asyncio.run(scenario())


def test_saved_custom_voice_recipe_is_removed_before_any_registration(monkeypatch):
    from Backend.character_voice_registration import ensure_character_voice_registered
    char = {'id':'custom','name':'Keep me','voiceSourceMode':'instruct','voiceInstruct':'design now','voiceId':'old'}
    result = asyncio.run(ensure_character_voice_registered(None,username='ordinary',char=char))
    assert result == strip_voice_settings(char)
    assert result['name'] == 'Keep me'
