"""Complete the explicitly authorized, verified 2026-09-09 Server-USA retirement."""
from __future__ import annotations

import json

from migration_transport import STATE, ssh_run


def main():
    if (STATE / "server-retirement.json").exists():
        print("Server-USA retirement already completed; no action taken.", flush=True)
        return
    for name in ("final-data-manifest-verification", "source-complete-verification",
                 "test-runtime-and-logs-verification", "production-public-acceptance"):
        assert json.loads((STATE / (name + ".json")).read_text())["passed"], name
    source_db = json.loads((STATE / "final-database-receipt.json").read_text())
    assert source_db["integrity"] == "ok" and source_db["all_table_counts_match"]
    protected = json.loads((STATE / "protected-server-before.json").read_text())
    temporary = json.loads((STATE / "retirement-source-sizes.json").read_text())["temp"]
    arguments = {"database_sha256": source_db["sha256"], "protected": protected,
                 "temporary": list(temporary)}
    script = "python3 - <<'PY'\n"
    script += "import pathlib,os,json,hashlib,subprocess,time\n"
    script += "args=" + repr(arguments) + "\n"
    script += r'''
units=['ponychat-backend','ponychat-cosyvoice','ponychat-searxng']
for unit in units:
 assert subprocess.run(['systemctl','is-active','--quiet',unit]).returncode!=0, unit+' still active'
h=hashlib.sha256()
with open('/opt/ponychat/Backend/database/ponychat.db','rb') as f:
 while data:=f.read(1048576):h.update(data)
assert h.hexdigest()==args['database_sha256'], 'Stopped database changed since verification'
protected=args['protected']
for value,expected in protected['protected_files'].items():
 p=pathlib.Path(value);st=p.stat()
 assert [st.st_size,st.st_mtime_ns]==expected, 'Protected file changed: '+value
for name,expected in protected['music'].items():
 assert subprocess.check_output(['systemctl','show',name,'-p','ActiveState','-p','MainPID'],text=True)==expected
# Both tunnels now reach the verified Windows process.
health=json.loads(subprocess.check_output(['curl','-fsS','http://127.0.0.1:5000/api/health']))
assert health['deploy_token']=='local-20260909-cn-ip-5.6.36'
assert json.loads(subprocess.check_output(['curl','-fsS','http://39.101.74.217:80/api/app/version']))['version_code']==376

for unit in units:subprocess.run(['systemctl','disable',unit],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)

report={'started_at':time.time(),'removed_files':0,'removed_bytes':0,'roots':[],'apks':0}
def keep(p):
 return p.name=='backups' or '.bak' in p.name or '.before-' in p.name or str(p) in protected['protected_roots']

def remove_tree(root, *, preserve_website=False, preserve_static=False):
 root=pathlib.Path(root)
 assert root.is_absolute() and '..' not in root.parts
 assert not root.is_symlink(), 'Refusing a symlink as retirement root'
 if not root.exists():return
 assert root.resolve()==root
 def visit(p):
  assert p.is_relative_to(root)
  if keep(p):return
  if preserve_website and p==root/'PonyChat-Website':return
  if preserve_static and p==root/'static':return
  if p.is_symlink():
   p.unlink();report['removed_files']+=1
  elif p.is_dir():
   for child in list(p.iterdir()):visit(child)
   if not any(p.iterdir()):p.rmdir()
  elif p.is_file():
   size=p.stat().st_size;p.unlink();report['removed_files']+=1;report['removed_bytes']+=size
  else:raise RuntimeError('Unexpected filesystem type: '+str(p))
 visit(root);report['roots'].append(str(root))

remove_tree('/opt/ponychat',preserve_website=True)
remove_tree('/opt/ponychat-cosyvoice',preserve_static=True)
remove_tree('/opt/ponychat-searxng')
for value in args['temporary']:
 p=pathlib.Path(value)
 assert p.parent==pathlib.Path('/tmp') and p.name.startswith('ponychat')
 assert not p.name.endswith(('.gz','.zip','.tar','.xz'))
 remove_tree(p)
remove_tree('/tmp/ponychat-local-migration-20260909')

for row in protected['extra_apks']:
 p=pathlib.Path(row['path'])
 assert p.suffix=='.apk' and 'backups' not in p.parts
 assert p.is_relative_to('/opt/ponychat/PonyChat-Website') or p.is_relative_to('/var/www/ponychat-static')
 assert p.is_file() and p.stat().st_size==row['size']
 p.unlink();report['apks']+=1;report['removed_files']+=1;report['removed_bytes']+=row['size']

for unit in units:
 p=pathlib.Path('/etc/systemd/system')/(unit+'.service')
 assert p.parent==pathlib.Path('/etc/systemd/system')
 p.unlink(missing_ok=True)
 for parent in ['/etc/systemd/system','/run/systemd/system.control','/run/systemd/system']:
  remove_tree(pathlib.Path(parent)/(unit+'.service.d'))
pathlib.Path('/etc/ponychat/cosyvoice.env').unlink(missing_ok=True)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','reset-failed',*units],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
for unit in units:
 assert subprocess.check_output(['systemctl','show',unit,'-p','LoadState','--value'],text=True).strip()=='not-found'
for value,expected in protected['protected_files'].items():
 p=pathlib.Path(value);st=p.stat()
 assert [st.st_size,st.st_mtime_ns]==expected, 'Protected file changed: '+value
for name,expected in protected['music'].items():
 assert subprocess.check_output(['systemctl','show',name,'-p','ActiveState','-p','MainPID'],text=True)==expected
for root in ['/opt/ponychat/PonyChat-Website','/var/www/ponychat-static']:
 assert not any(pathlib.Path(root).rglob('*.apk')), 'An APK remains in the website tree'
assert not pathlib.Path('/opt/ponychat/Backend/database/ponychat.db').exists()
assert not pathlib.Path('/opt/ponychat/var/.chatlogs').exists()
report.update(finished_at=time.time(),protected_files_verified=len(protected['protected_files']),
              music_processes_unchanged=True,units_removed=units,
              disk_available=os.statvfs('/').f_bavail*os.statvfs('/').f_frsize)
print(json.dumps(report))
PY
'''
    result = json.loads(ssh_run(script, timeout=1800))
    (STATE / "server-retirement.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
