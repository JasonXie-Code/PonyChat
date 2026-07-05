# -*- coding: utf-8 -*-
import sys, json, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import refine_pages as m
from pathlib import Path

tags_map = {t["file"]: t for t in m.load_tags()}

test_files = [
    "暮光闪闪.txt",       # major character 2000字
    "苹果杰克.txt",       # major character
    "Ace Point.txt",      # background character 500字
    "云中城.txt",         # major location 1000字
    "天马.txt",           # race
    "不泯童心.txt",       # episode
    "可爱标记_获得途径.txt",  # concept
    "友谊元素.txt",       # concept（若存在）
    "A True, True Friend.txt",  # song
    "Frago.txt",          # 之前失败的
]

ok_count = 0
for fname in test_files:
    tag = tags_map.get(fname)
    if not tag:
        print(f"[无标记] {fname}")
        continue
    if tag.get("skip"):
        print(f"[skip]  {fname}")
        continue

    t0 = time.time()
    fname_out, status, ok = m.process_tag(tag)
    elapsed = time.time() - t0
    flag = "✓" if ok else "✗"
    print(f"{flag} {elapsed:5.1f}s  {fname[:40]:40s}  {status}")
    if ok:
        ok_count += 1
        # 打印改写后内容的前 6 行
        dst = m.REFINED_DIR / fname
        if dst.exists():
            lines = dst.read_text(encoding="utf-8").splitlines()
            for line in lines[:6]:
                print(f"       {line}")
            print()

print(f"\n结果: {ok_count}/{len(test_files)} 成功")
