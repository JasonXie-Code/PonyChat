#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 MBTI/MLP/web/dist 打包为 tar.gz 后上传到 Server-USA（mbti.ponychat.org）。

远端存在两套历史路径，任一生效时都应读到同一套构建，故部署后会在服务器上镜像两份：
  - /var/www/mbti-ponychat-static  — nginx-ponychat-www.conf 子域 server 块
  - /var/www/mbti                  — 旧版 misc/nginx-mbti.ponychat.org.conf / deploy.ps1 默认

连接参数从 ServerKeys/servers.json 的 servers.usa 读取。

用法（在 MBTI/MLP 目录）:
  cd web && npm run build && cd .. && python misc/deploy_mbti_server_usa.py

环境变量（可选）:
  PONYCHAT_SERVERKEYS  ssh_lib 与 servers.json 所在目录（默认见 ServerKeys.md：P:\\ServerKeys）
  PONYCHAT_USA_HOST    覆盖目标 IP/域名
  PONYCHAT_USA_KEY     覆盖私钥路径
"""

from __future__ import annotations

import os
import sys
import tarfile
import tempfile
from pathlib import Path

_MBTI_ROOT = Path(__file__).resolve().parents[1]  # MBTI/MLP


def _serverkeys_dir() -> Path:
    """与仓库根目录 ServerKeys.md 一致：密钥在 P:\\ServerKeys，与代码分离。"""
    env = os.environ.get("PONYCHAT_SERVERKEYS", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    p_drive = Path("P:/ServerKeys")
    if p_drive.is_dir():
        return p_drive.resolve()
    # PonyChat/PonyChat-Website/MBTI/MLP → 上溯至工作区根，与仓库根同级的 ServerKeys/
    return (_MBTI_ROOT.parent.parent.parent.parent / "ServerKeys").resolve()


_SERVERKEYS = _serverkeys_dir()
if str(_SERVERKEYS) not in sys.path:
    sys.path.insert(0, str(_SERVERKEYS))

import ssh_lib as _lib  # noqa: E402

# 主上传目标（与 PonyChat-Website nginx-ponychat-www.conf 一致）
REMOTE_PRIMARY = "/var/www/mbti-ponychat-static"
# 与旧 Nginx / deploy.ps1 一致，由远端 cp -a 镜像，避免只更新一份时公网仍读旧目录
REMOTE_LEGACY  = "/var/www/mbti"
LOCAL_DIST     = _MBTI_ROOT / "web" / "dist"


def _make_tarball(dist: Path) -> Path:
    """将 dist/ 内容打包为临时 tar.gz。"""
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tf:
        tar_path = Path(tf.name)
    with tarfile.open(tar_path, "w:gz") as tar:
        for item in dist.rglob("*"):
            if item.is_file():
                tar.add(item, arcname=str(item.relative_to(dist)))
    return tar_path


def main() -> int:
    if not LOCAL_DIST.is_dir() or not (LOCAL_DIST / "index.html").is_file():
        print(f"请先执行: cd web && npm run build  （期望 {LOCAL_DIST}/index.html）", file=sys.stderr)
        return 1

    base_entry = _lib.load_server("usa")
    host = os.environ.get("PONYCHAT_USA_HOST", "").strip() or base_entry.host
    key = (
        Path(os.environ.get("PONYCHAT_USA_KEY", "").strip())
        if os.environ.get("PONYCHAT_USA_KEY", "").strip()
        else base_entry.key
    )

    entry = _lib.ServerEntry(
        name="usa-mbti",
        host=host,
        port=base_entry.port,
        user=base_entry.user,
        key=key,
        label="TheServerUSA (mbti.ponychat.org static)",
    )

    if not entry.key.is_file():
        print("缺少私钥", entry.key, file=sys.stderr)
        return 1

    print("[1/3] 打包 dist/ → tar.gz …")
    tar_path = _make_tarball(LOCAL_DIST)
    size_kb = tar_path.stat().st_size // 1024
    print(f"  压缩包：{tar_path}  ({size_kb} KB)", flush=True)

    print(f"[2/3] 上传并解压 → {REMOTE_PRIMARY} …")
    rc = _lib.scp_to(entry, tar_path, "/tmp/mbti-static.tar.gz")
    tar_path.unlink(missing_ok=True)
    if rc != 0:
        print("scp 失败:", rc, file=sys.stderr)
        return rc

    rc = _lib.ssh_bash_s(entry, "\n".join([
        "set -e",
        f"rm -rf {REMOTE_PRIMARY}",
        f"mkdir -p {REMOTE_PRIMARY}",
        f"tar -xzf /tmp/mbti-static.tar.gz -C {REMOTE_PRIMARY}/",
        "rm -f /tmp/mbti-static.tar.gz",
        f"find {REMOTE_PRIMARY} -type d -exec chmod 755 {{}} \\;",
        f"find {REMOTE_PRIMARY} -type f -exec chmod 644 {{}} \\;",
        "echo '[done] 解压完成'",
    ]))
    if rc != 0:
        print("远端解压失败:", rc, file=sys.stderr)
        return rc

    print(f"[3/3] 镜像 → {REMOTE_LEGACY}（对齐旧 Nginx root）…")
    rc = _lib.ssh_exec(
        entry,
        f"rm -rf {REMOTE_LEGACY} && "
        f"cp -a {REMOTE_PRIMARY} {REMOTE_LEGACY} && "
        f"find {REMOTE_LEGACY} -type d -exec chmod 755 {{}} \\; && "
        f"find {REMOTE_LEGACY} -type f -exec chmod 644 {{}} \\;",
    )
    if rc != 0:
        print("镜像到旧目录失败:", rc, file=sys.stderr)
        return rc

    print(
        f"\n完成。已同步 {LOCAL_DIST}\n"
        f"  → {entry.user}@{entry.host}:{REMOTE_PRIMARY}\n"
        f"  → {REMOTE_LEGACY}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
