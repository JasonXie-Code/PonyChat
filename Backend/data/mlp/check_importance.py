# -*- coding: utf-8 -*-
"""检查角色重要度分配是否合理"""
import sys, sqlite3
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import DB_PATH

conn = sqlite3.connect(str(DB_PATH))

# 只看 character 类型和无类型（很多角色落在无类型里）
rows = conn.execute(
    "SELECT cn_name, doc_type, importance FROM mlp_knowledge "
    "WHERE doc_type IN ('character', '') OR doc_type IS NULL "
    "ORDER BY importance, cn_name"
).fetchall()
conn.close()

# 按重要度分组
groups = {"major": [], "supporting": [], "minor": [], "background": []}
for cn_name, doc_type, imp in rows:
    tag = f" [{doc_type}]" if doc_type and doc_type != "character" else ""
    groups.get(imp, groups["background"]).append(cn_name + tag)

print("═══ major（核心角色，应为六主角+公主+大反派+关键角色）═══")
for n in sorted(groups["major"]):
    print(f"  {n}")
print(f"  共 {len(groups['major'])} 个\n")

print("═══ supporting（重要配角，应为经常出场的配角）═══")
for n in sorted(groups["supporting"]):
    print(f"  {n}")
print(f"  共 {len(groups['supporting'])} 个\n")

print("═══ minor（次要角色，出场少但有名字有剧情）═══")
for n in sorted(groups["minor"]):
    print(f"  {n}")
print(f"  共 {len(groups['minor'])} 个\n")

print(f"═══ background（背景角色）：共 {len(groups['background'])} 个（省略列表）═══")
