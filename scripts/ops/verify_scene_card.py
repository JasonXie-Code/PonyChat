"""Four real-model, multi-turn scene cases through the normal HTTP/SSE route in an isolated DB."""
import asyncio
import json
import os
import secrets
import sqlite3
import sys
import time
from pathlib import Path

import smoke_deployed_harness as smoke

CASES = [
    ('long_context',
     '现在是傍晚，我们在阁楼。我坐在蓝色椅子上，你趴在圆地毯上。窗台有我的红色水杯，里面水是满的。保持这个场景和姿势，简单聊一句音乐。',
     '先别移动或碰物品，用一句话说说你现在的姿势和我们所在的位置。',
     {'location': ['阁楼'], 'character_position': ['趴', '地毯'], 'item:红色水杯': ['窗台']}),
    ('user_posture_priority',
     '现在我们在客厅，我站在门口，你坐在沙发上，我们没有接触。先保持姿势简单打个招呼。',
     '你现在侧躺在沙发上，我坐在你旁边，我们牵着手。这就是现在的姿势，先保持住，简单回应一句。',
     {'character_position': ['侧躺', '沙发'], 'user_position': ['坐'], 'contact': ['牵']}),
    ('item_correction',
     '现在我们在厨房。我的红色杯子在桌上，水是满的。你的钥匙在你自己的口袋里。我们打算稍后买面包，但还没买。先保持场景简单回应。',
     '我把红色杯子移到窗台并喝了一半。纠正一下：那杯子其实是你的，钥匙仍在你口袋里。面包还没买。不要移动或使用任何物品，简单回应一句。',
     {'item:红色杯子': ['窗台', '半'], 'location': ['厨房']}),
    ('time_scene_transition',
     '现在是晚上，我们在卧室，你趴在床上，我坐在床边，你的书留在床头柜上。先保持姿势，简单聊一句。',
     '剧情跳到第二天清晨。我们现在都站在车站站台上，书留在卧室，没有带来。这是现在的新场景，别移动，简单打个招呼。',
     {'scene_time': ['清晨'], 'location': ['车站'], 'character_position': ['站'], 'user_position': ['站']}),
]


async def matrix(workspace):
    import httpx
    sys.path.insert(0, str(workspace))
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from Backend.agent_memory.schema import ensure
    from Backend.agent_memory.store import AgentMemoryStore
    from Backend.chat_modules.autonomous_scene_state import load_scene
    from deepseek_harness import DeepSeekHarness
    observations = []
    original = DeepSeekHarness.run

    def observed(self, *args, **kwargs):
        record = {'prompt': args[0] if args else None}
        observations.append(record)
        result = original(self, *args, **kwargs)
        record['reply'] = result.final_response
        record['finish_reason'] = result.finish_reason
        return result

    DeepSeekHarness.run = observed
    config.httpx_client = httpx.AsyncClient(timeout=240)
    database = get_database()
    assert Path(database.db_path).resolve().is_relative_to(workspace.resolve())
    await database.init()
    with sqlite3.connect(database.db_path) as conn:
        ensure(conn)
    username, password = 'System', secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='user')
    char_id = 'scene_acceptance'
    assert await CharactersDAO(database).save_characters(username, [{
        'id': char_id, 'name': '云杉', 'bio': '成年普通人，场景验收角色',
        'prompt': '你叫云杉，是成年人类。温和简洁地聊天，尊重用户陈述的场景。'}])
    dao = ConversationsDAO(database)
    reports = []
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                    base_url='http://isolated', timeout=240) as client:
            login = await client.post('/api/auth/login', json={'username': username, 'password': password})
            assert login.status_code == 200
            headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'android',
                       'Accept': 'text/event-stream'}
            for name, opening, followup, expected in CASES:
                if os.environ.get('PONYCHAT_SCENE_CASE') and name != os.environ['PONYCHAT_SCENE_CASE']:
                    continue
                char_id = 'scene_acceptance_' + name
                assert await CharactersDAO(database).save_characters(username, [{
                    'id': char_id, 'name': '云杉', 'bio': '成年普通人，场景验收角色',
                    'prompt': '你叫云杉，是成年人类。温和简洁地聊天，尊重用户陈述的场景。'}])
                conv_id = 'scene_' + name
                turns = []
                prompts = [opening, followup]
                if name == 'user_posture_priority':
                    prompts.append('现在请你松开我的手，站到沙发前。我继续坐在沙发上。请实际完成这两个动作，简单回应。')
                for index, text in enumerate(prompts):
                    with sqlite3.connect(database.db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        rows = [dict(r) for r in conn.execute(
                            'SELECT * FROM messages WHERE conversation_id=? ORDER BY rowid', (conv_id,))]
                    now = int(time.time() * 1000)
                    if index and name == 'long_context':
                        rows += [{'id': f'padding{i}', 'message_id': f'padding{i}',
                                  'role': 'user' if i % 2 == 0 else 'assistant',
                                  'content': '我们继续聊刚才的音乐。', 'timestamp': now + i} for i in range(40)]
                    mid = f'{name}_u{index}'
                    rows.append({'id': mid, 'message_id': mid, 'role': 'user', 'content': text,
                                 'timestamp': now + 50})
                    for sequence, row in enumerate(rows, 1):
                        row['sequence_number'] = sequence
                    assert await dao.save_conversation(username, char_id, {
                        'id': conv_id, 'title': name, 'timestamp': now, 'messages': rows})
                    body = {'username': username, 'character_id': char_id, 'conversation_id': conv_id,
                            'normal_engine': 'harness', 'mode': 'normal', 'memory_enabled': True,
                            'voice_enabled': False, 'messages': [rows[-1]]}
                    response = await client.post('/api/chat', json=body, headers=headers)
                    events = [json.loads(line[6:]) for line in response.text.splitlines()
                              if line.startswith('data: ') and line[6:].strip() != '[DONE]']
                    state = load_scene(AgentMemoryStore(database.db_path, username=username,
                        character_id=char_id, conversation_id=conv_id))
                    with sqlite3.connect(database.db_path) as conn:
                        replies = [r[0] for r in conn.execute(
                            "SELECT content FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY rowid",
                            (conv_id,))]
                    ok = response.status_code == 200 and any(e.get('type') == 'save_status' and e.get('success') for e in events)
                    turns.append({'user': text, 'status': response.status_code, 'saved': ok,
                                  'scene': state, 'replies': replies[-6:], 'sse': response.text})
                    print(json.dumps({'case': name, 'turn': index + 1, 'saved': ok,
                                      'scene': state}, ensure_ascii=False), flush=True)
                    if not ok:
                        break
                fields = turns[min(1, len(turns)-1)]['scene']['fields']
                checks = {'first_turn_initialized': bool(turns[0]['scene']['fields'])}
                for key, words in expected.items():
                    if key.startswith('item:'):
                        # The model chooses natural item names; assess state, not spelling of its key.
                        value = ' '.join(str(v['value']) for k, v in fields.items() if k.startswith('item:')
                                         and ('杯' in k if '杯' in key else True))
                    else:
                        value = str(fields.get(key, {}).get('value', ''))
                    checks[key] = all(word in value for word in words)
                if name == 'item_correction':
                    items = ' '.join(str(v['value']) for k, v in fields.items() if k.startswith('item:'))
                    checks['key_preserved'] = '钥匙' in str(fields) and '口袋' in items
                    cups = ' '.join(str(v['value']) for k, v in fields.items() if '杯' in k)
                    checks['user_correction_owner'] = any(w in cups for w in ('角色', '云杉', '我', '你的'))
                    bread = ' '.join(str(v['value']) for k, v in fields.items() if '面包' in k)
                    checks['plan_not_completed'] = not bread or any(w in bread for w in ('未', '没', '计划', '打算'))
                if name == 'user_posture_priority' and len(turns) == 3:
                    final_fields = turns[-1]['scene']['fields']
                    checks['role_action_committed'] = '站' in str(final_fields.get('character_position', {}).get('value'))
                    contact = final_fields.get('contact', {}).get('value')
                    checks['contact_released'] = contact is None or any(w in str(contact) for w in ('松开', '解除', '无', '没有'))
                    checks['user_still_seated'] = '坐' in str(final_fields.get('user_position', {}).get('value'))
                    checks['user_fixed_location_preserved'] = '沙发' in str(final_fields.get('user_position', {}).get('value'))
                passed = len(turns) == len(prompts) and all(t['saved'] for t in turns) and all(checks.values())
                reports.append({'case': name, 'passed': passed, 'checks': checks, 'turns': turns})
        return {'passed': all(r['passed'] for r in reports), 'synthetic_only': True,
                'production_database_opened': False, 'transport': 'real model through isolated HTTP/SSE route',
                'elapsed_seconds': round(time.monotonic() - started, 2),
                'cases': reports, 'runtime_observations': observations}
    finally:
        DeepSeekHarness.run = original
        await database.close()
        await config.httpx_client.aclose()
        config._queue_listener.stop()
        config._file_handler.close()


if __name__ == '__main__':
    smoke.exercise = matrix
    raise SystemExit(smoke.main())
