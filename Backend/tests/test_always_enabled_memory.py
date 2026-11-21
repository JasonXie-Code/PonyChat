import asyncio
import json
import sqlite3

import pytest
from test_unified_agent_memory import db, store, jobs, commit, WHEN
from unified_memory_test.agent_memory.review import ReviewTools
from unified_memory_test.agent_memory.relationship import project, stage_agent_decision


def test_upgrade_restores_memory_and_preserves_proactive_off(db):
    jobs.configure(db, 'alice', 'twilight', False)
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE user_settings(user_id INTEGER PRIMARY KEY,settings TEXT)')
        conn.execute('INSERT INTO user_settings VALUES(1,?)', (json.dumps({
            'memory_enabled': False, 'proactive_messages_enabled': False,
            'nickname': 'Alice', 'personal_preferences': {'twilight': '简洁回复'}}),))
    jobs.initialize(db)
    assert jobs.status(db, 'alice', 'twilight')['enabled']
    assert jobs.request_relationship(db, 'alice', 'twilight') == 'queued'
    with sqlite3.connect(db) as conn:
        settings = json.loads(conn.execute('SELECT settings FROM user_settings').fetchone()[0])
    assert settings == {'memory_enabled': True, 'proactive_messages_enabled': False,
                        'nickname': 'Alice', 'personal_preferences': {'twilight': '简洁回复'}}


@pytest.mark.parametrize('legacy_value', [False, None, True])
def test_old_clients_cannot_disable_memory(legacy_value):
    from Backend.utils import ChatRequest
    assert ChatRequest(messages=[], memory_enabled=legacy_value).memory_enabled is True


def test_old_settings_save_restores_memory_but_keeps_proactive_off(db):
    from types import SimpleNamespace
    from Backend.db.settings_dao import SettingsDAO
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE user_settings(user_id INTEGER PRIMARY KEY,settings TEXT,updated_at TEXT)')
    jobs.configure(db, 'alice', 'twilight', False)
    async def user_id(*args): return 1
    dao=SettingsDAO(SimpleNamespace(db_path=db, _get_user_id=user_id))
    assert asyncio.run(dao.save_settings('alice', {
        'memory_enabled':False, 'proactive_messages_enabled':False}))
    assert asyncio.run(dao.load_settings('alice')) == {
        'memory_enabled':True, 'proactive_messages_enabled':False}
    assert jobs.status(db,'alice','twilight')['enabled']


def test_manual_refresh_recovers_missed_mutual_commitment(db):
    from test_relationship_page_limits import page
    s=store(db)
    stage_agent_decision(s, {'relationship_stage': 'flirting'},
                         source_message_ids=['m1'], occurred_at=WHEN)
    commit(s)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) "
                     "VALUES('u1','u1','c1','user','那你以后就是我的女朋友了',1,2)")
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) "
                     "VALUES('a1','a1','c1','assistant','女朋友！那我收下啦，收下就不退货！',1,2)")
    s=store(db, sources=['m1','u1','a1'])
    tools=ReviewTools(db, {'username':'alice','character_id':'twilight','relationship_requested':1}, s)
    refreshed=page()
    refreshed['relationship_stage']='committed_partner'
    asyncio.run(tools.stage_relationship({'page':refreshed,
        'source_message_ids':['u1','a1'], 'occurred_at':WHEN}))
    commit(s)
    result=project(db,'alice','twilight')
    assert result['relationship_stage']=='committed_partner'
    assert result['relationship_page']['relationship_stage']=='committed_partner'


def test_refresh_does_not_change_manual_relationship_selection(db):
    from test_relationship_page_limits import page
    from unified_memory_test.agent_memory.relationship_control import set_control
    set_control(db,'alice','twilight','manual','familiar')
    s=store(db)
    tools=ReviewTools(db, {'username':'alice','character_id':'twilight','relationship_requested':1}, s)
    refreshed=page()
    refreshed['relationship_stage']='committed_partner'
    asyncio.run(tools.stage_relationship({'page':refreshed, 'source_message_ids':['m1'], 'occurred_at':WHEN}))
    commit(s)
    assert project(db,'alice','twilight')['relationship_stage']=='familiar'
