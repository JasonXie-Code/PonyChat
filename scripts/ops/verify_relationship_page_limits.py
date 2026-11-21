"""Real review Agent and relationship API, exclusively in a disposable database."""
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time

import smoke_deployed_harness as smoke

SOURCES=['Backend/agent_memory/relationship_page_contract.py','Backend/agent_memory/relationship.py',
         'Backend/agent_memory/review.py','Backend/agent_memory/store.py','Backend/agent_memory/service.py',
         'Backend/relationship_insights.py']


async def exercise(workspace: Path):
    import httpx
    sys.path.insert(0,str(workspace))
    import Backend
    from Backend import config
    from Backend.agent_memory import jobs, service
    from Backend.agent_memory.relationship import project, complete_page
    from Backend.agent_memory.relationship_page_contract import TEXT_LIMITS, ITEM_LIMITS, mobile_length, page_limits
    from Backend.chat_modules.harness_runtime import run_harness_turn
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao, get_membership_dao

    started=time.monotonic()
    config.httpx_client=httpx.AsyncClient(timeout=600)
    db=get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
    await db.init(); jobs.initialize(db.db_path)
    username,password='System',secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username,password,role='admin')
    assert await get_membership_dao().set_membership_by_username(username,'developer',None,
        note='isolated relationship copy limits acceptance')
    char='limits_'+secrets.token_hex(5)
    profile='你叫云杉，是温和好奇的成年独角兽小马，喜欢阅读与星空。'
    assert await CharactersDAO(db).save_characters(username,[{'id':char,'name':'云杉','prompt':profile}])
    conversation='limits_'+secrets.token_hex(5)
    messages=[]
    report={'synthetic_only':True,'production_database_opened':False,'status':200,'passed':False,
        'transport':'real review Harness + authenticated ASGI relationship state; isolated database',
        'source_hashes':{n:hashlib.sha256((workspace/n).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for n in SOURCES},
        'cases':[]}

    async def profile_loader(*_args): return profile

    async def save_message(role,text):
        mid='limits_'+secrets.token_hex(6)
        messages.append({'id':mid,'message_id':mid,'role':role,'content':text,
                         'timestamp':int(time.time()*1000),'sequence_number':len(messages)+1})
        assert await ConversationsDAO(db).save_conversation(username,char,{
            'id':conversation,'title':'synthetic relationship limits','timestamp':int(time.time()*1000),
            'messages':messages})

    await save_message('user','你好，我叫林舟。我喜欢绿茶和安静阅读，不爱喝甜饮料。今天在图书馆读了一本星空入门书，里面的冬季星座让我很感兴趣。')
    await save_message('assistant','我听你说完，分享了自己看星图时找到猎户座的经历，也想听你读书的感想。')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),base_url='http://isolated-limits') as client:
        login=await client.post('/api/auth/login',json={'username':username,'password':password})
        assert login.status_code==200
        headers={'X-Chat-Auth':login.json()['auth_token'],'X-Client-ID':'android'}
        params={'username':username,'character_id':char}
        for label in ('initial','existing_page_update','legacy_overlong_rebuild'):
            case={'label':label,'agent_calls':[],'passed':False}; report['cases'].append(case)
            before=project(db.db_path,username,char)
            if label=='existing_page_update':
                await save_message('user','我刚结束了一段让我很难过的友情，这会儿有点疲惫。我不想马上解决问题，只希望你安静听一听。以后难过时，请先问我想不想倾诉，再给建议。今天先不聊星座了。')
                await save_message('assistant','我放下手边的星图，安静陪你坐着，听你慢慢说。')
                jobs.enqueue(db.db_path,username,char,immediate=True)
            elif label=='legacy_overlong_rebuild':
                old=dict(before['relationship_page'])
                old.update(overview='我记得你喜欢绿茶与安静阅读。'*12,
                           mood='听到你说累了，我想安静陪着你。'*8,
                           self_portrait='你喜欢阅读，也愿意告诉我自己的心情。'*4,
                           chips=['安静陪伴你的心情','愿意慢慢了解你'])
                from Backend.agent_memory.store import AgentMemoryStore
                rows=AgentMemoryStore(db.db_path,username=username,character_id=char,conversation_id='fixture').list(category='relationship_page')
                service.manual(db.db_path,username,char,memory_id=rows[0]['id'],content=json.dumps(old,ensure_ascii=False))
            pre=await client.get('/api/relationship/state',headers=headers,params=params)
            case['before_status']=pre.status_code
            case['before_generation_status']=pre.json()['generation_status']
            if label!='existing_page_update': assert pre.json()['generation_status']=='queued'

            async def observe(prompt,cfg,tools,**kwargs):
                payload=json.loads(prompt)
                observed={'page_required':payload['relationship_page_required'],
                    'limits':payload['relationship_page_limits'],'page_submissions':[]}
                case['agent_calls'].append(observed)
                actual=tools['stage_relationship_page'].callback
                async def submission(args):
                    event={'page':args['page']}; observed['page_submissions'].append(event)
                    try:
                        result=await actual(args)
                        event['accepted']=True
                        return result
                    except ValueError as exc:
                        event.update(accepted=False,error=str(exc)); raise
                tools['stage_relationship_page'].callback=submission
                result=await run_harness_turn(prompt,cfg,tools,**kwargs)
                observed.update(llm_api_calls=result.get('llm_api_calls'),finish_reason=result.get('finish_reason'))
                return result

            result=await jobs.run_one(db.db_path,config.model_manager.get_model_for_task('normal'),profile_loader,
                username=username,character_id=char,harness_runner=observe)
            case['review_status']=result['status'] if result else None
            saved=project(db.db_path,username,char)
            response=await client.get('/api/relationship/state',headers=headers,params=params)
            exposed=response.json()['relationship_page']; raw=saved['relationship_page']
            fields=(*TEXT_LIMITS,*ITEM_LIMITS)
            case.update(page=exposed,stored_version=saved['relationship_page_source']['version'],
                lengths={**{k:mobile_length(raw[k]) for k in TEXT_LIMITS},
                         **{k:[mobile_length(v) for v in raw[k]] for k in ITEM_LIMITS}},
                api_copy_unchanged=all(exposed[k]==raw[k] for k in fields),
                generation_status=response.json()['generation_status'],
                no_ellipsis=not any('…' in str(exposed[k]) or '...' in str(exposed[k]) for k in fields))
            case['passed']=(response.status_code==200 and complete_page(raw) and case['api_copy_unchanged']
                and case['no_ellipsis'] and case['generation_status']=='idle'
                and any(d['category']=='relationship_page' for d in result['saved'])
                and all(c['limits']==page_limits() and c['page_required']==(label!='existing_page_update') for c in case['agent_calls']))
            if not case['passed']: break
    report.update(passed=len(report['cases'])==3 and all(c['passed'] for c in report['cases']),
                  elapsed_seconds=round(time.monotonic()-started,3))
    return report


if __name__=='__main__':
    smoke._exercise=exercise
    raise SystemExit(smoke.main())
