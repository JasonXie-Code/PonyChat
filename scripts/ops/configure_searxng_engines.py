"""Apply the five tested SearXNG engines on Server-USA with config rollback."""
from pathlib import Path
import sys


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'ServerKeys'))
    from ssh_lib import load_server, ssh_bash_s
    script = """set -eu
/opt/ponychat-searxng/venv/bin/python - <<'PY'
from pathlib import Path
import json,shutil,subprocess,time,urllib.request
import yaml
root=Path('/opt/ponychat-searxng')
config=root/'settings.yml'
original=config.read_bytes()
settings=yaml.safe_load(original)
engines=[{'name':'google','disabled':False},
         {'name':'google cse','disabled':False,'weight':0.8},
         {'name':'yahoo','disabled':False},
         {'name':'360search','disabled':False,'weight':0.4},
         {'name':'wikipedia','disabled':False}]
defaults=yaml.safe_load((root/'source/searx/settings.yml').read_text())
assert {e['name'] for e in engines}<={e['name'] for e in defaults['engines']}
backup=root/('settings.before-five-'+time.strftime('%Y%m%d-%H%M%S')+'.yml')
shutil.copy2(config,backup)
settings['use_default_settings']['engines']['keep_only']=[e['name'] for e in engines]
settings['engines']=engines
try:
 config.write_text(yaml.safe_dump(settings,allow_unicode=True))
 subprocess.run(['systemctl','restart','ponychat-searxng.service'],check=True)
 for _ in range(30):
  try:
   with urllib.request.urlopen('http://127.0.0.1:18786/healthz',timeout=2) as r:
    assert r.status==200
   break
  except Exception: time.sleep(.5)
 else: raise RuntimeError('SearXNG failed health check')
 print(json.dumps({'engines':engines,'backup':str(backup),'health':'ok'}))
except BaseException:
 config.write_bytes(original)
 subprocess.run(['systemctl','restart','ponychat-searxng.service'],check=True)
 raise
PY
"""
    raise SystemExit(ssh_bash_s(load_server('usa'), script))


if __name__ == '__main__':
    main()
