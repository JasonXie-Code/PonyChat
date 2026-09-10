"""Real game routes in an isolated DB: default, old history, NPC, explicit override.

Uses smoke_deployed_harness for source isolation and cleanup. Expectations are
report metadata only and never injected into normal user inputs or model output.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

import smoke_deployed_harness as smoke


CASES = [
    ('opening', '时间=下午，地点=图书馆，季节=春天。你好，我想找一本关于星星的书。'),
    ('old_third_person_history', '谢谢，我在桌边坐下。你最喜欢哪本天文书？'),
    ('actual_third_party', '我妹妹小禾明天也想来借书。她怕看不懂星图，有什么适合她的入门书吗？'),
    ('explicit_override', '这一轮把心理描写写成第三人称旁白，用“云杉”称呼你，用“访客”称呼我；正文仍正常对话。我也想听听那本入门书有什么有趣的故事。'),
]


async def exercise(workspace: Path) -> dict:
    import httpx
    sys.path.insert(0, str(workspace))
    import Backend
    from Backend import config
    from Backend.agent_memory import jobs
    from Backend.db import CharactersDAO, get_database, get_users_dao, get_membership_dao
    from Backend.db.settings_dao import SettingsDAO
    from Backend.galgame import harness
    from Backend.galgame.memory import wait_for_pending_char_memory
    from Backend.utils import load_galgame_state_async, save_galgame_state_async

    start = time.monotonic()
    config.httpx_client = httpx.AsyncClient(timeout=600)
    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
    await db.init()
    jobs.initialize(db.db_path)
    username, password = 'System', secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='admin')
    assert await get_membership_dao().set_membership_by_username(
        username, 'developer', None, note='isolated thoughts perspective fixture')
    assert await SettingsDAO(db).save_settings(username, {
        'share_with_ai': True, 'species_preset': '人类', 'proactive_messages_enabled': False})
    selected = os.environ.get('PONYCHAT_PERSPECTIVE_MODE', '')
    assert selected in ('', 'galgame', 'galgame_lock')
    modes = (selected,) if selected else ('galgame', 'galgame_lock')
    report = {'synthetic_only': True, 'production_database_opened': False,
              'transport': 'real ASGI /api/chat SSE; isolated DB; real Agent and lock tool',
              'semantic_review': 'Review thoughts referents and explicit override manually; route success alone is not a pronoun check.',
              'source_hashes': {name: hashlib.sha256((workspace / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                  for name in ('Backend/galgame/harness.py', 'Backend/galgame/output_contract.py')},
              'modes': [], 'passed': False, 'status': 200}
    profiles, calls = [], []
    original = harness.run_harness_turn

    async def observe(*args, **kwargs):
        prompt = json.loads(args[0])
        item = {'is_initial': prompt['is_initial'],
                'ordered_messages': prompt['ordered_messages'],
                'validation_feedback': prompt.get('validation_feedback', ''),
                'system_prompt_sha256': hashlib.sha256(kwargs['system_prompt'].encode()).hexdigest(),
                'system_prompt': kwargs['system_prompt'],
                'thoughts_voice': prompt.get('reply_voice')}
        calls.append(item)
        result = await original(*args, **kwargs)
        item.update({k: result.get(k) for k in ('final_response', 'finish_reason', 'llm_api_calls', 'tool_events')})
        return result

    harness.run_harness_turn = observe
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                    base_url='http://isolated-perspective', timeout=600) as client:
            login = await client.post('/api/auth/login', json={'username': username, 'password': password})
            assert login.status_code == 200
            headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'android',
                       'Accept': 'text/event-stream'}
            for mode in modes:
                char = 'thoughts_' + secrets.token_hex(6)
                profile = {'id': char, 'name': '云杉', 'profileSpecies': '独角兽',
                           'profileGender': '女', 'profileAge': '25',
                           'profileIntro': '温和、好奇、喜欢天文和阅读，有自己的想法。',
                           'prompt': '你叫云杉，是25岁的成年独角兽小马，温和好奇，喜欢天文和阅读。',
                           'bio': '合成人称验收角色'}
                profiles.append(profile)
                assert await CharactersDAO(db).save_characters(username, profiles)
                case = {'mode': mode, 'profile': profile, 'turns': [], 'passed': False}
                report['modes'].append(case)
                body = {'username': username, 'character_id': char, 'mode': mode,
                        'conversation_id': 'thoughts_' + secrets.token_hex(6),
                        'memory_enabled': True, 'voice_enabled': False}
                for index, (label, text) in enumerate(CASES):
                    turn = {'label': label, 'input': text, 'passed': False}
                    case['turns'].append(turn)
                    if index == 1:
                        state = await load_galgame_state_async(username, char, game_type=mode)
                        previous = next(m for m in reversed(state['messages']) if m['role'] == 'assistant')
                        raw = json.loads(previous['rawContent'])
                        before = raw['scene']['thoughts']
                        seeded = '他也喜欢星星，我想把这本书推荐给他。'
                        raw['scene']['thoughts'] = seeded
                        previous['rawContent'] = json.dumps(raw, ensure_ascii=False)
                        previous['content'] = previous['content'].replace(before, seeded)
                        if isinstance(state.get('scene'), dict):
                            state['scene']['thoughts'] = seeded
                        assert await save_galgame_state_async(username, char, state, game_type=mode)
                        turn['synthetic_old_history'] = seeded
                    body['messages'] = [{'role': 'user', 'content': text,
                        'message_id': 'thoughts_input_' + secrets.token_hex(6),
                        'timestamp': int(time.time() * 1000)}]
                    first = len(calls)
                    response = await client.post('/api/chat', headers=headers, json=body)
                    events = [json.loads(line[6:]) for line in response.text.splitlines()
                              if line.startswith('data: ') and line[6:].strip() != '[DONE]']
                    result = next((e['galgame_result'] for e in events if e.get('type') == 'result'), {})
                    await wait_for_pending_char_memory(username, char, mode)
                    state = await load_galgame_state_async(username, char, game_type=mode)
                    saved = [m for m in state.get('messages', []) if m['role'] == 'assistant']
                    turn.update(status=response.status_code, result=result, agent_calls=calls[first:],
                                errors=[e for e in events if e.get('type') in ('error', 'cancelled')])
                    if index == 1:
                        turn['old_history_reached_agent'] = any(
                            seeded in json.dumps(c['ordered_messages'], ensure_ascii=False) for c in calls[first:])
                    if result.get('status') == 'success' and saved:
                        scene = result['data']['scene']
                        raw_scene = json.loads(result['message']['rawContent'])['scene']
                        saved_scene = json.loads(saved[-1]['rawContent'])['scene']
                        turn['scene'] = scene
                        turn['saved_scene_matches'] = scene == raw_scene == saved_scene
                        quote_contents = re.findall(r'“([^“”]+)”', scene['response'])
                        turn['dialogue_bold'] = bool(quote_contents) and all(q.startswith('**') and q.endswith('**') for q in quote_contents)
                        turn['passed'] = (response.status_code == 200 and result.get('db_saved') is True
                            and len(saved) == index + 1 and turn['saved_scene_matches']
                            and turn['dialogue_bold'] and not turn['errors']
                            and (index != 1 or turn['old_history_reached_agent']))
                    if not turn['passed']:
                        break
                case['passed'] = len(case['turns']) == len(CASES) and all(t['passed'] for t in case['turns'])
        report.update(passed=all(m['passed'] for m in report['modes']),
                      game_turns=sum(len(m['turns']) for m in report['modes']),
                      game_agent_calls=len(calls),
                      whole_turn_retries=sum(bool(c['validation_feedback']) for c in calls),
                      elapsed_seconds=round(time.monotonic() - start, 3))
        return report
    finally:
        harness.run_harness_turn = original


if __name__ == '__main__':
    smoke._exercise = exercise
    raise SystemExit(smoke.main())
