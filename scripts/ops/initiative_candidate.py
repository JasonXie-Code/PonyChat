"""Stage bounded normal-prompt overlays and run isolated real-route comparisons."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import time

from compare_server_backend import load_server, _ssh_capture
from ssh_lib import scp_to


ROOT = Path(__file__).resolve().parents[2]
FILES = ['Backend/chat_modules/' + n + '.py' for n in (
    'autonomous_direct', 'autonomous_prompt_rules', 'autonomous_prompt_skills',
    'autonomous_behavior_policy', 'autonomous_normal', 'autonomous_reply', 'autonomous_service')]
PROBES = ['smoke_deployed_harness.py', 'verify_roleplay_style.py', 'verify_normal_initiative.py']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'probe'])
    parser.add_argument('--reports', required=True)
    parser.add_argument('--name', default='candidate')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--group', choices=['all', 'screenshots', 'boundaries', 'relationships', 'species'], default='all')
    args = parser.parse_args()
    assert re.fullmatch(r'[a-z0-9_-]+', args.name)
    reports = Path(args.reports).resolve()
    reports.mkdir(parents=True, exist_ok=True)
    server = load_server('usa')

    def remote(source):
        encoded = base64.b64encode(source.encode()).decode()
        rc, out, err = _ssh_capture(server, "python3 -c \"import base64;exec(base64.b64decode('" + encoded + "'))\"")
        if rc:
            raise RuntimeError('Remote probe driver failed: ' + out[-1000:] + err[-1000:])
        return json.loads(out.strip().splitlines()[-1])

    info_path = reports / (args.name + '-stage.json')
    if args.action == 'stage':
        stage = '/var/tmp/normal-initiative-' + time.strftime('%Y%m%d-%H%M%S') + '-' + args.name
        profile_path = reports / 'official-profile.json'
        if not profile_path.exists():
            profile = remote("import sqlite3,json\n" +
                "with sqlite3.connect('file:/opt/ponychat/Backend/database/ponychat.db?mode=ro',uri=True) as c:\n" +
                " rows=c.execute(\"SELECT id,data,prompt FROM characters WHERE COALESCE(is_official_source,0)=1 AND name=?\",('碧琪',)).fetchall()\n" +
                " assert len(rows)==1, 'Official Pinkie source must be unique'\n" +
                " ident,data,prompt=rows[0];profile=json.loads(data);profile['prompt']=prompt or '';profile['id']=ident\n" +
                "print(json.dumps(profile,ensure_ascii=False))")
            profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
        names = [n for n in FILES if (ROOT / n).exists()]
        hashes = {}
        with tempfile.TemporaryDirectory(prefix='initiative-probe-') as folder:
            folder = Path(folder)
            with tarfile.open(folder / 'candidate.tar.gz', 'w:gz') as tar:
                for name in names:
                    content = (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
                    compile(content, name, 'exec')
                    hashes[name] = hashlib.sha256(content).hexdigest()
                    item = tarfile.TarInfo(name)
                    item.size = len(content)
                    tar.addfile(item, io.BytesIO(content))
            with tarfile.open(folder / 'bundle.tar.gz', 'w:gz') as tar:
                tar.add(folder / 'candidate.tar.gz', arcname='candidate.tar.gz')
                for name in PROBES:
                    tar.add(ROOT / 'scripts/ops' / name, arcname=name)
                tar.add(profile_path, arcname='official-profile.json')
            remote('from pathlib import Path\nimport json\n' + f'Path({stage!r}).mkdir(mode=0o700)\n' +
                   "print(json.dumps({'created':True}))")
            assert scp_to(server, folder / 'bundle.tar.gz', stage + '/bundle.tar.gz') == 0
            info = remote('import tarfile,json,hashlib\nfrom pathlib import Path\n' +
                f'with tarfile.open({stage + "/bundle.tar.gz"!r}) as t:\n' +
                f' assert t.getnames()=={["candidate.tar.gz", *PROBES, "official-profile.json"]!r} and all(m.isfile() for m in t)\n' +
                f' t.extractall({stage!r},filter="data")\n' +
                "root=Path('/opt/ponychat')\n" +
                f"hashes={{n:hashlib.sha256((root/n).read_bytes()).hexdigest() if (root/n).exists() else None for n in {FILES!r}}}\n" +
                "print(json.dumps({'base_hashes':hashes,'deployment':json.loads((root/'Backend/.deploy_revision').read_text())}))")
        info.update(stage=stage, hashes=hashes, files=names,
                    revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip())
        info_path.write_text(json.dumps(info, indent=2), encoding='utf-8')
        (reports / 'manifest.json').write_text(json.dumps(names, indent=2), encoding='utf-8')
        print(json.dumps(info))
        return

    info = json.loads(info_path.read_text())
    stage = info['stage']
    settings = {'PONYCHAT_SMOKE_TIMEOUT_SECONDS': '1800', 'PONYCHAT_SMOKE_USERNAME': 'System',
                'PONYCHAT_INITIATIVE_GROUP': args.group,
                'PONYCHAT_INITIATIVE_PROFILE': stage + '/official-profile.json'}
    if not args.live:
        settings['PONYCHAT_COVERAGE_OVERLAY'] = stage + '/candidate.tar.gz'
    filename = args.name + ('-live' if args.live else '-overlay') + '-' + args.group + '.json'
    result = remote('import json,os,subprocess\nfrom pathlib import Path\n' +
        "pid=subprocess.check_output(['systemctl','show','ponychat-backend.service','-p','MainPID','--value'],text=True).strip()\n" +
        "runtime=dict(x.split('=',1) for x in Path('/proc/'+pid+'/environ').read_text().split('\\x00') if '=' in x)\n" +
        "keys=['PONYCHAT_HARNESS_POOL','PONYCHAT_AGENT_CAPACITY','PONYCHAT_HARNESS_POOL_SIZE']\n" +
        f"env={{**os.environ,**{{k:runtime[k] for k in keys if k in runtime}},**{settings!r}}}\n" +
        f"r=subprocess.run(['/opt/ponychat/.venv/bin/python',{stage+'/verify_normal_initiative.py'!r},{stage+'/'+filename!r},'--source','/opt/ponychat'],env=env,capture_output=True,text=True,timeout=1860)\n" +
        f"p=Path({stage+'/'+filename!r})\n" +
        "print(json.dumps({'exit_code':r.returncode,'stdout':r.stdout[-1000:],'stderr':r.stderr[-3000:],'report':json.loads(p.read_text()) if p.exists() else None}))")
    (reports / filename).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    report = result.get('report') or {}
    print(json.dumps({'exit_code': result['exit_code'], 'passed': report.get('passed'),
                      'cases': [{k: c.get(k) for k in ('label', 'passed', 'error_type')} for c in report.get('cases', [])],
                      'stderr': result['stderr'] if not report else ''}, ensure_ascii=False))
    raise SystemExit(bool(result['exit_code']))


if __name__ == '__main__':
    main()
