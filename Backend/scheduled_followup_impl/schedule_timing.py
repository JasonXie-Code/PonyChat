from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import aiosqlite

from .assistant_sanitize import sanitize_assistant_strip_markers
from .chat_modules.request_context import (
    build_chat_router_recent_user_assistant,
)
from .config import logger, model_manager
from .db import get_database
from .delivery_outbox import enqueue_chat_complete
from .galgame import generate_message_id
from .providers.llm_call import call_llm_payload
from .proactive_send_guard import proactive_reply_limit_reached
from .proactive_settings import apply_frequency_to_delay_seconds, load_proactive_settings
from .reasoning_config import apply_llm_task_payload_config, llm_task_float
from .reasoning_policy import resolve_software_reasoning_policy
from .shutdown_state import is_shutdown_requested
from .utils import ChatMessage, ChatRequest
from .websocket import galgame_locker


MIN_DELAY_SECONDS = 10
MAX_DELAY_SECONDS = 24 * 60 * 60
DEFAULT_EXPIRES_SECONDS = 2 * 60 * 60


def _scheduled_text_part_delay_seconds(content: str) -> float:
    return max(0.3, min(len(str(content or "")) / 10.0, 8.0)) + random.uniform(1.0, 3.0)


def _scheduled_message_part_delay_seconds(
    current_content: str,
    *,
    current_voice_result: dict[str, Any] | None = None,
) -> float:
    try:
        from .chat_modules.voice_messages import voice_result_display_delay_seconds

        voice_delay = voice_result_display_delay_seconds(current_voice_result, current_content)
    except Exception as exc:
        logger.debug("[ScheduledFollowup] voice delay helper failed: %s", exc)
        voice_delay = None
    if voice_delay is not None:
        return voice_delay
    return _scheduled_text_part_delay_seconds(current_content)
MAX_EXPIRES_SECONDS = 24 * 60 * 60
LOOP_INTERVAL_SECONDS = 5
MAX_DUE_BATCH = 8
MAX_RECENT_MESSAGES = 14
MAX_AUTO_MESSAGES_PER_CONVERSATION_PER_DAY = 24
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
QUIET_HOUR_START = 0
QUIET_HOUR_END = 8
EARLY_MORNING_MISMATCH_RE = re.compile(
    r"(早啊|早呀|早上好|早安|早晨好|上午好|起床|睡醒|早起|清晨|晨光|阳光|窗台|图书馆.*阳光)"
)
REMINDER_NATURAL_WINDOW_SECONDS = 10 * 60

NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM = """你是普通对话 Step 4：下回预备里的主动任务判断器。你只输出 JSON，不生成角色台词，不解释规则。

【职责边界】
- 你只判断“主动任务”：角色在 Step 3 主回复已经发送后，如果用户没有继续回复，是否值得隔一段时间再主动补一句。
- “被动任务”指用户明确约定的提醒/计时/叫醒/周期任务，对应 user_agreed_task；被动任务只由 Step 1 识别并落到任务系统，你在 Step 4 不得创建、修改或猜测被动任务。
- 你能看到当前用户消息、Step 3 最终角色回复、Step 1 意图识别摘要、Step 2 工具摘要和最近对话。必须基于最终角色回复判断，而不是基于原始角色设定直接幻想下一句。
- 如果用户新消息在 Step 4 完成前到达，服务器会取消本次主动任务判断；因此你只判断“没有新消息时是否值得安排”，不要写给用户看的解释。
- 你必须先填写 turn_state，再填写 scheduled_followup。turn_state 是主动任务资格判断，不是角色台词。
- Step 4 的前提是“Step 3 后用户还没有新的可见回复”。不得把 Step 3 最终角色回复里的问题、邀请、挑衅、等待动作、猜测或“等你……”当成用户已经回答、同意、接招或做出动作。

【主动任务规则】
- scheduled_followup 对高主动角色、熟人/好友/亲密关系、好奇追问、邀请、分享、想念、开心兴奋、轻量游戏或热聊停顿，通常必须 enabled=true；不要因为“用户刚刚还在聊”就机械关闭。
- 但如果 Step 3 主回复已经自然收束、明确要求用户先回答、正在告别/睡觉/下线、刚添加的新联系人开场，或继续补一句会像自问自答，则 enabled=false。
- 如果 Step 3 最终角色回复正在等待用户回答、选择、表态、行动、靠近、接招、跟上、证明自己、继续游戏回合或完成挑战，turn_state.last_assistant_reply_state 必须是 "waiting_for_user"。典型文本包括但不限于：“来啊”“证明给我看”“让我看看你能不能/能撑到”“等你接招”“轮到你了”“要不要/想不想/敢不敢/能不能”。
- waiting_for_user 不等于必须关闭主动任务；但 scheduled_followup 不能默认用户已经回答、同意、接招、跟上、靠近、继续或完成动作。若开启，seed 必须选择安全续接模式之一：角色自我补充/缓和上一句、换一种低压力邀请方式、给用户不用急着回应的台阶、转移到轻话题、或揭晓角色自己掌握的信息。seed 必须明确保留“用户尚未回应”的事实，不得写“用户接住了挑衅/答应了/靠近了/跟上了/想继续/已经选择”。
- 如果只能通过假设用户已经答应、接招或行动才能续接，则 scheduled_followup.enabled=false；如果可以改成自我补充、重新邀请、转移话题或低压力等待，则可以 enabled=true。
- 用户压力高不自动关闭主动任务：若 Step 3 主回复已经接了用户具体事实并给了角色化判断或低压力下一步，则 enabled=false（主回复已充分处理）；若 Step 3 主回复只是泛安慰（如"辛苦了/我在/泡茶/陪着你/靠着/画星星"）而未锚定用户前文具体事实，应 enabled=true，seed 必须安排一条锚定用户前文事实的新角度、轻判断或低压力安排，禁止重复泛安慰。
- 深夜保护：用户准备睡觉、休息、晚安、下线或对话已经礼貌收束时，主动任务通常必须关闭；不要为了活跃度打扰用户。
- 主动任务必须低压力、短、像角色自然想起一件新东西；seed 只写客观意图和切入点，不要提前输出短模板，不要写第一人称角色正文，不要代替用户回答角色刚问的问题。
- 如果最终角色回复已经问了用户一个问题，主动任务不能替用户回答这个问题；只能在确实有新价值时，换一个轻的观察、补充或关心点。
- 若 Step 3 最终角色回复把“故事/经历/话题选项”抛给用户，而最近可见对话已经讲过、展开过或反复提出其中某个选项，turn_state.waiting_target 应写成 "fresh_narrative_or_scene" 或等价说明；scheduled_followup.seed 禁止再次催问同一组旧选项（例如“还没想好听哪个故事吗”）。若开启主动任务，seed 必须要求角色改为推进未展开的新经历/后续事件、角色自己的新细节，或回到当前场景动作/亲密接触；若没有这种新拍子，enabled=false。
- 若最近一条真实 user 是明确问题或调侃追问，而 Step 3 最终角色回复只是沿旧问候、天气、早餐、生活安排、泛亲密动作或转移话题滑走，scheduled_followup.seed 不得继续沿旧话题补一句。若开启主动任务，waiting_target 写成 "repair_unanswered_user_question" 或等价说明，seed 必须要求角色先补答/承认刚才跑偏/回到用户刚问的点，再低压力承接氛围；否则 enabled=false。
- 例外只限“角色让用户猜一个角色自己掌握的信息”（如礼物颜色、藏了什么、准备了什么）：turn_state 可写 "self_reveal_possible"，scheduled_followup 可以安排角色没忍住自己揭晓；但仍不得写成用户猜对、同意、喜欢、接住或已经回答。
- 若用户像是不记得既有关系，且主回复已经温柔确认关系异常，主动任务可从“察觉对方像失忆、温柔提起已有证据中的共同经历试探”切入，但不得编造证据中没有的往事。
- 主动任务不是被动提醒。用户说“30秒后提醒我/每天叫我起床”这类明确约定，Step 4 必须 enabled=false，因为它已经属于被动任务。

【主体归属硬要求】
- seed/reason 必须保留“谁做了动作、谁被夸、谁被保护、谁在关心谁”的主体，不得把 Step 3 中角色对用户的评价改写成角色自己被评价。
- 若 Step 3 写“夸你一句 / 你护着我很帅 / 护着我的样子真帅”，被夸对象是用户，不是角色；seed 应写“角色想继续夸用户/因用户保护而安心撒娇”，绝不能写“角色被夸帅/角色被夸后得意/不夸我帅”。
- 若无法确定被评价主体，subject_integrity.evaluated_subject 填 "unclear"，seed 必须避开“被夸帅/被夸漂亮/被夸厉害”等会改变主体的说法，改写为“延续上一条的撒娇/安心/调侃余韵”。

【输出】
只输出一个 JSON 对象。下面是唯一完整字段例子，不要把示范文本当作要输出的正文：
{
  "turn_state": {
    "user_replied_after_step3": false,
    "last_assistant_reply_state": "waiting_for_user",
    "waiting_target": "action",
    "evidence": "来啊，证明给我看你能跟得上 / 等你来接招",
    "allowed_followup_mode": "soften_or_reinvite",
    "user_response_assumed": false,
    "decision_rule": "上一条角色正在等用户行动；主动续接只能缓和、重新邀请、转移话题或自我补充，不得写成用户已经接招"
  },
  "scheduled_followup": {
    "enabled": true,
    "target_delay_seconds": 20,
    "expires_seconds": 120,
    "cancel_if_user_replies": true,
    "allow_reschedule_after_send": false,
    "seed": "用户尚未回应上一句挑战；角色只把语气放轻一点或换一种邀请方式，给用户不用急着接招的台阶。不要写用户已经接招、跟上、靠近或同意。",
    "reason": "上一条在等待用户行动，但可以低压力缓和或重新邀请；不能默认用户已答应。",
    "pressure_level": "low",
    "subject_integrity": {
      "evaluated_subject": "none",
      "source_user_action": "",
      "source_character_action": "",
      "seed_subject_check": ""
    }
  }
}
"""

_pending_step4_next_turn_prep_tasks: dict[str, asyncio.Task] = {}
_pending_step4_followup_generation_tasks: dict[str, tuple[str, str, str, asyncio.Task]] = {}

_USER_CONVERSATION_END_RE = re.compile(
    r"(休息了|去休息|我要睡|我睡了|睡觉了|准备睡|该睡|晚安|明天再来|明天聊|明天见|先不聊|不聊了|下线了|拜拜|再见)"
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


async def _configure_noncritical_conn(conn: aiosqlite.Connection) -> None:
    await conn.execute(f"PRAGMA busy_timeout = {_noncritical_db_busy_timeout_ms()}")


def default_scheduled_followup() -> dict[str, Any]:
    return {
        "enabled": False,
        "target_delay_seconds": 0,
        "expires_seconds": 0,
        "cancel_if_user_replies": True,
        "allow_reschedule_after_send": False,
        "seed": "",
        "reason": "",
        "pressure_level": "low",
        "subject_integrity": {},
    }


def default_user_agreed_task() -> dict[str, Any]:
    return {
        "enabled": False,
        "task_type": "",
        "summary": "",
        "schedule_type": "once",
        "target_delay_seconds": 0,
        "interval_seconds": 0,
        "time_of_day": "",
        "days": [],
        "natural_window_seconds": 0,
        "cancel_if_user_replies": True,
    }


def coerce_user_agreed_task(value: Any) -> dict[str, Any]:
    out = default_user_agreed_task()
    if not isinstance(value, dict) or not bool(value.get("enabled")):
        return out
    task_type = str(value.get("task_type") or "").strip().lower()
    if task_type not in {"reminder", "timer", "appointment", "custom"}:
        task_type = "custom"
    summary = str(value.get("summary") or "").strip()
    schedule_type = str(value.get("schedule_type") or "once").strip().lower()
    if schedule_type not in {"once", "interval", "daily", "weekly", "monthly"}:
        schedule_type = "once"
    delay = _coerce_int(value.get("target_delay_seconds"), 0)
    interval_seconds = _coerce_int(value.get("interval_seconds"), 0)
    time_of_day = str(value.get("time_of_day") or "").strip()[:5]
    raw_days = value.get("days")
    days: list[int] = []
    if isinstance(raw_days, list):
        for item in raw_days[:7]:
            try:
                day = int(item)
            except (TypeError, ValueError):
                continue
            if schedule_type == "weekly" and 0 <= day <= 6 and day not in days:
                days.append(day)
            elif schedule_type == "monthly" and 1 <= day <= 31 and day not in days:
                days.append(day)
    if schedule_type == "interval":
        delay = max(delay, interval_seconds)
    if schedule_type == "once" and delay <= 0:
        return out
    if schedule_type == "interval" and max(delay, interval_seconds) <= 0:
        return out
    if schedule_type in {"daily", "weekly", "monthly"} and not re.match(r"^\d{1,2}:\d{2}$", time_of_day):
        return out
    if not summary:
        return out
    window = _coerce_int(value.get("natural_window_seconds"), REMINDER_NATURAL_WINDOW_SECONDS)
    window = max(60, min(2 * 60 * 60, window))
    out.update(
        {
            "enabled": True,
            "task_type": task_type,
            "summary": summary[:400],
            "schedule_type": schedule_type,
            "target_delay_seconds": max(MIN_DELAY_SECONDS, min(MAX_DELAY_SECONDS, delay)),
            "interval_seconds": max(0, min(MAX_DELAY_SECONDS, interval_seconds)),
            "time_of_day": time_of_day,
            "days": days,
            "natural_window_seconds": window,
            "cancel_if_user_replies": value.get("cancel_if_user_replies") is not False,
        }
    )
    return out


def coerce_scheduled_followup(value: Any, *, is_new_contact_opening: bool = False) -> dict[str, Any]:
    out = default_scheduled_followup()
    if is_new_contact_opening or not isinstance(value, dict):
        return out
    enabled = bool(value.get("enabled"))
    seed = str(value.get("seed") or "").strip()
    if not enabled or not seed:
        return out

    delay = _coerce_int(value.get("target_delay_seconds"), 0)
    delay = max(MIN_DELAY_SECONDS, min(MAX_DELAY_SECONDS, delay))
    expires = _coerce_int(value.get("expires_seconds"), DEFAULT_EXPIRES_SECONDS)
    expires = max(delay, min(MAX_EXPIRES_SECONDS, expires))
    pressure = str(value.get("pressure_level") or "low").strip().lower()
    if pressure not in {"low", "medium", "high"}:
        pressure = "low"
    subject_integrity = value.get("subject_integrity")
    if isinstance(subject_integrity, dict):
        subject_integrity = {
            "evaluated_subject": str(subject_integrity.get("evaluated_subject") or "").strip()[:40],
            "source_user_action": str(subject_integrity.get("source_user_action") or "").strip()[:160],
            "source_character_action": str(subject_integrity.get("source_character_action") or "").strip()[:160],
            "seed_subject_check": str(subject_integrity.get("seed_subject_check") or "").strip()[:240],
        }
        subject_integrity = {k: v for k, v in subject_integrity.items() if v}
    else:
        subject_integrity = {}

    out.update(
        {
            "enabled": True,
            "target_delay_seconds": delay,
            "expires_seconds": expires,
            "cancel_if_user_replies": value.get("cancel_if_user_replies") is not False,
            "allow_reschedule_after_send": bool(value.get("allow_reschedule_after_send")),
            "seed": seed[:600],
            "reason": str(value.get("reason") or "").strip()[:400],
            "pressure_level": pressure,
            "subject_integrity": subject_integrity,
        }
    )
    return out


_COMPLIMENT_TARGET_WORDS_RE = r"(?:帅|帅气|好看|漂亮|美|可爱|厉害|可靠|温柔|贴心|勇敢)"


def _step4_detect_user_evaluated_by_assistant(assistant_message: str) -> str:
    text = str(assistant_message or "").strip()
    if not text:
        return ""
    sentence_re = r"[^。！？!?；;\n]{0,36}"
    patterns = [
        rf"夸你(?:一句|一下)?{sentence_re}{_COMPLIMENT_TARGET_WORDS_RE}",
        rf"(?:你|用户|对方){sentence_re}{_COMPLIMENT_TARGET_WORDS_RE}",
        rf"(?:护着|保护|救|挡在|抱着|安慰){sentence_re}(?:我|角色|她|他|它){sentence_re}{_COMPLIMENT_TARGET_WORDS_RE}",
        rf"(?:你|用户|对方){sentence_re}(?:护着|保护|救|挡在|抱着|安慰){sentence_re}(?:我|角色|她|他|它){sentence_re}{_COMPLIMENT_TARGET_WORDS_RE}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)[:160]
    return ""


def _step4_detect_character_evaluated_by_user(user_message: str) -> str:
    text = str(user_message or "").strip()
    if not text:
        return ""
    sentence_re = r"[^。！？!?；;\n]{0,28}"
    patterns = [
        rf"(?:你|宝贝|角色|小马|老婆|老公){sentence_re}{_COMPLIMENT_TARGET_WORDS_RE}",
        rf"(?:夸你|夸夸你|你也){sentence_re}{_COMPLIMENT_TARGET_WORDS_RE}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)[:160]
    return ""


def _step4_seed_has_character_compliment_flip(text: str) -> bool:
    value = str(text or "")
    return bool(
        re.search(r"(?:角色|她|他|它|自己)?[^。！？!?；;\n]{0,18}被夸[^。！？!?；;\n]{0,18}" + _COMPLIMENT_TARGET_WORDS_RE, value)
        or re.search(r"(?:夸我|夸自己|我[^。！？!?；;\n]{0,8}帅|我[^。！？!?；;\n]{0,8}好看)", value)
    )


def _rewrite_step4_seed_user_evaluated_subject(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return value
    replacements = (
        ("表达被夸帅后的小得意", "表达夸完用户后的轻快、以及因用户保护而安心的撒娇"),
        ("被夸帅后的小得意", "夸完用户后的小得意和安心"),
        ("表达被夸后的得意", "表达夸完用户后的轻快和安心"),
        ("被夸后的小得意", "夸完用户后的小得意和安心"),
        ("角色被夸帅", "角色夸用户帅"),
        ("角色被夸", "角色夸用户"),
        ("被夸帅", "夸用户帅"),
        ("被夸漂亮", "夸用户漂亮"),
        ("被夸好看", "夸用户好看"),
        ("被夸厉害", "夸用户厉害"),
        ("被夸可爱", "夸用户可爱"),
        ("被夸", "夸用户"),
        ("夸我帅", "夸用户帅"),
        ("不夸我帅", "继续夸用户帅"),
    )
    for src, dst in replacements:
        value = value.replace(src, dst)
    value = re.sub(r"像['\"“‘]?那当然，我可是你怀里的小马呢['\"”’]?", "用角色自己的话延续撒娇和安心", value)
    value = re.sub(r"比如['\"“‘]?那当然，我可是你怀里的小马呢['\"”’]?", "比如继续夸用户刚才护着角色时很帅", value)
    return value.strip()


def _prepend_step4_subject_check(seed: str, check: str, *, limit: int = 600) -> str:
    seed_text = str(seed or "").strip()
    check_text = str(check or "").strip()
    if not check_text:
        return seed_text[:limit]
    prefix = f"主体核对：{check_text} "
    if seed_text.startswith(prefix) or check_text in seed_text[:120]:
        return seed_text[:limit]
    return (prefix + seed_text)[:limit]


def _apply_step4_subject_integrity_guard(
    plan: dict[str, Any],
    *,
    user_message: str,
    assistant_message: str,
) -> dict[str, Any]:
    if not isinstance(plan, dict) or not plan.get("enabled"):
        return plan
    existing_subject = plan.get("subject_integrity")
    if (
        isinstance(existing_subject, dict)
        and str(existing_subject.get("evaluated_subject") or "").strip() == "user"
        and str(existing_subject.get("seed_subject_check") or "").strip()
    ):
        return plan
    user_evidence = _step4_detect_user_evaluated_by_assistant(assistant_message)
    character_evidence = _step4_detect_character_evaluated_by_user(user_message)
    if not user_evidence or character_evidence:
        return plan

    seed = str(plan.get("seed") or "")
    reason = str(plan.get("reason") or "")
    if not (_step4_seed_has_character_compliment_flip(seed) or _step4_seed_has_character_compliment_flip(reason)):
        return plan

    checked = dict(plan)
    subject_check = (
        f"上一条角色评价的是用户（证据：{user_evidence}），不是角色被夸；"
        "主动续接不能写“我帅/夸我帅/角色被夸帅”，只能写角色继续夸用户或因用户保护而安心撒娇。"
    )
    checked["seed"] = _prepend_step4_subject_check(
        _rewrite_step4_seed_user_evaluated_subject(seed),
        subject_check,
        limit=600,
    )
    checked["reason"] = _rewrite_step4_seed_user_evaluated_subject(reason)[:400]
    checked["subject_integrity"] = {
        **(checked.get("subject_integrity") if isinstance(checked.get("subject_integrity"), dict) else {}),
        "evaluated_subject": "user",
        "source_character_action": user_evidence,
        "seed_subject_check": subject_check[:240],
    }
    return checked


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        m = re.search(r"-?\d+", value)
        if m:
            try:
                return int(m.group(0))
            except ValueError:
                return default
    return default


def _next_due_for_agreed_task(agreed_task: dict[str, Any], now_ms: int) -> int:
    schedule_type = str(agreed_task.get("schedule_type") or "once").strip().lower()
    if schedule_type == "interval":
        interval = max(MIN_DELAY_SECONDS, int(agreed_task.get("interval_seconds") or agreed_task.get("target_delay_seconds") or 3600))
        return now_ms + interval * 1000
    if schedule_type in {"daily", "weekly", "monthly"}:
        try:
            tz = ZoneInfo("Asia/Shanghai")
        except Exception:
            tz = LOCAL_TIMEZONE
        hhmm = str(agreed_task.get("time_of_day") or "08:00")
        try:
            hour, minute = [int(x) for x in hhmm.split(":", 1)]
        except Exception:
            hour, minute = 8, 0
        local_now = datetime.fromtimestamp(now_ms / 1000, tz=tz)
        due = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= local_now:
            due += timedelta(days=1)
        if schedule_type == "weekly":
            allowed = {int(x) for x in (agreed_task.get("days") or []) if isinstance(x, int) or str(x).isdigit()}
            if allowed:
                while due.weekday() not in allowed:
                    due += timedelta(days=1)
        elif schedule_type == "monthly":
            month_day = 1
            for item in agreed_task.get("days") or []:
                if isinstance(item, int) or str(item).isdigit():
                    month_day = max(1, min(31, int(item)))
                    break
            while due.day != min(month_day, _last_day_of_month(due)):
                due += timedelta(days=1)
        return int(due.timestamp() * 1000)
    delay = max(MIN_DELAY_SECONDS, int(agreed_task.get("target_delay_seconds") or MIN_DELAY_SECONDS))
    return now_ms + delay * 1000


def _last_day_of_month(value: datetime) -> int:
    if value.month == 12:
        next_month = value.replace(year=value.year + 1, month=1, day=1)
    else:
        next_month = value.replace(month=value.month + 1, day=1)
    return (next_month - timedelta(days=1)).day


async def _create_proactive_task_from_agreed(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    source_message_id: str,
    agreed_task: dict[str, Any],
    planner: dict[str, Any],
) -> Optional[str]:
    summary = str(agreed_task.get("summary") or "").strip()
    if not summary:
        return None
    now = _now_ms()
    schedule_type = str(agreed_task.get("schedule_type") or "once").strip().lower()
    if schedule_type not in {"once", "interval", "daily", "weekly", "monthly"}:
        schedule_type = "once"
    task_type = str(agreed_task.get("task_type") or "reminder").strip().lower()
    if task_type not in {"reminder", "timer", "appointment", "custom"}:
        task_type = "custom"
    task_id = f"pt_{uuid.uuid4().hex}"
    metadata = {
        "created_from": "normal_chat_user_agreed_task",
        "source_message_id": source_message_id,
        "user_agreed_task": agreed_task,
        "planner_user_agreed_task": agreed_task,
    }
    prompt = f"按用户在聊天里约定的定时任务自然提醒：{summary}"
    title = summary[:48] or "聊天约定提醒"
    db = get_database()
    await db.init()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await _configure_noncritical_conn(conn)
            await conn.execute(
                """
                INSERT INTO proactive_tasks (
                    id, username, character_id, conversation_id, source_message_id,
                    title, task_type, schedule_type, source, status, due_at_ms,
                    interval_seconds, time_of_day, timezone, days_json, jitter_minutes,
                    prompt, style, cancel_if_user_replies, metadata_json,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'user', 'active', ?, ?, ?, 'Asia/Shanghai', ?, 0, ?, 'gentle', ?, ?, ?, ?)
                """,
                (
                    task_id,
                    username,
                    character_id,
                    conversation_id,
                    source_message_id,
                    title,
                    task_type,
                    schedule_type,
                    _next_due_for_agreed_task(agreed_task, now),
                    max(0, int(agreed_task.get("interval_seconds") or agreed_task.get("target_delay_seconds") or 0)),
                    str(agreed_task.get("time_of_day") or "")[:5],
                    json.dumps(agreed_task.get("days") or [], ensure_ascii=False),
                    prompt[:1000],
                    1 if agreed_task.get("cancel_if_user_replies") else 0,
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            await conn.commit()
        logger.info("[ScheduledFollowup] created proactive task from chat id=%s type=%s schedule=%s", task_id, task_type, schedule_type)
        return task_id
    except Exception as exc:
        if _is_sqlite_locked(exc):
            logger.debug("[ScheduledFollowup] create proactive task skipped: database is locked")
        else:
            logger.warning("[ScheduledFollowup] create proactive task failed: %s", exc)
        return None


def _is_quiet_hour(ts_ms: Optional[int] = None) -> bool:
    dt = datetime.fromtimestamp((ts_ms or _now_ms()) / 1000, tz=LOCAL_TIMEZONE)
    return QUIET_HOUR_START <= dt.hour < QUIET_HOUR_END


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _latest_assistant_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "") == "assistant":
            return str(message.get("content") or "").strip()
    return ""


def _join_assistant_group(messages: list[dict[str, Any]]) -> str:
    parts = [
        str(message.get("content") or "").strip()
        for message in messages
        if str(message.get("role") or "") == "assistant" and str(message.get("content") or "").strip()
    ]
    return "\n\n".join(parts).strip()


def _latest_assistant_group_text(messages: list[dict[str, Any]]) -> str:
    group: list[dict[str, Any]] = []
    for message in reversed(messages or []):
        if str(message.get("role") or "") == "assistant":
            group.insert(0, message)
            continue
        if group:
            break
    return _join_assistant_group(group)


def _assistant_group_containing_message(
    messages: list[dict[str, Any]],
    message_id: str,
) -> str:
    target = str(message_id or "").strip()
    if not target:
        return ""
    idx = -1
    for i, message in enumerate(messages or []):
        if str(message.get("role") or "") == "assistant" and str(message.get("message_id") or "") == target:
            idx = i
            break
    if idx < 0:
        return ""
    start = idx
    while start > 0 and str((messages[start - 1] or {}).get("role") or "") == "assistant":
        start -= 1
    end = idx
    while end + 1 < len(messages) and str((messages[end + 1] or {}).get("role") or "") == "assistant":
        end += 1
    return _join_assistant_group(messages[start : end + 1])


def _voice_status_from_message(message: dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""
    state = message.get("voice_state") or message.get("voiceState")
    if isinstance(state, dict):
        status = str(state.get("voice_status") or state.get("voiceStatus") or state.get("status") or "").strip()
        if status:
            return status.lower()
    return str(message.get("voice_status") or message.get("voiceStatus") or "").strip().lower()


_TEXT_ONLY_DETAIL_SHORTCUTS = {
    "（请详细写出当前你的心理活动）",
    "（请详细写出当前你的身体状态）",
    "（请详细写出当前你看到的画面）",
}


def _compact_detail_shortcut_text(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _is_text_only_detail_shortcut(text: Any) -> bool:
    content = _compact_detail_shortcut_text(text)
    return content in {_compact_detail_shortcut_text(item) for item in _TEXT_ONLY_DETAIL_SHORTCUTS}


def _latest_assistant_was_voice(messages: list[dict[str, Any]]) -> bool:
    items = list(messages or [])
    for idx in range(len(items) - 1, -1, -1):
        message = items[idx]
        if str(message.get("role") or "") != "assistant":
            continue
        status = _voice_status_from_message(message)
        is_voice = status in {"ready", "pending"} or bool(message.get("audio_transfer") or message.get("audioTransfer"))
        if not is_voice:
            previous_user = ""
            for j in range(idx - 1, -1, -1):
                candidate = items[j]
                if isinstance(candidate, dict) and str(candidate.get("role") or "") == "user":
                    previous_user = str(candidate.get("content") or "")
                    break
            if _is_text_only_detail_shortcut(previous_user):
                continue
        return is_voice
    return False


def _compact_for_similarity(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or ""), flags=re.UNICODE)


def _char_bigrams(text: str) -> set[str]:
    compact = _compact_for_similarity(text)
    if len(compact) <= 1:
        return {compact} if compact else set()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _text_similarity(a: str, b: str) -> float:
    aa = _char_bigrams(a)
    bb = _char_bigrams(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / max(1, len(aa | bb))


def _has_common_followup_phrase(a: str, b: str, *, min_len: int = 7) -> bool:
    aa = _compact_for_similarity(a)
    bb = _compact_for_similarity(b)
    if len(aa) < min_len or len(bb) < min_len:
        return False
    if len(aa) > len(bb):
        aa, bb = bb, aa
    for size in range(min(18, len(aa)), min_len - 1, -1):
        for start in range(0, len(aa) - size + 1):
            if aa[start : start + size] in bb:
                return True
    return False


def _validate_generated_followup_content(
    content: str,
    recent_messages: list[dict[str, Any]],
    *,
    source_message_id: str = "",
) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {"ok": False, "reason": "empty_message"}

    last_assistant = _latest_assistant_text(recent_messages)
    if last_assistant:
        if _has_common_followup_phrase(text, last_assistant):
            return {"ok": False, "reason": "reuses_previous_assistant_core_phrase"}
        similarity = _text_similarity(text, last_assistant)
        # 定时跟进应推进新节拍；与上一条 assistant 词汇重叠过高通常是改写复读，缺乏价值。
        if similarity >= 0.62:
            return {"ok": False, "reason": "too_similar_to_previous_assistant"}

    candidates: list[tuple[str, str]] = [
        ("too_similar_to_previous_assistant_group", _latest_assistant_group_text(recent_messages)),
        ("too_similar_to_source_assistant_group", _assistant_group_containing_message(recent_messages, source_message_id)),
    ]
    seen: set[str] = set()
    for reason, candidate in candidates:
        candidate = str(candidate or "").strip()
        compact = _compact_for_similarity(candidate)
        if not compact or compact in seen:
            continue
        seen.add(compact)
        if _compact_for_similarity(text) == compact:
            return {"ok": False, "reason": reason}
        if _has_common_followup_phrase(text, candidate):
            return {"ok": False, "reason": reason}
        if _text_similarity(text, candidate) >= 0.72:
            return {"ok": False, "reason": reason}
    return {"ok": True}


def _is_user_conversation_end(text: str) -> bool:
    return bool(_USER_CONVERSATION_END_RE.search(str(text or "")))


def _is_early_morning_time_mismatch(text: str, ts_ms: Optional[int] = None) -> bool:
    """00:00–08:00 时段拦截语义上属于清晨/白天的内容。"""
    if not _is_quiet_hour(ts_ms):
        return False
    return bool(EARLY_MORNING_MISMATCH_RE.search(str(text or "")))


def _normalize_generated_long_dash_style(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return raw

    def _paren_depth(segment: str, depth: int) -> int:
        for ch in segment:
            if ch in "（(":
                depth += 1
            elif ch in "）)" and depth > 0:
                depth -= 1
        return depth

    parts: list[str] = []
    depth = 0
    cursor = 0
    for match in re.finditer(r"\s*—{2,}\s*", raw):
        before = raw[cursor:match.start()]
        parts.append(before)
        depth = _paren_depth(before, depth)
        parts.append("，" if depth > 0 else "\n\n")
        depth = _paren_depth(match.group(0), depth)
        cursor = match.end()
    parts.append(raw[cursor:])

    normalized = "".join(parts)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"([。！？!?…])\n\n([。！？!?…])", r"\1\2", normalized)
    normalized = re.sub(r"，{2,}", "，", normalized)
    normalized = re.sub(r"([。！？!?…])，", r"\1", normalized)
    return normalized


def clean_generated_proactive_content(raw: str, active_model: Optional[dict] = None) -> str:
    text = sanitize_assistant_strip_markers(str(raw or "").strip(), active_model if isinstance(active_model, dict) else {})
    text = re.sub(r"(?is)<think>.*?</think>", "", text).strip()
    if text.startswith("{") and "message" in text[:500]:
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                msg = str(obj.get("message") or "").strip()
                if msg:
                    text = msg
        except Exception:
            pass
    text = _normalize_generated_long_dash_style(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _scheduled_followup_debug_response(
    raw_response: Any,
    *,
    cleaned_content: str,
    raw_text: str = "",
    reasoning: str = "",
    full_raw_content: str = "",
    request_tokens_estimate: int = 0,
) -> dict[str, Any]:
    response = raw_response if isinstance(raw_response, dict) else {}
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    choices = response.get("choices") if isinstance(response.get("choices"), list) else []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    upstream_content = message.get("content", raw_text)
    upstream_reasoning = message.get("reasoning_content")
    prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    prompt_details = usage.get("prompt_tokens_details")
    cached_tokens = (
        int(prompt_details.get("cached_tokens") or 0)
        if isinstance(prompt_details, dict)
        else 0
    )
    cached_tokens = int(usage.get("prompt_cache_hit_tokens") or cached_tokens or 0)
    content = str(cleaned_content or "")
    raw_full = full_raw_content or raw_text or str(upstream_content or "")
    return {
        "kind": "scheduled_followup_response",
        "response_id": response.get("id"),
        "object": response.get("object"),
        "created": response.get("created"),
        "model": response.get("model"),
        "finish_reason": first_choice.get("finish_reason"),
        "request_tokens_estimate": int(request_tokens_estimate or 0),
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": int(usage.get("total_tokens") or (prompt_tokens + completion_tokens)),
            "prompt_cache_hit_tokens": cached_tokens,
            "raw": usage,
        },
        "assistant": {
            "content": content,
            "database_content": content,
            "delivery_content": content,
            "reasoning": reasoning or "",
            "has_reasoning": bool(str(reasoning or "").strip()),
            "content_chars": len(content),
            "reasoning_chars": len(reasoning or ""),
            "full_raw_content": raw_full,
            "cleaned_for_delivery": True,
        },
        "postprocess": {
            "long_dash_normalized": bool(re.search(r"—{2,}", str(upstream_content or raw_text or ""))),
            "content_changed": str(upstream_content or raw_text or "") != content,
        },
        "upstream_message": {
            "role": message.get("role"),
            "content": upstream_content,
            "reasoning_content": upstream_reasoning,
            "content_matches_database": upstream_content == content,
            "reasoning_matches_parsed": upstream_reasoning == reasoning,
        },
        "raw_response": copy.deepcopy(response) if isinstance(response, dict) else raw_response,
    }


def _planner_json(task: dict[str, Any]) -> dict[str, Any]:
    raw = task.get("planner_json")
    if not raw:
        raw = task.get("metadata_json")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _is_reminder_task(task: dict[str, Any]) -> bool:
    meta = _planner_json(task)
    agreed = coerce_user_agreed_task(meta.get("user_agreed_task"))
    return bool(agreed.get("enabled")) and str(agreed.get("task_type") or "") in {"reminder", "timer", "appointment", "custom"}


def _rough_late_label(late_seconds: int) -> str:
    if late_seconds <= 60:
        return "刚到点附近"
    if late_seconds <= 5 * 60:
        return "刚过一小会儿"
    if late_seconds <= REMINDER_NATURAL_WINDOW_SECONDS:
        return "稍微晚了一点"
    return "已经过太久"


def _step4_next_turn_prep_task_key(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
) -> str:
    return f"{username or ''}\0{character_id or ''}\0{conversation_id or ''}"


def _step4_generation_task_matches(
    meta: tuple[str, str, str, asyncio.Task],
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
) -> bool:
    u, c, conv, _task = meta
    return (
        u == str(username or "")
        and c == str(character_id or "")
        and conv == str(conversation_id or "")
    )


def _cancel_pending_step4_followup_generation(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
    *,
    reason: str = "user_message_arrived",
) -> int:
    cancelled = 0
    for task_id, meta in list(_pending_step4_followup_generation_tasks.items()):
        if not _step4_generation_task_matches(meta, username, character_id, conversation_id):
            continue
        _u, _c, _conv, task = meta
        if task and not task.done():
            task.cancel()
            cancelled += 1
            logger.info(
                "[ScheduledFollowup] cancelled Step 4 follow-up generation task=%s conv=%s reason=%s",
                task_id,
                str(conversation_id or "")[:12],
                reason,
            )
        _pending_step4_followup_generation_tasks.pop(task_id, None)
    return cancelled


def cancel_pending_step4_next_turn_prep_decision(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
    *,
    reason: str = "user_message_arrived",
) -> bool:
    """Cancel the in-flight Step 4 next-turn-prep active-task decision."""
    if not username or not character_id or not conversation_id:
        return False
    key = _step4_next_turn_prep_task_key(username, character_id, conversation_id)
    task = _pending_step4_next_turn_prep_tasks.pop(key, None)
    if task and not task.done():
        task.cancel()
        logger.info(
            "[ScheduledFollowup] cancelled Step 4 next-turn-prep decision conv=%s reason=%s",
            str(conversation_id)[:12],
            reason,
        )
        return True
    return False


def _loads_json_object_from_text(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    candidates = [text]
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        chunk = text[i : j + 1]
        if chunk != text:
            candidates.append(chunk)
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            continue
    return {}


def _compact_step4_next_turn_value(value: Any, limit: int = 900) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _step4_next_turn_recent_dialogue_lines(messages: list[dict[str, Any]] | None, *, limit: int = 8) -> str:
    rows = []
    for item in (messages or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = _compact_step4_next_turn_value(item.get("content"), 500)
        if content:
            rows.append(f"{role}: {content}")
    return "\n".join(rows)


def _step4_next_turn_planner_excerpt(planner: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(planner, dict):
        return {}
    keys = (
        "reply_intent",
        "tone",
        "length",
        "initiative_level",
        "speech_activity",
        "should_ask_question",
        "proactive_seed",
        "relationship_stage",
        "character_intimacy_style",
        "requested_escalation",
        "user_pressure_level",
        "memory_use_policy",
        "expression_policy",
        "risk_notes",
        "avoid_contradictions",
        "user_agreed_task",
    )
    return {key: planner.get(key) for key in keys if key in planner}


def _build_step4_next_turn_prep_decision_blob(
    *,
    user_message: str,
    assistant_message: str,
    recent_messages: list[dict[str, Any]] | None,
    planner: dict[str, Any] | None,
    character_profile: str = "",
    is_new_contact_opening: bool = False,
) -> str:
    parts = [
        "【当前用户消息】",
        _compact_step4_next_turn_value(user_message, 1600) or "（空）",
        "",
        "【Step 3 最终角色回复】",
        _compact_step4_next_turn_value(assistant_message, 2400) or "（空）",
        "",
        "【Step 3 后用户可见回复】",
        "无。Step 4 只在用户尚未回复时运行；不要把 Step 3 最终角色回复中的问题、邀请、挑衅、等待动作或“等你……”当成用户已经回答、同意、接招或做出新动作。",
        "",
        "【Step 1 意图识别摘要】",
        json.dumps(_step4_next_turn_planner_excerpt(planner), ensure_ascii=False),
        "",
        "【Step 2 工具摘要】",
        _compact_step4_next_turn_value(character_profile, 1200) or "（无）",
        "",
        "【最近对话】",
        _step4_next_turn_recent_dialogue_lines(recent_messages, limit=8) or "（无）",
        "",
        "【系统状态】",
        f"是否新联系人开场：{'是' if is_new_contact_opening else '否'}",
        "",
        "请判断是否安排主动任务 scheduled_followup。只输出 JSON。",
    ]
    return "\n".join(parts)


def schedule_step4_next_turn_prep_decision(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    source_message_id: str,
    user_message: str,
    assistant_message: str,
    recent_messages: list[dict[str, Any]] | None = None,
    planner: dict[str, Any] | None = None,
    character_profile: str = "",
    is_new_contact_opening: bool = False,
    chain_id: str = "",
    chain_count: int = 0,
) -> None:
    """Start Step 4 next-turn-prep active-task decision without blocking the visible reply."""
    if not username or not character_id or not conversation_id or not source_message_id:
        return
    key = _step4_next_turn_prep_task_key(username, character_id, conversation_id)
    old = _pending_step4_next_turn_prep_tasks.get(key)
    if old and not old.done():
        old.cancel()

    async def _runner() -> None:
        try:
            await _run_step4_next_turn_prep_decision(
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                user_message=user_message,
                assistant_message=assistant_message,
                recent_messages=recent_messages or [],
                planner=planner or {},
                character_profile=character_profile,
                is_new_contact_opening=is_new_contact_opening,
                chain_id=chain_id,
                chain_count=chain_count,
            )
        except asyncio.CancelledError:
            logger.debug(
                "[ScheduledFollowup] Step 4 next-turn-prep decision cancelled conv=%s",
                str(conversation_id)[:12],
            )
            raise
        except Exception as exc:
            logger.warning("[ScheduledFollowup] Step 4 next-turn-prep decision failed: %s", exc)

    task = asyncio.create_task(_runner())
    _pending_step4_next_turn_prep_tasks[key] = task

    def _cleanup(done: asyncio.Task) -> None:
        current = _pending_step4_next_turn_prep_tasks.get(key)
        if current is done:
            _pending_step4_next_turn_prep_tasks.pop(key, None)

    task.add_done_callback(_cleanup)
