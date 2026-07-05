from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVERKEYS = ROOT.parent.parent.parent / "ServerKeys"
sys.path.insert(0, str(SERVERKEYS))

from ssh_lib import deploy_upload_env, load_server, scp_to, ssh_bash_s  # noqa: E402

REMOTE_OPT = "/opt/mlp-music-auto"
REMOTE_WWW = "/var/www/mlp-music-auto"
REMOTE_DATA = "/data/mlp-music-auto"
REMOTE_TAR = "/tmp/mlp-music-auto-data.tar.gz"
SERVICE = "mlp-music-auto.service"
DOMAIN = "music-auto.ponychat.org"
PORT = 8823


HTTPS_PORT = 8847
CERT_DIR = f"/etc/letsencrypt/live/{DOMAIN}"
SNI_ROUTE = "/etc/nginx/stream.d/sni-route.conf"


def nginx_block() -> str:
    locations = f"""
    location /api/ {{
        proxy_pass http://127.0.0.1:{PORT};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }}
    location /audio/ {{
        alias {REMOTE_DATA}/source/audio/;
        add_header Accept-Ranges bytes;
    }}
    location /scores/ {{
        alias {REMOTE_DATA}/source/scores/;
        default_type application/pdf;
    }}
    location /charts/ {{
        alias {REMOTE_DATA}/source/charts/;
    }}
    location /generated/ {{
        alias {REMOTE_DATA}/generated/;
    }}
    location / {{
        try_files $uri $uri/ /index.html;
    }}"""
    return f"""server {{
    listen 80;
    server_name {DOMAIN};

    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}
    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 127.0.0.1:{HTTPS_PORT} ssl http2;
    server_name {DOMAIN};

    ssl_certificate     {CERT_DIR}/fullchain.pem;
    ssl_certificate_key {CERT_DIR}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    root {REMOTE_WWW};
    index index.html;
{locations}
}}"""


def pack_data() -> Path:
    out = ROOT / "dist" / "mlp-music-auto-data.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with tarfile.open(out, "w:gz", compresslevel=6) as tar:
        for name in ("source", "generated"):
            p = ROOT / name
            if p.is_dir():
                tar.add(p, arcname=name)
    return out


def main() -> int:
    entry = load_server("usa")
    env = deploy_upload_env()
    cfg = nginx_block()
    # 证书尚不存在时，nginx 初始配置临时仅用 HTTP（供 ACME 验证）
    http_only_cfg = f"""server {{
    listen 80;
    server_name {DOMAIN};
    location /.well-known/acme-challenge/ {{ root /var/www/certbot; }}
    root {REMOTE_WWW};
    index index.html;
    location /api/ {{
        proxy_pass http://127.0.0.1:{PORT};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    location / {{ try_files $uri $uri/ /index.html; }}
}}"""
    setup = f"""set -euo pipefail
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv nginx certbot python3-certbot-nginx
mkdir -p {REMOTE_OPT}/app {REMOTE_WWW} {REMOTE_DATA} /var/www/certbot
if [ ! -d {REMOTE_OPT}/venv ]; then python3 -m venv {REMOTE_OPT}/venv; fi
{REMOTE_OPT}/venv/bin/pip install -q -U pip
cat > /etc/systemd/system/{SERVICE} << 'UNIT'
[Unit]
Description=MLP Music AUTO API
After=network.target

[Service]
Type=simple
WorkingDirectory={REMOTE_OPT}/app
Environment=MLP_AUTO_DATA_ROOT={REMOTE_DATA}
ExecStart={REMOTE_OPT}/venv/bin/uvicorn main:app --host 127.0.0.1 --port {PORT}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
# 先写入仅 HTTP 配置，以便 certbot 签发证书
cat > /etc/nginx/sites-available/mlp-music-auto <<'NGINX'
{http_only_cfg}
NGINX
ln -sf /etc/nginx/sites-available/mlp-music-auto /etc/nginx/sites-enabled/mlp-music-auto
nginx -t
systemctl daemon-reload
systemctl enable {SERVICE} || true
systemctl reload nginx 2>/dev/null || systemctl start nginx
# 若尚未存在则签发证书
if [ ! -f {CERT_DIR}/fullchain.pem ]; then
    certbot certonly --webroot -w /var/www/certbot -d {DOMAIN} \
      --non-interactive --agree-tos --email admin@ponychat.org
fi
# 再写入完整 HTTPS 配置
cat > /etc/nginx/sites-available/mlp-music-auto <<'NGINX'
{cfg}
NGINX
# 若尚未注册则添加 SNI 路由
if ! grep -q '{DOMAIN}' {SNI_ROUTE} 2>/dev/null; then
    sed -i '/^    default /i \\    {DOMAIN}       127.0.0.1:{HTTPS_PORT};' {SNI_ROUTE}
fi
nginx -t
"""
    rc = ssh_bash_s(entry, setup, env=env)
    if rc != 0:
        return rc

    ssh_bash_s(entry, f"rm -rf {REMOTE_OPT}/app/* {REMOTE_WWW}/*", env=env)
    rc = scp_to(entry, ROOT / "app", f"{REMOTE_OPT}/", recursive=True, env=env)
    if rc != 0:
        return rc
    rc = scp_to(entry, ROOT / "web", f"{REMOTE_WWW}/", recursive=True, env=env)
    if rc != 0:
        return rc
    ssh_bash_s(entry, f"if [ -d {REMOTE_WWW}/web ]; then mv {REMOTE_WWW}/web/* {REMOTE_WWW}/ && rmdir {REMOTE_WWW}/web; fi", env=env)
    ssh_bash_s(entry, f"{REMOTE_OPT}/venv/bin/pip install -q -r {REMOTE_OPT}/app/requirements.txt", env=env)

    tarball = pack_data()
    rc = scp_to(entry, tarball, REMOTE_TAR, env=env)
    if rc != 0:
        return rc
    rc = ssh_bash_s(
        entry,
        f"rm -rf {REMOTE_DATA}/source {REMOTE_DATA}/generated && mkdir -p {REMOTE_DATA} && tar -xzf {REMOTE_TAR} -C {REMOTE_DATA} && rm -f {REMOTE_TAR}",
        env=env,
    )
    if rc != 0:
        return rc
    return ssh_bash_s(entry, f"systemctl restart {SERVICE} && systemctl reload nginx", env=env)


if __name__ == "__main__":
    raise SystemExit(main())
