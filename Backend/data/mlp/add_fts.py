# -*- coding: utf-8 -*-
"""
给 mlp_vectors.db 追加一张 FTS5 全文检索表 mlp_fts，
内容 = cn_name + content（向量表已有的数据直接同步，无需重新请求 API）。

用法：
    python add_fts.py
可反复执行，已存在时先删后建以保持同步。
"""
import sys, sqlite3
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import DB_PATH

conn = sqlite3.connect(str(DB_PATH))

# 删除旧 FTS 表（如果存在）
conn.execute("DROP TABLE IF EXISTS mlp_fts")
conn.commit()

# 建 FTS5 表：tokenize=unicode61 支持中文按字分词
# 注意：不加 content='' ，让 FTS5 自行存储数据（正常模式）
conn.execute("""
    CREATE VIRTUAL TABLE mlp_fts USING fts5(
        filename UNINDEXED,
        cn_name   UNINDEXED,
        doc_type  UNINDEXED,
        importance UNINDEXED,
        search_text,
        tokenize='unicode61'
    )
""")

# 从 mlp_knowledge 同步数据
# search_text = cn_name + "\n" + content（让 cn_name 被单独权重更高地检索）
rows = conn.execute(
    "SELECT filename, cn_name, doc_type, importance, content FROM mlp_knowledge"
).fetchall()

data = []
for fname, cn_name, doc_type, importance, content in rows:
    search_text = f"{cn_name or ''}\n{content or ''}"
    data.append((fname, cn_name or "", doc_type or "", importance or "", search_text))

conn.executemany(
    "INSERT INTO mlp_fts(filename, cn_name, doc_type, importance, search_text)"
    " VALUES (?,?,?,?,?)",
    data,
)
conn.commit()
conn.close()

print(f"FTS5 表建立完成，共 {len(data)} 条记录。")
print("测试查询：")

# 快速验证
conn2 = sqlite3.connect(DB_PATH)
for kw in ["碧琪", "彩虹黛茜", "彩虹", "苹果杰克", "暮光闪闪"]:
    results = conn2.execute(
        "SELECT filename, cn_name FROM mlp_fts WHERE search_text MATCH ? LIMIT 3",
        (kw,),
    ).fetchall()
    names = [r[1] for r in results]
    print(f"  「{kw}」→ {names if names else '无结果'}")
conn2.close()
