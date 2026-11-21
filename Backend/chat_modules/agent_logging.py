"""Agent diagnostics using the existing chat debug files and log index.

Context variables isolate concurrent requests. SDK notifications arrive on a
worker thread, so event snapshots are locked and written on the async caller.
No credentials/config objects are accepted by the recorder.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from . import agent_status


def _publish_status(function, *args):
    try:
        return function(*args)
    except Exception:
        logging.getLogger(__name__).warning('Agent progress update failed', exc_info=True)

_scope = contextvars.ContextVar('agent_log_scope', default=None)
_run = contextvars.ContextVar('agent_log_run', default=None)
_secret_keys = {'apikey', 'authorization', 'password', 'secret', 'accesstoken',
                'refreshtoken', 'cookie', 'setcookie', 'ponychatharnesstoken'}


def snapshot(value, depth=0):
    """Copy JSON diagnostics; omit image bytes and redact credential fields."""
    if depth > 40:
        return '[depth limit]'
    if isinstance(value, dict):
        image = value.get('type') in ('image', 'image_url')
        return {str(k): ('[REDACTED]' if re.sub(r'[^a-z]', '', str(k).lower()) in _secret_keys
                        else '[image bytes omitted]' if image and k == 'data'
                        else snapshot(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [snapshot(v, depth + 1) for v in value]
    if isinstance(value, str):
        value = re.sub(r'data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+', '[image bytes omitted]', value)
        return re.sub(r'(?i)\bBearer\s+[^\s"\']+', 'Bearer [REDACTED]', value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return {'type': type(value).__name__}


def error_data(exc):
    return {'type': type(exc).__name__, 'message': snapshot(str(exc))}


def outcome(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, asyncio.CancelledError):
            return 'interrupted'
        if isinstance(exc, TimeoutError):
            return 'timeout'
        exc = exc.__cause__ or exc.__context__
    return 'error'


async def write(stage, data, *, params=None):
    scope = _scope.get()
    if scope is None:
        return
    try:
        from ..utils import save_chat_debug_log
        await save_chat_debug_log(scope['username'], scope['character_id'], scope['mode'],
            scope['model'], snapshot(data), stage,
            params={**scope['params'], **(params or {})})
    except Exception:
        logging.getLogger(__name__).warning('Agent diagnostic write failed', exc_info=True)


@asynccontextmanager
async def log_scope(username, character_id, mode, *, params=None, request=None, model_config=None):
    params = dict(params or {})
    trace = params.get('trace_id') or params.get('request_id') or params.get('job_id') or uuid.uuid4().hex
    params.update(trace_id=trace, request_id=params.get('request_id') or trace)
    if request is not None:
        request._agent_log_params = params
    token = _scope.set(dict(username=username, character_id=character_id, mode=mode,
                            status_character_id=getattr(request, 'character_id', None),
                            model=str((model_config or {}).get('model_name') or ''), params=params, run_count=0))
    _scope.get()['public_status'] = await asyncio.to_thread(_publish_status, agent_status.begin, _scope.get())
    started = time.monotonic()
    failure = None
    try:
        yield
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            await asyncio.shield(asyncio.to_thread(_publish_status, agent_status.finish,
                _scope.get().get('public_status'), outcome(failure) if failure else 'success'))
            await asyncio.shield(write('AGENT_EXECUTION_END', {
                'kind': 'agent_execution', 'status': outcome(failure) if failure else 'success',
                'phase': 'generation', 'latency_ms': round((time.monotonic()-started)*1000),
                'harness_runs': _scope.get()['run_count'],
                'error': error_data(failure) if failure else None,
            }))
        finally:
            _scope.reset(token)


async def announce_retry(exc, retry_count):
    """Keep the same foreground task running while its one recovery starts."""
    scope = _scope.get()
    if scope is None:
        return
    await asyncio.to_thread(_publish_status, agent_status.retry,
                          scope.get('public_status'), retry_count)
    await write('AGENT_EXECUTION_RETRY', {
        'kind': 'agent_retry', 'status': 'running', 'retry_count': retry_count,
        'error': error_data(exc), 'delay_seconds': 0,
    })


def logged_normal(function):
    @functools.wraps(function)
    async def wrapped(request, *args, **kwargs):
        from .normal_speaker import normal_role_debug_params, effective_speaker_character_id
        params = normal_role_debug_params(request)
        params['conversation_id'] = getattr(request, 'conversation_id', None)
        params['job_id'] = getattr(request, '_normal_accepted_job_id', None)
        async with log_scope(request.username, effective_speaker_character_id(request) or request.character_id,
                             'normal', params=params, request=request,
                             model_config=kwargs.get('model_config') or (args[0] if args else None)):
            return await function(request, *args, **kwargs)
    return wrapped


def logged_game(function):
    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        debug = kwargs.get('chat_debug_request') or {}
        if not debug:
            return await function(*args, **kwargs)
        params = {**(debug.get('params') or {}), **(kwargs.get('agent_debug_params') or {}),
                  'parent_stage': debug.get('stage')}
        async with log_scope(debug.get('username'), debug.get('character_id'), kwargs.get('mode', 'galgame'),
                             params=params):
            return await function(*args, **kwargs)
    return wrapped


def logged_persistence(function):
    @functools.wraps(function)
    async def wrapped(request, model_name, full_text, *args, **kwargs):
        params = getattr(request, '_agent_log_params', None)
        if not params:
            return await function(request, model_name, full_text, *args, **kwargs)
        token = _scope.set(dict(username=request.username, character_id=request.character_id,
                                mode=request.mode, model=model_name, params=dict(params)))
        started, result, failure = time.monotonic(), None, None
        try:
            result = await function(request, model_name, full_text, *args, **kwargs)
            return result
        except BaseException as exc:
            failure = exc
            raise
        finally:
            try:
                await asyncio.shield(write('AGENT_PERSIST_RESULT', {
                    'kind': 'agent_persistence', 'phase': 'persistence',
                    'status': outcome(failure) if failure else 'success' if result[0] else 'error',
                    'submitted_reply': full_text, 'persist_user_only': kwargs.get('persist_user_only', False),
                    'save_ok': result[0] if result else False, 'message_ids': result[2] if result else None,
                    'error': error_data(failure) if failure else result[1] or None,
                    'latency_ms': round((time.monotonic()-started)*1000),
                }, params={'conversation_id': getattr(request, 'conversation_id', None)}))
            finally:
                _scope.reset(token)
    return wrapped


class RunRecorder:
    def __init__(self, params):
        self.started = time.monotonic()
        self.events = []
        self.dropped = 0
        self.lock = threading.Lock()
        self.step_started = {}
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self.params = params
        self.public_status = (_scope.get() or {}).get('public_status')
        self.writer = asyncio.create_task(self.drain())

    def add(self, kind, data):
        with self.lock:
            if len(self.events) >= 4000:
                self.dropped += 1
                return
            captured = snapshot(data)
            if isinstance(captured, dict):
                step_key = (captured.get('turn'), captured.get('step'))
                if kind == 'step/start':
                    self.step_started[step_key] = time.monotonic()
                elif kind == 'step/end' and step_key in self.step_started:
                    captured['latency_ms'] = round((time.monotonic()-self.step_started.pop(step_key))*1000)
            self.events.append({'sequence': len(self.events)+1, 'type': kind,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'elapsed_ms': round((time.monotonic()-self.started)*1000), 'data': captured})
            if kind in ('step/start', 'step/end', 'assistant/message', 'tool/start', 'tool/execution'):
                self.loop.call_soon_threadsafe(self.queue.put_nowait, self.events[-1])

    async def drain(self):
        while True:
            event = await self.queue.get()
            try:
                if event is None:
                    return
                data = event['data'] if isinstance(event['data'], dict) else {}
                await asyncio.to_thread(_publish_status, agent_status.event,
                    self.public_status, self.params['run_id'], event['type'], data)
                stage = {'step/start': 'AGENT_STEP_START', 'step/end': 'AGENT_STEP_END',
                         'assistant/message': 'AGENT_STEP_RESPONSE', 'tool/start': 'AGENT_TOOL_REQUEST',
                         'tool/execution': 'AGENT_TOOL_RESULT'}[event['type']]
                await write(stage, {'kind': 'agent_event', 'status': data.get('status', 'success'),
                    'events': [event], 'latency_ms': data.get('latency_ms', 0),
                    'error': data.get('error')},
                    params={**self.params, 'event_sequence': event['sequence'],
                            'sdk_turn': data.get('turn'), 'sdk_step': data.get('step'),
                            'tool_call_id': data.get('tool_call_id')})
            finally:
                self.queue.task_done()

    async def close(self):
        # Thread-safe enqueue callbacks already scheduled by the SDK run first.
        await asyncio.sleep(0)
        await self.queue.put(None)
        await self.writer


def record_event(kind, data):
    recorder = _run.get()
    if recorder is not None:
        try:
            recorder.add(kind, data)
        except Exception:
            logging.getLogger(__name__).warning('Agent event capture failed', exc_info=True)


def reconcile_sdk_events(events):
    """Some SDK versions return settled messages without notifying subscribers.

Recover those model steps once at completion; receipt time is explicitly marked
so the UI does not present it as a measured model execution timestamp.
"""
    recorder = _run.get()
    if recorder is None:
        return
    with recorder.lock:
        seen = {(e['type'], e['data'].get('turn'), e['data'].get('step'))
                for e in recorder.events if isinstance(e['data'], dict)}
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = event.get('type') or event.get('kind')
        data = event.get('data') or {}
        if kind not in ('step/start', 'step/end', 'assistant/message') or not isinstance(data, dict):
            continue
        key = (kind, data.get('turn'), data.get('step'))
        if key not in seen:
            record_event(kind, {**data, 'captured_on_completion': True})
            seen.add(key)


def current_params():
    scope = _scope.get()
    return dict(scope['params']) if scope else {}


def logged_harness(function):
    @functools.wraps(function)
    async def wrapped(prompt, model_config, tools, **kwargs):
        scope = _scope.get()
        if scope is None:
            return await function(prompt, model_config, tools, **kwargs)
        from .harness_runtime import MODEL
        scope['model'] = str(model_config.get('model_name') or MODEL)
        await asyncio.to_thread(_publish_status, agent_status.set_model,
                                scope.get('public_status'), scope['model'])
        scope['run_count'] += 1
        run_id = uuid.uuid4().hex
        params = {'run_id': run_id, 'run_number': scope['run_count']}
        recorder = RunRecorder(params)
        token = _run.set(recorder)
        request = {'system_prompt': kwargs.get('system_prompt', '你是一个自然、温暖的对话助手。按需使用提供的聊天工具。'),
            'prompt': prompt, 'tools': [{'name': name, 'description': getattr(tool, 'description', name),
                'parameters': getattr(tool, 'parameters', {})} for name, tool in tools.items()],
            'max_tokens': kwargs.get('max_tokens', 8192), 'max_tool_calls': kwargs.get('max_tool_calls', 12),
            'timeout_seconds': kwargs.get('timeout_seconds', 120),
            'reasoning_effort': None if model_config.get('harness_provider') == 'local-openai' else 'low'}
        result, failure = {}, None
        try:
            await write('AGENT_RUN_REQUEST', {'kind': 'agent_request', 'status': 'success',
                'request': request}, params=params)
            result = await function(prompt, model_config, tools, **kwargs)
            return result
        except BaseException as exc:
            failure = exc
            result = getattr(exc, 'harness_usage', {})
            raise
        finally:
            try:
                latency_ms = round((time.monotonic()-recorder.started)*1000)
                await asyncio.shield(recorder.close())
                await asyncio.shield(asyncio.to_thread(_publish_status, agent_status.settle_run,
                    scope.get('public_status'), run_id, result))
                status = outcome(failure) if failure else ('success' if result.get('finish_reason') == 'completed' else 'error')
                await asyncio.shield(write('AGENT_RUN_RESPONSE', {
                    'kind': 'agent_run', 'status': status, 'request': request,
                    'latency_ms': latency_ms,
                    'final_response': result.get('final_response'), 'finish_reason': result.get('finish_reason'),
                    'usage': result.get('usage', {}), 'llm_api_calls': result.get('llm_api_calls', 0),
                    'runtime_reused': result.get('runtime_reused', False),
                    'tool_call_count': result.get('tool_call_count', 0),
                    'events': recorder.events, 'events_dropped': recorder.dropped,
                    'sdk_events': result.get('events', []),
                    'error': error_data(failure) if failure else (
                        {'type': 'IncompleteRun', 'message': str(result.get('finish_reason'))} if status != 'success' else None),
                }, params=params))
            finally:
                _run.reset(token)
    return wrapped
