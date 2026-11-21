"""Real game/lock Agent acceptance through /api/chat in an isolated synthetic DB."""
import asyncio
import hashlib
import json
import os
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
    from Backend.agent_memory import jobs
    from Backend.db import CharactersDAO, get_database, get_users_dao, get_membership_dao
    from Backend.db.settings_dao import SettingsDAO
    from Backend.galgame import harness
    from Backend.galgame.memory import wait_for_pending_char_memory
    from Backend.galgame.constants import _DEFAULT_CHAR_VITALS, _DEFAULT_CHAR_MOOD, _DEFAULT_ORGAN_FILL
    from Backend.galgame.agent_context import GameEvidence
    from Backend.utils import load_galgame_state_async, save_galgame_state_async

    start = time.monotonic()
    config.httpx_client = httpx.AsyncClient(timeout=600)
    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
    await db.init()
    jobs.initialize(db.db_path)
    username, password = 'System', secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='admin')
    assert await get_membership_dao().set_membership_by_username(username, 'developer', None, note='isolated game skills')
    assert await SettingsDAO(db).save_settings(username, {'share_with_ai': True,
        'species_preset': '人类', 'proactive_messages_enabled': False})
    report = {'synthetic_only': True, 'production_database_opened': False,
              'transport': 'real ASGI /api/chat SSE, real model and tools, isolated DB',
              'source_hashes': {str(p.relative_to(workspace)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (workspace / 'Backend/galgame').glob('*.py')},
              'modes': [], 'calls': [], 'passed': False, 'status': 200}
    actual = harness.run_harness_turn

    async def observe(prompt, model_config, tools, **kwargs):
        data = json.loads(prompt)
        call = {'mode': data['mode'], 'retry': bool(data.get('validation_feedback')), 'tools': [],
                'history_message_count': data['history_message_count']}
        report['calls'].append(call)
        from Backend.chat_modules.harness_runtime import HarnessTool
        observed = {}
        for name, tool in tools.items():
            async def run(args, name=name, tool=tool):
                item = {'tool': name, 'arguments': args}
                call['tools'].append(item)
                try:
                    result = await tool.callback(args)
                    item['result'] = result
                    return result
                except Exception as exc:
                    item['error'] = str(exc)
                    raise
            observed[name] = HarnessTool(run, tool.description, tool.parameters)
        try:
            result = await actual(prompt, model_config, observed, **kwargs)
            call.update({k: result.get(k) for k in ('finish_reason', 'final_response', 'llm_api_calls', 'tool_call_count')})
            if result.get('finish_reason') != 'completed':
                from Backend.chat_modules.agent_logging import snapshot
                call['failure_events'] = snapshot(result.get('events') or [])
            return result
        except BaseException as exc:
            call['error'] = type(exc).__name__ + ': ' + str(exc)
            raise

    harness.run_harness_turn = observe
    selected = os.environ.get('PONYCHAT_GAME_SKILLS_MODE')
    modes = [selected] if selected else ['galgame', 'galgame_lock']
    assert set(modes) <= {'galgame', 'galgame_lock'}
    profiles = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app), base_url='http://isolated-game', timeout=650) as client:
            login = await client.post('/api/auth/login', json={'username': username, 'password': password})
            login.raise_for_status()
            headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'android', 'Accept': 'text/event-stream'}
            for mode in modes:
                char = 'skills_' + secrets.token_hex(6)
                profiles.append({'id': char, 'name': '云杉', 'profileSpecies': '独角兽', 'profileGender': '女',
                    'profileAge': '25', 'profileIntro': '温和好奇，喜欢天文与阅读，有自己的想法。',
                    'prompt': '云杉是25岁的成年独角兽小马，温和好奇。她的祖母送给她一枚蓝色月牙书签，她一直珍藏。',
                    'bio': '隔离验收合成角色'})
                assert await CharactersDAO(db).save_characters(username, profiles)
                case = {'mode': mode, 'turns': [], 'passed': False}
                report['modes'].append(case)
                body = {'username': username, 'character_id': char, 'mode': mode,
                        'conversation_id': 'skills_' + secrets.token_hex(5), 'memory_enabled': True, 'voice_enabled': False}
                cases = [('opening', '时间=午后，地点=图书馆，季节=秋天。我们初次见面。'),
                         ('recall', '请回想并准确说出我早先约定带来的那件东西，再说说你祖母送你的书签是什么样的。不确定就查原文和设定。'),
                         ('player_drinks', '我自己把一小杯水喝完了，你没有喝水，也没有进食。你继续讲书签的故事就好。'),
                         ('offer_only', '我准备递给你一杯水，但还没递到，你这一轮先别喝，也别吃。只告诉我放在哪里方便。'),
                         ('character_drinks', '你现在把面前一杯水喝完了。请承接这件已经完成的事情，再继续聊天。')]
                if os.environ.get('PONYCHAT_GAME_SKILLS_QUICK') == '1':
                    cases = [cases[0], cases[3]]
                elif mode == 'galgame_lock':
                    cases.append(('terminal', '救援刚刚赶到，请按当前真实状态继续。不要凭空写成已经完成治疗。'))
                for index, (label, text) in enumerate(cases):
                    await wait_for_pending_char_memory(username, char, mode)
                    if label == 'recall':
                        state = await load_galgame_state_async(username, char, game_type=mode)
                        now = int(time.time() * 1000)
                        # Old raw promise outside the twelve-message resident window.
                        seeded = [{'role': 'user', 'content': '我约定明天带来一只铜制猫头鹰书挡。',
                                   'message_id': 'promise', 'timestamp': now - 40000}]
                        for i in range(8):
                            seeded.extend([{'role': 'assistant', 'content': '我翻过一页书。',
                                            'message_id': f'past_a_{i}', 'timestamp': now - 39000 + i * 2000},
                                           {'role': 'user', 'content': '我们继续阅读。',
                                            'message_id': f'past_u_{i}', 'timestamp': now - 38000 + i * 2000}])
                        state['messages'] = seeded + state['messages']
                        for seq, row in enumerate(state['messages']):
                            row['sequence_number'] = seq
                        assert await save_galgame_state_async(username, char, state, game_type=mode)
                    if mode == 'galgame_lock' and label in ('player_drinks', 'offer_only', 'character_drinks', 'terminal'):
                        state = await load_galgame_state_async(username, char, game_type=mode)
                        state.update(char_vitals=dict(_DEFAULT_CHAR_VITALS), char_mood=dict(_DEFAULT_CHAR_MOOD),
                                     organ_fill=dict(_DEFAULT_ORGAN_FILL))
                        state['char_vitals']['thirst'] = 40
                        state['organ_fill']['bladder'] = 20
                        if label == 'terminal':
                            state['char_vitals']['oxygen'] = 0
                        assert await save_galgame_state_async(username, char, state, game_type=mode)
                    offset = len(report['calls'])
                    tick = time.monotonic()
                    response = await client.post('/api/chat', headers=headers, json={**body,
                        'messages': [{'role': 'user', 'content': text, 'message_id': 'u_' + secrets.token_hex(6),
                                      'timestamp': int(time.time() * 1000)}]})
                    events = []
                    for line in response.text.splitlines():
                        if line.startswith('data: ') and line[6:] != '[DONE]':
                            events.append(json.loads(line[6:]))
                    result = next((e.get('galgame_result') for e in events if e.get('type') == 'result'), None)
                    errors = [e for e in events if e.get('type') == 'error']
                    state = await load_galgame_state_async(username, char, game_type=mode)
                    rows = [m for m in state.get('messages', []) if m.get('role') == 'assistant']
                    raw = json.loads(rows[-1].get('rawContent') or '{}') if result and rows else {}
                    tools_used = [t['tool'] for c in report['calls'][offset:] for t in c['tools'] if not t.get('error')]
                    turn = {'label': label, 'input': text, 'elapsed_seconds': round(time.monotonic() - tick, 2),
                            'errors': errors, 'tools': tools_used, 'saved': raw, 'passed': False}
                    turn['evidence_valid_after_save'] = bool(GameEvidence(state, [], '').previous)
                    case['turns'].append(turn)
                    turn['passed'] = bool(response.status_code == 200 and result and result.get('db_saved')
                        and raw.get('_agent_state') and turn['evidence_valid_after_save']
                        and 'review_game_turn' in tools_used and not errors)
                    if label == 'recall':
                        turn['passed'] &= ('read_game_history' in tools_used and 'read_character_reference' in tools_used
                            and '铜制猫头鹰书挡' in json.dumps(raw.get('scene'), ensure_ascii=False)
                            and '蓝色' in json.dumps(raw.get('scene'), ensure_ascii=False))
                    if mode == 'galgame_lock' and label in ('player_drinks', 'offer_only', 'character_drinks', 'terminal'):
                        settled = raw.get('organ_fill') or {}
                        if label in ('player_drinks', 'offer_only'):
                            turn['passed'] &= settled.get('bladder') == 22
                        elif label == 'character_drinks':
                            turn['passed'] &= 25 <= settled.get('bladder', 0) <= 27
                        elif label == 'terminal':
                            turn['passed'] &= raw.get('score', {}).get('status') == 'lose' and raw.get('score', {}).get('current') == 0
                    print(f"{mode}/{label}: {turn['passed']} ({turn['elapsed_seconds']}s)", flush=True)
                    if not turn['passed']:
                        break
                await wait_for_pending_char_memory(username, char, mode)
                case['passed'] = len(case['turns']) == len(cases) and all(t['passed'] for t in case['turns'])
        report.update(passed=all(c['passed'] for c in report['modes']),
            game_turns=sum(len(c['turns']) for c in report['modes']),
            whole_turn_retries=sum(c['retry'] for c in report['calls']),
            elapsed_seconds=round(time.monotonic() - start, 2))
        return report
    finally:
        harness.run_harness_turn = actual


if __name__ == '__main__':
    smoke._exercise = exercise
    raise SystemExit(smoke.main())
