# -*- coding: utf-8 -*-
"""在项目根目录下启动 web 前端开发服务器（npm run dev）。"""

from __future__ import annotations

import os
import subprocess
import sys


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _prepend_shared_node_to_path(mbti_root: str) -> None:
    """优先使用仓库根 misc/tools 下的 Node（与 PonyChat 共用），便于未装全局 Node 时也能 npm run dev。"""
    # 当前目录：PonyChat/PonyChat-Website/MBTI/MLP → 上三级为 PonyChat 仓库根
    pony_root = os.path.abspath(os.path.join(mbti_root, "..", "..", ".."))
    for sub in ("node-windows-64", "node"):
        cand = os.path.join(pony_root, "misc", "tools", sub)
        node_exe = os.path.join(cand, "node.exe")
        if os.path.isfile(node_exe):
            os.environ["PATH"] = cand + os.pathsep + os.environ.get("PATH", "")
            return


def main() -> int:
    root = project_root()
    _prepend_shared_node_to_path(root)
    web = os.path.join(root, "web")
    if not os.path.isdir(web):
        print("未找到 web 目录，请确认仓库结构完整。", file=sys.stderr)
        return 1
    pkg = os.path.join(web, "package.json")
    if not os.path.isfile(pkg):
        print("未找到 web/package.json。", file=sys.stderr)
        return 1
    nm = os.path.join(web, "node_modules")
    if not os.path.isdir(nm):
        print("未检测到 web/node_modules，请先在 web 目录执行：npm install", file=sys.stderr)
        return 1
    os.chdir(web)
    if sys.platform == "win32":
        return subprocess.call("npm run dev", shell=True)
    return subprocess.call(["npm", "run", "dev"], cwd=web)


if __name__ == "__main__":
    raise SystemExit(main())
