import sys
sys.path.insert(0, 'P:/ServerKeys')
import ssh_lib

entry = ssh_lib.load_server('usa')
env = ssh_lib.deploy_upload_env()

# 步骤 1：给 HTTP 配置加上 acme-challenge 路径，为 certbot 做准备（暂不加 HTTPS 重定向）
step1_http_only = """server {
    listen 80;
    server_name music-auto.ponychat.org;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    root /var/www/mlp-music-auto;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8823;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /audio/ {
        alias /data/mlp-music-auto/source/audio/;
        add_header Accept-Ranges bytes;
    }
    location /scores/ {
        alias /data/mlp-music-auto/source/scores/;
        default_type application/pdf;
    }
    location /charts/ {
        alias /data/mlp-music-auto/source/charts/;
    }
    location /generated/ {
        alias /data/mlp-music-auto/generated/;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
}"""

# 步骤 1：写入临时 HTTP 配置并重载
rc = ssh_lib.ssh_bash_s(entry, f"""set -euo pipefail
mkdir -p /var/www/certbot
cat > /etc/nginx/sites-available/mlp-music-auto << 'NGINX_EOF'
{step1_http_only}
NGINX_EOF
nginx -t
systemctl reload nginx
echo "Step1: HTTP config with acme-challenge OK"
""", env=env)
if rc != 0:
    print("FAILED step1")
    raise SystemExit(rc)

# 步骤 2：申请证书
print("\n--- Step 2: certbot ---")
rc = ssh_lib.ssh_bash_s(entry, """set -euo pipefail
certbot certonly --webroot -w /var/www/certbot \
  -d music-auto.ponychat.org \
  --non-interactive --agree-tos \
  --email admin@ponychat.org 2>&1
echo "certbot exit: $?"
""", env=env)
if rc != 0:
    print("FAILED certbot - check output above")
    raise SystemExit(rc)

# 步骤 3：最终 nginx 配置（HTTP 重定向 + HTTPS at 8847）
final_config = """server {
    listen 80;
    server_name music-auto.ponychat.org;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 127.0.0.1:8847 ssl http2;
    server_name music-auto.ponychat.org;

    ssl_certificate     /etc/letsencrypt/live/music-auto.ponychat.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/music-auto.ponychat.org/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    root /var/www/mlp-music-auto;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8823;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
    location /audio/ {
        alias /data/mlp-music-auto/source/audio/;
        add_header Accept-Ranges bytes;
    }
    location /scores/ {
        alias /data/mlp-music-auto/source/scores/;
        default_type application/pdf;
    }
    location /charts/ {
        alias /data/mlp-music-auto/source/charts/;
    }
    location /generated/ {
        alias /data/mlp-music-auto/generated/;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
}"""

# 步骤 3：更新 sni-route.conf（追加 music-auto → 8847）
# 先读取当前内容，然后在 default 行之前插入
print("\n--- Step 3: update nginx config + SNI route ---")
rc = ssh_lib.ssh_bash_s(entry, f"""set -euo pipefail

# 写入最终 nginx 站点配置
cat > /etc/nginx/sites-available/mlp-music-auto << 'NGINX_EOF'
{final_config}
NGINX_EOF

# 检查 sni-route.conf 是否已经有 music-auto
if grep -q 'music-auto.ponychat.org' /etc/nginx/stream.d/sni-route.conf; then
    echo "SNI entry already exists, skipping"
else
    # 在 default 行前插入 music-auto
    sed -i '/^    default /i \\    music-auto.ponychat.org       127.0.0.1:8847;' /etc/nginx/stream.d/sni-route.conf
    echo "SNI entry added"
fi

cat /etc/nginx/stream.d/sni-route.conf

nginx -t
systemctl reload nginx
echo ""
echo "=== Step3 done: testing ==="
curl -sI http://music-auto.ponychat.org/ 2>/dev/null | head -3
curl -sk https://music-auto.ponychat.org/ 2>/dev/null | head -5 | cat
""", env=env)
if rc != 0:
    print("FAILED step3")
    raise SystemExit(rc)

print("\n=== ALL DONE ===")
