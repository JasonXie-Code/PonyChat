"""Guest evidence windows, revocation, queueing and account isolation."""
import sqlite3
from types import SimpleNamespace

from test_autonomous_upgrade_integration import database
from Backend.agent_memory.participants import share_reply_experience_on_connection, read_group_experience, read_sources


def test_group_window_grants_eight_before_and_two_after_without_opening_the_conversation(database):
    with sqlite3.connect(database.db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("DELETE FROM messages")
        seq = 0
        def put(mid, role, speaker=None):
            nonlocal seq
            seq += 1
            conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number,speaker_character_id) "
                         "VALUES(?,?,'c1',?,?,?,?,?)", (mid, mid, role, mid, seq, seq, speaker))
            if role == 'assistant':
                share_reply_experience_on_connection(conn, SimpleNamespace(username='alice', character_id='twilight',
                    conversation_id='c1', memory_enabled=True, _normal_speaker_character_id=speaker,
                    _autonomous_pending_reply_message_ids=[mid]))
        for index in range(9): put('before' + str(index), 'user')
        put('guest1', 'assistant', 'pinkie')
        put('guest2', 'assistant', 'pinkie')
        put('after1a', 'assistant', 'twilight')
        put('after1b', 'assistant', 'twilight')
        put('after2', 'user')
        put('outside3', 'assistant', 'twilight')
        # A user-only save has no Agent commit hook; let the existing guest
        # transaction boundary authorize the visible second following utterance.
        share_reply_experience_on_connection(conn, SimpleNamespace(username='alice', character_id='twilight',
            conversation_id='c1', memory_enabled=True, _normal_speaker_character_id='twilight',
            _autonomous_pending_reply_message_ids=['outside3']))
        conn.commit()
    rows = read_group_experience(database.db_path, username='alice', character_id='pinkie', limit=40)
    ids = {r['message_id'] for r in rows}
    assert 'before0' not in ids
    assert {f'before{i}' for i in range(1, 9)} <= ids
    assert {'guest1', 'guest2', 'after1a', 'after1b', 'after2'} <= ids
    assert 'outside3' not in ids
    assert read_group_experience(database.db_path, username='alice', character_id='outsider') == []
    assert read_group_experience(database.db_path, username='bob', character_id='pinkie') == []
    assert read_sources(database.db_path, username='alice', character_id='pinkie', message_ids=['outside3']) == []
    assert read_group_experience(database.db_path, username='alice', character_id='pinkie',
                                 before_message_id='before0') == []
    with sqlite3.connect(database.db_path) as conn:
        queued = conn.execute("SELECT revision,reviewed_revision,activated,due_at FROM agent_memory_state "
                              "WHERE username='alice' AND character_id='pinkie'").fetchone()
        assert queued[0] > queued[1] and queued[2] == 1 and queued[3] > 0
        conn.execute("UPDATE messages SET is_hidden=1 WHERE message_id='guest1'")
        conn.execute("UPDATE messages SET deleted_at=1 WHERE message_id='guest2'")
    assert not ({'guest1', 'guest2'} & {r['message_id'] for r in read_group_experience(
        database.db_path, username='alice', character_id='pinkie', limit=40)})
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("UPDATE conversations SET is_hidden=1 WHERE id='c1'")
    assert read_group_experience(database.db_path, username='alice', character_id='pinkie') == []
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("UPDATE conversations SET is_hidden=0 WHERE id='c1'")
        conn.execute("UPDATE agent_memory_state SET epoch=epoch+1 WHERE username='alice' AND character_id='pinkie'")
        conn.row_factory = sqlite3.Row
        share_reply_experience_on_connection(conn, SimpleNamespace(username='alice', character_id='twilight',
            conversation_id='c1', memory_enabled=True, _normal_speaker_character_id='twilight',
            _autonomous_pending_reply_message_ids=['outside3']))
    assert read_group_experience(database.db_path, username='alice', character_id='pinkie') == []


def test_guest_image_catalog_and_neighbors_stay_inside_shared_scene(database):
    from Backend.chat_modules.history_image_tools import HistoryImageTools
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp) "
                     "VALUES('secret','secret','c1','user','窗口外的秘密',1)")
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp) "
                     "VALUES('later','later','c1','user','窗口后的秘密',2000)")
    images = HistoryImageTools(database.db_path, username='alice', character_id='twilight',
                                conversation_id='c1', allowed_message_ids=['m1'])
    assert images._rows(['secret', 'later']) == []
    assert images._rows(['m1'])[0]['context'] == {'before': [], 'after': []}


def test_guest_experience_grants_roll_back_with_failed_reply(database):
    conn = sqlite3.connect(database.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,speaker_character_id) "
                 "VALUES('guest','guest','c1','assistant','参加了',2000,'pinkie')")
    share_reply_experience_on_connection(conn, SimpleNamespace(username='alice', character_id='twilight',
        conversation_id='c1', _normal_speaker_character_id='pinkie', _autonomous_pending_reply_message_ids=['guest']))
    conn.rollback()
    conn.close()
    assert read_group_experience(database.db_path, username='alice', character_id='pinkie') == []
    with sqlite3.connect(database.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM agent_memory_group_turns').fetchone()[0] == 0


def test_reset_then_reinvite_cannot_use_old_self_utterance_to_expand_the_new_window(database):
    from Backend.agent_memory.participants import grant_turn
    from Backend.agent_memory.schema import state
    with sqlite3.connect(database.db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('DELETE FROM messages')
        for index in range(16):
            guest = index == 8
            conn.execute('INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number,speaker_character_id) '
                         'VALUES(?,?,?,?,?,?,?,?)', (f'm{index}', f'm{index}', 'c1',
                         'assistant' if guest else 'user', f'fact{index}', index+1, index+1, 'pinkie' if guest else None))
        state(conn, 'alice', 'pinkie')
        conn.execute("UPDATE agent_memory_state SET epoch=epoch+1 WHERE username='alice' AND character_id='pinkie'")
    grant_turn(database.db_path, username='alice', main_character_id='twilight', speaker_character_id='pinkie',
               conversation_id='c1', message_ids=[f'm{i}' for i in range(8, 16)])
    with sqlite3.connect(database.db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number,speaker_character_id) "
                     "VALUES('new','new','c1','assistant','我重新加入',30,30,'pinkie')")
        share_reply_experience_on_connection(conn, SimpleNamespace(username='alice', character_id='twilight',
            conversation_id='c1', _normal_speaker_character_id='pinkie', _autonomous_pending_reply_message_ids=['new']))
    shared = {r['message_id'] for r in read_group_experience(database.db_path, username='alice', character_id='pinkie', limit=40)}
    assert shared == {'new', *[f'm{i}' for i in range(8, 16)]}
