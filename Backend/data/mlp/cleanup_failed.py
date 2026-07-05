# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

refined = Path(__file__).parent / "refined"
deleted = 0
for f in list(refined.glob("*.txt")):
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
        if "改写失败" in text:
            f.unlink()
            deleted += 1
    except Exception as e:
        print(f"  跳过 {f.name}: {e}")

remaining = len(list(refined.glob("*.txt")))
print(f"删除 {deleted} 个失败文件，剩余 {remaining} 个有效文件")
