"""Language decisions survive history reload without leaking internal raw text."""
import asyncio
import json
import sqlite3
from types import SimpleNamespace

from Backend.chat_modules.autonomous_delivery import delivery_state, configure_delivery
from Backend.chat_modules.autonomous_history import read_history
from Backend.chat_modules.reply_language_state import encode_language, decode_language


def state(rows):
    return delivery_state(rows, speaker='pony', main='pony')


def test_temporary_language_survives_database_roundtrip(tmp_path):
    db = tmp_path / 'chat.db'
    decision = {'language': 'English', 'continuation_language': 'Chinese', 'reason': 'this turn only'}
    request = SimpleNamespace(_normal_planner_result={})
    configure_delivery(request, {'envelope': json.dumps({'reply_language': decision, 'bubbles': [], 'voice_reply': {'enabled': False, 'continuation_enabled': True}})})
    raw = encode_language('Hello there', request._normal_reply_language, request._normal_reply_voice)
    with sqlite3.connect(db) as conn:
        conn.executescript('''CREATE TABLE users(id INTEGER, username TEXT);
        CREATE TABLE conversations(id TEXT,user_id INTEGER,character_id TEXT,is_hidden INTEGER);
        CREATE TABLE messages(id TEXT,message_id TEXT,conversation_id TEXT,role TEXT,content TEXT,raw_content TEXT,timestamp INTEGER,sequence_number INTEGER);
        INSERT INTO users VALUES(1,'tester');
        INSERT INTO conversations VALUES('chat',1,'pony',0);''')
        conn.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)', ('a','a','chat','assistant','Hello there',raw,1,1))
    rows = asyncio.run(read_history(db, username='tester', character_id='pony', conversation_id='chat'))
    assert rows[0]['content'] == 'Hello there'
    assert 'raw_content' not in rows[0]
    assert state(rows)['previous_reply_language'] == 'Chinese'
    assert state(rows)['voice_reply'] is True
    assert rows[0]['voice_reply']['enabled'] is False
    assert asyncio.run(read_history(db, username='other', character_id='pony', conversation_id='chat')) == []


def test_saved_french_beats_recent_symbols_or_legacy_guess():
    rows = [{'role':'assistant','content':'Bonjour','reply_language':{'language':'French','continuation_language':'French'}},
            {'role':'assistant','content':'嗯～'}]
    assert state(rows)['previous_reply_language'] == 'French'


def test_short_sounds_do_not_reset_legacy_english():
    assert state([{'role':'assistant','content':'Hello there'}, {'role':'assistant','content':'唔……嗯～'}])['previous_reply_language'] == 'English'


def test_chinese_name_does_not_override_english_prose():
    assert state([{'role':'assistant','content':'Hello 紫悦, would you like to read this book?'}])['previous_reply_language'] == 'English'


def test_unknown_latin_language_is_not_claimed_to_be_english():
    assert not state([{'role':'assistant','content':'Bonjour mon ami'}])['has_language_history']


def test_other_speaker_does_not_change_language():
    rows=[{'role':'assistant','content':'Hello there','speaker_character_id':'pony'},
          {'role':'assistant','content':'你好','speaker_character_id':'other','reply_language':{'language':'Chinese'}}]
    assert state(rows)['previous_reply_language'] == 'English'


def test_raw_reasoning_is_never_parsed_as_visible_history():
    assert decode_language('{"reasoning":"secret", "reply_language":{"language":"English"}}') is None
    assert decode_language('not json') is None


def test_missing_scope_is_backward_compatible():
    assert decode_language(encode_language('Hola', {'language':'Spanish'}))['continuation_language'] == 'Spanish'


def test_voice_temporary_text_and_failure_preserve_enabled_setting():
    rows = [{'role': 'assistant', 'content': '今天先打字', 'voice_state': {'voice_status': 'failed'},
             'voice_reply': {'enabled': False, 'continuation_enabled': True}}]
    assert state(rows)['voice_reply'] is True


def test_one_off_voice_does_not_enable_future_voice():
    rows = [{'role': 'assistant', 'content': 'Hello', 'voice_status': 'ready',
             'voice_reply': {'enabled': True, 'continuation_enabled': False}}]
    assert state(rows)['voice_reply'] is False


def test_voice_decision_roundtrip_without_language(tmp_path):
    from Backend.chat_modules.reply_language_state import decode_voice
    raw = encode_language('仅这次文字', None, {'enabled': False, 'continuation_enabled': True})
    assert decode_voice(raw) == {'enabled': False, 'continuation_enabled': True}
    assert decode_language(raw) is None
    assert decode_voice('plain legacy text') is None


def test_voice_client_gate_does_not_rewrite_continuation_setting():
    request = SimpleNamespace(_normal_planner_result={}, voice_enabled=False)
    configure_delivery(request, {'envelope': json.dumps({'reply_language': {'language': 'Chinese'},
        'voice_reply': {'enabled': True, 'continuation_enabled': True}, 'bubbles': []})})
    assert request._normal_planner_result['voice_reply']['enabled'] is False
    assert request._normal_reply_voice['continuation_enabled'] is True
