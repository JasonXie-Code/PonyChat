# -*- coding: utf-8 -*-
"""data/mlp 目录内脚本共用路径（相对本文件所在目录，勿写死盘符）。"""
import sys
from pathlib import Path

MLP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = MLP_DIR.parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Backend.runtime_paths import resolve_mlp_vector_db_path

DB_PATH = Path(resolve_mlp_vector_db_path(str(BACKEND_DIR)))
ALIASES_PATH = MLP_DIR / "aliases.json"
