from __future__ import annotations

import asyncio
import time
from typing import Any

from ..config import logger


_pending_step4_memory_relation_tasks: dict[str, asyncio.Task] = {}
_pending_step4_memory_relation_character_tasks: dict[str, set[asyncio.Task]] = {}
_locks: dict[str, asyncio.Lock] = {}


def _session_key(username: str, character_id: str, conversation_id: str) -> str:
    return f"{username or ''}\0{character_id or ''}\0{conversation_id or ''}"


def _character_key(username: str, character_id: str) -> str:
    return f"{username or ''}\0{character_id or ''}"


def _get_lock(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


async def wait_for_normal_step4_memory_relation(
    username: str | None,
    character_id: str | None,
    conversation_id: str | None,
) -> None:
    """Wait until the previous normal-turn Step 4 memory/relationship work is done.

    This is the ordering gate between turn N Step 4 extraction and turn N+1
    Step 1. It keeps newly extracted memory/relationship state visible before
    any new user message is processed, without delaying the already displayed
    reply in turn N.
    """
    if not username or not character_id or not conversation_id:
        return
    pending: list[asyncio.Task] = []
    if conversation_id:
        key = _session_key(username, character_id, conversation_id)
        task = _pending_step4_memory_relation_tasks.get(key)
        if task and not task.done():
            pending.append(task)
    character_task_set = _pending_step4_memory_relation_character_tasks.get(_character_key(username, character_id))
    if character_task_set:
        for task in list(character_task_set):
            if task.done():
                character_task_set.discard(task)
            else:
                pending.append(task)
        if not character_task_set:
            _pending_step4_memory_relation_character_tasks.pop(_character_key(username, character_id), None)

    unique_pending = list({id(task): task for task in pending}.values())
    if not unique_pending:
        return
    started = time.time()
    logger.info(
        "🧠 [NormalStep4MemoryRelation] 等待上一轮 Step 4 记忆/关系处理完成 conv=%s",
        str(conversation_id)[:12],
    )
    results: list[Any] = []
    try:
        results = await asyncio.gather(*unique_pending, return_exceptions=True)
    except asyncio.CancelledError:
        raise
    finally:
        logger.info(
            "🧠 [NormalStep4MemoryRelation] 上一轮 Step 4 处理等待结束 conv=%s elapsed=%.2fs",
            str(conversation_id)[:12],
            time.time() - started,
        )
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, Exception):
            logger.warning("[NormalStep4MemoryRelation] 上一轮处理失败，继续本轮: %s", result)


def schedule_normal_step4_memory_relation(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    user_message: str,
    assistant_message: str,
    db: Any,
    messages_for_bubbles: list[Any] | None = None,
    entry_at_ms: int | None = None,
    planner_memory_notes: str = "",
    memory_enabled: bool = True,
    extra_memory_extract_specs: list[dict[str, Any]] | None = None,
) -> None:
    """Schedule Step 4 memory/relationship extraction for a normal reply.

    New user messages wait for this task before entering their Step 1, but they
    do not wait for the rest of Step 4 next-turn preparation such as active
    follow-up decisions.
    """
    if not username or not character_id or not conversation_id:
        return
    key = _session_key(username, character_id, conversation_id)
    old = _pending_step4_memory_relation_tasks.get(key)
    target_character_ids = {str(character_id or "").strip()}
    for spec in extra_memory_extract_specs or []:
        if isinstance(spec, dict):
            target_character_id = str(spec.get("character_id") or "").strip()
            if target_character_id:
                target_character_ids.add(target_character_id)

    async def _chain() -> None:
        if old and not old.done():
            try:
                await old
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        async with _get_lock(key):
            jobs: list[asyncio.Task] = []
            if memory_enabled:
                try:
                    from .context_memory import _run_context_memory_update

                    jobs.append(
                        asyncio.create_task(
                            _run_context_memory_update(
                                username,
                                character_id,
                                conversation_id,
                                user_message,
                                assistant_message,
                                db,
                                messages_for_bubbles=messages_for_bubbles,
                                entry_at_ms=entry_at_ms,
                                planner_memory_notes=planner_memory_notes,
                                stage_prefix="NORMAL_STEP_4_MEMORY_RELATION",
                            )
                        )
                    )
                except Exception as exc:
                    logger.warning("🧠 [NormalStep4MemoryRelation] 上下文记忆任务创建失败: %s", exc)

                try:
                    from ..memory.extractor import do_extract

                    extract_messages = [
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": assistant_message},
                    ]
                    jobs.append(
                        asyncio.create_task(
                            do_extract(
                                username,
                                character_id,
                                extract_messages,
                                source="normal_chat",
                                debug_mode="normal",
                                debug_stage="NORMAL_STEP_4_MEMORY_RELATION_LONG_MEMORY_REQUEST",
                                planner_memory_notes=planner_memory_notes,
                            )
                        )
                    )
                    for spec in extra_memory_extract_specs or []:
                        if not isinstance(spec, dict):
                            continue
                        target_character_id = str(spec.get("character_id") or "").strip()
                        extract_spec_messages = spec.get("messages")
                        if not target_character_id or not isinstance(extract_spec_messages, list):
                            continue
                        kwargs: dict[str, Any] = {
                            "source": str(spec.get("source") or "normal_chat").strip() or "normal_chat",
                            "debug_mode": "normal",
                            "debug_stage": str(spec.get("debug_stage") or "NORMAL_STEP_4_MEMORY_RELATION_LONG_MEMORY_REQUEST"),
                        }
                        if spec.get("types"):
                            kwargs["types"] = spec.get("types")
                        if spec.get("created_at"):
                            kwargs["created_at"] = spec.get("created_at")
                        if planner_memory_notes:
                            kwargs["planner_memory_notes"] = planner_memory_notes
                        jobs.append(
                            asyncio.create_task(
                                do_extract(
                                    username,
                                    target_character_id,
                                    extract_spec_messages,
                                    **kwargs,
                                )
                            )
                        )
                except Exception as exc:
                    logger.warning("🧠 [NormalStep4MemoryRelation] 长期记忆/关系提取任务创建失败: %s", exc)

            if not jobs:
                return
            results = await asyncio.gather(*jobs, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("🧠 [NormalStep4MemoryRelation] 子任务失败: %s", result)

    task = asyncio.create_task(_chain())
    _pending_step4_memory_relation_tasks[key] = task

    target_keys = [_character_key(username, cid) for cid in target_character_ids if cid]
    for target_key in target_keys:
        _pending_step4_memory_relation_character_tasks.setdefault(target_key, set()).add(task)

    def _cleanup_done(done_task: asyncio.Task) -> None:
        if _pending_step4_memory_relation_tasks.get(key) is done_task:
            _pending_step4_memory_relation_tasks.pop(key, None)
        for target_key in target_keys:
            task_set = _pending_step4_memory_relation_character_tasks.get(target_key)
            if not task_set:
                continue
            task_set.discard(done_task)
            if not task_set:
                _pending_step4_memory_relation_character_tasks.pop(target_key, None)

    task.add_done_callback(_cleanup_done)


def get_pending_normal_step4_memory_relation_task(
    username: str,
    character_id: str,
    conversation_id: str,
) -> asyncio.Task | None:
    return _pending_step4_memory_relation_tasks.get(_session_key(username, character_id, conversation_id))
