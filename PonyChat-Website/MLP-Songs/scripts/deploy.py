# -*- coding: utf-8 -*-
"""
一键部署 MLP Music 到 Server-USA。

媒体默认先本地打成单个 .tar.gz，再 scp 上传、远端解压（比海量小文件 rsync 快得多）。
可选 --media-rsync 恢复按目录 rsync/scp。

依赖：本机 OpenSSH（ssh/scp）。ServerKeys：工作区 p:\\ServerKeys\\ssh_lib.py。

用法（在 PonyChat/PonyChat-Website/MLP-Songs 目录下）：
    python scripts/deploy.py                 # 应用 + 前端 + 索引 + 媒体（tar.gz）
    python scripts/deploy.py --no-media      # 不上传 media-export
    python scripts/deploy.py --media-rsync     # 媒体改用 rsync（若本机有 rsync）
    python scripts/deploy.py --keep-tarball  # 保留本地 dist 下打包文件
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

# 项目根：…/PonyChat-Website/MLP-Songs/；ServerKeys 与 PonyChat 仓库根同级（如 P:/ServerKeys）
ROOT = Path(__file__).resolve().parent.parent
SERVERKEYS = ROOT.parent.parent.parent / "ServerKeys"
sys.path.insert(0, str(SERVERKEYS))

from ssh_lib import deploy_upload_env, load_server, scp_to, ssh_bash_s  # noqa: E402

REMOTE_OPT = "/opt/mlp-music"
REMOTE_WWW = "/var/www/mlp-music"
REMOTE_DATA = "/data/mlp-music"
REMOTE_MEDIA_TAR = "/tmp/mlp-media-export.tar.gz"
TARBALL_NAME = "mlp-media-export.tar.gz"
SERVICE = "mlp-music.service"
DOMAIN = "music.ponychat.org"
WWW_DOMAIN = "www.music.ponychat.org"
UVICORN_PORT = 8822


def _nginx_locations_block() -> str:
    """与站点根、API、静态媒体相关的 location（HTTP/HTTPS 共用）。"""
    return f"""    root {REMOTE_WWW};
    index index.html;

    location /api/ {{
        proxy_pass http://127.0.0.1:{UVICORN_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location /audio/ {{
        alias {REMOTE_DATA}/audio/;
        add_header Accept-Ranges bytes;
    }}
    location /scores/ {{
        alias {REMOTE_DATA}/scores/;
        add_header Accept-Ranges bytes;
        default_type application/pdf;
    }}
    location /covers/ {{
        alias {REMOTE_DATA}/covers/;
    }}
    location /charts/ {{
        alias {REMOTE_DATA}/charts/;
    }}

    location / {{
        try_files $uri $uri/ /index.html;
    }}"""


def _nginx_site_http_only() -> str:
    """仅 HTTP（无证书时）。"""
    loc = _nginx_locations_block()
    return f"""server {{
    listen 80;
    server_name {DOMAIN} {WWW_DOMAIN};

{loc}
}}"""


def _nginx_site_https_template() -> str:
    """HTTP 重定向 + HTTPS；证书目录由远端用 __LE_DIR__ 替换（支持 -0001 等目录名）。"""
    loc = _nginx_locations_block()
    return f"""server {{
    listen 80;
    server_name {DOMAIN} {WWW_DOMAIN};
    return 301 https://$host$request_uri;
}}

server {{
    listen 127.0.0.1:8443 ssl http2;
    server_name {DOMAIN} {WWW_DOMAIN};
    ssl_certificate __LE_DIR__/fullchain.pem;
    ssl_certificate_key __LE_DIR__/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

{loc}
}}"""


def _ensure_utf8_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


def run_local(cmd: list[str], *, timeout: int | None = 600) -> int:
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "env": deploy_upload_env(),
        "check": False,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return subprocess.run(cmd, **kwargs).returncode


def remote_setup(entry) -> int:
    """远端目录、venv、systemd、nginx。

    若服务器上已有 Let's Encrypt 证书，则写入 HTTP→HTTPS 与 443 站点，避免覆盖 certbot 后再次部署导致 HTTPS 失效。
    证书目录优先 music / www 标准名，否则取 live 下第一个含 fullchain+privkey 的目录。
    """
    http_cfg = _nginx_site_http_only()
    ssl_tmpl = _nginx_site_https_template()
    script = f"""set -euo pipefail
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv nginx rsync certbot python3-certbot-nginx

mkdir -p {REMOTE_OPT}/app/data {REMOTE_WWW} {REMOTE_DATA}/audio {REMOTE_DATA}/scores {REMOTE_DATA}/covers {REMOTE_DATA}/charts

if [ ! -d {REMOTE_OPT}/venv ]; then
  python3 -m venv {REMOTE_OPT}/venv
fi
{REMOTE_OPT}/venv/bin/pip install -q -U pip

cat > /etc/systemd/system/{SERVICE} << 'UNIT'
[Unit]
Description=MLP Music API (FastAPI)
After=network.target

[Service]
Type=simple
WorkingDirectory={REMOTE_OPT}/app
Environment=MLP_MEDIA_ROOT={REMOTE_DATA}
Environment=PATH={REMOTE_OPT}/venv/bin:/usr/bin
ExecStart={REMOTE_OPT}/venv/bin/uvicorn main:app --host 127.0.0.1 --port {UVICORN_PORT}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

pick_ssl_dir() {{
  local c d
  for c in "/etc/letsencrypt/live/{DOMAIN}" "/etc/letsencrypt/live/{WWW_DOMAIN}"; do
    if [ -f "$c/fullchain.pem" ] && [ -f "$c/privkey.pem" ]; then echo "$c"; return 0; fi
  done
  for d in /etc/letsencrypt/live/*/; do
    [ -f "${{d}}fullchain.pem" ] && [ -f "${{d}}privkey.pem" ] || continue
    echo "${{d%/}}"
    return 0
  done
  return 1
}}
SSL_DIR="$(pick_ssl_dir || true)"
if [ -n "$SSL_DIR" ]; then
  export SSL_DIR
  python3 << 'PY'
import os
ssl_dir = os.environ["SSL_DIR"]
tmpl = {repr(ssl_tmpl)}
open("/etc/nginx/sites-available/mlp-music", "w", encoding="utf-8").write(
    tmpl.replace("__LE_DIR__", ssl_dir)
)
PY
else
cat > /etc/nginx/sites-available/mlp-music <<'ENDCONF'
{http_cfg}
ENDCONF
fi

ln -sf /etc/nginx/sites-available/mlp-music /etc/nginx/sites-enabled/mlp-music
# 公网 443 由 stream SNI 转发；music 须指向本机 TLS 端口 8443（勿用 8447 空端口）
if [ -f /etc/nginx/stream.d/sni-route.conf ]; then
  sed -i '/music\\.ponychat\\.org/s/8447/8443/' /etc/nginx/stream.d/sni-route.conf || true
fi
nginx -t
systemctl daemon-reload
systemctl enable {SERVICE} || true
systemctl reload nginx || systemctl restart nginx
echo REMOTE_SETUP_OK
"""
    return ssh_bash_s(entry, script, env=deploy_upload_env())


def upload_app_web_index(entry) -> None:
    """上传 app、web、安装依赖。"""
    app_dir = ROOT / "app"
    web_dir = ROOT / "web"
    if not app_dir.is_dir():
        print(f"[ERROR] 缺少目录: {app_dir}")
        sys.exit(1)
    if not web_dir.is_dir() or not (web_dir / "index.html").is_file():
        print(f"[ERROR] 缺少前端: {web_dir / 'index.html'}")
        sys.exit(1)

    rc = ssh_bash_s(
        entry,
        f"rm -rf {REMOTE_OPT}/app",
        env=deploy_upload_env(),
    )
    if rc != 0:
        print("[WARN] 远端清理 app 目录非零退出")

    rc = scp_to(entry, app_dir, f"{REMOTE_OPT}/", recursive=True, env=deploy_upload_env())
    if rc != 0:
        print(f"[ERROR] 上传 app 失败，退出码 {rc}")
        sys.exit(rc)

    rc = ssh_bash_s(
        entry,
        f"{REMOTE_OPT}/venv/bin/pip install -q -r {REMOTE_OPT}/app/requirements.txt",
        env=deploy_upload_env(),
    )
    if rc != 0:
        print(f"[ERROR] pip install 失败 {rc}")
        sys.exit(rc)

    rc = ssh_bash_s(entry, f"rm -rf {REMOTE_WWW}/*", env=deploy_upload_env())
    rc = scp_to(entry, web_dir, f"{REMOTE_WWW}/", recursive=True, env=deploy_upload_env())
    if rc != 0:
        print(f"[ERROR] 上传 web 失败，退出码 {rc}")
        sys.exit(rc)
    # scp -r web remote/ 会在远端生成 web/ 子目录，平铺到站点根
    rc = ssh_bash_s(
        entry,
        f"if [ -d {REMOTE_WWW}/web ]; then mv {REMOTE_WWW}/web/* {REMOTE_WWW}/ && rmdir {REMOTE_WWW}/web; fi",
        env=deploy_upload_env(),
    )
    if rc != 0:
        print(f"[WARN] 平铺 web 目录退出码 {rc}")


def build_media_tarball(media: Path, out: Path) -> None:
    """将 audio/scores/covers/charts 打成 gzip  tar，顶层目录为各子目录名。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file():
        out.unlink()
    t0 = time.perf_counter()
    print(f"[pack] 正在打包 {media} -> {out} …")
    with tarfile.open(out, "w:gz", compresslevel=6) as tar:
        for name in ("audio", "scores", "covers", "charts"):
            sub = media / name
            if sub.is_dir():
                tar.add(sub, arcname=name, recursive=True)
    sec = time.perf_counter() - t0
    mb = out.stat().st_size / (1024 * 1024)
    print(f"[pack] 完成 {mb:.1f} MB，耗时 {sec:.1f}s")


def upload_media_tarball(entry, *, keep_tarball: bool) -> None:
    """打包 media-export 为单文件，scp 后远端解压到 {REMOTE_DATA}。"""
    media = ROOT / "media-export"
    if not media.is_dir():
        print(f"[WARN] 本地无 media-export: {media}，跳过媒体上传")
        return

    dist = ROOT / "dist"
    tarball = dist / TARBALL_NAME
    build_media_tarball(media, tarball)

    print(f"[deploy] scp {tarball.name} -> {entry.host}:{REMOTE_MEDIA_TAR}")
    rc = ssh_bash_s(
        entry,
        f"rm -f {REMOTE_MEDIA_TAR}",
        env=deploy_upload_env(),
    )
    if rc != 0:
        print(f"[WARN] 远端删除旧包失败 {rc}")

    rc = scp_to(entry, tarball, REMOTE_MEDIA_TAR, env=deploy_upload_env())
    if rc != 0:
        print(f"[ERROR] 上传压缩包失败 {rc}")
        sys.exit(rc)

    script = f"""set -euo pipefail
rm -rf {REMOTE_DATA}/audio {REMOTE_DATA}/scores {REMOTE_DATA}/covers {REMOTE_DATA}/charts
mkdir -p {REMOTE_DATA}
tar -xzf {REMOTE_MEDIA_TAR} -C {REMOTE_DATA}
rm -f {REMOTE_MEDIA_TAR}
echo MEDIA_EXTRACT_OK
"""
    rc = ssh_bash_s(entry, script, env=deploy_upload_env())
    if rc != 0:
        print(f"[ERROR] 远端解压失败 {rc}")
        sys.exit(rc)

    if not keep_tarball:
        try:
            tarball.unlink()
            print(f"[pack] 已删除本地 {tarball}")
        except OSError as e:
            print(f"[WARN] 无法删除本地压缩包: {e}")


def upload_media_rsync(entry) -> None:
    """按目录 rsync 或 scp（增量/无 rsync 时回退）。"""
    media = ROOT / "media-export"
    if not media.is_dir():
        print(f"[WARN] 本地无 media-export: {media}，跳过媒体上传")
        return

    rsync = shutil.which("rsync")
    key = entry.key
    target = f"{entry.user}@{entry.host}:{REMOTE_DATA}/"

    if rsync:
        ssh_part = (
            f"ssh -i {key} -p {entry.port} "
            f"-o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        )
        if os.name == "nt":
            ssh_part += " -F NUL"
        cmd = [
            "rsync",
            "-avz",
            "--progress",
            "-e",
            ssh_part,
            str(media) + "/",
            target,
        ]
        print("[deploy] rsync media-export ->", REMOTE_DATA)
        rc = run_local(cmd, timeout=None)
        if rc != 0:
            print(f"[ERROR] rsync 失败 {rc}")
            sys.exit(rc)
        return

    print("[deploy] 未找到 rsync，使用 scp -r（无断点续传）…")
    for sub in ("audio", "scores", "covers", "charts"):
        p = media / sub
        if not p.is_dir():
            continue
        ssh_bash_s(
            entry,
            f"mkdir -p {REMOTE_DATA}/{sub}",
            env=deploy_upload_env(),
        )
        rc = scp_to(entry, p, f"{REMOTE_DATA}/{sub}/", recursive=True, env=deploy_upload_env())
        if rc != 0:
            print(f"[ERROR] 上传 {sub} 失败 {rc}")
            sys.exit(rc)


def restart_service(entry) -> None:
    rc = ssh_bash_s(
        entry,
        f"systemctl restart {SERVICE} && sleep 1 && systemctl is-active {SERVICE}",
        env=deploy_upload_env(),
    )
    if rc != 0:
        print(f"[WARN] 服务重启退出码 {rc}")


def main() -> None:
    _ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="部署 MLP Music 到 Server-USA")
    ap.add_argument("--no-media", action="store_true", help="不上传 media-export")
    ap.add_argument(
        "--media-rsync",
        action="store_true",
        help="媒体不用压缩包，改用 rsync（或 scp 回退）",
    )
    ap.add_argument(
        "--keep-tarball",
        action="store_true",
        help="保留本地 dist/ 下的压缩包（默认上传成功后删除以省空间）",
    )
    args = ap.parse_args()

    entry = load_server("usa")
    print(f"目标: {entry.label} {entry.user}@{entry.host}:{entry.port}")
    print(f"域名: {WWW_DOMAIN}（若远端已有 Let's Encrypt 证书，部署将保留 HTTPS）")

    rc = remote_setup(entry)
    if rc != 0:
        print(f"[ERROR] 远端初始化失败 {rc}")
        sys.exit(rc)

    upload_app_web_index(entry)
    if not args.no_media:
        if args.media_rsync:
            upload_media_rsync(entry)
        else:
            upload_media_tarball(entry, keep_tarball=args.keep_tarball)

    restart_service(entry)
    print("\n部署完成。请确认 DNS：A 记录 music.ponychat.org / www.music.ponychat.org ->", entry.host)
    print("若无证书：certbot --nginx -d music.ponychat.org -d www.music.ponychat.org")


if __name__ == "__main__":
    main()
