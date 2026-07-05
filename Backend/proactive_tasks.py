from __future__ import annotations

import asyncio
import json
import random
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import aiosqlite

from .config import logger
from .db import get_database
from .proactive_settings import apply_frequency_to_delay_seconds, load_proactive_settings
from .shutdown_state import is_shutdown_requested
from .websocket import galgame_locker


MAX_DUE_TASKS = 6
AUTO_LIFE_DELAY_SECONDS = 2 * 60 * 60
AUTO_LONG_DELAY_SECONDS = 24 * 60 * 60

_CONVERSATION_END_RE = re.compile(
    r"(休息了|去休息|我要睡|我睡了|睡觉了|准备睡|该睡|晚安|明天再来|明天聊|明天见|先不聊|不聊了|下线了|拜拜|再见)"
)
_SHORT_FOLLOWUP_SEED_RE = re.compile(
    r"(用户尚未回应|用户没有新可见消息|等待用户|在等待用户|上一条在等待|"
    r"低压力缓和|重新邀请|不用急着回应|给用户.*台阶|不能默认用户|不得默认用户|"
    r"用户未回复|用户没回|如果用户.*没回|尚未回复|还没回复)"
)


def now_ms() -> int:
    return int(time.time() * 1000)


def normalize_task_type(value: str) -> str:
    v = (value or "").strip().lower()
    allowed = {
        "short_followup",
        "life_share",
        "long_reconnect",
        "morning_wakeup",
        "night_goodnight",
        "reminder",
        "timer",
        "appointment",
        "custom",
    }
    return v if v in allowed else "custom"


def normalize_schedule_type(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in {"once", "interval", "daily", "weekly", "monthly"} else "once"


def _is_conversation_end(text: str) -> bool:
    return bool(_CONVERSATION_END_RE.search(str(text or "")))


def _is_short_followup_seed(seed: str, reason: str = "") -> bool:
    text = f"{seed or ''}\n{reason or ''}"
    return bool(_SHORT_FOLLOWUP_SEED_RE.search(text))


def _life_share_prompt_from_seed(base_seed: str, reason: str = "") -> str:
    seed = (base_seed or "").strip()
    if _is_short_followup_seed(seed, reason):
        return (
            "这是中层主动续接任务，不是短期补一句。最近可见 assistant 可能已经执行过下面的短期意图；"
            "到期时必须以最新可见对话为准，不能复述、改写或换标点重说该意图。"
            "如果最近 assistant 已经说过要做某件事，就推进到下一个明确状态、动作或转折，"
            "例如已经开始做、发现小插曲、换到一个新生活细节，或轻轻把话题转开；"
            "如果短期意图或最近 assistant 已经说“我去/我自己去/现在去/先去/准备去”某处或做某事，"
            "本条不得再次写成角色仍在原地重新宣布要去；必须写成已经到达、正在做、遇到新情况、完成一小步，"
            "或自然转到别的轻话题。"
            "新消息必须包含新的事实/动作/场景变化，不能只是耳朵、尾巴、叹气等同类小动作。"
            "为避免复述，短期意图原文不再提供；只读取最近可见对话来判断已经说过什么。"
        )
    return f"从上一段关系和话题自然延伸，分享一条角色自己的生活日常。参考意图：{seed[:400]}"


def _long_reconnect_prompt_from_seed(base_seed: str, reason: str = "") -> str:
    seed = (base_seed or "").strip()
    if _is_short_followup_seed(seed, reason):
        return (
            "隔了一段时间后，角色自然想起用户，发一条低压力的关心或回想。"
            "下面的短期意图只代表当时没等到用户回复时的一句补充，长间隔重连不得复述它；"
            "应从最新可见关系状态自然转到新的关心、回想或生活近况。"
            "为避免复述，短期意图原文不再提供；只读取最近可见对话来判断已经说过什么。"
        )
    return f"隔了一段时间后，角色自然想起用户，发一条低压力的关心或回想。参考意图：{seed[:400]}"


async def create_layered_auto_tasks(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    source_message_id: str,
    seed: str,
    reason: str = "",
) -> None:
    """普通回复后追加中/长层主动消息任务。

    短层仍由 `scheduled_followups` 负责。这两行按层级替换，避免热聊堆积过期的「两小时后」任务。
    """
    username = (username or "").strip()
    character_id = (character_id or "").strip()
    conversation_id = (conversation_id or "").strip()
    source_message_id = (source_message_id or "").strip()
    if not (username and character_id and conversation_id and source_message_id):
        return

    settings = await load_proactive_settings(username)
    if not settings.enabled:
        logger.info("[ProactiveTasks] skip layered auto tasks: proactive messages disabled username=%s", username)
        return

    base_seed = (seed or "").strip()
    if not base_seed:
        base_seed = "如果用户之后没有继续回复，角色可以自然分享一点自己的生活日常，不催促回应。"

    plans = [
        {
            "task_type": "life_share",
            "title": "生活日常",
            "delay": AUTO_LIFE_DELAY_SECONDS,
            "prompt": _life_share_prompt_from_seed(base_seed, reason),
            "style": "casual",
        },
        {
            "task_type": "long_reconnect",
            "title": "隔天想起你",
            "delay": AUTO_LONG_DELAY_SECONDS,
            "prompt": _long_reconnect_prompt_from_seed(base_seed, reason),
            "style": "gentle",
        },
    ]

    if _is_conversation_end(base_seed) or _is_conversation_end(reason):
        plans = [plan for plan in plans if plan.get("task_type") != "life_share"]

    db = get_database()
    await db.init()
    ts = now_ms()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            for plan in plans:
                await conn.execute(
                    """
                    UPDATE proactive_tasks
                       SET status='cancelled', updated_at_ms=?
                     WHERE username=? AND character_id=? AND conversation_id=?
                       AND source='auto' AND task_type=? AND status='active'
                    """,
                    (ts, username, character_id, conversation_id, plan["task_type"]),
                )
                await conn.execute(
                    """
                    INSERT INTO proactive_tasks (
                        id, username, character_id, conversation_id, source_message_id,
                        title, task_type, schedule_type, source, status, due_at_ms,
                        interval_seconds, time_of_day, timezone, days_json, jitter_minutes,
                        prompt, style, cancel_if_user_replies, metadata_json,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'once', 'auto', 'active', ?, 0, '', 'Asia/Shanghai', '[]', 0, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        f"pt_{uuid.uuid4().hex}",
                        username,
                        character_id,
                        conversation_id,
                        source_message_id,
                        plan["title"],
                        plan["task_type"],
                        ts + apply_frequency_to_delay_seconds(int(plan["delay"]), settings.frequency) * 1000,
                        plan["prompt"],
                        plan["style"],
                        json.dumps(
                            {
                                "reason": reason or "layered_auto",
                                "seed_kind": (
                                    "short_followup_context"
                                    if _is_short_followup_seed(base_seed, reason)
                                    else "open_life_context"
                                ),
                            },
                            ensure_ascii=False,
                        ),
                        ts,
                        ts,
                    ),
                )
            await conn.commit()
    except Exception as exc:
        logger.warning("[ProactiveTasks] create layered auto tasks failed: %s", exc)


async def process_due_proactive_tasks() -> int:
    db = get_database()
    await db.init()
    recovered = await recover_interrupted_processing_tasks()
    if recovered:
        logger.info("[ProactiveTasks] recovered %s interrupted processing task(s)", recovered)
    if is_shutdown_requested():
        return 0
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        async with conn.execute(
            """
            SELECT *
              FROM proactive_tasks
             WHERE status='active' AND due_at_ms <= ?
             ORDER BY due_at_ms ASC
             LIMIT ?
            """,
            (ts, MAX_DUE_TASKS),
        ) as cur:
            rows = await cur.fetchall()

    sent = 0
    for row in rows:
        if is_shutdown_requested():
            logger.info("[ProactiveTasks] shutdown requested; due tasks left active")
            break
        ok = await _process_one_task(dict(row))
        if ok:
            sent += 1
    return sent


async def recover_interrupted_processing_tasks() -> int:
    db = get_database()
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        cur = await conn.execute(
            """
            UPDATE proactive_tasks
               SET status='active',
                   due_at_ms=CASE WHEN due_at_ms > ? THEN due_at_ms ELSE ? END,
                   updated_at_ms=?
             WHERE status='processing'
            """,
            (ts, ts + 5000, ts),
        )
        await conn.commit()
        return int(cur.rowcount or 0)


async def _process_one_task(row: dict[str, Any]) -> bool:
    task_id = str(row.get("id") or "")
    if not task_id:
        return False
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        cur = await conn.execute(
            "UPDATE proactive_tasks SET status='processing', updated_at_ms=? WHERE id=? AND status='active'",
            (now_ms(), task_id),
        )
        await conn.commit()
        if int(cur.rowcount or 0) <= 0:
            return False
    if is_shutdown_requested():
        await _requeue_proactive_task(row)
        return False

    settings = await load_proactive_settings(str(row.get("username") or ""))
    if not settings.enabled:
        await _defer_proactive_task(row, "proactive_messages_disabled")
        return True

    task = await _build_scheduled_compatible_task(row)
    if not task:
        await _finish_proactive_task(row, "failed", "missing_conversation_or_message")
        return True

    try:
        from .scheduled_followup import (
            _append_assistant_message,
            _generate_followup_via_normal_pipeline,
            _latest_assistant_was_voice,
            _prepare_voice_for_scheduled_parts,
            _record_proactive_audit_only,
            _record_proactive_and_push_chat_complete,
            _validate_task_still_sendable,
        )

        async with galgame_locker.acquire(str(task.get("username") or ""), str(task.get("character_id") or "")):
            validation = await _validate_task_still_sendable(task)
            if not validation.get("ok"):
                await _finish_proactive_task(row, "skipped", str(validation.get("reason") or "not_sendable"))
                return True

            generated = await _generate_followup_via_normal_pipeline(task, validation.get("recent_messages") or [])
            if not generated.get("should_send"):
                await _finish_proactive_task(row, "skipped", str(generated.get("reason") or "director_cancelled"))
                return True

            if generated.get("persisted_by_normal_core"):
                if is_shutdown_requested():
                    await _requeue_proactive_task(row)
                    logger.info("[ProactiveTasks] shutdown before normal-core audit; requeued task=%s", task_id)
                    return True
                content = str(generated.get("message") or "").strip()
                message_ids = [
                    str(mid or "").strip()
                    for mid in (generated.get("assistant_message_ids") or [])
                    if str(mid or "").strip()
                ]
                if not content or not message_ids:
                    await _finish_proactive_task(row, "failed", "normal_core_missing_message_id")
                    return True
                segments = [p.strip() for p in re.split(r"\n+", content) if p.strip()] or [content]
                for idx, message_id in enumerate(message_ids):
                    await _record_proactive_audit_only(
                        task,
                        segments[idx] if idx < len(segments) else segments[-1],
                        message_id,
                    )
                await _finish_proactive_task(row, "sent", "", sent=True)
                logger.info("[ProactiveTasks] sent via normal core task=%s type=%s", task_id, row.get("task_type"))
                return True

            active_model = generated.get("active_model") if isinstance(generated.get("active_model"), dict) else {}
            from .scheduled_followup import clean_generated_proactive_content, _is_early_morning_time_mismatch

            content = clean_generated_proactive_content(str(generated.get("message") or "").strip(), active_model)
            if not content:
                await _finish_proactive_task(row, "skipped", "empty_message")
                return True
            if _is_early_morning_time_mismatch(content):
                await _finish_proactive_task(row, "skipped", "early_hours_morning_content")
                return True
            try:
                from .chat_modules.message_delivery_order import wait_for_conversation_delivery_slot

                can_deliver = await wait_for_conversation_delivery_slot(
                    task.get("username"),
                    task.get("character_id"),
                    task.get("conversation_id"),
                    reason="proactive_task",
                )
            except Exception as wait_exc:
                logger.debug("[ProactiveTasks] delivery wait skipped: %s", wait_exc)
                can_deliver = True
            if not can_deliver:
                await _defer_proactive_task(row, "delivery_order_timeout")
                return True

            validation = await _validate_task_still_sendable(task)
            if not validation.get("ok"):
                await _finish_proactive_task(row, "skipped", str(validation.get("reason") or "not_sendable_after_delivery_wait"))
                return True
            if is_shutdown_requested():
                await _requeue_proactive_task(row)
                logger.info("[ProactiveTasks] shutdown before append; requeued task=%s", task_id)
                return True
            should_follow_voice = _latest_assistant_was_voice(validation.get("recent_messages") or [])
            message_parts = await _append_assistant_message(task, content)
            if not message_parts:
                await _finish_proactive_task(row, "failed", "persist_failed")
                return True
            voice_results_by_message_id = {}
            if should_follow_voice:
                voice_results_by_message_id = await _prepare_voice_for_scheduled_parts(
                    task,
                    message_parts,
                    generated.get("request") if hasattr(generated.get("request"), "messages") else None,
                )
            for message_id, segment in message_parts:
                await _record_proactive_and_push_chat_complete(
                    task,
                    segment,
                    message_id,
                    voice_result=voice_results_by_message_id.get(message_id),
                )
            await _finish_proactive_task(row, "sent", "", sent=True)
            logger.info("[ProactiveTasks] sent task=%s type=%s", task_id, row.get("task_type"))
            return True
    except asyncio.CancelledError:
        if is_shutdown_requested():
            await _requeue_proactive_task(row)
            logger.info("[ProactiveTasks] shutdown requeued processing task=%s", task_id)
            return True
        raise
    except Exception as exc:
        logger.warning("[ProactiveTasks] task failed id=%s: %s", task_id, exc)
        await _finish_proactive_task(row, "failed", str(exc)[:300])
        return True


async def _requeue_proactive_task(row: dict[str, Any]) -> None:
    db = get_database()
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            UPDATE proactive_tasks
               SET status='active',
                   due_at_ms=CASE WHEN due_at_ms > ? THEN due_at_ms ELSE ? END,
                   updated_at_ms=?
             WHERE id=? AND status='processing'
            """,
            (ts, ts + 5000, ts, row.get("id")),
        )
        await conn.commit()


async def _defer_proactive_task(row: dict[str, Any], reason: str) -> None:
    db = get_database()
    ts = now_ms()
    metadata = {}
    try:
        metadata = json.loads(row.get("metadata_json") or "{}")
        if not isinstance(metadata, dict):
            metadata = {}
    except Exception:
        metadata = {}
    metadata["last_result"] = "deferred"
    metadata["last_reason"] = reason[:300]
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            UPDATE proactive_tasks
               SET status='active', due_at_ms=?, metadata_json=?, updated_at_ms=?
             WHERE id=?
            """,
            (ts + 60 * 60 * 1000, json.dumps(metadata, ensure_ascii=False), ts, row.get("id")),
        )
        await conn.commit()


async def _build_scheduled_compatible_task(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    username = str(row.get("username") or "")
    character_id = str(row.get("character_id") or "")
    conversation_id = str(row.get("conversation_id") or "")
    source_message_id = str(row.get("source_message_id") or "")
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        if not conversation_id:
            async with conn.execute(
                """
                SELECT c.id
                  FROM conversations c
                  JOIN users u ON u.id=c.user_id
                 WHERE u.username=? AND c.character_id=? AND COALESCE(c.is_hidden,0)=0
                 ORDER BY c.timestamp DESC
                 LIMIT 1
                """,
                (username, character_id),
            ) as cur:
                conv = await cur.fetchone()
            if not conv:
                return None
            conversation_id = conv[0]
        if not source_message_id:
            async with conn.execute(
                """
                SELECT message_id
                  FROM messages
                 WHERE conversation_id=? AND role='assistant'
                   AND deleted_at IS NULL AND COALESCE(is_hidden,0)=0
                 ORDER BY COALESCE(sequence_number,0) DESC, COALESCE(timestamp,0) DESC
                 LIMIT 1
                """,
                (conversation_id,),
            ) as cur:
                msg = await cur.fetchone()
            if not msg:
                return None
            source_message_id = msg[0]

    task_type = normalize_task_type(str(row.get("task_type") or "custom"))
    prompt = str(row.get("prompt") or "").strip()
    title = str(row.get("title") or "").strip()
    seed = prompt or title or "角色按用户设定的定时任务主动发来一条自然消息。"
    return {
        "id": str(row.get("id") or ""),
        "username": username,
        "character_id": character_id,
        "conversation_id": conversation_id,
        "source_message_id": source_message_id,
        "cancel_if_user_replies": int(row.get("cancel_if_user_replies") or 0),
        "allow_reschedule_after_send": 0,
        "seed": f"[{task_type}] {seed}",
        "reason": f"proactive_task:{task_type}",
        "pressure_level": "low",
        "chain_id": str(row.get("id") or ""),
        "chain_count": int(row.get("run_count") or 0),
        "metadata_json": row.get("metadata_json") or "{}",
    }


async def _finish_proactive_task(row: dict[str, Any], result: str, reason: str = "", *, sent: bool = False) -> None:
    db = get_database()
    schedule_type = normalize_schedule_type(str(row.get("schedule_type") or "once"))
    next_status = "completed" if schedule_type == "once" else "active"
    if result in {"failed", "skipped"} and schedule_type == "once":
        next_status = result
    next_due = _next_due_ms(row) if schedule_type in {"interval", "daily", "weekly", "monthly"} else int(row.get("due_at_ms") or now_ms())
    ts = now_ms()
    metadata = {}
    try:
        metadata = json.loads(row.get("metadata_json") or "{}")
        if not isinstance(metadata, dict):
            metadata = {}
    except Exception:
        metadata = {}
    metadata["last_result"] = result
    if reason:
        metadata["last_reason"] = reason[:300]
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            UPDATE proactive_tasks
               SET status=?, due_at_ms=?, last_run_at_ms=?,
                   run_count=run_count+?, metadata_json=?, updated_at_ms=?
             WHERE id=?
            """,
            (
                next_status,
                next_due,
                ts,
                1 if sent else 0,
                json.dumps(metadata, ensure_ascii=False),
                ts,
                row.get("id"),
            ),
        )
        await conn.commit()


def _next_due_ms(row: dict[str, Any]) -> int:
    schedule_type = normalize_schedule_type(str(row.get("schedule_type") or "once"))
    ts = now_ms()
    if schedule_type == "interval":
        interval = max(60, int(row.get("interval_seconds") or 3600))
        return _apply_jitter_ms(ts + interval * 1000, row)

    tz_name = str(row.get("timezone") or "Asia/Shanghai")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    hhmm = str(row.get("time_of_day") or "08:00")
    try:
        hour, minute = [int(x) for x in hhmm.split(":", 1)]
    except Exception:
        hour, minute = 8, 0
    now_local = datetime.now(tz)
    due = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= now_local:
        due += timedelta(days=1)
    if schedule_type == "weekly":
        try:
            days = json.loads(row.get("days_json") or "[]")
        except Exception:
            days = []
        allowed = {int(x) for x in days if isinstance(x, int) or str(x).isdigit()}
        if allowed:
            while due.weekday() not in allowed:
                due += timedelta(days=1)
    elif schedule_type == "monthly":
        try:
            days = json.loads(row.get("days_json") or "[]")
        except Exception:
            days = []
        month_day = 1
        for item in days:
            if isinstance(item, int) or str(item).isdigit():
                month_day = max(1, min(31, int(item)))
                break
        due = _monthly_due_after(now_local, hour, minute, month_day)
    return _apply_jitter_ms(int(due.timestamp() * 1000), row)


def _monthly_due_after(now_local: datetime, hour: int, minute: int, month_day: int) -> datetime:
    year = now_local.year
    month = now_local.month
    while True:
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
        last_day = (datetime(next_year, next_month, 1, tzinfo=now_local.tzinfo) - timedelta(days=1)).day
        due = now_local.replace(
            year=year,
            month=month,
            day=min(month_day, last_day),
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if due > now_local:
            return due
        year, month = next_year, next_month


def _apply_jitter_ms(due_at_ms: int, row: dict[str, Any]) -> int:
    try:
        jitter_minutes = max(0, int(row.get("jitter_minutes") or 0))
    except Exception:
        jitter_minutes = 0
    if jitter_minutes <= 0:
        return due_at_ms
    jitter_ms = random.randint(-jitter_minutes * 60_000, jitter_minutes * 60_000)
    return max(now_ms() + 60_000, due_at_ms + jitter_ms)
