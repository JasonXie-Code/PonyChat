#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""移动临时脚本文件"""
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = ROOT / "scripts"

files_to_move = ["organize_files.py", "整理根目录.py"]

for filename in files_to_move:
    source = ROOT / filename
    if source.exists():
        dest = SCRIPTS_DIR / filename
        try:
            shutil.move(str(source), str(dest))
            print(f"Moved: {filename} -> scripts/")
        except Exception as e:
            print(f"Error moving {filename}: {e}")

print("Done!")
