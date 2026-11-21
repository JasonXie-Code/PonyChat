# -*- coding: utf-8 -*-
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
    "两姐妹的城堡.txt",
    "云中城.txt",
    "友谊城堡.txt",
    "可爱标记_获得途径.txt",
    "彩虹卷发.txt",
    "彩虹飞跃.txt",
    "苹果杰克.txt",
    "暮光闪闪（EG）.txt",
]

for fname in test_files:
    path = m.CLEAN_DIR / fname
    if not path.exists():
        # 模糊匹配
        candidates = list(m.CLEAN_DIR.glob(fname.replace(".txt", "*.txt")))
        if candidates:
            path = candidates[0]
            fname = path.name
        else:
            print(f"[不存在] {fname}")
            continue
    text = path.read_text(encoding="utf-8")
    tag = m.tag_page(path.name, text[:800])
    skip_info = ("  跳过:" + tag["skip_reason"]) if tag["skip"] else ""
    print(f"{fname:35s}  {tag['type']:10s} {tag.get('importance',''):12s} {tag['target_words']}字{skip_info}")
