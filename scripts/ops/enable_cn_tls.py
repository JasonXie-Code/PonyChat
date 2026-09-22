"""Install the scoped PonyChat IP TLS entry on Server-CN; keep other SNI routes."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "ServerKeys"))
from ssh_lib import load_server, ssh_bash_s

PREPARE = r"""set -eu
backup=/root/ponychat-tls-20260911
mkdir -p "$backup" /var/www/ponychat-acme/.well-known/acme-challenge
for file in /etc/nginx/sites-available/scenery /etc/nginx/stream.d/sni-route.conf; do
  test -e "$backup/$(basename "$file")" || cp -a "$file" "$backup/$(basename "$file")"
done
python3 - <<'PY'
from pathlib import Path
p = Path('/etc/nginx/sites-enabled/scenery').resolve()
s = p.read_text()
if '/var/www/ponychat-acme' not in s:
    s = s.replace('    client_max_body_size 80m;', '''    client_max_body_size 80m;
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/ponychat-acme;
        default_type text/plain;
        try_files $uri =404;
    }''', 1)
    p.write_text(s)
PY
nginx -t
systemctl reload nginx
python3 -m venv /opt/ponychat-certbot
/opt/ponychat-certbot/bin/pip -q install --index-url https://mirrors.aliyun.com/pypi/simple 'certbot==5.4.0'
/opt/ponychat-certbot/bin/certbot --version
"""

ISSUE = r"""set -eu
/opt/ponychat-certbot/bin/certbot certonly --non-interactive --agree-tos \
  --register-unsafely-without-email --preferred-profile shortlived \
  --webroot --webroot-path /var/www/ponychat-acme --ip-address 39.101.74.217 \
  --cert-name ponychat-cn-ip \
  --config-dir /etc/letsencrypt-ponychat --work-dir /var/lib/letsencrypt-ponychat \
  --logs-dir /var/log/letsencrypt-ponychat
"""

INSTALL = r"""set -eu
test -s /etc/letsencrypt-ponychat/live/ponychat-cn-ip/fullchain.pem
cat > /etc/nginx/sites-available/ponychat-ip-tls <<'NGINX'
# IP clients do not send DNS SNI; stream routes empty/IP SNI to this listener.
server {
    listen 127.0.0.1:10449 ssl;
    server_name 39.101.74.217;
    ssl_certificate /etc/letsencrypt-ponychat/live/ponychat-cn-ip/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt-ponychat/live/ponychat-cn-ip/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:PonyChatTLS:10m;
    ssl_session_timeout 1d;
    client_max_body_size 80m;
    include /etc/nginx/snippets/ponychat-local-ip.conf;
    location / { return 404; }
}
NGINX
ln -sfn /etc/nginx/sites-available/ponychat-ip-tls /etc/nginx/sites-enabled/ponychat-ip-tls
python3 - <<'PY'
from pathlib import Path
p = Path('/etc/nginx/stream.d/sni-route.conf')
s = p.read_text()
if '127.0.0.1:10449' not in s:
    s = s.replace('map $ssl_preread_server_name $backend_443 {', '''map $ssl_preread_server_name $backend_443 {
    "" 127.0.0.1:10449;
    39.101.74.217 127.0.0.1:10449;''', 1)
# Long chat requests allow 600 seconds without a response body.
s = s.replace('proxy_timeout 300s;', 'proxy_timeout 900s;')
p.write_text(s)
PY
if ! nginx -t; then
  cp /root/ponychat-tls-20260911/sni-route.conf /etc/nginx/stream.d/sni-route.conf
  unlink /etc/nginx/sites-enabled/ponychat-ip-tls
  exit 1
fi
systemctl reload nginx
mkdir -p /etc/letsencrypt-ponychat/renewal-hooks/deploy
cat > /etc/letsencrypt-ponychat/renewal-hooks/deploy/reload-nginx <<'HOOK'
#!/bin/sh
set -eu
/usr/sbin/nginx -t
/bin/systemctl reload nginx
HOOK
chmod 755 /etc/letsencrypt-ponychat/renewal-hooks/deploy/reload-nginx
cat > /etc/systemd/system/ponychat-cert-renew.service <<'UNIT'
[Unit]
Description=Renew PonyChat short-lived IP TLS certificate
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/opt/ponychat-certbot/bin/certbot renew --non-interactive --config-dir /etc/letsencrypt-ponychat --work-dir /var/lib/letsencrypt-ponychat --logs-dir /var/log/letsencrypt-ponychat
UNIT
cat > /etc/systemd/system/ponychat-cert-renew.timer <<'UNIT'
[Unit]
Description=Check PonyChat IP certificate renewal every six hours
[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
RandomizedDelaySec=300
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now ponychat-cert-renew.timer
openssl x509 -in /etc/letsencrypt-ponychat/live/ponychat-cn-ip/fullchain.pem -noout -issuer -dates -ext subjectAltName
systemctl list-timers ponychat-cert-renew.timer --no-pager
"""

VERIFY_RENEWAL = r"""set -eu
/opt/ponychat-certbot/bin/certbot renew --dry-run --run-deploy-hooks \
  --config-dir /etc/letsencrypt-ponychat --work-dir /var/lib/letsencrypt-ponychat \
  --logs-dir /var/log/letsencrypt-ponychat
"""

REQUIRE_HTTPS = r"""set -eu
backup=/root/ponychat-tls-20260911
test -e "$backup/ponychat-local-ip.conf" || cp -a /etc/nginx/snippets/ponychat-local-ip.conf "$backup/ponychat-local-ip.conf"
cat > /etc/nginx/conf.d/ponychat-https-policy.conf <<'NGINX'
# Older APKs need only discovery and signed APK download to upgrade.
map "$scheme:$uri" $ponychat_plaintext_block {
    default 0;
    "http:/api/app/version" 0;
    "http:/download/apk" 0;
    ~^http: 1;
}
NGINX
python3 - <<'PY'
from pathlib import Path
p = Path('/etc/nginx/snippets/ponychat-local-ip.conf')
s = p.read_text()
if '$ponychat_plaintext_block' not in s:
    s = s.replace('    proxy_pass http://127.0.0.1:18500;', '''    default_type application/json;
    if ($ponychat_plaintext_block) {
        return 426 '{"detail":"Please upgrade PonyChat to 6.0.6 or later for HTTPS","min_version":"6.0.6","upgrade_required":true}';
    }
    proxy_pass http://127.0.0.1:18500;''', 1)
    s = s.replace('http://39.101.74.217:80', 'https://39.101.74.217')
    p.write_text(s)
PY
if ! nginx -t; then
  cp "$backup/ponychat-local-ip.conf" /etc/nginx/snippets/ponychat-local-ip.conf
  exit 1
fi
systemctl reload nginx
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "issue", "install", "verify-renewal", "require-https"])
    phase = parser.parse_args().phase
    raise SystemExit(ssh_bash_s(load_server("yuelimei"), {
        "prepare": PREPARE, "issue": ISSUE, "install": INSTALL,
        "verify-renewal": VERIFY_RENEWAL,
        "require-https": REQUIRE_HTTPS,
    }[phase]))
