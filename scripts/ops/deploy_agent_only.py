"""Stage and activate a committed Agent-only backend without restoring retired engines."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BASE = "94b2a99"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate", help="Activate a previously staged release after real-model acceptance")
    parser.add_argument("--verify", help="Verify deployed hashes and post-deployment isolated acceptance")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT.parent / "ServerKeys"))
    from ssh_lib import load_server, scp_to, ssh_bash_s
    server = load_server("usa")
    if args.verify:
        release = args.verify
        assert release.startswith("agent-only-") and all(c.isalnum() or c == "-" for c in release)
        script = f'''set -eu
python3 - <<'PY'
import hashlib,json,subprocess,urllib.request
from pathlib import Path
root=Path('/opt/ponychat')
stage=Path('/var/tmp')/{release!r}
receipt=json.loads((stage/'deployment.json').read_text())
assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==digest for name,digest in receipt['hashes'].items())
assert not any((root/name).exists() for name in receipt['removed'])
assert subprocess.run(['systemctl','is-active','--quiet','ponychat-backend.service']).returncode==0
summary={{'release':{release!r},'revision':receipt['revision'],'files_verified':len(receipt['hashes']),
         'removed_verified':len(receipt['removed']),'backup':receipt['backup'],'modes':{{}}}}
for mode in ('normal','galgame','galgame_lock'):
 report=json.loads((stage/('post-'+mode+'.json')).read_text())
 assert report['passed'], mode
 summary['modes'][mode]={{k:report[k] for k in ('passed','status','elapsed_seconds','agent_memory_count','continuity_passed','state_passed','game_agent_calls','metering_passed','game_turns','first_pass_turns','whole_turn_retries','first_pass_passed') if k in report}}
 feedback=[]
 for event in report.get('runtime_observations',[]):
  if event.get('kind')!='harness_run': continue
  try: prompt=json.loads(event.get('prompt') or '')
  except (ValueError,TypeError): continue
  if isinstance(prompt,dict) and prompt.get('validation_feedback'): feedback.append(prompt['validation_feedback'])
 summary['modes'][mode]['validation_retries']=feedback
health=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health',timeout=5))
assert health['deploy_token']=={release!r}
summary['health']=health
(stage/'acceptance-summary.json').write_text(json.dumps(summary,indent=2))
# Remove the temporary credential copy; live .env and acceptance reports stay untouched.
(stage/'.env').unlink(missing_ok=True)
print(json.dumps(summary))
PY
'''
        assert ssh_bash_s(server, script) == 0
        with urllib.request.urlopen("https://www.ponychat.org/api/health", timeout=30) as response:
            health = json.load(response)
        assert health["deploy_token"] == release
        print(json.dumps({"public_health": health}))
        return
    if args.activate:
        release = args.activate
        assert release.startswith("agent-only-") and all(c.isalnum() or c == "-" for c in release)
        script = f'''set -eu
cd /opt/ponychat
.venv/bin/python - <<'PY'
import hashlib,json,shutil,subprocess,time,urllib.request
from pathlib import Path
root=Path('/opt/ponychat')
stage=Path('/var/tmp')/{release!r}
manifest=json.loads((stage/'manifest.json').read_text())
for mode in ('normal','galgame','galgame_lock'):
 assert json.loads((stage/(mode+'.json')).read_text())['passed'], mode
backup=Path('/var/backups/ponychat-agent-only')/{release!r}
backup.mkdir(parents=True,exist_ok=False)
backup.chmod(0o700)
for name in list(manifest['hashes'])+manifest['removed']+['Backend/.deploy_revision']:
 source=root/name
 assert source.resolve().is_relative_to(root/'Backend')
 if source.is_file():
  target=backup/name
  target.parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(source,target)
subprocess.run(['systemctl','stop','ponychat-backend.service'],check=True)
# Failure stays stopped for a forward fix; never restore Actor/staged generation.
for name,digest in manifest['hashes'].items():
 source=stage/name
 assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
 target=root/name
 target.parent.mkdir(parents=True,exist_ok=True)
 shutil.copy2(source,target)
for name in manifest['removed']:
 (root/name).unlink(missing_ok=True)
for folder in (root/'Backend').rglob('__pycache__'):
 if folder.resolve().is_relative_to(root/'Backend'):
  for cached in folder.glob('*.pyc'): cached.unlink()
for name,digest in manifest['hashes'].items():
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
assert not any((root/name).exists() for name in manifest['removed'])
(root/'Backend/.deploy_revision').write_text(json.dumps({{'deploy_token':{release!r},'revision':manifest['revision']}}))
subprocess.run(['systemctl','start','ponychat-backend.service'],check=True)
for attempt in range(45):
 try:
  health=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health',timeout=3))
  if health.get('deploy_token')=={release!r}: break
 except Exception: pass
 time.sleep(2)
else: raise RuntimeError('New process health token missing; forward fix required')
receipt={{**manifest,'release':{release!r},'backup':str(backup),'health':health,'removed_verified':True}}
(stage/'deployment.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps({{'release':{release!r},'files_verified':len(manifest['hashes']),'removed_verified':len(manifest['removed']),'health':health}}))
PY
'''
        assert ssh_bash_s(server, script) == 0
        with urllib.request.urlopen("https://www.ponychat.org/api/health", timeout=30) as response:
            health = json.load(response)
        assert health["deploy_token"] == release
        print(json.dumps({"public_health": health}))
        return
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    changes = subprocess.check_output(["git", "diff", "--name-status", "--no-renames", BASE, revision, "--", "Backend"], cwd=ROOT).decode().splitlines()
    files, removed = [], []
    for line in changes:
        status, name = line.split("\t")
        path = Path(name)
        if set(path.parts) & {"tests", "Agent-Test", "database", "data", "deploy"}:
            continue
        if path.suffix not in {".py", ".mjs", ".json", ".txt"}:
            continue
        (removed if status == "D" else files).append(name)
    release = "agent-only-" + time.strftime("%Y%m%d-%H%M%S") + "-" + revision[:8]
    hashes = {}
    with tempfile.TemporaryDirectory(prefix="agent-only-") as temp:
        archive = Path(temp) / "release.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name in files + ["scripts/ops/smoke_deployed_harness.py"]:
                content = subprocess.check_output(["git", "show", revision + ":" + name], cwd=ROOT)
                if name.endswith(".py"): compile(content, name, "exec")
                if name in files: hashes[name] = hashlib.sha256(content).hexdigest()
                info = tarfile.TarInfo(name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
            manifest = json.dumps({"revision": revision, "hashes": hashes, "removed": removed}).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest)
            tar.addfile(info, io.BytesIO(manifest))
        remote = "/tmp/" + release + ".tar.gz"
        assert scp_to(server, archive, remote) == 0
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        script = f'''set -eu
python3 - <<'PY'
import hashlib,json,shutil,tarfile
from pathlib import Path
root=Path('/opt/ponychat')
stage=Path('/var/tmp')/{release!r}
stage.mkdir(mode=0o700)
for path in (root/'Backend').rglob('*'):
 rel=path.relative_to(root)
 if set(rel.parts)&{{'database','data','backups','Agent-Test','tests','__pycache__'}}: continue
 if path.is_file() and (path.suffix in ('.py','.mjs') or 'conf' in rel.parts and path.suffix=='.json'):
  target=stage/rel
  target.parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(path,target)
shutil.copy2(root/'.env',stage/'.env')
(stage/'.env').chmod(0o600)
archive=Path({remote!r})
assert hashlib.sha256(archive.read_bytes()).hexdigest()=={digest!r}
with tarfile.open(archive) as tar:
 assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in tar.getmembers())
 tar.extractall(stage,filter='data')
manifest=json.loads((stage/'manifest.json').read_text())
for name in manifest['removed']:
 assert (stage/name).resolve().is_relative_to(stage/'Backend')
 (stage/name).unlink(missing_ok=True)
for name,digest in manifest['hashes'].items():
 assert hashlib.sha256((stage/name).read_bytes()).hexdigest()==digest
print(json.dumps({{'stage':str(stage),'revision':manifest['revision'],'changed':len(manifest['hashes']),'removed':len(manifest['removed'])}}))
archive.unlink()
PY
'''
        assert ssh_bash_s(server, script) == 0


if __name__ == "__main__":
    main()
