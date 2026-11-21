"""Stage a scoped candidate and run isolated real-model probes on Server-USA."""
import argparse
import base64
import hashlib
import io
import json
import re
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['stage', 'reliability', 'recovery', 'parity', 'relations', 'followup', 'style'])
    p.add_argument('--reports', required=True)
    p.add_argument('--live', action='store_true')
    p.add_argument('--case', help='Run one named relation or style fixture; retain its full input')
    args = p.parse_args()
    if args.case and (args.action not in ('relations', 'style') or not re.fullmatch(r'[a-z0-9_]{1,80}', args.case)):
        p.error('--case requires a safe relation or style fixture name')
    reports = Path(args.reports).resolve()
    reports.mkdir(parents=True, exist_ok=True)
    from compare_server_backend import load_server, _ssh_capture
    from ssh_lib import scp_to
    server = load_server('usa')

    def remote(code):
        encoded = base64.b64encode(code.encode()).decode()
        rc, out, err = _ssh_capture(server, 'python3 -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"')
        if rc:
            raise RuntimeError(out[-4000:] + '\n' + err[-4000:])
        return json.loads(out.strip().splitlines()[-1])

    if args.action == 'stage':
        files = subprocess.check_output(['git', 'diff', '--name-only', 'HEAD', '--', 'Backend'], cwd=ROOT).decode().splitlines()
        files += subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', 'Backend'], cwd=ROOT).decode().splitlines()
        files = sorted({p for p in files if '/tests/' not in p and p.endswith(('.py', '.mjs'))})
        stage = '/var/tmp/normal-reliability-' + time.strftime('%Y%m%d-%H%M%S')
        hashes = {}
        with tempfile.TemporaryDirectory(prefix='parity-') as tmp:
            archive = Path(tmp)/'candidate.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                for name in files:
                    content = (ROOT/name).read_bytes().replace(b'\r\n', b'\n')
                    compile(content, name, 'exec')
                    hashes[name] = hashlib.sha256(content).hexdigest()
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    tar.addfile(member, io.BytesIO(content))
            result = remote('from pathlib import Path\nimport json\n'+f'Path({stage!r}).mkdir(mode=0o700)\n'+"print(json.dumps({'created':True}))")
            bundle = Path(tmp)/'probes.tar.gz'
            probe_names = ['smoke_deployed_harness.py', 'verify_agent_parity.py', 'verify_normal_reliability.py', 'verify_agent_recovery.py', 'verify_relation_continuity.py', 'verify_roleplay_style.py']
            with tarfile.open(bundle, 'w:gz') as tar:
                tar.add(archive, arcname='candidate.tar.gz')
                for name in probe_names:
                    tar.add(ROOT/'scripts/ops'/name, arcname=name)
            for attempt in range(3):
                if scp_to(server, bundle, stage+'/probes.tar.gz') == 0:
                    break
                time.sleep(2 * (attempt+1))
            else:
                raise RuntimeError('Candidate upload failed after three attempts')
            remote('import tarfile,json\n'+f'with tarfile.open({stage+"/probes.tar.gz"!r}) as tar:\n'+
                f' assert tar.getnames()=={["candidate.tar.gz", *probe_names]!r} and all(m.isfile() for m in tar)\n'+
                f' tar.extractall({stage!r},filter="data")\n'+"print(json.dumps({'unpacked':True}))")
        info = {'stage': stage, 'hashes': hashes, 'files': files,
                'base': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT).decode().strip()}
        (reports/'candidate.json').write_text(json.dumps(info, indent=2), encoding='utf8')
        (reports/'manifest.json').write_text(json.dumps(files, indent=2), encoding='utf8')
        print(json.dumps({'stage': stage, 'files': len(files)}))
        return
    cfg = json.loads((reports/'candidate.json').read_text())
    stage = cfg['stage']
    name = ('post-' if args.live else 'pre-') + args.action
    if args.case: name += '-' + args.case
    script = {'parity': 'verify_agent_parity.py', 'reliability': 'verify_normal_reliability.py',
              'recovery': 'verify_agent_recovery.py', 'relations': 'verify_relation_continuity.py',
              'followup': 'verify_agent_parity.py', 'style': 'verify_roleplay_style.py'}[args.action]
    settings = {'PONYCHAT_SMOKE_TIMEOUT_SECONDS': '1800', 'PONYCHAT_SMOKE_USERNAME': 'System'}
    if args.action == 'followup': settings['PONYCHAT_PARITY_ONLY_FOLLOWUP'] = '1'
    if args.case:
        settings['PONYCHAT_STYLE_CASE' if args.action == 'style' else 'PONYCHAT_RELATION_CASE'] = args.case
    if not args.live: settings['PONYCHAT_COVERAGE_OVERLAY'] = stage+'/candidate.tar.gz'
    result = remote('import subprocess,os,json\nfrom pathlib import Path\n'+
        "pid=subprocess.check_output(['systemctl','show','ponychat-backend.service','-p','MainPID','--value'],text=True).strip()\n"+
        "assert pid.isdigit() and int(pid)>0, 'Production runtime must be active for configuration comparison'\n"+
        "runtime_keys=('PONYCHAT_HARNESS_POOL','PONYCHAT_HARNESS_CONCURRENCY','PONYCHAT_HARNESS_TMPDIR')\n"+
        "runtime_env={}\n"+
        "for item in Path('/proc/'+pid+'/environ').read_bytes().split(b'\\0'):\n"+
        " key,sep,value=item.partition(b'=')\n"+
        " if sep and key.decode() in runtime_keys: runtime_env[key.decode()]=value.decode()\n"+
        # The SSH login does not inherit the service's systemd environment.
        # Copy only these non-secret settings; synthetic DB/auth remain isolated.
        f'env={{k:v for k,v in os.environ.items() if k not in runtime_keys}}\nenv.update(runtime_env)\nenv.update({settings!r})\n'+
        f"r=subprocess.run(['/opt/ponychat/.venv/bin/python',{stage+'/'+script!r},{stage+'/'+name+'.json'!r},'--source','/opt/ponychat'],env=env,capture_output=True,text=True,timeout=1860)\n"+
        f"p=Path({stage+'/'+name+'.json'!r})\n"+
        "print(json.dumps({'exit_code':r.returncode,'stdout':r.stdout[-2000:],'stderr':r.stderr[-4000:],'runtime_settings':{k:runtime_env.get(k) for k in runtime_keys},'report':json.loads(p.read_text()) if p.exists() else None}))")
    (reports/(name+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    report = result.get('report') or {}
    print(json.dumps({'exit_code':result['exit_code'], **{k:report[k] for k in ('passed','elapsed_seconds','game_turns','first_pass_turns','whole_turn_retries') if k in report},
                      'cases':[{k:c[k] for k in ('label','passed','errors','task') if k in c} for c in report.get('cases', [])],
                      'stderr':result['stderr'] if not report else ''}, ensure_ascii=False))
    if result['exit_code']: raise SystemExit(1)


if __name__ == '__main__':
    main()
