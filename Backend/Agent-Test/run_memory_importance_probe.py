"""Real Flash foreground route and background scoring, with isolated accounts."""
import asyncio
import json
from pathlib import Path
import secrets
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/ops'))
import smoke_deployed_harness as smoke

SAMPLES = [
    ('water', '请单独记住这条短期小事：今天午休路过便利店买了一瓶矿泉水。', '矿泉水', 1, 4),
    ('tea', '请单独记住这个长期偏好：我一直喜欢无糖绿茶，以后帮我挑饮料优先考虑这个。', '绿茶', 7, 8),
    ('allergy', '请单独记住这条重要信息：我对花生严重过敏，曾经因此住院，以后推荐食物一定要避开花生。', '花生', 9, 10),
]
PROFILE = '你叫云杉，是成年独角兽，性格温和，重视准确记忆。'


def assess(rows):
    checks = []
    for name, _text, term, low, high in SAMPLES:
        matches = [r for r in rows if term in r['content'] and r['category'] not in
                   ('relationship_page', 'relationship_state', 'daily', 'weekly', 'monthly', 'annual')]
        checks.append({'case':name, 'scores':[r['importance'] for r in matches],
                       'passed':bool(matches) and all(low <= r['importance'] <= high for r in matches)})
    return checks


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
    print('Foreground scoring finished', flush=True)
    background_char = records['background'][0]
    jobs.enqueue(database.db_path, username, background_char, immediate=True)
    async def profile(*_):
        return PROFILE
    background = await jobs.run_one(database.db_path, config.model_manager.get_model_for_task('normal'), profile,
        username=username, character_id=background_char, harness_runner=run_harness_turn, relationship_only=False)
    back = service.memories(database.db_path, username, background_char)
    checks = {'foreground':assess(front), 'background':assess(back)}
    return {'passed':response.status_code == 200 and all(c['passed'] for lane in checks.values() for c in lane),
            'status':response.status_code, 'elapsed_seconds':round(time.monotonic()-started,3),
            'model':MODEL, 'synthetic_only':True, 'production_database_opened':False,
            'source_revision':json.loads((workspace/'Backend/.deploy_revision').read_text())['deploy_token'],
            'samples':SAMPLES, 'checks':checks, 'foreground':front, 'foreground_calls':observed,
            'sse':response.text, 'background':back, 'background_result':background}


if __name__ == '__main__':
    smoke._exercise = exercise
    raise SystemExit(smoke.main())
