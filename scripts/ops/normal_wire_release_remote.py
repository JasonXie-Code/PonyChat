"""Scoped candidate preparation, verification and rollback-safe activation."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path('/opt/ponychat')
FILES = ['Backend/chat_modules/' + name + '.py' for name in (
    'autonomous_reply', 'autonomous_direct', 'autonomous_prompt_skills', 'autonomous_wire_format')]
TESTS = ['test_autonomous_wire_format', 'test_autonomous_reply', 'test_autonomous_prompt_skills',
         'test_autonomous_normal', 'test_autonomous_delivery']
PYTHON = str(ROOT / '.venv/bin/python')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def smoke(stage, overlay, name):
    wrapper = stage / 'smoke_overlay.py'
    wrapper.write_text('''import os,sys,shutil
from pathlib import Path
import smoke_deployed_harness as smoke
original=smoke.exercise
async def exercise(workspace):
    overlay=os.environ.get('NORMAL_WIRE_OVERLAY')
    if overlay:
        for name in ''' + repr(FILES) + ''':
            shutil.copy2(Path(overlay)/name,workspace/name)
    return await original(workspace)
smoke.exercise=exercise
sys.exit(smoke.main())
''')
    env = {**os.environ, 'PONYCHAT_SMOKE_USERNAME': 'System', 'PONYCHAT_SMOKE_CLIENT_ID': 'android',
           'PONYCHAT_HARNESS_POOL': '1', 'PONYCHAT_SMOKE_TIMEOUT_SECONDS': '240'}
    if overlay:
        env['NORMAL_WIRE_OVERLAY'] = str(overlay)
    report = stage / (name + '.json')
    run([PYTHON, str(wrapper), str(report), '--source', str(ROOT)], env=env, timeout=280)
    result = json.loads(report.read_text())
    assert result['passed'] and not result['production_database_opened']
    return {k: result[k] for k in ('passed', 'status', 'elapsed_seconds', 'agent_memory_count',
                                   'production_database_opened', 'deployment_token')}


def prepare(stage):
    candidate = stage / 'candidate'
    candidate.mkdir(exist_ok=False)
    for directory, dirs, names in os.walk(ROOT / 'Backend'):
        dirs[:] = [d for d in dirs if d not in {'database', 'data', 'backups', 'Agent-Test', '__pycache__', '.git'}]
        for name in names:
            if not name.endswith(('.py', '.mjs')):
                continue
            source = Path(directory) / name
            target = candidate / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    base = {name: digest(ROOT / name) for name in FILES}
    run(['git', 'apply', '--check', str(stage / 'changes.patch')], cwd=candidate)
    run(['git', 'apply', str(stage / 'changes.patch')], cwd=candidate)
    for name in [FILES[-1], 'Backend/tests/test_autonomous_wire_format.py']:
        target = candidate / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stage / name, target)
    for name in FILES:
        compile((candidate / name).read_bytes(), name, 'exec')
    # Run the current local contract tests against the actual production candidate.
    for test in TESTS:
        shutil.copy2(stage / ('Backend/tests/' + test + '.py'), candidate / ('Backend/tests/' + test + '.py'))
    result = subprocess.run([PYTHON, '-m', 'pytest', *['Backend/tests/' + t + '.py' for t in TESTS], '-q'],
                            cwd=candidate, capture_output=True, text=True, timeout=120)
    (stage / 'pytest.txt').write_text(result.stdout + result.stderr)
    if result.returncode:
        print(result.stdout + result.stderr, flush=True)
        result.check_returncode()
    preflight = smoke(stage, candidate, 'predeploy-smoke')
    manifest = {'release': stage.name, 'base_hashes': base,
                'hashes': {name: digest(candidate / name) for name in FILES}, 'preflight': preflight}
    (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'prepared': True, **manifest, 'tests': result.stdout[-300:]}))


def activate(stage):
    cfg = json.loads((stage / 'manifest.json').read_text())
    backup = Path('/var/backups/ponychat-normal-wire') / stage.name
    assert all(digest(ROOT / n) == h for n, h in cfg['base_hashes'].items()), 'Production source drift'
    assert all(digest(stage / 'candidate' / n) == h for n, h in cfg['hashes'].items()), 'Candidate drift'
    backup.mkdir(parents=True, exist_ok=False, mode=0o700)
    names = FILES + ['Backend/.deploy_revision']
    existed = {n: (ROOT / n).exists() for n in names}
    for name in names:
        if existed[name]:
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
    (backup / 'manifest.json').write_text(json.dumps({'existed': existed, **cfg}, indent=2))
    unit = 'ponychat-backend'
    try:
        run(['systemctl', 'stop', unit])
        for name in FILES:
            shutil.copy2(stage / 'candidate' / name, ROOT / name)
        (ROOT / 'Backend/.deploy_revision').write_text(json.dumps({'deploy_token': stage.name}))
        run(['systemctl', 'start', unit])
        for attempt in range(30):
            try:
                health = json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3))
                if health.get('deploy_token') == stage.name:
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Deployment health mismatch')
        postflight = smoke(stage, None, 'postdeploy-smoke')
        public = json.load(urllib.request.urlopen('https://www.ponychat.org/api/health', timeout=20))
        assert public.get('deploy_token') == stage.name
        assert all(digest(ROOT / n) == h for n, h in cfg['hashes'].items())
        run(['systemctl', 'is-active', '--quiet', unit])
        receipt = {'deployed': True, 'release': stage.name, 'backup': str(backup),
                   'hashes': cfg['hashes'], 'public_health': public, 'postflight': postflight}
        (stage / 'deployment.json').write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt))
    except BaseException:
        run(['systemctl', 'stop', unit])
        for name in names:
            if existed[name]:
                shutil.copy2(backup / name, ROOT / name)
            else:
                (ROOT / name).unlink(missing_ok=True)
        run(['systemctl', 'start', unit])
        raise


if __name__ == '__main__':
    action, value = sys.argv[1:]
    stage = Path(value).resolve()
    assert stage.parent == Path('/tmp') and stage.name.startswith('normal-wire-')
    with open('/var/lock/ponychat-agent-deploy.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        {'prepare': prepare, 'activate': activate}[action](stage)
