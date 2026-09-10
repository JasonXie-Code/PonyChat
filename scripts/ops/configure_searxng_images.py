"""Enable tested image engines alongside existing SearXNG engines (run on server)."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request

import yaml

IMAGE_ENGINES = ('google images', 'bing images')


def with_image_engines(settings, defaults):
    import copy
    settings = copy.deepcopy(settings)
    available = {row['name'] for row in defaults['engines']}
    if not set(IMAGE_ENGINES) <= available:
        raise ValueError('Installed SearXNG lacks configured image engines')
    default_settings = settings.get('use_default_settings')
    if isinstance(default_settings, dict):
        engine_settings = default_settings.setdefault('engines', {})
        if 'keep_only' in engine_settings:
            engine_settings['keep_only'] = list(dict.fromkeys([*engine_settings['keep_only'], *IMAGE_ENGINES]))
        if 'remove' in engine_settings:
            engine_settings['remove'] = [name for name in engine_settings['remove'] if name not in IMAGE_ENGINES]
    configured = settings.setdefault('engines', [])
    for name in IMAGE_ENGINES:
        row = next((item for item in configured if item['name'] == name), None)
        if row is None:
            configured.append({'name': name, 'disabled': False})
        else:
            row['disabled'] = False
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/opt/ponychat-searxng')
    parser.add_argument('--apply', action='store_true', help='Write config and restart after creating rollback copy')
    args = parser.parse_args()
    root = Path(args.root)
    path = root / 'settings.yml'
    original = path.read_bytes()
    settings = with_image_engines(yaml.safe_load(original), yaml.safe_load((root / 'source/searx/settings.yml').read_text()))
    if not args.apply:
        print(json.dumps({'image_engines': IMAGE_ENGINES, 'changed': settings != yaml.safe_load(original)}))
        return
    if settings == yaml.safe_load(original):
        print(json.dumps({'status': 'already_enabled', 'image_engines': IMAGE_ENGINES}))
        return
    backup = root / ('settings.before-web-images-' + time.strftime('%Y%m%d-%H%M%S') + '.yml')
    with backup.open('xb') as stream:
        stream.write(original)
    backup.chmod(0o600)
    try:
        path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding='utf-8')
        subprocess.run(['systemctl', 'restart', 'ponychat-searxng.service'], check=True)
        for _ in range(40):
            try:
                with urllib.request.urlopen('http://127.0.0.1:18786/healthz', timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError('SearXNG health check failed')
        print(json.dumps({'status': 'enabled', 'image_engines': IMAGE_ENGINES, 'backup': str(backup)}))
    except BaseException:
        path.write_bytes(original)
        subprocess.run(['systemctl', 'restart', 'ponychat-searxng.service'], check=True)
        raise


if __name__ == '__main__':
    main()
