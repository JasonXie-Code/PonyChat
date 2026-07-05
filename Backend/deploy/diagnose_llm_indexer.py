#!/usr/bin/env python3
"""直接 python -m Backend.deploy.diagnose_llm_indexer 运行在服务器上"""
import sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from Backend.routes.admin.llm_log_indexer import LLMLogIndexer, get_log_indexer, _parse_log_file, _resolve_logs_root
from Backend.config import DB_PATH

print("DB_PATH:", DB_PATH)
print("logs_root:", _resolve_logs_root())

# 测试 schema 初始化
idx = LLMLogIndexer(DB_PATH)
import asyncio
async def test():
    try:
        await idx.init_schema()
        print("Schema init OK")
    except Exception as e:
        print("Schema init FAILED:", e)
        traceback.print_exc()
        return

    # 测试解析一个文件
    root = _resolve_logs_root()
    count = 0
    for dp, dns, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".js"):
                fp = os.path.join(dp, fn)
                try:
                    entries = _parse_log_file(fp)
                    if entries:
                        print(f"Parsed OK: {fp}")
                        print(f"  Entry: {entries[0]}")
                        # Try inserting
                        inserted, errs = await idx._insert_entries(entries)
                        print(f"  Inserted: {inserted}, errors: {errs}")
                        count += 1
                        if count >= 3:
                            break
                    else:
                        print(f"Parsed empty: {fp}")
                        count += 1
                        if count >= 3:
                            break
                except Exception as e:
                    print(f"Parse ERROR {fp}: {e}")
                    traceback.print_exc()
                    count += 1
                    if count >= 3:
                        break
        if count >= 3:
            break

    # 测试扫描一次
    print("\nRunning scan_all (limited)...")
    result = await idx.scan_all()
    print("scan_all result:", result)

asyncio.run(test())
