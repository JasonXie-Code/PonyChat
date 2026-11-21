"""
后台自动上下文总结调度器

每隔 10 分钟扫描近期活跃的普通对话，对 token 使用率超过 92% 的对话静默触发摘要生成。
即使用户未在线，总结也会在后台完成，用户下次进入对话时可直接使用已生成的摘要。
"""

import asyncio
import time
from typing import Optional, Set, Tuple, Dict, Any, List

from ..config import logger, model_manager
from .. import config as app_config
from ..context_usage import CONTEXT_SUMMARY_KEEP_RECENT_MESSAGES, CONTEXT_LIMIT_TOKENS
from ..db.database import get_database
from ..utils import save_chat_debug_log

# ── 调度参数 ──────────────────────────────────────────────────────────────────
SCHEDULER_INTERVAL_SEC  = 600    # 每 10 分钟扫描一次
SUMMARIZE_THRESHOLD     = 0.92   # token 使用率超过此值时触发摘要
MAX_CONVS_PER_CYCLE     = 15     # 每轮最多处理的用户-角色对数量
INITIAL_DELAY_SEC       = 90     # 首次执行延迟（等待 DB / 模型管理器就绪）
KEEP_RECENT_MESSAGES    = CONTEXT_SUMMARY_KEEP_RECENT_MESSAGES  # 保留最近 N 条消息不纳入摘要，与端点保持一致
LLM_TIMEOUT_SEC         = 180    # LLM 调用超时（与 summarize_context 端点一致）
MIN_MESSAGES            = KEEP_RECENT_MESSAGES + 2  # 至少需要的消息数

# 正在处理中的对话 key（防止同一对话并发重复处理）
_in_progress: Set[str] = set()


def _split_recent_messages(messages: List[dict], keep_recent_messages: int = KEEP_RECENT_MESSAGES) -> Tuple[List[dict], List[dict]]:
    if not messages:
        return [], []
    if keep_recent_messages <= 0:
        return list(messages), []

    recent = list(messages[-keep_recent_messages:]) if len(messages) > keep_recent_messages else list(messages)
    older = list(messages[: max(0, len(messages) - len(recent))])
    return older, recent


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _find_best_conv(conversations: List[dict]) -> Tuple[Optional[dict], float]:
    """
    从对话列表中找出 token 使用率最高且超过阈值的对话。
    返回 (目标对话 dict, token 使用率)；不满足条件时返回 (None, 0.0)。
    """
    from ..context_usage import estimate_context_usage, CONTEXT_LIMIT_TOKENS

    best_conv, best_ratio = None, 0.0
    for conv in conversations:
        msgs = conv.get("messages") or []
        visible = [m for m in msgs
                   if not (m.get("isHidden") or m.get("is_hidden"))]
        if len(visible) < MIN_MESSAGES:
            continue
        usage = estimate_context_usage(
            messages=msgs,
            context_summary=conv.get("contextSummary") or "",
            cutoff_message_id=conv.get("contextSummaryCutoffMessageId"),
            cutoff_timestamp=conv.get("contextSummaryCutoffTimestamp"),
            cutoff_sequence=conv.get("contextSummaryCutoffSequence")
                or conv.get("contextSummaryCutoffSequenceNumber"),
        )
        limit = usage.get("limit_tokens", CONTEXT_LIMIT_TOKENS)
        total = usage.get("total_tokens", 0)
        ratio = total / limit if limit > 0 else 0.0
        if ratio > best_ratio:
            best_ratio = ratio
            best_conv = conv
    return (best_conv, best_ratio) if best_ratio >= SUMMARIZE_THRESHOLD else (None, 0.0)


async def _call_llm(
    prompt: str,
    *,
    chat_debug_request: Optional[dict] = None,
    metering_username: Optional[str] = None,
) -> Optional[str]:
    """
    调用活跃模型生成摘要，返回原始文本；失败或超时返回 None。
    """
    from ..providers.llm_call import call_llm_payload
    from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
    from ..reasoning_policy import resolve_software_reasoning_policy

    # 总结任务固定使用 for_summarize 专用模型，不随主模型变化
    active_model = model_manager.get_model_for_task("summarize")
    if not active_model:
        logger.warning("[AutoSummarizer] 无活跃模型，跳过")
        return None
    if not app_config.httpx_client:
        logger.warning("[AutoSummarizer] httpx_client 未就绪，跳过")
        return None

    model_name = active_model.get("model_name") or active_model.get("id", "")
    reasoning_policy = resolve_software_reasoning_policy(
        "memory_auto_summarize",
        model_name=model_name,
        mode="memory_auto_summarize",
        active_model=active_model,
        endpoint=active_model.get("endpoint", ""),
    )
    body: Dict[str, Any] = {
        "model":    model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream":   False,
    }
    apply_llm_task_payload_config(body, "memory_auto_summarize", output_token_field="max_tokens")
    timeout_sec = llm_task_float("memory_auto_summarize", "timeout_seconds", float(LLM_TIMEOUT_SEC)) or float(LLM_TIMEOUT_SEC)

    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(
            call_llm_payload(
                body,
                active_model,
                task="summarize",
                httpx_client=app_config.httpx_client,
                timeout=timeout_sec,
                chat_debug_request=chat_debug_request,
                record_usage="main",
                usage_meter_username=metering_username,
                reasoning_policy=reasoning_policy,
            ),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t0
        logger.error(
            f"[AutoSummarizer] LLM 超时（>{elapsed:.0f}s）"
            f" | model={model_name}"
        )
        return None
    except Exception as e:
        logger.warning(f"[AutoSummarizer] LLM 请求异常: {e}")
        return None

    resp_data = result.raw_response
    if isinstance(resp_data.get("error"), dict):
        err_msg = resp_data["error"].get("message", "")[:200]
        logger.warning(f"[AutoSummarizer] LLM 错误对象: {err_msg}")
        return None

    return (result.text or "").strip() or None


# ── 核心处理逻辑 ───────────────────────────────────────────────────────────────

async def _process_pair(db, username: str, char_id: str) -> bool:
    """
    处理单个用户-角色对：
    1. 快速读 DB，找出 token 最高的对话
    2. 释放 DB 连接，调用 LLM（慢）
    3. 重新获取 DB 连接，写回摘要

    返回 True 表示完成了一次摘要。
    """
    from ..db import ConversationsDAO
    from ..routes.characters import (
        _build_summary_prompt, _clean_summary_text, _pick_scene_time_hint,
    )
    from ..chat_modules.character import build_character_profile_prompt_block, load_character_from_db
    from ..user_identity import normalize_user_memory_text
    from ..refusal_detector import is_refusal, is_invalid_context_summary

    # ── 步骤 1：加载对话数据（load_conversations 内部自管理连接，直接传 db 包装器） ──
    conv_dao = ConversationsDAO(db)
    conversations = await conv_dao.load_conversations(username, char_id)

    if not conversations:
        return False

    target_conv, ratio = _find_best_conv(conversations)
    if target_conv is None:
        return False

    conv_id  = str(target_conv.get("id") or "")
    conv_key = f"{username}/{char_id}/{conv_id}"
    if conv_key in _in_progress:
        return False
    _in_progress.add(conv_key)

    try:
        # ── 步骤 2：准备摘要 prompt（CPU 密集，无需 DB） ──
        all_msgs    = target_conv.get("messages") or []
        prev_summary = str(target_conv.get("contextSummary") or "").strip()
        visible = [m for m in all_msgs
                   if not (m.get("isHidden") or m.get("is_hidden"))]
        to_summarize, _recent_tail = _split_recent_messages(visible, KEEP_RECENT_MESSAGES)
        if not to_summarize:
            return False

        cutoff_msg = to_summarize[-1]
        cutoff_message_id = (cutoff_msg.get("message_id")
                             if isinstance(cutoff_msg, dict) else None)
        cutoff_timestamp  = (cutoff_msg.get("timestamp")
                             if isinstance(cutoff_msg, dict) else None)
        raw_seq           = (cutoff_msg.get("sequence_number")
                             if isinstance(cutoff_msg, dict) else None)
        try:
            cutoff_sequence = int(raw_seq) if raw_seq is not None else None
        except (TypeError, ValueError):
            cutoff_sequence = None

        scene_time_hint = _pick_scene_time_hint(visible, {})
        summary_character_profile = ""
        summary_assistant_label = "角色"
        try:
            _summary_char = load_character_from_db(username, char_id) or {}
            summary_assistant_label = str(_summary_char.get("name") or "").strip() or summary_assistant_label
            summary_character_profile = build_character_profile_prompt_block(_summary_char)
        except Exception as _profile_err:
            logger.debug("[AutoSummarizer] 加载角色档案供摘要参考失败: %s", _profile_err)
        prompt = _build_summary_prompt(
            to_summarize,
            prev_summary=prev_summary,
            scene_time_hint=scene_time_hint,
            character_profile_context=summary_character_profile,
            assistant_label=summary_assistant_label,
        )

        active_model = model_manager.get_model_for_task("summarize") or {}
        _model_name = active_model.get("model_name") or active_model.get("id", "")

        logger.info(
            f"🔄 [AutoSummarizer] 触发 | user={username} char={char_id[:8]}... "
            f"conv={conv_id[:12]} | {ratio:.0%} 使用率 | "
            f"to_summarize={len(to_summarize)} 条"
        )

        # ── 步骤 3：调用 LLM（慢，不持有 DB 连接） ──
        t0 = time.monotonic()
        raw_summary = await _call_llm(
            prompt,
            chat_debug_request={
                "username": username,
                "character_id": char_id,
                "mode": "auto_summarize",
                "model_name": _model_name,
                "stage": "REQUEST",
            },
            metering_username=username,
        )
        if not raw_summary:
            return False

        # 拒绝检测：摘要完成后与分步生成相同（先关键词再小模型）
        if await is_refusal(raw_summary):
            logger.warning(
                f"[AutoSummarizer] LLM 拒绝生成摘要，跳过 | user={username} char={char_id[:8]}..."
            )
            return False

        summary_text = normalize_user_memory_text(
            _clean_summary_text(raw_summary),
            username=username,
        )
        if not summary_text:
            logger.warning(
                f"[AutoSummarizer] LLM 返回空摘要，跳过 | user={username}"
            )
            return False

        if is_invalid_context_summary(summary_text):
            logger.warning(
                f"[AutoSummarizer] 摘要为合规拒答/占位模板，跳过 | user={username} char={char_id[:8]}..."
            )
            return False

        # ── 步骤 4：写回摘要（精准 SQL UPDATE，不触碰消息列表） ──
        # 注意：不能用 save_conversation，它会把 LLM 等待期间新到的消息软删除。
        # 只更新摘要相关字段，保证消息数据安全。
        summary_time = int(time.time() * 1000)
        conn = await db.acquire()
        try:
            async with conn.execute(
                "SELECT id FROM users WHERE username = ? LIMIT 1", (username,)
            ) as cur:
                uid_row = await cur.fetchone()
            if not uid_row:
                logger.warning(f"[AutoSummarizer] 用户不存在: {username}")
                return False
            user_id = uid_row[0]

            await conn.execute(
                """UPDATE conversations
                   SET summary = ?,
                       context_summary_cutoff_message_id = ?,
                       context_summary_cutoff_timestamp  = ?,
                       context_summary_cutoff_sequence   = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?
                     AND user_id = ?
                     AND COALESCE(is_hidden, 0) = 0""",
                (
                    summary_text,
                    cutoff_message_id,
                    cutoff_timestamp,
                    cutoff_sequence,
                    conv_id,
                    user_id,
                ),
            )
            await conn.commit()
        finally:
            await db.release(conn)

        elapsed = time.monotonic() - t0
        logger.info(
            f"✅ [AutoSummarizer] 完成 | user={username} char={char_id[:8]}... "
            f"| 用时={elapsed:.0f}s | 摘要={len(summary_text)} chars"
        )
        return True

    finally:
        _in_progress.discard(conv_key)


async def _run_one_cycle(db) -> None:
    """
    执行一次完整扫描：
    1. 查询近期活跃的用户-角色对
    2. 逐对检查 token 用量并按需总结
    """
    # ── 查询候选用户-角色对（只取一次 conn，快速查询后立刻释放） ──
    conn = await db.acquire()
    try:
        cursor = await conn.execute(
            """SELECT DISTINCT u.username, c.character_id
               FROM conversations c
               JOIN users u ON u.id = c.user_id
               WHERE c.is_hidden = 0
               ORDER BY c.updated_at DESC
               LIMIT ?""",
            (MAX_CONVS_PER_CYCLE * 3,),   # 多取一些，经过 token 过滤后仍有足够
        )
        pairs = await cursor.fetchall()
    except Exception as e:
        logger.warning(f"⚠️ [AutoSummarizer] 查询候选对话失败: {e}")
        return
    finally:
        await db.release(conn)

    if not pairs:
        return

    summarized = 0
    seen: Set[str] = set()
    for username, char_id in pairs:
        if summarized >= MAX_CONVS_PER_CYCLE:
            break
        pair_key = f"{username}/{char_id}"
        if pair_key in seen:
            continue
        seen.add(pair_key)

        try:
            did = await _process_pair(db, username, char_id)
            if did:
                summarized += 1
                # 摘要间隔 2s，避免 LLM API 速率限制
                await asyncio.sleep(2)
        except Exception as e:
            logger.debug(
                f"[AutoSummarizer] 处理 {username}/{char_id[:8]}... 异常: {e}"
            )

    if summarized:
        logger.info(f"📝 [AutoSummarizer] 本轮完成 {summarized} 条对话总结")


async def auto_summarizer_loop() -> None:
    """主调度循环，每隔 SCHEDULER_INTERVAL_SEC 秒执行一次扫描。"""
    logger.info(
        f"📝 [AutoSummarizer] 后台摘要调度器已启动"
        f"（间隔 {SCHEDULER_INTERVAL_SEC}s，阈值 {SUMMARIZE_THRESHOLD:.0%}）"
    )
    # 首次延迟，等待 DB 初始化和模型管理器完成加载
    await asyncio.sleep(INITIAL_DELAY_SEC)

    while True:
        try:
            db = get_database()
            await _run_one_cycle(db)
        except Exception as e:
            logger.warning(f"⚠️ [AutoSummarizer] 循环异常: {e}")
        await asyncio.sleep(SCHEDULER_INTERVAL_SEC)
