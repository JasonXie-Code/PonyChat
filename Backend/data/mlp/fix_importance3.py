# -*- coding: utf-8 -*-
import sys, sqlite3
from mlp_paths import DB_PATH

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

conn = sqlite3.connect(str(DB_PATH))

fixes = [
    ("云宝黛茜_图集_概览.txt", "minor", "图集版本，与主条目重复"),
    ("露娜公主_图集.txt", "minor", "图集版本，与月亮公主主条目重复"),
    ("露娜公主_图集_第一至二季.txt", "minor", "图集版本，与月亮公主主条目重复"),
    ("谐律之盒.txt", "supporting", "物品，不是角色，不应是 major"),
]

for fname, new_imp, reason in fixes:
    r = conn.execute("UPDATE mlp_knowledge SET importance = ? WHERE filename = ?", (new_imp, fname))
    old = conn.execute("SELECT cn_name, importance FROM mlp_knowledge WHERE filename = ?", (fname,)).fetchone()
    if old:
        print(f"  {old[0]} → {new_imp} ({reason})")

conn.commit()

# 最终 major 角色
print("\n═══ 最终 major 列表 ═══")
rows = conn.execute(
    "SELECT cn_name, doc_type, filename FROM mlp_knowledge WHERE importance = 'major' ORDER BY doc_type, cn_name"
).fetchall()
for cn_name, dtype, fname in rows:
    print(f"  [{dtype:>10}] {cn_name}")
print(f"\n共 {len(rows)} 条 major")

# supporting 角色数量
sup = conn.execute("SELECT COUNT(*) FROM mlp_knowledge WHERE importance='supporting' AND doc_type='character'").fetchone()[0]
print(f"supporting 角色: {sup} 个")

conn.close()
