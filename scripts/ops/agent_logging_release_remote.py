"""Prepare and activate the bounded Agent logging patch on Server-USA."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = Path('/opt/ponychat')
STATIC = Path('/var/www/ponychat-static')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def apply_check(patch, cwd, reverse=False):
    command = ['git', 'apply', '--ignore-space-change', '--check']
    if reverse:
        command.append('--reverse')
    return subprocess.run([*command, str(patch)], cwd=cwd, capture_output=True).returncode == 0


def prepare(stage, manifest):
    candidate = stage / 'candidate'
    candidate.mkdir(exist_ok=True)
    before, after, changes = {}, {}, []
    for name, expected in manifest['backend'].items():
        source, target = ROOT / name, candidate / name
        before[name] = digest(source)
        patches = sorted((stage/'patches').glob(name.replace('/', '__') + '.*.patch'))
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            target.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
        if digest(target) == expected:
            after[name] = digest(source)
            continue
        for patch in patches:
            if target.exists() and apply_check(patch, candidate, reverse=True):
                continue
            assert apply_check(patch, candidate), 'Patch cannot safely apply: ' + name
            subprocess.run(['git', 'apply', '--ignore-space-change', str(patch)], cwd=candidate, check=True)
        compile(target.read_bytes(), name, 'exec')
        after[name] = digest(target)
        if after[name] != before[name]:
            changes.append(name)
    assert (STATIC / 'index.html').is_file()
    static_before = {name: digest(STATIC / name) for name in manifest['frontend']}
    result = dict(backend_before=before, backend_after=after, changes=changes, static_before=static_before)
    (stage / 'plan.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({'prepared': True, **result}))


def activate(stage, manifest):
    plan = json.loads((stage / 'plan.json').read_text())
    # Compare-and-swap under the shared deployment lock; never overwrite a newer release.
    assert all(digest(ROOT/n) == h for n, h in plan['backend_before'].items()), 'Backend changed since preparation'
    assert all(digest(STATIC/n) == h for n, h in plan['static_before'].items()), 'Frontend changed since preparation'
    assert subprocess.run(['systemctl', 'is-active', '--quiet', 'ponychat-backend.service']).returncode == 0
    backup = Path('/var/backups/ponychat-agent-logging') / manifest['release']
    backup.mkdir(parents=True, exist_ok=False)
    backup.chmod(0o700)
    targets = {n: ROOT/n for n in plan['changes']}
    targets['Backend/.deploy_revision'] = ROOT/'Backend/.deploy_revision'
    targets.update({'static/'+n: STATIC/n for n in manifest['frontend']})
    existed = {}
    for name, target in targets.items():
        existed[name] = target.is_file()
        if target.is_file():
            saved = backup/name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
    (backup/'manifest.json').write_text(json.dumps({'targets': {n: str(p) for n,p in targets.items()}, 'existed': existed}))
    stopped = False
    try:
        subprocess.run(['systemctl', 'stop', 'ponychat-backend.service'], check=True)
        stopped = True
        db = ROOT/'Backend/database/ponychat.db'
        with sqlite3.connect(db) as src, sqlite3.connect(backup/'ponychat.db') as dest:
            src.backup(dest)
        for name in plan['changes']:
            target = ROOT/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage/'candidate'/name, target)
            assert digest(target) == plan['backend_after'][name]
        # Add assets first; old hashed bundles remain available to open browser tabs.
        for name in manifest['frontend']:
            if name == 'index.html':
                continue
            target = STATIC/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage/'frontend'/name, target)
        (ROOT/'Backend/.deploy_revision').write_text(json.dumps({'deploy_token': manifest['release'],
            'revision': manifest['revision'], 'scope': 'agent-logging-patch'}))
        subprocess.run(['systemctl', 'start', 'ponychat-backend.service'], check=True)
        for _ in range(45):
            try:
                health = json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3))
                if health.get('deploy_token') == manifest['release']:
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Backend did not activate')
        pending = STATIC/('index.'+manifest['release']+'.tmp')
        shutil.copy2(stage/'frontend/index.html', pending)
        pending.replace(STATIC/'index.html')
        assert all(digest(STATIC/n) == h for n,h in manifest['frontend'].items())
        with sqlite3.connect(db) as conn:
            assert conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        receipt = {'target': 'Server-USA', 'release': manifest['release'], 'source_revision': manifest['revision'],
            'backup': str(backup), 'health': health, 'backend_hashes': plan['backend_after'],
            'changed_backend': plan['changes'], 'frontend_hashes': manifest['frontend']}
        (stage/'receipt.json').write_text(json.dumps(receipt, indent=2))
        (backup/'receipt.json').write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt))
    except BaseException:
        if stopped:
            subprocess.run(['systemctl', 'stop', 'ponychat-backend.service'], check=False)
            for name,target in targets.items():
                if existed[name]:
                    shutil.copy2(backup/name, target)
                else:
                    target.unlink(missing_ok=True)
            subprocess.run(['systemctl', 'start', 'ponychat-backend.service'], check=True)
        print('ROLLED_BACK '+str(backup))
        raise


if __name__ == '__main__':
    stage = Path(sys.argv[2]).resolve()
    assert stage.parent == Path('/tmp') and stage.name.startswith('ponychat-logs-')
    manifest = json.loads((stage/'manifest.json').read_text())
    assert sys.argv[1] in ('prepare', 'activate')
    (prepare if sys.argv[1] == 'prepare' else activate)(stage, manifest)
