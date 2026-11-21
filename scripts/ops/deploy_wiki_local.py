"""Activate the committed local backend with verified previous-code rollback."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[2]


def main():
    marker = ROOT / 'Backend/.deploy_revision'
    previous = json.loads(marker.read_text(encoding='utf-8'))
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    names = subprocess.check_output(['git', 'ls-files', 'Backend'], cwd=ROOT).decode().splitlines()
    names = [n for n in names if n.endswith(('.py', '.mjs'))
             and not set(Path(n).parts).intersection({'tests', 'Agent-Test', 'data'})]
    hashes = {}
    for name in names:
        data = (ROOT / name).read_bytes()
        committed = subprocess.check_output(['git', 'show', revision + ':' + name], cwd=ROOT)
        assert data.replace(b'\r\n', b'\n') == committed.replace(b'\r\n', b'\n'), name
        hashes[name] = hashlib.sha256(data).hexdigest()
    changed = [n for n in names if previous.get('files', {}).get(n) != hashes[n]]
    release = 'local-wiki-' + time.strftime('%Y%m%d-%H%M%S') + '-' + revision[:8]
    backup = ROOT / 'var/local-stack/releases' / release
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(marker, backup / 'deploy_revision.json')
    old = {}
    reconstructed = []
    for name in changed:
        digest = previous.get('files', {}).get(name)
        old[name] = digest is not None
        if digest:
            data = subprocess.check_output(['git', 'show', previous['git_commit'] + ':' + name], cwd=ROOT)
            candidates = (data, data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
            matched = next((b for b in candidates if hashlib.sha256(b).hexdigest() == digest), None)
            if matched is None:
                # Older local releases can contain mixed line endings or an
                # uncommitted source snapshot. Retain the recorded revision as
                # a labeled reconstruction, never claim its raw hash matches.
                reconstructed.append(name)
            else:
                data = matched
            if name.endswith('.py'):
                compile(data, name, 'exec')
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    (backup / 'rollback.json').write_text(json.dumps({'files': old, 'previous': previous['deploy_token'],
        'reconstructed_from_revision': reconstructed, 'revision': previous['git_commit']}))
    with sqlite3.connect((ROOT / 'Backend/database/ponychat.db').as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(backup / 'ponychat.db') as target:
            source.backup(target)

    def restart():
        status = json.loads((ROOT / 'var/local-stack/status.json').read_text())
        parent = psutil.Process(status['chat']['pid'])
        assert parent.cmdline()[-2:] == ['-m', 'Backend']
        assert Path(parent.cwd()).resolve() == ROOT.resolve()
        assert psutil.Process(status['supervisor_pid']).is_running()
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        _, remaining = psutil.wait_procs([parent, *children], timeout=5)
        assert not remaining, 'Old backend did not stop'
        return parent.pid

    try:
        assert json.loads(marker.read_text()) == previous, 'Concurrent deployment detected'
        marker.write_text(json.dumps({**previous, 'deploy_token': release, 'git_commit': revision,
                                      'files': hashes}, indent=2), encoding='utf-8')
        old_pid = restart()
        with httpx.Client(trust_env=False, timeout=12) as client:
            for _ in range(35):
                try:
                    if client.get('http://127.0.0.1:5000/api/health').json().get('deploy_token') == release:
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('Backend did not become healthy')
            health = {}
            for name, base in [('local', 'http://127.0.0.1:5000'), ('cn', 'https://39.101.74.217'),
                               ('official', 'https://www.ponychat.org')]:
                response = client.get(base + '/api/health')
                response.raise_for_status()
                health[name] = response.json()
                assert health[name]['deploy_token'] == release
        receipt = {'release': release, 'revision': revision, 'previous_token': previous['deploy_token'],
                   'target': 'Windows P:/PonyChat; remote gateways forward here', 'previous_pid': old_pid,
                   'listener_pid': next(c.pid for c in psutil.net_connections(kind='tcp')
                                        if c.status == psutil.CONN_LISTEN and c.laddr.port == 5000),
                   'backup': str(backup), 'changed_runtime_files': changed,
                   'rollback_reconstructed_from_revision': reconstructed,
                   'hashes': {n: hashes[n] for n in changed}, 'health': health}
        (ROOT / 'docs/testing/wiki-deployment-20260910.json').write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
    except BaseException:
        for name, existed in old.items():
            if existed:
                shutil.copy2(backup / name, ROOT / name)
            else:
                (ROOT / name).unlink(missing_ok=True)
        shutil.copy2(backup / 'deploy_revision.json', marker)
        restart()
        raise


if __name__ == '__main__':
    main()
