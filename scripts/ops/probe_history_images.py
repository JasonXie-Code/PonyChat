"""Real-model old-image reread in a disposable source/config copy and synthetic DB."""
import asyncio
import base64
from io import BytesIO
import json
import sqlite3
import time

import smoke_deployed_harness as smoke


async def exercise(workspace):
    started = time.monotonic()
    import sys
    import os
    import tarfile
    overlay = os.environ.get('PONYCHAT_HISTORY_IMAGE_OVERLAY')
    if overlay:
        with tarfile.open(overlay) as archive:
            assert all(m.isfile() and m.name.startswith('Backend/') and '..' not in m.name.split('/') for m in archive)
            archive.extractall(workspace, filter='data')
    sys.path.insert(0, str(workspace))
    import Backend
    from Backend import config
    from Backend.chat_modules import history_image_tools as module
    from Backend.chat_modules.autonomous_normal import run_autonomous_turn
    from Backend.chat_modules.harness_runtime import run_harness_turn
    from Backend.chat_modules.agent_logging import snapshot
    from PIL import Image, ImageDraw, ImageFont
    db = workspace / 'image-probe.db'
    with sqlite3.connect(db) as conn:
        conn.executescript('''CREATE TABLE users(id INTEGER,username TEXT);
            CREATE TABLE conversations(id TEXT,user_id INTEGER,character_id TEXT,is_hidden INTEGER);
            CREATE TABLE messages(id TEXT,message_id TEXT,conversation_id TEXT,role TEXT,content TEXT,timestamp INTEGER);
            INSERT INTO users VALUES(1,'synthetic');
            INSERT INTO conversations VALUES('test',1,'pony',0);
            INSERT INTO messages VALUES('before-old','before-old','test','user','这张图片里有两种几何图形和四位数字，稍后我再问你。',1);
            INSERT INTO messages VALUES('old','old','test','user','这就是那张测试图',2);
            INSERT INTO messages VALUES('after-old','after-old','test','assistant','好的，之后可以继续问我这张图。',3);
            INSERT INTO messages VALUES('before-new','before-new','test','user','换个话题，这次发一张风景照片，看天上的云。',4);
            INSERT INTO messages VALUES('newer','newer','test','user','这是风景照',5);''')
    picture = Image.new('RGB', (600, 400), 'white')
    draw = ImageDraw.Draw(picture)
    draw.rectangle((40,40,180,180), fill='blue')
    draw.ellipse((360,40,510,190), fill='red')
    draw.text((190,260), '7319', font=ImageFont.truetype('DejaVuSans.ttf', 55), fill='black')
    output = BytesIO()
    picture.save(output, 'PNG')
    data = 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
    calls = []
    missing = False
    async def phone(username, request):
        calls.append(dict(request))
        if request['action'] == 'list':
            return {'status':'ok','images':[{'message_id':'newer','image_count':1},
                {'message_id':'old','image_count':1}], 'has_more':False}
        if request['message_id'] != 'old':
            return None
        return None if missing else {'image':data}
    module.request_from_phone = phone
    tools = module.HistoryImageTools(db, username='synthetic', character_id='pony', conversation_id='test')
    model = next(dict(m) for m in config.model_manager.get_models() if m['id'] == 'deepseek-flash')
    results = []
    async def observed_runner(*args, **kwargs):
        result = await run_harness_turn(*args, **kwargs)
        if result.get('finish_reason') != 'completed':
            print(json.dumps(snapshot({'finish_reason':result.get('finish_reason'),
                'tool_events':result.get('tool_events'), 'events':result.get('events', [])[-8:]}), ensure_ascii=False), flush=True)
        return result
    try:
        from Backend.chat_modules.autonomous_prompt_skills import run_skill_turn
        for own_sticker in (False, True):
            calls.clear()
            tools = module.HistoryImageTools(db, username='synthetic', character_id='pony', conversation_id='test')
            # Reproduce the invalid read from a text-only message before the real
            # Agent continues. No user logs or private conversation are replayed.
            rejected = await tools.read_image({'message_id': 'after-old', 'image_index': 1,
                                               'selection_reason': 'check whether this text has a picture'})
            assert rejected.get('reason') == 'image_not_confirmed' and not calls
            recent = [{'role': 'assistant', 'content': '你好呀，要一起去喝茶吗？', 'message_id': 'greeting'}]
            if own_sticker:
                recent.append({'role': 'assistant', 'content': '[表情包]', 'message_id': 'own-sticker',
                               'attachments': [{'type': 'sticker', 'name': '开心', 'url': '/api/admin/assets/own/file'}]})
            recent.append({'role': 'user', 'content': '好呀，我们去河边的小茶馆吧。', 'message_id': 'question'})
            result = await run_skill_turn(run_autonomous_turn,
                home_profile='名称：云朵\n种族：陆马\n性格：外向热情，喜欢交朋友',
                messages=recent, character_profile='云朵是一匹外向热情、爱喝茶的陆马。',
                environment=module.IMAGE_SOURCE_RULE + '\n先前无效的读图请求结果（未发现图片）：' +
                    json.dumps(rejected, ensure_ascii=False),
                model_config=model, history_image_tools=tools, harness_runner=observed_runner)
            envelope = result['envelope']
            visible = ''.join(p.get('text', '') for b in json.loads(envelope)['bubbles'] for p in b['parts'])
            success = not any(word in visible for word in ('图片', '发图', '重发', '上传', 'image', 'picture', 'photo'))
            results.append({'case': 'plain_text_with_own_sticker' if own_sticker else 'plain_text',
                            'passed': success, 'calls': list(calls), 'reply': envelope})
        for unavailable in (False, True):
            missing = unavailable
            calls.clear()
            result = await run_autonomous_turn(
                messages=[{'role':'user','content':'重新看一下我之前发过的那张图，告诉我里面两种图形各是什么颜色，以及图中的四位数字。','message_id':'question','timestamp':2}],
                character_profile='你是温和直率的小马紫悦，以中文简短回答。',
                environment='用户明确追问历史图片；先用list_history_images定位，再用read_history_image重新看原图。原图没有取回时提醒图片过期请重传。',
                model_config=model, history_image_tools=tools, harness_runner=observed_runner)
            envelope = result['envelope']
            success = ('7319' in envelope and '蓝' in envelope and '红' in envelope) if not missing else (
                ('过期' in envelope or '重新' in envelope or '再发' in envelope) and '7319' not in envelope)
            results.append({'missing':missing, 'calls':list(calls), 'reply':envelope,
                'passed': success and any(c.get('message_id')=='old' for c in calls)
                    and not any(c.get('message_id')=='newer' for c in calls)})
        return {'passed':all(r['passed'] for r in results),'cases':results, 'status':'completed',
                'elapsed_seconds':round(time.monotonic()-started, 3), 'agent_memory_count':0,
                'scope':'Real Agent and native tool image rendering; phone transport replaced with synthetic fixture.'}
    finally:
        if config.httpx_client is not None:
            await config.httpx_client.aclose()
        config._queue_listener.stop()
        config._file_handler.close()


if __name__ == '__main__':
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
