"""Stage a scoped candidate and run isolated real-model probes on Server-USA."""
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

ROOT = Path(__file__).resolve().parents[2]
FILES = ['Backend/chat_modules/' + name + '.py' for name in (
    'autonomous_business', 'autonomous_followup', 'autonomous_normal', 'autonomous_prompt_skills',
    'autonomous_service', 'autonomous_transaction', 'autonomous_shortcuts', 'autonomous_speech')] + [
    'Backend/galgame/harness.py', 'Backend/galgame/handler.py', 'Backend/galgame/lock_state.py',
    'Backend/galgame/output_contract.py', 'Backend/galgame/memory.py',
    'Backend/scheduled_followup_impl/followup_generation.py']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['stage', 'normal', 'parity', 'galgame', 'galgame_lock', 'lock_boundaries', 'coverage'])
    p.add_argument('--reports', required=True)
    p.add_argument('--live', action='store_true')
    args = p.parse_args()
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
        stage = '/var/tmp/agent-parity-' + time.strftime('%Y%m%d-%H%M%S')
        hashes = {}
        with tempfile.TemporaryDirectory(prefix='parity-') as tmp:
            archive = Path(tmp)/'candidate.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                for name in FILES:
                    content = (ROOT/name).read_bytes().replace(b'\r\n', b'\n')
                    compile(content, name, 'exec')
                    hashes[name] = hashlib.sha256(content).hexdigest()
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    tar.addfile(member, io.BytesIO(content))
            result = remote('from pathlib import Path\nimport json\n'+f'Path({stage!r}).mkdir(mode=0o700)\n'+"print(json.dumps({'created':True}))")
            bundle = Path(tmp)/'probes.tar.gz'
            probe_names = ['smoke_deployed_harness.py', 'verify_agent_parity.py', 'verify_agent_coverage.py']
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
        info = {'stage': stage, 'hashes': hashes, 'files': FILES,
                'base': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT).decode().strip()}
        (reports/'candidate.json').write_text(json.dumps(info, indent=2), encoding='utf8')
        (reports/'manifest.json').write_text(json.dumps(FILES, indent=2), encoding='utf8')
        print(json.dumps({'stage': stage, 'files': len(FILES)}))
        return
    cfg = json.loads((reports/'candidate.json').read_text())
    stage = cfg['stage']
    name = ('post-' if args.live else 'pre-') + args.action
    script = 'verify_agent_parity.py' if args.action == 'parity' else 'verify_agent_coverage.py' if args.action == 'coverage' else 'smoke_deployed_harness.py'
    settings = {'PONYCHAT_SMOKE_TIMEOUT_SECONDS': '1200', 'PONYCHAT_SMOKE_USERNAME': 'System'}
    if not args.live: settings['PONYCHAT_COVERAGE_OVERLAY'] = stage+'/candidate.tar.gz'
    if args.action in ('galgame', 'galgame_lock', 'lock_boundaries'):
        settings.update(PONYCHAT_SMOKE_GAME_MODE='galgame' if args.action == 'galgame' else 'galgame_lock',
                        PONYCHAT_SMOKE_GAME_ROUNDS='4')
    if args.action == 'lock_boundaries': settings['PONYCHAT_SMOKE_LOCK_BOUNDARIES'] = '1'
    result = remote('import subprocess,os,json\nfrom pathlib import Path\n'+
        f'env=dict(os.environ,**{settings!r})\n'+
        f"r=subprocess.run(['/opt/ponychat/.venv/bin/python',{stage+'/'+script!r},{stage+'/'+name+'.json'!r},'--source','/opt/ponychat'],env=env,capture_output=True,text=True,timeout=1260)\n"+
        f"p=Path({stage+'/'+name+'.json'!r})\n"+
        "print(json.dumps({'exit_code':r.returncode,'stdout':r.stdout[-2000:],'stderr':r.stderr[-4000:],'report':json.loads(p.read_text()) if p.exists() else None}))")
    (reports/(name+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    report = result.get('report') or {}
    print(json.dumps({'exit_code':result['exit_code'], **{k:report[k] for k in ('passed','elapsed_seconds','game_turns','first_pass_turns','whole_turn_retries') if k in report},
                      'cases':[{k:c[k] for k in ('label','passed','errors','task') if k in c} for c in report.get('cases', [])],
                      'stderr':result['stderr'] if not report else ''}, ensure_ascii=False))
    if result['exit_code']: raise SystemExit(1)


if __name__ == '__main__':
    main()
