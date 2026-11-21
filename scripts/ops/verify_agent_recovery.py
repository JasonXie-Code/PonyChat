"""Real-model, isolated database recovery checks for all three chat modes."""
import asyncio
import json
from pathlib import Path
import secrets
import sys
import time

import smoke_deployed_harness as smoke
from verify_normal_reliability import exercise as cleanup_exercise


async def disconnected_post(app, body, headers, marker):
    gone, delivered = asyncio.Event(), False
    packets = []
    payload = json.dumps(body).encode()
    status = 0
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
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
            if marker in packet:
                gone.set()
    scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.0'},
        'http_version': '1.1', 'method': 'POST', 'scheme': 'http', 'path': '/api/chat',
        'raw_path': b'/api/chat', 'query_string': b'', 'root_path': '',
        'headers': [(k.lower().encode(), v.encode()) for k,v in headers.items()] +
                   [(b'content-type', b'application/json')],
        'client': ('127.0.0.1', 49101), 'server': ('isolated', 80)}
    await asyncio.wait_for(app(scope, receive, send), 600)
    return {'status': status, 'disconnected': gone.is_set(), 'packets': packets}


async def _exercise(workspace):
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    from Backend import config
    from Backend.db import get_database, get_users_dao, CharactersDAO, ConversationsDAO
    from Backend.db.settings_dao import SettingsDAO
    from Backend.agent_memory import jobs
    from Backend.background_jobs import drain_background_jobs
    from Backend.chat_modules import harness_runtime
    from Backend.galgame import harness as game_harness
    from Backend.utils import load_galgame_state_async
    from Backend.galgame.memory import wait_for_pending_char_memory
    config.httpx_client = httpx.AsyncClient(timeout=600)
    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
    await db.init()
    jobs.initialize(db.db_path)
    username, password = 'System', secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='admin')
    from Backend.db import get_membership_dao
    assert await get_membership_dao().set_membership_by_username(
        username, 'developer', None, note='isolated recovery acceptance fixture')
    await SettingsDAO(db).save_settings(username, {'share_with_ai': True, 'species_preset': '人类',
                                                'proactive_messages_enabled': False})
    profiles, cases, calls = [], [], []
    original = harness_runtime.run_harness_turn
    model_started = asyncio.Event()
    async def observed(*args, **kwargs):
        channel = kwargs.get('input_channel')
        item = {'mode': json.loads(args[0]).get('mode', 'normal'), 'channel': bool(channel)}
        calls.append(item)
        model_started.set()
        try:
            result = await original(*args, **kwargs)
            item.update(final_response=result.get('final_response'), finish_reason=result.get('finish_reason'),
                        llm_api_calls=result.get('llm_api_calls'),
                        input_receipts=list(channel.input_receipts) if channel else [])
            return result
        except BaseException as exc:
            item['error'] = type(exc).__name__ + ': ' + str(exc)
            raise
    harness_runtime.run_harness_turn = observed
    game_harness.run_harness_turn = observed
    began = time.monotonic()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                base_url='http://isolated', timeout=600) as client:
        login = await client.post('/api/auth/login', json={'username': username, 'password': password})
        assert login.status_code == 200
        headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'android',
                   'Accept': 'text/event-stream'}
        async def setup(mode):
            char, conv = 'recovery_' + secrets.token_hex(5), 'recovery_' + secrets.token_hex(5)
            profiles.append({'id': char, 'name': '云杉', 'profileSpecies': '独角兽', 'profileGender': '女',
                'profileAge': '25', 'prompt': '云杉是成年独角兽小马，温和、好奇、有自己的想法。喜欢读书和观察星星。',
                'bio': '合成验收角色'})
            assert await CharactersDAO(db).save_characters(username, profiles)
            if mode == 'normal':
                assert await ConversationsDAO(db).save_conversation(username, char,
                    {'id': conv, 'title': 'synthetic', 'timestamp': int(time.time()*1000), 'messages': []})
            return {'username': username, 'character_id': char, 'conversation_id': conv, 'mode': mode,
                    'memory_enabled': True, 'voice_enabled': False, 'messages': []}
        def message(text):
            return {'role': 'user', 'content': text, 'message_id': 'input_' + secrets.token_hex(5),
                    'timestamp': int(time.time()*1000)}

        body = await setup('normal')
        body['messages'] = [message('我们现在在街口，我原本想去河边散步。你想陪我去吗？')]
        first = asyncio.create_task(disconnected_post(config.app, body, headers, '"type": "accepted"'))
        await asyncio.wait_for(model_started.wait(), 180)
        await asyncio.sleep(1)
        supplement = {**body, 'messages': [message('补充一下，我改主意了，现在去图书馆，不去河边。请用中文回应。')]}
        second = await client.post('/api/chat', json=supplement, headers=headers)
        detached = await first
        await drain_background_jobs(240)
        before_retry = len(calls)
        replay = await client.post('/api/chat', json=supplement, headers=headers)
        saved = await ConversationsDAO(db).load_conversations(username, body['character_id'])
        rows = [m for c in saved for m in c.get('messages', [])]
        replies = [m.get('content') for m in rows if m.get('role') == 'assistant']
        mids = [m.get('message_id') for m in rows]
        case = {'label': 'normal_live_supplement_and_reconnect', 'mode': 'normal', 'input': body['messages'],
                'supplement': supplement['messages'], 'detached': detached,
                'response': second.text, 'replies': replies, 'raw_model_responses': list(calls),
                'agent_invocations': before_retry, 'agent_invocations_after_replay': len(calls),
                'passed': detached['disconnected'] and second.status_code == replay.status_code == 200
                and bool(replies) and before_retry == len(calls) == 1
                and bool(calls[0].get('input_receipts')) and len(mids) == len(set(mids))}
        cases.append(case)

        for mode in ('galgame', 'galgame_lock'):
            body = await setup(mode)
            body['messages'] = [message('时间=下午，地点=图书馆，季节=春天。你好，我想找一本关于星星的书。')]
            start = len(calls)
            opening = await client.post('/api/chat', json=body, headers=headers)
            await wait_for_pending_char_memory(username, body['character_id'], mode)
            old = await load_galgame_state_async(username, body['character_id'], game_type=mode)
            body['messages'] = [message('谢谢，我在桌边坐下，翻开你递来的书。你喜欢哪一页？')]
            detached = await disconnected_post(config.app, body, headers, '"type": "step"')
            await drain_background_jobs(600)
            await wait_for_pending_char_memory(username, body['character_id'], mode)
            after = await load_galgame_state_async(username, body['character_id'], game_type=mode)
            params = {'username': username, 'character_id': body['character_id'], 'mode': mode}
            pulls = [await client.get('/api/conversation/detail', headers=headers, params=params) for _ in range(2)]
            final = await load_galgame_state_async(username, body['character_id'], game_type=mode)
            old_ai = [m for m in old.get('messages', []) if m.get('role') == 'assistant']
            new_ai = [m for m in after.get('messages', []) if m.get('role') == 'assistant']
            state_keys = ('score', 'char_vitals', 'char_mood', 'organ_fill', 'messages')
            stable = all(after.get(k) == final.get(k) for k in state_keys)
            pulled_messages = pulls[-1].json().get('messages', [])
            restored_reply = any(m.get('message_id') == new_ai[-1].get('message_id')
                and m.get('rawContent') == new_ai[-1].get('rawContent') for m in pulled_messages) if new_ai else False
            successful_calls = [c for c in calls[start:] if c.get('finish_reason') == 'completed']
            cases.append({'label': mode + '_disconnect_and_repeated_pull', 'mode': mode,
                'opening_status': opening.status_code, 'opening_response': opening.text,
                'input': body['messages'], 'detached': detached, 'raw_model_responses': calls[start:],
                'assistant_count_before': len(old_ai), 'assistant_count_after': len(new_ai),
                'restored_state': {k: after.get(k) for k in state_keys},
                'pull_status': [p.status_code for p in pulls], 'pulled': pulls[-1].json(),
                'stable_after_repeated_pull': stable,
                'passed': detached['disconnected'] and detached['status'] == 200
                and len(new_ai) == len(old_ai) + 1 and len(old_ai) == 1 and stable
                and all(p.status_code == 200 for p in pulls) and len(successful_calls) >= 2
                and restored_reply})
    return {'passed': all(c['passed'] for c in cases), 'status': 200, 'cases': cases,
            'synthetic_only': True, 'production_database_opened': False,
            'elapsed_seconds': round(time.monotonic()-began, 3)}


async def exercise(workspace):
    import verify_normal_reliability as reliability
    reliability._exercise = _exercise
    return await cleanup_exercise(workspace)


if __name__ == '__main__':
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
