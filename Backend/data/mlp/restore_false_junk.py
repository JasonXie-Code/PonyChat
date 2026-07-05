# -*- coding: utf-8 -*-
"""恢复被误判为垃圾的有效条目（内容 ≥ 500 字的不是垃圾）"""
import sys, shutil, json, sqlite3, struct, os, time
import numpy as np
import requests
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import MLP_DIR, DB_PATH

SRC  = MLP_DIR / "refined"
DST  = MLP_DIR / "refined_pony"
DB   = DB_PATH
TAGS = MLP_DIR / "tags.jsonl"

JUNK_PATTERNS = [
    "你提供的原始内容", "无法完成", "没有实际的剧情", "无法为你生成",
    "请补充完整", "仅包含该作品的基础发行信息", "无法改写", "缺少具体内容",
    "无法按照要求完成", "无法生成符合要求", "缺少完整的剧情", "请你补充完整",
    "当前提供的内容仅包含", "并非《我的小马驹：友谊就是魔法》的官方角色",
]

MIN_VALID_LENGTH = 500

tag_map = {}
with open(TAGS, encoding="utf-8", errors="replace") as f:
    for line in f:
        try:
            d = json.loads(line.strip())
            tag_map[d["file"]] = d
        except Exception:
            pass

# 找出 refined/ 中被删但内容够长的文件
false_junk = []
for fp in sorted(SRC.glob("*.txt")):
    if (DST / fp.name).exists():
        continue
    content = fp.read_text(encoding="utf-8", errors="replace")
    has_pattern = any(p in content for p in JUNK_PATTERNS)
    if has_pattern and len(content) >= MIN_VALID_LENGTH:
        false_junk.append(fp)
        print(f"  需恢复: {fp.name} ({len(content)} 字)")

print(f"\n共 {len(false_junk)} 个误判文件需要恢复")
if not false_junk:
    print("无需恢复")
    sys.exit(0)

# 复制回 refined_pony/
for fp in false_junk:
    shutil.copy2(fp, DST / fp.name)
print(f"✔ 已复制 {len(false_junk)} 个文件到 refined_pony/")

# 重新向量化入库
API_KEY = os.environ.get("PONYCHAT_DASHSCOPE_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
if not API_KEY:
    raise RuntimeError("Set PONYCHAT_DASHSCOPE_API_KEY or DASHSCOPE_API_KEY before embedding restored files.")
EMBED_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"

def embed(text: str) -> list[float]:
    for attempt in range(3):
        try:
            r = requests.post(EMBED_URL, headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            }, json={
                "model": "text-embedding-v3",
                "input": [text[:6000]],
                "dimensions": 1024,
                "encoding_format": "float",
            }, timeout=15)
            if r.status_code == 200:
                return r.json()["data"][0]["embedding"]
        except Exception:
            pass
        time.sleep(1 * (attempt + 1))
    return None

def vec_to_blob(v):
    return struct.pack(f"{len(v)}f", *v)

conn = sqlite3.connect(DB)
ok = 0
for fp in false_junk:
    content = fp.read_text(encoding="utf-8", errors="replace")
    meta = tag_map.get(fp.name, {})
    cn_name = meta.get("cn_name", fp.stem)
    doc_type = meta.get("type", "")
    importance = meta.get("importance", "")

    vec = embed(content[:6000])
    if vec is None:
        print(f"  ✗ 向量化失败: {fp.name}")
        continue
    blob = vec_to_blob(vec)
    conn.execute(
        "INSERT OR REPLACE INTO mlp_knowledge (filename, cn_name, doc_type, importance, content, embedding) VALUES (?,?,?,?,?,?)",
        (fp.name, cn_name, doc_type, importance, content, blob)
    )
    # FTS 全文检索
    search_text = cn_name + "\n" + content
    conn.execute(
        "INSERT INTO mlp_fts (filename, cn_name, doc_type, importance, search_text) VALUES (?,?,?,?,?)",
        (fp.name, cn_name, doc_type, importance, search_text)
    )
    ok += 1
    print(f"  ✔ 已恢复: {cn_name} ({fp.name})")

conn.commit()
total = conn.execute("SELECT COUNT(*) FROM mlp_knowledge").fetchone()[0]
print(f"\n✔ 恢复完成：{ok}/{len(false_junk)} 成功，数据库现有 {total} 条")
conn.close()
