"""Scoped history-image deployment on Server-USA; source backups and health rollback."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request


def main():
    archive, release = Path(sys.argv[1]), sys.argv[2]
    assert release.startswith('history-images-') and all(c.isalnum() or c == '-' for c in release)
    root = Path('/opt/ponychat')
    backup = root / 'backups' / release
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = root / '.env'
    shutil.copy2(env, backup / 'environment.before')
    edits = {}
    with tarfile.open(archive) as payload:
        for member in payload:
            assert member.isfile() and member.name.startswith('Backend/') and '..' not in Path(member.name).parts
            edits[member.name] = payload.extractfile(member).read()
    baselines = json.loads(Path(sys.argv[3]).read_text())
    for name, data in edits.items():
        target = root / name
        if target.exists():
            current = hashlib.sha256(target.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            assert current in {baselines.get(name), hashlib.sha256(data).hexdigest()}, 'Concurrent source change: ' + name
        else:
            assert baselines.get(name) is None, 'Unexpected missing source: ' + name

    name = 'Backend/chat_modules/autonomous_normal.py'
    normal = (root / name).read_text()
    if 'history_image_tools=None' not in normal:
        assert normal.count('source_reader=None, prior_image_reader=None,') == 2
        normal = normal.replace('source_reader=None, prior_image_reader=None,',
            'source_reader=None, prior_image_reader=None, history_image_tools=None,')
        normal = normal.replace('source_reader=source_reader, prior_image_reader=prior_image_reader, business_tools=',
            'source_reader=source_reader, prior_image_reader=prior_image_reader, history_image_tools=history_image_tools, business_tools=')
        normal = normal.replace('    if prior_image_reader:\n',
            '    if history_image_tools:\n        history_image_tools.register(capability)\n    if prior_image_reader:\n')
    normal = normal.replace('observations.append({"tool": name, "arguments": dict(arguments), "result": value})',
        'from .agent_logging import snapshot\n            observations.append({"tool": name, "arguments": dict(arguments), "result": snapshot(value)})')
    assert 'history_image_tools.register(capability)' in normal and 'history_image_tools=history_image_tools' in normal
    edits[name] = normal.encode()

    name = 'Backend/chat_modules/autonomous_service.py'
    service = (root / name).read_text()
    if '    from .history_image_tools import HistoryImageTools' not in service:
        anchor = '    from .autonomous_images import resolve_harness_image_blocks'
        assert service.count(anchor) == 1
        service = service.replace(anchor, '    from .history_image_tools import HistoryImageTools\n'
            '    history_image_tools = HistoryImageTools(config.DB_PATH, username=request.username,\n'
            '        character_id=request.character_id, conversation_id=request.conversation_id)\n'
            '    environment += "\\n用户追问历史图片时，先用list_history_images定位，再用read_history_image重新看原图；需要更早图片时翻页。不要仅靠历史识图摘要回答新的画面细节。"\n\n' + anchor)
        service = service.replace('source_reader=originals, prior_image_reader=prior_images, business_tools=',
            'source_reader=originals, prior_image_reader=prior_images, history_image_tools=history_image_tools, business_tools=')
    assert 'history_image_tools=history_image_tools' in service
    edits[name] = service.encode()
    edits['Backend/.deploy_revision'] = json.dumps({'deploy_token': release}).encode()
    for name, data in edits.items():
        if name.endswith('.py'):
            compile(data, name, 'exec')
    existed = [name for name in edits if (root / name).exists()]
    missing = [name for name in edits if name not in existed]
    with tarfile.open(backup / 'source.before.tar.gz', 'w:gz') as out:
        for name in existed:
            out.add(root / name, arcname=name)
    (backup / 'new-files.json').write_text(json.dumps(missing))
    apk = root / 'PonyChat-Website/Main/deploy/releases/PonyChat-v5.6.25-365-release.apk'
    assert apk.is_file(), 'Publish APK first'
    was_active = subprocess.run(['systemctl','is-active','--quiet','ponychat-backend.service']).returncode == 0
    assert was_active, 'Unexpected stopped backend; no change made'
    try:
        subprocess.run(['systemctl','stop','ponychat-backend.service'], check=True)
        for name, data in edits.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        values = {'PONYCHAT_APP_VERSION_NAME':'5.6.25', 'PONYCHAT_APP_VERSION_CODE':'365',
                  'PONYCHAT_APP_APK_PATH': str(apk)}
        lines = env.read_text().splitlines()
        lines = [line for line in lines if line.split('=',1)[0] not in values]
        env.write_text('\n'.join(lines + [k+'='+v for k,v in values.items()]) + '\n')
        subprocess.run(['systemctl','start','ponychat-backend.service'], check=True)
        for _ in range(45):
            try:
                with urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3) as response:
                    health = json.load(response)
                if health.get('deploy_token') == release:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('New backend health token was not observed')
        receipt = {'deploy_token':release, 'backup':str(backup), 'health':health,
                   'files':{name:hashlib.sha256(data).hexdigest() for name,data in edits.items()},
                   'user_media_storage':'phone; SDK scratch in /dev/shm; no durable media writes',
                   'version_name':'5.6.25','version_code':365}
        (backup / 'receipt.json').write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt))
    except BaseException:
        subprocess.run(['systemctl','stop','ponychat-backend.service'])
        with tarfile.open(backup / 'source.before.tar.gz') as source:
            source.extractall(root, filter='data')
        for name in missing:
            target = (root / name).resolve()
            assert target.is_relative_to(root.resolve())
            target.unlink(missing_ok=True)
        shutil.copy2(backup / 'environment.before', env)
        subprocess.run(['systemctl','start','ponychat-backend.service'], check=True)
        raise


if __name__ == '__main__':
    main()
