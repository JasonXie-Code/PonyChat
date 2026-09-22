"""近期图片识图池单测。

本目录的既有约定是用同步测试函数包一个 asyncio.run()（仓库没有 pytest 异步配置），
因此异步用例与数据库关闭都在同一个事件循环内完成。
"""

from __future__ import annotations

import sys
import asyncio
from pathlib import Path

# 仓库根目录（含 Backend/ 包）
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from Backend.chat_modules.image_context_store import (
    INJECT_MAX,
    append_from_vision_fields,
    count_stored,
    format_prior_injection_block,
    get_last_n_for_injection,
    get_last_reply_based_on_image,
    set_last_reply_based_on_image,
)
from Backend.db import get_database


async def _queue_append_and_inject_newest_order():
    u, c, conv = "u1", "ch1", "conv1"
    await append_from_vision_fields(
        u, c, conv,
        user_text="看这张",
        image_count=1,
        should_refuse=False,
        image_summary="摘要A",
        visible_text="",
    )
    await asyncio.sleep(0.01)
    await append_from_vision_fields(
        u, c, conv,
        user_text="再看",
        image_count=1,
        should_refuse=False,
        image_summary="摘要B",
        visible_text="",
    )
    assert await count_stored(u, c, conv) >= 2
    last4 = await get_last_n_for_injection(u, c, conv, n=INJECT_MAX)
    assert len(last4) >= 2
    assert last4[0].image_summary == "摘要B"
    assert last4[1].image_summary == "摘要A"
    block = format_prior_injection_block(last4)
    assert "最近第1组" in block
    assert "摘要B" in block


async def _last_reply_flag_roundtrip():
    u, c, conv = "u2", "ch2", "conv2"
    await set_last_reply_based_on_image(u, c, conv, False)
    assert not await get_last_reply_based_on_image(u, c, conv)
    await set_last_reply_based_on_image(u, c, conv, True)
    assert await get_last_reply_based_on_image(u, c, conv)
    await set_last_reply_based_on_image(u, c, conv, False)
    assert not await get_last_reply_based_on_image(u, c, conv)


def _run(case):
    """在同一事件循环内跑用例，并在结束时关闭数据库连接池。"""
    async def scenario():
        try:
            await case()
        finally:
            await get_database().close()
    asyncio.run(scenario())


def test_queue_append_and_inject_newest_order():
    _run(_queue_append_and_inject_newest_order)


def test_last_reply_flag_roundtrip():
    _run(_last_reply_flag_roundtrip)


if __name__ == "__main__":
    _run(_queue_append_and_inject_newest_order)
    _run(_last_reply_flag_roundtrip)
    print("ok")
