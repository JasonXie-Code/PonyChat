# -*- coding: utf-8 -*-
"""修正角色重要度分配"""
import sys, sqlite3
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import DB_PATH

conn = sqlite3.connect(str(DB_PATH))

FIXES = {
    # major → supporting（不属于核心主角/核心反派）
    "凝心雪儿": "supporting",
    "白胡子星璇": "supporting",
    "风暴大王": "supporting",
    
    # 重复条目检查 - 先看看有哪些
}

for cn_name, new_imp in FIXES.items():
    conn.execute("UPDATE mlp_knowledge SET importance = ? WHERE cn_name = ?", (new_imp, cn_name))
    print(f"  {cn_name}: → {new_imp}")

conn.commit()

# 检查重复的 cn_name
dupes = conn.execute(
    "SELECT cn_name, COUNT(*) as cnt, GROUP_CONCAT(filename, ' | ') "
    "FROM mlp_knowledge WHERE doc_type = 'character' "
    "GROUP BY cn_name HAVING cnt > 1"
).fetchall()

print(f"\n重复的角色条目（{len(dupes)} 组）：")
for cn_name, cnt, files in dupes:
    imp = conn.execute("SELECT importance FROM mlp_knowledge WHERE cn_name = ?", (cn_name,)).fetchone()[0]
    print(f"  {cn_name} x{cnt} [{imp}]: {files}")

# 检查所有 major 角色最终列表
print("\n最终 major 角色列表：")
majors = conn.execute(
    "SELECT cn_name, filename FROM mlp_knowledge WHERE importance = 'major' AND (doc_type = 'character' OR doc_type = '' OR doc_type IS NULL) ORDER BY cn_name"
).fetchall()
for cn_name, fname in majors:
    print(f"  {cn_name} ({fname})")

conn.close()
