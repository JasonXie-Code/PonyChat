"""Real chat and relationship timings with a dedicated account in an isolated copy.

Uses real authenticated ASGI routes, real models and the normal background worker.
Timings exclude public network transport and Android rendering; no production DB.
"""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys
import time


MESSAGES = [
    '你好，我叫小林，第一次见面。用一两句话和我聊聊就好。',
    '我喜欢在周末散步，你呢？',
    '我通常去家附近的公园。',
    '公园里有一棵很大的树，我喜欢在那里看书。',
    '我最近在读一本讲植物的书。',
    '我最喜欢薄荷，闻起来很清爽。',
    '喝茶的时候我不加糖。',
    '今天工作有点忙，现在终于休息了。',
    '和你说几句话感觉轻松多了。',
    '我也喜欢听雨声，特别是晚上。',
    '下雨的时候我会待在家里整理书架。',
    '我有一本从小保留的故事书。',
    '里面的探险故事我现在还喜欢。',
    '有机会我们可以一起聊聊喜欢的故事。',
    '今天很开心认识你，之后还想和你继续聊天。',
]


async def exercise(workspace, report, rounds):
    import httpx
    import Backend
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao, get_membership_dao
    from Backend.agent_memory import jobs

    config.httpx_client = httpx.AsyncClient(timeout=240)
    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace)
    await db.init()
    jobs.initialize(db.db_path)
    username = 'relationship_bench_' + secrets.token_hex(4)
    # The isolated app keeps the real authentication flow, with this test-only
    # account explicitly admitted to its otherwise Jason/System-only allowlist.
    from Backend import login_control
    login_control.ALLOWED_APP_LOGIN_USERS = login_control.ALLOWED_APP_LOGIN_USERS | {username}
    password = secrets.token_urlsafe(24)
    character_id, conversation_id = 'relationship_bench_pony', 'relationship_bench_chat'
    await get_users_dao().create_user(username, password, role='user')
    await get_membership_dao().set_membership_by_username(username, 'developer', None, note='isolated timing test')
    profile = '你叫青禾，是成年陆马。性格温和，喜欢读书和散步。和新朋友自然聊天，每次简短回答一两句话。'
    await CharactersDAO(db).save_characters(username, [{
        'id': character_id, 'name': '青禾', 'prompt': profile, 'bio': profile}])
    (workspace / 'test-account.json').write_text(json.dumps({
        'username': username, 'password': password, 'character_id': character_id}, ensure_ascii=False), encoding='utf8')
    result = {'scope': 'isolated real-model authenticated ASGI routes; excludes network and Android rendering',
              'username': username, 'character_id': character_id, 'workspace': str(workspace),
              'rounds': [], 'pages': [], 'reviews': []}

    def flush():
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')

    original_run = jobs.run_one
    async def observed_run(*args, **kwargs):
        started = time.monotonic()
        try:
            value = await original_run(*args, **kwargs)
            if value is not None:
                row = {'seconds': round(time.monotonic()-started, 3), 'status': value['status'],
                       'llm_api_calls': value['llm_api_calls'], 'tools': value['tools'],
                       'saved_categories': [v['category'] for v in value['saved']]}
                result['reviews'].append(row)
                print(json.dumps({'review': row}, ensure_ascii=False), flush=True)
                flush()
            return value
        except Exception as exc:
            result['reviews'].append({'seconds': round(time.monotonic()-started, 3),
                                       'error': type(exc).__name__ + ': ' + str(exc)[:200]})
            flush()
            raise
    jobs.run_one = observed_run
    worker = asyncio.create_task(jobs.worker_loop())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app), base_url='http://benchmark', timeout=240) as client:
            login = await client.post('/api/auth/login', json={'username': username, 'password': password})
            login.raise_for_status()
            client.headers['X-Chat-Auth'] = login.json()['auth_token']
            client.headers['X-Client-ID'] = 'relationship-benchmark'
            params = {'username': username, 'character_id': character_id}

            async def page(label, refresh=False):
                started = time.monotonic()
                previous = (await client.get('/api/relationship/state', params=params)).json() if refresh else {}
                response = await client.post('/api/relationship/refresh', json={**params, 'conversation_id': conversation_id}) if refresh else await client.get('/api/relationship/state', params=params)
                response.raise_for_status()
                body = response.json()
                samples = [{'at': round(time.monotonic()-started, 3), 'status': body.get('generation_status')}]
                while body.get('generation_status') in ('queued', 'running') and time.monotonic()-started < 230:
                    await asyncio.sleep(2)
                    response = await client.get('/api/relationship/state', params=params)
                    response.raise_for_status()
                    body = response.json()
                    if samples[-1]['status'] != body.get('generation_status'):
                        samples.append({'at': round(time.monotonic()-started, 3), 'status': body.get('generation_status')})
                row = {'label': label, 'seconds': round(time.monotonic()-started, 3),
                       'status': body.get('generation_status'), 'has_page': bool(body.get('relationship_page')),
                       'updated_at_ms': body.get('relationship_page_updated_at_ms'),
                       'newer_than_before': body.get('relationship_page_updated_at_ms', 0) > previous.get('relationship_page_updated_at_ms', 0),
                       'transitions': samples, 'page': body.get('relationship_page')}
                result['pages'].append(row)
                flush()
                print(json.dumps({'page': row}, ensure_ascii=False), flush=True)

            for index, text in enumerate(MESSAGES[:rounds], 1):
                with sqlite3.connect(db.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    history = [dict(r) for r in conn.execute(
                        'SELECT message_id AS id,message_id,role,content,timestamp FROM messages WHERE conversation_id=? ORDER BY timestamp,rowid', (conversation_id,))]
                message = {'id': f'user_{index}', 'message_id': f'user_{index}', 'role': 'user',
                           'content': text, 'timestamp': int(time.time()*1000)}
                await ConversationsDAO(db).save_conversation(username, character_id, {
                    'id': conversation_id, 'title': '关系加载耗时测试', 'timestamp': message['timestamp'],
                    'messages': [*history, message]})
                started = time.monotonic()
                response = await client.post('/api/chat', json={**params, 'conversation_id': conversation_id,
                    'normal_engine': 'harness', 'mode': 'normal', 'memory_enabled': True, 'voice_enabled': False,
                    'messages': [*history, message]})
                errors = []
                for line in response.text.splitlines():
                    if line.startswith('data:'):
                        try:
                            event = json.loads(line[5:])
                            if event.get('error') or event.get('type') == 'error':
                                errors.append(event)
                        except ValueError:
                            pass
                row = {'round': index, 'seconds': round(time.monotonic()-started, 3),
                       'http_status': response.status_code, 'errors': errors}
                result['rounds'].append(row)
                flush()
                print(json.dumps({'chat': row}, ensure_ascii=False), flush=True)
                if response.status_code != 200 or errors:
                    (workspace / f'failed-chat-{index}.txt').write_text(response.text, encoding='utf8')
                    raise RuntimeError('Chat failed; see isolated response')
                if index == 1:
                    await page('after_first_round')
                if index == rounds:
                    await page(f'after_{rounds}_rounds')
                    await page('pull_refresh', refresh=True)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        flush()
        await db.close()
        await config.httpx_client.aclose()
        config._queue_listener.stop()
        config._file_handler.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--rounds', type=int, default=15)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[2]
    workspace = source / '.tmp' / ('relationship-bench-' + args.label + '-' + secrets.token_hex(3))
    workspace.mkdir(parents=True)
    excluded = {'database', 'data', 'backups', 'Agent-Test', 'tests', '__pycache__', '数据存档', '.venv'}
    for parent, dirs, files in os.walk(source / 'Backend'):
        dirs[:] = [d for d in dirs if d not in excluded]
        for name in files:
            path = Path(parent) / name
            if path.suffix not in {'.py', '.mjs', '.json'}:
                continue
            target = workspace / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    from dotenv import dotenv_values
    for key, value in dotenv_values(source / '.env').items():
        if value is not None:
            os.environ.setdefault(key, value)
    os.environ.update(PONYCHAT_DB_PATH=str(workspace / 'test.db'),
                      PONYCHAT_BACKUP_DIR=str(workspace / 'backups'),
                      PONYCHAT_MLP_VECTOR_DB_PATH=str(workspace / 'vectors.db'),
                      AUTH_SECRET=secrets.token_urlsafe(48), PONYCHAT_VOICE_ENABLED='0')
    sys.path.insert(0, str(workspace))
    os.chdir(workspace)
    logging.disable(logging.CRITICAL)
    report = source / 'docs/testing/ponychat-6.0.0-20260909' / ('relationship-timing-' + args.label + '.json')
    print(json.dumps({'workspace': str(workspace), 'report': str(report)}), flush=True)
    asyncio.run(exercise(workspace, report, args.rounds))


if __name__ == '__main__':
    main()
