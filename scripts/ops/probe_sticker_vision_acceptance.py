"""Real normal-chat route acceptance of sticker pixels in an isolated snapshot."""
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import hashlib
import logging

import smoke_deployed_harness as smoke

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / os.environ.get('PONYCHAT_STICKER_REPORT', 'docs/testing/sticker-vision-20260913')
SPEC = json.loads(Path(os.environ['PONYCHAT_STICKER_SPEC']).read_text(encoding='utf-8')) if os.environ.get('PONYCHAT_STICKER_SPEC') else {}
FIXTURE = ROOT / SPEC.get('fixture', 'var/qa/pinkie-images/1668671.jpg')
ATTACHMENT_NAME = SPEC.get('name', '蓝色小马在哭')
ATTACHMENT_METADATA = SPEC.get('metadata', {'detail': '蓝色小马在伤心地哭泣', 'image_text': 'GOODBYE', 'custom_tags': ['伤心', '告别']})
REVISION = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()


async def exercise(workspace):
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from Backend.agent_memory.schema import ensure
    from deepseek_harness import DeepSeekHarness
    # Capture synthetic-database failures without logging credentials or prompts.
    errors = []
    class ErrorCapture(logging.Handler):
        def emit(self, record):
            errors.append(record.getMessage())
    logging.disable(logging.WARNING)
    logging.getLogger().addHandler(ErrorCapture(level=logging.ERROR))

    started = time.monotonic()
    config.httpx_client = httpx.AsyncClient(timeout=120)
    database = get_database()
    assert Path(database.db_path).resolve().is_relative_to(workspace.resolve())
    await database.init()
    with sqlite3.connect(database.db_path) as conn:
        ensure(conn)
    password = secrets.token_urlsafe(24)
    assert await get_users_dao().create_user('System', password, role='user')
    character = 'synthetic_sticker'
    assert await CharactersDAO(database).save_characters('System', [{
        'id': character, 'name': '云杉',
        'prompt': '你叫云杉，是成年独角兽小马，温和简洁。', 'bio': 'Synthetic sticker acceptance'}])
    pixels = FIXTURE.read_bytes()
    from PIL import Image
    mime = Image.MIME[Image.open(io.BytesIO(pixels)).format]
    with sqlite3.connect(database.db_path) as conn:
        user_id = conn.execute("SELECT id FROM users WHERE username='System'").fetchone()[0]
        conn.execute('INSERT INTO media_assets(id,name,mime_type,file_data) VALUES(?,?,?,?)',
                     ('misleading', ATTACHMENT_NAME, mime, pixels))
        conn.execute('INSERT INTO user_sticker_assets(id,user_id,source_asset_id,name) VALUES(?,?,?,?)',
                     ('saved', user_id, 'misleading', ATTACHMENT_NAME))
    observations = []
    actual_run = DeepSeekHarness.run

    def observe_run(self, *args, **kwargs):
        prompt = args[0] if args else kwargs.get('prompt')
        event = {'native_image_count': sum(b.get('type') == 'image' for b in prompt)
                 if isinstance(prompt, list) else 0}
        observations.append(event)
        result = actual_run(self, *args, **kwargs)
        event.update(final_response=result.final_response, finish_reason=result.finish_reason)
        return result

    DeepSeekHarness.run = observe_run
    cases = [
        ('conflicting_labels', {'asset_id': 'misleading'}, '这张表情包实际画了什么？卡片上写的是什么意思？', False),
        ('image_only', {'asset_id': 'misleading'}, '', False),
        ('saved_id_then_text', {'user_sticker_id': 'saved'}, '卡片上是在邀请什么？', True),
        ('missing_original', {'asset_id': 'missing'}, '这张表情包里是什么？', False),
    ]
    cases = SPEC.get('cases', cases)
    selected = os.environ.get('PONYCHAT_STICKER_CASES')
    if selected:
        wanted = set(selected.split(','))
        assert wanted <= {case[0] for case in cases}, 'Unknown acceptance case'
        cases = [case for case in cases if case[0] in wanted]
    report = {'revision': REVISION, 'fixture_sha256': hashlib.sha256(pixels).hexdigest(),
              'autonomous_images_sha256': hashlib.sha256((workspace / 'Backend/chat_modules/autonomous_images.py').read_bytes()).hexdigest(),
              'scope': 'Frozen commit; real /api/chat ASGI SSE route and real model; isolated synthetic database. No deployment or Android UI acceptance.',
              'cases': []}
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / ('fixture' + FIXTURE.suffix)).write_bytes(pixels)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                base_url='http://isolated-sticker', timeout=240) as client:
        login = await client.post('/api/auth/login', json={'username': 'System', 'password': password})
        assert login.status_code == 200
        headers = {'X-Chat-Auth': login.json()['auth_token'], 'X-Client-ID': 'synthetic-sticker'}
        for name, reference, text, split in cases:
            # Normal mode permits one visible conversation per character.
            # Each independent case therefore needs its own character as well.
            character = 'synthetic_' + name
            assert await CharactersDAO(database).save_characters('System', [{
                'id': character, 'name': '云杉',
                'prompt': '你叫云杉，是成年独角兽小马，温和简洁。', 'bio': 'Synthetic sticker acceptance'}])
            now = int(time.time() * 1000)
            conversation = 'sticker_' + name
            assert await ConversationsDAO(database).save_conversation('System', character, {
                'id': conversation, 'title': name, 'timestamp': now, 'messages': []})
            attachment = {'type': 'sticker', **reference, 'name': ATTACHMENT_NAME, 'metadata': ATTACHMENT_METADATA}
            messages = [{'role': 'user', 'content': '' if split else text, 'attachments': [attachment],
                         'message_id': name + '_image', 'timestamp': now}]
            if split:
                messages.append({'role': 'user', 'content': text, 'message_id': name + '_text', 'timestamp': now + 1})
            body = {'username': 'System', 'character_id': character, 'conversation_id': conversation,
                    'normal_engine': 'harness', 'mode': 'normal', 'memory_enabled': True,
                    'voice_enabled': False, 'messages': messages}
            begin = len(observations)
            error_start = len(errors)
            response = await client.post('/api/chat', headers=headers, json=body)
            events = [json.loads(line[6:]) for line in response.text.splitlines()
                      if line.startswith('data: ') and line[6:].strip() != '[DONE]']
            runs = observations[begin:]
            expected_images = 0 if name == 'missing_original' else 1
            transport_passed = (response.status_code == 200 and bool(runs)
                and any(r['native_image_count'] == expected_images for r in runs)
                and not any(e.get('type') == 'error' for e in events)
                and any(e.get('type') == 'save_status' and e.get('success') for e in events))
            report['cases'].append({'case': name, 'request': body, 'status': response.status_code,
                                    'transport_passed': transport_passed, 'runs': runs, 'events': events,
                                    'errors': errors[error_start:]})
            (REPORT / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(name + ': transport=' + str(transport_passed), flush=True)
    report.update(passed=all(c['transport_passed'] for c in report['cases']),
                  elapsed_seconds=round(time.monotonic() - started, 2))
    return report


if __name__ == '__main__':
    smoke._exercise = exercise
    os.environ['PONYCHAT_SMOKE_TIMEOUT_SECONDS'] = '850'
    with tempfile.TemporaryDirectory(prefix='ponychat-sticker-snapshot-') as directory:
        source = Path(directory)
        archive = subprocess.check_output(['git', 'archive', REVISION, 'Backend'], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(source, filter='data')
        # Apply only this acceptance-discovered fix; exclude concurrent work.
        for relative in SPEC.get('overlays', ['Backend/chat_modules/autonomous_images.py']):
            (source / relative).write_bytes((ROOT / relative).read_bytes())
        # Only the existing harness key loader reads this temporary config.
        (source / '.env').write_bytes((ROOT / '.env').read_bytes())
        sys.argv = [sys.argv[0], str(REPORT / 'results.json'), '--source', str(source)]
        raise SystemExit(smoke.main())
