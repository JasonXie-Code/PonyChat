# -*- coding: utf-8 -*-
"""
扫描 refined/ 下所有文件：
  - 提取 Markdown 第一行 # 标题中的中文主名
  - 与文件名（去掉 .txt）对比
  - 若不一致且不是已知后缀变体（_图集、_概览等），则：
    1. 在文件 > 简介行追加"别名：XXX"
    2. 把文件重命名为内容标题对应的名字
    3. 同时更新 tags.jsonl 里的 file 字段
"""
import sys, json, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

REFINED_DIR = Path(__file__).parent / "refined"
TAGS_FILE   = Path(__file__).parent / "tags.jsonl"

def sanitize_filename(name: str) -> str:
    """移除 Windows 文件名非法字符"""
    return re.sub(r'[\\/:*?"<>|]', "", name).strip()

def extract_main_title(text: str) -> str:
    """从 # 标题行提取中文主名（括号前的部分）"""
    m = re.match(r"^#\s+(.+)$", text.splitlines()[0])
    if not m:
        return ""
    title = m.group(1).strip()
    # 去掉括号内容，取第一段
    title = re.sub(r"[（(].*", "", title).strip()
    return title

# 加载 tags
tags_map: dict[str, dict] = {}
for line in TAGS_FILE.read_text(encoding="utf-8").splitlines():
    if line.strip():
        t = json.loads(line)
        tags_map[t["file"]] = t

mismatches = []
for f in sorted(REFINED_DIR.glob("*.txt")):
    stem = f.stem  # 文件名（无 .txt）
    text = f.read_text(encoding="utf-8", errors="replace")
    title = extract_main_title(text)
    if not title:
        continue
    # 如果标题名在文件名中出现 → 对齐，跳过
    if title in stem or stem in title:
        continue
    mismatches.append((f, stem, title, text))

print(f"发现 {len(mismatches)} 个文件名与标题不一致：")
for f, stem, title, _ in mismatches[:30]:
    print(f"  {stem:30s}  →  {title}")
if len(mismatches) > 30:
    print(f"  ... 共 {len(mismatches)} 个")

if not mismatches:
    print("全部对齐，无需操作。")
    sys.exit(0)

ans = input("\n是否执行重命名？(y/N) ").strip().lower()
if ans != "y":
    print("已取消。")
    sys.exit(0)

# 执行重命名
renamed = 0
skipped = 0
new_tags: list[dict] = []

for f, stem, title, text in mismatches:
    # 新文件名（净化非法字符）
    new_name = sanitize_filename(title) + ".txt"
    new_path = REFINED_DIR / new_name

    # 如果目标已存在，跳过（别名页，内容已由正名页覆盖）
    if new_path.exists():
        print(f"  [跳过-已存在] {f.name} → {new_name}")
        # 删除别名文件（避免重复）
        f.unlink()
        # 从 tags 中移除旧 key
        tags_map.pop(f.name, None)
        skipped += 1
        continue

    # 在 > 简介行后追加别名（若尚未有）
    alias_note = f"别名：{stem}"
    lines = text.splitlines()
    # 找第一个 > 行
    inserted = False
    for i, line in enumerate(lines):
        if line.startswith("> ") and alias_note not in line:
            lines[i] = line.rstrip() + f"  \n> （{alias_note}）"
            inserted = True
            break
    if not inserted:
        # 在 # 标题后插一行
        lines.insert(1, f"\n> （{alias_note}）")

    new_text = "\n".join(lines)
    new_path.write_text(new_text, encoding="utf-8")
    f.unlink()

    # 更新 tags_map
    old_tag = tags_map.pop(f.name, {})
    if old_tag:
        old_tag["file"] = new_name
        tags_map[new_name] = old_tag

    print(f"  [重命名] {f.name:35s} → {new_name}")
    renamed += 1

# 重写 tags.jsonl
with open(TAGS_FILE, "w", encoding="utf-8") as fout:
    for tag in tags_map.values():
        fout.write(json.dumps(tag, ensure_ascii=False) + "\n")

print(f"\n完成：重命名 {renamed} 个，跳过（已有正名文件）{skipped} 个")
print(f"tags.jsonl 已同步更新")
