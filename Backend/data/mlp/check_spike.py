# -*- coding: utf-8 -*-
import sys, sqlite3
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from mlp_paths import DB_PATH

conn = sqlite3.connect(str(DB_PATH))
rows = conn.execute(
    "SELECT cn_name, doc_type, content FROM mlp_knowledge WHERE cn_name LIKE '%斯派克%'"
).fetchall()
for r in rows:
    print("cn_name :", r[0])
    print("doc_type:", r[1])
    print("内容前300字:")
    print(r[2][:300])
    print("---")
conn.close()
