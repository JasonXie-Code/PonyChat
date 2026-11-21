"""
后端 Prompt Cache 模拟器

算法：
  - 对每条 system 消息（角色设定、指令等）计算内容哈希
  - 若该哈希在 1 小时内被使用过 → 缓存命中，tokens 计入 cache_read，不计入 input
  - 若命中，自动刷新过期时间（滑动窗口）：内容一直被使用则持续命中
  - 1 小时内未再被使用 → 自动过期，下次重新计入 input（首次发送）

只对 system 消息做缓存模拟；user / assistant 消息内容每次均不同，不参与缓存。
"""

import asyncio
import hashlib
import logging
import time
from typing import Tuple

logger = logging.getLogger(__name__)

CACHE_TTL = 3600  # 秒，滑动窗口时长

# content_hash -> 最后访问时间戳
_cache: dict[str, float] = {}
_lock = asyncio.Lock()


def _hash(username: str, content: str) -> str:
    """缓存 key 包含用户名，确保不同用户之间完全隔离。"""
    raw = f"{username}\x00{content}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _tokens(content: str) -> int:
    """与 estimate_tokens 公式一致：CJK × 1.5，其余 × 0.3，每条消息加 4 token 固定开销。"""
    from .utils import _count_text_tokens
    return _count_text_tokens(content) + 4


async def split_usage(messages: list, username: str = "") -> Tuple[int, int]:
    """
    遍历消息列表，将 token 估算拆分为：
      (input_tokens, cache_read_tokens)

    规则：
      - system 消息：按 (username, content) 检查缓存
          命中 → cache_read_tokens，刷新 TTL（滑动窗口）
          未命中 → input_tokens，写入缓存
      - user / assistant 消息：始终计入 input_tokens

    不同用户之间缓存完全隔离，不会相互影响。
    返回值中 input_tokens 已包含全局 +20 基础偏移。
    """
    now = time.time()
    input_tok = 0
    cache_tok = 0

    async with _lock:
        for m in messages:
            role = str(m.get("role", "user"))
            content = str(m.get("content", ""))
            tok = _tokens(content)

            if role == "system" and content.strip():
                h = _hash(username, content)
                last = _cache.get(h)
                if last is not None and (now - last) < CACHE_TTL:
                    # 缓存命中，刷新滑动窗口
                    _cache[h] = now
                    cache_tok += tok
                    logger.debug(
                        "🎯 [PromptCacheSim] 命中 user=%s hash=%.8s tokens=%d age=%.0fs",
                        username, h, tok, now - last,
                    )
                else:
                    # 缓存未命中（首次或已过期），写入缓存
                    _cache[h] = now
                    input_tok += tok
                    if last is not None:
                        logger.info(
                            "⏰ [PromptCacheSim] 过期重新计入 user=%s hash=%.8s tokens=%d",
                            username, h, tok,
                        )
                    else:
                        logger.info(
                            "📝 [PromptCacheSim] 首次缓存 user=%s hash=%.8s tokens=%d",
                            username, h, tok,
                        )
            else:
                input_tok += tok

    # 全局基础偏移加到 input 侧
    return input_tok + 20, cache_tok


async def cleanup() -> int:
    """清理已过期条目，返回清理数量。可定期调用防止内存泄漏。"""
    now = time.time()
    async with _lock:
        expired = [h for h, t in _cache.items() if now - t >= CACHE_TTL]
        for h in expired:
            del _cache[h]
    if expired:
        logger.info("🧹 [PromptCacheSim] 清理过期条目 %d 个", len(expired))
    return len(expired)


def cache_size() -> int:
    """当前缓存条目数（无锁快照，仅供监控用）。"""
    return len(_cache)
