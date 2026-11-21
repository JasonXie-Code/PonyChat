"""Prepare or activate only the normal-chat transport fixes on Server-USA."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time

FILES = ['Backend/chat_modules/' + name + '.py' for name in (
    'autonomous_reply', 'autonomous_direct', 'autonomous_prompt_skills', 'autonomous_wire_format')]
TESTS = ['test_autonomous_wire_format', 'test_autonomous_reply', 'test_autonomous_prompt_skills',
         'test_autonomous_normal', 'test_autonomous_delivery']

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'activate'])
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--base', default='HEAD')
    args = parser.parse_args()
    reports = Path(args.report_dir).resolve()
    reports.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT.parent / 'ServerKeys'))
    from ssh_lib import load_server, scp_to
    from compare_server_backend import _ssh_capture
    server = load_server('usa')

    def remote(source):
        encoded = base64.b64encode(source.encode()).decode()
        rc, out, err = _ssh_capture(server, 'python3 -c "import base64;exec(base64.b64decode(\'' + encoded + '\'))"')
        print(out, flush=True)
        if rc:
            raise RuntimeError(err)
        return json.loads(out.strip().splitlines()[-1])

    if args.action == 'prepare':
        release = 'normal-wire-' + time.strftime('%Y%m%d-%H%M%S')
        stage = '/tmp/' + release
        patch = subprocess.check_output(['git', 'diff', args.base, '--', *FILES[:-1]], cwd=ROOT)
        assert patch
        with tempfile.TemporaryDirectory(prefix='normal-wire-') as folder:
            archive = Path(folder) / 'payload.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                def add(name, content):
                    entry = tarfile.TarInfo(name)
                    entry.size = len(content)
                    entry.mode = 0o600
                    tar.addfile(entry, io.BytesIO(content))
                add('changes.patch', patch)
                add(FILES[-1], (ROOT / FILES[-1]).read_bytes())
                for test in TESTS:
                    name = 'Backend/tests/' + test + '.py'
                    add(name, (ROOT / name).read_bytes())
                for name in ('normal_wire_release_remote.py', 'smoke_deployed_harness.py'):
                    add(name, Path(__file__).with_name(name).read_bytes())
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            remote_archive = stage + '.tar.gz'
            assert scp_to(server, archive, remote_archive) == 0
            remote('import hashlib,tarfile,json\nfrom pathlib import Path\n'
                   f'p=Path({remote_archive!r});s=Path({stage!r})\n'
                   f'assert hashlib.sha256(p.read_bytes()).hexdigest()=={digest!r}\n'
                   's.mkdir(mode=0o700,exist_ok=False)\nwith tarfile.open(p) as t:\n'
                   " assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in t)\n"
                   " t.extractall(s,filter='data')\nprint(json.dumps({'staged':str(s)}))")
        (reports / 'stage.json').write_text(json.dumps({'stage': stage, 'base': args.base}))
    else:
        stage = json.loads((reports / 'stage.json').read_text())['stage']
    result = remote('import subprocess\nsubprocess.run(' + repr([
        '/opt/ponychat/.venv/bin/python', stage + '/normal_wire_release_remote.py', args.action, stage]) + ',check=True)')
    (reports / (args.action + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
