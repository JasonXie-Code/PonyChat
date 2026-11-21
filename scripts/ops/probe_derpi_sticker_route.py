"""Exercise the full copied normal-chat route with live search and isolated data."""
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import sys
import time

import smoke_deployed_harness as smoke


async def exercise(workspace):
    sys.path.insert(0, str(workspace))
    import httpx
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from Backend.agent_memory.schema import ensure
    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
    config.httpx_client = httpx.AsyncClient(timeout=240)
    await db.init()
    with sqlite3.connect(db.db_path) as conn:
        ensure(conn)
    # The actual login gate only accepts these names; this fresh identity and
    # password exist exclusively in the asserted temporary database above.
    username = 'System'
    password = secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='user')
    char_id, conv_id = 'synthetic_twilight', 'synthetic_derpi_conversation'
    profile = '你是紫悦，成年天角兽。热爱学习和魔法，刚解出难题，现在很开心。用中文和朋友交流。'
    assert await CharactersDAO(db).save_characters(username, [
        {'id': char_id, 'name': '紫悦', 'prompt': profile, 'bio': 'isolated acceptance fixture'}])
    now = int(time.time() * 1000)
    text = '给我发一张紫悦开心的表情包庆祝吧。请直接按呆站标签找，普通安全评级，静态或动图都行。'
    message = {'id': 'request', 'message_id': 'request', 'role': 'user', 'content': text,
               'timestamp': now, 'sequence_number': 1}
    assert await ConversationsDAO(db).save_conversation(username, char_id,
        {'id': conv_id, 'title': 'isolated sticker acceptance', 'timestamp': now, 'messages': [message]})
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                    base_url='http://isolated-backend', timeout=240) as client:
            login = await client.post('/api/auth/login', json={'username': username, 'password': password})
            assert login.status_code == 200
            headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'android',
                       'X-PonyChat-Web-Images': 'receipt-v1', 'Accept': 'text/event-stream'}
            response = await client.post('/api/chat', headers=headers, json={
                'username': username, 'character_id': char_id, 'conversation_id': conv_id,
                'mode': 'normal', 'normal_engine': 'harness', 'memory_enabled': False,
                'voice_enabled': False, 'messages': [message]})
            events = [json.loads(line[5:]) for line in response.text.splitlines()
                      if line.startswith('data:') and line[5:].strip() not in ('', '[DONE]')]
            with sqlite3.connect(db.db_path) as conn:
                attachments = [{'url': url, 'metadata': json.loads(meta)} for url, meta in conn.execute(
                    'SELECT url,metadata_json FROM message_attachments WHERE conversation_id=?', (conv_id,))]
            checks = []
            for item in attachments:
                image = await client.get(item['url'])
                filename = item['url'].rsplit('/', 1)[-1]
                matches = image.status_code == 200 and hashlib.sha256(image.content).hexdigest() == item['metadata']['sha256']
                receipt = await client.post('/api/chat_images/' + filename + '/received', headers=headers)
                from Backend.chat_image_transfer import load_chat_image_transfer
                checks.append({'source_url': item['metadata'].get('source_url'),
                    'purpose': item['metadata'].get('purpose'), 'download_matches': matches,
                    'receipt_status': receipt.status_code, 'cleared': load_chat_image_transfer(filename) is None})
            passed = (response.status_code == 200 and bool(checks)
                      and any(e.get('type') == 'save_status' and e.get('success') for e in events)
                      and not any(e.get('type') == 'error' or e.get('error') for e in events)
                      and all(c['download_matches'] and c['receipt_status'] == 200 and c['cleared']
                              and c['purpose'] == 'sticker' and 'derpibooru.org/' in c['source_url'] for c in checks))
            marker = json.loads((workspace / 'Backend/.deploy_revision').read_text(encoding='utf-8'))
            return {'passed': passed, 'status': response.status_code,
                    'elapsed_seconds': round(time.monotonic() - started, 2),
                    'deploy_token': marker['deploy_token'], 'checks': checks, 'events': events,
                    'scope': 'Copied deployed backend; real configured model/search/download and ASGI chat/save/receipt; isolated account/database, no physical phone.'}
    finally:
        await config.httpx_client.aclose()
        await db.close()
        config._queue_listener.stop()
        config._file_handler.close()


if __name__ == '__main__':
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
