#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path
from typing import Any, Tuple

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import resolve_project_root, chatlogs_dir

ROOT = resolve_project_root(Path(__file__))
CHATLOG_DIR = chatlogs_dir(ROOT)
LOG_FILE_PATTERN = "*.js"


def try_pretty_json_string(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if not ((stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]"))):
        return None
    try:
        obj = json.loads(stripped)
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return pretty_json_like_loose(stripped)


def pretty_json_like_loose(text: str) -> str | None:
    if "\n" in text:
        return text
    if len(text) < 120:
        return None

    out: list[str] = []
    indent = 0
    in_string = False
    escaped = False

    for ch in text:
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
        elif ch in "{[":
            out.append(ch)
            indent += 1
            out.append("\n" + ("  " * indent))
        elif ch == ",":
            out.append(ch)
            out.append("\n" + ("  " * indent))
        elif ch in "}]":
            indent = max(0, indent - 1)
            out.append("\n" + ("  " * indent) + ch)
        else:
            out.append(ch)

    pretty = "".join(out).strip()
    return pretty or None


def normalize_log_string_for_display(value: str) -> str:
    if "\r" in value:
        value = value.replace("\r\n", "\n").replace("\r", "\n")

    pretty_whole = try_pretty_json_string(value)
    if pretty_whole is not None:
        return pretty_whole

    mixed_match = re.match(
        r"(?s)^\s*(<(?:think|thinking)>[\s\S]*?</(?:think|thinking)>)\s*([\{\[][\s\S]*[\}\]])\s*$",
        value.strip(),
        flags=re.IGNORECASE,
    )
    if mixed_match:
        think_part = mixed_match.group(1).strip()
        json_part = mixed_match.group(2).strip()
        pretty_json = try_pretty_json_string(json_part)
        if pretty_json is not None:
            return f"{think_part}\n{pretty_json}"

    return value


def to_js_literal(value: Any, indent: int = 0) -> str:
    pad = " " * indent
    next_pad = " " * (indent + 4)

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        value = normalize_log_string_for_display(value)
        if "\n" in value:
            escaped = value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
            return f"`{escaped}`"
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        if not value:
            return "[]"
        items = [f"{next_pad}{to_js_literal(v, indent + 4)}" for v in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        parts = []
        for k, v in value.items():
            key = json.dumps(str(k), ensure_ascii=False)
            parts.append(f"{next_pad}{key}: {to_js_literal(v, indent + 4)}")
        return "{\n" + ",\n".join(parts) + f"\n{pad}}}"
    return json.dumps(str(value), ensure_ascii=False)


def extract_debug_json(content: str) -> Tuple[bool, str]:
    match = re.match(r"^\s*const\s+debug_log\s*=\s*([\s\S]*?)\s*;\s*$", content)
    if not match:
        return False, ""
    return True, match.group(1)


def convert_template_data_field(content: str) -> Tuple[bool, str]:
    """
    回退路径：当整个 JS 字面量无法直接 json.loads 时，
    仅对 "data": `...` 模板字符串做可读性格式化。
    """
    pattern = re.compile(r'("data"\s*:\s*`)([\s\S]*?)(`\s*[,\}])')
    match = pattern.search(content)
    if not match:
        return False, content

    original_inner = match.group(2)
    normalized_inner = normalize_log_string_for_display(original_inner)
    if normalized_inner == original_inner:
        return False, content

    new_content = content[:match.start(2)] + normalized_inner + content[match.end(2):]
    return True, new_content


def convert_file(path: Path) -> str:
    original = path.read_text(encoding="utf-8")
    ok, payload = extract_debug_json(original)
    if not ok:
        return "skip_not_debug_log"

    try:
        parsed = json.loads(payload)
    except Exception:
        updated, fallback_content = convert_template_data_field(original)
        if not updated:
            return "skip_not_json_object"
        path.write_text(fallback_content, encoding="utf-8")
        return "converted"

    new_content = f"const debug_log = {to_js_literal(parsed, 0)};"
    if new_content == original:
        return "unchanged"

    path.write_text(new_content, encoding="utf-8")
    return "converted"


def main() -> int:
    if not CHATLOG_DIR.exists():
        print(f"[ERROR] directory not found: {CHATLOG_DIR}")
        return 1

    files = sorted(CHATLOG_DIR.glob(LOG_FILE_PATTERN))
    total = len(files)
    converted = 0
    unchanged = 0
    skipped = 0
    failed = 0

    for fp in files:
        try:
            result = convert_file(fp)
            if result == "converted":
                converted += 1
            elif result == "unchanged":
                unchanged += 1
            else:
                skipped += 1
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {fp.name}: {exc}")

    print(f"[DONE] total={total} converted={converted} unchanged={unchanged} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
