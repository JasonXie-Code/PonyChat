"""Real Agent selection and delivery with isolated DB and synthetic phone images."""
import asyncio
import base64
from io import BytesIO
import json
import sqlite3
import sys
import time
from types import SimpleNamespace

import smoke_deployed_harness as smoke


async def exercise(workspace):
    sys.path.insert(0, str(workspace))
    from Backend import config
    from Backend.chat_modules import history_image_tools as module
    from Backend.chat_modules.autonomous_normal import run_autonomous_turn
    from Backend.chat_modules.autonomous_prompt_skills import run_skill_turn
    from Backend.chat_image_transfer import load_chat_image_transfer, discard_web_image_transfer
    from PIL import Image, ImageDraw
    import httpx
    started = time.monotonic()
    db = workspace / 'selection.db'
    with sqlite3.connect(db) as conn:
        conn.executescript('''CREATE TABLE users(id INTEGER,username TEXT);
            CREATE TABLE conversations(id TEXT,user_id INTEGER,character_id TEXT,is_hidden INTEGER);
            CREATE TABLE messages(id TEXT,message_id TEXT,conversation_id TEXT,role TEXT,content TEXT,timestamp INTEGER);
            INSERT INTO users VALUES(1,'synthetic');
            INSERT INTO conversations VALUES('selection',1,'pony',0);
            INSERT INTO messages VALUES('a','a','selection','assistant','第一张是我挑的图片。',1);
            INSERT INTO messages VALUES('b','b','selection','assistant','第二张也是我挑的图片。',2);''')
    images = {}
    for mid, color in [('a', 'red'), ('b', 'blue')]:
        picture = Image.new('RGB', (256, 256), 'white')
        draw = ImageDraw.Draw(picture)
        if mid == 'a':
            draw.ellipse((40, 40, 216, 216), fill=color)
        else:
            draw.rectangle((40, 40, 216, 216), fill=color)
        output = BytesIO()
        picture.save(output, 'PNG')
        images[mid] = 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
    cases = [
        ('favorite_send', '这么多张里，你最喜欢哪一张？把你最喜欢的发出来，然后解说一下。', True, False),
        ('second_send', '就选第二幅吧，给我看看，再讲讲里面的图形和颜色。', True, False),
        ('discussion_only', '这两张你更喜欢哪张？只聊喜好，不要发图片。', False, False),
        ('missing_original', '把第二张发给我，再解说一下。', False, True),
    ]
    results = []
    model = config.model_manager.get_active_model()
    try:
        for name, text, expected, missing in cases:
            calls = []
            async def phone(username, request):
                calls.append(dict(request))
                if request['action'] == 'list':
                    return {'status': 'ok', 'images': [{'message_id': mid, 'image_count': 1}
                            for mid in ('b', 'a')], 'has_more': False}
                return None if missing else {'image': images[request['message_id']]}
            module.request_from_phone = phone
            tools = module.HistoryImageTools(db, username='synthetic', character_id='pony', conversation_id='selection')
            result = await run_skill_turn(run_autonomous_turn,
                home_profile='名称：云杉\n种族：独角兽\n性格：温和直率，喜欢蓝色与几何图形',
                messages=[{'role': 'assistant', 'content': '第一张是我挑的图片。', 'message_id': 'a'},
                          {'role': 'assistant', 'content': '第二张也是我挑的图片。', 'message_id': 'b'},
                          {'role': 'user', 'content': text, 'message_id': 'question'}],
                character_profile='你是成年独角兽云杉，温和直率，喜欢蓝色与几何图形，以中文交流。',
                environment=module.IMAGE_SOURCE_RULE,
                model_config=model, history_image_tools=tools)
            request = SimpleNamespace()
            tools.apply_to_request(request, result['bubble_count'])
            assets = getattr(request, '_assistant_asset_attachments', [])
            deliveries = []
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app), base_url='http://test') as client:
                for asset in assets:
                    response = await client.get(asset['url'])
                    original = base64.b64decode(images[asset['metadata']['source_message_id']].split(',', 1)[1])
                    deliveries.append(response.status_code == 200 and response.content == original)
                    discard_web_image_transfer(asset['url'].rsplit('/', 1)[-1], 'synthetic')
            passed = bool(assets) == expected and all(deliveries)
            if name == 'second_send':
                passed = passed and bool(assets) and assets[0]['metadata']['source_message_id'] == 'b'
            row = {'case': name, 'passed': passed, 'calls': calls, 'reply': result['envelope'],
                   'attachments': assets, 'http_downloads_match_original': deliveries}
            results.append(row)
            print(json.dumps({'case': name, 'passed': passed, 'attachments': len(assets)}, ensure_ascii=False), flush=True)
        return {'passed': all(r['passed'] for r in results), 'cases': results, 'model_id': model['id'],
                'elapsed_seconds': round(time.monotonic() - started, 2),
                'scope': 'Real configured Agent; synthetic phone transport; isolated ASGI download with original-byte comparison, no real handset acceptance.'}
    finally:
        if config.httpx_client is not None:
            await config.httpx_client.aclose()
        from Backend.db import get_database
        await get_database().close()
        config._queue_listener.stop()
        config._file_handler.close()


if __name__ == '__main__':
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
