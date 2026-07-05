#!/usr/bin/env python3
"""
验证游戏模式（Galgame）数据能否正确保存并读回。
用法：在项目根目录执行
  python misc/tmp-scripts/verify_galgame_save.py
  或
  misc/tools/python/python.exe misc/tmp-scripts/verify_galgame_save.py
"""
import asyncio
import sys
import os

# 确保能 import backend（从项目根运行）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

# 使用与主应用一致的数据库路径
DB_PATH = os.path.join(ROOT, "database", "ponychat.db")


async def main():
    from backend.db import get_database, GalgameDAO

    # 使用与 config 一致的路径，避免单例指向错误 DB
    db = get_database(DB_PATH)
    await db.init()
    dao = GalgameDAO(db)

    # 使用已存在的用户和角色（Jason, user_id=1；其下任一角色 id）
    username = "Jason"
    char_id = "1766939275064"  # 紫悦等角色之一，仅用于测试

    test_payload = {
        "messages": [
            {
                "role": "user",
                "content": "[验证] 游戏模式保存测试",
                "rawContent": "[验证] 游戏模式保存测试",
                "message_id": "verify_gal_msg_0",
                "timestamp": 1700000000000,
                "sequence_number": 0,
                "previous_message_id": None,
            },
            {
                "role": "assistant",
                "content": "收到，保存功能正常。",
                "rawContent": "收到，保存功能正常。",
                "message_id": "verify_gal_msg_1",
                "timestamp": 1700000001000,
                "sequence_number": 1,
                "previous_message_id": "verify_gal_msg_0",
            },
        ],
        "score": 45,
        "status": "playing",
        "version": 1,
    }

    print("1. 保存 Galgame 测试数据...")
    ok = await dao.save_galgame_data(username, char_id, test_payload, allow_overwrite_with_fewer=True)
    if not ok:
        print("   [失败] save_galgame_data 返回 False")
        return 1
    print("   [成功] save_galgame_data 返回 True")

    print("2. 从数据库读回...")
    loaded = await dao.load_galgame_data(username, char_id)
    if not loaded:
        print("   [失败] load_galgame_data 返回 None")
        return 1
    msgs = loaded.get("messages") or []
    score = loaded.get("score", 0)
    print(f"   [成功] 读回 messages={len(msgs)}, score={score}")

    if len(msgs) != 2:
        print(f"   [失败] 期望 2 条消息，实际 {len(msgs)}")
        return 1
    if score != 45:
        print(f"   [失败] 期望 score=45，实际 {score}")
        return 1
    if (msgs[0].get("content") or "").strip() != "[验证] 游戏模式保存测试":
        print("   [失败] 第一条消息 content 不一致")
        return 1
    print("3. 内容校验通过：游戏模式数据能正确保存并读回。")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
