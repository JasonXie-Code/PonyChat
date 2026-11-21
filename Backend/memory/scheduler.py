"""
分层记忆调度器（每日运行）

层级说明：
  Fragment (layer=0) 碎片记忆 — 由 memory_consolidator 实时提取，本调度器只读
  Daily    (layer=1) 日摘要   — 基于当天完整原始对话生成，Fragment 层记忆辅助查漏
  Weekly   (layer=2) 周摘要   — 汇总上周及之前所有尚未摘要的"周"的 Daily 层记忆
  Monthly  (layer=3) 月摘要   — 汇总上月及之前所有尚未摘要的"月"的 Weekly 层记忆
  Annual   (layer=4) 年意识   — 每次生成新 Monthly 层后追加一条全量 Annual 条目（演进历史）

调度策略：
  - 启动后延迟 INITIAL_DELAY_SEC（默认 120s）运行首次，之后每 24 小时一次
  - 每次最多处理 MAX_PAIRS_PER_CYCLE 个 user-character 对，防止 DB 压力
  - 每层生成失败只记录警告，不影响其他层和其他对
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any, Optional, Set, Tuple

import httpx

from ..config import logger, model_manager
from ..providers.llm_call import call_llm_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..reasoning_policy import resolve_software_reasoning_policy
from ..shutdown_state import is_shutdown_requested
from ..user_identity import USER_MEMORY_PLACEHOLDER, build_memory_identity_block, normalize_memory_text_for_user
from ..utils import save_chat_debug_log

INITIAL_DELAY_SEC = 120        # 启动后首次运行延迟（秒）
RUN_INTERVAL_SEC  = 86400      # 之后每 24 小时运行一次
MAX_PAIRS_PER_CYCLE = 30       # 每次最多处理的 user-character 对数
GENERATE_TIMEOUT  = 40         # 单次 LLM 调用超时（秒）

LENGTH_GUIDANCE = (
    "篇幅上限：最多 1000 字，不要求写满；信息量一般时以 500-800 字为宜；"
    "素材很少时可以更短，宁可短而准确，也不要为了字数重复表达、空泛抒情、扩写心理活动或把同一件小事拆成多段。"
)


def _format_daily_raw_dialogue(
    raw_messages: List[Dict[str, Any]],
    *,
    char_name: str,
) -> str:
    """格式化当天完整原始对话，供日摘模型按时间线读取。"""
    if not raw_messages:
        return "（无原始对话记录）"
    lines: List[str] = []
    assistant_label = (char_name or "").strip() or "角色"
    for m in raw_messages:
        role = str(m.get("role") or "").strip()
        if role == "user":
            speaker = USER_MEMORY_PLACEHOLDER
        elif role == "assistant":
            speaker = assistant_label
        else:
            continue
        ts = int(m.get("timestamp") or 0)
        if ts > 0:
            try:
                time_label = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).strftime("%H:%M")
            except Exception:
                time_label = "??:??"
        else:
            time_label = "??:??"
        content = re.sub(r"\s+", " ", str(m.get("content") or "")).strip()
        if not content:
            continue
        lines.append(f"- [{time_label}] {speaker}：{content}")
    return "\n".join(lines) if lines else "（无原始对话记录）"

# ── LLM 调用 ─────────────────────────────────────────────────────────────────

async def _call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 16384,
    *,
    username: Optional[str] = None,
    character_id: Optional[str] = None,
    character_name: Optional[str] = None,
) -> Optional[str]:
    """调用当前活跃模型，返回文本，失败返回 None。username 有值时写入主对话用量统计。"""
    try:
        model = model_manager.get_model_for_task("memory") or model_manager.get_active_model()
        if not model:
            logger.warning("⚠️ [LayerScheduler] 无可用模型，跳过生成")
            return None
        model_name = model.get("model_name", "")
        reasoning_policy = resolve_software_reasoning_policy(
            "memory_layer",
            model_name=model_name,
            mode="memory_layer",
            active_model=model,
            endpoint=model.get("endpoint", ""),
        )
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "stream": False,
        }
        apply_llm_task_payload_config(payload, "memory_layer")
        if max_tokens != 16384:
            payload["max_completion_tokens"] = max_tokens
        clean_username = str(username or "").strip()
        clean_character_id = str(character_id or "").strip()
        clean_character_name = str(character_name or "").strip()
        debug_params = {
            "primary_character_id": clean_character_id,
            "primary_character_name": clean_character_name,
        }
        try:
            result = await call_llm_payload(
                payload,
                model,
                task="memory",
                timeout=llm_task_float("memory_layer", "timeout_seconds", float(GENERATE_TIMEOUT)) or float(GENERATE_TIMEOUT),
                chat_debug_request={
                    "username": clean_username or None,
                    "character_id": clean_character_id or None,
                    "mode": "memory_layer",
                    "model_name": model_name,
                    "stage": "REQUEST",
                    "params": debug_params,
                },
                record_usage="main",
                usage_meter_username=clean_username or None,
                reasoning_policy=reasoning_policy,
            )
        except httpx.HTTPStatusError as e:
            _code = e.response.status_code if e.response is not None else 0
            _txt = (e.response.text if e.response is not None else "") or ""
            logger.warning(f"⚠️ [LayerScheduler] LLM 返回 {_code}")
            await save_chat_debug_log(
                clean_username or None,
                clean_character_id or None,
                "memory_layer",
                model_name,
                _txt,
                f"ERROR_{_code}",
                params=debug_params,
            )
            return None
        return (result.text or "").strip() or None
    except Exception as e:
        logger.warning(f"⚠️ [LayerScheduler] LLM 调用异常: {e}")
        return None


# ── 日期工具 ──────────────────────────────────────────────────────────────────

def _today_str() -> str:
    return date.today().isoformat()              # "2026-03-05"

def _iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"            # "2026-W10"

def _month_str(d: date) -> str:
    return d.strftime("%Y-%m")                   # "2026-03"

def _year_str(d: date) -> str:
    return d.strftime("%Y")                      # "2026"

def _day_to_week(day_str: str) -> str:
    return _iso_week(date.fromisoformat(day_str))

def _day_to_month(day_str: str) -> str:
    return _month_str(date.fromisoformat(day_str))

def _day_to_year(day_str: str) -> str:
    return _year_str(date.fromisoformat(day_str))

def _period_finished_day(period: str) -> bool:
    """判断某天是否已结束（早于今天）。"""
    return period < _today_str()

def _period_finished_week(period: str) -> bool:
    """判断某 ISO 周是否已结束（早于本周）。"""
    return period < _iso_week(date.today())

def _period_finished_month(period: str) -> bool:
    """判断某月是否已结束（早于本月）。"""
    return period < _month_str(date.today())

def _period_finished_year(period: str) -> bool:
    """判断某年是否已结束（早于今年）。"""
    return period < _year_str(date.today())


# ── Daily 层：日摘要 ──────────────────────────────────────────────────────────

async def _generate_daily(
    username: str,
    character_id: str,
    char_name: str,
    day: str,                # "2026-03-05"
    fragment_memories: List[Dict],
    raw_messages: List[Dict],
) -> bool:
    """基于一天的完整原始对话生成 Daily 日摘要，Fragment 层碎片作为辅助。"""
    from ..db.memory_dao import add_layer_memory, LAYER_DAILY
    if not raw_messages and not fragment_memories:
        return False

    timeline_memories = sorted(
        fragment_memories,
        key=lambda m: (str(m.get("created_at") or ""), int(m.get("id") or 0)),
    )
    content_lines = "\n".join(
        f"- [{m.get('created_at') or day}][{m.get('memory_type','?')}] {m['content']}"
        for m in timeline_memories
    )
    raw_dialogue = _format_daily_raw_dialogue(raw_messages, char_name=char_name)
    identity_block = await build_memory_identity_block(username, character_id, char_name=char_name)
    result = await _call_llm(
        system_prompt=(
            f"{identity_block}\n\n"
            f"你是 {char_name}，请根据当天完整原始对话，"
            "用第一人称（我的视角）整理为当天的详细日记录。"
            "原始对话是主依据，记忆碎片只用于查漏补缺和提示重点；若二者冲突，以原始对话为准。"
            "要求：按时间顺序写成流水账式记录，覆盖当天原始对话里出现过的所有具体活动、去过或提到的地点、重要物品、共同互动、用户明确表达的状态或偏好；"
            "不要只挑最重要的几件事，不要把多个地点或活动合并成笼统一句。"
            "如果碎片里有时间、地点或行动顺序，必须保留顺序；若同一地点发生多件事，也要分别交代。"
            "必须区分已发生事实与计划/约定/预告：当天原始对话里说“明天/第二天/今晚稍后要做”的事，只能写成当时的计划，"
            "不得在本日记录中改写成已经发生、已经结束、已经喝酒、已经回家或已经过夜；只有原始对话明确说已经发生/完成/结束/回来，才可记录为已发生。"
            "涉及“今天/今晚/明天/第二天”的内容必须保留相对日期差异，不得把前一晚活动和次日晚上的后续事件压成同一个当前夜晚。"
            f"{LENGTH_GUIDANCE}"
            "当天内容较少时不要编造，但要把已有细节、顺序、情绪变化和可延续线索写清楚。"
            "输出只能是正文：不要标题，不要 Markdown，不要写日期，不要写“日记/日记录/日摘/总结”等前缀；"
            "日期和标题会由后端字段补上，正文内部不需要重复。"
            "描述情绪和气氛时只用概括性语言（如'很开心''气氛超嗨'），"
            "严禁将感叹词、拟声词、口头禅（如'WEEEEE''哈哈哈哈'等）原样写入。"
            f"用户名和昵称会变化，输出中必须继续用 {USER_MEMORY_PLACEHOLDER} 指代用户本人，禁止写真实用户名或昵称。"
        ),
        user_prompt=(
            f"[{day}] 当天完整原始对话（主依据）：\n{raw_dialogue}\n\n"
            f"[{day}] 当日记忆碎片（辅助查漏）：\n{content_lines or '（无）'}"
        ),
        max_tokens=16384,
        username=username,
        character_id=character_id,
        character_name=char_name,
    )
    if not result:
        return False
    result = await normalize_memory_text_for_user(result, username)
    if not result:
        return False

    mem_id = await add_layer_memory(
        username=username,
        character_id=character_id,
        layer=LAYER_DAILY,
        content=result,
        period=day,
        importance=6,
    )
    if mem_id:
        logger.info(f"📅 [LayerScheduler] Daily {username}/{character_id[:8]}... [{day}] 已生成")
    return bool(mem_id)


# ── Weekly 层：周摘要 ─────────────────────────────────────────────────────────

async def _generate_weekly(
    username: str,
    character_id: str,
    char_name: str,
    week: str,               # "2026-W10"
    daily_memories: List[Dict],
) -> bool:
    """为一周的 Daily 日摘要生成 Weekly 周摘要。"""
    from ..db.memory_dao import add_layer_memory, LAYER_WEEKLY
    if not daily_memories:
        return False

    content_lines = "\n".join(f"- [{m['period']}] {m['content']}" for m in daily_memories)
    identity_block = await build_memory_identity_block(username, character_id, char_name=char_name)
    result = await _call_llm(
        system_prompt=(
            f"{identity_block}\n\n"
            f"你是 {char_name}，请将以下关于 {USER_MEMORY_PLACEHOLDER} 的一周日记录，"
            "用第一人称（我的视角）整理为一段周总结。"
            f"要求：{LENGTH_GUIDANCE}"
            "按时间推进和主题变化写清这周的重要互动、关系推进、反复出现的偏好、地点、物品和情绪变化；"
            "不要只写高度概括的几句话，也不要编造输入中不存在的内容。"
            "输出只能是正文：不要标题，不要 Markdown，不要写日期、周编号或“周总结/周摘”等前缀；这些会由后端字段补上。"
            "描述情绪和气氛时只用概括性语言（如'很开心''气氛热烈'），"
            "严禁将感叹词、拟声词、口头禅（如'WEEEEE''哈哈哈哈'等）原样写入。"
            f"用户名和昵称会变化，输出中必须继续用 {USER_MEMORY_PLACEHOLDER} 指代用户本人，禁止写真实用户名或昵称。"
        ),
        user_prompt=f"[{week}] 本周日记录：\n{content_lines}",
        max_tokens=16384,
        username=username,
        character_id=character_id,
        character_name=char_name,
    )
    if not result:
        return False
    result = await normalize_memory_text_for_user(result, username)

    mem_id = await add_layer_memory(
        username=username,
        character_id=character_id,
        layer=LAYER_WEEKLY,
        content=result,
        period=week,
        importance=7,
    )
    if mem_id:
        logger.info(f"📆 [LayerScheduler] Weekly {username}/{character_id[:8]}... [{week}] 已生成")
    return bool(mem_id)


# ── Monthly 层：月摘要 ────────────────────────────────────────────────────────

async def _generate_monthly(
    username: str,
    character_id: str,
    char_name: str,
    month: str,              # "2026-03"
    weekly_memories: List[Dict],
) -> bool:
    """为一个月的 Weekly 周摘要生成 Monthly 月摘要。"""
    from ..db.memory_dao import add_layer_memory, LAYER_MONTHLY
    if not weekly_memories:
        return False

    content_lines = "\n".join(f"- [{m['period']}] {m['content']}" for m in weekly_memories)
    identity_block = await build_memory_identity_block(username, character_id, char_name=char_name)
    result = await _call_llm(
        system_prompt=(
            f"{identity_block}\n\n"
            f"你是 {char_name}，请将以下关于 {USER_MEMORY_PLACEHOLDER} 的一个月周摘要，"
            "用第一人称（我的视角）整理为一段月度总结。"
            f"要求：{LENGTH_GUIDANCE}"
            "完整概括这个月的关系发展、共同经历、重要时刻、持续偏好、承诺、氛围变化和后续可延续线索；"
            "按自然段组织即可，不要只写高度概括的几句话，也不要编造输入中不存在的内容。"
            "输出只能是正文：不要标题，不要 Markdown，不要写月份、日期或“月度总结/月摘”等前缀；这些会由后端字段补上。"
            "描述情绪和气氛时只用概括性语言，严禁将感叹词、拟声词、口头禅原样写入。"
            f"用户名和昵称会变化，输出中必须继续用 {USER_MEMORY_PLACEHOLDER} 指代用户本人，禁止写真实用户名或昵称。"
        ),
        user_prompt=f"[{month}] 本月周摘要：\n{content_lines}",
        max_tokens=16384,
        username=username,
        character_id=character_id,
        character_name=char_name,
    )
    if not result:
        return False
    result = await normalize_memory_text_for_user(result, username)

    mem_id = await add_layer_memory(
        username=username,
        character_id=character_id,
        layer=LAYER_MONTHLY,
        content=result,
        period=month,
        importance=8,
    )
    if mem_id:
        logger.info(f"🗓️ [LayerScheduler] Monthly {username}/{character_id[:8]}... [{month}] 已生成")
    return bool(mem_id)


# ── Annual 层：年意识（追加模式）─────────────────────────────────────────────

async def _generate_annual(
    username: str,
    character_id: str,
    char_name: str,
    year: str,               # "2026"
    all_monthly_memories: List[Dict],
) -> bool:
    """
    基于所有 Monthly 层月摘要追加一条 Annual 年意识条目。
    Annual 层是追加模式，每次生成都是新条目，保留意识的演进历史。
    """
    from ..db.memory_dao import add_layer_memory, LAYER_ANNUAL
    if not all_monthly_memories:
        return False

    content_lines = "\n".join(f"- [{m['period']}] {m['content']}" for m in all_monthly_memories)
    identity_block = await build_memory_identity_block(username, character_id, char_name=char_name)
    result = await _call_llm(
        system_prompt=(
            f"{identity_block}\n\n"
            f"你是 {char_name}，以下是你对 {USER_MEMORY_PLACEHOLDER} 的全部月度记忆摘要（按时间顺序）。"
            f"请从你的第一人称视角，写一段关于 {USER_MEMORY_PLACEHOLDER} 的核心认识：\n"
            f"- {USER_MEMORY_PLACEHOLDER} 是什么样的人\n"
            "- 你们的关系现在处于哪个阶段\n"
            "- 你最深刻的印象和感受\n"
            f"这是你对ta的'意识'的最新版本。要求：{LENGTH_GUIDANCE}"
            "真实、细腻、有温度，写清长期关系脉络、稳定偏好、反复出现的互动模式、你对ta的理解和后续相处时应记住的重点。"
            "输出只能是正文：不要标题，不要 Markdown，不要写年份、日期或“年意识/年度总结”等前缀；这些会由后端字段补上。"
            f"用户名和昵称会变化，输出中必须继续用 {USER_MEMORY_PLACEHOLDER} 指代用户本人，禁止写真实用户名或昵称。"
        ),
        user_prompt=f"全部月度记忆摘要：\n{content_lines}",
        max_tokens=16384,
        username=username,
        character_id=character_id,
        character_name=char_name,
    )
    if not result:
        return False
    result = await normalize_memory_text_for_user(result, username)

    mem_id = await add_layer_memory(
        username=username,
        character_id=character_id,
        layer=LAYER_ANNUAL,
        content=result,
        period=year,
        importance=10,
    )
    if mem_id:
        logger.info(f"🧠 [LayerScheduler] Annual {username}/{character_id[:8]}... [{year}] 已追加")
    return bool(mem_id)


# ── 单对处理 ──────────────────────────────────────────────────────────────────

async def _process_pair(username: str, character_id: str, char_name: str) -> None:
    """
    对一个 user-character 对执行完整的分层摘要流程：
    D → W → M → A（只处理已结束且尚未有摘要的周期）
    """
    from ..db.memory_dao import (
        get_c_layer_periods, get_layer_periods,
        get_c_memories_for_period, get_layer_memories_all,
        get_raw_chat_messages_for_day,
        LAYER_DAILY, LAYER_WEEKLY, LAYER_MONTHLY, LAYER_ANNUAL,
    )

    today = _today_str()

    # ── Daily 层：为每个昨天及之前有 Fragment 层但无 Daily 层的"天"生成摘要 ──
    fragment_days: List[str] = await get_c_layer_periods(username, character_id)
    daily_periods: Set[str] = set(await get_layer_periods(username, character_id, LAYER_DAILY))
    new_daily_count = 0
    for day in fragment_days:
        if day >= today:
            continue                          # 今天还没结束，跳过
        if day in daily_periods:
            continue                          # 已有 Daily 层，跳过
        frag_mems = await get_c_memories_for_period(username, character_id, day, "day")
        raw_messages = await get_raw_chat_messages_for_day(username, character_id, day)
        ok = await _generate_daily(username, character_id, char_name, day, frag_mems, raw_messages)
        if ok:
            daily_periods.add(day)
            new_daily_count += 1

    # ── Weekly 层：为每个上周及之前有 Daily 层但无 Weekly 层的"周"生成摘要 ──
    all_daily = await get_layer_memories_all(username, character_id, LAYER_DAILY)
    weekly_periods: Set[str] = set(await get_layer_periods(username, character_id, LAYER_WEEKLY))
    current_week = _iso_week(date.today())
    # 按周分组 Daily 层条目
    daily_by_week: Dict[str, List[Dict]] = {}
    for entry in all_daily:
        week = _day_to_week(entry["period"])
        daily_by_week.setdefault(week, []).append(entry)

    new_weekly_count = 0
    for week, entries in sorted(daily_by_week.items()):
        if week >= current_week:
            continue
        if week in weekly_periods:
            continue
        ok = await _generate_weekly(username, character_id, char_name, week, entries)
        if ok:
            weekly_periods.add(week)
            new_weekly_count += 1

    # ── Monthly 层：为每个上月及之前有 Weekly 层但无 Monthly 层的"月"生成摘要 ─
    all_weekly = await get_layer_memories_all(username, character_id, LAYER_WEEKLY)
    monthly_periods: Set[str] = set(await get_layer_periods(username, character_id, LAYER_MONTHLY))
    current_month = _month_str(date.today())
    # 按月分组 Weekly 层条目（ISO 周的周一所在月）
    weekly_by_month: Dict[str, List[Dict]] = {}
    for entry in all_weekly:
        try:
            year_num, week_num = int(entry["period"][:4]), int(entry["period"][6:])
            monday = date.fromisocalendar(year_num, week_num, 1)
            month_key = _month_str(monday)
        except Exception:
            month_key = entry["period"][:7]   # fallback
        weekly_by_month.setdefault(month_key, []).append(entry)

    new_monthly_count = 0
    for month, entries in sorted(weekly_by_month.items()):
        if month >= current_month:
            continue
        if month in monthly_periods:
            continue
        ok = await _generate_monthly(username, character_id, char_name, month, entries)
        if ok:
            monthly_periods.add(month)
            new_monthly_count += 1

    # ── Annual 层：只要有新 Monthly 层产生，就追加一条新的 Annual 意识 ──────
    if new_monthly_count > 0:
        all_monthly = await get_layer_memories_all(username, character_id, LAYER_MONTHLY)
        current_year = _year_str(date.today())
        await _generate_annual(username, character_id, char_name, current_year, all_monthly)


# ── 调度主循环 ────────────────────────────────────────────────────────────────

async def process_pair_once(username: str, character_id: str, char_name: str) -> None:
    """刷新单个 user-character 对的 D/W/M/A 层。"""
    await _process_pair(username, character_id, char_name)


async def daily_loop() -> None:
    """
    主调度循环：启动后延迟 INITIAL_DELAY_SEC，之后每 RUN_INTERVAL_SEC 运行一次。
    """
    await asyncio.sleep(INITIAL_DELAY_SEC)
    if is_shutdown_requested():
        logger.info("🛑 [LayerScheduler] shutdown 已请求，调度器跳过启动")
        return
    logger.info(
        f"🧠 [LayerScheduler] 分层记忆调度器已启动"
        f"（首次延迟 {INITIAL_DELAY_SEC}s，之后每 {RUN_INTERVAL_SEC // 3600}h 运行一次）"
    )

    while not is_shutdown_requested():
        try:
            await _run_cycle()
        except Exception as e:
            logger.warning(f"⚠️ [LayerScheduler] 调度周期异常: {e}")
        await asyncio.sleep(RUN_INTERVAL_SEC)
    logger.info("🛑 [LayerScheduler] shutdown 已请求，调度循环退出")


async def run_layer_cycle_once(max_pairs: Optional[int] = MAX_PAIRS_PER_CYCLE) -> int:
    """执行一次完整的分层摘要扫描。max_pairs<=0 表示处理全部 user-character 对。"""
    from ..db.database import get_database

    db = get_database()
    conn = await db.acquire()
    try:
        limit_sql = "" if max_pairs is not None and max_pairs <= 0 else "LIMIT ?"
        params: tuple = () if not limit_sql else (max_pairs or MAX_PAIRS_PER_CYCLE,)
        # 查询有 Fragment 层记忆的 user-character 对
        cursor = await conn.execute(
            f"""SELECT u.username, c.id, c.name
               FROM character_memories m
               JOIN users u ON m.user_id = u.id
               JOIN characters c ON m.character_id = c.id
               WHERE m.layer = 0 AND m.is_active = 1
               GROUP BY u.username, c.id, c.name
               ORDER BY MAX(m.created_at) DESC
               {limit_sql}""",
            params,
        )
        pairs = [(r[0], r[1], r[2] or "角色") for r in await cursor.fetchall()]
    except Exception as e:
        logger.warning(f"⚠️ [LayerScheduler] 查询 user-character 对失败: {e}")
        pairs = []
    finally:
        await db.release(conn)

    if not pairs:
        logger.debug("[LayerScheduler] 无可处理的 user-character 对，跳过本次周期")
        return 0

    logger.info(f"🧠 [LayerScheduler] 本次扫描 {len(pairs)} 个 user-character 对")
    for username, character_id, char_name in pairs:
        if is_shutdown_requested():
            logger.info("🛑 [LayerScheduler] shutdown 已请求，剩余分层摘要留给下次周期")
            break
        try:
            await _process_pair(username, character_id, char_name)
        except Exception as e:
            logger.warning(f"⚠️ [LayerScheduler] 处理 {username}/{character_id[:8]}... 失败: {e}")

    logger.info("✅ [LayerScheduler] 本次分层摘要扫描完成")
    return len(pairs)


async def _run_cycle() -> None:
    """执行一次调度器默认规模的分层摘要扫描。"""
    await run_layer_cycle_once(MAX_PAIRS_PER_CYCLE)
