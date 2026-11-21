"""
普通聊天模式（mode=normal）下，在发起 LLM 请求前插入可变延迟，模拟真人 QQ 回复节奏。

环境变量：
  PONYCHAT_IM_REPLY_DELAY_ENABLED   默认 1；设为 0 关闭
  PONYCHAT_IM_REPLY_DELAY_MIN_MS    默认 800
  PONYCHAT_IM_REPLY_DELAY_MAX_MS    默认 12000
  PONYCHAT_IM_REPLY_DELAY_JITTER_MS 默认 1500（额外随机上限）
"""
from __future__ import annotations

import asyncio
import os
import random
import re
from typing import Any, List

from ..config import logger


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _last_user_text(messages: List[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c.strip()
        if isinstance(c, list):
            parts: List[str] = []
            for p in c:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(str(p.get("text") or ""))
            return " ".join(parts).strip()
    return ""


def compute_normal_mode_reply_delay_ms(request: Any, messages: List[dict]) -> int:
    if (getattr(request, "mode", None) or "normal") != "normal":
        return 0
    if _env_int("PONYCHAT_IM_REPLY_DELAY_ENABLED", 1) == 0:
        return 0

    min_ms = max(0, _env_int("PONYCHAT_IM_REPLY_DELAY_MIN_MS", 800))
    max_ms = max(min_ms, _env_int("PONYCHAT_IM_REPLY_DELAY_MAX_MS", 12000))

    text = _last_user_text(messages)
    if not text:
        base = min_ms
    else:
        ln = len(text)
        # 略随字数增加（有上限），短消息也快回
        length_bonus = min(6000, ln * 35)
        # 看起来像急事 → 略缩短
        if re.search(r"急|救命|快来|快点|在吗在吗|!!!|！！", text):
            length_bonus = max(0, length_bonus - 2500)
        # 问句略增思考感
        question_bonus = 400 if ("?" in text or "？" in text) else 0
        base = min_ms + length_bonus + question_bonus

    jitter = random.randint(0, _env_int("PONYCHAT_IM_REPLY_DELAY_JITTER_MS", 1500))
    delay_ms = int(base + jitter)
    return max(min_ms, min(max_ms, delay_ms))


async def apply_normal_mode_reply_delay(
    request: Any,
    messages: List[dict],
    *,
    username: str,
    character_id: str,
    client_id: str,
) -> None:
    """在非流式上游请求真正访问模型前调用；支持生成取消时提前结束等待。"""
    ms = compute_normal_mode_reply_delay_ms(request, messages)
    if ms <= 0:
        return

    from .state import is_generation_cancelled

    logger.info(
        "⏱️ [IM仿真] 普通聊天延迟 %sms 后再请求模型 (user=%s char=%s)",
        ms,
        username or "-",
        (character_id or "")[:8] + "…" if character_id and len(character_id) > 8 else (character_id or "-"),
    )

    remaining = ms
    chunk_ms = 200
    while remaining > 0:
        if is_generation_cancelled(username, character_id, client_id):
            logger.info("⏱️ [IM仿真] 延迟期间检测到取消，跳过剩余等待")
            return
        step = min(chunk_ms, remaining)
        await asyncio.sleep(step / 1000.0)
        remaining -= step
