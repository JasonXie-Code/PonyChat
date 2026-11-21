# -*- coding: utf-8 -*-
"""检查 DB 现状 + 找出被误删的主线内容"""
import sys, sqlite3
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import MLP_DIR, DB_PATH

DB  = str(DB_PATH)
REF = MLP_DIR / "refined"

conn = sqlite3.connect(DB)
n = conn.execute("SELECT COUNT(*) FROM mlp_knowledge").fetchone()[0]
print(f"DB 当前 {n} 条\n")

# 检查斯派克是否还在
rows = conn.execute(
    "SELECT filename, cn_name, doc_type FROM mlp_knowledge WHERE cn_name LIKE '%斯派克%' OR cn_name LIKE '%穗龙%'"
).fetchall()
print("斯派克/穗龙相关：")
for r in rows: print(f"  {r[0]} | {r[1]} [{r[2]}]")

# 确认这三个主线条目是否被误删
misses = ["School Raze - Part 1.txt", "The Hearth's Warming Club.txt", "The Flim Flam Brothers (song).txt"]
print("\n被删的主线条目检查：")
for fname in misses:
    row = conn.execute("SELECT filename FROM mlp_knowledge WHERE filename=?", (fname,)).fetchone()
    fp = REF / fname
    in_db = row is not None
    in_refined = fp.exists()
    print(f"  {fname}: DB={'✔' if in_db else '✗'}, refined={'✔' if in_refined else '✗'}")

# 找出 refined/ 里还有哪些文件不在 DB 里（可能是其他误删）
db_files = {r[0] for r in conn.execute("SELECT filename FROM mlp_knowledge").fetchall()}
refined_files = {f.name for f in REF.glob("*.txt")}
missing_from_db = refined_files - db_files
print(f"\nrefined/ 有但 DB 无的文件：{len(missing_from_db)} 个（被删除或未导入）")

# 找出其中 filename 不含 EG 特征的（可能误删）
import re
EG_RE = re.compile(r"EG\)|（EG）|小马国女孩|Equestria.Girls|Canterlot.High", re.I)
suspicious = [f for f in missing_from_db if not EG_RE.search(f)]
print(f"其中文件名不含 EG 特征的 {len(suspicious)} 个（可能误删）：")
for f in sorted(suspicious)[:30]:
    print(f"  {f}")

conn.close()
