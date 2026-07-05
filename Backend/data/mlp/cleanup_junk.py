# -*- coding: utf-8 -*-
"""清理向量库中 LLM 拒绝改写的垃圾条目，同时从 refined_pony/ 移除对应文件"""
import sys, sqlite3
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import MLP_DIR, DB_PATH

PONY_DIR = MLP_DIR / "refined_pony"

JUNK_PATTERNS = [
    "你提供的原始内容",
    "无法完成",
    "没有实际的剧情",
    "无法为你生成",
    "请补充完整",
    "仅包含该作品的基础发行信息",
    "无法改写",
    "缺少具体内容",
    "无法按照要求完成",
    "无法生成符合要求",
    "缺少完整的剧情",
    "请你补充完整",
    "当前提供的内容仅包含",
    "并非《我的小马驹：友谊就是魔法》的官方角色",
]

conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT id, filename, cn_name, doc_type, content FROM mlp_knowledge").fetchall()

junk_ids = []
junk_files = []
for rid, fname, cn_name, doc_type, content in rows:
    for pat in JUNK_PATTERNS:
        if pat in content:
            junk_ids.append(rid)
            junk_files.append(fname)
            print(f"  删除: [{doc_type}] {cn_name} ({fname})")
            break

print(f"\n共 {len(junk_ids)} 条垃圾")
if not junk_ids:
    print("无需清理")
    conn.close()
    sys.exit(0)

# 删除数据库
for rid in junk_ids:
    conn.execute("DELETE FROM mlp_knowledge WHERE id = ?", (rid,))
conn.commit()

# 删除 FTS
for fname in junk_files:
    conn.execute("DELETE FROM mlp_fts WHERE filename = ?", (fname,))
conn.commit()

remain = conn.execute("SELECT COUNT(*) FROM mlp_knowledge").fetchone()[0]
print(f"✔ 已从数据库删除 {len(junk_ids)} 条，剩余 {remain} 条")
conn.close()

# 从 refined_pony/ 移除
removed = 0
for fname in junk_files:
    fp = PONY_DIR / fname
    if fp.exists():
        fp.unlink()
        removed += 1
print(f"✔ 已从 refined_pony/ 移除 {removed} 个文件")
