"""Build, stage or activate only the Agent logging release. No application config changes."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
KEYS = ROOT.parent/'ServerKeys'
LOG_COMMIT = '371f35b'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def remote(script):
    runner = "import sys;sys.path.insert(0,"+repr(str(KEYS))+ ");from ssh_lib import load_server,ssh_bash_s;sys.exit(ssh_bash_s(load_server('usa'),sys.stdin.read()))"
    result = subprocess.run([sys.executable, '-c', runner], input=script, capture_output=True, text=True)
    if result.returncode:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError('Remote operation failed')
    lines = [line for line in result.stdout.splitlines() if line.startswith('{')]
    return json.loads(lines[-1]) if lines else {'output': result.stdout}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'activate'])
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--followup', action='append', default=[], help='Additional committed fixes to the logging files')
    args = parser.parse_args()
    reports = Path(args.report_dir).resolve()
    reports.mkdir(parents=True, exist_ok=True)
    if args.action == 'activate':
        manifest = json.loads((reports/'manifest.json').read_text())
        stage = '/tmp/'+manifest['release']
        receipt = remote('set -eu\nexec 9>/var/lock/ponychat-agent-deploy.lock\nflock -n 9\n'
            + f'/opt/ponychat/.venv/bin/python {stage}/remote.py activate {stage}\n')
        (reports/'deployment.json').write_text(json.dumps(receipt, indent=2)+'\n')
        print(json.dumps({'release': receipt['release'], 'backup': receipt['backup']}))
        return
    revision = git('rev-parse', 'HEAD').decode().strip()
    names = git('show', '--name-only', '--format=', LOG_COMMIT).decode().splitlines()
    backend = [n for n in names if n.startswith('Backend/') and '/tests/' not in n]
    assert not git('status', '--porcelain', '--', *backend, 'PonyChat-Website/Main/frontend'), 'Release source files must be committed'
    subprocess.run(['npm.cmd', 'run', 'build'], cwd=ROOT/'PonyChat-Website/Main/frontend', check=True,
                   stdout=subprocess.DEVNULL)
    manifest = {'release': 'ponychat-logs-'+time.strftime('%Y%m%d-%H%M%S')+'-'+revision[:8],
                'revision': revision, 'backend': {}, 'frontend': {}}
    with tempfile.TemporaryDirectory(prefix='ponychat-log-release-') as directory:
        archive = Path(directory)/'release.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            def add(name, content):
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                entry.mode = 0o644
                tar.addfile(entry, io.BytesIO(content))
            for name in backend:
                content = git('show', revision+':'+name)
                compile(content, name, 'exec')
                manifest['backend'][name] = hashlib.sha256(content).hexdigest()
                for index, commit in enumerate([LOG_COMMIT, *args.followup]):
                    patch = git('diff', commit+'^', commit, '--', name)
                    if patch:
                        add('patches/'+name.replace('/', '__')+f'.{index}.patch', patch)
            dist = ROOT/'PonyChat-Website/Main/frontend/dist'
            for path in [dist/'index.html', *sorted((dist/'assets').iterdir())]:
                if not path.is_file() or path.name != 'index.html' and not re.search(r'-[\w-]{8}\.(js|css|ttf|woff2?)$', path.name):
                    continue
                content = path.read_bytes()
                name = path.relative_to(dist).as_posix()
                manifest['frontend'][name] = hashlib.sha256(content).hexdigest()
                add('frontend/'+name, content)
            assert any('ConversationLogsSection' in n for n in manifest['frontend'])
            add('manifest.json', json.dumps(manifest).encode())
            add('remote.py', Path(__file__).with_name('agent_logging_release_remote.py').read_bytes())
        sys.path.insert(0, str(KEYS))
        from ssh_lib import load_server, scp_to
        remote_archive = '/tmp/'+manifest['release']+'.tar.gz'
        assert scp_to(load_server('usa'), archive, remote_archive) == 0
        stage = '/tmp/'+manifest['release']
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        script = f'''set -eu
python3 - <<'PY'
import hashlib,tarfile
from pathlib import Path
archive=Path({remote_archive!r});stage=Path({stage!r})
assert hashlib.sha256(archive.read_bytes()).hexdigest()=={checksum!r}
stage.mkdir(mode=0o700,exist_ok=False)
with tarfile.open(archive) as payload:
 assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in payload)
 payload.extractall(stage,filter='data')
PY
/opt/ponychat/.venv/bin/python {stage}/remote.py prepare {stage}
'''
        plan = remote(script)
        (reports/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
        (reports/'preflight.json').write_text(json.dumps(plan, indent=2)+'\n')
        print(json.dumps({'release': manifest['release'], 'changes': plan['changes']}))


if __name__ == '__main__':
    main()
