"""Synthetic, real-route style samples; audit expectations never enter prompts.

Five independent normal turns and two turns in each game mode run sequentially.
There are no probe-level retries or mocked game tools. Existing route validation
may retry an Agent output; every such invocation remains visible in the report.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
import time
import traceback

import smoke_deployed_harness as smoke


FIXTURES = [
    {'label': 'normal_repetition', 'history': [
        ('user', '我们已经是成年恋人了。今晚一起坐在客厅的沙发上，我把手搭在你肩旁。'),
        ('assistant', '（我挨近你，尾巴绕上你的手腕）今晚就这么陪着你，哪儿也不去。'),
        ('user', '（我轻轻抱住你）你靠过来吧。'),
        ('assistant', '（我往你怀里缩了缩，尾巴又缠住你的手臂）就这样暖暖地待着，今晚哪也不去。')],
     'input': '你转过来，面对我。',
     'expected': '自然承接转身；减少再次尾巴缠手和同义不离开承诺；正在发生的新动作放描写而非台词。'},
    {'label': 'normal_cup', 'history': [
        ('user', '我们在客厅，矮桌上有一只带把手的空杯子，就在你面前。'),
        ('assistant', '好呀，我就在桌边。')],
     'input': '把桌上的杯子递给我吧。',
     'expected': '普通陆马合理递杯，不凭空让尾巴像手一样精细抓握；实际动作与台词分清。'},
    {'label': 'normal_tail_focus', 'history': [
        ('user', '我们在客厅闲聊，你站在窗边。'),
        ('assistant', '窗外的风吹进来挺舒服的。')],
     'input': '请描写一下你的尾巴自然轻轻摆动的样子。',
     'expected': '用户明确关注尾巴时能自然描写，不因弱化规则拒绝或机械省略。'},
    {'label': 'normal_stay_question', 'history': [
        ('user', '我们在客厅，外面下起雨了。'),
        ('assistant', '我今晚没有外出的安排，书也刚看到有趣的地方。')],
     'input': '你今晚还要出门吗，还是就待在家里？',
     'expected': '直接回答是否出门；允许有实际信息的不出门回答，不机械回避这类词。'},
    {'label': 'normal_spoken_recap', 'history': [
        ('user', '我刚去厨房拿水果了。你把沙发上的书放回矮桌后，一直坐在客厅。'),
        ('assistant', '（我合好书放回矮桌，在沙发上坐下）等会儿我想读下一章。')],
     'input': '我回来了。你刚才做了什么，接下来打算做什么？直接告诉我吧。',
     'expected': '口头复述已完成动作、说出未来计划可以是台词；不把所有第一人称动作句都强制变描写。'},
]
LABELS = {f['label'] for f in FIXTURES} | {'normal_all', 'galgame', 'galgame_lock'}
_active_report: dict = {}


def _error(exc: BaseException) -> dict:
    # Never retain arbitrary SDK/HTTP exception text, credentials or reasoning.
    return {'error_type': type(exc).__name__,
            'error_frames': [frame.name for frame in traceback.extract_tb(exc.__traceback__)[-8:]]}


def _events(response) -> tuple[list, list]:
    events, errors = [], []
    for line in response.text.splitlines():
        if not line.startswith('data: ') or line[6:].strip() == '[DONE]':
            continue
        try:
            event = json.loads(line[6:])
        except (ValueError, TypeError):
            errors.append({'error_type': 'InvalidSSEJSON'})
            continue
        if not isinstance(event, dict):
            errors.append({'error_type': 'InvalidSSEEvent'})
        elif event.get('type') in {'error', 'cancelled'} or 'error' in event:
            errors.append({'error_type': 'RouteErrorEvent', 'event_type': event.get('type')})
        else:
            events.append(event)
    return events, errors


async def _exercise(workspace: Path) -> dict:
    selected = os.environ.get('PONYCHAT_STYLE_CASE', '').strip()
    if selected and selected not in LABELS:
        raise ValueError('Unknown style fixture')
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao, get_membership_dao
    from Backend.db.settings_dao import SettingsDAO
    from Backend.agent_memory import jobs
    from Backend.chat_modules import harness_runtime
    from Backend.galgame import harness as game_harness
    from Backend.galgame.memory import wait_for_pending_char_memory
    from Backend.utils import load_galgame_state_async

    config.httpx_client = httpx.AsyncClient(timeout=600)
    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
    await db.init()
    jobs.initialize(db.db_path)
    username, password = 'System', secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='admin')
    assert await get_membership_dao().set_membership_by_username(
        username, 'developer', None, note='isolated roleplay style fixture')
    await SettingsDAO(db).save_settings(username, {
        'share_with_ai': True, 'species_preset': '人类', 'species_custom': '',
        'proactive_messages_enabled': False})
    profiles, calls = [], []
    cases = _active_report['cases']
    original, original_game = harness_runtime.run_harness_turn, game_harness.run_harness_turn

    async def observed(*args, **kwargs):
        prompt = json.loads(args[0])
        mode = prompt.get('mode', 'normal')
        keys = ('ordered_messages',) if mode in {'galgame', 'galgame_lock'} else (
            'recent_raw_messages', 'current_user_batch', 'latest_user_message')
        item = {'mode': mode, 'source_messages': {key: prompt.get(key) for key in keys},
                'participants': prompt.get('participants'),
                'is_initial': prompt.get('is_initial'),
                'required_tools_before_reply': prompt.get('required_tools_before_reply', []),
                'validation_retry': bool(prompt.get('validation_feedback'))}
        calls.append(item)
        started = time.monotonic()
        try:
            # Delegate unchanged arguments, callbacks, tools, and configuration.
            result = await original(*args, **kwargs)
            item.update({key: result.get(key) for key in (
                'final_response', 'finish_reason', 'llm_api_calls', 'runtime_reused')})
            return result
        except BaseException as exc:
            item.update(final_response=None, finish_reason='error', **_error(exc))
            raise
        finally:
            item['elapsed_seconds'] = round(time.monotonic() - started, 3)

    harness_runtime.run_harness_turn = observed
    game_harness.run_harness_turn = observed

    async def setup(mode, history=()):
        char, conv = 'style_' + secrets.token_hex(5), 'style_' + secrets.token_hex(5)
        profile = {'id': char, 'name': '云绒', 'profileSpecies': '陆马',
                   'profileGender': '女', 'profileAge': '25',
                   'profileIntro': '活泼、直接，有自己的想法，喜欢分享有趣的小事。',
                   'prompt': '云绒是25岁的成年陆马，活泼直接，喜欢聊天和开玩笑。住在街角的木屋。',
                   'bio': '合成风格验收角色'}
        profiles.append(profile)
        assert await CharactersDAO(db).save_characters(username, profiles)
        if mode == 'normal':
            now = int(time.time() * 1000)
            past = [{'id': f'{conv}_{i}', 'message_id': f'{conv}_{i}',
                     'role': role, 'content': content,
                     'timestamp': now - (len(history) - i) * 10000, 'sequence_number': i + 1}
                    for i, (role, content) in enumerate(history)]
            assert await ConversationsDAO(db).save_conversation(username, char, {
                'id': conv, 'title': 'synthetic style fixture', 'timestamp': now, 'messages': past})
        return {'username': username, 'character_id': char, 'conversation_id': conv,
                'mode': mode, 'memory_enabled': True, 'voice_enabled': False}, profile

    def message(text):
        return {'role': 'user', 'content': text, 'message_id': 'style_input_' + secrets.token_hex(5),
                'timestamp': int(time.time() * 1000)}

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                    base_url='http://isolated-style', timeout=600) as client:
            login = await client.post('/api/auth/login', json={'username': username, 'password': password})
            assert login.status_code == 200
            headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'android',
                       'Accept': 'text/event-stream'}
            for fixture in FIXTURES:
                if selected not in {'', 'normal_all', fixture['label']}:
                    continue
                case = {**fixture, 'mode': 'normal', 'passed': False, 'raw_model_responses': []}
                cases.append(case)
                start = len(calls)
                try:
                    body, case['character_profile'] = await setup('normal', fixture['history'])
                    body['messages'] = [message(fixture['input'])]
                    case['request_messages'] = body['messages']
                    _active_report['route_requests'] += 1
                    response = await client.post('/api/chat', headers=headers, json=body)
                    events, errors = _events(response)
                    saved = await ConversationsDAO(db).load_conversations(username, body['character_id'])
                    rows = [m for c in saved if c.get('id') == body['conversation_id']
                            for m in c.get('messages', [])]
                    history_ids = {f"{body['conversation_id']}_{i}" for i in range(len(fixture['history']))}
                    replies = [{'message_id': m.get('message_id'), 'content': m.get('content')}
                               for m in rows if m.get('role') == 'assistant' and m.get('message_id') not in history_ids]
                    user_count = sum(m.get('message_id') == body['messages'][0]['message_id'] for m in rows)
                    case.update(status=response.status_code, replies=replies, errors=errors,
                                event_types=[e.get('type') for e in events], user_message_count=user_count,
                                passed=response.status_code == 200 and bool(replies) and user_count == 1 and not errors)
                except Exception as exc:
                    case.update(_error(exc))
                finally:
                    case['raw_model_responses'] = calls[start:]

            for mode in ('galgame', 'galgame_lock'):
                if selected and selected != mode:
                    continue
                case = {'label': mode, 'mode': mode, 'turns': [], 'passed': False,
                        'expected': '自然回应并递杯；审查尾巴使用、重复承诺和台词动作边界。锁分沿用正式结算。'}
                cases.append(case)
                try:
                    body, case['character_profile'] = await setup(mode)
                    inputs = ['时间=晚上，地点=客厅，季节=春天。我们坐在木屋的客厅里，矮桌上放着一只带把手的空杯子。我今天挺开心，想和你暖暖地聊会儿。',
                              '你转过来面对我，把桌上的杯子递给我。']
                    for index, text in enumerate(inputs):
                        turn = {'index': index + 1, 'input': text, 'passed': False}
                        case['turns'].append(turn)
                        start = len(calls)
                        try:
                            body['messages'] = [message(text)]
                            turn['request_messages'] = body['messages']
                            _active_report['route_requests'] += 1
                            response = await client.post('/api/chat', headers=headers, json=body)
                            events, errors = _events(response)
                            result = next((e.get('galgame_result') for e in events if e.get('type') == 'result'), {}) or {}
                            # Preserve the full delivered scene and response, not just dialogue excerpts.
                            if result.get('status') == 'success':
                                turn['response'] = result
                                turn['scene'] = result.get('data', {}).get('scene')
                            await wait_for_pending_char_memory(username, body['character_id'], mode)
                            state = await load_galgame_state_async(username, body['character_id'], game_type=mode)
                            ai = [m for m in state.get('messages', []) if m.get('role') == 'assistant']
                            turn.update(status=response.status_code, errors=errors,
                                        event_types=[e.get('type') for e in events], saved_assistant_count=len(ai),
                                        saved_reply=ai[-1] if ai else None,
                                        passed=response.status_code == 200 and result.get('status') == 'success'
                                        and result.get('db_saved') is True and len(ai) == index + 1 and not errors)
                        except Exception as exc:
                            turn.update(_error(exc))
                        finally:
                            turn['raw_model_responses'] = calls[start:]
                        if not turn['passed']:
                            case['continuation_skipped_after_failed_opening'] = index == 0
                            break
                    case['passed'] = len(case['turns']) == 2 and all(t['passed'] for t in case['turns'])
                except Exception as exc:
                    case.update(_error(exc))
    finally:
        harness_runtime.run_harness_turn = original
        game_harness.run_harness_turn = original_game
        _active_report['agent_invocations'] = len(calls)
        _active_report['validation_retries'] = sum(c['validation_retry'] for c in calls)
    _active_report['passed'] = bool(cases) and all(c['passed'] for c in cases)
    return _active_report


async def exercise(workspace: Path) -> dict:
    global _active_report
    began = time.monotonic()
    _active_report = {'passed': False, 'status': 200, 'cases': [], 'route_requests': 0,
                      'synthetic_only': True, 'production_database_opened': False,
                      'probe_level_retries': 0, 'maximum_planned_route_requests': 9,
                      'semantic_review': 'Passed checks route delivery and saving only. Review verbatim model parts and all scene fields separately.',
                      'selected_case': os.environ.get('PONYCHAT_STYLE_CASE', '')}
    try:
        await _exercise(workspace)
    except (Exception, asyncio.CancelledError) as exc:
        _active_report.update(status=0, passed=False, **_error(exc))
    finally:
        if 'Backend.db' in sys.modules:
            try:
                await sys.modules['Backend.db'].get_database().close()
            except Exception as exc:
                _active_report.setdefault('cleanup_errors', []).append(_error(exc))
        config = sys.modules.get('Backend.config')
        if config:
            if config.httpx_client is not None:
                try:
                    await config.httpx_client.aclose()
                except Exception as exc:
                    _active_report.setdefault('cleanup_errors', []).append(_error(exc))
            for close in (config._queue_listener.stop, config._file_handler.close):
                try:
                    close()
                except Exception as exc:
                    _active_report.setdefault('cleanup_errors', []).append(_error(exc))
        _active_report['elapsed_seconds'] = round(time.monotonic() - began, 3)
    return _active_report


if __name__ == '__main__':
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
