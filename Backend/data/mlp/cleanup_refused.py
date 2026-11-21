# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

refined = Path(__file__).parent / "refined"
markers = ["不良信息", "不符合", "无法处理", "抱歉，我", "很抱歉", "我不能"]
deleted = 0
for f in list(refined.glob("*.txt")):
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
        if any(m in text for m in markers):
            print(f"  删除拒绝响应: {f.name}")
            f.unlink()
            deleted += 1
    except Exception as e:
        print(f"  跳过 {f.name}: {e}")

remaining = len(list(refined.glob("*.txt")))
print(f"共删除 {deleted} 个，剩余 {remaining} 个")
