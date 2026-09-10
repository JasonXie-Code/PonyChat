"""Real Agent, route and scheduler acceptance using only a temporary synthetic DB."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

import smoke_deployed_harness as smoke


async def _exercise(workspace):
    overlay = os.environ.get('PONYCHAT_COVERAGE_OVERLAY')
    if overlay:
        import tarfile
        with tarfile.open(overlay) as archive:
            assert all(m.isfile() and m.name.startswith('Backend/') and '..' not in m.name.split('/') for m in archive)
            archive.extractall(workspace, filter='data')
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    from Backend import config, scheduled_followup as sf
    from Backend.db import get_database, get_users_dao, CharactersDAO, ConversationsDAO
    from Backend.agent_memory import jobs
    config.httpx_client = httpx.AsyncClient(timeout=600)
    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
    await db.init()
    jobs.initialize(db.db_path)
    username, password = os.environ.get('PONYCHAT_SMOKE_USERNAME', 'System'), secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='admin')
    characters = []
    profile = {
        'name': '云杉', 'profileSpecies': '人类', 'profileGender': '女',
        'prompt': '云杉是成年女性，细心、开朗、有自己的想法，喜欢观察天气和分享有趣的新发现。说话自然简洁，愿意主动聊天，但不重复催促对方。',
        'bio': '隔离验收角色', 'profileIntro': '细心开朗，有自己的想法，喜欢观察和分享新发现。'}
    cases = []
    began = time.monotonic()
    from Backend.chat_modules import harness_runtime
    actual = harness_runtime.run_harness_turn
    calls = []
    diagnostics = []
    actual_error = config.logger.error
    def observe_error(message, *args, **kwargs):
        diagnostics.append(str(message) % args if args else str(message))
        return actual_error(message, *args, **kwargs)
    config.logger.error = observe_error
    actual_warning = config.logger.warning
    def observe_warning(message, *args, **kwargs):
        if '[ScheduledFollowup]' in str(message):
            diagnostics.append(str(message) % args if args else str(message))
        return actual_warning(message, *args, **kwargs)
    config.logger.warning = observe_warning

    async def observed(*args, **kwargs):
        start = time.monotonic()
        try:
            result = await actual(*args, **kwargs)
        except Exception as exc:
            diagnostics.append(type(exc).__name__ + ': ' + str(exc))
            raise
        try:
            prompt = json.loads(args[0])
            availability = prompt.get('followup_availability')
        except (ValueError, TypeError):
            availability = None
        calls.append({'elapsed_seconds': round(time.monotonic()-start, 3), 'followup_availability': availability,
                      'finish_reason': result.get('finish_reason'),
                      'llm_api_calls': result.get('llm_api_calls'),
                      'final_response': result.get('final_response')})
        return result
    harness_runtime.run_harness_turn = observed

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                base_url='http://isolated', timeout=600) as client:
        login = await client.post('/api/auth/login', json={'username': username, 'password': password})
        assert login.status_code == 200
        # The real Android endpoint treats messages as a delta. An unknown
        # client declares a full snapshot and would hide our seeded history.
        headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'android'}

        async def turn(label, text, *, enabled=True):
            from Backend.db.settings_dao import SettingsDAO
            await SettingsDAO(db).save_settings(username, {'proactive_messages_enabled': enabled})
            char = 'parity_character_' + secrets.token_hex(5)
            characters.append(dict(profile, id=char))
            assert await CharactersDAO(db).save_characters(username, characters)
            conv = 'parity_' + secrets.token_hex(5)
            mid = 'u_' + secrets.token_hex(5)
            now = int(time.time()*1000)
            assert await ConversationsDAO(db).save_conversation(username, char, {'id': conv, 'title': label,
                'timestamp': now, 'messages': [
                    {'id': conv+'_past_u', 'role': 'user', 'content': '今天下午我们在图书馆窗边聊天。', 'message_id': conv+'_past_u', 'timestamp': now-20000, 'sequence_number': 1},
                    {'id': conv+'_past_a', 'role': 'assistant', 'content': '好，我在窗边坐下了。你想聊点什么？', 'message_id': conv+'_past_a', 'timestamp': now-10000, 'sequence_number': 2},
                    {'id': mid, 'role': 'user', 'content': text, 'message_id': mid, 'timestamp': now, 'sequence_number': 3}]})
            before = len(calls)
            diagnostic_start = len(diagnostics)
            response = await client.post('/api/chat', headers=headers, json={
                'username': username, 'character_id': char, 'conversation_id': conv, 'mode': 'normal',
                'memory_enabled': True, 'voice_enabled': False,
                'messages': [{'role': 'user', 'content': text, 'message_id': mid, 'timestamp': now}]})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line[6:] != '[DONE]']
            with sqlite3.connect(db.db_path) as conn:
                conn.row_factory = sqlite3.Row
                tasks = [dict(r) for r in conn.execute('SELECT * FROM scheduled_followups WHERE conversation_id=?', (conv,))]
                agreed = conn.execute('SELECT COUNT(*) FROM proactive_tasks WHERE conversation_id=?', (conv,)).fetchone()[0]
                agreed_plans = [dict(r) for r in conn.execute('SELECT title,prompt,metadata_json FROM proactive_tasks WHERE conversation_id=?', (conv,))]
                replies = [dict(r) for r in conn.execute("SELECT message_id,content FROM messages WHERE conversation_id=? AND role='assistant' AND timestamp>=? AND COALESCE(is_hidden,0)=0", (conv, now))]
            parsed = []
            for call in calls[before:]:
                try: parsed.append(json.loads(call['final_response']))
                except (TypeError, ValueError): pass
            item = {'label': label, 'input': text, 'status': response.status_code,
                'reply_saved': bool(replies), 'replies': replies, 'schedules': tasks, 'agreed_tasks': agreed, 'agreed_plans': agreed_plans,
                'followup_decision': next((p.get('followup_decision') for p in reversed(parsed) if 'followup_decision' in p), None),
                'errors': [e for e in events if e.get('type') == 'error'], 'agent_runs': len(calls)-before,
                'response': response.text, 'diagnostics': diagnostics[diagnostic_start:], 'character_id': char,
                'raw_model_responses': [c['final_response'] for c in calls[before:]]}
            item['passed'] = response.status_code == 200 and bool(replies) and not item['errors']
            cases.append(item)
            return item, conv

        natural, conv = await turn('natural_followup', '我先去给杯子添点水。你接着看窗外，想到什么待会儿再跟我说，不用等我回来或者回复。')
        natural['passed'] &= len(natural['schedules']) == 1
        if natural['schedules']:
            task = natural['schedules'][0]
            # Simulate the agreed due instant during daytime. Only the clock
            # guard is controlled; generation, cancellation, save and push are real.
            sf._is_quiet_hour = lambda *a, **kw: False
            due_start = len(calls)
            await sf._process_one_due(task)
            with sqlite3.connect(db.db_path) as conn:
                conn.row_factory = sqlite3.Row
                delivered = dict(conn.execute('SELECT status,cancel_reason,sent_message_id FROM scheduled_followups WHERE id=?', (task['id'],)).fetchone())
                extra = [dict(r) for r in conn.execute("SELECT m.message_id,m.content,m.client_id FROM messages m "
                    "JOIN proactive_messages p ON p.message_id=m.message_id "
                    "WHERE m.conversation_id=? AND m.role='assistant' AND m.deleted_at IS NULL "
                    "AND COALESCE(m.is_hidden,0)=0 ORDER BY m.timestamp,m.rowid", (conv,))]
                pending = conn.execute("SELECT COUNT(*) FROM scheduled_followups WHERE conversation_id=? AND status='pending'", (conv,)).fetchone()[0]
            cases.append({'label': 'due_followup_delivery', 'task': delivered, 'replies': extra,
                          'diagnostics': list(diagnostics),
                          'raw_model_responses': [c['final_response'] for c in calls[due_start:]],
                          'pending_chained': pending, 'passed': delivered['status'] == 'sent'
                          and delivered['sent_message_id'] in [m['message_id'] for m in extra] and pending == 0})

        if os.environ.get('PONYCHAT_PARITY_ONLY_FOLLOWUP') == '1':
            return _report(cases, began, calls)

        ended, _ = await turn('conversation_end', '晚安，我去睡觉了，不用再给我发消息。')
        ended['passed'] &= not ended['schedules']
        disabled, _ = await turn('proactive_disabled', '你接着看窗外，想到什么待会儿再跟我说。', enabled=False)
        disabled['passed'] &= not disabled['schedules']
        reminder, _ = await turn('agreed_reminder', '两分钟后提醒我喝水。')
        reminder['passed'] &= reminder['agreed_tasks'] == 1
        cancel, conv = await turn('new_user_cancels', '你再观察一下窗外，发现什么新情况待会儿主动告诉我，不用等我回复。')
        cancel['passed'] &= len(cancel['schedules']) == 1
        if cancel['schedules']:
            task = cancel['schedules'][0]
            await sf.cancel_pending_for_user_message(username, cancel['character_id'], conv)
            await sf._process_one_due(task)
            with sqlite3.connect(db.db_path) as conn:
                status = conn.execute('SELECT status FROM scheduled_followups WHERE id=?', (task['id'],)).fetchone()[0]
            cases.append({'label': 'cancelled_task_not_sent', 'status': status, 'passed': status == 'cancelled'})
        for label, text in [('thought', '（请详细描写出当前你的心理活动）'),
                            ('body', '（请详细描写出当前你的身体状态）'),
                            ('visual', '（请详细描写出当前你看到的画面）')]:
            item, _ = await turn(label, text)
            item['passed'] &= len(item['replies']) == 3 and all(
                p['content'].startswith('（') and p['content'].endswith('）') for p in item['replies'])
        item, _ = await turn('mouth_occupied', '（我用手捂住你的嘴，示意你先听听窗外的鸟叫声）请用三个气泡回应。')
        try:
            final = json.loads(calls[-1]['final_response'])
            # Independent visible contract check; also runs against the release
            # before autonomous_speech exists for a genuine before/after pair.
            import re
            parts = final['bubbles'][0]['parts']
            item['passed'] &= any(p['kind'] != 'speech' for p in parts)
            item['passed'] &= all(re.fullmatch(r'[嗯唔呜哼啊哦噗呼嗬嘶咳啧啾\s，。！？,.!?…～~、—-]{1,16}', p['text'])
                                  for p in parts if p['kind'] == 'speech')
        except (IndexError, TypeError, ValueError):
            item['passed'] = False
    return _report(cases, began, calls)


def _report(cases, began, calls):
    return {'passed': all(c['passed'] for c in cases), 'status': 200, 'cases': cases,
        'elapsed_seconds': round(time.monotonic()-began, 3), 'runtime_observations': calls,
        'synthetic_only': True, 'production_database_opened': False,
        'clock_controlled': 'due execution and quiet hours simulated; real Agent and persistence'}


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
