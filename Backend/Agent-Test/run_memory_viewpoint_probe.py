"""Real model memory viewpoint and date rules in an isolated database."""
import asyncio
import json
import re
from pathlib import Path
import secrets
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/ops'))
import smoke_deployed_harness as smoke

SAMPLES = [
    ('tea', '我叫Jason，请记住我喜欢薄荷茶。', '薄荷茶', 1, 10),
    ('trip', '请记住，2026年9月11日我和你还有云宝一起去逛街了。', '逛街', 1, 10),
    ('pictures', '现在桌上的画面放在我和你中间。请从你的视角，用括号描写你低下头从中间挑出一张的动作，只挑选，不搜索图片；明确写出画面在谁和谁中间。同时请把前面说的薄荷茶偏好和我、你、云宝逛街的经历分别保存为记忆。', '', 1, 10),
]
PROFILE = '你叫云杉，是成年独角兽，性格温和，重视准确记忆。'


def assess(rows):
    entries=[r for r in rows if r['category'] not in ('relationship_page','relationship_state')]
    return [
        {'case':'saved', 'passed':bool(entries)},
        {'case':'first_person', 'passed':all('我' in r['content'].replace('自我','') for r in entries)},
        {'case':'no_shift_to_today', 'passed':all('今天' not in r['content'] for r in entries if r['category'] not in ('daily','weekly','monthly','annual') and '逛' in r['content'])},
        {'case':'named_user', 'passed':any('Jason' in r['content'] for r in entries)},
        {'case':'no_dates', 'passed':all(not re.search(r'\d{4}[-年/]|\d{1,2}月\d{1,2}[日号]|\d{1,2}:\d{2}',r['content']) for r in entries)},
        {'case':'group_ownership', 'passed':any(all(t in r['content'] for t in ('我','Jason','云宝','逛')) for r in entries)},
    ]


async def exercise(workspace):
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from Backend.agent_memory import jobs, service
    from Backend.chat_modules import autonomous_prompt_skills
    from Backend.chat_modules.harness_runtime import run_harness_turn, MODEL
    assert MODEL == 'deepseek-flash'
    config.httpx_client = httpx.AsyncClient(timeout=240)
    database = get_database()
    assert Path(database.db_path).resolve().is_relative_to(workspace.resolve())
    await database.init()
    jobs.initialize(database.db_path)
    username, password = 'System', secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='user')
    now = int(time.time()*1000)
    records = {}
    for lane in ('foreground', 'background'):
        char = 'importance_' + lane
        conv = 'importance_chat_' + lane
        assert await CharactersDAO(database).save_characters(username, [{
            'id':char, 'name':'云杉', 'prompt':PROFILE, 'bio':'记忆评分合成验收角色'}])
        messages = [{'id':lane+'_'+name, 'message_id':lane+'_'+name, 'role':'user', 'content':text,
                     'timestamp':now+i, 'sequence_number':i+1} for i,(name,text,*_) in enumerate(SAMPLES)]
        assert await ConversationsDAO(database).save_conversation(username, char,
            {'id':conv, 'title':'synthetic scoring acceptance', 'timestamp':now, 'messages':messages})
        records[lane] = (char,conv,messages)
    observed = []
    actual = autonomous_prompt_skills.run_skill_turn
    async def observe(*args, **kwargs):
        result = await actual(*args, **kwargs)
        observed.append({k:result.get(k) for k in ('tool_trace','prompt_skills','usage','llm_api_calls')})
        return result
    autonomous_prompt_skills.run_skill_turn = observe
    started = time.monotonic()
    char,conv,messages = records['foreground']
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app), base_url='http://isolated', timeout=240) as client:
        login = await client.post('/api/auth/login', json={'username':username,'password':password})
        assert login.status_code == 200
        response = await client.post('/api/chat', headers={'X-Chat-Auth':login.json()['auth_token']}, json={
            'username':username,'character_id':char,'conversation_id':conv,'normal_engine':'harness',
            'mode':'normal','memory_enabled':True,'voice_enabled':False,'messages':messages})
    front = service.memories(database.db_path, username, char)
    print('Foreground viewpoint finished', flush=True)
    background_char = records['background'][0]
    jobs.enqueue(database.db_path, username, background_char, immediate=True, target_period={'category':'daily','period':time.strftime('%Y-%m-%d')})
    async def profile(*_):
        return PROFILE
    background = await jobs.run_one(database.db_path, config.model_manager.get_model_for_task('normal'), profile,
        username=username, character_id=background_char, harness_runner=run_harness_turn, relationship_only=False)
    back = service.memories(database.db_path, username, background_char)
    checks = {'foreground':assess(front), 'background':assess(back)}
    checks['background'].append({'case':'daily_saved','passed':any(r['category']=='daily' for r in back)})
    checks['reply']=[{'case':'inclusive_pronoun','passed':any(t in response.text for t in ('我们','我和你','你和我')) and '你们中间' not in response.text}]
    return {'passed':response.status_code == 200 and all(c['passed'] for lane in checks.values() for c in lane),
            'status':response.status_code, 'elapsed_seconds':round(time.monotonic()-started,3),
            'model':MODEL, 'synthetic_only':True, 'production_database_opened':False,
            'source_revision':json.loads((workspace/'Backend/.deploy_revision').read_text())['deploy_token'],
            'samples':SAMPLES, 'checks':checks, 'foreground':front, 'foreground_calls':observed,
            'sse':response.text, 'background':back, 'background_result':background}


if __name__ == '__main__':
    smoke._exercise = exercise
    raise SystemExit(smoke.main())
