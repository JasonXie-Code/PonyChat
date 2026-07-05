# -*- coding: utf-8 -*-
"""
将数据库中所有角色 prompt 和 data.prompt 字段里的未成年年龄替换为 18 岁。
策略：将所有出现的 X岁（X < 18）替换为 18岁，同时也替换"年龄: X"等格式。
"""
import os
import sqlite3
import json
import re
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import default_database_path, resolve_project_root

DB_PATH = os.environ.get("PONYCHAT_DB_PATH") or str(
    default_database_path(resolve_project_root(Path(__file__)))
)

AGE_PATTERN_TEXT = re.compile(r'(\d+)\s*岁')
AGE_PATTERN_FIELD = re.compile(r'(年龄[：:]\s*)(\d+)')
AGE_FIELD_NUM = re.compile(r'^(\d+)$')


def replace_minor_age_in_text(text: str) -> tuple[str, list]:
    """替换文本中所有未成年年龄，返回(新文本, 替换列表)"""
    if not text:
        return text, []
    changes = []

    def replace_age(m):
        age = int(m.group(1))
        if age < 18:
            changes.append(f"{age}岁 → 18岁")
            return "18岁"
        return m.group(0)

    def replace_age_field(m):
        age = int(m.group(2))
        if age < 18:
            changes.append(f"年龄字段 {age} → 18")
            return m.group(1) + "18"
        return m.group(0)

    new_text = AGE_PATTERN_TEXT.sub(replace_age, text)
    new_text = AGE_PATTERN_FIELD.sub(replace_age_field, new_text)
    return new_text, changes


def fix_data_json_age(data_str: str) -> tuple[str, list]:
    """替换 data JSON 中的年龄字段"""
    if not data_str:
        return data_str, []
    try:
        d = json.loads(data_str)
    except Exception:
        return data_str, []

    changes = []

    # 检查 data 顶层的 age 字段
    for key in ['age', 'Age', 'AGE']:
        if key in d:
            val = d[key]
            if isinstance(val, (int, float)) and int(val) < 18:
                changes.append(f"data.{key}: {val} → 18")
                d[key] = 18
            elif isinstance(val, str) and AGE_FIELD_NUM.match(val.strip()):
                age = int(val.strip())
                if age < 18:
                    changes.append(f"data.{key}: {val} → 18")
                    d[key] = "18"

    # 替换 data.prompt 里的年龄文本
    if 'prompt' in d and isinstance(d['prompt'], str):
        new_prompt, c = replace_minor_age_in_text(d['prompt'])
        if c:
            d['prompt'] = new_prompt
            changes.extend([f"data.prompt: {x}" for x in c])

    if not changes:
        return data_str, []
    return json.dumps(d, ensure_ascii=False), changes


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT id, name, prompt, data FROM characters WHERE is_hidden=0")
    rows = cur.fetchall()
    print(f"共加载 {len(rows)} 个未隐藏角色\n")

    updated_count = 0
    for r in rows:
        char_id = r['id']
        name = r['name']
        prompt = r['prompt'] or ''
        data_str = r['data'] or ''

        all_changes = []

        # 替换 prompt 字段
        new_prompt, prompt_changes = replace_minor_age_in_text(prompt)
        all_changes.extend(prompt_changes)

        # 替换 data JSON 里的年龄
        new_data_str, data_changes = fix_data_json_age(data_str)
        all_changes.extend(data_changes)

        if all_changes:
            cur.execute(
                "UPDATE characters SET prompt=?, data=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_prompt, new_data_str, char_id)
            )
            updated_count += 1
            print(f"[修改] ID={char_id[:8]} | 角色: {name[:20]}")
            for c in all_changes:
                print(f"       {c}")
            print()

    conn.commit()
    conn.close()
    print(f"\n完成：共修改 {updated_count} 个角色的年龄。")


if __name__ == '__main__':
    main()
