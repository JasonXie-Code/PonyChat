"""近期图片识图池与 normal_planner 合并逻辑单测。"""

from __future__ import annotations

import sys
import asyncio
from pathlib import Path

import pytest

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
from Backend.chat_modules.normal_planner import _coerce_planner, default_planner_result
from Backend.db import get_database


@pytest.fixture(autouse=True)
async def _close_db_after_test():
    try:
        yield
    finally:
        await get_database().close()


async def test_queue_append_and_inject_newest_order():
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


async def test_last_reply_flag_roundtrip():
    u, c, conv = "u2", "ch2", "conv2"
    await set_last_reply_based_on_image(u, c, conv, False)
    assert not await get_last_reply_based_on_image(u, c, conv)
    await set_last_reply_based_on_image(u, c, conv, True)
    assert await get_last_reply_based_on_image(u, c, conv)
    await set_last_reply_based_on_image(u, c, conv, False)
    assert not await get_last_reply_based_on_image(u, c, conv)


def test_coerce_planner_strips_use_prior_without_pool():
    d = {**default_planner_result(), "use_prior_image_context": True, "image_context_reason": "想引用"}
    o = _coerce_planner(d, can_use_prior_image_context=False)
    assert o["use_prior_image_context"] is False


def test_coerce_planner_allows_use_prior_with_pool():
    d = {**default_planner_result(), "use_prior_image_context": True, "image_context_reason": "图里字"}
    o = _coerce_planner(d, can_use_prior_image_context=True)
    assert o["use_prior_image_context"] is True


def test_coerce_planner_low_speech_activity_disables_output_channels():
    d = {
        **default_planner_result(),
        "speech_activity": 3,
        "speech_reason": "用户只是在晚安后确认收束",
        "should_ask_question": True,
        "asset_plan": {"enabled": True, "count": 1, "send_intensity": 90},
        "scheduled_followup": {"enabled": True, "target_delay_seconds": 60, "expires_seconds": 1800},
    }
    o = _coerce_planner(d, can_use_prior_image_context=True)
    assert o["speech_activity"] == 3
    assert o["speech_reason"] == "用户只是在晚安后确认收束"
    assert o["bubble_count"] == 0
    assert o["should_ask_question"] is False
    assert o["asset_plan"]["enabled"] is False
    assert o["reply_sequence"] == []
    assert o["scheduled_followup"]["enabled"] is False


if __name__ == "__main__":
    asyncio.run(test_queue_append_and_inject_newest_order())
    asyncio.run(test_last_reply_flag_roundtrip())
    test_coerce_planner_strips_use_prior_without_pool()
    test_coerce_planner_allows_use_prior_with_pool()
    test_coerce_planner_low_speech_activity_disables_output_channels()
    from Backend.db import get_database
    asyncio.run(get_database().close())
    print("ok")
