"""Start the configured local vision model and switch PonyChat's default model."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'server/config.json'
MANIFEST = ROOT.parent / 'Backend/conf/model_config.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def probe(route):
    cfg = read(CONFIG)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{cfg['port']}/{route}", timeout=3) as response:
        return json.load(response)


def ready():
    try:
        cfg = read(CONFIG)
        props = probe('props')
        listing = probe('v1/models')
        models = listing['data']
        return (any(m['id'] == cfg['alias'] for m in models)
                and any('multimodal' in m.get('capabilities', []) for m in listing.get('models', []))
                and props['default_generation_settings']['n_ctx'] == cfg['n_ctx']
                and props['total_slots'] == cfg['parallel'])
    except (OSError, ValueError, KeyError):
        return False


def command(cfg):
    args = [str(ROOT / 'server/bin/llama-server.exe')]
    for key in ('model', 'mmproj'):
        path = ROOT / cfg[key]
        if not path.is_file():
            raise FileNotFoundError(path)
        args += ['--' + key, str(path)]
    for option, value in {
        'host': '127.0.0.1', 'port': cfg['port'], 'alias': cfg['alias'],
        'ctx-size': cfg['n_ctx'], 'parallel': cfg['parallel'],
        'n-gpu-layers': cfg['n_gpu_layers'], 'batch-size': cfg['n_batch'],
        'threads': cfg['n_threads'], 'n-predict': cfg['n_predict'],
        'reasoning-budget': cfg['reasoning_budget'], 'cache-type-k': 'q8_0',
        'cache-type-v': 'q8_0', 'flash-attn': 'on',
    }.items():
        args += ['--' + option, str(value)]
    return args + ['--jinja']


def start():
    if ready():
        print('Local Qwen vision server is ready: 131072 tokens, one slot.')
        return
    # Never terminate other llama-server processes or replace an occupied port.
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', read(CONFIG)['port']))
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    with (logs / 'qwen.stdout.log').open('ab') as out, (logs / 'qwen.stderr.log').open('ab') as err:
        child = subprocess.Popen(command(read(CONFIG)), cwd=ROOT, stdin=subprocess.DEVNULL,
            stdout=out, stderr=err, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f'Local model exited {child.returncode}; see {logs}')
        if ready():
            print(f'Local Qwen vision server ready; PID {child.pid}')
            return
        time.sleep(1)
    raise TimeoutError(f'Local model is still loading; see {logs}')


def stop():
    """Stop only this installation's configured Qwen process."""
    import psutil
    executable = (ROOT / 'server/bin/llama-server.exe').resolve()
    alias = read(CONFIG)['alias']
    stopped = []
    for process in psutil.process_iter(['exe', 'cmdline']):
        try:
            if not process.info['exe'] or Path(process.info['exe']).resolve() != executable:
                continue
            args = process.info['cmdline'] or []
            if '--alias' not in args or args[args.index('--alias') + 1] != alias:
                continue
            process.terminate()
            process.wait(timeout=15)
            stopped.append(process.pid)
        except psutil.NoSuchProcess:
            pass
    print(f'Stopped local Qwen processes: {stopped}')


def select(model_id):
    if model_id == 'qwen3.5-4b-local':
        start()
    manifest = read(MANIFEST)
    manifest['active_model'] = model_id
    pending = MANIFEST.with_suffix('.json.tmp')
    pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(pending, MANIFEST)
    print(f'PonyChat main chat model: {model_id}. Backend selection applies to all users.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status', 'qwen', 'deepseek'])
    args = parser.parse_args()
    if args.action == 'start':
        start()
    elif args.action == 'stop':
        stop()
    elif args.action == 'status':
        print(json.dumps({'ready': ready(), 'active_model': read(MANIFEST)['active_model']}, indent=2))
    else:
        select('qwen3.5-4b-local' if args.action == 'qwen' else 'deepseek-flash')
