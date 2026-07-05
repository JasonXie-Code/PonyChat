# -*- coding: utf-8 -*-
import sys, sqlite3
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import MLP_DIR, DB_PATH

conn = sqlite3.connect(str(DB_PATH))
rows = conn.execute(
    "SELECT cn_name, doc_type, importance, filename FROM mlp_knowledge ORDER BY doc_type, cn_name"
).fetchall()
conn.close()

TYPE_LABELS = {
    "character": "角色",
    "episode": "剧集/漫画",
    "song": "歌曲",
    "concept": "概念/设定",
    "location": "地点",
    "item": "道具/物品",
    "race": "种族/生物",
    "skip": "其他",
    "": "未分类",
}

by_type = defaultdict(list)
for cn_name, doc_type, importance, filename in rows:
    by_type[doc_type or ""].append((cn_name, importance or "", filename))

lines = []
lines.append("# MLP 知识库条目总览")
lines.append("")
lines.append(f"> 共 **{len(rows)}** 条记录，数据来源：`mlp_vectors.db`")
lines.append("")

# 汇总表
lines.append("## 分类统计")
lines.append("")
lines.append("| 类型 | 数量 |")
lines.append("|------|------|")
for dtype in ["character", "location", "race", "concept", "item", "episode", "song", "", "skip"]:
    if dtype in by_type:
        label = TYPE_LABELS.get(dtype, dtype)
        lines.append(f"| {label} | {len(by_type[dtype])} |")
lines.append(f"| **总计** | **{len(rows)}** |")
lines.append("")

# 按类型输出详细表格
order = ["character", "location", "race", "concept", "item", "episode", "song", "", "skip"]
for dtype in order:
    if dtype not in by_type:
        continue
    label = TYPE_LABELS.get(dtype, dtype)
    items = by_type[dtype]
    lines.append(f"## {label}（{len(items)} 条）")
    lines.append("")
    lines.append("| # | 名称 | 重要度 |")
    lines.append("|---|------|--------|")
    for i, (cn_name, imp, fname) in enumerate(items, 1):
        lines.append(f"| {i} | {cn_name} | {imp} |")
    lines.append("")

output = "\n".join(lines)
with open(MLP_DIR / "knowledge_index.md", "w", encoding="utf-8") as f:
    f.write(output)
print(f"已导出 {len(rows)} 条到 knowledge_index.md")
