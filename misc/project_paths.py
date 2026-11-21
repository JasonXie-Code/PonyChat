# -*- coding: utf-8 -*-
"""
便携布局：解析 PonyChat 项目根目录。

支持：
- Legacy：项目根下为 backend/、misc/、data/mlp/（知识库）等
- Deploy：backend-server/backend/、web-server/frontend/、android-local/ 等分块布局
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def resolve_repo_root(start: Optional[Path] = None) -> Path:
    """
    解析含嵌入式工具链的仓库根目录：其下存在 ``misc/tools``（jdk、android-sdk、python 等）。
    与 ``resolve_project_root`` 通常指向同一目录（PonyChat 仓库根）；本函数以 misc 为准，避免将
    ``Backend/`` 等子目录误当作根路径。
    """
    if start is None:
        start = Path.cwd()
    cur = Path(start).resolve()
    if cur.is_file():
        cur = cur.parent
    for _ in range(22):
        if (cur / "misc" / "tools").is_dir():
            return cur
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    raise RuntimeError(
        "无法定位仓库根（未找到 misc/tools）。请将嵌入式工具链放在仓库根目录 misc/tools/。"
        f" 起点: {start!s}"
    )


def resolve_project_root(start: Optional[Path] = None) -> Path:
    """
    自任意路径向上查找，直至出现 backend/conf 或 backend-server/backend/conf。
    start 默认为当前工作目录；传入 __file__ 时请先使用 Path(__file__) 的父目录（文件所在目录）。
    """
    if start is None:
        start = Path.cwd()
    cur = Path(start).resolve()
    if cur.is_file():
        cur = cur.parent
    for _ in range(18):
        # Deploy 分块：项目根下含 backend-server/backend/conf
        if (cur / "backend-server" / "backend" / "conf").is_dir():
            return cur
        # Legacy：backend/conf 或 Backend/conf（大小写/历史目录名）
        if cur.name != "backend-server" and (
            (cur / "backend" / "conf").is_dir() or (cur / "Backend" / "conf").is_dir()
        ):
            return cur
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    raise RuntimeError(
        "无法定位 PonyChat 项目根（需存在 backend/conf 或 backend-server/backend/conf）。"
        f" 起点: {start!s}"
    )


def backend_package_dir(root: Optional[Path] = None) -> Path:
    if root is None:
        root = resolve_project_root()
    d = root / "backend-server" / "backend"
    if (d / "conf").is_dir():
        return d
    d2 = root / "backend"
    if (d2 / "conf").is_dir():
        return d2
    d3 = root / "Backend"
    if (d3 / "conf").is_dir():
        return d3
    raise RuntimeError(f"在 {root} 下未找到 backend 包（缺 conf/）")


def default_database_path(root: Optional[Path] = None) -> Path:
    return backend_package_dir(root) / "database" / "ponychat.db"


def default_backup_dir(root: Optional[Path] = None) -> Path:
    return backend_package_dir(root) / "backups"


def backlogs_dir(root: Optional[Path] = None) -> Path:
    """后端导出/批处理日志等：优先 var/backlogs，否则 .BackLogs。"""
    if root is None:
        root = resolve_project_root()
    p = root / "var" / "backlogs"
    if p.is_dir():
        return p
    leg = root / ".BackLogs"
    if leg.is_dir():
        return leg
    p.mkdir(parents=True, exist_ok=True)
    return p


def chatlogs_dir(root: Optional[Path] = None) -> Path:
    """对话调试日志目录：优先 var/.chatlogs（与后端 CHATLOGS_DIR 一致），
    兼容旧路径 var/chatlogs 与 .ChatLogs。"""
    if root is None:
        root = resolve_project_root()
    p = root / "var" / ".chatlogs"
    if p.is_dir():
        return p
    leg_no_dot = root / "var" / "chatlogs"
    if leg_no_dot.is_dir():
        return leg_no_dot
    leg = root / ".ChatLogs"
    if leg.is_dir():
        return leg
    p.mkdir(parents=True, exist_ok=True)
    return p


def mlp_data_dir(root: Optional[Path] = None) -> Path:
    """
    知识库数据目录：优先 Deploy 的 backend-server/MLP_Data，
    其次 Backend/data/mlp（源码布局），再次根目录 data/mlp、MLP_Data。
    """
    if root is None:
        root = resolve_project_root()
    d = root / "backend-server" / "MLP_Data"
    if d.is_dir():
        return d
    try:
        bd = backend_package_dir(root) / "data" / "mlp"
        if bd.is_dir():
            return bd
    except RuntimeError:
        pass
    d2 = root / "data" / "mlp"
    if d2.is_dir():
        return d2
    d3 = root / "MLP_Data"
    if d3.is_dir():
        return d3
    try:
        return backend_package_dir(root) / "data" / "mlp"
    except RuntimeError:
        return root / "data" / "mlp"
