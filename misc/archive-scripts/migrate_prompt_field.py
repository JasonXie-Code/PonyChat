# -*- coding: utf-8 -*-
"""
数据库迁移：将角色 data JSON 中的 systemPrompt 字段统一归并到 prompt 字段。
迁移规则：
  - prompt 已有值 → 不动（用户已通过 App/后端写入了新字段，优先保留）
  - prompt 为空 且 systemPrompt 非空 → 把 systemPrompt 的值写入 prompt，并清空 systemPrompt
迁移后所有角色统一使用 prompt 字段。
"""
import sqlite3
import json
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = str(_ROOT / "backend" / "database" / "ponychat.db")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, data FROM characters")
        rows = cursor.fetchall()

        migrated = 0
        skipped = 0
        for char_id, data_json in rows:
            if not data_json:
                continue
            try:
                data = json.loads(data_json)
            except Exception as e:
                print(f"⚠️ 跳过 {char_id[:16]}... JSON 解析失败: {e}")
                continue

            system_prompt_val = data.get("systemPrompt") or ""
            prompt_val = data.get("prompt") or ""

            if prompt_val:
                # prompt 已有值，不迁移，但仍清除冗余的 systemPrompt
                if system_prompt_val:
                    data.pop("systemPrompt", None)
                    new_json = json.dumps(data, ensure_ascii=False)
                    cursor.execute("UPDATE characters SET data = ?, prompt = ? WHERE id = ?",
                                   (new_json, prompt_val, char_id))
                    print(f"🧹 {char_id[:20]}... prompt 已存在，清除冗余 systemPrompt")
                    migrated += 1
                else:
                    skipped += 1
                continue

            if not system_prompt_val:
                skipped += 1
                continue

            # prompt 为空，systemPrompt 有值 → 迁移
            data["prompt"] = system_prompt_val
            data.pop("systemPrompt", None)
            new_json = json.dumps(data, ensure_ascii=False)
            cursor.execute(
                "UPDATE characters SET data = ?, prompt = ? WHERE id = ?",
                (new_json, system_prompt_val, char_id)
            )
            print(f"✅ 迁移 {char_id[:20]}... systemPrompt({len(system_prompt_val)}字) → prompt")
            migrated += 1

        conn.commit()
        print(f"\n完成：迁移 {migrated} 条，跳过 {skipped} 条（prompt 已是空且 systemPrompt 也空）")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
