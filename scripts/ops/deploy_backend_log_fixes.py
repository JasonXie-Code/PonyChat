"""Deploy scoped log-audit fixes from Git, with drift checks and rollback."""
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
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
FILES = [
    'Backend/agent_memory/review.py',
    'Backend/character_voice_registration.py',
    'Backend/chat_modules/harness_plugin/chat-tools.mjs',
    'Backend/chat_modules/harness_runtime.py',
    'Backend/chat_modules/harness_pool.py',
    'Backend/routes/admin/characters_impl/admin_character_updates.py',
    'Backend/routes/admin/llm_log_indexer.py',
]

REMOTE_SCRIPT = r'''
import hashlib,json,shutil,subprocess,tarfile,time,urllib.request
from pathlib import Path
root=Path('/opt/ponychat')
backup=Path('/var/backups/ponychat-log-fixes')/cfg['release']
unit='ponychat-backend.service'
def restore():
    subprocess.run(['systemctl','stop',unit],check=True)
    old=json.loads((backup/'manifest.json').read_text())
    for name,existed in old.items():
        if existed: shutil.copy2(backup/name,root/name)
        else: (root/name).unlink(missing_ok=True)
    subprocess.run(['systemctl','start',unit],check=True)
if cfg.get('rollback'):
    for name,digest in cfg['hashes'].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest, 'Concurrent deployment: '+name
    restore()
    print(json.dumps({'rolled_back':True,'backup':str(backup)}))
else:
    archive=Path(cfg['archive'])
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==cfg['archive_hash']
    for name,digest in cfg['base_hashes'].items():
        assert hashlib.sha256((root/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==digest, 'Source drift: '+name
    subprocess.run(['systemctl','is-active','--quiet',unit],check=True)
    with tarfile.open(archive) as tar:
        assert tar.getnames()==cfg['files'] and all(m.isfile() for m in tar.getmembers())
        for name in cfg['files']:
            if name.endswith('.py'): compile(tar.extractfile(name).read(),name,'exec')
    backup.mkdir(parents=True,exist_ok=False)
    backup.chmod(0o700)
    old={}
    for name in cfg['files']+['Backend/.deploy_revision']:
        old[name]=(root/name).exists()
        if old[name]:
            target=backup/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(root/name,target)
    (backup/'manifest.json').write_text(json.dumps(old))
    try:
        subprocess.run(['systemctl','stop',unit],check=True)
        with tarfile.open(archive) as tar: tar.extractall(root,filter='data')
        for name,digest in cfg['hashes'].items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
        (root/'Backend/.deploy_revision').write_text(json.dumps({'deploy_token':cfg['release']}))
        subprocess.run(['systemctl','start',unit],check=True)
        for attempt in range(45):
            try:
                health=json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health',timeout=3))
                if health.get('deploy_token')==cfg['release']: break
            except Exception: pass
            time.sleep(2)
        else: raise RuntimeError('New process health token missing')
        receipt={'target':'Server-USA','release':cfg['release'],'revision':cfg['revision'],
                 'base':cfg['base'],'backup':str(backup),'hashes':cfg['hashes'],'health':health}
        (backup/'receipt.json').write_text(json.dumps(receipt,indent=2))
        print(json.dumps(receipt))
    except BaseException:
        restore()
        print('ROLLED_BACK '+str(backup))
        raise
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, help='Expected deployed Git revision, ignoring CRLF differences')
    parser.add_argument('--report', required=True)
    parser.add_argument('--deploy', action='store_true')
    args = parser.parse_args()
    revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT).decode().strip()
    base = subprocess.check_output(['git','rev-parse',args.base], cwd=ROOT).decode().strip()
    release = 'log-fixes-'+time.strftime('%Y%m%d-%H%M%S')+'-'+revision[:8]
    cfg = {'release':release,'revision':revision,'base':base,'files':FILES,'hashes':{},'base_hashes':{}}
    sys.path.insert(0, str(ROOT.parent/'ServerKeys'))
    from ssh_lib import load_server, scp_to
    from compare_server_backend import _ssh_capture
    server = load_server('usa')

    def remote(rollback=False):
        script = 'cfg='+repr({**cfg,'rollback':rollback})+'\n'+REMOTE_SCRIPT
        encoded = base64.b64encode(script.encode()).decode()
        rc, output, error = _ssh_capture(server,
            'cd /opt/ponychat && .venv/bin/python -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"')
        if rc:
            raise RuntimeError(output+'\n'+error)
        print(output, flush=True)
        return json.loads(output.strip().splitlines()[-1])

    with tempfile.TemporaryDirectory(prefix='ponychat-log-fixes-') as directory:
        archive = Path(directory)/'patch.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for name in FILES:
                content = subprocess.check_output(['git','show',revision+':'+name],cwd=ROOT)
                if name.endswith('.py'):
                    compile(content,name,'exec')
                else:
                    check = Path(directory)/'check.mjs'
                    check.write_bytes(content)
                    subprocess.run(['node','--check',str(check)],check=True)
                previous = subprocess.check_output(['git','show',base+':'+name],cwd=ROOT)
                cfg['base_hashes'][name] = hashlib.sha256(previous.replace(b'\r\n',b'\n')).hexdigest()
                cfg['hashes'][name] = hashlib.sha256(content).hexdigest()
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                entry.mode = 0o644
                tar.addfile(entry,io.BytesIO(content))
        cfg['archive_hash'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        cfg['archive'] = '/tmp/'+release+'.tar.gz'
        if not args.deploy:
            print(json.dumps({'prepared':True,**cfg}))
            return
        assert scp_to(server,archive,cfg['archive']) == 0
        receipt = remote()
        try:
            for attempt in range(6):
                try:
                    health = json.load(urllib.request.urlopen('https://www.ponychat.org/api/health',timeout=10))
                    if health.get('deploy_token')==release: break
                except Exception: pass
                time.sleep(2)
            else: raise RuntimeError('Public health token mismatch')
            receipt['public_health'] = health
        except BaseException:
            remote(rollback=True)
            raise
        report = Path(args.report)
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print(json.dumps({'deployed':True,'release':release,'report':str(report)}))


if __name__ == '__main__':
    main()
