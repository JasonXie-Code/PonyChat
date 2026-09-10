"""Apply only this commit's search/context patch on Server-USA, preserving other changes."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
FILES = ['Backend/chat_modules/autonomous_normal.py', 'Backend/chat_modules/autonomous_service.py',
         'Backend/chat_modules/autonomous_web_search.py', 'Backend/agent_memory/calendar_context.py']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='HEAD')
    args = parser.parse_args()
    revision = subprocess.check_output(['git', 'rev-parse', args.revision], cwd=ROOT).decode().strip()
    patch = subprocess.check_output(['git', 'diff', '--binary', revision+'^', revision, '--', *FILES], cwd=ROOT)
    assert patch
    release = 'search-context-' + time.strftime('%Y%m%d-%H%M%S') + '-' + revision[:8]
    sys.path.insert(0, str(ROOT.parent/'ServerKeys'))
    from ssh_lib import load_server, scp_to, ssh_bash_s
    server = load_server('usa')
    with tempfile.TemporaryDirectory(prefix='ponychat-search-deploy-') as directory:
        source = Path(directory)/'change.patch'
        source.write_bytes(patch)
        remote = '/tmp/'+release+'.patch'
        assert scp_to(server, source, remote) == 0
        script = "set -eu\ncd /opt/ponychat\n.venv/bin/python - <<'PY'\n" + f'''
import hashlib,json,shutil,subprocess,time,urllib.request
from pathlib import Path
root=Path('/opt/ponychat')
patch=Path({remote!r})
assert hashlib.sha256(patch.read_bytes()).hexdigest()=={hashlib.sha256(patch).hexdigest()!r}
subprocess.run(['git','apply','--check',str(patch)],check=True,cwd=root)
subprocess.run(['systemctl','is-active','--quiet','ponychat-searxng.service'],check=True)
subprocess.run(['systemctl','is-active','--quiet','ponychat-backend.service'],check=True)
backup=Path('/var/backups/ponychat-search-context')/{release!r}
backup.mkdir(parents=True,exist_ok=False)
backup.chmod(0o700)
old={{}}
for name in {FILES!r}+['Backend/.deploy_revision']:
 p=root/name
 old[name]=p.exists()
 if p.exists():
  target=backup/name
  target.parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(p,target)
(backup/'manifest.json').write_text(json.dumps(old))
try:
 subprocess.run(['systemctl','stop','ponychat-backend.service'],check=True)
 subprocess.run(['git','apply',str(patch)],check=True,cwd=root)
 hashes={{}}
 for name in {FILES!r}:
  content=(root/name).read_bytes()
  compile(content,name,'exec')
  hashes[name]=hashlib.sha256(content).hexdigest()
 (root/'Backend/.deploy_revision').write_text(json.dumps({{'deploy_token':{release!r}}}))
 subprocess.run(['systemctl','start','ponychat-backend.service'],check=True)
 for attempt in range(40):
  try:
   health=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health',timeout=3))
   if health.get('deploy_token')=={release!r}: break
  except Exception: pass
  time.sleep(2)
 else: raise RuntimeError('New process health token missing')
 receipt={{'target':'Server-USA','revision':{revision!r},'release':{release!r},'backup':str(backup),'health':health,'hashes':hashes}}
 (backup/'receipt.json').write_text(json.dumps(receipt,indent=2))
 print(json.dumps(receipt))
except BaseException:
 subprocess.run(['systemctl','stop','ponychat-backend.service'],check=False)
 for name,existed in old.items():
  if existed: shutil.copy2(backup/name,root/name)
  else: (root/name).unlink(missing_ok=True)
 subprocess.run(['systemctl','start','ponychat-backend.service'],check=True)
 print('ROLLED_BACK '+str(backup))
 raise
''' + '\nPY\n'
        assert ssh_bash_s(server, script) == 0
    health = json.load(urllib.request.urlopen('https://www.ponychat.org/api/health', timeout=30))
    assert health.get('deploy_token') == release
    print(json.dumps({'public_health': health, 'target': 'Server-USA'}))


if __name__ == '__main__':
    main()
