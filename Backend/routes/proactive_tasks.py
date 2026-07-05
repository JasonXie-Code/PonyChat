from __future__ import annotations

import json
import random
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import aiosqlite
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..db import get_database
from ..proactive_tasks import normalize_schedule_type, normalize_task_type
from .auth import auth_token_verify


router = APIRouter(prefix="/api/proactive/tasks", tags=["ProactiveTasks"])


class ProactiveTaskBody(BaseModel):
    character_id: str
    conversation_id: str = ""
    title: str = ""
    task_type: str = "custom"
    schedule_type: str = "once"
    due_at_ms: Optional[int] = None
    interval_seconds: int = 0
    time_of_day: str = ""
    timezone: str = "Asia/Shanghai"
    days: list[int] = []
    jitter_minutes: int = 0
    prompt: str = ""
    style: str = "gentle"
    enabled: bool = True
    cancel_if_user_replies: bool = False


async def _auth_username(x_chat_auth: Optional[str]) -> Optional[str]:
    return await auth_token_verify((x_chat_auth or "").strip())


def _now_ms() -> int:
    return int(time.time() * 1000)


def _initial_due_ms(body: ProactiveTaskBody) -> int:
    now = _now_ms()
    schedule_type = normalize_schedule_type(body.schedule_type)
    explicit = int(body.due_at_ms or 0)
    if explicit > 0:
        return explicit
    if schedule_type == "interval":
        return _apply_jitter_ms(now + max(60, int(body.interval_seconds or 3600)) * 1000, body.jitter_minutes)
    if schedule_type in {"daily", "weekly", "monthly"}:
        try:
            tz = ZoneInfo(body.timezone.strip() or "Asia/Shanghai")
        except Exception:
            tz = ZoneInfo("Asia/Shanghai")
        try:
            hour, minute = [int(x) for x in (body.time_of_day or "08:00").split(":", 1)]
        except Exception:
            hour, minute = 8, 0
        local_now = datetime.now(tz)
        due = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= local_now:
            due += timedelta(days=1)
        if schedule_type == "weekly" and body.days:
            allowed = {int(x) for x in body.days}
            while due.weekday() not in allowed:
                due += timedelta(days=1)
        elif schedule_type == "monthly":
            month_day = 1
            for item in body.days:
                try:
                    month_day = max(1, min(31, int(item)))
                    break
                except (TypeError, ValueError):
                    continue
            due = _monthly_due_after(local_now, hour, minute, month_day)
        return _apply_jitter_ms(int(due.timestamp() * 1000), body.jitter_minutes)
    return now + 60_000


def _monthly_due_after(local_now: datetime, hour: int, minute: int, month_day: int) -> datetime:
    year = local_now.year
    month = local_now.month
    while True:
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
        last_day = (datetime(next_year, next_month, 1, tzinfo=local_now.tzinfo) - timedelta(days=1)).day
        due = local_now.replace(
            year=year,
            month=month,
            day=min(month_day, last_day),
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if due > local_now:
            return due
        year, month = next_year, next_month


def _apply_jitter_ms(due_at_ms: int, jitter_minutes: int) -> int:
    try:
        jitter = max(0, int(jitter_minutes or 0))
    except Exception:
        jitter = 0
    if jitter <= 0:
        return due_at_ms
    jitter_ms = random.randint(-jitter * 60_000, jitter * 60_000)
    return max(_now_ms() + 60_000, due_at_ms + jitter_ms)


def _row_to_task(row: aiosqlite.Row | tuple) -> dict[str, Any]:
    keys = [
        "id", "username", "character_id", "conversation_id", "source_message_id",
        "title", "task_type", "schedule_type", "source", "status", "due_at_ms",
        "interval_seconds", "time_of_day", "timezone", "days_json", "jitter_minutes",
        "prompt", "style", "cancel_if_user_replies", "metadata_json",
        "last_run_at_ms", "run_count", "created_at_ms", "updated_at_ms",
    ]
    d = dict(zip(keys, row))
    try:
        d["days"] = json.loads(d.pop("days_json") or "[]")
    except Exception:
        d["days"] = []
    try:
        d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
    except Exception:
        d["metadata"] = {}
    d["enabled"] = d["status"] == "active"
    return d


@router.get("")
async def list_tasks(
    character_id: Optional[str] = None,
    include_auto: bool = False,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    username = await _auth_username(x_chat_auth)
    if not username:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})
    db = get_database()
    await db.init()
    where = ["username=?", "status != 'cancelled'"]
    params: list[Any] = [username]
    if character_id:
        where.append("character_id=?")
        params.append(character_id)
    if not include_auto:
        where.append("source='user'")
    sql = f"""
        SELECT id, username, character_id, conversation_id, source_message_id,
               title, task_type, schedule_type, source, status, due_at_ms,
               interval_seconds, time_of_day, timezone, days_json, jitter_minutes,
               prompt, style, cancel_if_user_replies, metadata_json,
               last_run_at_ms, run_count, created_at_ms, updated_at_ms
          FROM proactive_tasks
         WHERE {' AND '.join(where)}
         ORDER BY status ASC, due_at_ms ASC
         LIMIT 200
    """
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
    return {"status": "ok", "tasks": [_row_to_task(r) for r in rows]}


@router.post("")
async def create_task(
    body: ProactiveTaskBody,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    username = await _auth_username(x_chat_auth)
    if not username:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})
    now = _now_ms()
    due = _initial_due_ms(body)
    task_id = f"pt_{uuid.uuid4().hex}"
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            INSERT INTO proactive_tasks (
                id, username, character_id, conversation_id, source_message_id,
                title, task_type, schedule_type, source, status, due_at_ms,
                interval_seconds, time_of_day, timezone, days_json, jitter_minutes,
                prompt, style, cancel_if_user_replies, metadata_json,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, '', ?, ?, ?, 'user', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
            """,
            (
                task_id,
                username,
                body.character_id.strip(),
                body.conversation_id.strip(),
                body.title.strip()[:120],
                normalize_task_type(body.task_type),
                normalize_schedule_type(body.schedule_type),
                "active" if body.enabled else "paused",
                due,
                max(0, int(body.interval_seconds or 0)),
                body.time_of_day.strip()[:5],
                body.timezone.strip() or "Asia/Shanghai",
                json.dumps(body.days or [], ensure_ascii=False),
                max(0, int(body.jitter_minutes or 0)),
                body.prompt.strip()[:1000],
                body.style.strip()[:40] or "gentle",
                1 if body.cancel_if_user_replies else 0,
                now,
                now,
            ),
        )
        await conn.commit()
    return {"status": "ok", "id": task_id}


@router.put("/{task_id}")
async def update_task(
    task_id: str,
    body: ProactiveTaskBody,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    username = await _auth_username(x_chat_auth)
    if not username:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        cur = await conn.execute(
            """
            UPDATE proactive_tasks
               SET character_id=?, conversation_id=?, title=?, task_type=?,
                   schedule_type=?, status=?, due_at_ms=?, interval_seconds=?,
                   time_of_day=?, timezone=?, days_json=?, jitter_minutes=?,
                   prompt=?, style=?, cancel_if_user_replies=?, updated_at_ms=?
             WHERE id=? AND username=? AND source='user'
            """,
            (
                body.character_id.strip(),
                body.conversation_id.strip(),
                body.title.strip()[:120],
                normalize_task_type(body.task_type),
                normalize_schedule_type(body.schedule_type),
                "active" if body.enabled else "paused",
                _initial_due_ms(body),
                max(0, int(body.interval_seconds or 0)),
                body.time_of_day.strip()[:5],
                body.timezone.strip() or "Asia/Shanghai",
                json.dumps(body.days or [], ensure_ascii=False),
                max(0, int(body.jitter_minutes or 0)),
                body.prompt.strip()[:1000],
                body.style.strip()[:40] or "gentle",
                1 if body.cancel_if_user_replies else 0,
                _now_ms(),
                task_id,
                username,
            ),
        )
        await conn.commit()
        if int(cur.rowcount or 0) <= 0:
            return JSONResponse(status_code=404, content={"status": "error", "message": "not_found"})
    return {"status": "ok"}


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    username = await _auth_username(x_chat_auth)
    if not username:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        cur = await conn.execute(
            "UPDATE proactive_tasks SET status='cancelled', updated_at_ms=? WHERE id=? AND username=? AND source='user'",
            (_now_ms(), task_id, username),
        )
        await conn.commit()
        if int(cur.rowcount or 0) <= 0:
            return JSONResponse(status_code=404, content={"status": "error", "message": "not_found"})
    return {"status": "ok"}
