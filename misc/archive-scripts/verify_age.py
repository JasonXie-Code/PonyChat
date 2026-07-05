# -*- coding: utf-8 -*-
import os
import sqlite3, json, re, sys, io
from pathlib import Path

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import default_database_path, resolve_project_root

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DB_PATH = os.environ.get("PONYCHAT_DB_PATH") or str(
    default_database_path(resolve_project_root(Path(__file__)))
)
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT id, name, prompt, data FROM characters WHERE is_hidden=0")
rows = cur.fetchall()

found_minor = False
for r in rows:
    prompt = r['prompt'] or ''
    ages_prompt = [int(a) for a in re.findall(r'(\d+)\s*岁', prompt)]
    minor_prompt = [a for a in ages_prompt if a < 18]

    data_str = r['data'] or ''
    data_ages = []
    try:
        d = json.loads(data_str)
        dp = d.get('prompt', '')
        data_ages = [int(a) for a in re.findall(r'(\d+)\s*岁', dp)]
    except Exception:
        pass
    minor_data = [a for a in data_ages if a < 18]

    if minor_prompt or minor_data:
        found_minor = True
        print(f"[残留未成年] ID={r['id'][:8]} 角色={r['name'][:20]} prompt未成年={minor_prompt} data未成年={minor_data}")

if not found_minor:
    print("验证通过：所有角色 prompt 中均不含未成年年龄。")
conn.close()
