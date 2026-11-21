"""Stage the explicit normal-retry manifest and run its isolated acceptance probe."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_server_backend import _ssh_capture, load_server
from ssh_lib import scp_to

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / 'docs/testing/normal-auto-retry-20260909'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    server = load_server('usa')
    names = json.loads((REPORTS / 'manifest.json').read_text())
    stage = '/var/tmp/normal-retry-' + time.strftime('%Y%m%d-%H%M%S')

    def remote(code):
        encoded = base64.b64encode(code.encode()).decode()
        rc, out, err = _ssh_capture(server,
            'python3 -c "import base64;exec(base64.b64decode(\'' + encoded + '\'))"')
        if rc:
            raise RuntimeError(out[-2000:] + err[-2000:])
        return json.loads(out.strip().splitlines()[-1])

    with tempfile.TemporaryDirectory(prefix='normal-retry-candidate-') as directory:
        bundle, overlay = Path(directory) / 'bundle.tar.gz', io.BytesIO()
        hashes = {}
        with tarfile.open(fileobj=overlay, mode='w:gz') as tar:
            for name in names:
                content = (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
                compile(content, name, 'exec')
                hashes[name] = hashlib.sha256(content).hexdigest()
                member = tarfile.TarInfo(name)
                member.size = len(content)
                tar.addfile(member, io.BytesIO(content))
        with tarfile.open(bundle, 'w:gz') as tar:
            content = overlay.getvalue()
            member = tarfile.TarInfo('candidate.tar.gz')
            member.size = len(content)
            tar.addfile(member, io.BytesIO(content))
            for name in ('smoke_deployed_harness.py', 'verify_normal_automatic_retry.py'):
                tar.add(ROOT / 'scripts/ops' / name, arcname=name)
        remote(f'from pathlib import Path\nimport json\nPath({stage!r}).mkdir(mode=0o700)\nprint(json.dumps({{"created":True}}))')
        assert scp_to(server, bundle, stage + '/bundle.tar.gz') == 0
        result = remote(f'''import tarfile,json,subprocess,os
from pathlib import Path
stage=Path({stage!r})
with tarfile.open(stage/'bundle.tar.gz') as tar:
 assert tar.getnames()==['candidate.tar.gz','smoke_deployed_harness.py','verify_normal_automatic_retry.py']
 assert all(m.isfile() for m in tar)
 tar.extractall(stage,filter='data')
env=dict(os.environ,PONYCHAT_SMOKE_TIMEOUT_SECONDS='620')
if not {args.live!r}:env['PONYCHAT_COVERAGE_OVERLAY']=str(stage/'candidate.tar.gz')
r=subprocess.run(['/opt/ponychat/.venv/bin/python',str(stage/'verify_normal_automatic_retry.py'),str(stage/'report.json'),'--source','/opt/ponychat'],env=env,capture_output=True,text=True,timeout=660)
p=stage/'report.json'
print(json.dumps({{'exit_code':r.returncode,'report':json.loads(p.read_text()) if p.exists() else None,'stderr':r.stderr[-2500:]}}))
''')
    result.update(stage=stage, candidate_hashes=hashes, live=args.live)
    (REPORTS / ('postdeploy.json' if args.live else 'candidate.json')).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'exit_code': result['exit_code'], 'stage': stage,
        'cases': [{k: c[k] for k in ('label','passed','elapsed_seconds','error_type') if k in c}
                  for c in (result['report'] or {}).get('cases', [])],
        'stderr': result['stderr']}, ensure_ascii=False))
    return result['exit_code']


if __name__ == '__main__':
    sys.exit(main())
