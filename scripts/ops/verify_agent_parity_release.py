"""Verify the scoped release receipt against local files, Server-USA and public health."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import urllib.request

from compare_server_backend import _ssh_capture, load_server

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', required=True)
    reports = Path(parser.parse_args().reports).resolve()
    receipt = json.loads((reports/'deployment.json').read_text())
    names = list(receipt['hashes'])
    assert receipt['target'] == 'Server-USA'
    assert all(name.startswith('Backend/') and '..' not in Path(name).parts and '\\' not in name for name in names)
    code = '''import hashlib,json,subprocess
from pathlib import Path
root=Path('/opt/ponychat')
names=NAMES
hashes={name:hashlib.sha256((root/name).read_bytes().replace(b'\\r\\n',b'\\n')).hexdigest() for name in names}
print(json.dumps({'hashes':hashes,'service':subprocess.check_output(['systemctl','is-active','ponychat-backend.service'],text=True).strip(),'revision':json.loads((root/'Backend/.deploy_revision').read_text())}))
'''.replace('NAMES', repr(names))
    encoded = base64.b64encode(code.encode()).decode()
    rc, out, err = _ssh_capture(load_server('usa'), 'python3 -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"')
    if rc:
        raise RuntimeError(out[-2000:]+'\n'+err[-2000:])
    remote = json.loads(out.strip().splitlines()[-1])
    local = {name:hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for name in names}
    health = json.load(urllib.request.urlopen('https://www.ponychat.org/api/health', timeout=30))
    result = {'passed': remote['hashes'] == local == receipt['hashes'] and remote['service'] == 'active'
              and remote['revision']['revision'] == receipt['revision']
              and health.get('status') == 'running' and health.get('deploy_token') == receipt['release'],
              'matched_files':sum(remote['hashes'][name] == local[name] == receipt['hashes'][name] for name in names),
              'service': remote['service'], 'revision':remote['revision'], 'public_health':health}
    first_path = reports/'deployment-first-release.json'
    if first_path.exists():
        first = json.loads(first_path.read_text())
        normal_files = [name for name in first['hashes'] if '/galgame/' not in name]
        result['normal_chat_unchanged_from_first_release'] = all(receipt['hashes'][name] == first['hashes'][name] for name in normal_files)
        result['normal_chat_matched_files'] = len(normal_files)
    (reports/'final-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))
    assert result['passed']


if __name__ == '__main__':
    main()
