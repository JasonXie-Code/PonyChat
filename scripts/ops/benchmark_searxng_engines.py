"""Run small, sequential candidate probes in an isolated loopback SearXNG process."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import httpx
import yaml

ROOT = Path('/opt/ponychat-searxng')
CANDIDATES = ['google', 'google cse', 'wikipedia', 'mojeek', 'qwant', 'startpage',
              'yahoo', 'seznam', 'sogou', 'baidu', '360search']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engines', nargs='+', default=CANDIDATES)
    parser.add_argument('--queries', nargs='+', default=['紫悦', 'Twilight Sparkle'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    defaults = yaml.safe_load((ROOT/'source/searx/settings.yml').read_text())
    configs = {r['name']: r for r in defaults['engines']}
    assert set(args.engines) <= configs.keys()
    report = {'target': 'Server-USA', 'queries': args.queries, 'results': []}
    with tempfile.TemporaryDirectory(prefix='engine-probe-', dir=ROOT/'state') as directory:
        work = Path(directory)
        settings = yaml.safe_load((ROOT/'settings.yml').read_text())
        settings['use_default_settings'] = {'engines': {'keep_only': args.engines}}
        settings['engines'] = [{'name': n, 'disabled': False} for n in args.engines]
        settings['server']['secret_key'] = 'isolated-engine-test'
        (work/'settings.yml').write_text(yaml.safe_dump(settings))
        env = dict(os.environ, SEARXNG_SETTINGS_PATH=str(work/'settings.yml'),
                   SEARXNG_DATA_PATH=str(work), XDG_CACHE_HOME=str(work))
        with (work/'process.log').open('w') as log:
            process = subprocess.Popen([str(ROOT/'venv/bin/gunicorn'), '--bind', '127.0.0.1:18787',
                '--workers', '1', '--threads', '2', '--timeout', '30', 'searx.webapp:app'],
                cwd=ROOT/'source', env=env, stdout=log, stderr=log)
            try:
                with httpx.Client(base_url='http://127.0.0.1:18787', timeout=15, trust_env=False) as client:
                    for _ in range(30):
                        if process.poll() is not None:
                            raise RuntimeError((work/'process.log').read_text()[-3000:])
                        try:
                            if client.get('/healthz').status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.5)
                    else:
                        raise RuntimeError('Probe process failed to start')
                    for query in args.queries:
                        for name in args.engines:
                            started = time.monotonic()
                            item = {'engine': name, 'query': query}
                            try:
                                response = client.get('/search', params={'q': '!'+configs[name]['shortcut']+' '+query,
                                    'format': 'json', 'language': 'all', 'safesearch': 1})
                                response.raise_for_status()
                                data = response.json()
                                item.update(count=len(data.get('results', [])), infobox_count=len(data.get('infoboxes', [])), errors=data.get('unresponsive_engines', []),
                                    results=[{k:r.get(k) for k in ('title','url','content','engines')}
                                             for r in data.get('results', [])[:5]],
                                    infoboxes=data.get('infoboxes', [])[:1])
                            except (httpx.HTTPError, ValueError) as exc:
                                item.update(count=0, errors=[type(exc).__name__])
                            item['seconds'] = round(time.monotonic()-started, 3)
                            report['results'].append(item)
                            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
                            print(json.dumps({k:v for k,v in item.items() if k not in ('results','infoboxes')}, ensure_ascii=False), flush=True)
                            time.sleep(1.5)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
