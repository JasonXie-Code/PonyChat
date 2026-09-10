"""Publish the built log-page fix, retaining old assets and atomically replacing HTML."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import urllib.request

import compare_server_backend as ssh
from ssh_lib import scp_to

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / 'PonyChat-Website/Main/frontend/dist'
REMOTE = '/var/www/ponychat-static'


def remote(server, script):
    path = f'/tmp/ponychat-static-check-{time.time_ns()}.py'
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / 'remote.py'
        source.write_text(script, encoding='utf-8')
        assert scp_to(server, source, path) == 0
    code, out, err = ssh._ssh_capture(server, f"python3 {path}")
    if code:
        raise RuntimeError(err or out)
    return json.loads(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--deploy', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    hashes = {p.relative_to(DIST).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in DIST.rglob('*') if p.is_file()}
    assert 'index.html' in hashes
    server = ssh.load_server('usa')
    old = remote(server, f"""
import hashlib,json
from pathlib import Path
root=Path({REMOTE!r})
names={list(hashes)!r}
print(json.dumps({{name: hashlib.sha256((root/name).read_bytes()).hexdigest() if (root/name).is_file() else None for name in names}}))
""")
    changed = [name for name in hashes if old[name] != hashes[name]]
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    release = f'log-page-{time.strftime("%Y%m%d-%H%M%S")}-{revision[:8]}'
    report = {'target': 'Server-USA', 'revision': revision, 'release': release,
              'changedFiles': changed, 'hashes': hashes, 'deployed': False}
    if args.deploy and changed:
        archive = f'/tmp/{release}.tar.gz'
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / 'static.tar.gz'
            with tarfile.open(bundle, 'w:gz') as tar:
                for name in changed:
                    tar.add(DIST / name, arcname=name)
            assert scp_to(server, bundle, archive) == 0
        result = remote(server, f"""
import hashlib,json,os,shutil,tarfile
from pathlib import Path
root=Path({REMOTE!r})
backup=Path('/var/backups/ponychat-log-page')/{release!r}
backup.mkdir(parents=True,mode=0o700)
hashes={hashes!r}
old={old!r}
changed={changed!r}
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
assert all(digest(root/name)==old[name] for name in changed), 'Concurrent static deployment'
with tarfile.open({archive!r}) as tar:
    assert all(m.name in changed and m.isfile() for m in tar.getmembers())
    tar.extractall(backup/'staged')
assert all(digest(backup/'staged'/name)==hashes[name] for name in changed)
(backup/'before.json').write_text(json.dumps({{name:old[name] for name in changed}}))
for name in changed:
    if old[name] is not None:
        (backup/'before'/name).parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/name,backup/'before'/name)
try:
    for name in sorted(changed,key=lambda name: name=='index.html'):
        destination=root/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=destination.with_name(destination.name+'.log-page-tmp')
        shutil.copy2(backup/'staged'/name,temporary)
        os.replace(temporary,destination)
    assert all(digest(root/name)==value for name,value in hashes.items())
except Exception:
    for name in changed:
        if old[name] is not None:
            shutil.copy2(backup/'before'/name,root/name)
    raise
Path({archive!r}).unlink()
print(json.dumps({{'backup':str(backup),'allHashesVerified':True}}))
""")
        report.update(result, deployed=True)
    url = f'https://admin.ponychat.org/admin/conversation-logs?release={release}'
    with urllib.request.urlopen(url, timeout=30) as response:
        report['publicHtmlVerified'] = hashlib.sha256(response.read()).hexdigest() == hashes['index.html']
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'hashes'}))
    if args.deploy:
        assert report['publicHtmlVerified'], 'Public HTML does not match deployed build'


if __name__ == '__main__':
    main()
