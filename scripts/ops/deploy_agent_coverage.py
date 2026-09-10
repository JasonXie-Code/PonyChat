"""Focused, checksum-verified Agent fix release with code and SQLite backups."""
import argparse
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
import urllib.request

ROOT=Path(__file__).resolve().parents[2]


def validate_paths(names, *, allow_empty=False, allow_ops=False):
    if not isinstance(names, list) or (not names and not allow_empty):
        raise ValueError('Manifest must contain explicit Backend file paths')
    if len(set(names)) != len(names):
        raise ValueError('Duplicate manifest paths')
    for name in names:
        prefix = r'(?:Backend|scripts/ops)' if allow_ops else 'Backend'
        if not isinstance(name, str) or not re.fullmatch(prefix + r'/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:py|mjs)', name):
            raise ValueError('Invalid Backend source path: ' + repr(name))
    return names


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',help='JSON array of committed Backend source paths')
    parser.add_argument('--report',required=True)
    parser.add_argument('--android-receipt', help='Published, signed APK receipt to activate with this backend')
    parser.add_argument('--expected-deploy-token', help='Refuse to overwrite a different live release')
    parser.add_argument('--delete-manifest', help='JSON array of obsolete committed Backend files to remove')
    parser.add_argument('--delete-base-revision', default='HEAD^', help='Revision containing the old bytes; mismatching live files are not deleted')
    args=parser.parse_args()
    android = json.loads(Path(args.android_receipt).read_text(encoding='utf8')) if args.android_receipt else None
    app_values = {}
    if android:
        assert android['published'] and android['sha256'] == android['public_sha256']
        version, code = android['version_name'], android['version_code']
        assert re.fullmatch(r'\d+\.\d+\.\d+', version) and type(code) is int and code > 0
        assert re.fullmatch(r'[0-9a-f]{64}', android['sha256'])
        app_values = {'PONYCHAT_APP_VERSION_NAME': version, 'PONYCHAT_APP_VERSION_CODE': str(code),
            'PONYCHAT_APP_APK_PATH': f'/opt/ponychat/PonyChat-Website/Main/deploy/releases/PonyChat-v{version}-{code}-release.apk'}
    names=validate_paths(json.loads(Path(args.manifest).read_text(encoding='utf-8')))
    deleted=validate_paths(json.loads(Path(args.delete_manifest).read_text(encoding='utf-8')), allow_empty=True, allow_ops=True) if args.delete_manifest else []
    assert not set(names).intersection(deleted)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
    deleted_hashes={}
    for name in deleted:
        assert subprocess.run(['git','cat-file','-e',revision+':'+name],cwd=ROOT,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode != 0, 'Deletion still exists in committed release'
        before=subprocess.check_output(['git','show',args.delete_base_revision+':'+name],cwd=ROOT)
        deleted_hashes[name]=hashlib.sha256(before.replace(b'\r\n',b'\n')).hexdigest()
    release='agent-coverage-'+time.strftime('%Y%m%d-%H%M%S')+'-'+revision[:8]
    server_keys = next((parent / 'ServerKeys' for parent in ROOT.parents
                        if (parent / 'ServerKeys' / 'ssh_lib.py').is_file()), None)
    if server_keys is None:
        raise RuntimeError('Could not locate the adjacent ServerKeys checkout')
    sys.path.insert(0,str(server_keys))
    from ssh_lib import load_server,scp_to,ssh_bash_s
    server=load_server('usa')
    hashes={}
    with tempfile.TemporaryDirectory(prefix='ponychat-agent-release-') as directory:
        archive=Path(directory)/'release.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for name in names:
                content=subprocess.check_output(['git','show',revision+':'+name],cwd=ROOT)
                if name.endswith('.py'):
                    compile(content,name,'exec')
                hashes[name]=hashlib.sha256(content).hexdigest()
                member=tarfile.TarInfo(name);member.size=len(content)
                tar.addfile(member,io.BytesIO(content))
        remote='/tmp/'+release+'.tar.gz'
        assert scp_to(server,archive,remote)==0
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        script=f'''set -eu
exec 9>/var/lock/ponychat-agent-deploy.lock
flock -n 9
cd /opt/ponychat
.venv/bin/python - <<'PY'
import hashlib,json,shutil,sqlite3,subprocess,tarfile,time,urllib.request
from pathlib import Path
root=Path('/opt/ponychat'); archive=Path({remote!r}); names={names!r}; expected={hashes!r}
deleted={deleted!r}; deleted_hashes={deleted_hashes!r}
assert hashlib.sha256(archive.read_bytes()).hexdigest()=={digest!r}
if {args.expected_deploy_token!r}:
 assert json.loads((root/'Backend/.deploy_revision').read_text())['deploy_token']=={args.expected_deploy_token!r}, 'Live release changed'
backup=Path('/var/backups/ponychat-agent')/{release!r}
backup.mkdir(parents=True,exist_ok=False);backup.chmod(0o700)
assert subprocess.run(['systemctl','is-active','--quiet','ponychat-backend.service']).returncode==0
old={{}}
app_values={app_values!r}
if app_values:
 assert hashlib.sha256(Path(app_values['PONYCHAT_APP_APK_PATH']).read_bytes()).hexdigest()=={android['sha256'] if android else ''!r}
for name in names+deleted+['Backend/.deploy_revision']+(['.env'] if app_values else []):
 assert (root/name).resolve().is_relative_to(root.resolve()), 'Path escaped deployment root'
 assert not (root/name).is_symlink(), 'Refuse symlink target'
 p=root/name;old[name]=p.exists()
 if name in deleted and p.exists():
  assert hashlib.sha256(p.read_bytes().replace(b'\\r\\n',b'\\n')).hexdigest()==deleted_hashes[name], 'Obsolete live file changed: '+name
 if p.exists():
  target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
(backup/'manifest.json').write_text(json.dumps(old))
try:
 subprocess.run(['systemctl','stop','ponychat-backend.service'],check=True)
 db=root/'Backend/database/ponychat.db'
 assert db.is_file()
 with sqlite3.connect(db) as src, sqlite3.connect(backup/'ponychat.db') as dest:
  src.backup(dest)
 for name in deleted:
  (root/name).unlink(missing_ok=True)
 with tarfile.open(archive) as tar:
  assert tar.getnames()==names and all(m.isfile() for m in tar.getmembers())
  tar.extractall(root,filter='data')
 for name in names:
  content=(root/name).read_bytes();assert hashlib.sha256(content).hexdigest()==expected[name]
  if name.endswith('.py'):compile(content,name,'exec')
 (root/'Backend/.deploy_revision').write_text(json.dumps({{'deploy_token':{release!r},'revision':{revision!r}}}))
 if app_values:
  env=root/'.env'
  lines=[line for line in env.read_text().splitlines() if line.partition('=')[0].strip() not in app_values]
  env.write_text('\\n'.join(lines+[key+'='+value for key,value in app_values.items()])+'\\n')
 subprocess.run(['systemctl','start','ponychat-backend.service'],check=True)
 for i in range(45):
  try:
   health=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health',timeout=3))
   if health.get('deploy_token')=={release!r}:break
  except Exception:pass
  time.sleep(2)
 else:raise RuntimeError('New backend health check failed')
 with sqlite3.connect(db) as conn:
  assert conn.execute('PRAGMA quick_check').fetchone()[0]=='ok'
  for table in ('agent_memory_participants','agent_memory_attempts'):
   assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
 assert all(not (root/name).exists() for name in deleted)
 receipt={{'release':{release!r},'revision':{revision!r},'backup':str(backup),'hashes':expected,'deleted_files':deleted,'health':health}}
 (backup/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
except BaseException:
 subprocess.run(['systemctl','stop','ponychat-backend.service'],check=False)
 for name,exists in old.items():
  if exists:shutil.copy2(backup/name,root/name)
  else:(root/name).unlink(missing_ok=True)
 # Schema changes are additive. Preserve any newly received user messages;
 # retain the pre-deploy DB backup for explicit recovery instead of overwriting.
 subprocess.run(['systemctl','start','ponychat-backend.service'],check=True)
 print('ROLLED_BACK_CODE '+str(backup));raise
PY
'''
        assert ssh_bash_s(server,script)==0
    health=json.load(urllib.request.urlopen('https://www.ponychat.org/api/health',timeout=30))
    assert health.get('deploy_token')==release
    receipt={'target':'Server-USA','revision':revision,'release':release,'hashes':hashes,'deleted_files':deleted,
             'backup':'/var/backups/ponychat-agent/'+release,'public_health':health}
    if android:
        version=json.load(urllib.request.urlopen('https://www.ponychat.org/api/app/version',timeout=30))
        assert version['version_name']==android['version_name'] and version['version_code']==android['version_code']
        receipt['public_app_version']=version
    Path(args.report).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':
    main()
