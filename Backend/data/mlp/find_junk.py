# -*- coding: utf-8 -*-
import sys, sqlite3
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import DB_PATH

conn = sqlite3.connect(str(DB_PATH))
rows = conn.execute("SELECT filename, cn_name, doc_type, LENGTH(content), content FROM mlp_knowledge").fetchall()

junk_patterns = [
    "你提供的原始内容",
    "无法完成",
    "没有实际的剧情",
    "无法为你生成",
    "请补充完整",
    "仅包含该作品的基础发行信息",
    "无法改写",
    "缺少具体内容",
]

print("=== 疑似 LLM 拒绝/空内容条目 ===\n")
junk_list = []
for fname, cn_name, doc_type, length, content in rows:
    for pat in junk_patterns:
        if pat in content:
            junk_list.append((fname, cn_name, doc_type, length, content[:150]))
            break

print(f"共 {len(junk_list)} 条疑似垃圾\n")
for fname, cn_name, doc_type, length, preview in junk_list:
    print(f"  [{doc_type:>10}] {cn_name:<30} ({length} 字)")
    print(f"            {preview.replace(chr(10), ' ')}")
    print()

# 也看一下极短内容（<100字）的条目
short = [(f, cn, dt, l) for f, cn, dt, l, c in rows if l < 100]
print(f"=== 内容 < 100 字的条目：{len(short)} 条 ===\n")
for fname, cn_name, doc_type, length in short[:20]:
    print(f"  [{doc_type:>10}] {cn_name:<30} ({length} 字)")

conn.close()
