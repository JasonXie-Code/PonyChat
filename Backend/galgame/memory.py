"""Galgame 角色短期记忆（语义事件流）：异步更新 + 提示词注入 + 分层摘要。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from ..config import logger
from ..reasoning_config import llm_task_float
from .seq_prompts import _SEQ_CHAR_MEMORY_UPDATE
from .utils import try_fix_json

# 分层记忆：达到 KEEP_VERBATIM_MAX+1 条时触发摘要并裁剪为 KEEP_VERBATIM_AFTER_TRIM 条
KEEP_VERBATIM_MAX = 15
KEEP_VERBATIM_AFTER_TRIM = 8
SHORT_TERM_MAX_TURNS = 16

# 兼容旧名
CHAR_MEMORY_MAX_ENTRIES = KEEP_VERBATIM_MAX

_pending_memory_tasks: dict[str, asyncio.Task] = {}
_memory_locks: dict[str, asyncio.Lock] = {}


def _session_key(username: str, character_id: str, game_type: str) -> str:
    return f"{username}\x00{character_id}\x00{game_type}"


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _memory_locks:
        _memory_locks[key] = asyncio.Lock()
    return _memory_locks[key]


def _entry_turn(ent: dict, fallback: int) -> int:
    try:
        return int(ent.get("turn", fallback))
    except (TypeError, ValueError):
        return fallback


def _format_entries_block(entries: list, *, start_index: int = 1) -> str:
    lines: list[str] = []
    for i, ent in enumerate(entries):
        if not isinstance(ent, dict):
            continue
        turn = _entry_turn(ent, start_index + i)
        t_val = str(ent.get("time") or "").strip()
        l_val = str(ent.get("location") or "").strip()
        scene_tag = f"[{t_val}/{l_val}] " if (t_val and t_val != "未知") or (l_val and l_val != "未知") else ""
        parts = [f"· 第{turn}轮 {scene_tag}".rstrip()]
        for k, label in (
            ("player_action", "玩家"),
            ("event", "事件"),
            ("char_change", "角色变化"),
            ("relationship", "关系"),
            ("emotional_note", "情绪"),
        ):
            v = ent.get(k)
            if v:
                parts.append(f"{label}：{v}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def format_tiered_memory_for_prompt(char_memory: Any, state: dict | None) -> str:
    """三段式：长期 / 短期 / 对话历史；state 可为空 dict。"""
    state = state if isinstance(state, dict) else {}
    blocks: list[str] = []

    lt = str(state.get("longTermMemory") or "").strip()
    ltc = state.get("longTermMemoryCutoffTurn")
    if lt:
        if ltc is not None:
            try:
                ltc_i = int(ltc)
                title_rng = f"第0-{ltc_i}轮"
            except (TypeError, ValueError):
                title_rng = ""
        else:
            title_rng = ""
        blocks.append(f"【中期记忆】\n{title_rng + ' ' if title_rng else ''}{lt}".strip())

    st = str(state.get("shortTermMemory") or "").strip()
    sts = state.get("shortTermMemoryStartTurn")
    stc = state.get("shortTermMemoryCutoffTurn")
    if st:
        rng = ""
        if sts is not None and stc is not None:
            try:
                rng = f"第{int(sts)}-{int(stc)}轮 "
            except (TypeError, ValueError):
                rng = ""
        blocks.append(f"【短期记忆】\n{rng}{st}".strip())

    cm_lines = _format_dialogue_history_only(char_memory)
    if cm_lines:
        blocks.append(cm_lines)

    return "\n\n".join(blocks) if blocks else ""


def _format_dialogue_history_only(char_memory: Any) -> str:
    if not isinstance(char_memory, dict):
        return ""
    entries = char_memory.get("entries")
    if not isinstance(entries, list) or not entries:
        return ""
    lines: list[str] = [
        "【对话历史】",
        "以下为各轮已发生事实的客观记录；只描述已发生之事，不含预测或计划；请据此推进叙事，**禁止**复述或模仿其中任何措辞。",
    ]
    for i, ent in enumerate(entries, 1):
        if not isinstance(ent, dict):
            continue
        turn = _entry_turn(ent, i)
        t_val = str(ent.get("time") or "").strip()
        l_val = str(ent.get("location") or "").strip()
        scene_tag = f"[{t_val}/{l_val}] " if (t_val and t_val != "未知") or (l_val and l_val != "未知") else ""
        parts = [f"· 第{turn}轮 {scene_tag}".rstrip()]
        for k, label in (
            ("player_action", "玩家"),
            ("event", "事件"),
            ("char_change", "角色变化"),
            ("relationship", "关系"),
            ("emotional_note", "情绪"),
        ):
            v = ent.get(k)
            if v:
                parts.append(f"{label}：{v}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _clean_profile_string(value: object, *, max_len: int = 160) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


def normalize_repetition_profile(raw: Any) -> dict:
    """将第 10 步去重档案归一化为适合注入提示词的小型结构。"""
    if not isinstance(raw, dict):
        return {}

    avoid: list[str] = []
    for item in raw.get("avoid_next_turn") or []:
        text = _clean_profile_string(item, max_len=180)
        if text and text not in avoid:
            avoid.append(text)
        if len(avoid) >= 5:
            break

    surface: list[dict[str, Any]] = []
    for item in raw.get("overused_surface_patterns") or []:
        if not isinstance(item, dict):
            continue
        pattern = _clean_profile_string(item.get("pattern"), max_len=80)
        if not pattern:
            continue
        kind = _clean_profile_string(item.get("type"), max_len=40)
        meaning = _clean_profile_string(item.get("meaning"), max_len=100)
        try:
            cooldown = int(item.get("cooldown_turns") or 3)
        except (TypeError, ValueError):
            cooldown = 3
        surface.append(
            {
                "pattern": pattern,
                "type": kind or "surface_pattern",
                "meaning": meaning,
                "cooldown_turns": max(1, min(8, cooldown)),
            }
        )
        if len(surface) >= 8:
            break

    loops: list[dict[str, Any]] = []
    for item in raw.get("semantic_loops") or []:
        if not isinstance(item, dict):
            continue
        pattern = _clean_profile_string(item.get("pattern"), max_len=120)
        if not pattern:
            continue
        alts: list[str] = []
        for alt in item.get("suggested_alternatives") or []:
            alt_text = _clean_profile_string(alt, max_len=60)
            if alt_text and alt_text not in alts:
                alts.append(alt_text)
            if len(alts) >= 5:
                break
        loops.append(
            {
                "pattern": pattern,
                "meaning": _clean_profile_string(item.get("meaning"), max_len=120),
                "suggested_alternatives": alts,
            }
        )
        if len(loops) >= 5:
            break

    profile = {
        "avoid_next_turn": avoid,
        "overused_surface_patterns": surface,
        "semantic_loops": loops,
    }
    if not any(profile.values()):
        return {}
    return profile


def format_repetition_profile_for_prompt(state: dict | None) -> str:
    """将第 10 步语义去重档案格式化为下一轮提示词块。"""
    if not isinstance(state, dict):
        return ""
    profile = normalize_repetition_profile(state.get("repetition_profile"))
    if not profile:
        return ""

    lines = [
        "【上一轮第10步去重档案｜下一轮表达冷却】",
        "以下内容由上轮记忆分析生成，用于保持状态连续但避免表层表达循环；优先级低于玩家本轮明确动作，高于普通叙事惯性。",
    ]
    avoid = profile.get("avoid_next_turn") or []
    if avoid:
        lines.append("下一轮避免：")
        for item in avoid:
            lines.append(f"- {item}")

    surface = profile.get("overused_surface_patterns") or []
    if surface:
        lines.append("过度使用的表层模式：")
        for item in surface:
            pattern = item.get("pattern") or ""
            meaning = item.get("meaning") or ""
            cooldown = item.get("cooldown_turns") or 3
            suffix = f"；语义：{meaning}" if meaning else ""
            lines.append(f"- {pattern}{suffix}；冷却约{cooldown}轮")

    loops = profile.get("semantic_loops") or []
    if loops:
        lines.append("需打破的语义节拍：")
        for item in loops:
            pattern = item.get("pattern") or ""
            meaning = item.get("meaning") or ""
            alts = item.get("suggested_alternatives") or []
            alt_text = "；替代方向：" + "、".join(alts[:5]) if alts else ""
            meaning_text = f"；功能：{meaning}" if meaning else ""
            lines.append(f"- {pattern}{meaning_text}{alt_text}")

    lines.append("本轮应延续角色状态，但换用新的动作对象、台词策略、场景推进或生活化行为。")
    return "\n".join(lines)


def format_char_memory_for_prompt(char_memory: Any) -> str:
    """兼容入口：无分层字段时等价于仅对话历史。"""
    return format_tiered_memory_for_prompt(char_memory, {})


async def wait_for_pending_char_memory(username: str, character_id: str, game_type: str) -> None:
    """下一局请求到达时等待上一轮异步记忆任务完成（触发点前移）。"""
    key = _session_key(username, character_id, game_type)
    t = _pending_memory_tasks.get(key)
    if not t or t.done():
        return
    try:
        await asyncio.wait_for(t, timeout=120.0)
    except asyncio.TimeoutError:
        logger.warning(
            "🧠 [CharMemory] 等待上轮记忆任务超时 | user=%s char=%s",
            username,
            (character_id or "")[:8],
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.debug("🧠 [CharMemory] 等待记忆任务: %s", e)


def schedule_char_memory_update_after_turn(
    *,
    username: str,
    character_id: str,
    game_type: str,
) -> None:
    """在已成功保存本局状态后调用：链式排队，避免并发写库冲突。"""

    key = _session_key(username, character_id, game_type)
    old = _pending_memory_tasks.get(key)

    async def _chain() -> None:
        if old and not old.done():
            try:
                await old
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        try:
            await _run_char_memory_update_locked(username, character_id, game_type)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "🧠 [CharMemory] 更新失败 | user=%s char=%s err=%s",
                username,
                (character_id or "")[:8],
                e,
            )

    _pending_memory_tasks[key] = asyncio.create_task(_chain())


async def _call_summarize_llm(
    prompt: str,
    *,
    username: str = "",
    character_id: str = "",
    game_type: str = "galgame",
    stage: str = "SEQ_STEP_10_MEMORY",
) -> str | None:
    from .. import config as app_config
    from ..config import model_manager
    from ..utils import save_chat_debug_log

    from .seq_llm import call_llm_galgame_sequential

    active_model = model_manager.get_model_for_task("summarize")
    if not active_model:
        logger.warning("[CharMemory] 无 for_summarize 模型，跳过记忆更新")
        return None
    if not app_config.httpx_client:
        return None
    model_name = active_model.get("model_name") or active_model.get("id", "")
    _seq_mode = game_type if game_type in ("galgame", "galgame_lock") else "galgame"
    body: dict[str, Any] = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    timeout_sec = llm_task_float("galgame_seq_step_10_memory", "timeout_seconds", 120.0) or 120.0

    try:
        result = await asyncio.wait_for(
            call_llm_galgame_sequential(
                body,
                active_model,
                mode=_seq_mode,
                model_name=str(model_name),
                httpx_client=app_config.httpx_client,
                timeout=timeout_sec,
                chat_debug_request={
                    "username": username or None,
                    "character_id": character_id or None,
                    "mode": game_type,
                    "model_name": model_name,
                    "stage": f"{stage}_REQUEST",
                },
                record_usage="main",
                usage_meter_username=username or None,
            ),
            timeout=timeout_sec,
        )
    except Exception as e:
        logger.warning("[CharMemory] LLM 请求异常: %s", e)
        await save_chat_debug_log(
            username or None, character_id or None, game_type, model_name,
            str(e), stage=f"{stage}_ERROR",
        )
        return None
    if isinstance(result.raw_response.get("error"), dict):
        logger.warning("[CharMemory] LLM 错误对象")
        await save_chat_debug_log(
            username or None, character_id or None, game_type, model_name,
            str(result.raw_response.get("error")), stage=f"{stage}_ERROR",
        )
        return None
    raw_content = (result.text or "").strip() or None
    if not raw_content and (result.reasoning or "").strip():
        _cand = (result.reasoning or "").strip()
        if "{" in _cand and "}" in _cand:
            raw_content = _cand
            logger.info("[CharMemory] 正文为空，回退使用 reasoning 中的 JSON 片段")
    if not raw_content:
        logger.warning(
            "[CharMemory] 模型返回空正文且无可回退内容 reasoning_len=%s",
            len((result.reasoning or "").strip()),
        )

    # 记忆摘要不应含任何括号注释，全部移除（含全角/半角括号及其内容）
    if raw_content:
        raw_content = re.sub(r"[（(][^）)]*[）)]", "", raw_content).strip()
        raw_content = raw_content or None

    return raw_content


def _parse_memory_json(raw: str) -> dict | None:
    if not raw:
        return None
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        obj = json.loads(try_fix_json(m.group(0)), strict=False)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _split_step10_memory_payload(raw_obj: dict) -> tuple[dict | None, dict]:
    """同时兼容旧版扁平 Step 10 JSON 与新版结构化输出。"""
    if not isinstance(raw_obj, dict):
        return None, {}
    entry = raw_obj.get("memory_entry")
    if isinstance(entry, dict):
        profile = normalize_repetition_profile(raw_obj.get("repetition_profile"))
        return entry, profile
    legacy_entry = {
        "turn": raw_obj.get("turn"),
        "player_action": raw_obj.get("player_action"),
        "event": raw_obj.get("event"),
    }
    if any(legacy_entry.values()):
        profile = normalize_repetition_profile(raw_obj.get("repetition_profile"))
        return legacy_entry, profile
    return None, normalize_repetition_profile(raw_obj.get("repetition_profile"))


def _fallback_memory_entry_from_turn(
    *,
    raw: str,
    user_text: str,
    turn_idx: int,
    time_val: str = "",
    loc_val: str = "",
    relationship: str = "",
    mood: str = "",
) -> dict | None:
    """第 10 步 LLM 输出为空或无效时，构建最小本地记忆条目。

    刻意保守：仅使用本轮已生成 payload 中的既有事实，不推断去重档案。
    """
    data: Any = {}
    if raw:
        try:
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                data = json.loads(try_fix_json(m.group(0)), strict=False)
        except Exception:
            data = {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        data = {}

    scene = data.get("scene") if isinstance(data.get("scene"), dict) else {}
    if not isinstance(scene, dict):
        scene = {}

    player_action = str(data.get("player_action") or user_text or "").strip()
    parts: list[str] = []
    for key in ("env", "body_state", "third_party_dialogue", "response"):
        val = str(scene.get(key) or "").strip()
        if val and val.strip("（）() ") not in ("无", "none", "null"):
            parts.append(val)
    if not parts:
        content = raw.strip()
        if content:
            parts.append(content[:500])
    if not player_action and not parts:
        return None

    return {
        "turn": int(turn_idx or 0),
        "player_action": player_action[:800],
        "event": "。".join(p.strip("。") for p in parts if p).strip()[:800],
        "time": str(time_val or scene.get("time") or "")[:30],
        "location": str(loc_val or scene.get("location") or "")[:30],
        "relationship": str(relationship or data.get("relationship_stage") or "")[:100],
        "emotional_note": str(mood or data.get("mood") or "")[:60],
        "_fallback": True,
    }


def _mode_time_rules(is_lock_mode: bool) -> str:
    mode_name = "锁分模式" if is_lock_mode else "游戏模式"
    return (
        f"当前为{mode_name}剧情记忆整理。\n"
        "【时间规则】严禁写入现实世界时间；仅使用剧情内场景时间或「以剧情推进为准」。\n"
    )


async def _llm_merge_long_term(
    prev_long: str,
    prev_short: str,
    *,
    is_lock_mode: bool,
    username: str,
    character_id: str,
    game_type: str,
) -> str | None:
    prompt = (
        f"{_mode_time_rules(is_lock_mode)}"
        "你是剧情存档整理专家。将下列「已有长期记忆」与「已有短期记忆」合并为一份新的【长期记忆】摘要。\n"
        "要求：客观中性；保留关键人物关系、核心剧情转折、不可逆事件与当前关系阶段；"
        "禁止复述口语化台词与拟声；若同类微动作、表情、比喻或环境意象反复出现，须折叠为抽象状态或叙事功能，不要逐轮保留同一身体部位+动作模板；"
        "禁止输出任何括号（含全角括号）及括号内说明；总字数不超过800字。\n\n"
        f"【已有长期记忆】\n{prev_long.strip() or '（无）'}\n\n"
        f"【已有短期记忆】\n{prev_short.strip() or '（无）'}\n\n"
        "请直接输出摘要正文，不要小标题或前缀。"
    )
    return await _call_summarize_llm(
        prompt,
        username=username,
        character_id=character_id,
        game_type=game_type,
        stage="SEQ_STEP_10_TIERED_LONG",
    )


async def _llm_extend_short_term(
    prev_short: str,
    entries_block: str,
    *,
    is_lock_mode: bool,
    username: str,
    character_id: str,
    game_type: str,
) -> str | None:
    prompt = (
        f"{_mode_time_rules(is_lock_mode)}"
        "你是剧情存档整理专家。将「已有短期记忆」与下列【新增逐轮转写】合并为一份新的【短期记忆】摘要。\n"
        "要求：客观中性；保留与近期剧情推进直接相关的事实；禁止复述口语化台词；"
        "若同类微动作、表情、比喻或环境意象反复出现，须折叠为抽象状态或叙事功能，不要逐轮保留同一身体部位+动作模板；"
        "禁止输出任何括号（含全角括号）及括号内说明；总字数不超过500字。\n\n"
        f"【已有短期记忆】\n{prev_short.strip() or '（无）'}\n\n"
        f"【新增逐轮转写】\n{entries_block}\n\n"
        "请直接输出摘要正文，不要小标题或前缀。"
    )
    return await _call_summarize_llm(
        prompt,
        username=username,
        character_id=character_id,
        game_type=game_type,
        stage="SEQ_STEP_10_TIERED_SHORT_EXTEND",
    )


async def _llm_new_short_term_from_entries(
    entries_block: str,
    *,
    is_lock_mode: bool,
    username: str,
    character_id: str,
    game_type: str,
) -> str | None:
    prompt = (
        f"{_mode_time_rules(is_lock_mode)}"
        "你是剧情存档整理专家。将下列【逐轮转写】整理为一份【短期记忆】摘要。\n"
        "要求：客观中性；保留关键事实与关系变化；禁止复述口语化台词；"
        "若同类微动作、表情、比喻或环境意象反复出现，须折叠为抽象状态或叙事功能，不要逐轮保留同一身体部位+动作模板；"
        "禁止输出任何括号（含全角括号）及括号内说明；总字数不超过500字。\n\n"
        f"{entries_block}\n\n"
        "请直接输出摘要正文，不要小标题或前缀。"
    )
    return await _call_summarize_llm(
        prompt,
        username=username,
        character_id=character_id,
        game_type=game_type,
        stage="SEQ_STEP_10_TIERED_SHORT_NEW",
    )


async def try_fold_char_memory_entries(
    state: dict,
    *,
    is_lock_mode: bool,
    username: str = "",
    character_id: str = "",
    game_type: str = "galgame",
    force: bool = False,
) -> bool:
    """
    当 char_memory.entries 长度 > KEEP_VERBATIM_MAX（或 API force=True 且长度 > KEEP_VERBATIM_AFTER_TRIM）时：
    生成分层摘要并裁剪为最近 KEEP_VERBATIM_AFTER_TRIM 条。
    失败时返回 False，不修改 entries。
    """
    prev_cm = state.get("char_memory") if isinstance(state.get("char_memory"), dict) else {"entries": []}
    entries = [e for e in (prev_cm.get("entries") or []) if isinstance(e, dict)]
    if len(entries) <= KEEP_VERBATIM_AFTER_TRIM:
        return False
    if len(entries) <= KEEP_VERBATIM_MAX and not force:
        return False

    to_summarize = entries[:-KEEP_VERBATIM_AFTER_TRIM]
    keep_entries = entries[-KEEP_VERBATIM_AFTER_TRIM:]
    if not to_summarize:
        return False

    prev_short = str(state.get("shortTermMemory") or "").strip()
    prev_short_start = state.get("shortTermMemoryStartTurn")
    prev_short_cutoff = state.get("shortTermMemoryCutoffTurn")
    prev_long = str(state.get("longTermMemory") or "").strip()
    prev_long_cutoff = state.get("longTermMemoryCutoffTurn")

    try:
        pss = int(prev_short_start) if prev_short_start is not None else None
    except (TypeError, ValueError):
        pss = None
    try:
        psc = int(prev_short_cutoff) if prev_short_cutoff is not None else None
    except (TypeError, ValueError):
        psc = None
    try:
        plc = int(prev_long_cutoff) if prev_long_cutoff is not None else None
    except (TypeError, ValueError):
        plc = None

    short_covered = 0
    if prev_short and pss is not None and psc is not None:
        short_covered = max(0, psc - pss + 1)
    elif prev_short:
        short_covered = SHORT_TERM_MAX_TURNS

    overflow = short_covered + len(to_summarize) > SHORT_TERM_MAX_TURNS
    entries_block = _format_entries_block(to_summarize)
    t_first = _entry_turn(to_summarize[0], 0)
    t_last = _entry_turn(to_summarize[-1], 0)

    if overflow:
        merged_long = await _llm_merge_long_term(
            prev_long,
            prev_short,
            is_lock_mode=is_lock_mode,
            username=username,
            character_id=character_id,
            game_type=game_type,
        )
        if not merged_long:
            logger.warning(
                "🧠 [TieredMemory] 长期合并失败，跳过裁剪 | user=%s char=%s",
                username,
                (character_id or "")[:8],
            )
            return False
        new_short = await _llm_new_short_term_from_entries(
            entries_block,
            is_lock_mode=is_lock_mode,
            username=username,
            character_id=character_id,
            game_type=game_type,
        )
        if not new_short:
            logger.warning(
                "🧠 [TieredMemory] 新短期生成失败，跳过裁剪 | user=%s char=%s",
                username,
                (character_id or "")[:8],
            )
            return False
        new_long_cutoff = (
            psc if psc is not None else (plc if plc is not None else max(0, t_first - 1))
        )
        state["longTermMemory"] = merged_long.strip()
        state["longTermMemoryCutoffTurn"] = new_long_cutoff
        state["shortTermMemory"] = new_short.strip()
        state["shortTermMemoryStartTurn"] = t_first
        state["shortTermMemoryCutoffTurn"] = t_last
    else:
        if prev_short:
            new_short = await _llm_extend_short_term(
                prev_short,
                entries_block,
                is_lock_mode=is_lock_mode,
                username=username,
                character_id=character_id,
                game_type=game_type,
            )
        else:
            new_short = await _llm_new_short_term_from_entries(
                entries_block,
                is_lock_mode=is_lock_mode,
                username=username,
                character_id=character_id,
                game_type=game_type,
            )
        if not new_short:
            logger.warning(
                "🧠 [TieredMemory] 短期摘要失败，跳过裁剪 | user=%s char=%s",
                username,
                (character_id or "")[:8],
            )
            return False
        new_s_start = pss if pss is not None else t_first
        state["shortTermMemory"] = new_short.strip()
        state["shortTermMemoryStartTurn"] = new_s_start
        state["shortTermMemoryCutoffTurn"] = t_last

    state["char_memory"] = {
        "entries": keep_entries,
        "updated_at": int(time.time() * 1000),
    }
    logger.info(
        "🧠 [TieredMemory] 已折叠 entries→%s | overflow=%s user=%s char=%s",
        len(keep_entries),
        overflow,
        username,
        (character_id or "")[:8],
    )
    return True


async def run_forced_tiered_fold_from_state(
    state: dict,
    *,
    is_lock_mode: bool,
    username: str,
    character_id: str,
    game_type: str,
) -> bool:
    """API 强制触发分层折叠（9～15 条亦可触发）。"""
    return await try_fold_char_memory_entries(
        state,
        is_lock_mode=is_lock_mode,
        username=username,
        character_id=character_id,
        game_type=game_type,
        force=True,
    )


async def _run_char_memory_update_locked(username: str, character_id: str, game_type: str) -> None:
    async with _get_lock(_session_key(username, character_id, game_type)):
        from ..utils import load_galgame_state_async, save_galgame_state_async
        from ..chat_modules.character import load_character_from_db

        _char_obj = load_character_from_db(username, character_id)
        char_name = (_char_obj.get("name") or "").strip() if _char_obj else ""

        state = await load_galgame_state_async(username, character_id, game_type=game_type)
        msgs = [m for m in (state.get("messages") or []) if not m.get("isHidden") and not m.get("is_hidden")]
        if len(msgs) < 1:
            return
        last_ai = None
        last_user = None
        for m in reversed(msgs):
            if last_ai is None and m.get("role") == "assistant":
                last_ai = m
            elif last_user is None and m.get("role") == "user":
                last_user = m
            if last_ai and last_user:
                break
        if not last_ai:
            return
        is_opening = last_user is None  # 开场白：无玩家输入，仅 assistant 开局消息
        user_text = "" if is_opening else str(last_user.get("content") or "").strip()
        user_text = user_text.split("【当前任务")[0].strip()
        raw = str(last_ai.get("rawContent") or last_ai.get("content") or "").strip()
        turn_idx = 0 if is_opening else sum(1 for x in msgs if x.get("role") == "user")

        prev_cm = state.get("char_memory") if isinstance(state.get("char_memory"), dict) else {"entries": []}
        prev_entries = prev_cm.get("entries") if isinstance(prev_cm.get("entries"), list) else []

        director_note = ""
        rel = str(state.get("relationship_stage") or "")
        mood = str(state.get("mood") or "")
        time_val = ""
        loc_val = ""

        payload_hint = ""
        if raw.startswith("{"):
            try:
                gd = json.loads(try_fix_json(raw), strict=False)
                if isinstance(gd, dict) and isinstance(gd.get("data"), dict):
                    gd = gd["data"]
                if isinstance(gd, dict):
                    sc = gd.get("scene") or {}
                    if not isinstance(sc, dict):
                        sc = {}
                    rel = str(gd.get("relationship_stage") or state.get("relationship_stage") or "")
                    mood = str(gd.get("mood") or state.get("mood") or "")
                    time_val = str(sc.get("time") or "").strip()
                    loc_val = str(sc.get("location") or "").strip()
                    env_t = str(sc.get("env") or "")[:240]
                    body_t = str(sc.get("body_state") or "")[:240]
                    th_t = str(sc.get("thoughts") or "")[:240]
                    third_t = str(sc.get("third_party_dialogue") or "")[:200]
                    rsp_t = str(sc.get("response") or "")[:300]
                    payload_hint = (
                        f"env提要:{env_t}\n"
                        f"body_state提要:{body_t}\n"
                        f"thoughts提要:{th_t}\n"
                        f"third_party_dialogue提要:{third_t}\n"
                        f"response提要:{rsp_t}"
                    )
                    inner = gd.get("character_inner_arc")
                    if inner:
                        director_note = str(inner)[:400]
                    dmeta = gd.get("_director_meta")
                    if isinstance(dmeta, dict) and len(director_note) < 50:
                        director_note = str(dmeta)[:300]
            except Exception:
                payload_hint = raw[:500]

        char_name_line = f"角色名（贯穿整段记忆，禁止替换为其他名字）：{char_name}\n" if char_name else ""
        player_line = "玩家本轮：（游戏开场，角色主动发起场景）\n" if is_opening else f"玩家本轮：{user_text[:500]}\n"
        recent_entries = [e for e in prev_entries[-8:] if isinstance(e, dict)]
        recent_block = _format_entries_block(recent_entries) if recent_entries else ""
        prev_repetition_profile = format_repetition_profile_for_prompt(state)
        prompt = (
            f"{_SEQ_CHAR_MEMORY_UPDATE}\n\n"
            f"{char_name_line}"
            f"回合序号 turn={turn_idx}\n"
            f"{player_line}"
            f"上一轮去重档案：\n{prev_repetition_profile or '无'}\n"
            f"近期中性记忆：\n{recent_block or '无'}\n"
            f"场景/文本提要：{payload_hint or raw[:600]}\n"
        )
        raw_out = await _call_summarize_llm(
            prompt,
            username=username,
            character_id=character_id,
            game_type=game_type,
        )
        raw_obj = _parse_memory_json(raw_out or "")
        new_obj, repetition_profile = _split_step10_memory_payload(raw_obj or {})
        if not new_obj:
            new_obj = _fallback_memory_entry_from_turn(
                raw=raw,
                user_text=user_text,
                turn_idx=turn_idx,
                time_val=time_val,
                loc_val=loc_val,
                relationship=rel,
                mood=mood,
            )
            if not new_obj:
                logger.warning("[CharMemory] 模型未返回有效 JSON，且本地兜底记忆无法生成，跳过写入")
                return
            logger.warning("[CharMemory] 模型未返回有效 JSON，已使用本地兜底记忆写入")
        # turn / player_action / event 来自 LLM 转写
        new_obj["turn"] = int(new_obj.get("turn") or turn_idx)
        for k in ("player_action", "event"):
            new_obj[k] = str(new_obj.get(k) or "")[:800]
        # time / location / relationship / emotional_note 由后端从游戏状态直接注入，不依赖 LLM
        new_obj["time"] = str(time_val or "")[:30]
        new_obj["location"] = str(loc_val or "")[:30]
        new_obj["relationship"] = str(rel or "")[:100]
        new_obj["emotional_note"] = str(mood or "")[:60]
        new_obj.pop("open_threads", None)

        entries = [e for e in prev_entries if isinstance(e, dict)]
        entries.append(new_obj)
        if repetition_profile:
            state["repetition_profile"] = repetition_profile

        is_lock_mode = game_type == "galgame_lock"
        if len(entries) > KEEP_VERBATIM_MAX:
            # 先写入完整 entries 再尝试折叠（fold 会改写 state 内 char_memory）
            state["char_memory"] = {"entries": entries, "updated_at": int(time.time() * 1000)}
            folded = await try_fold_char_memory_entries(
                state,
                is_lock_mode=is_lock_mode,
                username=username,
                character_id=character_id,
                game_type=game_type,
                force=False,
            )
            if not folded:
                state["char_memory"] = {"entries": entries, "updated_at": int(time.time() * 1000)}
        else:
            state["char_memory"] = {"entries": entries, "updated_at": int(time.time() * 1000)}

        ok = await save_galgame_state_async(username, character_id, state, game_type=game_type)
        if ok:
            logger.info(
                "🧠 [CharMemory] 已写入 %s 条 | user=%s char=%s",
                len(state.get("char_memory", {}).get("entries") or []),
                username,
                (character_id or "")[:8],
            )
