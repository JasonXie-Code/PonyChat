# -*- coding: utf-8 -*-
"""
统计 + 删除 mlp_vectors.db 中 EQG / 人类世界相关条目，并从 aliases.json 移除对应别名。

判断条件（满足任意一条即删除）：
  1. cn_name 含 "(EG)" / "（EG）" / "小马国女孩" / "人类" / "坎特拉高中"
  2. filename 含 "(EG)" / "（EG）" / "EG）" / "Equestria Girls" / "Canterlot High"
  3. doc_type == "eg_character"
  4. content 开头含 "《小马国女孩" / "坎特拉预科学院" 且 doc_type == "character"（不误删地点）
"""
import sys, re, json, sqlite3, shutil
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import MLP_DIR, DB_PATH, ALIASES_PATH

ALIASES_F   = ALIASES_PATH
REFINED_DIR = MLP_DIR / "refined"

# ── 判断是否为 EG 条目 ──────────────────────────────────────────────────────
EG_PATTERNS = [
    r"\(EG\)",
    r"（EG）",
    r"小马国女孩",
    r"人类\s*(暮光|云宝|苹果|萍琪|瑞瑞|小蝶|崔克茜|余晖|午夜闪闪)",
    r"坎特拉(高中|预科学院|中学)",
    r"Equestria.Girls",
    r"Canterlot.High",
    r"EQG",
]
EG_RE = re.compile("|".join(EG_PATTERNS), re.IGNORECASE)

def is_eg(filename: str, cn_name: str, doc_type: str, content: str) -> bool:
    for text in (filename, cn_name):
        if text and EG_RE.search(text):
            return True
    if doc_type == "eg_character":
        return True
    # 内容开头含 EG 特征
    head = (content or "")[:300]
    if EG_RE.search(head):
        return True
    return False

# ── 连接 DB，扫描 ──────────────────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
rows = conn.execute(
    "SELECT id, filename, cn_name, doc_type, content FROM mlp_knowledge"
).fetchall()

to_delete = []
for row_id, fname, cn_name, doc_type, content in rows:
    if is_eg(fname, cn_name or "", doc_type or "", content or ""):
        to_delete.append((row_id, fname, cn_name))

print(f"扫描 {len(rows)} 条，发现 EG 条目 {len(to_delete)} 个：")
for _, fname, cn_name in to_delete[:60]:
    print(f"  {fname}  |  {cn_name}")
if len(to_delete) > 60:
    print(f"  ...（共 {len(to_delete)} 条）")

ans = input(f"\n确认删除 {len(to_delete)} 条？(y/n): ").strip().lower()
if ans != "y":
    print("已取消")
    conn.close()
    sys.exit(0)

# ── 删除 DB 条目 + FTS5 条目 ───────────────────────────────────────────────
ids = [r[0] for r in to_delete]
fnames = {r[1] for r in to_delete}

conn.execute(f"DELETE FROM mlp_knowledge WHERE id IN ({','.join('?'*len(ids))})", ids)

# FTS5 同步删除
for fname in fnames:
    try:
        conn.execute("DELETE FROM mlp_fts WHERE filename = ?", (fname,))
    except Exception:
        pass

conn.commit()

remaining = conn.execute("SELECT COUNT(*) FROM mlp_knowledge").fetchone()[0]
conn.close()
print(f"✔ 已删除 {len(to_delete)} 条，剩余 {remaining} 条")

# ── 从 aliases.json 移除指向被删条目的别名 ──────────────────────────────────
data = json.loads(ALIASES_F.read_text(encoding="utf-8"))
# 找出被删条目的 cn_name 片段
deleted_cn = {cn for _, _, cn in to_delete if cn}

# EG 别名关键词（值中含这些词的也删）
EG_ALIAS_RE = re.compile(
    r"人类|EG|小马国女孩|午夜闪闪|Sci.Twi|Midnight.Sparkle|Canterlot.High",
    re.IGNORECASE
)

removed_aliases = []
new_data = {}
for k, v in data.items():
    if k.startswith("_") or k.startswith("──"):
        new_data[k] = v
        continue
    # 值指向被删条目，或别名/值本身含 EG 关键词
    if any(cn in v for cn in deleted_cn) or EG_ALIAS_RE.search(k) or EG_ALIAS_RE.search(v):
        removed_aliases.append((k, v))
    else:
        new_data[k] = v

ALIASES_F.write_text(json.dumps(new_data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✔ aliases.json 移除 {len(removed_aliases)} 条别名：")
for k, v in removed_aliases:
    print(f"  「{k}」→「{v}」")
print("完成。")
