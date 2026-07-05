# -*- coding: utf-8 -*-
"""验证数据库中所有角色 data JSON 均不含 systemPrompt 字段，若仍有残余则强制清除。"""
import sqlite3
import json
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = str(_ROOT / "backend" / "database" / "ponychat.db")

def verify_and_clean():
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, data FROM characters")
        rows = cursor.fetchall()

        still_has = 0
        clean = 0
        fixed = 0
        for char_id, data_json in rows:
            if not data_json:
                clean += 1
                continue
            try:
                data = json.loads(data_json)
            except Exception:
                clean += 1
                continue

            if "systemPrompt" in data:
                still_has += 1
                # 若 prompt 仍为空则先迁移，再清除
                if not data.get("prompt"):
                    data["prompt"] = data["systemPrompt"]
                    cursor.execute("UPDATE characters SET prompt = ? WHERE id = ?",
                                   (data["systemPrompt"], char_id))
                data.pop("systemPrompt")
                new_json = json.dumps(data, ensure_ascii=False)
                cursor.execute("UPDATE characters SET data = ? WHERE id = ?", (new_json, char_id))
                print(f"🔧 强制清除 {char_id[:24]}... 中的 systemPrompt")
                fixed += 1
            else:
                clean += 1

        conn.commit()
        print(f"\n验证完毕：")
        print(f"  ✅ 已干净（无 systemPrompt）：{clean} 条")
        print(f"  🔧 本次强制清除：{fixed} 条（原本仍有残余）")
        if still_has == 0:
            print("\n✅ 数据库彻底干净，所有角色均不含 systemPrompt 字段。")
    finally:
        conn.close()

if __name__ == "__main__":
    verify_and_clean()
