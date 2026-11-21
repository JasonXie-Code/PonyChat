# -*- coding: utf-8 -*-
"""
第一步：扫描 refined/，把"纯小马世界"条目复制到 refined_pony/
第二步：删除旧向量库，从 refined_pony/ 重建

EQG/人类 判断规则（满足任意一条 → 排除）：
  A. cn_name 含 "（EG）" 或 "小马国女孩"
  B. filename 含 "(EG)" 或 "（EG）"
  C. content 前 400 字符含 "坎特拉高中" 或 "水晶预科学院"（EQG专有校名）
  D. content 里"小马国女孩"/"Equestria Girls"/"坎特拉高中" 合计出现 ≥ 3 次
     且非剧集类型（剧集里偶尔提到EG角色但主线在马界，不误删）
  E. filename 列表中确知的纯EQG内容（歌曲/电影）

注意：主线剧集即使提到"余晖烁烁"也保留；角色页只删（EG）版本。
"""
import sys, re, json, shutil, sqlite3
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import MLP_DIR, DB_PATH

SRC  = MLP_DIR / "refined"
DST  = MLP_DIR / "refined_pony"
TAGS = MLP_DIR / "tags.jsonl"
DB   = DB_PATH

# ── 加载 tags.jsonl ──────────────────────────────────────────────────────────
tag_map = {}
with open(TAGS, encoding="utf-8", errors="replace") as f:
    for line in f:
        try:
            d = json.loads(line.strip())
            tag_map[d["file"]] = d
        except Exception:
            pass

# ── EQG 检测 ─────────────────────────────────────────────────────────────────
# 确知为 EQG 专属的文件名关键词
EG_FILENAME_RE = re.compile(
    r"\(EG\)|（EG）|Equestria.Girls|Canterlot.High|CHS.Rally|CHS.Musical"
    r"|ACADECA|Rainbow.Rocks|Friendship.Games|Legend.of.Everfree"
    r"|Spring.Break|Holidays.Unwrapped|Minis",
    re.I
)

# EQG 内容关键词（出现即可怀疑）
EG_CONTENT_RE = re.compile(
    r"小马国女孩|坎特拉高中|水晶预科学院|Equestria\s*Girls|Canterlot\s*High"
    r"|CHS\s|坎特洛特高中",
    re.I
)

# cn_name 中的 EG 标记
EG_NAME_RE = re.compile(r"（EG）|\(EG\)|小马国女孩")

def is_eg(fname: str, tag: dict, content: str) -> tuple[bool, str]:
    cn_name  = tag.get("cn_name", "")
    doc_type = tag.get("type", "")
    is_ep_or_song = doc_type in ("episode", "song")

    # A: cn_name 含 EG 标记（无论类型）
    if EG_NAME_RE.search(cn_name):
        return True, f"cn_name 含 EG 标记: {cn_name}"

    # B: 文件名含明显 EQG 关键词（无论类型）
    if EG_FILENAME_RE.search(fname):
        return True, f"filename EQG 模式"

    # 剧集/歌曲仅凭 A、B 判断；不做内容扫描
    # （LLM 生成内容可能错误地把"友谊学园"写成"坎特拉高中"）
    if is_ep_or_song:
        return False, ""

    # C: 非剧集类，开头就提到 EQG 专属场景
    head = content[:400]
    if re.search(r"坎特拉高中|水晶预科学院", head):
        return True, f"开头含 EQG 校名"

    # D: 非剧集类，内容多次提到 EQG
    eg_count = len(EG_CONTENT_RE.findall(content))
    if eg_count >= 3:
        return True, f"内容含 EQG {eg_count} 次"

    return False, ""

# ── 扫描 ─────────────────────────────────────────────────────────────────────
keep, exclude = [], []
for fp in sorted(SRC.glob("*.txt")):
    content = fp.read_text(encoding="utf-8", errors="replace")
    tag = tag_map.get(fp.name, {"type": "", "cn_name": fp.stem})
    eg, reason = is_eg(fp.name, tag, content)
    if eg:
        exclude.append((fp.name, reason))
    else:
        keep.append(fp)

print(f"refined/ 共 {len(keep)+len(exclude)} 个文件")
print(f"  ✔ 保留（纯马界）: {len(keep)} 个")
print(f"  ✗ 排除（EQG/人类）: {len(exclude)} 个\n")

print("排除列表（前50）：")
for fname, reason in exclude[:50]:
    print(f"  {fname}  [{reason}]")
if len(exclude) > 50:
    print(f"  ...（共 {len(exclude)} 条）")

print(f"\n准备将 {len(keep)} 个文件复制到 refined_pony/ 并重建向量库")
ans = input("确认？(y/n): ").strip().lower()
if ans != "y":
    print("已取消")
    sys.exit(0)

# ── 复制 ─────────────────────────────────────────────────────────────────────
if DST.exists():
    shutil.rmtree(DST)
DST.mkdir()
for fp in keep:
    shutil.copy2(fp, DST / fp.name)
print(f"✔ 已复制 {len(keep)} 个文件到 refined_pony/")

# ── 删除旧向量库 ─────────────────────────────────────────────────────────────
if DB.exists():
    DB.unlink()
    print(f"✔ 已删除旧向量库 {DB.name}")

print("\n现在请运行：python build_vector_db.py")
print("（build_vector_db.py 默认读取 refined/ ，需要先把路径改为 refined_pony/）")
