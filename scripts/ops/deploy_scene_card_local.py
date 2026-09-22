"""Activate a tested scoped release on the current Windows production host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / 'docs/testing/scene-card-20260910'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--image-preflight', action='store_true')
    parser.add_argument('--reports', type=Path, help='A scoped report directory with manifest.json and predeploy-gated.json')
    args = parser.parse_args()
    assert os.name == 'nt'
    reports = args.reports or (ROOT / 'docs/testing/g4-image-defaults-20260910' if args.image_preflight else REPORTS)
    if args.image_preflight:
        tests = json.loads((reports / 'four-images.json').read_text(encoding='utf8'))
        visual = json.loads((reports / 'visual-review.json').read_text(encoding='utf8'))
        assert tests['passed'] and len(tests['cases']) == 4 and visual['passed']
        assert all(len(case['images']) == 1 and all(Path(p).is_file() for p in case['images']) for case in tests['cases'])
    else:
        tests = json.loads((reports / 'predeploy-gated.json').read_text(encoding='utf8'))
        assert tests['passed'] and len(tests['cases']) == 4 and not tests['production_database_opened']
        relative = json.loads((reports / 'predeploy-relative.json').read_text(encoding='utf8'))
        assert relative['passed'] and not relative['production_database_opened']
    names = json.loads((reports / 'manifest.json').read_text())
    assert not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT).strip()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    marker = ROOT / 'Backend/.deploy_revision'
    previous = json.loads(marker.read_text())
    release = ('local-g4-images-' if args.image_preflight else 'local-scene-card-') + time.strftime('%Y%m%d-%H%M%S') + '-' + revision[:8]
    backup = ROOT / 'var/local-stack/releases' / release
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(marker, backup / 'deploy_revision.json')
    old = {}
    for name in names:
        data = subprocess.run(['git', 'show', args.base + ':' + name], cwd=ROOT, capture_output=True)
        old[name] = data.returncode == 0
        if old[name]:
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data.stdout)
        compile((ROOT / name).read_bytes(), name, 'exec')
    with sqlite3.connect((ROOT / 'Backend/database/ponychat.db').as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(backup / 'ponychat.db') as target:
            source.backup(target)
    (backup / 'rollback.json').write_text(json.dumps({'files': old, 'base': args.base, 'previous_token': previous['deploy_token']}))

    def restart():
        status = json.loads((ROOT / 'var/local-stack/status.json').read_text())
        parent = psutil.Process(status['chat']['pid'])
        command = parent.cmdline()
        assert command[-2:] == ['-m', 'Backend'] and Path(command[0]).resolve().is_relative_to(ROOT)
        assert psutil.Process(status['supervisor_pid']).is_running()
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        _, remaining = psutil.wait_procs([parent, *children], timeout=5)
        assert not remaining, 'Old chat processes did not stop'
        return parent.pid

    file_names = subprocess.check_output(['git', 'ls-files', 'Backend'], cwd=ROOT).decode().splitlines()
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in file_names if name.endswith(('.py', '.mjs')) and (ROOT / name).is_file()}
    try:
        marker.write_text(json.dumps({**previous, 'deploy_token': release, 'git_commit': revision,
                                      'files': hashes}, indent=2), encoding='utf8')
        previous_pid = restart()
        with httpx.Client(trust_env=False, timeout=15) as client:
            for _ in range(45):
                try:
                    result = client.get('http://127.0.0.1:5000/api/health').json()
                    if result.get('deploy_token') == release:
                        break
                except Exception:
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('New backend did not become healthy')
            health = {}
            for key, base in [('local', 'http://127.0.0.1:5000'), ('cn', 'https://39.101.74.217'),
                              ('official', 'https://www.ponychat.org')]:
                response = client.get(base + '/api/health')
                response.raise_for_status()
                health[key] = response.json()
                assert health[key]['deploy_token'] == release
        receipt = {'passed': True, 'target': 'Windows P:/PonyChat; CN and USA forwarding',
                   'release': release, 'revision': revision, 'previous_pid': previous_pid,
                   'listener_pid': next(c.pid for c in psutil.net_connections(kind='tcp')
                                        if c.status == psutil.CONN_LISTEN and c.laddr.port == 5000),
                   'backup': str(backup), 'health': health, 'hashes': {n: hashes[n] for n in names}}
        (reports / 'deployment.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
    except BaseException:
        for name, existed in old.items():
            if existed:
                shutil.copy2(backup / name, ROOT / name)
            else:
                (ROOT / name).unlink(missing_ok=True)
        shutil.copy2(backup / 'deploy_revision.json', marker)
        restart()
        print('Restored previous code and marker; production DB preserved. Backup: ' + str(backup), flush=True)
        raise


if __name__ == '__main__':
    main()
