"""Measure deployed normal-chat nodes with real models and a synthetic database.

Run beside run_style_matrix_probe.py and smoke_deployed_harness.py on Server-USA.
Observers exist only in this isolated process; production code is not modified.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import run_style_matrix_probe as matrix
import smoke_deployed_harness as smoke


async def exercise(workspace):
    overlay = os.environ.get('PONYCHAT_TIMING_OVERLAY_DIR')
    if overlay:
        import shutil
        for path in Path(overlay).rglob('*.py'):
            relative = path.relative_to(overlay)
            if relative.parts[0] != 'Backend' or '..' in relative.parts:
                raise ValueError('Overlay must contain Backend Python files only')
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    sys.path.insert(0, str(workspace))
    import Backend
    from Backend import config
    from Backend.chat_modules import autonomous_normal, autonomous_service
    from Backend.chat_modules import autonomous_prompt_skills, agent_logging, harness_runtime
    from Backend.chat_modules import harness_pool

    requests = []
    active = None

    def mark(kind, name, started=None, **fields):
        if active is None:
            return
        now = time.perf_counter()
        active['events'].append(dict(kind=kind, name=name,
            at_ms=round((now-active['_start'])*1000, 3),
            **({'duration_ms': round((now-started)*1000, 3)} if started is not None else {}), **fields))

    def observe(module, name):
        original = getattr(module, name)
        @functools.wraps(original)
        async def wrapped(*args, **kwargs):
            started = time.perf_counter()
            mark('start', name)
            status = 'success'
            try:
                return await original(*args, **kwargs)
            except BaseException:
                status = 'error'
                raise
            finally:
                mark('span', name, started, status=status)
        # Service modules inject function aliases; observe those references too.
        for loaded in list(sys.modules.values()):
            if getattr(loaded, '__name__', '').startswith('Backend'):
                for key, value in list(vars(loaded).items()):
                    if value is original:
                        setattr(loaded, key, wrapped)

    for module, name in (
        (autonomous_service, 'prepare_autonomous_request'),
        (autonomous_service, 'settle_autonomous_usage'),
        (autonomous_service, 'autonomous_delivery_content'),
        (autonomous_prompt_skills, 'run_skill_turn'),
        (autonomous_normal, 'run_autonomous_turn'),
        (harness_runtime, 'run_harness_turn'),
        (harness_pool, 'acquire_harness'),
    ):
        observe(module, name)

    original_record = agent_logging.record_event
    def record(kind, data):
        # Keep timing metadata, never raw model configuration or credentials.
        mark('sdk', kind, details={k: data[k] for k in
            ('turn', 'step', 'tool', 'tool_call_id', 'status', 'latency_ms', 'captured_on_completion')
            if k in data})
        return original_record(kind, data)
    agent_logging.record_event = record

    original_write = agent_logging.write
    async def write(stage, data, **kwargs):
        mark('diagnostic', stage, details={k: data[k] for k in
            ('latency_ms', 'status', 'runtime_reused', 'llm_api_calls', 'harness_runs', 'save_ok', 'error') if k in data},
            source_events=[{'type': e.get('type'), 'elapsed_ms': e.get('elapsed_ms'),
                'data': {k: e.get('data', {}).get(k) for k in
                    ('turn', 'step', 'tool', 'tool_call_id', 'status', 'latency_ms',
                     'captured_on_completion', 'error') if k in e.get('data', {})}}
                for e in data.get('events', [])])
        return await original_write(stage, data, **kwargs)
    agent_logging.write = write

    class TimingMiddleware:
        def __init__(self, app):
            self.app = app
        async def __call__(self, scope, receive, send):
            nonlocal active
            if scope.get('path') != '/api/chat':
                return await self.app(scope, receive, send)
            row = {'events': [], '_start': time.perf_counter()}
            active = row
            pending = ''
            async def timed_send(message):
                nonlocal pending
                if message['type'] == 'http.response.start':
                    mark('http', 'response_start', status=message['status'])
                elif message['type'] == 'http.response.body':
                    pending += message.get('body', b'').decode('utf8')
                    while '\n' in pending:
                        line, pending = pending.split('\n', 1)
                        if line.startswith('data: '):
                            data = line[6:]
                            if data == '[DONE]':
                                mark('sse', 'DONE')
                            else:
                                try:
                                    event = json.loads(data)
                                    mark('sse', event.get('type', 'content'),
                                         success=event.get('success'), error=event.get('error'))
                                except ValueError:
                                    mark('sse', 'unparsed')
                await send(message)
            try:
                await self.app(scope, receive, timed_send)
            finally:
                row['total_ms'] = round((time.perf_counter()-row.pop('_start'))*1000, 3)
                requests.append(row)
                active = None

    config.app.add_middleware(TimingMiddleware)
    fixtures = workspace / 'timing-profiles.json'
    fixtures.write_text(json.dumps([dict(id='timing_synthetic', name='云杉',
        prompt='云杉是成年独角兽小马，有四蹄和独角。温和但有自己的主见，喜欢读书，日常说话自然简洁。',
        profileIntro='云杉是温和、有主见的成年独角兽小马。',
        profileSpecies='独角兽小马', profilePersonality='温和，有主见')], ensure_ascii=False))
    cases = workspace / 'timing-cases.json'
    default_cases = [
        ['simple_first', '首轮闲聊', '晚上好，今天想和你轻松聊两句。'],
        ['memory', '保存记忆', '请记住，我以后喝茶更喜欢薄荷茶。今天刚忙完，想歇一会儿。'],
        ['simple_again', '再次闲聊', '我今天终于把拖了一个星期的事情搞定了，现在特别开心！'],
    ]
    cases.write_text(json.dumps(json.loads(Path(os.environ['PONYCHAT_TIMING_CASES']).read_text())
        if os.environ.get('PONYCHAT_TIMING_CASES') else default_cases, ensure_ascii=False))
    os.environ['PONYCHAT_STYLE_PROFILES'] = str(fixtures)
    os.environ['PONYCHAT_STYLE_CASES'] = str(cases)
    os.environ['PONYCHAT_STYLE_PROGRESS'] = str(workspace / 'progress.json')
    result = await matrix.exercise(workspace)
    result['node_timings'] = requests
    result['observed_source_hashes'] = {str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
        for name in ('autonomous_delivery.py', 'autonomous_normal.py',
                     'autonomous_prompt_skills.py', 'autonomous_service.py', 'character.py',
                     'personal_preferences.py', 'request_context.py', 'service_impl/chat_request.py')
        for path in [workspace / 'Backend/chat_modules' / name]}
    result['measurement'] = {
        'clock': 'perf_counter; spans overlap and must not be summed',
        'transport': 'ASGI send timestamps, excludes public network and device rendering',
        'synthetic_profile': True, 'voice_enabled': False,
        'pool_enabled': os.getenv('PONYCHAT_HARNESS_POOL', '0'),
        'sdk_note': 'captured_on_completion events are not live model timing measurements',
        'candidate_overlay': bool(overlay),
    }
    return result


if __name__ == '__main__':
    os.environ.setdefault('PONYCHAT_SMOKE_TIMEOUT_SECONDS', '700')
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
