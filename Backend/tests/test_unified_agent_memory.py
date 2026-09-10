"""Isolated SQLite acceptance of the new store, with no service/model startup."""
import asyncio
import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT=Path(__file__).parents[1]/'agent_memory'
parent = types.ModuleType('unified_memory_test')
parent.__path__ = [str(ROOT.parent)]
sys.modules['unified_memory_test'] = parent
spec=importlib.util.spec_from_file_location('unified_memory_test.agent_memory',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from unified_memory_test.agent_memory import jobs, service, evidence
from unified_memory_test.agent_memory.store import AgentMemoryStore, MemoryConflictError
from unified_memory_test.agent_memory.review import ReviewTools

WHEN='2026-09-05T12:00:00+08:00'

@pytest.fixture
def db(tmp_path):
    path=tmp_path/'test.sqlite'
    with sqlite3.connect(path) as c:
        c.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT);
          CREATE TABLE conversations(id TEXT PRIMARY KEY,user_id INTEGER,character_id TEXT,is_hidden INTEGER DEFAULT 0);
          CREATE TABLE messages(id TEXT,message_id TEXT,conversation_id TEXT,role TEXT,content TEXT,timestamp INTEGER,
            sequence_number INTEGER,speaker_character_id TEXT,is_hidden INTEGER DEFAULT 0,deleted_at TEXT);
          INSERT INTO users VALUES(1,'alice'),(2,'bob');
          INSERT INTO conversations(id,user_id,character_id) VALUES('c1',1,'twilight'),('c2',1,'twilight'),('b',2,'twilight'),('p',1,'pinkie');''')
        c.execute("INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) VALUES('m1','m1','c1','user','我喜欢绿茶',?,1)",
                  (int(__import__('datetime').datetime.fromisoformat(WHEN).timestamp()*1000),))
    jobs.initialize(path)
    return path

def store(db,**kw):
    return AgentMemoryStore(db,username=kw.get('username','alice'),character_id=kw.get('character_id','twilight'),
                           conversation_id=kw.get('conversation_id','c1'),allowed_sources=kw.get('sources',['m1']))

def stage(s,**kw):
    return s.stage(kind=kw.pop('kind','fact'),content=kw.pop('content','用户喜欢绿茶'),
                   source_message_ids=kw.pop('source_message_ids',['m1']),occurred_at=WHEN,**kw)

def commit(s):
    return s.commit(reply_succeeded=True,generation_is_current=lambda:True)

def test_owner_scene_and_shared_fact(db):
    s=store(db); stage(s,category='preference'); stage(s,kind='current_scene',content='用户在门口'); commit(s)
    assert len(store(db).list())==2
    assert len(store(db,conversation_id='c2').list())==1
    assert store(db,username='bob').list()==[]
    assert store(db,character_id='pinkie').list()==[]
    with pytest.raises(ValueError): stage(store(db,username='bob'))

@pytest.mark.parametrize('change',["content='改为红茶'",'is_hidden=1',"deleted_at='today'"])
def test_evidence_change_invalidates_read_and_pending_commit(db,change):
    s=store(db); stage(s); commit(s)
    pending=store(db); stage(pending)
    with sqlite3.connect(db) as c: c.execute('UPDATE messages SET '+change)
    assert store(db).list()==[]
    assert store(db).list(include_stale=True)[0]['stale']
    with pytest.raises(MemoryConflictError): commit(pending)

def test_revision_and_version_races(db):
    s=store(db); row=stage(s); commit(s)
    a,b=store(db),store(db)
    for candidate in (a,b): stage(candidate,entry_id=row['entry_id'],expected_version=1,status='cancelled',category='commitment')
    commit(a)
    with pytest.raises(MemoryConflictError): commit(b)
    jobs.enqueue(db,'alice','twilight',immediate=True); job=jobs.claim(db)
    pending=store(db); stage(pending)
    jobs.enqueue(db,'alice','twilight')
    with pytest.raises(MemoryConflictError): pending.commit(reply_succeeded=True,generation_is_current=lambda:True,expected_revision=job['revision'])

def test_reset_cancels_inflight_and_keeps_other_character(db):
    s=store(db); stage(s); commit(s)
    service.manual(db,'alice','pinkie',content='其他角色记忆',category='episode')
    pending=store(db); stage(pending)
    async def reset():
        import aiosqlite
        async with aiosqlite.connect(db) as c:
            await service.reset_on_connection(c,'alice','twilight'); await c.commit()
    asyncio.run(reset())
    with pytest.raises(MemoryConflictError): commit(pending)
    assert store(db).list()==[]
    assert len(service.memories(db,'alice','pinkie'))==1
    assert not jobs.status(db,'alice','twilight')['pending']

def test_manual_updates_stable_id_and_retracts(db):
    row=service.manual(db,'alice','twilight',content='手动记忆',category='preference')
    newer=service.manual(db,'alice','twilight',memory_id=row['id'],content='修改后')
    assert newer['id']==row['id'] and newer['version']==2
    with pytest.raises(LookupError): service.manual(db,'bob','twilight',memory_id=row['id'],content='越权')
    service.manual(db,'alice','twilight',memory_id=row['id'],retract=True)
    assert service.memories(db,'alice','twilight')==[]

def test_summary_dependency_invalidates_on_edit(db):
    s=store(db); fact=stage(s); commit(s)
    ref=f"memory:{fact['entry_id']}:1"
    summary=store(db,sources=[ref]); stage(summary,category='daily',period='2026-09-05',source_message_ids=[ref]); commit(summary)
    assert len(store(db).list())==2
    s=store(db); stage(s,entry_id=fact['entry_id'],expected_version=1,content='更正后的事实'); commit(s)
    assert len(store(db).list())==1

def test_period_paging_requires_all_sources(db):
    with sqlite3.connect(db) as c:
        original=c.execute('SELECT * FROM messages').fetchone()
        for i in range(1,90):
            row=list(original); row[0]=row[1]=f'm{i+1}'; row[6]=i+1
            c.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?)',row)
    s=store(db); tools=ReviewTools(db,dict(username='alice',character_id='twilight'),s)
    async def exercise():
        args=dict(category='daily',period='2026-09-05')
        seen=[]
        for more in (True,True,False):
            page=await tools.read_period(args); assert page['has_more']==more
            seen.extend(r['message_id'] for r in page['messages'])
            if more:
                with pytest.raises(ValueError):
                    await tools.stage(dict(kind='fact',content='日摘',importance=6,source_message_ids=['m1'],occurred_at=WHEN,**args))
        assert len(set(seen))==90
        await tools.stage(dict(kind='fact',content='日摘',importance=6,source_message_ids=['m1'],occurred_at=WHEN,**args))
    asyncio.run(exercise()); commit(s)
    assert store(db).list()[0]['category']=='daily'

def test_jobs_survive_restart_backoff_and_memory_disabled(db):
    assert jobs.claim(db) is None

    jobs.enqueue(db,'alice','twilight',immediate=True)
    job=jobs.claim(db); assert job and jobs.claim(db) is None
    jobs.finish(db,job,error='retry')
    jobs.initialize(db)
    assert jobs.status(db,'alice','twilight')['attempts']==1
    assert jobs.claim(db) is None
    jobs.configure(db,'alice','twilight',False)
    jobs.enqueue(db,'alice','twilight',immediate=True)
    assert jobs.claim(db) is None


def test_duplicate_exact_fact_is_idempotent(db):
    for _ in range(2):
        s=store(db); stage(s); commit(s)
    assert len(store(db).list())==1


def test_unchanged_sync_does_not_schedule_review(db):
    before=jobs.status(db,'alice','twilight')['revision']
    with sqlite3.connect(db) as c: c.execute('UPDATE messages SET content=content,is_hidden=is_hidden')
    assert jobs.status(db,'alice','twilight')['revision']==before


def test_scene_replaces_previous_scene_without_accumulating(db):
    s=store(db); first=stage(s,kind='current_scene',content='在窗边'); commit(s)
    s=store(db); second=stage(s,kind='current_scene',content='在门口'); commit(s)
    assert second['entry_id']==first['entry_id'] and second['version']==2
    assert len(store(db).list(kind='current_scene'))==1


def test_old_specific_fact_is_searchable_after_500_new_entries(db):
    s=store(db); stage(s,content='唯一旧偏好桂花茶'); commit(s)
    for batch in range(17):
        s=store(db)
        for i in range(30):stage(s,content=f'普通记录{batch*30+i}')
        commit(s)
    assert store(db).list(query='桂花茶')[0]['content']=='唯一旧偏好桂花茶'


def test_manual_importance_and_relationship_projection(db):
    from unified_memory_test.agent_memory.relationship import set_manual_stage, project
    row=service.manual(db,'alice','twilight',content='重要约定',importance=9)
    assert service.memories(db,'alice','twilight')[0]['importance']==9
    service.manual(db,'alice','twilight',memory_id=row['id'],importance=7)
    assert service.memories(db,'alice','twilight')[0]['importance']==7
    set_manual_stage(db,'alice','twilight','familiar')
    assert project(db,'alice','twilight')['relationship_stage']=='familiar'
    assert project(db,'alice','twilight')['updated_at_ms']>0
    assert len(service.memories(db,'alice','twilight'))==1


def test_dormant_history_is_not_recomputed_at_midnight(db):
    with sqlite3.connect(db) as c:
        c.execute("UPDATE agent_memory_state SET last_review_day='2020-01-01'")
    assert jobs.claim(db) is None
    jobs.enqueue(db,'alice','twilight',immediate=True)
    assert jobs.claim(db)['character_id']=='twilight'


def test_explicit_summary_precedes_older_background_job(db):
    jobs.enqueue(db,'alice','pinkie',immediate=True)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE agent_memory_state SET due_at=1 WHERE character_id='pinkie'")
    jobs.enqueue(db,'alice','twilight',immediate=True,target_period={'category':'daily','period':'2026-09-05'})
    assert jobs.claim(db)['character_id']=='twilight'


def test_relationship_poll_coalesces_and_completion_clears_request(db):
    assert jobs.request_relationship(db,'alice','pinkie')=='no_history'
    assert jobs.request_relationship(db,'alice','twilight')=='queued'
    revision=jobs.status(db,'alice','twilight')['revision']
    job=jobs.claim(db)
    for _ in range(5): jobs.request_relationship(db,'alice','twilight')
    assert jobs.status(db,'alice','twilight')['revision']==revision
    jobs.finish(db,job,relationship_saved=True)
    assert not jobs.status(db,'alice','twilight')['relationship_requested']


def test_relationship_retry_clears_failure_without_invalidating_revision(db):
    jobs.request_relationship(db,'alice','twilight')
    job=jobs.claim(db)
    jobs.finish(db,job,error='timeout')
    jobs.request_relationship(db,'alice','twilight',retry=True)
    current=jobs.status(db,'alice','twilight')
    assert current['last_error'] is None and current['revision']==job['revision']
    assert jobs.claim(db)['character_id']=='twilight'


def test_opening_relationship_does_not_invalidate_running_review(db):
    jobs.enqueue(db, 'alice', 'twilight', immediate=True)
    job = jobs.claim(db)
    jobs.request_relationship(db, 'alice', 'twilight')
    current = jobs.status(db, 'alice', 'twilight')
    assert current['revision'] == job['revision'] and current['running']
    jobs.finish(db, job, relationship_saved=True)
    assert not jobs.status(db, 'alice', 'twilight')['relationship_requested']


def test_changed_evidence_retries_requested_page_without_error_backoff(db):
    jobs.request_relationship(db, 'alice', 'twilight')
    job = jobs.claim(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE messages SET content='我现在喜欢红茶' WHERE message_id='m1'")
    jobs.finish(db, job, error='snapshot changed')
    assert jobs.status(db, 'alice', 'twilight')['last_error'] is None
    assert jobs.claim(db, relationship_only=True) is not None


def test_page_lane_does_not_claim_unrelated_archive_jobs(db):
    jobs.enqueue(db, 'alice', 'pinkie', immediate=True)
    jobs.request_relationship(db, 'alice', 'twilight')
    assert jobs.claim(db, relationship_only=False)['character_id'] == 'pinkie'
    assert jobs.claim(db, relationship_only=True)['character_id'] == 'twilight'


def test_explicit_page_refresh_stages_only_page_and_leaves_archive_pending(db, monkeypatch):
    import json
    from unified_memory_test.agent_memory import review, usage
    from unified_memory_test.agent_memory.relationship import FIELDS, LIST_FIELDS
    jobs.request_relationship(db, 'alice', 'twilight')
    job = jobs.claim(db, relationship_only=True)
    async def runner(raw, _config, tools, **options):
        assert set(tools) == {'stage_relationship_page'}
        assert options['timeout_seconds'] == 30 and options['max_tool_calls'] == 4
        assert json.loads(raw)['pending_periods']['pending'] == []
        await tools['stage_relationship_page']({'page': {
            **{field: '仍在了解你' for field in FIELDS},
            **{field: ['初识'] for field in LIST_FIELDS}},
            'source_message_ids': ['m1'], 'occurred_at': WHEN})
        return {'finish_reason': 'completed', 'final_response': '{}'}
    async def no_meter(*_args, **_kwargs): pass
    monkeypatch.setattr(review.ReviewTools, 'register', lambda tools: {'stage_relationship_page': tools.stage_relationship, 'stage_memory': tools.stage})
    monkeypatch.setattr(usage, 'meter_user', no_meter)
    result = asyncio.run(review.review(db, job, {}, 'profile', harness_runner=runner))
    assert [row['category'] for row in result['saved']] == ['relationship_page']
    jobs.finish(db, job, saved_count=1, needs_more=result['needs_more'], relationship_saved=True)
    current = jobs.status(db, 'alice', 'twilight')
    assert current['pending'] and not current['relationship_requested']


def test_relationship_requires_all_sections_and_updates_stable_entry(db):
    from unified_memory_test.agent_memory.relationship import FIELDS,LIST_FIELDS,project
    s=store(db); tools=ReviewTools(db,{'username':'alice','character_id':'twilight'},s)
    args={'page':{'overview':'用户喜欢绿茶'},'source_message_ids':['m1'],'occurred_at':WHEN}
    with pytest.raises(ValueError): asyncio.run(tools.stage_relationship(args))
    args['page']={**{k:'我还在了解这位喜欢绿茶的朋友' for k in FIELDS},
                  **{k:['聊聊绿茶'] for k in LIST_FIELDS},'relationship_stage':'new_contact'}
    first=asyncio.run(tools.stage_relationship(args)); commit(s)
    s=store(db); tools=ReviewTools(db,{'username':'alice','character_id':'twilight'},s)
    args['page']['mood']='期待了解更多'
    second=asyncio.run(tools.stage_relationship(args)); commit(s)
    assert first['entry_id']==second['entry_id'] and second['version']==2
    assert project(db,'alice','twilight')['relationship_page']['mood']=='期待了解更多'


def test_foreground_agent_owns_relationship_fields_and_review_preserves_them(db):
    from unified_memory_test.agent_memory.relationship import FIELDS, LIST_FIELDS, project, stage_agent_decision
    decision={'relationship_stage':'intimate_partner','character_intimacy_style':'playful',
              'requested_escalation':'affection','user_pressure_level':'low'}
    s=store(db)
    staged=stage_agent_decision(s,decision,source_message_ids=['m1'],occurred_at=WHEN)
    assert staged['staged'] and staged['relationship_state']==decision
    commit(s)
    assert {key:project(db,'alice','twilight')[key] for key in decision}==decision
    assert service.memories(db,'alice','twilight')==[]

    s=store(db); tools=ReviewTools(db,{'username':'alice','character_id':'twilight'},s)
    page={**{key:'有原文依据的关系描述' for key in FIELDS},
          **{key:['有依据'] for key in LIST_FIELDS},'relationship_stage':'new_contact'}
    asyncio.run(tools.stage_relationship({'page':page,'source_message_ids':['m1'],'occurred_at':WHEN}))
    commit(s)
    projected=project(db,'alice','twilight')
    assert {key:projected[key] for key in decision}==decision
    assert projected['relationship_page']['overview']=='有原文依据的关系描述'


def test_background_review_meters_every_agent_model_call(db, monkeypatch):
    from unified_memory_test.agent_memory import review, usage
    jobs.enqueue(db, 'alice', 'twilight', immediate=True)
    job = jobs.claim(db, username='alice', character_id='twilight')
    observed = []

    async def harness_runner(*_args, **_kwargs):
        return {'finish_reason': 'completed', 'final_response': '{"completed":true}',
                'usage': {'prompt_tokens': 120, 'completion_tokens': 15},
                'llm_api_calls': 3}

    def record(*args):
        observed.append(('record', args[3], args[4]['llm_api_calls']))

    async def meter_user(username, result, **_kwargs):
        observed.append(('meter', username, result['usage'], result['llm_api_calls']))

    monkeypatch.setattr(usage, 'record', record)
    monkeypatch.setattr(usage, 'meter_user', meter_user)
    monkeypatch.setattr(review.ReviewTools, 'register', lambda _self: {})
    result = asyncio.run(review.review(db, job, {}, 'profile', harness_runner=harness_runner))

    assert result['llm_api_calls'] == 3
    assert ('record', 'background', 3) in observed
    assert ('meter', 'alice', {'prompt_tokens': 120, 'completion_tokens': 15}, 3) in observed


@pytest.mark.parametrize('progress', [False, True])
def test_budget_stop_commits_only_valid_progress_and_keeps_job_pending(db, monkeypatch, progress):
    from unified_memory_test.agent_memory import review, usage
    jobs.enqueue(db, 'alice', 'twilight', immediate=True)
    job = jobs.claim(db, username='alice', character_id='twilight')
    metered = []
    def register(tools):
        return {'stage':tools.stage}
    async def runner(_prompt, _config, tools, **kwargs):
        assert kwargs['stop_on_tool_budget'] is True
        if progress:
            await tools['stage']({'kind':'fact','category':'preference','content':'用户喜欢绿茶',
                'source_message_ids':['m1'],'occurred_at':WHEN,'importance':7})
        return {'finish_reason':'tool_budget_exhausted', 'llm_api_calls':2,
                'usage':{'prompt_tokens':11,'completion_tokens':3}}
    async def meter(_username, result, **_):
        metered.append(result)
    monkeypatch.setattr(review.ReviewTools, 'register', register)
    monkeypatch.setattr(usage, 'meter_user', meter)
    if progress:
        result = asyncio.run(review.review(db, job, {}, 'profile', harness_runner=runner))
        assert len(result['saved']) == 1 and result['status'] == 'partial' and result['needs_more']
        assert store(db).list()[0]['content'] == '用户喜欢绿茶'
        jobs.finish(db, job, saved_count=1, needs_more=True)
        assert jobs.status(db, 'alice', 'twilight')['pending']
    else:
        with pytest.raises(ValueError, match='without staged progress'):
            asyncio.run(review.review(db, job, {}, 'profile', harness_runner=runner))
        assert not store(db).list()
    assert metered[0]['llm_api_calls'] == 2 and metered[0]['incomplete']


def test_summary_tools_advertise_readiness_without_weakening_evidence(db):
    tools = ReviewTools(db, {'username':'alice','character_id':'twilight'}, store(db))
    args = {'importance':6,'kind':'fact','category':'daily','period':'2026-09-05','content':'用户喜欢绿茶',
            'source_message_ids':['m1'],'occurred_at':WHEN}
    with pytest.raises(ValueError, match='not ready'):
        asyncio.run(tools.stage(args))
    result = asyncio.run(tools.read_period({'category':'daily','period':'2026-09-05'}))
    assert result['ready_to_stage'] and result['next_action'] == 'stage_memory'
    assert asyncio.run(tools.stage(args))['staged']


def test_review_page_schema_requires_arrays_but_not_foreground_decision():
    from unified_memory_test.agent_memory.review import REVIEW_PAGE_SCHEMA
    assert 'relationship_stage' not in REVIEW_PAGE_SCHEMA['properties']
    for key in ('chips','remembered_items','timeline_items','suggestions'):
        assert REVIEW_PAGE_SCHEMA['properties'][key]['type'] == 'array'
        assert key in REVIEW_PAGE_SCHEMA['required']
