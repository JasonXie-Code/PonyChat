"""Full-schema regressions for the Agent entry, shared contracts and atomic writes."""
import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

from Backend.agent_memory import jobs
from Backend.agent_memory.store import AgentMemoryStore
from Backend.chat_modules import autonomous_normal as normal
from Backend.chat_modules.autonomous_service import prepare_autonomous_request
from Backend.chat_modules.autonomous_transaction import install_memory_transaction
from Backend.chat_modules.autonomous_shortcuts import ShortcutContract
from Backend.db.database import Database, SCHEMA_SQL
from Backend.db.conversations_dao import ConversationsDAO
from Backend.utils import ChatRequest, ChatMessage
from test_autonomous_normal import model_result

WHEN = '2026-09-06T15:00:00+08:00'


def scene_result(text):
    """These synthetic messages establish no scene facts; initialize as unknown."""
    from Backend.chat_modules.autonomous_scene_state import FIELDS
    result = model_result(text)
    data = json.loads(result['final_response'])
    data['reply_language']['language'] = 'Chinese'
    data['scene_patch'] = {'reset': False, 'changes': {
        field: {'value': None, 'source_message_ids': ['m1']} for field in sorted(FIELDS)}}
    return {**result, 'final_response': json.dumps(data, ensure_ascii=False)}


@pytest.fixture
def database(tmp_path, monkeypatch):
    db = Database(str(tmp_path/'integration.sqlite'))
    with sqlite3.connect(db.db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO users(id,username,password) VALUES(1,'alice','test')")
        conn.execute("INSERT INTO characters(id,user_id,name) VALUES('twilight',1,'暮光闪闪')")
        conn.execute("INSERT INTO characters(id,user_id,name) VALUES('pinkie',1,'碧琪')")
        conn.execute("INSERT INTO conversations(id,user_id,character_id,title,timestamp) VALUES('c1',1,'twilight','test',1000)")
        conn.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) VALUES('m1','m1','c1','user','请记住我喜欢绿茶',1000,1)")
    async def migrations():
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            await db._migrate_columns(conn)
            from Backend.chat_modules.normal_lifecycle import ensure_normal_lifecycle_table_on_connection
            await ensure_normal_lifecycle_table_on_connection(conn)
    asyncio.run(migrations())
    jobs.initialize(db.db_path)

    async def init():
        pass
    monkeypatch.setattr(db,'init',init)
    from Backend import config, proactive_settings
    from Backend.chat_modules import image_context_store, character
    from Backend.db import database as database_module
    monkeypatch.setattr(config,'DB_PATH',db.db_path)
    # Another active task restored the relationship Planner. Keep offline tests
    # offline while preserving its independently tested contract.
    monkeypatch.setattr(config.model_manager,'get_model_for_task',lambda *a:None)
    for mod in (proactive_settings,image_context_store,character,database_module):
        monkeypatch.setattr(mod,'get_database',lambda:db)
    import Backend.utils as utils
    async def log(*args,**kwargs):
        pass
    monkeypatch.setattr(utils,'save_chat_debug_log',log)
    return db


def request():
    return ChatRequest(username='alice',character_id='twilight',conversation_id='c1',mode='normal',
                       messages=[ChatMessage(role='user',content='请记住我喜欢绿茶',message_id='m1',timestamp=1000)])


def draft(db):
    store = AgentMemoryStore(db.db_path,username='alice',character_id='twilight',conversation_id='c1',allowed_sources=['m1'])
    store.stage(kind='fact',content='用户喜欢绿茶',source_message_ids=['m1'],occurred_at=WHEN)
    return store


def save(db, req):
    return ConversationsDAO(db).save_conversation('alice','twilight',{'id':'c1','timestamp':2000,'messages':[
        {'role':'user','content':'请记住我喜欢绿茶','message_id':'m1','timestamp':1000,'sequence_number':1},
        {'role':'assistant','content':'记住了','message_id':'a1','timestamp':2000,'sequence_number':2}]},
        before_commit=req._autonomous_before_reply_commit)


@pytest.mark.parametrize('failure',['none','hidden','disabled','settings_disabled','superseded'])
def test_reply_and_memory_are_atomic(database,failure):
    req, store = request(), draft(database)
    install_memory_transaction(req,store)
    if failure=='hidden':
        with sqlite3.connect(database.db_path) as conn:
            conn.execute("UPDATE messages SET is_hidden=1 WHERE message_id='m1'")
    elif failure=='disabled':
        jobs.configure(database.db_path,'alice','twilight',False)
    elif failure=='settings_disabled':
        with sqlite3.connect(database.db_path) as conn:
            conn.execute('INSERT INTO user_settings(user_id,settings) VALUES(1,?)',(json.dumps({'memory_enabled':False}),))
    req._autonomous_generation_is_current = lambda:failure!='superseded'
    assert asyncio.run(save(database,req)) is (failure=='none')
    with sqlite3.connect(database.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE message_id='a1'").fetchone()[0] == int(failure=='none')
        assert conn.execute('SELECT COUNT(*) FROM agent_memory_heads').fetchone()[0] == int(failure=='none')


@pytest.mark.parametrize('text,kind',[
    ('（请详细写出当前你的心理活动）','thought'),
    ('（请详细写出当前你的身体状态）','body_state'),
    ('（请详细写出当前你看到的画面）','visual'),
    ('（请推进剧情发展）','action'),
])
def test_all_shortcuts_forbid_emoji_and_preserve_delivery_contract(text,kind):
    history=[{'role':'user','content':'Please use voice.'},
             {'role':'assistant','content':'Come with me.','speaker_character_id':'twilight','voice_state':{'voice_status':'ready'}},
             {'role':'user','content':text}]
    shortcut=ShortcutContract(history,'角色种族：独角兽',speaker='twilight',main='twilight')
    assert shortcut.description or shortcut.story
    data=json.loads(model_result('I look toward the open door.\n\nI notice the light.\n\nI stay still.')['final_response'])
    data.update(shortcut.delivery)
    for bubble in data['bubbles']:
        bubble['parts'][0]['kind']=kind
    assert shortcut.error(data)==''
    data['bubbles'][0]['parts'][0]['text'] += ' 😊'
    assert 'emoji' in shortcut.error(data)
    if shortcut.description:
        data['bubbles'][0]['parts'][0].update(kind='speech',text='Hello.')
        assert '非speech' in shortcut.error(data)


@pytest.mark.parametrize('intro', ['', '认真好学的雌性独角兽'])
def test_actual_prepare_registers_usable_tools_and_writes_memory(database,monkeypatch,intro):
    captured={}
    attempts=[]
    from Backend.chat_modules import harness_runtime
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("UPDATE characters SET data=? WHERE id='twilight'",
                     (json.dumps({'name':'暮光闪闪','profileIntro':intro,'profileSpecies':'独角兽'}),))

    async def runner(prompt,config,tools,**kwargs):
        attempts.append(1)
        captured.update(json.loads(prompt))
        await tools['read_character_reference'].callback({'query':'独角兽 种族'})
        from Backend.chat_modules.harness_runtime import _closed_schema
        for tool in tools.values():
            _closed_schema(tool.parameters)
        await tools['update_relationship_state'].callback(dict(relationship_stage='uncertain',
            character_intimacy_style='balanced',requested_escalation='none',user_pressure_level='low',
            source_message_ids=['m1'],occurred_at=WHEN))
        await tools['stage_memory'].callback(dict(kind='fact',content='用户喜欢绿茶',source_message_ids=['m1'],occurred_at=WHEN,importance=7))
        assert 'compose_character_reply' not in tools
        return scene_result('记住了')

    monkeypatch.setattr(harness_runtime,'run_harness_turn',runner)
    req=request()
    asyncio.run(prepare_autonomous_request(req,{},profile='角色种族：独角兽',environment='共享用户：测试者',image_urls=[]))
    assert len(attempts)==1
    assert '共享用户：测试者' in captured['environment']
    assert bool(req._normal_agent_trace['prompt_skills']['has_homepage_intro']) == bool(intro)
    assert req._normal_agent_trace['prompt_skills']['searched_this_turn']
    assert '角色种族：独角兽' not in captured['character_profile']
    if intro:
        assert intro in captured['character_profile']
    assert asyncio.run(save(database,req))
    with sqlite3.connect(database.db_path) as conn:
        categories={row[0] for row in conn.execute('''SELECT v.category FROM agent_memory_heads h
            JOIN agent_memory_versions v ON v.entry_id=h.entry_id AND v.version=h.version''')}
        assert categories=={'fact','relationship_state'}
        scene=json.loads(conn.execute('SELECT fields_json FROM normal_agent_scene_cards').fetchone()[0])
        assert len(scene)==6 and all(item['value'] is None for item in scene.values())


def test_actual_shortcut_entry_has_no_sticker_tools(database,monkeypatch):
    from Backend.chat_modules import harness_runtime
    attempts=[]
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("UPDATE messages SET content='（请详细写出当前你的心理活动）' WHERE message_id='m1'")

    async def runner(prompt,config,tools,**kwargs):
        assert 'stage_sticker' not in tools and 'search_stickers' not in tools
        await tools['read_character_reference'].callback({'query':'独角兽 种族'})
        await tools['update_relationship_state'].callback(dict(relationship_stage='uncertain',
            character_intimacy_style='balanced',requested_escalation='none',user_pressure_level='low',
            source_message_ids=['m1'],occurred_at=WHEN))
        attempts.append(1)
        assert 'compose_character_reply' not in tools
        result = scene_result('我想着刚才的事情\n\n我的心情渐渐安定\n\n我的注意力回到眼前')
        data = json.loads(result['final_response'])
        data['reply_language']['language'] = 'Chinese'
        for bubble in data['bubbles']:
            bubble['parts'][0]['kind'] = 'thought'
        return {**result, 'final_response': json.dumps(data, ensure_ascii=False)}

    monkeypatch.setattr(harness_runtime,'run_harness_turn',runner)
    req=request()
    req.messages[0].content='（请详细写出当前你的心理活动）'
    asyncio.run(prepare_autonomous_request(req,{},profile='角色种族：独角兽',environment='',image_urls=[]))
    assert len(attempts)==1
    assert req._assistant_asset_attachments==[]
    assert not req._normal_planner_result['voice_reply']['enabled']


@pytest.mark.parametrize('kind',['agreed','followup'])
def test_schedule_and_reply_commit_together(database,kind):
    from Backend.chat_modules.autonomous_schedule import validate_schedule
    from Backend.proactive_settings import ProactiveSettings
    req=request()
    plan=validate_schedule({'kind':kind,'summary':'提醒喝水','target_delay_seconds':120,
                           'source_message_id':'m1'},req,[{'role':'user','message_id':'m1','content':'两分钟后提醒我喝水'}])
    business=SimpleNamespace(request=req,schedules=[plan],settings=ProactiveSettings(),lifecycle=None)
    install_memory_transaction(req,None,business)
    assert asyncio.run(save(database,req))
    table='proactive_tasks' if kind=='agreed' else 'scheduled_followups'
    with sqlite3.connect(database.db_path) as conn:
        row=conn.execute(f'SELECT source_message_id FROM {table}').fetchone()
        assert row[0]=='a1'


def test_image_archive_and_lifecycle_share_reply_transaction(database):
    from Backend.proactive_settings import ProactiveSettings
    req=request()
    req._autonomous_image_fields={'image_summary':'蓝色杯子','visible_text':'TEA','user_text':'这是什么',
                                  'image_count':1,'identified_entities':['杯子']}
    business=SimpleNamespace(request=req,schedules=[],settings=ProactiveSettings(),
                              lifecycle={'source_message_id':'m1','reason':'fixture terminal event'})
    install_memory_transaction(req,None,business)
    assert asyncio.run(save(database,req))
    with sqlite3.connect(database.db_path) as conn:
        assert conn.execute('SELECT image_summary FROM normal_image_contexts').fetchone()[0]=='蓝色杯子'
        assert conn.execute('SELECT state FROM normal_character_lifecycle').fetchone()[0]=='dead'


def test_transaction_rollback_removes_reply_schedule_and_image(database):
    from Backend.proactive_settings import ProactiveSettings
    req=request()
    req._autonomous_image_fields={'image_summary':'blue','user_text':'image','image_count':1}
    # An invalid persisted plan simulates a later business write failing after
    # memory insertion. The reply and memory must both roll back.
    business=SimpleNamespace(request=req,schedules=[{'kind':'agreed','plan':{},'id':'bad'}],
                              settings=ProactiveSettings(),lifecycle=None)
    install_memory_transaction(req,draft(database),business)
    assert not asyncio.run(save(database,req))
    with sqlite3.connect(database.db_path) as conn:
        for table in ('agent_memory_heads','proactive_tasks','normal_image_contexts'):
            assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE message_id='a1'").fetchone()[0]==0
