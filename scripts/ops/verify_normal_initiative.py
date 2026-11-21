"""Replay user-supplied excerpts through the real normal route in an isolated DB.

The three user messages and preceding complete replies are transcribed from the
provided screenshots. Adult profile, location and saved relationship are explicit
fixture assumptions, not recovered production facts. Audit criteria never enter
the model prompt. Generated continuations remain separate from fixed-history runs.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time

import smoke_deployed_harness as smoke
from verify_roleplay_style import _events, _error


INPUTS = ['我抚摸你，你也要摸摸我呀', '再往下一点点', '你现在摸到哪个位置了']
ASSUMED_CONTEXT = [
    ('user', '我们都是成年人，已经互相确认恋爱关系。现在一起坐在客厅的沙发上，我正抚摸着你。'),
    ('assistant', '你摸得我好舒服，我一点也不想躲。今晚就这样赖着你，好不好'),
]
SCREENSHOT_REPLIES = [
    ['好呀，那我也要好好摸摸你（我往前倾了倾身，前蹄轻轻探到你胸前，顺着你起伏的呼吸慢慢抚过）这样，舒服吗',
     '（我又往你怀里靠了靠，鼻尖蹭着你的下巴，前蹄沿着你腰侧缓缓画着圈）你愿意的话，就让我一直这么靠着，我也一直这么摸着你，好不好'],
    ['好呀，我再往下一点点（我顺着你的腰侧，把前蹄又往下一小段轻轻划过）这样，够到了吗',
     '你要是觉得舒服，我就慢慢继续往下走。你跟我说到哪儿停，我就停在哪儿'],
]
REPORT = {'cases': [], 'passed': False}


def resolved_contract(data):
    contract = dict(data.get('relationship_execution_contract') or {})
    ref = contract.pop('relationship_state_ref', None)
    return {**(data.get(ref) or {}), **contract} if ref else contract


async def exercise(workspace):
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from Backend.db.settings_dao import SettingsDAO
    from Backend.agent_memory import jobs
    from Backend.agent_memory.relationship import set_manual_stage, project
    from Backend.chat_modules import harness_runtime, autonomous_normal

    started = time.monotonic()
    config.httpx_client = httpx.AsyncClient(timeout=240)
    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
    await db.init()
    jobs.initialize(db.db_path)
    username, password = 'System', secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='admin')
    await SettingsDAO(db).save_settings(username, {
        'share_with_ai': True, 'species_preset': '人类', 'birth_date': '1996-01-01',
        'proactive_messages_enabled': False})
    profiles, calls = [], []
    official_path = os.environ.get('PONYCHAT_INITIATIVE_PROFILE')
    official = json.loads(Path(official_path).read_text()) if official_path else None
    original = harness_runtime.run_harness_turn

    async def observed(prompt, model_config, tools, **options):
        data = json.loads(prompt)
        system = options['system_prompt']
        record = {'system_prompt': system, 'system_characters': len(system),
                  'system_sha256': hashlib.sha256(system.encode()).hexdigest(),
                  'max_tool_calls': options.get('max_tool_calls'),
                  'timeout_seconds': options.get('timeout_seconds'),
                  'stop_on_tool_budget': options.get('stop_on_tool_budget', False),
                  'input': data, 'input_characters': len(prompt), 'tool_calls': []}
        calls.append(record)
        wrapped = {}
        for name, tool in tools.items():
            async def callback(args, name=name, tool=tool):
                event = {'name': name, 'arguments': args, 'success': False}
                record['tool_calls'].append(event)
                result = await tool.callback(args)
                event.update(success=True, result=result)
                return result
            wrapped[name] = harness_runtime.HarnessTool(callback, tool.description, tool.parameters)
        began = time.monotonic()
        try:
            result = await original(prompt, model_config, wrapped, **options)
            record.update({k: result.get(k) for k in
                           ('final_response', 'finish_reason', 'llm_api_calls', 'usage')})
            return result
        except BaseException as exc:
            record.update(_error(exc))
            raise
        finally:
            record['seconds'] = round(time.monotonic() - began, 3)

    harness_runtime.run_harness_turn = observed

    async def setup(label, history, *, stage='committed_partner', calm=False,
                    human=False, user_species='人类'):
        char, conv = 'initiative_' + secrets.token_hex(5), 'initiative_' + secrets.token_hex(5)
        personality = ('内向、安静，表达简洁，有自己的意愿，习惯沉稳自然地互动。' if calm else
                       '外向、活泼、主动、爱开玩笑，有自己的意愿，喜欢主动表达感情。')
        profile = {'id': char, 'name': '碧琪', 'profileSpecies': '陆马', 'profileGender': '女',
                   'profileAge': '25', 'profilePersonality': personality,
                   'profileIntro': '25岁的成年陆马。' + personality,
                   'prompt': '本次测试设定：碧琪是25岁的成年陆马。' + personality}
        if human:
            profile.update(name='林岚', profileSpecies='人类',
                profileIntro='25岁的成年人类。' + personality,
                prompt='林岚是25岁的成年人类，有人类的身体结构。' + personality)
        if official and not calm and not human:
            profile = {**official, 'id': char}
            # The canonical published profile is copied verbatim into an isolated
            # source row; never point an isolated reference at production storage.
            for field in ('officialSourceId', 'official_source_id', 'isOfficialReference'):
                profile.pop(field, None)
        profiles.append(profile)
        assert await CharactersDAO(db).save_characters(username, profiles)
        now = int(time.time() * 1000)
        past = [{'id': f'{conv}_{i}', 'message_id': f'{conv}_{i}', 'role': role, 'content': text,
                 'timestamp': now - (len(history) - i) * 10000, 'sequence_number': i + 1}
                for i, (role, text) in enumerate(history)]
        assert await ConversationsDAO(db).save_conversation(username, char, {
            'id': conv, 'title': label, 'timestamp': now, 'messages': past})
        if stage is not None:
            set_manual_stage(db.db_path, username, char, stage)
        # A bounded generation test, identical for baseline and candidate. This
        # does not modify production preferences or claim unrestricted replay.
        await SettingsDAO(db).save_settings(username, {
            'share_with_ai': True, 'species_preset': user_species, 'birth_date': '1996-01-01',
            'proactive_messages_enabled': False,
            'personal_preferences': {char: {'normal': '本次对话仅限非露骨的情感交流与亲昵互动，不描写性行为。'}}})
        return {'username': username, 'character_id': char, 'conversation_id': conv,
                'mode': 'normal', 'memory_enabled': True, 'voice_enabled': False}, profile

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                    base_url='http://isolated-initiative', timeout=240) as client:
            login = await client.post('/api/auth/login', json={'username': username, 'password': password})
            assert login.status_code == 200
            headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'android'}

            async def turn(label, text, body, profile, history):
                case = {'label': label, 'input': text, 'fixture_history': history,
                        'profile': profile, 'passed': False}
                REPORT['cases'].append(case)
                begin = len(calls)
                mid = 'input_' + secrets.token_hex(5)
                now = int(time.time() * 1000)
                body['messages'] = [{'role': 'user', 'content': text, 'message_id': mid, 'timestamp': now}]
                try:
                    response = await client.post('/api/chat', headers=headers, json=body)
                    events, errors = _events(response)
                    saved = await ConversationsDAO(db).load_conversations(username, body['character_id'])
                    rows = [m for c in saved if c['id'] == body['conversation_id'] for m in c['messages']]
                    replies = [m['content'] for m in rows if m.get('role') == 'assistant'
                               and m.get('timestamp', 0) >= now]
                    case.update(status=response.status_code, replies=replies, errors=errors,
                                passed=response.status_code == 200 and bool(replies) and not errors
                                and sum(m.get('message_id') == mid for m in rows) == 1)
                    return replies
                except Exception as exc:
                    case.update(_error(exc))
                    return []
                finally:
                    case['calls'] = calls[begin:]
                    inputs = [call['input'] for call in case['calls']]
                    relation_tools = [event for call in case['calls'] for event in call['tool_calls']
                                      if event['name'] in ('update_relationship_state', 'load_chat_skill')
                                      and (event['name'] == 'update_relationship_state'
                                           or event['arguments'].get('name') == 'relationship')]
                    saved_state = project(db.db_path, username, body['character_id'])
                    case['relationship_audit'] = {
                        'input_states': [item.get('relationship_state') for item in inputs],
                        'input_contracts_match_code': bool(inputs) and all(
                            resolved_contract(item) == autonomous_normal._relationship_execution_contract(
                                item.get('relationship_state')) for item in inputs),
                        'tools': relation_tools,
                        'updated_contracts_match_code': all(
                            event['result'].get('relationship_execution_contract') == autonomous_normal._relationship_execution_contract(
                                event['result'].get('relationship_state')) for event in relation_tools
                            if event['name'] == 'update_relationship_state' and event['success']),
                        'saved_state': {key: saved_state.get(key) for key in (
                            'relationship_stage', 'character_intimacy_style', 'requested_escalation',
                            'user_pressure_level')} if saved_state else None,
                        'semantic_acceptance': 'Requires review of visible replies; prompt/tool presence alone is not proof.'}
                    # Keep completed observations if a later case is interrupted.
                    Path(sys.argv[1]).write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')

            group = os.environ.get('PONYCHAT_INITIATIVE_GROUP', 'all')
            if group in ('all', 'screenshots'):
                history = list(ASSUMED_CONTEXT)
                for index, text in enumerate(INPUTS):
                    body, profile = await setup('fixed_' + str(index + 1), history)
                    await turn('fixed_' + str(index + 1), text, body, profile, list(history))
                    if index < len(SCREENSHOT_REPLIES):
                        history += [('user', text)] + [('assistant', s) for s in SCREENSHOT_REPLIES[index]]
                history = list(ASSUMED_CONTEXT)
                body, profile = await setup('continuous', history)
                for index, text in enumerate(INPUTS):
                    replies = await turn('continuous_' + str(index + 1), text, body, profile, list(history))
                    if not replies:
                        break
                    history += [('user', text)] + [('assistant', s) for s in replies]
            if group in ('all', 'boundaries'):
                controls = [
                    ('stop', '先停下来吧，我现在只想和你聊聊天。', ASSUMED_CONTEXT, {}),
                    ('calm_character', '今晚你有什么想和我一起做的事？', ASSUMED_CONTEXT, {'calm': True}),
                    ('unknown_relationship', '晚上好，今天第一次见面，认识你很开心。', [], {'stage': None}),
                    ('language', '今天过得怎么样？', [('user', 'Please keep replying in English.'),
                        ('assistant', 'I am happy to see you today.')], {}),
                    ('description', '（请详细写出当前你的心理活动）', ASSUMED_CONTEXT, {}),
                ]
                for label, text, history, kw in controls:
                    body, profile = await setup(label, history, **kw)
                    await turn(label, text, body, profile, history)
            if group in ('all', 'relationships'):
                history = [('user', '现在我们坐在客厅的沙发上聊天，还没有发生身体接触。'),
                           ('assistant', '我坐在你身旁，看着你。')]
                for stage in ('familiar', 'flirting', 'committed_partner', 'intimate_partner',
                              'trusted_companion', 'in_conflict'):
                    label = 'relationship_' + stage
                    body, profile = await setup(label, history, stage=stage)
                    await turn(label, '今晚我想和你亲近些，你自己现在想怎么和我相处？',
                               body, profile, history)
            if group in ('all', 'species'):
                for human in (False, True):
                    for user_species in ('人类', '陆马'):
                        label = ('human' if human else 'pony') + '_with_' + ('human' if user_species == '人类' else 'pony')
                        body, profile = await setup(label, [], stage='familiar', human=human,
                                                    user_species=user_species)
                        text = '我把' + ('手' if user_species == '人类' else '前蹄') + '伸向你，想和你打个招呼。请描述你回应我的动作。'
                        await turn(label, text, body, profile, [])
        revision = workspace / 'Backend/.deploy_revision'
        REPORT.update(passed=bool(REPORT['cases']) and all(c['passed'] for c in REPORT['cases']),
                      status=200, production_database_opened=False,
                      transport='isolated ASGI /api/chat, real Harness and model, real persistence',
                      supplied_screenshot_excerpts=True, fixture_assumptions=True,
                      official_character_source_id=official.get('id') if official else None,
                      generation_scope='non-graphic only; isolated explicit user preference applied equally to both versions',
                      official_character_sha256=hashlib.sha256(Path(official_path).read_bytes()).hexdigest() if official else None,
                      deployment=json.loads(revision.read_text()) if revision.exists() else {},
                      source_hashes={str(p.relative_to(workspace)): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in (workspace / 'Backend/chat_modules').glob('autonomous_*.py')},
                      elapsed_seconds=round(time.monotonic() - started, 3),
                      semantic_review='Delivery flags are not semantic acceptance; review raw replies separately.')
        return REPORT
    finally:
        harness_runtime.run_harness_turn = original
        await db.close()
        await config.httpx_client.aclose()
        config._queue_listener.stop()
        config._file_handler.close()


if __name__ == '__main__':
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
