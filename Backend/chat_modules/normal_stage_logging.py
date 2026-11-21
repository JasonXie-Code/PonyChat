from __future__ import annotations

import asyncio
import time

from ..config import logger


_NORMAL_STAGE_LABELS = {
    "NORMAL_AGENT_AUTONOMOUS": "Agent 自主回复生成",
    "NORMAL_AGENT_SILENCE_PERSIST": "Agent 静默结果持久化",
    "NORMAL_STEP_3_PERSIST": "Agent 回复持久化",
    "NORMAL_STEP_3_VOICE_PREPARE": "Agent 语音准备",
    "NORMAL_STEP_3_VOICE_ATTACH": "Agent 语音附件生成",
    "NORMAL_STEP_4_HANDOFF_ROUTER": "Agent 发言交接判断",
}


def normal_stage_label(stage: str) -> str:
    return _NORMAL_STAGE_LABELS.get(str(stage or ""), str(stage or "UNKNOWN"))


def _normal_stage_context_suffix(log_context: dict | None) -> str:
    if not isinstance(log_context, dict):
        return ""
    parts = []
    for key in ("user", "char", "conv", "job"):
        value = str(log_context.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    return (" " + " ".join(parts)) if parts else ""


async def await_logged_normal_stage(
    awaitable,
    stage: str,
    normal_generation_current,
    superseded_error_type,
    *,
    log_context: dict | None = None,
):
    """等待普通模式 Agent 操作，并统一记录开始、完成、失败、取消和耗时。"""
    label = normal_stage_label(stage)
    context_suffix = _normal_stage_context_suffix(log_context)
    started = time.perf_counter()
    logger.info("🔗 [普通Agent] 开始 %s stage=%s%s", label, stage, context_suffix)
    task = asyncio.ensure_future(awaitable)
    outcome = "failed"
    try:
        while not task.done():
            if not normal_generation_current():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                outcome = "superseded"
                raise superseded_error_type(stage)
            await asyncio.sleep(0.2)
        result = await task
        outcome = "completed"
        return result
    except asyncio.CancelledError:
        task.cancel()
        outcome = "cancelled"
        raise
    except Exception as exc:
        if not task.done():
            task.cancel()
        if outcome != "superseded":
            logger.warning(
                "❌ [普通Agent] 失败 %s stage=%s elapsed=%.2fs error=%s%s",
                label,
                stage,
                time.perf_counter() - started,
                exc,
                context_suffix,
            )
        raise
    finally:
        elapsed = time.perf_counter() - started
        if outcome == "completed":
            logger.info("✅ [普通Agent] 完成 %s stage=%s elapsed=%.2fs%s", label, stage, elapsed, context_suffix)
        elif outcome in {"cancelled", "superseded"}:
            logger.info(
                "🛑 [普通Agent] 取消 %s stage=%s reason=%s elapsed=%.2fs%s",
                label,
                stage,
                outcome,
                elapsed,
                context_suffix,
            )
