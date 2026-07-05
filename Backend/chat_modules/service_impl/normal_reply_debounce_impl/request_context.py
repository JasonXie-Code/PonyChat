from __future__ import annotations


import asyncio
import copy
import json
import random
import re
import time
from typing import Any, Optional

import aiosqlite
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from .. import config, prompt_cache_sim
from ..config import logger
from ..db import get_database, get_users_dao
from ..db.memory_dao import format_layered_memories_for_prompt, recall_memories_layered
from ..db.settings_dao import SettingsDAO
from ..providers import DoubaoProvider, QwenProvider, XaiProvider, get_provider
from ..providers.llm_call import (
    DEFAULT_LLM_OUTPUT_MAX_TOKENS,
    force_default_output_token_limit,
)
from ..reasoning_config import (
    get_llm_task_config,
    llm_task_int,
)
from ..reasoning_policy import (
    apply_model_param_policy,
    is_deepseek_v4_model,
    resolve_software_reasoning_policy,
)
from ..context_usage import CONTEXT_LIMIT_TOKENS as _CTX_LIMIT_TOKENS
from ..utils import ChatMessage, ChatRequest, estimate_tokens as _estimate_tokens, format_client_context, save_chat_debug_log
from ..user_identity import USER_MEMORY_PLACEHOLDER, replace_user_placeholder
from ..websocket import generation_locker, manager
from .character import build_character_profile_prompt_block, load_character_from_db
from .nonstream import handle_nonstream_request
from ..galgame.messages import build_galgame_messages
from .request_context import (
    assemble_messages,
    build_chat_router_recent_user_assistant,
    build_user_context,
    collect_message_images,
    get_last_user_image_urls,
    normalize_image_url_for_model,
    resolve_auth_and_quota,
)
from .normal_reasoning_switches import (
    NORMAL_MAIN_REPLY_THINKING_HIGH,
    apply_normal_thinking_switch,
)
from .normal_speaker import (
    ensure_guest_private_context,
    effective_speaker_character_id,
    format_normal_at_event_context,
    guest_private_recent_raw_turns,
    guest_scene_context_prompt,
    is_guest_speaker,
    load_recent_guest_group_memory_block,
    mark_normal_forced_reply_characters,
    normal_at_event_context,
    normal_forced_reply_character_ids,
    normal_role_debug_params,
    prepare_normal_reply_speaker,
    resolve_explicit_at_reply_character_ids,
    requested_reply_character_ids,
    run_normal_user_speaker_intent_router,
    speaker_context_conversation_id,
    speaker_display_name,
    load_owned_visible_character,
)
from .runtime import get_smart_parameters
from .smart_router import run_web_search
from .state import is_generation_current


def _normal_reply_debounce_ms() -> int:
    return 0


class NormalGenerationSuperseded(Exception):
    def __init__(self, stage: str):
        super().__init__(stage)
        self.stage = stage


def _normal_debounce_cancelled_response(use_json_protocol: bool, *, stage: str | None = None):
    event = {
        "type": "cancelled",
        "reason": "superseded_by_new_user_message",
    }
    if stage:
        event["stage"] = stage
    if use_json_protocol:
        return JSONResponse(
            {
                "protocol": "ponychat_chat_v1",
                "mode": "normal",
                "events": [event, {"type": "done"}],
            }
        )

    async def _lines():
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _lines(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


def _normal_no_reply_response(
    use_json_protocol: bool,
    *,
    reason: str,
    save_ok: bool = True,
    save_msg: str = "",
    quota_message: str | None = None,
):
    events = []
    if reason == "quota_exceeded":
        events.append({
            "type": "quota_exceeded",
            "message": quota_message or "今日积分已用完",
        })
    events.extend([
        {"type": "no_reply", "reason": reason},
        {"type": "save_status", "success": bool(save_ok), "message": save_msg or ""},
        {"type": "done"},
    ])
    if use_json_protocol:
        return JSONResponse(
            {
                "protocol": "ponychat_chat_v1",
                "mode": "normal",
                "events": events,
            }
        )

    async def _lines():
        for event in events[:-1]:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _lines(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


def _collapse_unreplied_user_tail_for_model_context(request: ChatRequest) -> None:
    """Model sees consecutive unreplied user messages as one message; DB keeps originals."""
    if (request.mode or "normal") != "normal" or request.is_summary_request:
        return
    try:
        from .state import get_model_context_messages, is_summary_placeholder_message

        def _copy_message(msg: ChatMessage) -> ChatMessage:
            if hasattr(msg, "model_copy"):
                return msg.model_copy(deep=True)
            return msg.copy(deep=True)

        source = [_copy_message(m) for m in get_model_context_messages(request)]
        if not source:
            return
        last_assistant_idx = -1
        for idx, msg in enumerate(source):
            if getattr(msg, "role", None) == "assistant" and not getattr(msg, "isHidden", False):
                last_assistant_idx = idx
        tail_user_indices: list[int] = []
        for idx in range(last_assistant_idx + 1, len(source)):
            msg = source[idx]
            if (
                getattr(msg, "role", None) == "user"
                and not getattr(msg, "isHidden", False)
                and not is_summary_placeholder_message(msg)
            ):
                tail_user_indices.append(idx)
        if len(tail_user_indices) <= 1:
            return

        tail_users = [source[idx] for idx in tail_user_indices]
        parts: list[str] = []
        attachments: list[Any] = []
        images: list[str] = []
        for msg in tail_users:
            text = str(getattr(msg, "content", "") or "").strip()
            if text:
                parts.append(text)
            for attachment in (getattr(msg, "attachments", None) or []):
                attachments.append(attachment)
            if getattr(msg, "image_url", None):
                images.append(str(getattr(msg, "image_url")))
            for image in (getattr(msg, "images", None) or []):
                if image:
                    images.append(str(image))
        if not parts and attachments:
            parts.append("[表情]")
        merged_content = "\n\n".join(parts).strip()
        if not merged_content and not attachments and not images:
            return

        merged_msg = _copy_message(tail_users[-1])
        merged_msg.content = merged_content
        merged_msg.attachments = attachments or None
        merged_msg.images = images or None
        merged_msg.image_url = images[0] if images else None

        tail_set = set(tail_user_indices)
        first_tail = tail_user_indices[0]
        collapsed: list[ChatMessage] = []
        for idx, msg in enumerate(source):
            if idx == first_tail:
                collapsed.append(merged_msg)
            elif idx in tail_set:
                continue
            else:
                collapsed.append(msg)
        setattr(request, "_model_context_messages", collapsed)
        logger.info(
            "[NormalPending] 已将 %s 条未回复用户消息合并为 1 条模型上下文消息 conv=%s",
            len(tail_user_indices),
            str(getattr(request, "conversation_id", "") or "")[:12],
        )
    except Exception as exc:
        logger.warning("[NormalPending] 合并未回复用户消息失败，保留原上下文继续: %s", exc)


_ANDROID_DELTA_CLIENT_IDS = {"single", "android"}
_RETRACTED_USER_MESSAGE_TEXTS = {"（撤回了消息）", "(撤回了消息)"}


def _is_retracted_user_message(msg: ChatMessage) -> bool:
    return (
        getattr(msg, "role", None) == "user"
        and str(getattr(msg, "content", "") or "").strip() in _RETRACTED_USER_MESSAGE_TEXTS
    )


def _db_message_to_chat_message(msg: dict[str, Any]) -> ChatMessage | None:
    if not isinstance(msg, dict):
        return None
    role = str(msg.get("role") or "").strip()
    if role not in {"user", "assistant"}:
        return None
    return ChatMessage(
        role=role,
        content=str(msg.get("content") or ""),
        image_url=msg.get("image_url"),
        timestamp=msg.get("timestamp"),
        isHidden=bool(msg.get("isHidden") or msg.get("is_hidden")),
        message_id=msg.get("message_id"),
        sequence_number=msg.get("sequence_number"),
        previous_message_id=msg.get("previous_message_id"),
        client_id=msg.get("client_id"),
        generation_duration_ms=msg.get("generation_duration_ms"),
        attachments=msg.get("attachments"),
        voice_state=msg.get("voice_state"),
        voice_status=msg.get("voice_status"),
        voice_id=msg.get("voice_id"),
        voice_job_id=msg.get("voice_job_id"),
        voice_cache_key=msg.get("voice_cache_key"),
        tts_text=msg.get("tts_text"),
        transcript=msg.get("transcript"),
        text_fragments=msg.get("text_fragments"),
        voice_error=msg.get("voice_error"),
        quoted_message=msg.get("quoted_message"),
        speaker_character_id=msg.get("speaker_character_id") or msg.get("speakerCharacterId"),
        speaker_name=msg.get("speaker_name") or msg.get("speakerName"),
        speaker_avatar=msg.get("speaker_avatar") or msg.get("speakerAvatar"),
    )


async def _enrich_recent_chat_voice_states(
    recent_chat: list[dict],
    conversation_id: Optional[str],
) -> list[dict]:
    """Planner needs delivery metadata even when the client only sent text history."""
    conv_id = str(conversation_id or "").strip()
    if not conv_id or not recent_chat:
        return recent_chat
    message_ids = [
        str(msg.get("message_id") or "").strip()
        for msg in recent_chat
        if isinstance(msg, dict) and msg.get("role") == "assistant"
    ]
    message_ids = [mid for mid in message_ids if mid]
    if not message_ids:
        return recent_chat
    try:
        from ..db.message_voice_states import attach_voice_state, load_voice_states_for_messages

        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            states_by_mid = await load_voice_states_for_messages(conn, conv_id, message_ids)
        if not states_by_mid:
            return recent_chat
        for msg in recent_chat:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            mid = str(msg.get("message_id") or "").strip()
            if mid:
                attach_voice_state(msg, states_by_mid.get(mid))
    except Exception as exc:
        logger.debug("🎙️ [NormalPlanner] 补齐最近语音状态失败 conv=%s: %s", conv_id[:12], exc)
    return recent_chat


def _chat_message_to_recent_dict(msg: ChatMessage) -> dict[str, Any]:
    content = str(getattr(msg, "content", "") or "")
    if getattr(msg, "role", None) == "assistant":
        speaker_name = str(getattr(msg, "speaker_name", "") or "").strip()
        speaker_id = str(getattr(msg, "speaker_character_id", "") or "").strip()
        if speaker_name or speaker_id:
            content = f"【{speaker_name or speaker_id}在当前对话中的发言】\n{content}"
    item: dict[str, Any] = {
        "role": getattr(msg, "role", ""),
        "content": content,
    }
    for key in (
        "message_id",
        "timestamp",
        "voice_state",
        "voice_status",
        "voice_id",
        "voice_job_id",
        "voice_cache_key",
        "tts_text",
        "transcript",
        "text_fragments",
        "voice_error",
        "speaker_character_id",
        "speaker_name",
        "speaker_avatar",
    ):
        value = getattr(msg, key, None)
        if value is not None:
            item[key] = value
    return item


async def _load_server_recent_chat_for_planner(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
    *,
    max_messages: int = 6,
) -> list[dict]:
    """Planner-side recent history fallback for clients that send only the newest user message."""
    if not username or not character_id or not conversation_id:
        return []
    try:
        db = get_database()
        await db.init()
        from ..db.conversations_dao import ConversationsDAO

        convs_dao = ConversationsDAO(db)
        convs = await convs_dao.load_conversations(username, character_id)
        conv_id = str(conversation_id or "").strip()
        target = next((c for c in convs if str(c.get("id") or "") == conv_id), None)
        if not target:
            return []
        out: list[dict] = []
        for raw in target.get("messages") or []:
            cm = _db_message_to_chat_message(raw)
            if cm is None or getattr(cm, "isHidden", False):
                continue
            if getattr(cm, "role", None) not in {"user", "assistant"}:
                continue
            content = str(getattr(cm, "content", "") or "").strip()
            if not content and getattr(cm, "role", None) != "assistant":
                continue
            out.append(_chat_message_to_recent_dict(cm))
        return out[-max_messages:]
    except Exception as exc:
        logger.debug("[NormalPlanner] 加载服务端最近对话供导演参考失败 conv=%s: %s", str(conversation_id or "")[:12], exc)
        return []


def _latest_visible_user_batch(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Return only the newest user batch after the last assistant message."""
    if not messages:
        return []
    start = 0
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "role", None) == "assistant":
            start = i + 1
            break
    out: list[ChatMessage] = []
    for msg in messages[start:]:
        if getattr(msg, "role", None) != "user" or getattr(msg, "isHidden", False):
            continue
        content = str(getattr(msg, "content", "") or "")
        if content.startswith("[以下是本对话之前内容的摘要"):
            continue
        out.append(msg)
    if out:
        return out
    last_user = next(
        (
            m for m in reversed(messages)
            if getattr(m, "role", None) == "user"
            and not getattr(m, "isHidden", False)
            and not str(getattr(m, "content", "") or "").startswith("[以下是本对话之前内容的摘要")
        ),
        None,
    )
    return [last_user] if last_user else []


async def _rebuild_android_normal_request_from_server_history(
    request: ChatRequest,
    *,
    client_id: str,
) -> None:
    """Android normal chat sends only the newest user batch; server history is authoritative."""
    if (request.mode or "normal") != "normal" or request.is_summary_request:
        return
    if (client_id or "").strip() not in _ANDROID_DELTA_CLIENT_IDS:
        return
    latest_users = _latest_visible_user_batch(list(request.messages or []))
    if not latest_users:
        return

    server_messages: list[ChatMessage] = []
    try:
        db = get_database()
        await db.init()
        from ..db.conversations_dao import ConversationsDAO

        convs_dao = ConversationsDAO(db)
        convs = await convs_dao.load_conversations(request.username or "", request.character_id or "")
        target = None
        requested_conv_id = str(getattr(request, "conversation_id", "") or "").strip()
        if requested_conv_id:
            target = next((c for c in convs if str(c.get("id") or "") == requested_conv_id), None)
        if target is None and convs:
            target = convs[0]
            request.conversation_id = str(target.get("id") or request.conversation_id or "")
        if target:
            for raw in target.get("messages") or []:
                cm = _db_message_to_chat_message(raw)
                if cm is not None:
                    server_messages.append(cm)
    except Exception as exc:
        logger.warning("📲 [AndroidDelta] 加载服务端历史失败，保留本轮用户消息继续: %s", exc)

    merged = list(server_messages)
    existing_ids = {
        str(getattr(m, "message_id", "") or "").strip()
        for m in merged
        if str(getattr(m, "message_id", "") or "").strip()
    }
    appended = 0
    replaced_retracted = 0
    preserved_transient_media = False
    for msg in latest_users:
        mid = str(getattr(msg, "message_id", "") or "").strip()
        if mid and mid in existing_ids:
            if _is_retracted_user_message(msg):
                for idx, existing in enumerate(merged):
                    if str(getattr(existing, "message_id", "") or "").strip() != mid:
                        continue
                    merged[idx] = msg
                    # 撤回语义以这条 user 为新的对话尾部，丢弃原请求可能已经生成/落库的旧角色回复。
                    merged = merged[: idx + 1]
                    existing_ids = {
                        str(getattr(m, "message_id", "") or "").strip()
                        for m in merged
                        if str(getattr(m, "message_id", "") or "").strip()
                    }
                    replaced_retracted += 1
                    break
            else:
                transient_images = collect_message_images(msg)
                if transient_images:
                    for idx, existing in enumerate(merged):
                        if str(getattr(existing, "message_id", "") or "").strip() != mid:
                            continue
                        if hasattr(existing, "model_copy"):
                            patched = existing.model_copy(deep=True)
                        else:
                            patched = existing.copy(deep=True)
                        patched.image_url = transient_images[0]
                        patched.images = transient_images
                        if getattr(msg, "attachments", None) and not getattr(patched, "attachments", None):
                            patched.attachments = getattr(msg, "attachments", None)
                        if not str(getattr(patched, "content", "") or "").strip():
                            patched.content = str(getattr(msg, "content", "") or "")
                        merged[idx] = patched
                        preserved_transient_media = True
                        break
            continue
        merged.append(msg)
        appended += 1
        if mid:
            existing_ids.add(mid)
    if appended == 0 and latest_users and not preserved_transient_media:
        # Regenerate/retry path: keep the latest user visible to the model even if DB already has it.
        merged = list(server_messages)
    request.messages = merged or latest_users
    try:
        from .state import apply_backend_context_summary_if_needed, estimate_request_context_tokens, get_model_context_messages

        await apply_backend_context_summary_if_needed(request)
        setattr(request, "_android_delta_request_tokens", estimate_request_context_tokens(get_model_context_messages(request)))
    except Exception as exc:
        logger.debug("📲 [AndroidDelta] 重算上下文摘要/Token 失败: %s", exc)
    logger.info(
        "📲 [AndroidDelta] 普通对话请求已按服务端历史重建: server=%s latest_user=%s final=%s retracted=%s conv=%s",
        len(server_messages),
        len(latest_users),
        len(request.messages or []),
        replaced_retracted,
        str(getattr(request, "conversation_id", "") or "")[:12],
    )


async def _persist_android_normal_user_delta(request: ChatRequest, *, client_id: str) -> None:
    """Persist the newest Android normal-mode user message before debounce.

    Android sends only the current user delta. The backend owns debounce and
    request coalescing, so each incoming delta must become part of authoritative
    server history before a later request rebuilds its context.
    """
    if (request.mode or "normal") != "normal" or request.is_summary_request:
        return
    if (client_id or "").strip() not in _ANDROID_DELTA_CLIENT_IDS:
        return
    if not request.username or not request.character_id:
        return
    if not _latest_visible_user_batch(list(request.messages or [])):
        return
    try:
        await _rebuild_android_normal_request_from_server_history(request, client_id=client_id)
        setattr(request, "_normal_enable_guest_direct_prewrite", True)
        await prepare_normal_reply_speaker(request)
        from .runtime import run_conversation_persistence

        save_ok, save_msg, _ = await run_conversation_persistence(
            request,
            "client_user_delta",
            "",
            int(time.time() * 1000),
            persist_user_only=True,
        )
        if not save_ok:
            logger.warning("📲 [AndroidDelta] 预保存用户消息失败: %s", save_msg)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("📲 [AndroidDelta] 预保存用户消息异常，继续走请求体上下文: %s", exc)


async def _load_recent_deleted_tail_context(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
) -> str:
    """已停用：不再把已删除角色回复注入模型上下文。"""
    return ""


async def _is_new_contact_opening(
    request: ChatRequest,
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
) -> bool:
    """当本场 normal 聊天尚无可见的角色回复时为 True。"""
    try:
        for msg in getattr(request, "messages", None) or []:
            if (
                getattr(msg, "role", None) == "assistant"
                and not getattr(msg, "isHidden", False)
                and str(getattr(msg, "content", "") or "").strip()
            ):
                return False
    except Exception:
        pass

    if not username or not character_id:
        return True

    try:
        db = get_database()
        conn = await db.acquire()
        try:
            where_conv = "AND c.id = ?" if conversation_id else ""
            params = [username, character_id]
            if conversation_id:
                params.append(conversation_id)
            async with conn.execute(
                f"""
                SELECT COUNT(*)
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  JOIN users u ON u.id = c.user_id
                 WHERE u.username = ?
                   AND c.character_id = ?
                    {where_conv}
                   AND COALESCE(c.is_hidden, 0) = 0
                   AND m.role = 'assistant'
                   AND m.deleted_at IS NULL
                   AND COALESCE(m.is_hidden, 0) = 0
                """,
                tuple(params),
            ) as cur:
                row = await cur.fetchone()
        finally:
            await db.release(conn)
        return int(row[0] if row else 0) <= 0
    except Exception as exc:
        logger.debug("[NewContactOpening] prior assistant check failed: %s", exc)
        return True


def _build_planner_character_prompt_context(username: Optional[str], character_id: Optional[str]) -> str:
    """返回原始角色资料，供后续 normal planner 包装使用。

    planner/Step 2 需要完整角色 prompt 做自我认知；Step 3 只会从这里
    抽取主页档案字段，不会直接接收完整 prompt。
    """
    if not username or not character_id:
        return ""
    try:
        character = load_character_from_db(username, character_id) or {}
        profile_prompt = build_character_profile_prompt_block(character).strip()
        prompt = str(character.get("prompt") or "").strip()
        parts = [part for part in (profile_prompt, prompt) if part]
        if not parts:
            return ""
        name = str(character.get("name") or character_id).strip()
        return f"角色名称：{name}\n\n" + "\n\n".join(parts)
    except Exception as exc:
        logger.debug("[NormalPlanner] 加载角色设定供导演参考失败: %s", exc)
        return ""


_PLANNER_CHARACTER_COMPACT_KEYWORDS = (
    "角色名称",
    "名称",
    "性别",
    "种族",
    "年龄",
    "16人格",
    "性格",
    "兴趣",
    "简介",
    "身份",
    "职业",
    "工作",
    "说话",
    "语气",
    "口癖",
    "称呼",
    "喜欢",
    "讨厌",
    "害怕",
    "能力",
    "擅长",
    "亲密",
    "关系",
    "边界",
)


def _build_planner_step1_character_prompt_context(character_prompt_context: str, *, limit: int = 2200) -> str:
    """Short character hints for routing steps.

    The full character prompt is intentionally kept for Step 2 self-cognition.
    Step 1 and lightweight tools only need identity/voice hints so they do not
    repeatedly pay for the whole setting.
    """
    raw = str(character_prompt_context or "").strip()
    if not raw:
        return ""
    kept: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        text = re.sub(r"\s+", " ", str(line or "").strip())
        if not text:
            continue
        if len(text) > 260:
            text = text[:260] + "..."
        if any(key in text for key in _PLANNER_CHARACTER_COMPACT_KEYWORDS):
            if text not in seen:
                kept.append(text)
                seen.add(text)
        if sum(len(x) + 1 for x in kept) >= limit:
            break
    if not kept:
        kept = [re.sub(r"\s+", " ", raw[: min(limit, 900)]).strip()]
    note = "【完整角色设定注入位置】完整角色设定只在 Step 2 自我认知工具中完整读取；本段是供 Step 1/轻量工具使用的短角色摘要。"
    return (note + "\n" + "\n".join(kept))[:limit]


_PLANNER_CONTEXT_SCAFFOLD_RE = re.compile(
    r"(以下是各轮已发生事实|只描述已发生之事|禁止复述|不得凭角色设定|必须以用户原话|"
    r"若与最近真实对话|请据此继续对话|这些是角色大脑里的长期记忆|只可作为背景|"
    r"除非最近可见对话明确建立)"
)


def _compact_normal_stage_context(text: str, *, limit: int = 2600) -> str:
    """Keep fact-bearing lines, drop prompt scaffolding for non-memory-recall steps."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    out: list[str] = []
    total = 0
    for line in raw.splitlines():
        item = re.sub(r"\s+", " ", line.strip())
        if not item or _PLANNER_CONTEXT_SCAFFOLD_RE.search(item):
            continue
        keep_header = item.startswith("【") or item.startswith("[") or item.startswith("──")
        keep_fact = bool(
            re.search(
                r"(20\d{2}|第\d+轮|当前|位置|地点|卧室|房间|门口|一起|约定|喜欢|关系|表白|求婚|订婚|群聊|@|刚才|今天|昨天|明天|用户|角色)",
                item,
            )
        )
        if not (keep_header or keep_fact):
            continue
        if len(item) > 240:
            item = item[:240] + "..."
        next_len = len(item) + 1
        if total + next_len > limit:
            break
        out.append(item)
        total += next_len
    if not out:
        return re.sub(r"\s+", " ", raw[:limit]).strip()
    return "\n".join(out)[:limit]


def _join_nonempty_context_parts(*parts: str) -> str:
    return "\n\n".join(str(part or "").strip() for part in parts if str(part or "").strip())


_DESCRIPTION_INSTRUCTION_RE = re.compile(
    r"(请)?(详细|具体|仔细|多段|分段)?(写出|描写|描述|写一下|写一写|展开)"
    r".{0,18}(当前|现在|此刻|这时)?(你|角色|自己)?"
    r".{0,18}(心理活动|内心|想法|身体状态|身体反应|身体感受|感受|周围的环境|环境描写|环境|看到的画面|看到|画面|动作|表情|状态)"
)
_DESCRIPTION_ONLY_RE = re.compile(r"(不要说话|只描写|只描述|只写感受|只写心理|只写动作|纯描写)")
_BRACKET_ACTION_RE = re.compile(r"[（(]\s*([^（）()]{2,160})\s*[）)]")
_USER_ACTION_HINT_RE = re.compile(
    r"(我|俺|本人|咱|我们|咱们).{0,24}"
    r"(递|给|扶|牵|拉|推|拿|放|挡|拦|打开|关上|坐|站|靠近|抱|握|摸|拍|指|看向|走|跑|跳|躲|转身|捡|递给|拿走)"
)


def _latest_user_text(request: ChatRequest) -> str:
    last_user = next(
        (
            m for m in reversed(getattr(request, "messages", None) or [])
            if getattr(m, "role", None) == "user"
            and not getattr(m, "isHidden", False)
        ),
        None,
    )
    return str(getattr(last_user, "content", "") or "")


_GREETING_ONLY_OPENING_RE = re.compile(
    r"^\s*(?:你好|您好|哈喽|hello|hi|嗨|在吗|早安|午安|晚上好|晚安|喂)[。！!？?\s~～,.，、]*$",
    re.I,
)
_SUBSTANTIVE_OPENING_RE = re.compile(
    r"(请|怎么|为什么|哪里|哪儿|在哪|什么|多少|是否|是不是|吗|？|\?|"
    r"乳房|乳腺|胸前|胸口|肚子下方|胯间|后腿之间|可爱标记|蹄|手指|手掌|"
    r"第一次来我家|来我家|我的房间|我房间|用户家|用户房间|当前|现在|画面|场景|描写|描述|写出|检查|对比)"
)


def _new_contact_opening_should_preserve_user_task(text: str) -> bool:
    """Return True when the first user turn is already a concrete task/question."""
    content = re.sub(r"\s+", "", str(text or ""))
    if not content or _GREETING_ONLY_OPENING_RE.match(content):
        return False
    if len(content) >= 18:
        return True
    return bool(_SUBSTANTIVE_OPENING_RE.search(content))


def _latest_user_message_id_from_request(request: ChatRequest) -> str:
    last_user = next(
        (
            m for m in reversed(getattr(request, "messages", None) or [])
            if getattr(m, "role", None) == "user"
            and not getattr(m, "isHidden", False)
        ),
        None,
    )
    return str(getattr(last_user, "message_id", "") or "") if last_user is not None else ""


def _is_legitimate_description_instruction_text(text: str) -> bool:
    content = re.sub(r"\s+", "", str(text or ""))
    if not content:
        return False
    return bool(_DESCRIPTION_INSTRUCTION_RE.search(content) or _DESCRIPTION_ONLY_RE.search(content))


def _is_pure_description_instruction_text(text: str) -> bool:
    content = re.sub(r"\s+", "", str(text or ""))
    if not content:
        return False
    if re.search(r"(?:不是|并非|并不是|不属于|非).{0,12}(?:纯描写|只描写|只描述|禁言|不要说话|不说话)", content):
        return False
    if _DESCRIPTION_ONLY_RE.search(content) or re.search(r"(不要|别|不用|禁止).{0,8}(说话|台词|对白|发言)", content):
        return True
    return bool(
        re.search(
            r"(请)?(?:继续|接着|再)?详细写出当前(?:你的(?:心理活动|身体状态)|周围的环境描写|你看到的画面)",
            content,
        )
    )


_DIRECT_LOCATION_QUERY_RE = re.compile(
    r"(在哪(?:里|儿)?|在哪里|在哪儿|哪儿|哪里|位置(?:在)?哪|位置在哪里|当前位置|当前的位置|在什么地方|在何处)"
)
_SCENE_STATE_AUDIT_RE = re.compile(
    r"(分别在哪|分别在哪里|物品.*在哪|位置.*姿势|什么姿势|只说现在|只说当前|当前状态|没有任何人移动|没有换场景|杯子|钥匙|红皮书|蓝色陶瓷杯)"
)
_LOCATION_QUERY_DETAIL_RE = re.compile(
    r"(看见|看到|听见|听到|发生|聊了什么|说了什么|做了什么|所见所闻|心理|内心|想法|感受|画面|描述|描写|详细|为什么|怎么想|怎么看|同意|拒绝|去过|到过|经过|走过|来过|逛过|路过|路线|行程|先后|哪些地方|哪几个地方)"
)


def _is_direct_location_query_text(text: str) -> bool:
    content = re.sub(r"[\s，。！？!?、；;：:（）()\[\]【】\"'“”‘’]+", "", str(text or ""))
    if not content:
        return False
    if _is_legitimate_description_instruction_text(text):
        return False
    if _LOCATION_QUERY_DETAIL_RE.search(content):
        return False
    return bool(_DIRECT_LOCATION_QUERY_RE.search(content))


def _is_scene_state_audit_query_text(text: str) -> bool:
    content = re.sub(r"[\s，。！？!?、；;：:（）()\[\]【】\"'“”‘’]+", "", str(text or ""))
    if not content:
        return False
    if _is_legitimate_description_instruction_text(text):
        return False
    has_location_or_state = bool(_DIRECT_LOCATION_QUERY_RE.search(content) or "当前状态" in content or "只说现在" in content)
    has_multi_slot = bool(_SCENE_STATE_AUDIT_RE.search(content))
    has_item_probe = bool(re.search(r"(杯子|蓝色陶瓷杯|钥匙|红皮书|物品).{0,20}(分别|在哪|哪里|位置)", content))
    return has_location_or_state and (has_multi_slot or has_item_probe)


def _apply_direct_location_query_policy(planner_result: dict, latest_user_text: str) -> dict:
    is_scene_audit = _is_scene_state_audit_query_text(latest_user_text)
    if not is_scene_audit and not _is_direct_location_query_text(latest_user_text):
        return planner_result
    fact = planner_result.get("fact_judgement") if isinstance(planner_result.get("fact_judgement"), dict) else {}
    fact = dict(fact)
    desc = fact.get("description_request") if isinstance(fact.get("description_request"), dict) else {}
    if desc:
        fact["description_request"] = {
            **desc,
            "enabled": False,
            "target": "",
            "intensity": "normal",
            "full_bracket_bubbles": False,
            "dialogue_allowed": True,
            "reason": "当前用户只是位置查询，不延续上一轮描写或心理活动请求。",
        }
    avoid = list(planner_result.get("avoid_contradictions") or [])
    if is_scene_audit:
        has_completed_handoff = bool(
            re.search(r"(递给我|交给我|给我|递到我手|交到我手)", str(latest_user_text or ""))
        )
        for item in (
            "场景状态核对必须即时回复，speech_activity 不得为 0-8，bubble_count 不得为 0",
            "场景状态核对不能只回答位置；必须覆盖用户点名的位置、姿势和每个物品状态",
            "单气泡场景核对也要同一段列齐事实，不按普通短答压成一个事实点",
        ):
            if item not in avoid:
                avoid.append(item)
        if has_completed_handoff:
            for item in (
                "当前用户叙述“把 X 递给我/交给我/给我”后再追问现在状态时，X 必须写成已经在用户手里/用户处",
                "不得把已完成递交动作写成正要递、这就递、准备递、仍在角色手里或递到面前但未交付",
            ):
                if item not in avoid:
                    avoid.append(item)
        policy = (
            "场景状态核对覆盖：当前用户正在核对位置、姿势和多个物品状态。"
            "本轮必须即时回复；同一段内按用户点名顺序列齐当前角色位置/姿势、杯子、钥匙、红皮书等槽位。"
            "不要只答“我在旁边/站着”，也不要用“都在原处/没动”替代具体物品位置。"
        )
        if has_completed_handoff:
            policy += (
                "当前用户说“把银色钥匙递给我/交给我/给我”属于已完成动作；"
                "最终正文必须写钥匙已经在用户手里/你那里，禁止写成我正要递、这就递、还在我手里。"
            )
        memory_policy = (
            "当前用户是在核对当前场景状态；只使用当前场景锚点、最近可见对话和事实边界中明确支持的 current position/posture/items。"
            "长期记忆和角色设定不能覆盖这些当前槽位。"
        )
        try:
            current_activity = int(planner_result.get("speech_activity") or 0)
        except Exception:
            current_activity = 0
        return {
            **planner_result,
            "fact_judgement": fact if fact else planner_result.get("fact_judgement", fact),
            "reply_intent": "回答当前场景状态/物品位置核对",
            "tone": planner_result.get("tone") or "简短、清楚、贴近角色",
            "length": "medium",
            "action_style": "plain_text",
            "speech_activity": max(56, current_activity),
            "bubble_count": max(1, int(planner_result.get("bubble_count") or 1)),
            "speech_reason": "当前用户要求核对当前场景位置、姿势和物品状态，必须即时答全",
            "should_ask_question": False,
            "expression_policy": _append_service_policy_text(planner_result.get("expression_policy"), policy),
            "memory_use_policy": _append_service_policy_text(planner_result.get("memory_use_policy"), memory_policy),
            "avoid_contradictions": avoid,
            "reply_sequence": planner_result.get("reply_sequence") or [{"type": "text", "intent": "scene_state_audit"}],
        }
    for item in (
        "不要把上一轮心理活动/描写/只写感受请求延续到本轮位置短问句",
        "位置查询只回答当前角色自己的地点/姿态；不要顺带复述昨晚经历、群聊所见所闻或旧事回忆",
    ):
        if item not in avoid:
            avoid.append(item)
    policy = (
        "位置短问句覆盖：当前用户只是在问当前/刚才的位置。"
        "本轮只回答当前角色自己的地点或姿态，可轻带一句即时状态；"
        "不要延续上一轮心理活动/描写写法，不要主动展开昨晚经历、群聊所见所闻或旧事回忆。"
        "如果需要使用临时群聊记忆，只取 scene_anchor/current_character.position。"
    )
    memory_policy = (
        "当前用户是位置短问句；只使用当前场景锚点或当前角色 position 回答位置，"
        "不把旧的描写请求、心理活动内容或群聊 observations 当作本轮正文素材。"
    )
    try:
        current_activity = int(planner_result.get("speech_activity") or 45)
    except Exception:
        current_activity = 45
    bounded_activity = max(36, min(max(current_activity, 36), 55))
    return {
        **planner_result,
        "fact_judgement": fact if fact else planner_result.get("fact_judgement", fact),
        "reply_intent": "回答当前位置",
        "tone": planner_result.get("tone") or "简短、贴近角色",
        "length": "short",
        "action_style": "light_inline",
        "speech_activity": bounded_activity,
        "bubble_count": 1,
        "speech_reason": "当前用户只是询问位置，需要简短回答，不延续上一轮描写请求",
        "should_ask_question": False,
        "expression_policy": _append_service_policy_text(planner_result.get("expression_policy"), policy),
        "memory_use_policy": _append_service_policy_text(planner_result.get("memory_use_policy"), memory_policy),
        "avoid_contradictions": avoid,
    }


def _append_service_policy_text(existing: Any, addition: str) -> str:
    base = str(existing or "").strip()
    extra = str(addition or "").strip()
    if not base:
        return extra
    if not extra or extra in base:
        return base
    return base.rstrip() + "\n" + extra


def _prepend_service_policy_text(existing: Any, addition: str) -> str:
    base = str(existing or "").strip()
    extra = str(addition or "").strip()
    if not extra:
        return base
    if extra in base:
        return base
    if not base:
        return extra
    return extra.rstrip() + "\n" + base


def _extract_latest_user_action_anchor(request: ChatRequest) -> str:
    content = _latest_user_text(request)
    compact = re.sub(r"\s+", "", str(content or ""))
    if not compact:
        return ""
    snippets: list[str] = []
    for match in _BRACKET_ACTION_RE.finditer(str(content or "")):
        snippet = str(match.group(1) or "").strip()
        if snippet and _USER_ACTION_HINT_RE.search(re.sub(r"\s+", "", snippet)):
            snippets.append(snippet)
    if not snippets and _USER_ACTION_HINT_RE.search(compact):
        snippets.append(str(content or "").strip())
    if not snippets:
        return ""
    anchor = "；".join(snippets)[:220]
    return anchor


def _apply_latest_user_action_anchor(planner_result: dict, request: ChatRequest) -> dict:
    if getattr(request, "_normal_terminal_death_action", False):
        return planner_result
    anchor = _extract_latest_user_action_anchor(request)
    if not anchor:
        return planner_result
    instruction = (
        f"本轮最新用户动作锚点：{anchor}。主回复第一拍必须先承接这个动作，"
        "点出用户动作、物品/位置变化或角色即时反应之一；不要先进入早安、你好、自我介绍、旧日常或泛化闲聊。"
    )
    return {
        **planner_result,
        "reply_intent": f"先承接用户动作：{anchor}",
        "tone": _prepend_service_policy_text(
            planner_result.get("tone"),
            "第一句先回应本轮用户动作，再进入角色语气和后续内容。",
        ),
        "expression_policy": _prepend_service_policy_text(planner_result.get("expression_policy"), instruction),
        "proactive_seed": _prepend_service_policy_text(
            planner_result.get("proactive_seed"),
            f"先写角色对用户刚才动作的具体反应：{anchor}。",
        ),
        "avoid_contradictions": list(planner_result.get("avoid_contradictions") or [])
        + [
            "不要无视本轮用户刚做的动作",
            "不要把用户刚做的动作改写成角色自己主动完成",
            "不要用通用问候或自我介绍替代动作承接",
        ],
    }


def _description_instruction_bubble_count_from_activity(score: int) -> int:
    if score >= 91:
        return 4
    if score >= 76:
        return 3
    return 2


def _apply_description_instruction_policy(planner_result: dict, request: ChatRequest) -> dict:
    content = _latest_user_text(request)
    if not _is_legitimate_description_instruction_text(content):
        return planner_result
    detailed = any(k in content for k in ("详细", "环境", "画面", "看到", "身体", "状态", "心理", "感受", "动作", "表情"))
    target_activity = 82 if detailed else 65
    if "特别" in content or "四" in content or "多段" in content:
        target_activity = 95
    current_activity = 0
    try:
        current_activity = int(planner_result.get("speech_activity") or 0)
    except Exception:
        current_activity = 0
    if not _is_pure_description_instruction_text(content):
        mixed_activity = 72 if detailed else 58
        final_activity = max(current_activity, mixed_activity)
        try:
            existing_count = int(planner_result.get("bubble_count") or 1)
        except Exception:
            existing_count = 1
        existing_count = max(1, existing_count)
        target_count = min(existing_count, 2)
        if "多段" in content or "分段" in content:
            target_count = 2
        policy = (
            "合法描写/写法请求：本轮有描写焦点，但用户没有要求纯描写禁言；"
            "正文可以混合短台词和括号动作/心理/状态，台词仍可承担角色态度、选择和剧情推进。"
            "不要把心理、动作、身体反应逐项拆成多个纯括号气泡；"
            "不要套用“身体反应-心理活动-嗯/好”的固定三段模板。"
        )
        avoid = list(planner_result.get("avoid_contradictions") or [])
        for item in (
            "不要把普通剧情续写误判成只能输出完整括号描写",
            "不要输出多个纯括号动作/心理后只用“嗯/好/唔”等低信息短音收尾",
        ):
            if item not in avoid:
                avoid.append(item)
        return {
            **planner_result,
            "action_style": "cinematic" if detailed else "light_inline",
            "length": "medium" if detailed else planner_result.get("length", "medium"),
            "speech_activity": final_activity,
            "bubble_count": target_count,
            "speech_reason": "合法描写焦点可混合台词与短描写，不强制纯括号多气泡",
            "should_ask_question": False,
            "expression_policy": _append_service_policy_text(
                planner_result.get("expression_policy"),
                policy,
            ),
            "avoid_contradictions": avoid,
        }
    policy = (
        "合法描写/写法请求硬性格式：本轮必须按用户要求输出当前心理、身体、环境、画面、动作或感受描写，禁止写普通聊天台词；"
        "输出 2-4 个非空气泡，复杂画面/身体/环境可用 3-4 个，简单心理/感受可用 2 个；"
        "每个非空气泡必须是独立完整闭合的全角括号描写，逐段以「（」开头、以「）」结尾；"
        "每个气泡只承载一个镜头或状态层次，并根据需要自动控制字数，避免把长段落塞进一个气泡；"
        "单个气泡宜 60-140 个字符，复杂镜头最多约 180 个字符；如果超过这个长度，必须拆成下一个气泡，"
        "不要出现一个气泡承担两三个层次的长段落。"
    )
    avoid = list(planner_result.get("avoid_contradictions") or [])
    for item in (
        "不要把合法描写/写法请求当成普通寒暄或反问用户",
        "不要把多层描写合并成一个超长气泡",
        "不要让单个描写气泡超过约 180 个字符",
        "不要输出任何未包在全角括号里的非空段落",
    ):
        if item not in avoid:
            avoid.append(item)
    final_activity = max(current_activity, target_activity)
    return {
        **planner_result,
        "action_style": "cinematic",
        "length": "long" if detailed else planner_result.get("length", "medium"),
        "speech_activity": final_activity,
        "bubble_count": _description_instruction_bubble_count_from_activity(final_activity),
        "speech_reason": "合法描写/写法请求需要多段呈现，需用 2-4 个完整括号气泡便于阅读",
        "should_ask_question": False,
        "expression_policy": _append_service_policy_text(
            planner_result.get("expression_policy"),
            policy,
        ),
        "avoid_contradictions": avoid,
    }
