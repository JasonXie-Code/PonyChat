# -*- coding: utf-8 -*-
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MISC = _REPO_ROOT / "misc"
sys.path.insert(0, str(_MISC))
from project_paths import backend_package_dir, resolve_project_root

src_path = backend_package_dir(resolve_project_root(_REPO_ROOT)) / "chat_modules" / "nonstream.py"
src = src_path.read_text(encoding="utf-8")
lines = src.splitlines()

# 二分查找精确定位报错行
try:
    compile(src, str(src_path), "exec")
    print("Full file OK")
except SyntaxError as e:
    print(f"Full file error: line={e.lineno}, msg={e.msg}")
    safe_text = (e.text or "").encode("ascii", errors="replace").decode("ascii")
    print(f"Text: {repr(safe_text[:100])}")

    # 再缩小范围：分段检查
    for start, end in [(1, 50), (1, 100), (1, 200), (1, 500), (200, 500), (500, 1000), (1000, 2000), (2000, 3000)]:
        snippet = "\n".join(lines[start - 1 : end])
        try:
            compile(snippet, "test", "exec")
        except SyntaxError as e2:
            print(f"Section {start}-{end}: error at relative line {e2.lineno}, msg={e2.msg}")
            break
