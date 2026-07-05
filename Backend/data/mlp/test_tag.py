# -*- coding: utf-8 -*-
import sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

_MLP = Path(__file__).resolve().parent
_misc = _MLP.parent.parent / "misc"
sys.path.insert(0, str(_misc))
from project_paths import mlp_data_dir, resolve_project_root

import tag_pages as m

_BASE = mlp_data_dir(resolve_project_root(_MLP))
m.CLEAN_DIR = _BASE / "clean"
m.TAGS_FILE = _BASE / "tags_test.jsonl"
m.TAGS_FILE.unlink(missing_ok=True)

pages = sorted(m.CLEAN_DIR.glob("*.txt"))[:10]
print(f"测试 {len(pages)} 个文件\n")

with open(m.TAGS_FILE, "w", encoding="utf-8") as fout:
    for i, path in enumerate(pages, 1):
        text = path.read_text(encoding="utf-8")
        head = text[:800]
        print(f"[{i}/10] {path.name[:40]:40s}", end=" ... ", flush=True)
        tag = m.tag_page(path.name, head)
        fout.write(json.dumps(tag, ensure_ascii=False) + "\n")
        skip_info = ("跳过:" + tag["skip_reason"]) if tag["skip"] else ""
        print(f"{tag['type']}/{tag.get('importance','')}  目标:{tag['target_words']}字  {skip_info}")

print("\n完成，结果写入 tags_test.jsonl")
