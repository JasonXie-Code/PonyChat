# -*- coding: utf-8 -*-
import sys, sqlite3
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import DB_PATH

conn = sqlite3.connect(str(DB_PATH))
rows = conn.execute(
    "SELECT cn_name, doc_type, importance, filename FROM mlp_knowledge WHERE importance = '' OR importance IS NULL ORDER BY doc_type, cn_name"
).fetchall()
conn.close()

by_type = defaultdict(list)
for cn_name, doc_type, imp, fname in rows:
    by_type[doc_type or "(无类型)"].append(cn_name)

print(f"缺少重要度的条目共 {len(rows)} 条\n")
for dtype in sorted(by_type.keys()):
    items = by_type[dtype]
    print(f"── {dtype} ({len(items)} 条) ──")
    for name in items:
        print(f"  {name}")
    print()
