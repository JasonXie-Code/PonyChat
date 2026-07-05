# -*- coding: utf-8 -*-
"""
烟测：拒绝检测已关闭，is_refusal / is_invalid_context_summary 恒为 False。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from backend.refusal_detector import is_invalid_context_summary, is_refusal


async def main() -> None:
    assert await is_refusal("作为AI，我无法生成此类内容。") is False
    assert await is_refusal("") is False
    assert is_invalid_context_summary("不符合公序良俗，低俗色情内容。") is False
    print("OK: refusal_detector 已全部放行")


if __name__ == "__main__":
    asyncio.run(main())
