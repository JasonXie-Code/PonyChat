# -*- coding: utf-8 -*-
import sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import refine_pages as m
from pathlib import Path

tags_by_file = {
    t["file"]: t
    for t in m.load_tags()
}

test_files = [
    "暮光闪闪.txt",       # major character
    "云中城.txt",         # major location
    "忘形之交.txt",       # episode
    "天马.txt",           # race
    "可爱标记_获得途径.txt",  # concept
]

for fname in test_files:
    tag = tags_by_file.get(fname)
    if not tag:
        print(f"[无标记] {fname}")
        continue
    src = m.CLEAN_DIR / fname
    raw = src.read_text(encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"文件: {fname}  类型:{tag['type']}  重要度:{tag.get('importance','')}  目标:{tag['target_words']}字")
    print("─"*60)
    result = m.refine_page(tag, raw)
    # 打印前 60 行
    lines = result.splitlines()
    for line in lines[:60]:
        print(line)
    if len(lines) > 60:
        print(f"... 共{len(lines)}行，实际字数约{len(result)}字")
    print()
