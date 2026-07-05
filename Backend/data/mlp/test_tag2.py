# -*- coding: utf-8 -*-
"""测试几个典型页面（角色/地点/概念）的分类效果"""
import sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

_MLP = Path(__file__).resolve().parent
_misc = _MLP.parent.parent / "misc"
sys.path.insert(0, str(_misc))
from project_paths import mlp_data_dir, resolve_project_root

import tag_pages as m

_BASE = mlp_data_dir(resolve_project_root(_MLP))
m.CLEAN_DIR = _BASE / "clean"

test_files = [
    "暮光闪闪.txt",
    "彩虹卷发.txt",
    "小马镇.txt",
    "可爱标记.txt",
    "天马.txt",
    "友谊元素.txt",
    "爱情魔法水晶.txt",
    "忘形之交.txt",       # 剧集
    "命运魔咒.txt",       # 剧集
    "威廉·安德森.txt",    # 应该 skip（真实人物）
]

for fname in test_files:
    path = m.CLEAN_DIR / fname
    if not path.exists():
        print(f"[不存在] {fname}")
        continue
    text = path.read_text(encoding="utf-8")
    tag = m.tag_page(fname, text[:800])
    skip_info = ("  !! 跳过:" + tag["skip_reason"]) if tag["skip"] else ""
    print(f"{fname:30s}  {tag['type']:10s} {tag.get('importance',''):12s} {tag['target_words']}字{skip_info}")
