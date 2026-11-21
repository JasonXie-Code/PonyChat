#!/usr/bin/env python3
"""远程验证脚本：在服务器 venv 中运行，检查 context_memory 和数据库表"""
import sys, asyncio, json

sys.path.insert(0, '/opt/ponychat/Backend')
sys.path.insert(0, '/opt/ponychat')

results = []

# 1. 导入 context_memory
try:
    from Backend.chat_modules.context_memory import (
        load_context_memory,
        format_context_memory_for_prompt,
        inject_context_memory_into_messages,
        schedule_context_memory_update,
    )
    results.append({"ok": True, "msg": "context_memory module imported"})
except Exception as e:
    results.append({"ok": False, "msg": f"context_memory import: {e}"})

# 2. 检查 normal_chat_memory 表
try:
    from Backend.db.database import get_database
    import aiosqlite

    async def check_table():
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='normal_chat_memory'"
            ) as cur:
                row = await cur.fetchone()
        return row is not None

    exists = asyncio.run(check_table())
    results.append({"ok": exists, "msg": "normal_chat_memory table exists" if exists else "normal_chat_memory table NOT found"})
except Exception as e:
    results.append({"ok": False, "msg": f"DB check: {e}"})

# 3. 通过 OpenAPI 检查路由
try:
    import httpx
    resp = httpx.get("http://127.0.0.1:5000/openapi.json", timeout=5)
    spec = resp.json()
    paths = list(spec.get("paths", {}).keys())
    for ep in ["/api/conversation/messages", "/api/messages/search", "/api/admin/migrate_merge_conversations"]:
        found = ep in paths
        results.append({"ok": found, "msg": f"route {ep} {'registered' if found else 'NOT FOUND'}"})
except Exception as e:
    results.append({"ok": False, "msg": f"OpenAPI check: {e}"})

print(json.dumps(results))
