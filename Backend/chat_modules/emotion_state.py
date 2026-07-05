from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

import aiosqlite

from ..config import logger


_PERIOD_LABELS = (
    (5, "early_morning", "early morning"),
    (9, "morning", "morning"),
    (12, "late_morning", "late morning"),
    (14, "noon", "noon"),
    (18, "afternoon", "afternoon"),
    (22, "evening", "evening"),
    (24, "night", "night"),
)


def _noncritical_db_busy_timeout_ms() -> int:
    raw = os.getenv("PONYCHAT_NONCRITICAL_DB_BUSY_TIMEOUT_MS") or "500"
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 500
    return max(100, min(value, 5000))


def _is_sqlite_locked(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def _client_datetime(client_context: Any = None) -> datetime:
    raw = getattr(client_context, "time_iso", None) if client_context is not None else None
    if raw:
        try:
            return datetime.fromisoformat(str(raw))
        except Exception:
            pass
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    except Exception:
        return datetime.now()


def _period_for(dt: datetime) -> tuple[str, str]:
    hour = dt.hour
    for upper, key, label in _PERIOD_LABELS:
        if hour < upper:
            return key, label
    return "night", "night"


def period_key(client_context: Any = None) -> str:
    dt = _client_datetime(client_context)
    key, _label = _period_for(dt)
    return f"{dt.strftime('%Y-%m-%d')}:{key}"


def _default_baseline(period: str) -> dict[str, Any]:
    label = "calm"
    reason = "这是角色在当前时段的普通背景心情"
    if period.endswith(":night"):
        label = "quiet"
        reason = "当前时段会让角色自然更安静一些"
    elif period.endswith(":early_morning"):
        label = "soft"
        reason = "当前时段让角色带着刚开始一天的柔和底色"
    return {
        "label": label,
        "intensity": 25,
        "energy": 45,
        "reason": reason,
        "scope": period,
    }


def _default_reactive() -> dict[str, Any]:
    return {
        "label": "neutral",
        "intensity": 0,
        "stance_to_user": "steady",
        "trigger": "",
        "decay": "fast",
    }


def _coerce_emotion_obj(value: Any, *, default: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return dict(default)
    out = dict(default)
    for key in ("label", "reason", "scope", "stance_to_user", "trigger", "decay"):
        if key in value and str(value.get(key) or "").strip():
            out[key] = str(value.get(key)).strip()[:240]
    for key in ("intensity", "energy", "valence", "arousal", "confidence"):
        if key in value:
            try:
                out[key] = max(-100 if key == "valence" else 0, min(100, int(float(value.get(key)))))
            except Exception:
                pass
    return out


def coerce_planner_emotion(planner_result: dict[str, Any] | None, state: dict[str, Any] | None = None) -> dict[str, Any]:
    p = planner_result or {}
    current = state or {}
    baseline_default = current.get("baseline_emotion") or _default_baseline(str(current.get("period_key") or period_key()))
    reactive_default = current.get("reactive_emotion") or _default_reactive()
    baseline = _coerce_emotion_obj(p.get("baseline_emotion"), default=baseline_default)
    reactive = _coerce_emotion_obj(p.get("reactive_emotion"), default=reactive_default)
    blend = str(p.get("emotion_blend") or "").strip()
    if not blend:
        blend = (
            f"背景心情为{baseline.get('label')}，强度 {baseline.get('intensity')}；"
            f"当前由用户触发的短期反应为{reactive.get('label')}，强度 {reactive.get('intensity')}。"
        )
    return {
        "baseline_emotion": baseline,
        "reactive_emotion": reactive,
        "emotion_blend": blend[:900],
    }


async def load_emotion_state(
    username: str,
    character_id: str,
    conversation_id: str,
    db,
    *,
    client_context: Any = None,
) -> dict[str, Any]:
    pk = period_key(client_context)
    default_state = {
        "period_key": pk,
        "baseline_emotion": _default_baseline(pk),
        "reactive_emotion": _default_reactive(),
        "emotion_blend": "",
        "updated_ms": 0,
    }
    if not username or not character_id or not conversation_id:
        return default_state

    conn = await db.acquire()
    try:
        cur = await conn.execute(
            """SELECT period_key, baseline_json, reactive_json, emotion_blend, updated_ms
               FROM normal_emotion_state
               WHERE username=? AND character_id=? AND conversation_id=?""",
            (username, character_id, conversation_id),
        )
        row = await cur.fetchone()
    except Exception as exc:
        logger.debug("[EmotionState] load failed: %s", exc)
        return default_state
    finally:
        await db.release(conn)

    if not row:
        return default_state

    old_period = str(row[0] or "")
    if old_period != pk:
        return default_state

    try:
        baseline = json.loads(row[1] or "{}")
    except Exception:
        baseline = {}
    try:
        reactive = json.loads(row[2] or "{}")
    except Exception:
        reactive = {}

    return {
        "period_key": pk,
        "baseline_emotion": _coerce_emotion_obj(baseline, default=_default_baseline(pk)),
        "reactive_emotion": _coerce_emotion_obj(reactive, default=_default_reactive()),
        "emotion_blend": str(row[3] or "").strip(),
        "updated_ms": int(row[4] or 0),
    }


async def save_emotion_state(
    username: str,
    character_id: str,
    conversation_id: str,
    state: dict[str, Any],
    db,
) -> bool:
    if not username or not character_id or not conversation_id:
        return False
    pk = str(state.get("period_key") or period_key())
    baseline = _coerce_emotion_obj(state.get("baseline_emotion"), default=_default_baseline(pk))
    reactive = _coerce_emotion_obj(state.get("reactive_emotion"), default=_default_reactive())
    blend = str(state.get("emotion_blend") or "").strip()[:900]
    updated_ms = int(time.time() * 1000)

    try:
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute(f"PRAGMA busy_timeout = {_noncritical_db_busy_timeout_ms()}")
            await conn.execute(
                """INSERT INTO normal_emotion_state
                       (username, character_id, conversation_id, period_key,
                        baseline_json, reactive_json, emotion_blend, updated_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(username, character_id, conversation_id) DO UPDATE SET
                       period_key=excluded.period_key,
                       baseline_json=excluded.baseline_json,
                       reactive_json=excluded.reactive_json,
                       emotion_blend=excluded.emotion_blend,
                       updated_ms=excluded.updated_ms""",
                (
                    username,
                    character_id,
                    conversation_id,
                    pk,
                    json.dumps(baseline, ensure_ascii=False),
                    json.dumps(reactive, ensure_ascii=False),
                    blend,
                    updated_ms,
                ),
            )
            await conn.commit()
        return True
    except Exception as exc:
        if _is_sqlite_locked(exc):
            logger.debug("[EmotionState] save skipped: database is locked")
        else:
            logger.warning("[EmotionState] save failed: %s", exc)
        return False


async def save_from_planner(
    username: str,
    character_id: str,
    conversation_id: str,
    planner_result: dict[str, Any],
    previous_state: dict[str, Any],
    db,
) -> bool:
    coerced = coerce_planner_emotion(planner_result, previous_state)
    next_state = {
        "period_key": previous_state.get("period_key") or period_key(),
        **coerced,
    }
    return await save_emotion_state(username, character_id, conversation_id, next_state, db)


def format_emotion_state_for_planner(state: dict[str, Any] | None) -> str:
    if not state:
        return ""
    baseline = state.get("baseline_emotion") or {}
    reactive = state.get("reactive_emotion") or {}
    blend = str(state.get("emotion_blend") or "").strip()
    return (
        "【普通对话导演可参考的角色情绪状态】\n"
        f"时段键: {state.get('period_key') or ''}\n"
        "baseline_emotion: "
        f"label={baseline.get('label')}, intensity={baseline.get('intensity')}, "
        f"energy={baseline.get('energy')}, reason={baseline.get('reason')}\n"
        "reactive_emotion: "
        f"label={reactive.get('label')}, intensity={reactive.get('intensity')}, "
        f"stance_to_user={reactive.get('stance_to_user')}, trigger={reactive.get('trigger')}, "
        f"decay={reactive.get('decay')}\n"
        f"上一轮融合说明: {blend}\n"
        "baseline_emotion 表示角色在当前时段自身的背景心情。"
        "reactive_emotion 表示由用户最新消息触发的短期反应情绪。"
        "不要把情绪字段写入 state_anchor。"
    )


def format_emotion_block_for_reply(planner_result: dict[str, Any] | None, state: dict[str, Any] | None) -> str:
    emotion = coerce_planner_emotion(planner_result, state)
    baseline = emotion["baseline_emotion"]
    reactive = emotion["reactive_emotion"]
    blend = emotion["emotion_blend"]
    return (
        "【角色情绪调度】\n"
        "当前有两层情绪生效：\n"
        f"1. baseline_emotion: label={baseline.get('label')}, intensity={baseline.get('intensity')}, "
        f"energy={baseline.get('energy')}, reason={baseline.get('reason')}. "
        "这是角色在当前日期/时段自身的背景心情。\n"
        f"2. reactive_emotion: label={reactive.get('label')}, intensity={reactive.get('intensity')}, "
        f"stance_to_user={reactive.get('stance_to_user')}, trigger={reactive.get('trigger')}, "
        f"decay={reactive.get('decay')}. "
        "这是由用户最新消息触发的短期反应，可能会暂时盖过背景心情。\n"
        f"融合规则: {blend}\n"
        "请通过措辞、节奏、主动性和细微选择表现融合后的情绪。"
        "除非在角色台词中非常自然，否则不要直接向用户说出这些情绪标签。"
    )
