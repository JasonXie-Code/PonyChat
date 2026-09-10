"""Read-only Agent progress, shared by API workers; never stores prompts or replies."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from contextlib import closing

import psutil

_PROCESS = [os.getpid(), psutil.Process().create_time()]


def _process_alive(identity):
    try:
        return bool(identity and psutil.Process(identity[0]).create_time() == identity[1])
    except (psutil.Error, OSError):
        return False


def _path():
    return Path(os.getenv('PONYCHAT_AGENT_STATUS_DB_PATH') or
                Path(__file__).resolve().parents[2] / 'var' / 'agent-status.sqlite3')


def _connect():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=1)
    conn.execute('CREATE TABLE IF NOT EXISTS progress '
                 '(owner TEXT, trace TEXT, conversation TEXT, updated REAL, payload TEXT, '
                 'PRIMARY KEY(owner, trace))')
    conn.execute('CREATE INDEX IF NOT EXISTS progress_owner_updated ON progress(owner, updated DESC)')
    return conn


def _owner(username, character_id, mode):
    return hashlib.sha256(json.dumps([username, character_id, mode]).encode()).hexdigest()


def begin(scope):
    mode = scope['mode']
    if not scope.get('username') or not scope.get('character_id') or mode not in (
            'normal', 'galgame', 'galgame_lock', 'agent_memory'):
        return None
    params = scope['params']
    key = (_owner(scope['username'], scope.get('status_character_id') or scope['character_id'],
                  'normal' if mode == 'agent_memory' else mode),
           str(params['trace_id']))
    now = time.time()
    with closing(_connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT payload FROM progress WHERE owner=? AND trace=?', key).fetchone()
        state = json.loads(row[0]) if row else {
            'run_id': key[1], 'mode': 'normal' if mode == 'agent_memory' else mode,
            'phase': 'background_memory' if mode == 'agent_memory' or params.get('phase') == 'background_memory' else 'foreground',
            'model': scope['model'], 'started_at': now, '_runs': {},
        }
        state.update(status='running', activity='准备本次任务', finished_at=None, updated_at=now, _process=_PROCESS)
        for run in state['_runs'].values():
            run['active_tools'] = {}
        conn.execute('INSERT OR REPLACE INTO progress VALUES(?,?,?,?,?)',
                     (*key, str(params.get('conversation_id') or ''), now, json.dumps(state, ensure_ascii=False)))
        conn.execute('DELETE FROM progress WHERE updated < ?', (now - 86400,))
    return key


def _change(key, change):
    if key is None:
        return
    with closing(_connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT payload FROM progress WHERE owner=? AND trace=?', key).fetchone()
        if row is None:
            return
        state = json.loads(row[0])
        change(state)
        state['updated_at'] = time.time()
        conn.execute('UPDATE progress SET updated=?, payload=? WHERE owner=? AND trace=?',
                     (state['updated_at'], json.dumps(state, ensure_ascii=False), *key))


def set_model(key, model):
    """Publish the actual invocation model, including before a call fails."""
    _change(key, lambda state: state.update(model=str(model)))


def event(key, run_id, kind, data):
    if not isinstance(data, dict):
        return
    def update(state):
        run = state['_runs'].setdefault(run_id, {
            'steps': [], 'tools': [], 'models': 0, 'tool_count': 0, 'recent_tools': []})
        if kind in ('step/start', 'step/end', 'assistant/message'):
            if data.get('turn') is None or data.get('step') is None:
                return
            step = str(data['turn']) + ':' + str(data['step'])
            if step not in run['steps']:
                run['steps'].append(step)
            state['activity'] = '正在调用模型' if kind == 'step/start' else '正在处理模型结果'
        elif kind in ('tool/start', 'tool/execution'):
            call_id = data.get('tool_call_id')
            if call_id and data.get('billable', True) and call_id not in run['tools']:
                run['tools'].append(call_id)
            # Tool identifiers are trusted registered names, never tool arguments/results.
            name = str(data.get('tool') or '')[:64]
            active = run.setdefault('active_tools', {})
            recent = run.setdefault('recent_tools', [])
            if name and (not recent or recent[-1] != name):
                recent.append(name)
                del recent[:-5]
            if kind == 'tool/start' and name:
                active[str(call_id or name)] = name
            else:
                active.pop(str(call_id or name), None)
            state['activity'] = ('正在执行工具：' if kind == 'tool/start' else '工具执行已结束：') + name
        else:
            return
        run['models'] = max(run['models'], len(run['steps']))
        run['tool_count'] = max(run['tool_count'], len(run['tools']))
    _change(key, update)


def settle_run(key, run_id, result):
    def update(state):
        run = state['_runs'].setdefault(run_id, {
            'steps': [], 'tools': [], 'models': 0, 'tool_count': 0, 'recent_tools': []})
        for target, source in (('models', 'llm_api_calls'), ('tool_count', 'tool_call_count')):
            count = result.get(source, 0)
            if type(count) is int and count >= 0:
                run[target] = max(run[target], count)
        state['activity'] = '正在整理本次结果'
        run['active_tools'] = {}
    _change(key, update)


def retry(key, retry_count):
    def update(state):
        state.update(status='running', activity='本次执行未成功，正在立即重试',
                     retry_count=retry_count, finished_at=None)
    _change(key, update)


def finish(key, status):
    def update(state):
        state.update(status=status, finished_at=time.time(), activity={
            'success': '本次 Agent 任务已结束', 'timeout': '本次任务已超时',
            'interrupted': '本次任务已中断', 'error': '本次任务执行失败',
        }.get(status, '本次任务已结束'))
    _change(key, update)


def _candidates(username, character_id, mode, conversation_id=None, *, all_modes=False):
    owners = [_owner(username, character_id, item) for item in
              (('normal', 'galgame', 'galgame_lock') if all_modes else (mode,))]
    with closing(_connect()) as conn:
        rows = conn.execute('SELECT conversation, payload FROM progress WHERE owner IN (' +
                            ','.join('?' for _ in owners) + ') ORDER BY updated DESC LIMIT 120', owners).fetchall()
    candidates = []
    now = time.time()
    for conversation, payload in rows:
        state = json.loads(payload)
        if conversation_id and conversation != conversation_id and state['phase'] != 'background_memory':
            continue
        if now - state['updated_at'] > 86400:
            continue
        if state['status'] == 'running' and (now - state['updated_at'] > 600 or not _process_alive(state.get('_process'))):
            state.update(status='stale', activity='状态更新已中断', finished_at=state['updated_at'])
        candidates.append(state)
    return candidates


def _public(state, now):
    state = dict(state)
    runs = state.pop('_runs')
    state.pop('_process', None)
    models = sum(run['models'] for run in runs.values())
    tools = sum(run['tool_count'] for run in runs.values())
    active = list(dict.fromkeys(name for run in runs.values()
                               for name in run.get('active_tools', {}).values()))
    recent = list(dict.fromkeys(name for run in runs.values()
                               for name in run.get('recent_tools', [])))
    return {**state, 'model_calls': models, 'tool_calls': tools, 'points': models + tools,
            'current_tools': active if state['status'] == 'running' else [],
            'recent_tools': recent[-5:],
            'elapsed_ms': max(0, round(((state['finished_at'] or now) - state['started_at']) * 1000))}


def read(username, character_id, mode, conversation_id=None):
    candidates = _candidates(username, character_id, mode, conversation_id)
    if not candidates:
        return None
    # Prefer the current foreground task, then active background memory, then the latest result.
    state = next((s for s in candidates if s['status'] == 'running' and s['phase'] == 'foreground'), None)
    state = state or next((s for s in candidates if s['status'] == 'running'), candidates[0])
    return _public(state, time.time())


def read_all(username, character_id, mode):
    """All active Agents for this owner/character, or the latest result per task kind."""
    candidates = _candidates(username, character_id, mode, all_modes=True)
    active_groups = {(s['mode'], s['phase']) for s in candidates if s['status'] == 'running'}
    selected, seen = [], set()
    for state in candidates:
        group = (state['mode'], state['phase'])
        if state['status'] != 'running' and (group in active_groups or group in seen):
            continue
        seen.add(group)
        selected.append(state)
    selected.sort(key=lambda s: (s['status'] != 'running', s['mode'] != mode,
                                 s['phase'] != 'foreground', -s['updated_at']))
    return [_public(state, time.time()) for state in selected]
