# -*- coding: utf-8 -*-
import sys, json; sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

tags = {}
for l in Path("tags.jsonl").read_text(encoding="utf-8").splitlines():
    if l.strip():
        t = json.loads(l)
        tags[t["file"]] = t

for name in ["碧琪.txt", "萍琪派.txt"]:
    t = tags.get(name, {})
    print(f"[标记] {name}: type={t.get('type')} cn={t.get('cn_name')} skip={t.get('skip')}")
    clean_f = Path("clean") / name
    refined_f = Path("refined") / name
    print(f"  clean:   {'存在 '+str(clean_f.stat().st_size)+'B' if clean_f.exists() else '不存在'}")
    print(f"  refined: {'存在' if refined_f.exists() else '不存在'}")
