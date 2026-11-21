#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

WEBSITE_ROOT = Path(__file__).resolve().parents[1]
if str(WEBSITE_ROOT) not in sys.path:
    sys.path.insert(0, str(WEBSITE_ROOT))

from deploy_lib.incremental import deploy_tree, stage_files  # noqa: E402


def main() -> None:
    root = Path(__file__).resolve().parent
    static = root / "static"
    files = [
        (root / "app_cosyvoice.py", "app_cosyvoice.py"),
        (static / "index.html", "static/index.html"),
        (static / "cosyvoice.html", "static/cosyvoice.html"),
        (static / "qwen3tts.html", "static/qwen3tts.html"),
        (static / "assets" / "voice.css", "static/assets/voice.css"),
        (static / "assets" / "cosyvoice.js", "static/assets/cosyvoice.js"),
        (static / "assets" / "voice.js", "static/assets/voice.js"),
    ]
    for font in (static / "assets").glob("*.ttf"):
        files.append((font, f"static/assets/{font.name}"))

    api_key = (os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_TTS_API_KEY") or "").strip()
    env_setup = ""
    if api_key:
        env_setup = (
            "install -d -m 700 /etc/ponychat\n"
            "cat > /etc/ponychat/cosyvoice.env <<'ENV'\n"
            f"DASHSCOPE_API_KEY={api_key}\n"
            "COSYVOICE_MODEL=cosyvoice-v3-flash\n"
            "COSYVOICE_DEFAULT_VOICE=longanyang\n"
            "COSYVOICE_PUBLIC_BASE_URL=https://voice.ponychat.org/cosyvoice\n"
            "ENV\n"
            "chmod 600 /etc/ponychat/cosyvoice.env\n"
        )

    service = r"""cat > /etc/systemd/system/ponychat-cosyvoice.service <<'UNIT'
[Unit]
Description=PonyChat CosyVoiceTTS
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/ponychat-cosyvoice
EnvironmentFile=-/etc/ponychat/cosyvoice.env
ExecStart=/opt/ponychat-cosyvoice/.venv/bin/uvicorn app_cosyvoice:app --host 127.0.0.1 --port 18010
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
"""

    nginx = r"""cat > /etc/nginx/sites-available/voice.ponychat.org <<'NGINX'
server {
    listen 80;
    server_name voice.ponychat.org;
    location ^~ /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 127.0.0.1:8443 ssl;
    server_name voice.ponychat.org;

    ssl_certificate /etc/letsencrypt/live/voice.ponychat.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/voice.ponychat.org/privkey.pem;
    client_max_body_size 20m;

    location = / { return 302 https://voice.ponychat.org/cosyvoice/; }
    location = /qwen3tts { return 301 https://voice.ponychat.org/cosyvoice/; }
    location ^~ /qwen3tts/ { return 301 https://voice.ponychat.org/cosyvoice/; }
    location = /omnivoice { return 410; }
    location ^~ /omnivoice/ { return 410; }

    location = /cosyvoice { return 301 https://voice.ponychat.org/cosyvoice/; }
    location ^~ /cosyvoice/ {
        proxy_pass http://127.0.0.1:18010/cosyvoice/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 180s;
    }

    location ^~ /assets/ { proxy_pass http://127.0.0.1:18010/assets/; }
    location ^~ /logo/ { proxy_pass http://127.0.0.1:18010/logo/; }
}

server {
    listen 154.17.23.237:8443 ssl;
    server_name 154.17.23.237;

    ssl_certificate /etc/letsencrypt/live/voice.ponychat.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/voice.ponychat.org/privkey.pem;
    return 301 https://voice.ponychat.org$request_uri;
}
NGINX
ln -sf /etc/nginx/sites-available/voice.ponychat.org /etc/nginx/sites-enabled/voice.ponychat.org
"""

    post_commands = [
        "set -euo pipefail",
        "cd /opt/ponychat-cosyvoice",
        "python3 -m venv .venv",
        ".venv/bin/python -m pip install --upgrade pip >/dev/null",
        ".venv/bin/python -m pip install fastapi 'uvicorn[standard]' httpx pydantic python-multipart >/dev/null",
        env_setup,
        service,
        nginx,
        "systemctl daemon-reload",
        "systemctl enable --now ponychat-cosyvoice.service",
        "systemctl restart ponychat-cosyvoice.service",
        "nginx -t",
        "systemctl reload nginx",
        "systemctl --no-pager --plain status ponychat-cosyvoice.service | sed -n '1,12p'",
    ]

    with stage_files(files, dirs=[(static / "logo", "static/logo")]) as tmp:
        deploy_tree(
            local_dir=Path(tmp),
            target_kind="server",
            target_name="usa",
            remote_dir="/opt/ponychat-cosyvoice",
            label="CosyVoiceTTS",
            post_commands=post_commands,
        )


if __name__ == "__main__":
    main()
