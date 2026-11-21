#!/usr/bin/env python3
"""
检查 JS 模块 import 语句是否统一使用 ?v=__CACHE_VERSION__

用法：
  python check_imports.py          # 检查并报告
  python check_imports.py --fix    # 自动修复

规则：
  - js/ 目录下所有 .js 文件的 import ... from '...xxx.js' 必须带 ?v=__CACHE_VERSION__
  - 排除 node_modules、vendor、admin 目录（admin 页面使用独立缓存策略）
  - 仅检查引用项目内 .js 文件的 import（不检查 npm 包等外部引用）
"""
import re
import sys
from pathlib import Path

_MISC = Path(__file__).resolve().parent.parent
if str(_MISC) not in sys.path:
    sys.path.insert(0, str(_MISC))
from project_paths import resolve_project_root

_JS_ROOT = resolve_project_root(Path(__file__))
JS_DIR = _JS_ROOT / "frontend" / "js"
CACHE_SUFFIX = "?v=__CACHE_VERSION__"
EXCLUDE_DIRS = {"node_modules", "vendor", "admin", "lib"}

# 匹配: import ... from '相对路径.js' 或 import ... from '相对路径.js?v=...'
IMPORT_RE = re.compile(
    r"""(import\s+.*?from\s+['"])"""           # group(1): import 前缀
    r"""(\.\.?/[^'"]*?\.js)"""                 # group(2): 相对路径 .js
    r"""(\?v=[^'"]*)?"""                       # group(3): 可选的 ?v=xxx
    r"""(['"])""",                              # group(4): 闭合引号
    re.MULTILINE
)


def scan_file(filepath: Path, fix: bool = False):
    """扫描单个文件，返回问题列表。fix=True 时自动修复。"""
    issues = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return issues

    new_content = content
    for match in IMPORT_RE.finditer(content):
        prefix = match.group(1)     # import ... from '
        js_path = match.group(2)    # ../foo/bar.js
        version = match.group(3)    # ?v=__CACHE_VERSION__ 或其他
        quote = match.group(4)      # '

        if version == CACHE_SUFFIX:
            continue  # 正确

        line_num = content[:match.start()].count("\n") + 1
        full_match = match.group(0)

        if version is None:
            issue_type = "缺少 ?v=__CACHE_VERSION__"
        elif version != CACHE_SUFFIX:
            issue_type = f"硬编码版本号 {version}（应为 ?v=__CACHE_VERSION__）"
        else:
            continue

        issues.append({
            "file": str(filepath.relative_to(JS_DIR.parent)),
            "line": line_num,
            "type": issue_type,
            "original": full_match,
        })

        if fix:
            fixed = f"{prefix}{js_path}{CACHE_SUFFIX}{quote}"
            new_content = new_content.replace(full_match, fixed, 1)

    if fix and new_content != content:
        filepath.write_text(new_content, encoding="utf-8")

    return issues


def main():
    fix = "--fix" in sys.argv
    all_issues = []

    for js_file in sorted(JS_DIR.rglob("*.js")):
        # 排除目录
        rel_parts = js_file.relative_to(JS_DIR).parts
        if any(part in EXCLUDE_DIRS for part in rel_parts):
            continue
        issues = scan_file(js_file, fix=fix)
        all_issues.extend(issues)

    if not all_issues:
        print("[OK] All JS imports use ?v=__CACHE_VERSION__ correctly.")
        sys.exit(0)

    action_word = "FIXED" if fix else "FOUND"
    print(f"[{action_word}] {len(all_issues)} import(s) with version issues:\n")
    for issue in all_issues:
        status = "fixed" if fix else "needs fix"
        print(f"  {issue['file']}:{issue['line']} - {issue['type']}")
        print(f"    [{status}] {issue['original']}")
        print()

    if not fix:
        print("Run: python check_imports.py --fix")
        sys.exit(1)
    else:
        print("[OK] All issues have been auto-fixed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
