#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 Main/frontend/dist 打包为 tar.gz 后上传至 Server-USA，并安装 nginx-ponychat-www.conf（静态站）。

连接参数从 ServerKeys/servers.json 中 servers.usa 条目读取（host/port/user/key）。

用法（PonyChat 仓库根）：
  python PonyChat-Website/Main/deploy/server-usa/deploy_static_web_now.py

环境变量（可选）：
  PONYCHAT_USA_HOST  覆盖目标 IP/域名
  PONYCHAT_USA_KEY   覆盖私钥路径
"""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import io
from pathlib import Path

# Windows 控制台统一 UTF-8，避免 Cursor/PowerShell 中中文步骤名乱码。
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
else:
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        pass

# 本脚本路径：PonyChat/PonyChat-Website/Main/deploy/server-usa/ → parents[4] 为 PonyChat 仓库根；ServerKeys 与其同级（如 P:/ServerKeys）
_PONYCHAT_ROOT = Path(__file__).resolve().parents[4]
_SERVERKEYS    = _PONYCHAT_ROOT.parent / "ServerKeys"
if str(_SERVERKEYS) not in sys.path:
    sys.path.insert(0, str(_SERVERKEYS))

import ssh_lib as _lib  # noqa: E402

REMOTE_DIR = "/var/www/ponychat-static"


def _make_tarball(dist: Path) -> Path:
    """将 dist/ 内容打包为临时 tar.gz，包内路径为 dist/*（相对 dist 本身）。"""
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tf:
        tar_path = Path(tf.name)
    with tarfile.open(tar_path, "w:gz") as tar:
        for item in dist.rglob("*"):
            if item.is_file():
                tar.add(item, arcname=str(item.relative_to(dist)))
    return tar_path


def main() -> int:
    # web_repo = Main/（其下 frontend/dist、deploy/server-usa）
    web_repo  = Path(__file__).resolve().parents[2]
    dist      = web_repo / "frontend" / "dist"
    nginx_src = web_repo / "deploy" / "server-usa" / "nginx-ponychat-www.conf"

    base_entry = _lib.load_server("usa")
    host = os.environ.get("PONYCHAT_USA_HOST", "").strip() or base_entry.host
    key  = Path(os.environ.get("PONYCHAT_USA_KEY", "").strip()) if os.environ.get("PONYCHAT_USA_KEY", "").strip() else base_entry.key

    entry = _lib.ServerEntry(
        name="usa-ponychat",
        host=host,
        port=base_entry.port,
        user=base_entry.user,
        key=key,
        label="TheServerUSA (PonyChat static)",
    )

    if not dist.is_dir() or not (dist / "index.html").is_file():
        print("请先执行: cd PonyChat-Website/Main/frontend && npm run build", file=sys.stderr)
        return 1
    if not nginx_src.is_file():
        print("缺少", nginx_src, file=sys.stderr)
        return 1
    if not entry.key.is_file():
        print("缺少私钥", entry.key, file=sys.stderr)
        return 1

    print("[1/4] 打包 dist/ → tar.gz …")
    tar_path = _make_tarball(dist)
    size_kb = tar_path.stat().st_size // 1024
    print(f"  压缩包：{tar_path}  ({size_kb} KB)", flush=True)

    print("[2/4] 上传压缩包并解压 …")
    rc = _lib.scp_to(entry, tar_path, "/tmp/ponychat-static.tar.gz")
    tar_path.unlink(missing_ok=True)
    if rc != 0:
        print("scp 失败:", rc, file=sys.stderr)
        return rc

    rc = _lib.ssh_bash_s(entry, "\n".join([
        "set -e",
        f"rm -rf {REMOTE_DIR}",
        f"mkdir -p {REMOTE_DIR} /var/www/html",
        f"tar -xzf /tmp/ponychat-static.tar.gz -C {REMOTE_DIR}/",
        "rm -f /tmp/ponychat-static.tar.gz",
        f"find {REMOTE_DIR} -type d -exec chmod 755 {{}} \\;",
        f"find {REMOTE_DIR} -type f -exec chmod 644 {{}} \\;",
        "echo '[done] 解压完成'",
    ]))
    if rc != 0:
        print("远端解压失败:", rc, file=sys.stderr)
        return rc

    print("[3/4] 安装 Nginx 配置 …")
    rc = _lib.scp_to(entry, nginx_src, "/tmp/ponychat-www.conf")
    if rc != 0:
        print("scp nginx 失败:", rc, file=sys.stderr)
        return rc

    rc = _lib.ssh_bash_s(entry, "\n".join([
        "set -e",
        "install -m 0644 /tmp/ponychat-www.conf /etc/nginx/sites-available/ponychat-www",
        "ln -sf /etc/nginx/sites-available/ponychat-www /etc/nginx/sites-enabled/ponychat-www",
        "rm -f /tmp/ponychat-www.conf",
        "nginx -t",
        "systemctl reload nginx",
        "echo '[done] nginx reload OK'",
    ]))
    if rc != 0:
        print("远端 nginx 安装失败:", rc, file=sys.stderr)
        return rc

    print("[4/4] 远端 HTTPS 探活（127.0.0.1:8443）…")
    _lib.ssh_exec(
        entry,
        "curl -skI --resolve www.ponychat.org:8443:127.0.0.1 "
        "https://www.ponychat.org:8443/ | head -5",
    )
    _lib.ssh_exec(
        entry,
        "curl -skI --resolve drive.ponychat.org:8443:127.0.0.1 "
        "https://drive.ponychat.org:8443/ | head -5",
    )

    print(
        "\n完成。请确认 Server-USA /etc/nginx/nginx.conf 内 stream map 含 "
        "www.ponychat.org、ponychat.org 与 drive.ponychat.org → 127.0.0.1:8443"
        "（见 PonyChat-Website/Main/deploy/server-usa/DEPLOY-STATIC-WEB.md）。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
