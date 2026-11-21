from __future__ import annotations

import json
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import aiosqlite

from .config import logger
from .db import get_database
from .galgame import generate_message_id
from .proactive_settings import apply_frequency_to_delay_seconds, load_proactive_settings
from .proactive_send_guard import proactive_reply_limit_reached
from .relationship_stages import normalize_relationship_stage
from .scheduled_followup import (
    _generate_followup_via_normal_pipeline,
    _latest_assistant_was_voice,
    _prepare_voice_for_scheduled_parts,
    _record_proactive_audit_only,
    _record_proactive_and_push_chat_complete,
    clean_generated_proactive_content,
)
from .shutdown_state import is_shutdown_requested
from .websocket import galgame_locker


LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
MAX_EVALUATIONS_PER_TICK = 20
MAX_DUE_ATTEMPTS_PER_TICK = 8
MAX_LONG_PROACTIVE_PER_USER_PER_DAY = 3
MAX_LONG_PROACTIVE_PER_CHARACTER_PER_DAY = 1
QUIET_HOUR_START = 0
QUIET_HOUR_END = 8

ABSENCE_START_SECONDS = 18 * 60 * 60
LONG_ABSENCE_MAX_DAY = 7
DORMANT_INTERVAL_SECONDS = 7 * 24 * 60 * 60

_CONVERSATION_END_RE = re.compile(
    r"(休息了|去休息|我要睡|我睡了|睡觉了|准备睡|该睡|晚安|明天再来|明天聊|明天见|先不聊|不聊了|下线了|拜拜|再见|别打扰|不要打扰|先忙)"
)


def now_ms() -> int:
    return int(time.time() * 1000)


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        data = json.loads(value or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _content_signature(text: str) -> str:
    raw = re.sub(r"\s+", "", str(text or ""))
    raw = re.sub(r"[，。！？、,.!?~～…（）()「」『』\"'：:；;]", "", raw)
    return raw[:48]


def _is_conversation_end(text: str) -> bool:
    return bool(_CONVERSATION_END_RE.search(str(text or "")))


def _state_for_silence(silence_seconds: int) -> str:
    if silence_seconds < 30 * 60:
        return "active_chatting"
    if silence_seconds < ABSENCE_START_SECONDS:
        return "short_silence"
    day = max(1, int(silence_seconds // (24 * 60 * 60)) + 1)
    if day <= 3:
        return f"absent_day_{day}"
    if day <= LONG_ABSENCE_MAX_DAY:
        return "long_absence"
    return "dormant"


def _next_day_delay_seconds(day_index: int, frequency: str) -> int:
    if frequency == "low":
        schedule = {0: 24 * 60 * 60, 1: 48 * 60 * 60, 2: 4 * 24 * 60 * 60}
    elif frequency == "high":
        schedule = {
            0: 18 * 60 * 60,
            1: 24 * 60 * 60,
            2: 24 * 60 * 60,
            3: 36 * 60 * 60,
            4: 48 * 60 * 60,
        }
    else:
        schedule = {
            0: 24 * 60 * 60,
            1: 30 * 60 * 60,
            2: 36 * 60 * 60,
            3: 48 * 60 * 60,
            4: 60 * 60 * 60,
        }
    return schedule.get(day_index, DORMANT_INTERVAL_SECONDS)


def _next_evaluation_delay_seconds(state: str) -> int:
    if state == "active_chatting":
        return 30 * 60
    if state == "short_silence":
        return 60 * 60
    if state.startswith("absent_day_"):
        return 3 * 60 * 60
    if state == "long_absence":
        return 6 * 60 * 60
    return 24 * 60 * 60


def _motivation_for_day(day_index: int, history: list[Any], relationship_stage: str) -> str:
    relationship_stage = str(relationship_stage or "uncertain").strip().lower()
    candidates = [
        "thought_of_user",
        "life_share",
        "memory_callback",
        "care_check",
        "quiet_waiting",
        "reentry_invite",
    ]
    if relationship_stage in {"flirting", "committed_partner", "intimate_partner"}:
        candidates.insert(1, "playful_ping")
    preferred = {
        0: "thought_of_user",
        1: "life_share",
        2: "care_check",
        3: "quiet_waiting",
        4: "memory_callback",
    }.get(day_index, "reentry_invite")
    recent = [str(x) for x in history[-3:]]
    if preferred not in recent:
        return preferred
    for item in candidates:
        if item not in recent:
            return item
    return preferred


def _prompt_seed(motivation: str, day_index: int, relationship_stage: str) -> str:
    relationship_stage = str(relationship_stage or "uncertain").strip().lower()
    delivery_context = (
        "这是一条角色主动发给用户的消息；发送时用户仍未回复、未出现、未上线，"
        "不要写成角色已经看到用户回来、走近或正在和角色面对面，"
        "也不要假设用户已经忙完或已经看到这条消息。"
    )
    pressure = f"{delivery_context} 保持低压力，不催促用户回复。"
    if relationship_stage in {"broken_up", "in_conflict", "mutual_dislike", "hurtful_dynamic"}:
        return (
            "用户已经一段时间没回复；但当前关系是分手、争吵、互相看不顺眼或互相伤害一类的负向关系。"
            "角色发消息时要保持低压力和边界感，可以表达冷静后的想法、道歉、希望停止互相伤害、约定晚点再谈或保留距离，"
            f"不要写成暧昧、想念轰炸、撒娇催回或默认已经和好。{delivery_context}"
        )
    if relationship_stage in {"mentor_student", "trusted_companion", "family_like"}:
        return (
            "用户已经一段时间没回复；当前关系是师生、可信同伴或家人般的正向非恋爱关系。"
            "角色可以低压力分享近况、关心、提醒、提供支持或留下一个回来继续处理事情的入口，"
            f"但不要写成恋爱想念、暧昧试探或伴侣亲密。{delivery_context}"
        )
    if motivation == "life_share":
        return f"用户已经一段时间没回复；角色分享一小段自己的生活状态或刚发生的小事，{pressure}"
    if motivation == "memory_callback":
        return f"用户已经一段时间没回复；角色轻轻想起之前对话里一个真实话题，不编造用户没说过的事，{pressure}"
    if motivation == "care_check":
        return f"用户已经连续第 {day_index + 1} 天没有回来；角色低压力关心用户近况，避免质问或道歉轰炸。"
    if motivation == "playful_ping":
        return f"用户已经一段时间没回复；角色用符合自身性格的轻松方式戳一下用户，保留玩笑感，{pressure}"
    if motivation == "quiet_waiting":
        return f"用户已经几天没回来；角色表达自己还在，但会安静等用户忙完，{pressure}"
    if motivation == "reentry_invite":
        return f"用户长期没回来；角色给用户一个很轻的回来入口，短句，不表现得沉重。"
    if relationship_stage in {"committed_partner", "intimate_partner"}:
        return f"用户已经一段时间没回复；角色自然想起用户，可以轻微表达想念，但不要施压。{delivery_context}"
    return f"用户已经一段时间没回复；角色自然想起用户，发一条低压力消息。{delivery_context}"


def _is_quiet_hour(ts_ms: int) -> bool:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=LOCAL_TIMEZONE)
    return QUIET_HOUR_START <= dt.hour < QUIET_HOUR_END


def _next_allowed_daytime_ms(ts_ms: int) -> int:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=LOCAL_TIMEZONE)
    target = dt.replace(hour=QUIET_HOUR_END, minute=random.randint(5, 45), second=0, microsecond=0)
    if target <= dt:
        target += timedelta(days=1)
    return int(target.timestamp() * 1000)


@dataclass
class PresenceUpdate:
    username: str
    character_id: str
    conversation_id: str
    last_user_message_id: str = ""
    last_user_at_ms: int = 0
    last_user_text: str = ""
    last_assistant_message_id: str = ""
    last_assistant_at_ms: int = 0
    relationship_stage: str = ""


async def ensure_long_proactive_tables() -> None:
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS relationship_presence_states (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'active_chatting',
                relationship_stage TEXT NOT NULL DEFAULT 'uncertain',
                relationship_page_json TEXT NOT NULL DEFAULT '{}',
                relationship_page_updated_at_ms INTEGER NOT NULL DEFAULT 0,
                relationship_page_source_json TEXT NOT NULL DEFAULT '{}',
                character_initiative INTEGER NOT NULL DEFAULT 45,
                user_proactive_frequency TEXT NOT NULL DEFAULT 'normal',
                last_user_message_id TEXT DEFAULT '',
                last_user_at_ms INTEGER DEFAULT 0,
                last_assistant_message_id TEXT DEFAULT '',
                last_assistant_at_ms INTEGER DEFAULT 0,
                last_proactive_message_id TEXT DEFAULT '',
                last_proactive_at_ms INTEGER DEFAULT 0,
                absence_started_at_ms INTEGER DEFAULT 0,
                silence_hours REAL DEFAULT 0,
                consecutive_proactive_days INTEGER NOT NULL DEFAULT 0,
                total_proactive_in_absence INTEGER NOT NULL DEFAULT 0,
                last_motivation TEXT DEFAULT '',
                motivation_history_json TEXT NOT NULL DEFAULT '[]',
                content_signature_history_json TEXT NOT NULL DEFAULT '[]',
                cooldown_until_ms INTEGER DEFAULT 0,
                next_evaluation_at_ms INTEGER DEFAULT 0,
                user_ended_conversation INTEGER NOT NULL DEFAULT 0,
                user_do_not_disturb_until_ms INTEGER DEFAULT 0,
                disabled_reason TEXT DEFAULT '',
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_presence_pair
                ON relationship_presence_states(username, character_id);
            CREATE INDEX IF NOT EXISTS idx_relationship_presence_eval
                ON relationship_presence_states(next_evaluation_at_ms);
            CREATE TABLE IF NOT EXISTS proactive_campaigns (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT '',
                campaign_type TEXT NOT NULL DEFAULT 'absence_reconnect',
                status TEXT NOT NULL DEFAULT 'active',
                started_at_ms INTEGER NOT NULL,
                ended_at_ms INTEGER DEFAULT 0,
                current_day_index INTEGER NOT NULL DEFAULT 0,
                max_day_index INTEGER NOT NULL DEFAULT 7,
                cadence_policy TEXT NOT NULL DEFAULT 'adaptive',
                pressure_ceiling TEXT NOT NULL DEFAULT 'low',
                relationship_stage_at_start TEXT DEFAULT 'uncertain',
                seed_context_json TEXT NOT NULL DEFAULT '{}',
                last_touch_at_ms INTEGER DEFAULT 0,
                next_touch_due_at_ms INTEGER DEFAULT 0,
                next_touch_window_start_ms INTEGER DEFAULT 0,
                next_touch_window_end_ms INTEGER DEFAULT 0,
                stop_if_user_replies INTEGER NOT NULL DEFAULT 1,
                stop_reason TEXT DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_proactive_campaigns_active
                ON proactive_campaigns(status, next_touch_due_at_ms);
            CREATE INDEX IF NOT EXISTS idx_proactive_campaigns_pair
                ON proactive_campaigns(username, character_id, status);
            CREATE TABLE IF NOT EXISTS proactive_touch_attempts (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT '',
                due_at_ms INTEGER NOT NULL,
                window_start_ms INTEGER NOT NULL,
                window_end_ms INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                motivation TEXT NOT NULL DEFAULT '',
                pressure_level TEXT NOT NULL DEFAULT 'low',
                topic_source TEXT NOT NULL DEFAULT '',
                prompt_seed TEXT NOT NULL DEFAULT '',
                generated_message_id TEXT DEFAULT '',
                generated_content TEXT DEFAULT '',
                content_signature TEXT DEFAULT '',
                skip_reason TEXT DEFAULT '',
                failure_reason TEXT DEFAULT '',
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_proactive_touch_attempts_due
                ON proactive_touch_attempts(status, due_at_ms);
            CREATE INDEX IF NOT EXISTS idx_proactive_touch_attempts_campaign
                ON proactive_touch_attempts(campaign_id, status);
            """
        )
        async with conn.execute("PRAGMA table_info(relationship_presence_states)") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        if columns and "relationship_stage" not in columns:
            await conn.execute(
                "ALTER TABLE relationship_presence_states "
                "ADD COLUMN relationship_stage TEXT NOT NULL DEFAULT 'uncertain'"
            )
        for column, definition in [
            ("relationship_page_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("relationship_page_updated_at_ms", "INTEGER NOT NULL DEFAULT 0"),
            ("relationship_page_source_json", "TEXT NOT NULL DEFAULT '{}'"),
        ]:
            if columns and column not in columns:
                await conn.execute(
                    f"ALTER TABLE relationship_presence_states ADD COLUMN {column} {definition}"
                )
        await conn.commit()


async def record_conversation_presence(update: PresenceUpdate) -> None:
    if not update.username or not update.character_id or not update.conversation_id:
        return
    await ensure_long_proactive_tables()
    settings = await load_proactive_settings(update.username)
    ts = now_ms()
    user_end = 1 if _is_conversation_end(update.last_user_text) else 0
    state = "active_chatting"
    next_eval = ts + _next_evaluation_delay_seconds(state) * 1000
    has_relationship_stage = bool(str(update.relationship_stage or "").strip())
    relationship_stage = (
        normalize_relationship_stage(update.relationship_stage)
        if has_relationship_stage
        else "uncertain"
    )
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            INSERT INTO relationship_presence_states (
                id, username, character_id, conversation_id, state, relationship_stage,
                user_proactive_frequency, last_user_message_id, last_user_at_ms,
                last_assistant_message_id, last_assistant_at_ms,
                absence_started_at_ms, silence_hours, consecutive_proactive_days,
                total_proactive_in_absence, next_evaluation_at_ms,
                user_ended_conversation, disabled_reason, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?, '', ?, ?)
            ON CONFLICT(username, character_id) DO UPDATE SET
                conversation_id=excluded.conversation_id,
                state=excluded.state,
                relationship_stage=CASE
                    WHEN ? THEN excluded.relationship_stage
                    ELSE relationship_presence_states.relationship_stage
                END,
                user_proactive_frequency=excluded.user_proactive_frequency,
                last_user_message_id=CASE WHEN excluded.last_user_at_ms > 0 THEN excluded.last_user_message_id ELSE relationship_presence_states.last_user_message_id END,
                last_user_at_ms=MAX(COALESCE(relationship_presence_states.last_user_at_ms, 0), excluded.last_user_at_ms),
                last_assistant_message_id=CASE WHEN excluded.last_assistant_at_ms > 0 THEN excluded.last_assistant_message_id ELSE relationship_presence_states.last_assistant_message_id END,
                last_assistant_at_ms=MAX(COALESCE(relationship_presence_states.last_assistant_at_ms, 0), excluded.last_assistant_at_ms),
                absence_started_at_ms=0,
                silence_hours=0,
                consecutive_proactive_days=0,
                total_proactive_in_absence=0,
                next_evaluation_at_ms=excluded.next_evaluation_at_ms,
                user_ended_conversation=excluded.user_ended_conversation,
                disabled_reason='',
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                f"rps_{uuid.uuid4().hex}",
                update.username,
                update.character_id,
                update.conversation_id,
                state,
                relationship_stage,
                settings.frequency,
                update.last_user_message_id,
                int(update.last_user_at_ms or 0),
                update.last_assistant_message_id,
                int(update.last_assistant_at_ms or 0),
                next_eval,
                user_end,
                ts,
                ts,
                1 if has_relationship_stage else 0,
            ),
        )
        if update.last_user_at_ms > 0:
            await _cancel_absence_locked(conn, update.username, update.character_id, "user_replied")
        await conn.commit()


async def record_presence_from_saved_messages(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
    relationship_stage: str = "",
) -> None:
    visible = [
        m for m in (messages or [])
        if m.get("role") in {"user", "assistant"} and not m.get("isHidden") and not m.get("is_hidden")
    ]
    if not visible:
        return
    last_user = next((m for m in reversed(visible) if m.get("role") == "user"), None)
    last_assistant = next((m for m in reversed(visible) if m.get("role") == "assistant"), None)
    await record_conversation_presence(
        PresenceUpdate(
            username=username,
            character_id=character_id,
            conversation_id=conversation_id,
            last_user_message_id=str((last_user or {}).get("message_id") or ""),
            last_user_at_ms=int((last_user or {}).get("timestamp") or 0),
            last_user_text=str((last_user or {}).get("content") or ""),
            last_assistant_message_id=str((last_assistant or {}).get("message_id") or ""),
            last_assistant_at_ms=int((last_assistant or {}).get("timestamp") or 0),
            relationship_stage=relationship_stage,
        )
    )


async def _cancel_absence_locked(conn: aiosqlite.Connection, username: str, character_id: str, reason: str) -> None:
    ts = now_ms()
    await conn.execute(
        """
        UPDATE proactive_campaigns
           SET status='stopped', ended_at_ms=?, stop_reason=?, updated_at_ms=?
         WHERE username=? AND character_id=? AND status='active'
           AND campaign_type='absence_reconnect'
        """,
        (ts, reason, ts, username, character_id),
    )
    await conn.execute(
        """
        UPDATE proactive_touch_attempts
           SET status='cancelled', skip_reason=?, updated_at_ms=?
         WHERE username=? AND character_id=? AND status='pending'
        """,
        (reason, ts, username, character_id),
    )


async def process_long_proactive_tick() -> dict[str, int]:
    await ensure_long_proactive_tables()
    recovered = await recover_interrupted_touch_attempts()
    if recovered:
        logger.info("[LongProactive] recovered %s interrupted processing attempt(s)", recovered)
    if is_shutdown_requested():
        return {"evaluated": 0, "sent": 0}
    evaluated = await _evaluate_due_presence_states()
    if is_shutdown_requested():
        return {"evaluated": evaluated, "sent": 0}
    sent = await _process_due_touch_attempts()
    return {"evaluated": evaluated, "sent": sent}


async def recover_interrupted_touch_attempts() -> int:
    db = get_database()
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        cur = await conn.execute(
            """
            UPDATE proactive_touch_attempts
               SET status='pending',
                   due_at_ms=CASE WHEN due_at_ms > ? THEN due_at_ms ELSE ? END,
                   updated_at_ms=?
             WHERE status='processing'
               AND COALESCE(generated_message_id, '') = ''
            """,
            (ts, ts + 5000, ts),
        )
        await conn.commit()
        return int(cur.rowcount or 0)


async def _evaluate_due_presence_states() -> int:
    ts = now_ms()
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT *
              FROM relationship_presence_states
             WHERE next_evaluation_at_ms <= ?
             ORDER BY next_evaluation_at_ms ASC
             LIMIT ?
            """,
            (ts, MAX_EVALUATIONS_PER_TICK),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    count = 0
    for row in rows:
        if is_shutdown_requested():
            logger.info("[LongProactive] shutdown requested; remaining presence evaluations deferred")
            break
        if await _evaluate_one_presence(row):
            count += 1
    return count


async def _evaluate_one_presence(row: dict[str, Any]) -> bool:
    username = str(row.get("username") or "")
    character_id = str(row.get("character_id") or "")
    if not username or not character_id:
        return False
    settings = await load_proactive_settings(username)
    ts = now_ms()
    if not settings.enabled:
        await _update_presence_disabled(row, "proactive_messages_disabled")
        return True
    last_user_at = int(row.get("last_user_at_ms") or 0)
    if last_user_at <= 0:
        await _bump_presence_eval(row, ts + 24 * 60 * 60 * 1000)
        return True
    silence_seconds = max(0, int((ts - last_user_at) / 1000))
    state = _state_for_silence(silence_seconds)
    if int(row.get("user_ended_conversation") or 0):
        await _update_presence_state(row, state, silence_seconds, ts + 24 * 60 * 60 * 1000)
        return True
    if silence_seconds < ABSENCE_START_SECONDS:
        await _update_presence_state(row, state, silence_seconds, ts + _next_evaluation_delay_seconds(state) * 1000)
        return True
    if int(row.get("cooldown_until_ms") or 0) > ts:
        await _update_presence_state(row, state, silence_seconds, int(row.get("cooldown_until_ms") or ts))
        return True
    await _ensure_absence_campaign(row, state, settings.frequency)
    await _update_presence_state(row, state, silence_seconds, ts + _next_evaluation_delay_seconds(state) * 1000)
    return True


async def _update_presence_disabled(row: dict[str, Any], reason: str) -> None:
    db = get_database()
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            UPDATE relationship_presence_states
               SET disabled_reason=?, next_evaluation_at_ms=?, updated_at_ms=?
             WHERE id=?
            """,
            (reason, ts + 24 * 60 * 60 * 1000, ts, row.get("id")),
        )
        await conn.commit()


async def _bump_presence_eval(row: dict[str, Any], next_eval: int) -> None:
    db = get_database()
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            "UPDATE relationship_presence_states SET next_evaluation_at_ms=?, updated_at_ms=? WHERE id=?",
            (next_eval, ts, row.get("id")),
        )
        await conn.commit()


async def _update_presence_state(row: dict[str, Any], state: str, silence_seconds: int, next_eval: int) -> None:
    db = get_database()
    ts = now_ms()
    absence_started = int(row.get("absence_started_at_ms") or 0)
    if state.startswith("absent_") or state in {"long_absence", "dormant"}:
        absence_started = absence_started or int(row.get("last_user_at_ms") or ts)
    else:
        absence_started = 0
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            UPDATE relationship_presence_states
               SET state=?, silence_hours=?, absence_started_at_ms=?,
                   user_proactive_frequency=?, next_evaluation_at_ms=?,
                   disabled_reason='', updated_at_ms=?
             WHERE id=?
            """,
            (
                state,
                round(silence_seconds / 3600.0, 2),
                absence_started,
                (await load_proactive_settings(str(row.get("username") or ""))).frequency,
                next_eval,
                ts,
                row.get("id"),
            ),
        )
        await conn.commit()


async def _ensure_absence_campaign(row: dict[str, Any], state: str, frequency: str) -> None:
    db = get_database()
    ts = now_ms()
    username = str(row.get("username") or "")
    character_id = str(row.get("character_id") or "")
    conversation_id = str(row.get("conversation_id") or "")
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        if conversation_id:
            limit = await proactive_reply_limit_reached(conn, conversation_id)
            if limit.get("reached"):
                await conn.execute(
                    """
                    UPDATE proactive_campaigns
                       SET status='stopped', stop_reason='consecutive_proactive_limit',
                           ended_at_ms=?, updated_at_ms=?
                     WHERE username=? AND character_id=? AND status='active'
                    """,
                    (ts, ts, username, character_id),
                )
                await conn.execute(
                    """
                    UPDATE proactive_touch_attempts
                       SET status='cancelled', skip_reason='consecutive_proactive_limit',
                           updated_at_ms=?
                     WHERE username=? AND character_id=? AND status='pending'
                    """,
                    (ts, username, character_id),
                )
                await conn.commit()
                logger.info(
                    "[LongProactive] skip campaign: consecutive proactive limit reached conv=%s count=%s limit=%s",
                    conversation_id[:12],
                    limit.get("count"),
                    limit.get("limit"),
                )
                return
        async with conn.execute(
            """
            SELECT *
              FROM proactive_campaigns
             WHERE username=? AND character_id=? AND status='active'
               AND campaign_type='absence_reconnect'
             ORDER BY created_at_ms DESC
             LIMIT 1
            """,
            (username, character_id),
        ) as cur:
            campaign = await cur.fetchone()
        if campaign:
            campaign_id = str(campaign["id"])
            day_index = int(campaign["current_day_index"] or 0)
        else:
            campaign_id = f"pc_{uuid.uuid4().hex}"
            day_index = 0
            await conn.execute(
                """
                INSERT INTO proactive_campaigns (
                    id, username, character_id, conversation_id, campaign_type, status,
                    started_at_ms, current_day_index, max_day_index, cadence_policy,
                    pressure_ceiling, relationship_stage_at_start, seed_context_json,
                    stop_if_user_replies, metadata_json, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, 'absence_reconnect', 'active', ?, 0, ?, 'adaptive',
                          'low', ?, ?, 1, '{}', ?, ?)
                """,
                (
                    campaign_id,
                    username,
                    character_id,
                    str(row.get("conversation_id") or ""),
                    ts,
                    LONG_ABSENCE_MAX_DAY,
                    str(row.get("relationship_stage") or "uncertain"),
                    json.dumps({"state": state, "absence_started_at_ms": row.get("absence_started_at_ms") or row.get("last_user_at_ms")}, ensure_ascii=False),
                    ts,
                    ts,
                ),
            )
        async with conn.execute(
            "SELECT 1 FROM proactive_touch_attempts WHERE campaign_id=? AND status='pending' LIMIT 1",
            (campaign_id,),
        ) as cur:
            if await cur.fetchone():
                await conn.commit()
                return
        if day_index >= LONG_ABSENCE_MAX_DAY and frequency != "high":
            next_delay = DORMANT_INTERVAL_SECONDS
        else:
            next_delay = _next_day_delay_seconds(day_index, frequency)
        next_delay = apply_frequency_to_delay_seconds(next_delay, frequency)
        window_start = ts + max(60, next_delay) * 1000
        window_end = window_start + random.randint(30, 120) * 60 * 1000
        due_at = random.randint(window_start, window_end)
        if _is_quiet_hour(due_at):
            due_at = _next_allowed_daytime_ms(due_at)
            window_start = due_at
            window_end = due_at + 60 * 60 * 1000
        history = _json_list(row.get("motivation_history_json"))
        motivation = _motivation_for_day(day_index, history, str(row.get("relationship_stage") or "uncertain"))
        prompt = _prompt_seed(motivation, day_index, str(row.get("relationship_stage") or "uncertain"))
        attempt_id = f"pta_{uuid.uuid4().hex}"
        await conn.execute(
            """
            INSERT INTO proactive_touch_attempts (
                id, campaign_id, username, character_id, conversation_id,
                due_at_ms, window_start_ms, window_end_ms, status,
                motivation, pressure_level, topic_source, prompt_seed,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'low', 'absence_campaign', ?, ?, ?)
            """,
            (
                attempt_id,
                campaign_id,
                username,
                character_id,
                str(row.get("conversation_id") or ""),
                due_at,
                window_start,
                window_end,
                motivation,
                prompt,
                ts,
                ts,
            ),
        )
        await conn.execute(
            """
            UPDATE proactive_campaigns
               SET next_touch_due_at_ms=?, next_touch_window_start_ms=?,
                   next_touch_window_end_ms=?, updated_at_ms=?
             WHERE id=?
            """,
            (due_at, window_start, window_end, ts, campaign_id),
        )
        await conn.commit()


async def _process_due_touch_attempts() -> int:
    ts = now_ms()
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT *
              FROM proactive_touch_attempts
             WHERE status='pending' AND due_at_ms <= ?
             ORDER BY due_at_ms ASC
             LIMIT ?
            """,
            (ts, MAX_DUE_ATTEMPTS_PER_TICK),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    sent = 0
    for row in rows:
        if is_shutdown_requested():
            logger.info("[LongProactive] shutdown requested; touch attempts left pending")
            break
        if await _process_one_attempt(row):
            sent += 1
    return sent


async def _process_one_attempt(attempt: dict[str, Any]) -> bool:
    db = get_database()
    ts = now_ms()
    attempt_id = str(attempt.get("id") or "")
    async with aiosqlite.connect(db.db_path) as conn:
        cur = await conn.execute(
            "UPDATE proactive_touch_attempts SET status='processing', updated_at_ms=? WHERE id=? AND status='pending'",
            (ts, attempt_id),
        )
        await conn.commit()
        if int(cur.rowcount or 0) <= 0:
            return False
    if is_shutdown_requested():
        await _requeue_touch_attempt(attempt)
        return False
    validation = await _validate_attempt_sendable(attempt)
    if not validation.get("ok"):
        await _finish_attempt(attempt, "skipped", validation.get("reason") or "not_sendable")
        return False
    task = await _build_scheduled_task_from_attempt(attempt, validation)
    if not task:
        await _finish_attempt(attempt, "failed", "missing_task_context")
        return False
    try:
        async with galgame_locker.acquire(str(task.get("username") or ""), str(task.get("character_id") or "")):
            generated = await _generate_followup_via_normal_pipeline(task, validation.get("recent_messages") or [])
            active_model = generated.get("active_model") if isinstance(generated.get("active_model"), dict) else {}
            content = clean_generated_proactive_content(str(generated.get("message") or "").strip(), active_model)
            if not generated.get("should_send") or not content:
                await _finish_attempt(attempt, "skipped", str(generated.get("reason") or "empty_message"))
                return False
            signature = _content_signature(content)
            if signature and signature in validation.get("content_signatures", []):
                await _finish_attempt(attempt, "skipped", "repeated_content_signature")
                return False
            if generated.get("persisted_by_normal_core"):
                if is_shutdown_requested():
                    await _requeue_touch_attempt(attempt)
                    logger.info("[LongProactive] shutdown before normal-core audit; requeued attempt=%s", attempt_id)
                    return False
                message_ids = [
                    str(mid or "").strip()
                    for mid in (generated.get("assistant_message_ids") or [])
                    if str(mid or "").strip()
                ]
                if not message_ids:
                    await _finish_attempt(attempt, "failed", "normal_core_missing_message_id")
                    return False
                segments = [p.strip() for p in re.split(r"\n+", content) if p.strip()] or [content]
                proactive_ids = []
                for idx, message_id in enumerate(message_ids):
                    proactive_ids.append(
                        await _record_proactive_audit_only(
                            task,
                            segments[idx] if idx < len(segments) else segments[-1],
                            message_id,
                        )
                    )
                await _mark_attempt_sent(attempt, message_ids[-1], content, signature)
                await _advance_campaign_after_send(attempt, message_ids[-1], content, signature)
                logger.info("[LongProactive] sent via normal core attempt=%s proactive=%s", attempt_id, proactive_ids)
                return True
            recheck = await _validate_attempt_sendable(attempt)
            if not recheck.get("ok"):
                await _finish_attempt(attempt, "skipped", recheck.get("reason") or "not_sendable_after_generation")
                return False
            if is_shutdown_requested():
                await _requeue_touch_attempt(attempt)
                logger.info("[LongProactive] shutdown before append; requeued attempt=%s", attempt_id)
                return False
            should_follow_voice = _latest_assistant_was_voice(recheck.get("recent_messages") or [])
            message_parts = await _append_long_proactive_message(task, content)
            if not message_parts:
                await _finish_attempt(attempt, "failed", "persist_failed")
                return False
            voice_results_by_message_id = {}
            if should_follow_voice:
                voice_results_by_message_id = await _prepare_voice_for_scheduled_parts(
                    task,
                    message_parts,
                    generated.get("request") if hasattr(generated.get("request"), "messages") else None,
                )
            proactive_ids = []
            for message_id, segment in message_parts:
                proactive_ids.append(
                    await _record_proactive_and_push_chat_complete(
                        task,
                        segment,
                        message_id,
                        voice_result=voice_results_by_message_id.get(message_id),
                    )
                )
            await _mark_attempt_sent(attempt, message_parts[-1][0], content, signature)
            await _advance_campaign_after_send(attempt, message_parts[-1][0], content, signature)
            logger.info("[LongProactive] sent attempt=%s proactive=%s", attempt_id, proactive_ids)
            return True
    except asyncio.CancelledError:
        if is_shutdown_requested():
            await _requeue_touch_attempt(attempt)
            logger.info("[LongProactive] shutdown requeued processing attempt=%s", attempt_id)
            return False
        raise
    except Exception as exc:
        logger.warning("[LongProactive] attempt failed id=%s: %s", attempt_id, exc)
        await _finish_attempt(attempt, "failed", str(exc)[:300])
        return False


async def _requeue_touch_attempt(attempt: dict[str, Any]) -> None:
    db = get_database()
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            UPDATE proactive_touch_attempts
               SET status='pending',
                   due_at_ms=CASE WHEN due_at_ms > ? THEN due_at_ms ELSE ? END,
                   updated_at_ms=?
             WHERE id=?
               AND status='processing'
               AND COALESCE(generated_message_id, '') = ''
            """,
            (ts, ts + 5000, ts, attempt.get("id")),
        )
        await conn.commit()


async def _validate_attempt_sendable(attempt: dict[str, Any]) -> dict[str, Any]:
    username = str(attempt.get("username") or "")
    character_id = str(attempt.get("character_id") or "")
    conversation_id = str(attempt.get("conversation_id") or "")
    settings = await load_proactive_settings(username)
    if not settings.enabled:
        return {"ok": False, "reason": "proactive_messages_disabled"}
    ts = now_ms()
    if _is_quiet_hour(ts) and str(attempt.get("topic_source") or "") != "codex_test_bypass_quiet":
        await _defer_attempt(attempt, "quiet_hours", _next_allowed_daytime_ms(ts))
        return {"ok": False, "reason": "quiet_hours_deferred"}
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        from .chat_modules.normal_lifecycle import scheduled_character_is_dead_on_connection
        if await scheduled_character_is_dead_on_connection(conn, attempt):
            return {"ok": False, "reason": "character_already_dead"}
        async with conn.execute(
            """
            SELECT rps.*, c.is_hidden
              FROM relationship_presence_states rps
              LEFT JOIN conversations c ON c.id=rps.conversation_id
             WHERE rps.username=? AND rps.character_id=?
             LIMIT 1
            """,
            (username, character_id),
        ) as cur:
            state = await cur.fetchone()
        if not state:
            return {"ok": False, "reason": "presence_missing"}
        if int(state["is_hidden"] or 0) != 0:
            return {"ok": False, "reason": "conversation_hidden"}
        if int(state["user_ended_conversation"] or 0):
            return {"ok": False, "reason": "user_ended_conversation"}
        limit = await proactive_reply_limit_reached(conn, conversation_id or str(state["conversation_id"] or ""))
        if limit.get("reached"):
            return {
                "ok": False,
                "reason": str(limit.get("reason") or "consecutive_proactive_limit"),
                "consecutive_proactive_reply_groups": int(limit.get("count") or 0),
                "consecutive_proactive_reply_limit": int(limit.get("limit") or 0),
            }
        last_user_at = int(state["last_user_at_ms"] or 0)
        last_proactive_at = int(state["last_proactive_at_ms"] or 0)
        if last_proactive_at > 0 and ts - last_proactive_at < 6 * 60 * 60 * 1000:
            return {"ok": False, "reason": "character_cooldown"}
        if conversation_id:
            async with conn.execute(
                """
                SELECT m.role, m.content, m.timestamp, m.message_id, m.sequence_number,
                       mvs.voice_status, mvs.voice_id, mvs.voice_cache_key
                  FROM messages m
                  LEFT JOIN message_voice_states mvs
                         ON mvs.conversation_id = m.conversation_id
                        AND mvs.message_id = m.message_id
                 WHERE m.conversation_id=? AND m.deleted_at IS NULL AND COALESCE(m.is_hidden,0)=0
                 ORDER BY COALESCE(m.sequence_number,0) DESC, COALESCE(m.timestamp,0) DESC, m.rowid DESC
                 LIMIT 14
                """,
                (conversation_id,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            rows = []
        recent = [
            {
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["timestamp"],
                "message_id": r["message_id"],
                "sequence_number": r["sequence_number"],
                "voice_state": {
                    "voice_status": r["voice_status"],
                    "voice_id": r["voice_id"],
                    "voice_cache_key": r["voice_cache_key"],
                } if r["voice_status"] else None,
                "voice_status": r["voice_status"],
            }
            for r in reversed(rows)
        ]
        latest_user = next((m for m in reversed(recent) if m.get("role") == "user"), None)
        if latest_user and int(latest_user.get("timestamp") or 0) > last_user_at:
            return {"ok": False, "reason": "user_replied_after_presence"}
        if _is_conversation_end(str((latest_user or {}).get("content") or "")):
            return {"ok": False, "reason": "latest_user_ended_conversation"}
        day_start = int(datetime.now(LOCAL_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        async with conn.execute(
            """
            SELECT COUNT(*) FROM proactive_touch_attempts
             WHERE username=? AND status='sent' AND updated_at_ms>=?
            """,
            (username, day_start),
        ) as cur:
            user_count = int((await cur.fetchone())[0] or 0)
        if user_count >= MAX_LONG_PROACTIVE_PER_USER_PER_DAY:
            return {"ok": False, "reason": "daily_user_long_proactive_limit"}
        async with conn.execute(
            """
            SELECT COUNT(*) FROM proactive_touch_attempts
             WHERE username=? AND character_id=? AND status='sent' AND updated_at_ms>=?
            """,
            (username, character_id, day_start),
        ) as cur:
            char_count = int((await cur.fetchone())[0] or 0)
        if char_count >= MAX_LONG_PROACTIVE_PER_CHARACTER_PER_DAY:
            return {"ok": False, "reason": "daily_character_long_proactive_limit"}
        signatures = [str(x) for x in _json_list(state["content_signature_history_json"])]
        return {
            "ok": True,
            "state": dict(state),
            "recent_messages": recent,
            "content_signatures": signatures,
        }


async def _defer_attempt(attempt: dict[str, Any], reason: str, due_at_ms: int) -> None:
    db = get_database()
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            UPDATE proactive_touch_attempts
               SET status='pending', due_at_ms=?, window_start_ms=?, window_end_ms=?,
                   skip_reason=?, updated_at_ms=?
             WHERE id=?
            """,
            (due_at_ms, due_at_ms, due_at_ms + 60 * 60 * 1000, reason, ts, attempt.get("id")),
        )
        await conn.commit()


async def _build_scheduled_task_from_attempt(attempt: dict[str, Any], validation: dict[str, Any]) -> Optional[dict[str, Any]]:
    state = validation.get("state") or {}
    source_message_id = str(state.get("last_assistant_message_id") or "")
    conversation_id = str(attempt.get("conversation_id") or state.get("conversation_id") or "")
    if not conversation_id or not source_message_id:
        return None
    seed = (
        f"[absence_reconnect:{attempt.get('motivation')}] "
        "用户仍处于失联/未回复状态；这是角色隔空发出的主动消息，"
        "不要描写用户已经回来、上线、走近、进入场景或正在被角色看见，"
        "不要假设用户已经忙完或正在读这条消息。"
        f"{attempt.get('prompt_seed')}"
    )
    return {
        "id": str(attempt.get("id") or ""),
        "username": str(attempt.get("username") or ""),
        "character_id": str(attempt.get("character_id") or ""),
        "conversation_id": conversation_id,
        "source_message_id": source_message_id,
        "cancel_if_user_replies": 1,
        "allow_reschedule_after_send": 0,
        "seed": seed,
        "reason": "long_proactive_absence",
        "pressure_level": "low",
        "chain_id": str(attempt.get("campaign_id") or ""),
        "chain_count": int((state or {}).get("total_proactive_in_absence") or 0),
        "metadata_json": "{}",
    }


async def _append_long_proactive_message(task: dict[str, Any], content: str) -> list[tuple[str, str]]:
    db = get_database()
    segments = [p.strip() for p in re.split(r"\n+", (content or "").strip()) if p.strip()]
    if not segments:
        return []
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("BEGIN IMMEDIATE")
        try:
            from .chat_modules.normal_lifecycle import scheduled_character_is_dead_on_connection
            if await scheduled_character_is_dead_on_connection(conn, task):
                await conn.rollback()
                return []
            async with conn.execute(
                "SELECT status FROM proactive_touch_attempts WHERE id=? LIMIT 1",
                (task["id"],),
            ) as cur:
                row = await cur.fetchone()
            if not row or str(row[0] or "") != "processing":
                await conn.rollback()
                return []
            async with conn.execute(
                """
                SELECT message_id, sequence_number
                  FROM messages
                 WHERE conversation_id=? AND deleted_at IS NULL
                 ORDER BY COALESCE(sequence_number,0) DESC, COALESCE(timestamp,0) DESC, rowid DESC
                 LIMIT 1
                """,
                (task["conversation_id"],),
            ) as cur:
                prev = await cur.fetchone()
            prev_id = prev[0] if prev else None
            next_seq = int(prev[1] or 0) + 1 if prev else 0
            saved: list[tuple[str, str]] = []
            for idx, segment in enumerate(segments):
                message_id = generate_message_id()
                row_id = f"{task['conversation_id']}_{message_id}"
                await conn.execute(
                    """
                    INSERT INTO messages (
                        id, conversation_id, role, content, raw_content, image_url,
                        timestamp, message_id, sequence_number, previous_message_id,
                        suggestions, suggestions_status, client_id, generation_duration_ms
                    ) VALUES (?, ?, 'assistant', ?, ?, NULL, ?, ?, ?, ?, NULL, 'none', 'scheduled_followup', NULL)
                    """,
                    (row_id, task["conversation_id"], segment, segment, ts + idx, message_id, next_seq + idx, prev_id),
                )
                saved.append((message_id, segment))
                prev_id = message_id
            await conn.execute(
                "UPDATE conversations SET timestamp=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (ts, task["conversation_id"]),
            )
            await conn.commit()
            return saved
        except Exception:
            await conn.rollback()
            raise


async def _finish_attempt(attempt: dict[str, Any], status: str, reason: str) -> None:
    db = get_database()
    ts = now_ms()
    col = "skip_reason" if status == "skipped" else "failure_reason"
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            f"UPDATE proactive_touch_attempts SET status=?, {col}=?, updated_at_ms=? WHERE id=?",
            (status, reason[:300], ts, attempt.get("id")),
        )
        await conn.commit()


async def _mark_attempt_sent(attempt: dict[str, Any], message_id: str, content: str, signature: str) -> None:
    db = get_database()
    ts = now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            UPDATE proactive_touch_attempts
               SET status='sent', generated_message_id=?, generated_content=?,
                   content_signature=?, updated_at_ms=?
             WHERE id=?
            """,
            (message_id, content[:2000], signature, ts, attempt.get("id")),
        )
        await conn.commit()


async def _advance_campaign_after_send(attempt: dict[str, Any], message_id: str, content: str, signature: str) -> None:
    db = get_database()
    ts = now_ms()
    username = str(attempt.get("username") or "")
    character_id = str(attempt.get("character_id") or "")
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM relationship_presence_states WHERE username=? AND character_id=? LIMIT 1",
            (username, character_id),
        ) as cur:
            state = await cur.fetchone()
        motivation_history = _json_list(state["motivation_history_json"] if state else "[]")
        motivation_history.append(str(attempt.get("motivation") or ""))
        motivation_history = motivation_history[-10:]
        signature_history = _json_list(state["content_signature_history_json"] if state else "[]")
        if signature:
            signature_history.append(signature)
        signature_history = signature_history[-12:]
        await conn.execute(
            """
            UPDATE relationship_presence_states
               SET last_proactive_message_id=?, last_proactive_at_ms=?,
                   consecutive_proactive_days=consecutive_proactive_days+1,
                   total_proactive_in_absence=total_proactive_in_absence+1,
                   last_motivation=?, motivation_history_json=?,
                   content_signature_history_json=?, cooldown_until_ms=?,
                   updated_at_ms=?
             WHERE username=? AND character_id=?
            """,
            (
                message_id,
                ts,
                str(attempt.get("motivation") or ""),
                json.dumps(motivation_history, ensure_ascii=False),
                json.dumps(signature_history, ensure_ascii=False),
                ts + 6 * 60 * 60 * 1000,
                ts,
                username,
                character_id,
            ),
        )
        async with conn.execute(
            "SELECT * FROM proactive_campaigns WHERE id=? LIMIT 1",
            (attempt.get("campaign_id"),),
        ) as cur:
            campaign = await cur.fetchone()
        if campaign:
            day_index = int(campaign["current_day_index"] or 0) + 1
            status = "active"
            stop_reason = ""
            if day_index > int(campaign["max_day_index"] or LONG_ABSENCE_MAX_DAY):
                status = "active"
                stop_reason = "dormant_cadence"
            await conn.execute(
                """
                UPDATE proactive_campaigns
                   SET current_day_index=?, last_touch_at_ms=?,
                       next_touch_due_at_ms=0, next_touch_window_start_ms=0,
                       next_touch_window_end_ms=0, stop_reason=?,
                       status=?, updated_at_ms=?
                 WHERE id=?
                """,
                (day_index, ts, stop_reason, status, ts, attempt.get("campaign_id")),
            )
        await conn.commit()
