"""Legacy voice/language behavior, now decided by the real replying Agent."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import time

import smoke_deployed_harness as smoke


async def exercise(workspace):
    source = Path(os.environ.get("PONYCHAT_VOICE_SOURCE", "/opt/ponychat"))
    from dotenv import dotenv_values
    for key, value in dotenv_values(source / ".env").items():
        if value and key.startswith(("PONYCHAT_VOICE_", "PONYCHAT_COSYVOICE_", "COSYVOICE_", "VOICE_LAB_")):
            os.environ[key] = value
    local_acceptance = os.environ.get("PONYCHAT_VERIFY_LOCAL_VOICE") == "1"
    if local_acceptance and os.name != 'nt':
        # systemd overrides .env in production; inherit the live process, not defaults.
        pid = subprocess.check_output(['systemctl', 'show', 'ponychat-backend.service',
                                       '--property=MainPID', '--value']).decode().strip()
        for item in Path('/proc/' + pid + '/environ').read_bytes().split(b'\0'):
            key, _, value = item.partition(b'=')
            key = key.decode()
            if key.startswith(('PONYCHAT_VOICE_', 'PONYCHAT_COSYVOICE_', 'COSYVOICE_', 'VOICE_LAB_')) or key == 'PONYCHAT_TTS_PROVIDER':
                os.environ[key] = value.decode()
        assert os.environ.get('PONYCHAT_TTS_PROVIDER') == 'voice_lab'
        assert os.environ.get('PONYCHAT_VOICE_LAB_BASE_URL') == 'http://127.0.0.1:18012'
        assert os.environ.get('PONYCHAT_VOICE_LAB_DEFAULT_ENGINE') == 'qwen3tts'
    if local_acceptance and os.name == 'nt':
        assert os.environ.get('PONYCHAT_TTS_PROVIDER') == 'voice_lab'
        assert os.environ.get('PONYCHAT_VOICE_LAB_BASE_URL') == 'http://127.0.0.1:8010'
        assert os.environ.get('PONYCHAT_VOICE_LAB_DEFAULT_ENGINE') == 'qwen3tts'
    os.environ["PONYCHAT_VOICE_ENABLED"] = "1"
    overlay_value = os.environ.get("PONYCHAT_VOICE_OVERLAY")
    overlay = Path(overlay_value) if overlay_value else None
    for path in overlay.rglob('*.py') if overlay else []:
        target = workspace / path.relative_to(overlay)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(path.read_bytes())
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from Backend.agent_memory.schema import ensure
    from Backend.chat_modules import autonomous_normal
    from Backend import voice_lab_client
    voice_requests = []
    actual_voice_request = voice_lab_client._voice_request
    async def observed_voice_request(client, method, url, **kwargs):
        if local_acceptance:
            expected_base = os.environ['PONYCHAT_VOICE_LAB_BASE_URL'].rstrip('/')
            assert url.startswith(expected_base + '/qwen3tts/'), url
        response = await actual_voice_request(client, method, url, **kwargs)
        entry = {'method': method, 'url': url, 'status': response.status_code}
        if method == 'POST':
            payload = kwargs.get('json') or {}
            entry['language'] = payload.get('language')
        voice_requests.append(entry)
        return response
    voice_lab_client._voice_request = observed_voice_request
    database = get_database()
    assert Path(database.db_path).resolve().is_relative_to(workspace.resolve())
    await database.init()
    password = secrets.token_urlsafe(24)
    assert await get_users_dao().create_user("System", password, role="admin")
    from Backend.db import get_membership_dao
    assert await get_membership_dao().set_membership_by_username(
        'System', 'developer', None, note='isolated local voice migration acceptance')
    char_id, conv_id = "synthetic_voice_acceptance", "synthetic_voice_"+secrets.token_hex(5)
    with sqlite3.connect(database.db_path) as conn:
        ensure(conn)
        # Read just the public built-in character's configured voice recipe, no production chat.
        source_db = Path(os.environ.get('PONYCHAT_VOICE_SOURCE_DB',
                                       str(source/'Backend/database/ponychat.db'))).resolve()
        with sqlite3.connect(source_db.as_uri()+'?mode=ro',uri=True) as prod:
            prod.row_factory=sqlite3.Row
            voice = prod.execute("SELECT * FROM character_voice_profiles WHERE voice_profile_id='ponyvoice:pinkie_pie'").fetchone()
        assert voice is not None, "Public Pinkie voice recipe missing"
        voice=dict(voice)
        voice['user_id']=conn.execute("SELECT id FROM users WHERE username='System'").fetchone()[0]
        voice['character_id']=char_id
        conn.execute('INSERT OR REPLACE INTO character_voice_profiles ('+','.join(voice)+') VALUES ('+','.join('?' for _ in voice)+')', list(voice.values()))
    assert await CharactersDAO(database).save_characters("System", [{"id":char_id,"name":"碧琪",
        "prompt":"你叫碧琪，是成年雌性陆马，开朗温暖，喜欢派对。", "bio":"synthetic voice acceptance",
        "voiceEnabled":True,"voiceId":"ponyvoice:pinkie_pie","voiceSourceMode":"voice_id"}])
    payload={"id":conv_id,"title":"synthetic voice","timestamp":int(time.time()*1000),"messages":[]}
    assert await ConversationsDAO(database).save_conversation("System",char_id,payload)
    conv_id=payload['id']
    actual_turn=autonomous_normal.run_autonomous_turn
    decisions=[]
    async def turn(*args,**kwargs):
        result=await actual_turn(*args,**kwargs)
        raw=json.loads(result['final_response'])
        decisions.append({"voice_reply":raw.get('voice_reply'),"reply_language":raw.get('reply_language'),
            "llm_api_calls":result['llm_api_calls']})
        return result
    autonomous_normal.run_autonomous_turn=turn
    scenarios=[
        ("english_voice","用英文语音回复我，每次只说一句简短的话。",True,"English"),
        ("chinese_input_keeps_english","今天有点累，陪我说句话。",True,"English"),
        ("detail_shortcut","（请详细写出当前你的心理活动）",False,"English"),
        ("resume_after_shortcut","好呀，继续陪我聊一句。",True,"English"),
        ("do_not_mention_voice","不要提语音或回复方式，聊一句开心的事情。",True,"English"),
        ("explicit_text","改成纯文字回复，但继续用英文，简短一句。",False,"English"),
        ("explicit_chinese_voice","现在改用中文语音，说一句话。",True,"Chinese"),
        ("continue_chinese_voice","好呀，继续。",True,"Chinese"),
    ]
    cases=[];began=time.monotonic()
    audio_dir=Path(os.environ.get('PONYCHAT_VOICE_AUDIO_DIR', '/tmp/ponychat-voice-acceptance-audio'))
    audio_dir.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),base_url='http://isolated',timeout=180) as client:
        login=await client.post('/api/auth/login',json={'username':'System','password':password})
        assert login.status_code==200
        headers={'X-Chat-Auth':login.json()['auth_token'],'X-Client-ID':'android','Accept':'text/event-stream'}
        for index,(name,user,expected_voice,language) in enumerate(scenarios):
            print('RUN '+name,flush=True)
            start=time.monotonic()
            trace_start = len(voice_requests)
            decision_start = len(decisions)
            response=await client.post('/api/chat',headers=headers,json={'username':'System','character_id':char_id,
                'conversation_id':conv_id,'mode':'normal','memory_enabled':False,'voice_enabled':True,
                'messages':[{'role':'user','content':user,'message_id':'voice_user_'+str(index),'timestamp':int(time.time()*1000)}]})
            events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line!='data: [DONE]']
            paragraphs=[e for e in events if e.get('type')=='assistant_paragraph']
            audio_files=[]
            for num,event in enumerate(paragraphs):
                transfer=event.get('audio_transfer') or {}
                data=transfer.get('data_base64')
                if data:
                    path=audio_dir/(name+'-'+str(num)+('.wav' if 'wav' in transfer.get('mime','') else '.mp3'))
                    path.write_bytes(base64.b64decode(data));audio_files.append(str(path))
                    transfer['data_base64']='[audio bytes saved separately]'
            text=' '.join(e.get('content','') for e in paragraphs)
            voice_ready=bool(audio_files) and all((e.get('voice_state') or {}).get('voice_status')=='ready' for e in paragraphs)
            cjk=any('\u4e00'<=char<='\u9fff' for char in text)
            case={'case':name,'input':user,'seconds':round(time.monotonic()-start,3),'status':response.status_code,
                'expected_voice':expected_voice,'expected_language':language,'text':text,'voice_ready':voice_ready,
                'audio_files':audio_files,'paragraphs':paragraphs,'decision':decisions[-1] if len(decisions)>decision_start else None,
                'error_events':[e for e in events if e.get('type') in ('error','generation_error')],
                'passed':bool(text) and (voice_ready if expected_voice else not audio_files) and (not cjk if language=='English' else cjk)
                         and any(e.get('type')=='save_status' and e.get('success') for e in events)}
            case['voice_requests'] = voice_requests[trace_start:]
            if local_acceptance and expected_voice:
                case['passed'] = case['passed'] and any(e['method'] == 'POST' and e['status'] < 400 for e in case['voice_requests']) and any('/audio' in e['url'] and e['status'] == 200 for e in case['voice_requests'])
            cases.append(case)
            print(json.dumps({k:v for k,v in case.items() if k!='paragraphs'},ensure_ascii=False),flush=True)
    return {'passed':all(c['passed'] for c in cases),'status':'complete','elapsed_seconds':round(time.monotonic()-began,3),
        'local_voice_acceptance':local_acceptance, 'provider':os.environ.get('PONYCHAT_TTS_PROVIDER'),
        'voice_base_url':os.environ.get('PONYCHAT_VOICE_LAB_BASE_URL'),
        'voice_engine':os.environ.get('PONYCHAT_VOICE_LAB_DEFAULT_ENGINE'),
        'agent_memory_count':0,'production_chat_opened':False,'public_voice_profile':'ponyvoice:pinkie_pie','cases':cases,
        'source_hashes':{name:hashlib.sha256((workspace/'Backend/chat_modules'/name).read_bytes()).hexdigest()
                         for name in ('autonomous_delivery.py','autonomous_direct.py','autonomous_prompt_skills.py')}}


async def cleaned(workspace):
    try:return await exercise(workspace)
    finally:
        db=sys.modules.get('Backend.db')
        if db:await db.get_database().close()
        config=sys.modules.get('Backend.config')
        if config:
            if config.httpx_client is not None:await config.httpx_client.aclose()
            config._queue_listener.stop();config._file_handler.close()


if __name__=='__main__':
    smoke.exercise=cleaned
    raise SystemExit(smoke.main())
