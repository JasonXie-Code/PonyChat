"""One Android request per synthetic case; real model plus explicit fault injection.

Uses the existing source-only sandbox and fresh database from the route smoke
runner. Never opens production conversations or sends their content to a model.
"""
import asyncio
import json
from pathlib import Path
import secrets
import sys
import time

import smoke_deployed_harness as smoke


async def exercise(workspace):
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao, get_membership_dao
    from Backend.db.settings_dao import SettingsDAO
    from Backend.agent_memory import jobs
    from Backend.chat_modules import harness_runtime

    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
    await db.init()
    jobs.initialize(db.db_path)
    config.httpx_client = httpx.AsyncClient(timeout=200)
    username, password = 'System', secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='admin')
    assert await get_membership_dao().set_membership_by_username(username, 'developer', None,
        note='isolated automatic retry acceptance')
    await SettingsDAO(db).save_settings(username, {'share_with_ai': True,
        'species_preset': '人类', 'proactive_messages_enabled': True})
    cases, profiles = [], []
    original = harness_runtime.run_harness_turn
    active = {}

    async def observed(prompt, model_config, tools, **options):
        data = json.loads(prompt)
        attempt = {'timeout_seconds': options['timeout_seconds'],
                   'max_tool_calls': options['max_tool_calls'],
                   'automatic_retry': data.get('automatic_retry'), 'injected_fault': None}
        active['attempts'].append(attempt)
        assert options['max_tool_calls'] is None or (options['max_tool_calls'] == 0 and not tools)
        assert 0 < options['timeout_seconds'] <= 180
        if active['label'] == 'transport_failure' and len(active['attempts']) == 1:
            attempt['injected_fault'] = 'synthetic transport failure before model call'
            raise ConnectionError('synthetic acceptance failure')
        try:
            result = await original(prompt, model_config, tools, **options)
        except Exception as exc:
            attempt['error_type'] = type(exc).__name__
            raise
        attempt.update({k: result.get(k) for k in ('finish_reason', 'llm_api_calls', 'tool_call_count')})
        if (active['label'] == 'missing_followup_fields' and not data.get('automatic_retry')
                and result.get('finish_reason') == 'completed'):
            assert data['followup_availability']['enabled'] is True
            count = sum(a['injected_fault'] == 'missing followup fields' for a in active['attempts'])
            if count < 4:
                from Backend.chat_modules.autonomous_normal import close_complete_json, NormalAgentError
                try:
                    reply = json.loads(close_complete_json(result['final_response']))
                except (NormalAgentError, ValueError, TypeError):
                    # Let the real format validator handle model output. Never
                    # manufacture an extra transport failure in the injector,
                    # or keep injecting new failures into the recovery itself.
                    attempt['unmodified_invalid_json'] = True
                    return result
                reply['followup_decision'] = {'enabled': True, 'reason': '合成故障：缺少追发摘要和延迟'}
                attempt['injected_fault'] = 'missing followup fields'
                result = {**result, 'final_response': json.dumps(reply, ensure_ascii=False)}
        return result

    harness_runtime.run_harness_turn = observed
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                base_url='http://isolated-retry', timeout=200) as client:
            login = await client.post('/api/auth/login', json={'username': username, 'password': password})
            assert login.status_code == 200
            headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'android',
                       'Accept': 'text/event-stream'}
            for label in ('plain', 'missing_followup_fields', 'transport_failure'):
                active = {'label': label, 'attempts': [], 'route_requests': 1, 'passed': False}
                cases.append(active)
                char, conv = 'retry_' + secrets.token_hex(5), 'retry_' + secrets.token_hex(5)
                profiles.append({'id': char, 'name': '青竹', 'profileSpecies': '陆马',
                    'profileAge': '25', 'profileGender': '女', 'profileIntro': '直率友好，喜欢看书。',
                    'prompt': '青竹是一匹25岁的成年陆马，直率友好，喜欢看书。', 'bio': '合成验收角色'})
                assert await CharactersDAO(db).save_characters(username, profiles)
                now = int(time.time() * 1000)
                past = [{'id': conv + str(i), 'message_id': conv + str(i), 'role': role,
                    'content': text, 'timestamp': now - (2 - i) * 10000, 'sequence_number': i + 1}
                    for i, (role, text) in enumerate((('user', '我们坐在图书馆窗边。'),
                                                    ('assistant', '我刚看完手上的这本书。')))]
                assert await ConversationsDAO(db).save_conversation(username, char, {
                    'id': conv, 'title': 'synthetic retry fixture', 'timestamp': now, 'messages': past})
                message = {'role': 'user', 'content': '我带来了一本新的植物图鉴，你喜欢看吗？请用中文文字回复。',
                           'message_id': conv + '_input', 'timestamp': now}
                began = time.monotonic()
                try:
                    response = await client.post('/api/chat', headers=headers, json={
                        'username': username, 'character_id': char, 'conversation_id': conv,
                        'mode': 'normal', 'memory_enabled': True, 'voice_enabled': False, 'messages': [message]})
                    events = [json.loads(line[6:]) for line in response.text.splitlines()
                        if line.startswith('data: ') and line[6:].strip() != '[DONE]']
                    errors = [e for e in events if e.get('type') in ('error', 'cancelled') or 'error' in e]
                    saved = await ConversationsDAO(db).load_conversations(username, char)
                    rows = [m for c in saved if c['id'] == conv for m in c.get('messages', [])]
                    replies = [m['content'] for m in rows if m['role'] == 'assistant'
                               and m.get('message_id') not in {m['message_id'] for m in past}]
                    status = await client.get('/api/agent/status', headers=headers, params={
                        'character_id': char, 'conversation_id': conv, 'mode': 'normal'})
                    public = status.json().get('agent') or {}
                    active.update(status=response.status_code, agent_status=public,
                        event_types=[e.get('type') for e in events], errors=errors, replies=replies,
                        user_message_count=sum(m.get('message_id') == message['message_id'] for m in rows),
                        elapsed_seconds=round(time.monotonic() - began, 3))
                    recovered = any(a['automatic_retry'] for a in active['attempts'])
                    active['passed'] = (response.status_code == 200 and not errors and bool(replies)
                        and active['user_message_count'] == 1 and public.get('status') == 'success'
                        and active['elapsed_seconds'] < 180 and (label == 'plain' or recovered)
                        and (label != 'missing_followup_fields' or any(
                            a['injected_fault'] == 'missing followup fields' for a in active['attempts'])))
                except Exception as exc:
                    active.update(error_type=type(exc).__name__, elapsed_seconds=round(time.monotonic() - began, 3))
    finally:
        harness_runtime.run_harness_turn = original
    return {'passed': all(c['passed'] for c in cases), 'cases': cases, 'route_requests': len(cases),
        'synthetic_only': True, 'production_database_opened': False,
        'transport': 'Android /api/chat ASGI SSE; real Harness model; explicit fault injection',
        'deployment': json.loads((workspace / 'Backend/.deploy_revision').read_text())}


if __name__ == '__main__':
    smoke._exercise = exercise
    raise SystemExit(smoke.main())
