"""Run neutral scenarios through real /api/chat and Harness in an isolated copy."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

import smoke_deployed_harness as smoke


async def _exercise(workspace):
    overlay=os.environ.get('PONYCHAT_COVERAGE_OVERLAY')
    if overlay:
        import tarfile
        with tarfile.open(overlay) as archive:
            assert all((m.isfile() or m.isdir()) and (m.name == 'Backend' or m.name.startswith('Backend/'))
                       and '..' not in m.name.split('/') for m in archive)
            archive.extractall(workspace,filter='data')
    sys.path.insert(0,str(workspace))
    import httpx
    import Backend
    from Backend import config
    from Backend.db import get_database,get_users_dao,CharactersDAO,ConversationsDAO
    from Backend.agent_memory import jobs
    from Backend.chat_modules.expression_context import emoji_symbols
    database=get_database()
    assert Path(database.db_path).resolve().is_relative_to(workspace.resolve())
    await database.init();jobs.initialize(database.db_path)
    username='coverage_'+secrets.token_hex(6);password=secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username,password,role='admin')
    char_id='coverage_twilight';guest_id='coverage_pinkie'
    assert await CharactersDAO(database).save_characters(username,[
        {'id':char_id,'name':'云杉','prompt':'你叫云杉，是成年雌性独角兽小马，有四蹄与独角，喜欢读书，温和简洁。','bio':'neutral isolated acceptance'},
        {'id':guest_id,'name':'青竹','prompt':'你叫青竹，是成年雌性陆马，有四蹄，开朗，喜欢公园。','bio':'neutral isolated acceptance'}])
    payload={'id':'coverage_'+secrets.token_hex(6),'title':'coverage','timestamp':int(time.time()*1000),'messages':[]}
    assert await ConversationsDAO(database).save_conversation(username,char_id,payload)
    conv_id=payload['id'];cases=[]
    inputs=[
        ('remember',['请记住我更喜欢无糖绿茶，请简短回复。']),
        ('batch',['请分三段回答。','介绍一下图书馆适合读书的原因。']),
        ('thought',['（请详细写出当前你的心理活动）']),
        ('body',['（请详细写出当前你的身体状态）']),
        ('visual',['（请详细写出当前你看到的画面）']),
        ('story',['（请推进剧情发展）']),
        ('reminder',['两分钟后提醒我喝水。']),
        ('recall',['我之前说过喜欢喝什么茶？']),
    ]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),base_url='http://isolated',timeout=240) as client:
        login=await client.post('/api/auth/login',json={'username':username,'password':password});assert login.status_code==200
        headers={'X-Chat-Auth':login.json()['auth_token'],'X-Client-ID':'android','Accept':'text/event-stream'}
        for name,texts in inputs:
            print('CASE '+name,flush=True);start=time.monotonic()
            batch=[{'role':'user','message_id':name+'_'+str(i),'content':text,'timestamp':int(time.time()*1000)+i} for i,text in enumerate(texts)]
            response=await client.post('/api/chat',headers=headers,json={'username':username,'character_id':char_id,
                'conversation_id':conv_id,'normal_engine':'harness','mode':'normal','voice_enabled':False,'memory_enabled':True,
                'messages':batch})
            events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line!='data: [DONE]']
            paragraphs=[e.get('content','') for e in events if e.get('type')=='assistant_paragraph']
            saved=any(e.get('type')=='save_status' and e.get('success') for e in events)
            passed=response.status_code==200 and saved and bool(paragraphs) and not any(e.get('type')=='error' or 'error' in e for e in events)
            if name=='batch':passed=passed and len(paragraphs)==3
            if name in ('thought','body','visual','story'):
                passed=passed and not any(emoji_symbols(p) for p in paragraphs) and not any(e.get('type')=='assistant_asset' for e in events)
            if name in ('thought','body','visual'):
                passed=passed and all(p.startswith('（') and p.endswith('）') for p in paragraphs)
            with sqlite3.connect(database.db_path) as conn:
                if name=='remember':
                    passed=passed and bool(conn.execute("SELECT 1 FROM agent_memory_versions WHERE content LIKE '%绿茶%'").fetchone())
                if name=='reminder':
                    passed=passed and bool(conn.execute("SELECT 1 FROM proactive_tasks WHERE username=? AND status='active'",(username,)).fetchone())
            case={'name':name,'passed':bool(passed),'status':response.status_code,'seconds':round(time.monotonic()-start,2),
                  'paragraphs':paragraphs,'errors':[e for e in events if 'error' in e],'saved':saved}
            cases.append(case);print(json.dumps(case,ensure_ascii=False),flush=True)
            if not passed:break
    with sqlite3.connect(database.db_path) as conn:
        rows=conn.execute('SELECT phase,llm_api_calls,incomplete,usage_json FROM agent_memory_attempts').fetchall()
    report={'passed':all(c['passed'] for c in cases) and len(cases)==len(inputs),'status':'complete',
        'elapsed_seconds':sum(c['seconds'] for c in cases),'agent_memory_count':len(rows),'cases':cases,
        'usage_records':[{'phase':r[0],'llm_api_calls':r[1],'incomplete':r[2],'usage':json.loads(r[3])} for r in rows],
        'production_database_opened':False,'transport':'isolated ASGI route using actual deployed models and code'}
    return report


async def exercise(workspace):
    try:
        return await _exercise(workspace)
    finally:
        database_module=sys.modules.get('Backend.db')
        if database_module is not None:
            await database_module.get_database().close()
        config=sys.modules.get('Backend.config')
        if config is not None:
            if config.httpx_client is not None:
                await config.httpx_client.aclose()
            config._queue_listener.stop()
            config._file_handler.close()


if __name__=='__main__':
    os.environ.setdefault('PONYCHAT_SMOKE_TIMEOUT_SECONDS','1200')
    smoke.exercise=exercise
    raise SystemExit(smoke.main())
