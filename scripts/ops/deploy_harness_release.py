"""Deploy tracked Backend code with a rollback snapshot and exact health check.

Default only prepares a local archive. --deploy is the explicit production action.
Database, model credentials, reports, logs and tests are never in the archive.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import secrets
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/ponychat"
EXCLUDED = {"Agent-Test", "tests", "deploy", "database", "data", "backups", "__pycache__"}
CONFIG_FILES = {"Backend/conf/model_config.json", "Backend/conf/models/deepseek.json",
                "Backend/conf/reasoning_control.json"}
REMOVED_FILES = ["Backend/conf/models/doubao.json", "Backend/providers/doubao.py"]


def source_files() -> list[Path]:
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "Backend"], cwd=ROOT
    ).decode().split("\0")
    result = []
    for name in filter(None, names):
        path = Path(name)
        if set(path.parts[1:]) & EXCLUDED:
            continue
        if path.suffix == ".py" or name in CONFIG_FILES or name == "Backend/conf/requirements.txt" or (
            name.startswith("Backend/chat_modules/harness_plugin/") and path.suffix == ".mjs"
        ):
            source = ROOT / path
            if source.suffix == ".py":
                compile(source.read_bytes(), name, "exec")
            result.append(path)
    if not result:
        raise RuntimeError("No tracked Backend source files")
    return sorted(result)


def deployment_script(release: str, digest: str, version: str, code: int, apk_hash: str,
                      wait_for_activation: bool = False) -> str:
    # Values are generated tokens or parsed from our signed APK receipt, never secrets.
    return f'''set -eu
python3 - <<'PY'
import hashlib,json,os,re,shutil,subprocess,tarfile,time,urllib.request
from pathlib import Path
root=Path({REMOTE!r})
release={release!r}
archive=Path('/tmp/ponychat-'+release+'.tar.gz')
assert hashlib.sha256(archive.read_bytes()).hexdigest()=={digest!r}
snapshot=Path('/var/backups/ponychat-harness')/release
snapshot.mkdir(parents=True,exist_ok=False)
snapshot.chmod(0o700)
env=root/'.env'
nginx=Path('/etc/nginx/sites-enabled/ponychat-www').resolve(strict=True)
shutil.copy2(env,snapshot/'environment.before')
shutil.copy2(nginx,snapshot/'nginx.before')
with (snapshot/'pip-freeze.before.txt').open('w') as output:
 subprocess.run([str(root/'.venv/bin/python'),'-m','pip','freeze'],stdout=output,check=True)
with tarfile.open(archive) as payload:
 names=payload.getnames()
 assert all(n.startswith('Backend/') and '..' not in Path(n).parts and not Path(n).is_absolute() for n in names)
 assert all(not m.issym() and not m.islnk() for m in payload.getmembers())
 removed={REMOVED_FILES!r}
 existed=[n for n in names+removed if (root/n).exists()]
 missing=[n for n in names if not (root/n).exists()]
 with tarfile.open(snapshot/'source.before.tar.gz','w:gz') as backup:
  for name in existed: backup.add(root/name,arcname=name)
 (snapshot/'new-files.json').write_text(json.dumps(missing))
 (snapshot/'manifest.json').write_text(json.dumps(names))
 service_was_active=subprocess.run(['systemctl','is-active','--quiet','ponychat-backend.service']).returncode==0
 (snapshot/'backend-was-active').write_text(str(service_was_active))
 def restore():
  subprocess.run(['systemctl','stop','ponychat-backend.service'],check=False)
  with tarfile.open(snapshot/'source.before.tar.gz') as backup: backup.extractall(root,filter='data')
  for name in missing: (root/name).unlink(missing_ok=True)
  shutil.copy2(snapshot/'environment.before',env)
  shutil.copy2(snapshot/'nginx.before',nginx)
  subprocess.run(['nginx','-t'],check=True)
  subprocess.run(['systemctl','reload','nginx'],check=True)
  if service_was_active: subprocess.run(['systemctl','start','ponychat-backend.service'],check=True)
 source_changed=False
 try:
  subprocess.run([str(root/'.venv/bin/python'),'-m','pip','install','--disable-pip-version-check','deepseek-harness-sdk==0.1.2rc1'],check=True)
  subprocess.run([str(root/'.venv/bin/python'),'-c','from deepseek_harness import DeepSeekHarness; from importlib.metadata import version; assert version("deepseek-harness-sdk")=="0.1.2rc1"; assert version("deepseek-harness-runtime-bin")=="0.1.2rc1"'],check=True)
  if {wait_for_activation!r}:
   print('READY_FOR_ACTIVATION '+str(snapshot/'activate'),flush=True)
   for attempt in range(450):
    if (snapshot/'activate').exists(): break
    time.sleep(2)
   else: raise RuntimeError('Timed out before activation approval')
  source_changed=True
  subprocess.run(['systemctl','stop','ponychat-backend.service'],check=True)
  payload.extractall(root,filter='data')
  for name in removed: (root/name).unlink(missing_ok=True)
  for name in names:
   if name.endswith('.py'): compile((root/name).read_bytes(),name,'exec')
  values={{'PONYCHAT_APP_VERSION_NAME':{version!r},'PONYCHAT_APP_VERSION_CODE':str({code!r}),'PONYCHAT_APP_APK_PATH':{(REMOTE+'/PonyChat-Website/Main/deploy/releases/PonyChat-v'+version+'-'+str(code)+'-release.apk')!r}}}
  assert hashlib.sha256(Path(values['PONYCHAT_APP_APK_PATH']).read_bytes()).hexdigest()=={apk_hash!r}
  lines=env.read_text().splitlines()
  for key,value in values.items():
   lines=[line for line in lines if not line.startswith(key+'=')]
   lines.append(key+'='+value)
  env.write_text('\\n'.join(lines)+'\\n')
  pause=Path('/var/lib/ponychat-model-pause/paused')
  if pause.exists():
   shutil.copy2(pause,snapshot/'pause-marker.before')
   pause.unlink()
  subprocess.run(['systemctl','start','ponychat-backend.service'],check=True)
  health=None
  for attempt in range(60):
   try:
    with urllib.request.urlopen('http://127.0.0.1:5000/api/health',timeout=3) as response: health=json.load(response)
    if health.get('deploy_token')==release: break
   except Exception: pass
   time.sleep(2)
  else: raise RuntimeError('Deployed process did not report expected health token')
  prior=Path('/var/lib/ponychat-model-pause/ponychat-cosyvoice.service.previous-active')
  if prior.exists() and prior.read_text().strip()=='active':
   subprocess.run(['systemctl','start','ponychat-cosyvoice.service'],check=True)
  text=nginx.read_text()
  if '# BEGIN PonyChat static APK' in text:
   text,count=re.subn(r'    # BEGIN PonyChat static APK.*?    # END PonyChat static APK\\n(?:\\n)?','',text,count=1,flags=re.S)
   assert count==1
   nginx.write_text(text)
   subprocess.run(['nginx','-t'],check=True)
   subprocess.run(['systemctl','reload','nginx'],check=True)
  result={{'deploy_token':release,'backup':str(snapshot),'health':health,'backend_active':subprocess.run(['systemctl','is-active','--quiet','ponychat-backend.service']).returncode==0}}
  (snapshot/'receipt.json').write_text(json.dumps(result,indent=2))
  print(json.dumps(result))
 except BaseException:
  if source_changed:
   restore()
   print('DEPLOYMENT_ROLLED_BACK backup='+str(snapshot))
  else:
   print('DEPLOYMENT_NOT_ACTIVATED backup='+str(snapshot))
  raise
finally_marker=snapshot/'completed'
finally_marker.touch()
archive.unlink()
PY
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--wait-for-activation", action="store_true",
                        help="Wait for a marker in the printed snapshot path before stopping the service")
    args = parser.parse_args()
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "Backend"], cwd=ROOT
    ).decode().splitlines()
    if args.deploy and any(Path(name).suffix in {".py", ".mjs"}
                           and not set(Path(name).parts) & EXCLUDED for name in untracked):
        raise RuntimeError("Stage all new Backend source files before deploying")
    files = source_files()
    release = "harness-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
    app_build = (ROOT / "Android-App/app/build.gradle.kts").read_text(encoding="utf-8")
    version = re.search(r'\bversionName\s*=\s*"([0-9.]+)"', app_build).group(1)
    code = int(re.search(r"\bversionCode\s*=\s*(\d+)", app_build).group(1))
    receipt = ROOT / f"Android-App/releases/PonyChat-v{version}-{code}-release.json"
    apk = json.loads(receipt.read_text(encoding="utf-8"))
    if (apk["version_name"] != version or apk["version_code"] != code
            or not apk.get("published") or apk.get("public_sha256") != apk["sha256"]):
        raise RuntimeError("Publish and verify the current signed APK before deploying")
    with tempfile.TemporaryDirectory(prefix="ponychat-release-") as directory:
        archive = Path(directory) / "backend.tar.gz"
        with tarfile.open(archive, "w:gz") as payload:
            for file in files:
                payload.add(ROOT / file, arcname=file.as_posix(), recursive=False)
            revision = json.dumps({"deploy_token": release}).encode()
            info = tarfile.TarInfo("Backend/.deploy_revision")
            info.size = len(revision)
            payload.addfile(info, io.BytesIO(revision))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        print(json.dumps({"release": release, "files": len(files), "archive_sha256": digest,
                          "deploy": args.deploy, "target": "Server-USA 154.17.23.237"}))
        if not args.deploy:
            return 0
        sys.path.insert(0, str(ROOT.parent / "ServerKeys"))
        from ssh_lib import load_server, scp_to, ssh_bash_s
        server = load_server("usa")
        if scp_to(server, archive, "/tmp/ponychat-" + release + ".tar.gz"):
            raise RuntimeError("Archive upload failed")
        script = deployment_script(release, digest, apk["version_name"], apk["version_code"], apk["sha256"],
                                   args.wait_for_activation)
        if ssh_bash_s(server, script):
            raise RuntimeError("Deployment failed; inspect the named rollback snapshot")
    with urllib.request.urlopen("https://www.ponychat.org/api/health", timeout=30) as response:
        public_health = json.load(response)
    if public_health.get("deploy_token") != release:
        raise RuntimeError("Public health did not match deployed source token")
    public_hash = hashlib.sha256()
    public_bytes = 0
    with urllib.request.urlopen("https://www.ponychat.org/download/apk", timeout=60) as response:
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            public_hash.update(chunk)
            public_bytes += len(chunk)
    if public_hash.hexdigest() != apk["sha256"] or public_bytes != apk["bytes"]:
        raise RuntimeError("Canonical public APK does not match the signed release")
    print(json.dumps({"public_health_token": release, "canonical_apk_sha256": public_hash.hexdigest(),
                      "canonical_apk_bytes": public_bytes, "canonical_route": "backend"}))
    (ROOT / ".ponychat-models-paused").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
