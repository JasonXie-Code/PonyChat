"""Synthetic real-Agent probes for disconnects, participant identity and plans."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

import smoke_deployed_harness as smoke


async def _exercise(workspace, fixtures=None):
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from Backend.db.settings_dao import SettingsDAO
    from Backend.agent_memory import jobs
    from Backend.background_jobs import drain_background_jobs, active_background_jobs
    from Backend.chat_modules import harness_runtime

    config.httpx_client = httpx.AsyncClient(timeout=600)
    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
    await db.init()
    jobs.initialize(db.db_path)
    username, password = 'System', secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='admin')
    original = harness_runtime.run_harness_turn
    calls, characters, cases = [], [], []
    began = time.monotonic()

    async def observed(*args, **kwargs):
        prompt = json.loads(args[0])
        sources = {key: prompt.get(key) for key in
                   ('recent_raw_messages', 'current_user_batch', 'latest_user_message')}
        started = time.monotonic()
        try:
            result = await original(*args, **kwargs)
        except Exception as exc:
            # Preserve failures as failures, without exposing SDK credentials or
            # hidden reasoning through arbitrary exception text.
            import traceback
            calls.append({'final_response': None, 'finish_reason': 'error',
                          'error_type': type(exc).__name__,
                          'error_frames': [f.name for f in traceback.extract_tb(exc.__traceback__)[-8:]],
                          'elapsed_seconds': round(time.monotonic()-started, 3),
                          'participants': prompt.get('participants'), 'source_messages': sources})
            raise
        calls.append({'final_response': result.get('final_response'),
                      'finish_reason': result.get('finish_reason'),
                      'participants': prompt.get('participants'),
                      'llm_api_calls': result.get('llm_api_calls'),
                      'runtime_reused': result.get('runtime_reused'),
                      'elapsed_seconds': round(time.monotonic()-started, 3),
                      'source_messages': sources})
        return result
    harness_runtime.run_harness_turn = observed

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                base_url='http://isolated', timeout=600) as client:
        login = await client.post('/api/auth/login', json={'username': username, 'password': password})
        assert login.status_code == 200
        headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'android'}

        async def turn(label, text, history, *, user_species='人类', character_species='陆马', disconnect=None):
            await SettingsDAO(db).save_settings(username, {
                'share_with_ai': True, 'species_preset': user_species,
                'species_custom': '', 'proactive_messages_enabled': False})
            char, conv = 'reliability_' + secrets.token_hex(5), 'reliability_' + secrets.token_hex(5)
            profile = {'id': char, 'name': '云绒', 'profileSpecies': character_species,
                'profileGender': '女', 'profileAge': '25',
                'profileIntro': '活泼、直接，有自己的想法，喜欢分享有趣的小事。',
                'prompt': f'云绒是成年{character_species}，活泼直接，喜欢聊天和开玩笑。住在街角的木屋。',
                'bio': '合成验收角色'}
            characters.append(profile)
            assert await CharactersDAO(db).save_characters(username, characters)
            now = int(time.time()*1000)
            past = [{'id': f'{conv}_{i}', 'message_id': f'{conv}_{i}', 'role': role,
                     'content': content, 'timestamp': now-(len(history)-i)*10000, 'sequence_number': i+1}
                    for i, (role, content) in enumerate(history)]
            assert await ConversationsDAO(db).save_conversation(username, char, {
                'id': conv, 'title': label, 'timestamp': now, 'messages': past})
            mid = conv + '_input'
            body = {'username': username, 'character_id': char, 'conversation_id': conv,
                'mode': 'normal', 'memory_enabled': True, 'voice_enabled': False,
                'messages': [{'role': 'user', 'content': text, 'message_id': mid, 'timestamp': now}]}
            before = len(calls)
            packets, accepted_jobs = [], []
            status = 0
            if disconnect is None:
                response = await client.post('/api/chat', headers=headers, json=body)
                status, packets = response.status_code, [response.text]
            else:
                gone, sent_request = asyncio.Event(), False
                payload = json.dumps(body).encode()
                async def receive():
                    nonlocal sent_request
                    if not sent_request:
                        sent_request = True
                        return {'type': 'http.request', 'body': payload, 'more_body': False}
                    await gone.wait()
                    return {'type': 'http.disconnect'}
                async def send(event):
                    nonlocal status
                    if event['type'] == 'http.response.start':
                        status = event['status']
                    if event['type'] == 'http.response.body':
                        packet = event.get('body', b'').decode()
                        packets.append(packet)
                        if '"type": "accepted"' in packet and not gone.is_set():
                            accepted_jobs.extend(active_background_jobs())
                            if disconnect:
                                await asyncio.sleep(disconnect)
                            gone.set()
                scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.0'},
                    'http_version': '1.1', 'method': 'POST', 'scheme': 'http', 'path': '/api/chat',
                    'raw_path': b'/api/chat', 'query_string': b'', 'root_path': '',
                    'headers': [(k.lower().encode(), v.encode()) for k,v in headers.items()] +
                               [(b'content-type', b'application/json')],
                    'client': ('127.0.0.1', 49100), 'server': ('isolated', 80)}
                await asyncio.wait_for(config.app(scope, receive, send), 180)
                await drain_background_jobs(180)
            with sqlite3.connect(db.db_path) as con:
                replies = [{'message_id': r[0], 'content': r[1]} for r in con.execute(
                    "SELECT message_id,content FROM messages WHERE conversation_id=? AND role='assistant' "
                    "AND timestamp>=? AND deleted_at IS NULL AND COALESCE(is_hidden,0)=0 ORDER BY timestamp,sequence_number,rowid",
                    (conv, now))]
                user_count = con.execute('SELECT COUNT(*) FROM messages WHERE conversation_id=? AND message_id=?', (conv,mid)).fetchone()[0]
            # The same DAO used by the sync route must expose the completed reply
            # after the initiating SSE connection has disappeared.
            loaded = await ConversationsDAO(db).load_conversations(username, char)
            synced = [m for c in loaded for m in c.get('messages', []) if m.get('message_id') in {r['message_id'] for r in replies}]
            events = [json.loads(line[6:]) for line in ''.join(packets).splitlines()
                      if line.startswith('data: ') and line[6:] != '[DONE]']
            case = {'label': label, 'input': text, 'history': history,
                'user_species': user_species, 'character_species': character_species,
                'disconnect_after_accept_seconds': disconnect, 'status': status,
                'accepted_jobs': accepted_jobs, 'replies': replies, 'synced_reply_count': len(synced),
                'user_message_count': user_count, 'raw_model_responses': calls[before:],
                'errors': [e for e in events if e.get('type') == 'error' or 'error' in e],
                'passed': status == 200 and bool(replies) and len(synced) == len(replies) and user_count == 1}
            case['passed'] &= not case['errors']
            cases.append(case)

        if fixtures is not None:
            for fixture in fixtures:
                await turn(fixture['label'], fixture['input'], fixture['history'])
                cases[-1]['expected_semantics'] = fixture['expected']
        else:
            await standard_cases(turn)
    return {'passed': all(c['passed'] for c in cases), 'status': 200, 'cases': cases,
        'semantic_review': 'Review verbatim replies separately; passed above checks delivery, not unrestricted semantics.',
        'synthetic_only': True, 'production_database_opened': False,
        'elapsed_seconds': round(time.monotonic()-began, 3)}


async def standard_cases(turn):
    base = [('user', '我们还在河边的栏杆旁，我手里只有吃完的零食空袋。'),
            ('assistant', '要是回家的话，我还想把新买的芝士藏到枕头底下，改天再拿出来。')]
    await turn('human_hand_and_unfinished_plan', '（我牵起你的蹄子）那我们去你那边吧', base)
    await turn('planned_drawer_not_existing_resource', '我想用彩带包礼物，你那儿现在有吗？', [
        ('user', '我们还没有去商店，也没有买彩带，现在在街口。'),
        ('assistant', '等买到了，我想把那卷蓝色彩带收到书桌抽屉里。')])
    await turn('completed_storage_can_be_recalled', '彩带在哪里？', [
        ('user', '刚才我们已经买好彩带回到屋里，你把那卷蓝色彩带放进书桌抽屉了。'),
        ('assistant', '好，彩带放好了。')])
    await turn('pony_user_human_character', '（我把前蹄搭在你的手心）带我走到门口吧。', [
        ('user', '我们在木屋的客厅里。'), ('assistant', '我站在你旁边。')],
        user_species='陆马', character_species='人类')
    await turn('explicit_temporary_transformation', '（我暂时变成了陆马，把前蹄搭在你的前蹄上）我们出门吧。', [
        ('user', '我们在木屋门口。'), ('assistant', '好，我在门边等你。')])
    if os.environ.get('PONYCHAT_RELIABILITY_SKIP_DISCONNECT') != '1':
        for delay in (0, 1):
            await turn('disconnect_' + str(delay), '重新用中文写一遍。', [
                ('user', '请用英文说你想去哪里散步。'),
                ('assistant', 'I want to take a quiet walk by the river.')], disconnect=delay)


async def exercise(workspace):
    try:
        return await _exercise(workspace)
    finally:
        if 'Backend.db' in sys.modules:
            await sys.modules['Backend.db'].get_database().close()
        config = sys.modules.get('Backend.config')
        if config:
            if config.httpx_client is not None:
                await config.httpx_client.aclose()
            config._queue_listener.stop()
            config._file_handler.close()


if __name__ == '__main__':
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
