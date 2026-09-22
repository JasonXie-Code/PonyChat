"""Isolated upload -> consecutive image/text messages -> real Agent SSE acceptance."""
import io
import json
import sys
from pathlib import Path
import secrets
import sqlite3
import time

import smoke_deployed_harness as smoke


async def exercise(workspace):
    sys.path.insert(0, str(workspace))
    import httpx
    from PIL import Image, ImageDraw, ImageFont
    import Backend
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from Backend.agent_memory.schema import ensure

    started = time.monotonic()
    config.httpx_client = httpx.AsyncClient(timeout=120)
    database = get_database()
    assert Path(database.db_path).resolve().is_relative_to(workspace.resolve())
    await database.init()
    with sqlite3.connect(database.db_path) as conn:
        ensure(conn)
    username, password = 'System', secrets.token_urlsafe(24)
    assert await get_users_dao().create_user(username, password, role='user')
    character, conversation = 'synthetic_vision', 'synthetic_vision_' + secrets.token_hex(4)
    assert await CharactersDAO(database).save_characters(username, [{
        'id': character, 'name': '云杉', 'prompt': '你叫云杉，是成年独角兽小马，温和简洁。',
        'bio': 'synthetic vision acceptance'}])
    now = int(time.time() * 1000)
    assert await ConversationsDAO(database).save_conversation(username, character, {
        'id': conversation, 'title': 'Synthetic vision acceptance', 'timestamp': now, 'messages': []})
    picture = Image.new('RGB', (640, 480), 'white')
    draw = ImageDraw.Draw(picture)
    draw.rectangle((40, 40, 210, 210), fill='blue')
    draw.ellipse((380, 40, 550, 210), fill='red')
    draw.text((200, 300), '7319', fill='black',
              font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 65))
    output = io.BytesIO()
    picture.save(output, 'PNG')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                base_url='http://isolated-vision', timeout=240) as client:
        login = await client.post('/api/auth/login', json={'username': username, 'password': password})
        assert login.status_code == 200
        headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'synthetic-vision'}
        uploaded = await client.post('/api/chat_images', headers=headers,
                                    files={'file': ('fixture.png', output.getvalue(), 'image/png')})
        assert uploaded.status_code == 200
        body = {'username': username, 'character_id': character, 'conversation_id': conversation,
                'normal_engine': 'harness', 'mode': 'normal', 'memory_enabled': True,
                'voice_enabled': False, 'messages': [
                    {'role': 'user', 'content': '', 'image_url': uploaded.json()['url'],
                     'message_id': 'synthetic_image', 'timestamp': now},
                    {'role': 'user', 'content': '请告诉我图中两种图形的形状、颜色和四位数字。',
                     'message_id': 'synthetic_question', 'timestamp': now + 1}]}
        response = await client.post('/api/chat', json=body, headers=headers)
    events = [json.loads(line[6:]) for line in response.text.splitlines()
              if line.startswith('data: ') and line[6:].strip() != '[DONE]']
    passed = response.status_code == 200 and not any(e.get('type') == 'error' for e in events)
    passed = passed and all(word in response.text for word in ('蓝', '红', '7319'))
    return {'passed': passed, 'status': response.status_code, 'upload_status': uploaded.status_code,
            'elapsed_seconds': round(time.monotonic() - started, 2), 'events': events,
            'transport': 'Real upload and chat ASGI routes, real model, isolated synthetic DB',
            'deploy_token': json.loads((workspace / 'Backend/.deploy_revision').read_text())['deploy_token']}


if __name__ == '__main__':
    smoke._exercise = exercise
    raise SystemExit(smoke.main())
