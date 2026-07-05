# -*- coding: utf-8 -*-
"""SSH 远端检查 HTTPS / Nginx / 证书（需 ServerKeys 与 usa 密钥）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent.parent.parent / "ServerKeys"))

from ssh_lib import deploy_upload_env, load_server, ssh_bash_s  # noqa: E402

SCRIPT = r"""set -euo pipefail
echo "=== hostname ==="
hostname
echo "=== ss :443 :80 ==="
ss -tlnp 2>/dev/null | grep -E ':443|:80' || echo "(no match)"
echo "=== certbot certificates ==="
certbot certificates 2>&1 || true
echo "=== ls /etc/letsencrypt/live ==="
ls -la /etc/letsencrypt/live/ 2>&1 || echo "missing"
echo "=== head mlp-music nginx ==="
head -70 /etc/nginx/sites-available/mlp-music 2>&1 || true
echo "=== nginx -t ==="
nginx -t 2>&1
echo "=== curl https 127.0.0.1 ==="
curl -skI --connect-timeout 5 "https://127.0.0.1/" -H "Host: music.ponychat.org" 2>&1 | head -20 || true
echo "=== openssl s_client ==="
echo | timeout 8 openssl s_client -connect 127.0.0.1:443 -servername music.ponychat.org 2>&1 | head -35 || true
echo "=== curl from server to public https ==="
curl -sS -I --connect-timeout 12 "https://music.ponychat.org/" 2>&1 | head -25 || true
echo "=== openssl x509 SAN (music) ==="
openssl x509 -in /etc/letsencrypt/live/music.ponychat.org/fullchain.pem -noout -text 2>/dev/null | grep -A3 "Subject Alternative" || true
echo "=== grep listen 443 sites-enabled ==="
grep -r "listen.*443" /etc/nginx/sites-enabled/ 2>/dev/null || true
echo "=== tail error.log ==="
tail -20 /var/log/nginx/error.log 2>/dev/null || true
echo "=== index.html ==="
ls -la /var/www/mlp-music/index.html 2>&1 || true
echo "=== all listen 443 / default_server ==="
grep -rn "listen.*443\|default_server" /etc/nginx/ 2>/dev/null | head -80
echo "=== grep 8447 18445 stream ==="
grep -rn "8447\|18445\|stream" /etc/nginx/ 2>/dev/null | head -40
echo "=== ls sites-enabled ==="
ls -la /etc/nginx/sites-enabled/
echo "=== sni-route.conf ==="
cat /etc/nginx/stream.d/sni-route.conf 2>/dev/null || true
echo "=== ss 8443 8447 ==="
ss -tlnp | grep -E '8443|8447' || true
"""

if __name__ == "__main__":
    entry = load_server("usa")
    print(f"SSH {entry.user}@{entry.host}:{entry.port} ({entry.label})\n")
    rc = ssh_bash_s(entry, SCRIPT, env=deploy_upload_env())
    sys.exit(rc)
