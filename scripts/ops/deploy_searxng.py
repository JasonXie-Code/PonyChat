"""Install the pinned private SearXNG service on Server-USA; no public listener."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
REVISION = 'c7f3080aac5de13b619c4a5ab36590a2c5165e1c'


def main():
    sys.path.insert(0, str(ROOT.parent / 'ServerKeys'))
    from ssh_lib import load_server, ssh_bash_s
    script = r"""set -eu
base=/opt/ponychat-searxng
if [ ! -d "$base/source/.git" ]; then
  install -d -m 755 "$base"
  git clone --depth 1 https://github.com/searxng/searxng.git "$base/source"
fi
test "$(git -C "$base/source" rev-parse HEAD)" = '__REVISION__'
if [ ! -x "$base/venv/bin/gunicorn" ]; then
  python3 -m venv "$base/venv"
  "$base/venv/bin/pip" install -q --upgrade pip setuptools wheel
  "$base/venv/bin/pip" install -q -r "$base/source/requirements.txt" gunicorn
  "$base/venv/bin/pip" install -q --no-build-isolation --no-deps -e "$base/source"
fi
id ponychat-search >/dev/null 2>&1 || useradd --system --home-dir "$base" --shell /usr/sbin/nologin ponychat-search
install -d -o ponychat-search -g ponychat-search -m 750 "$base/state"
python3 - <<'PY'
from pathlib import Path
import secrets, shutil, time
root=Path('/opt/ponychat-searxng')
settings=root/'settings.yml'
if not settings.exists():
 settings.write_text('''use_default_settings:
  engines:
    keep_only: [google, google cse, yahoo, 360search, wikipedia]
general:
  debug: false
  instance_name: PonyChat Private Search
search:
  formats: [html, json]
  autocomplete: ''
  safe_search: 1
server:
  secret_key: '''+secrets.token_hex(32)+'''
  limiter: false
  image_proxy: false
outgoing:
  request_timeout: 5.0
  max_request_timeout: 8.0
engines:
  - name: google
    disabled: false
  - name: google cse
    disabled: false
    weight: 0.8
  - name: yahoo
    disabled: false
  - name: 360search
    disabled: false
    weight: 0.4
  - name: wikipedia
    disabled: false
''')
unit=Path('/etc/systemd/system/ponychat-searxng.service')
content='''[Unit]
Description=PonyChat private SearXNG search
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ponychat-search
Group=ponychat-search
WorkingDirectory=/opt/ponychat-searxng/source
Environment=SEARXNG_SETTINGS_PATH=/opt/ponychat-searxng/settings.yml
Environment=SEARXNG_DATA_PATH=/opt/ponychat-searxng/state
Environment=XDG_CACHE_HOME=/opt/ponychat-searxng/state
Environment=HOME=/opt/ponychat-searxng/state
ExecStart=/opt/ponychat-searxng/venv/bin/gunicorn --bind 127.0.0.1:18786 --workers 1 --threads 4 --timeout 40 searx.webapp:app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/ponychat-searxng/state
MemoryMax=384M

[Install]
WantedBy=multi-user.target
'''
if unit.exists() and unit.read_text()!=content:
 shutil.copy2(unit,root/('service.before-'+time.strftime('%Y%m%d-%H%M%S')))
unit.write_text(content)
PY
chown root:ponychat-search "$base/settings.yml"
chmod 640 "$base/settings.yml"
systemctl daemon-reload
systemctl enable --now ponychat-searxng.service
sleep 3
systemctl is-active ponychat-searxng.service
curl -fsS http://127.0.0.1:18786/healthz
git -C "$base/source" rev-parse HEAD
""".replace('__REVISION__', REVISION)
    raise SystemExit(ssh_bash_s(load_server('usa'), script))


if __name__ == '__main__':
    main()
