from __future__ import annotations

from .reply_language_state import encode_language

import base64
import json
import os
import re
import time
import urllib.parse
from typing import Any, Callable, Optional, Tuple

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import logger
from ..db import ConversationsDAO, get_database
from ..galgame import generate_message_id
from ..retry_manager import compute_backoff_delay
from ..utils import ChatRequest
from .assistant_units import build_assistant_units, split_assistant_paragraphs
from .normal_speaker import speaker_message_fields, effective_speaker_character_id
from ..websocket import galgame_locker
from .state import is_summary_placeholder_message
from .agent_logging import logged_persistence


def _is_internal_trigger_message(request: Any, msg: Any) -> bool:
    trigger_mid = str(getattr(request, "_normal_internal_trigger_message_id", "") or "").strip()
    if not trigger_mid:
        return False
    msg_mid = str(getattr(msg, "message_id", "") or "").strip()
    return bool(msg_mid and msg_mid == trigger_mid)


def _visible_message_for_proactive_guard(msg: dict[str, Any]) -> bool:
    if msg.get("deleted_at"):
        return False
    if bool(msg.get("isHidden") or msg.get("is_hidden")):
        return False
    return str(msg.get("role") or "") in {"user", "assistant"}


def _compact_for_proactive_similarity(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or ""), flags=re.UNICODE)


def _char_bigrams_for_proactive_similarity(text: str) -> set[str]:
    compact = _compact_for_proactive_similarity(text)
    if len(compact) <= 1:
        return {compact} if compact else set()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _proactive_text_similarity(a: str, b: str) -> float:
    aa = _char_bigrams_for_proactive_similarity(a)
    bb = _char_bigrams_for_proactive_similarity(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / max(1, len(aa | bb))


def _has_common_proactive_phrase(a: str, b: str, *, min_len: int = 7) -> bool:
    aa = _compact_for_proactive_similarity(a)
    bb = _compact_for_proactive_similarity(b)
    if len(aa) < min_len or len(bb) < min_len:
        return False
    if len(aa) > len(bb):
        aa, bb = bb, aa
    for size in range(min(18, len(aa)), min_len - 1, -1):
        for start in range(0, len(aa) - size + 1):
            if aa[start : start + size] in bb:
                return True
    return False


def _latest_assistant_text_for_proactive_guard(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages or []):
        if str(msg.get("role") or "") == "assistant" and _visible_message_for_proactive_guard(msg):
            return str(msg.get("content") or "")
    return ""


def _latest_assistant_group_for_proactive_guard(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    in_group = False
    for msg in reversed(messages or []):
        if not _visible_message_for_proactive_guard(msg):
            continue
        if str(msg.get("role") or "") == "assistant":
            parts.append(str(msg.get("content") or ""))
            in_group = True
            continue
        if in_group:
            break
    return "\n\n".join(reversed([p for p in parts if p.strip()]))


def _assistant_group_containing_for_proactive_guard(
    messages: list[dict[str, Any]],
    source_message_id: str,
) -> str:
    source = str(source_message_id or "").strip()
    if not source:
        return ""
    visible = [m for m in messages or [] if _visible_message_for_proactive_guard(m)]
    idx = next(
        (
            i
            for i, msg in enumerate(visible)
            if str(msg.get("message_id") or "").strip() == source
            and str(msg.get("role") or "") == "assistant"
        ),
        None,
    )
    if idx is None:
        return ""
    start = idx
    while start > 0 and str(visible[start - 1].get("role") or "") == "assistant":
        start -= 1
    end = idx
    while end + 1 < len(visible) and str(visible[end + 1].get("role") or "") == "assistant":
        end += 1
    return "\n\n".join(str(visible[i].get("content") or "") for i in range(start, end + 1))


def _normal_proactive_duplicate_guard_reason(
    content: str,
    messages: list[dict[str, Any]],
    *,
    source_message_id: str = "",
) -> str:
    text = str(content or "").strip()
    if not text:
        return "empty_message"
    last_assistant = _latest_assistant_text_for_proactive_guard(messages)
    if last_assistant:
        if _has_common_proactive_phrase(text, last_assistant):
            return "reuses_previous_assistant_core_phrase"
        if _proactive_text_similarity(text, last_assistant) >= 0.62:
            return "too_similar_to_previous_assistant"
    candidates = [
        ("too_similar_to_previous_assistant_group", _latest_assistant_group_for_proactive_guard(messages)),
        (
            "too_similar_to_source_assistant_group",
            _assistant_group_containing_for_proactive_guard(messages, source_message_id),
        ),
    ]
    seen: set[str] = set()
    for reason, candidate in candidates:
        candidate = str(candidate or "").strip()
        compact = _compact_for_proactive_similarity(candidate)
        if not compact or compact in seen:
            continue
        seen.add(compact)
        if _compact_for_proactive_similarity(text) == compact:
            return reason
        if _has_common_proactive_phrase(text, candidate):
            return reason
        if _proactive_text_similarity(text, candidate) >= 0.72:
            return reason
    return ""


def extract_usage_from_response(resp_json: dict) -> Tuple[int, int]:
    usage = resp_json.get("usage") or resp_json.get("usage_metadata") or resp_json.get("usageMetadata") or {}
    if isinstance(usage, dict):
        inp = int(usage.get("input_tokens") or usage.get("prompt_tokens") or usage.get("promptTokenCount") or 0)
        out = int(usage.get("output_tokens") or usage.get("completion_tokens") or usage.get("candidatesTokenCount") or usage.get("outputTokenCount") or 0)
        cache = int(usage.get("cache_read_input_tokens") or usage.get("cacheReadInputTokens") or usage.get("cache_read_tokens") or 0)
        return (inp + cache, out)
    return (0, 0)


def estimate_output_tokens(text: str) -> int:
    if not text or not isinstance(text, str):
        return 0
    from ..utils import _count_text_tokens
    return max(0, _count_text_tokens(text) + 20)


class RetryableHTTPStatusError(Exception):
    def __init__(self, response: Optional[httpx.Response] = None, status_code: Optional[int] = None, detail: str = ""):
        self.response = response
        self.status_code = int(status_code if status_code is not None else (response.status_code if response is not None else 0))
        self.detail = detail
        super().__init__(f"HTTP {self.status_code}")


async def post_with_transport_retry(
    *,
    client: httpx.AsyncClient,
    api_url: str,
    request_payload: dict,
    headers: dict,
    max_transport_retries: int,
    on_before_sleep: Optional[Callable[[Exception, int, int], None]] = None,
) -> httpx.Response:
    async def _request_once() -> httpx.Response:
        resp = await client.post(api_url, json=request_payload, headers=headers)
        if resp.status_code != 200:
            raise RetryableHTTPStatusError(resp)
        return resp

    def _log_before_sleep(retry_state) -> None:
        err = retry_state.outcome.exception() if retry_state.outcome else None
        attempt_used = retry_state.attempt_number
        delay = compute_backoff_delay(max(0, attempt_used - 1))
        if err is None:
            return
        if on_before_sleep is not None:
            on_before_sleep(err, attempt_used, delay)
            return
        if isinstance(err, RetryableHTTPStatusError):
            logger.warning("🔄 API 请求失败 (HTTP %s)，%s秒后重试", err.status_code, delay)
            logger.warning("🔄 传输层重试预算消耗 %s/%s（HTTP=%s）", attempt_used, max_transport_retries, err.status_code)
        elif isinstance(err, httpx.RequestError):
            logger.warning("🔄 网络请求异常: %s，%s秒后重试", err, delay)
            logger.warning("🔄 传输层重试预算消耗 %s/%s（网络异常）", attempt_used, max_transport_retries)

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_transport_retries + 1),
        wait=wait_exponential(multiplier=1, min=1),
        retry=retry_if_exception_type((RetryableHTTPStatusError, httpx.RequestError)),
        before_sleep=_log_before_sleep,
        reraise=True,
    ):
        with attempt:
            return await _request_once()


def ensure_windows_cairo_runtime() -> None:
    if os.name != "nt":
        return
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    candidates = [
        os.path.join(project_root, "misc", "tools", "gtk", "bin"),
        r"C:\Program Files\GTK3-Runtime Win64\bin",
        r"C:\msys64\mingw64\bin",
    ]
    for dll_dir in candidates:
        if not os.path.isdir(dll_dir):
            continue
        if dll_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(dll_dir)  # type: ignore[attr-defined]
        except Exception:
            pass


@logged_persistence
async def run_conversation_persistence(
    request,
    model_name: str,
    full_text: str,
    gen_start_ms: int = 0,
    *,
    persist_user_only: bool = False,
) -> tuple[bool, str, list[str] | None]:
    if not request.username or not request.character_id:
        return True, "", None
    effective_text = (full_text or "").strip()
    has_assets = bool(
        getattr(request, "_assistant_asset_by_request_id", None)
        or getattr(request, "_assistant_asset_attachments", None)
    )
    if not effective_text and not has_assets and not persist_user_only:
        return True, "", None
    try:
        class _NoopAsyncLock:
            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc, tb):
                return False

        lock_ctx = (
            _NoopAsyncLock()
            if bool(getattr(request, "_normal_skip_persistence_galgame_lock", False))
            else galgame_locker.acquire(request.username, request.character_id)
        )
        async with lock_ctx:
            requested_conv_id = str(request.conversation_id or "").strip()
            conv_id = requested_conv_id
            clean_content = re.sub(r'<(?:think|thinking)>.*?</(?:think|thinking)>', '', full_text, flags=re.DOTALL).strip()
            now_ts = int(time.time() * 1000)
            generation_duration_ms = (now_ts - gen_start_ms) if gen_start_ms > 0 else None
            existing_messages = []
            matched_conv = None
            load_failed = False
            try:
                db = get_database()
                await db.init()
                convs_dao = ConversationsDAO(db)
                existing_convs = await convs_dao.load_conversations(request.username, request.character_id)
                request_mids = {
                    str(getattr(m, "message_id", "") or "").strip()
                    for m in (request.messages or [])
                    if str(getattr(m, "message_id", "") or "").strip()
                }

                if not conv_id and existing_convs:
                    best_conv = None
                    best_hits = 0
                    if request_mids:
                        for c in existing_convs:
                            hits = sum(
                                1
                                for m in (c.get("messages") or [])
                                if str(m.get("message_id") or "") in request_mids
                            )
                            if hits > best_hits:
                                best_conv = c
                                best_hits = hits
                    if best_conv and best_hits > 0:
                        conv_id = str(best_conv.get("id") or "").strip()
                        matched_conv = best_conv
                        logger.warning(
                            "🛡️ [DB-AutoSave] 请求缺少 conversation_id，但消息链匹配旧对话，已续接: "
                            "%s/%s/%s (hits=%s)",
                            request.username,
                            request.character_id,
                            conv_id[:12],
                            best_hits,
                        )
                    elif len(request.messages or []) > 1:
                        latest_conv = next((c for c in existing_convs if c.get("messages")), existing_convs[0])
                        conv_id = str(latest_conv.get("id") or "").strip()
                        logger.warning(
                            "🛡️ [DB-AutoSave] 请求缺少 conversation_id 且携带多条历史，已续接最近对话: "
                            "%s/%s/%s",
                            request.username,
                            request.character_id,
                            conv_id[:12],
                        )
                if not conv_id:
                    conv_id = f"conv_{int(time.time()*1000)}"

                if not matched_conv:
                    matched_conv = next((c for c in existing_convs if c.get("id") == conv_id), None)
                if not matched_conv and requested_conv_id:
                    if request_mids:
                        best_conv = None
                        best_hits = 0
                        for c in existing_convs:
                            hits = sum(
                                1
                                for m in (c.get("messages") or [])
                                if str(m.get("message_id") or "") in request_mids
                            )
                            if hits > best_hits:
                                best_conv = c
                                best_hits = hits
                        if best_conv and best_hits > 0:
                            old_conv_id = conv_id
                            conv_id = str(best_conv.get("id") or conv_id)
                            matched_conv = best_conv
                            logger.warning(
                                "🛡️ [DB-AutoSave] 请求 conversation_id 未命中，但消息链匹配旧对话，已重新挂回: "
                                "%s/%s %s -> %s (hits=%s)",
                                request.username,
                                request.character_id,
                                old_conv_id[:12],
                                conv_id[:12],
                                best_hits,
                            )
                if matched_conv:
                    existing_messages = matched_conv.get("messages", [])
            except Exception as db_load_err:
                load_failed = True
                logger.warning(f"⚠️ [DB] 加载现有对话失败: {db_load_err}")
            if load_failed:
                return False, "加载现有对话失败，已跳过保存以防覆盖历史", None
            # 以客户端上送的消息序列作为当前会话真相源（可反映“重试后移除旧轮次”），
            # 同时优先复用 DB 中同 message_id 的已有记录，保留 rawContent 等扩展字段。
            existing_by_mid = {
                str(m.get("message_id")): m
                for m in (existing_messages or [])
                if m.get("message_id")
            }
            append_only = bool(getattr(request, "_normal_persist_append_only", False))
            internal_trigger_mid = str(getattr(request, "_normal_internal_trigger_message_id", "") or "").strip()
            char_convs: list[dict] = []
            if append_only:
                char_convs = [dict(m) for m in (existing_messages or [])]
                existing_ids = {
                    str(m.get("message_id") or "").strip()
                    for m in char_convs
                    if str(m.get("message_id") or "").strip()
                }
                if internal_trigger_mid and not persist_user_only:
                    trigger_msg = next(
                        (
                            m for m in (request.messages or [])
                            if _is_internal_trigger_message(request, m)
                        ),
                        None,
                    )
                    if trigger_msg is not None and internal_trigger_mid not in existing_ids:
                        char_convs.append(
                            {
                                "role": "user",
                                "content": getattr(trigger_msg, "content", None) or "",
                                "timestamp": getattr(trigger_msg, "timestamp", None) or (now_ts - 100),
                                "image_url": getattr(trigger_msg, "image_url", None),
                                "message_id": internal_trigger_mid,
                                "sequence_number": len(char_convs),
                                "previous_message_id": char_convs[-1].get("message_id") if char_convs else None,
                                "isHidden": True,
                                "hidden_reason": "internal_proactive_trigger",
                                "client_id": "internal_proactive",
                            }
                        )
            else:
                seen_request_mids: set[str] = set()
                for idx, req_msg in enumerate(request.messages or []):
                    if is_summary_placeholder_message(req_msg):
                        continue
                    req_mid = str(getattr(req_msg, "message_id", None) or "").strip()
                    if req_mid and req_mid in seen_request_mids:
                        continue
                    if req_mid:
                        seen_request_mids.add(req_mid)

                    base = dict(existing_by_mid.get(req_mid) or {})
                    base["role"] = getattr(req_msg, "role", None) or base.get("role") or "user"
                    base["content"] = getattr(req_msg, "content", None) or base.get("content") or ""
                    base["timestamp"] = getattr(req_msg, "timestamp", None) or base.get("timestamp") or (now_ts - 1000 + idx)
                    base["image_url"] = getattr(req_msg, "image_url", None) or base.get("image_url")
                    base["message_id"] = req_mid or base.get("message_id") or generate_message_id()
                    req_attachments = getattr(req_msg, "attachments", None)
                    if req_attachments is not None:
                        base["attachments"] = [
                            a.model_dump(exclude_none=True) if hasattr(a, "model_dump")
                            else a.dict(exclude_none=True) if hasattr(a, "dict")
                            else a
                            for a in (req_attachments or [])
                        ]
                    req_quote = getattr(req_msg, "quoted_message", None)
                    if req_quote is not None:
                        if hasattr(req_quote, "model_dump"):
                            base["quoted_message"] = req_quote.model_dump(exclude_none=True)
                        elif hasattr(req_quote, "dict"):
                            base["quoted_message"] = req_quote.dict(exclude_none=True)
                        elif isinstance(req_quote, dict):
                            base["quoted_message"] = {k: v for k, v in req_quote.items() if v is not None}
                    # 透传隐藏标记：用于“重试软删除”消息持久化（DB 保留但 UI/上下文忽略）
                    base["isHidden"] = bool(getattr(req_msg, "isHidden", False))
                    base["sequence_number"] = idx
                    base["previous_message_id"] = char_convs[-1].get("message_id") if char_convs else None
                    char_convs.append(base)

                # 兼容极端情况：客户端未上传历史消息时，沿用数据库已有消息，避免误清空。
                if not char_convs:
                    char_convs = list(existing_messages)

            # 多角色并发回复的子请求会同时生成、依次保存。子请求携带的是父请求
            # 启动并发时的旧 messages；若继续把这份旧 messages 当作“当前会话真相源”，
            # 后保存的子请求会覆盖先保存的角色回复。这里仅对 multi-speaker child
            # 改为以 DB 最新会话为基底，再追加本子请求的 assistant。
            if (
                bool(getattr(request, "_normal_multi_speaker_child", False))
                and not persist_user_only
                and existing_messages
            ):
                char_convs = [dict(m) for m in existing_messages]

            last_user_msg = next(
                (
                    m for m in reversed(request.messages)
                    if m.role == "user" and not is_summary_placeholder_message(m)
                    and not _is_internal_trigger_message(request, m)
                ),
                None,
            )
            if last_user_msg and not getattr(request, "isHidden", False):
                user_content = last_user_msg.content
                user_timestamp = getattr(last_user_msg, "timestamp", None)
                user_msg_id = getattr(last_user_msg, "message_id", None)
                should_add_user = True
                if user_msg_id:
                    if next((m for m in char_convs if m.get("message_id") == user_msg_id), None):
                        should_add_user = False
                if should_add_user and char_convs:
                    last_conv_msg = char_convs[-1]
                    if last_conv_msg.get("role") == "user" and last_conv_msg.get("content") == user_content:
                        if user_timestamp and last_conv_msg.get("timestamp") and abs(user_timestamp - last_conv_msg.get("timestamp")) < 5000:
                            should_add_user = False
                if should_add_user:
                    new_seq = len(char_convs)
                    new_user_msg = {
                        "role": "user", "content": user_content, "timestamp": now_ts - 100,
                        "image_url": last_user_msg.image_url, "message_id": user_msg_id or generate_message_id(),
                        "sequence_number": new_seq, "previous_message_id": char_convs[-1].get("message_id") if char_convs else None
                    }
                    req_attachments = getattr(last_user_msg, "attachments", None)
                    if req_attachments is not None:
                        new_user_msg["attachments"] = [
                            a.model_dump(exclude_none=True) if hasattr(a, "model_dump")
                            else a.dict(exclude_none=True) if hasattr(a, "dict")
                            else a
                            for a in (req_attachments or [])
                        ]
                    req_quote = getattr(last_user_msg, "quoted_message", None)
                    if req_quote is not None:
                        if hasattr(req_quote, "model_dump"):
                            new_user_msg["quoted_message"] = req_quote.model_dump(exclude_none=True)
                        elif hasattr(req_quote, "dict"):
                            new_user_msg["quoted_message"] = req_quote.dict(exclude_none=True)
                        elif isinstance(req_quote, dict):
                            new_user_msg["quoted_message"] = {k: v for k, v in req_quote.items() if v is not None}
                    char_convs.append(new_user_msg)
            # 任意换行均拆分为独立气泡（与 normal_nonstream.py 保持一致）
            _full_clean = (clean_content or full_text or "").strip()
            _paragraphs = split_assistant_paragraphs(_full_clean)

            should_add_assistant = bool(_paragraphs)
            if should_add_assistant and bool(getattr(request, "_normal_internal_proactive_trigger", False)):
                source_message_id = str(
                    getattr(request, "_normal_internal_proactive_source_message_id", "") or ""
                ).strip()
                guard_reason = _normal_proactive_duplicate_guard_reason(
                    "\n\n".join(_paragraphs),
                    char_convs,
                    source_message_id=source_message_id,
                )
                if guard_reason:
                    logger.info(
                        "[NormalProactiveGuard] skip proactive persistence: %s user=%s char=%s conv=%s source=%s",
                        guard_reason,
                        request.username,
                        request.character_id,
                        conv_id[:12],
                        source_message_id[:12],
                    )
                    setattr(request, "_normal_internal_proactive_cancel_reason", guard_reason)
                    return False, guard_reason, None
            if should_add_assistant and char_convs and char_convs[-1].get("role") == "assistant":
                first_para = _paragraphs[0]
                last_content = char_convs[-1].get("content", "")
                if first_para and last_content and first_para[:100] == last_content[:100]:
                    if abs(now_ts - char_convs[-1].get("timestamp", 0)) < 10000:
                        should_add_assistant = False
            if not should_add_assistant:
                _paragraphs = []

            ai_msg_ids: list[str] = []
            ai_msg_meta: list[dict] = []
            asset_msg_ids: list[str] = []
            asset_msg_meta: list[dict] = []
            asset_msg_ids_by_request_id: dict[str, str] = {}
            _speaker_fields = speaker_message_fields(request)
            assistant_asset_by_request_id = getattr(request, "_assistant_asset_by_request_id", None) or {}
            assistant_asset_attachments = list(getattr(request, "_assistant_asset_attachments", None) or [])
            units = build_assistant_units(
                "\n".join(_paragraphs),
                reply_sequence=getattr(request, "_assistant_reply_sequence", None),
                attachment_by_request_id=assistant_asset_by_request_id,
                fallback_attachments=assistant_asset_attachments,
            )
            prev_id = char_convs[-1].get("message_id") if char_convs else None
            first_text = True
            for i, unit in enumerate(units):
                typ = unit.get("type")
                if typ == "text":
                    para = str(unit.get("content") or "").strip()
                    if not para:
                        continue
                    para_id = generate_message_id()
                    if first_text:
                        first_text = False
                    ai_msg_ids.append(para_id)
                    msg_ts = now_ts + i
                    msg_seq = len(char_convs)
                    assistant_msg: dict = {
                        "role": "assistant", "content": para, "rawContent": encode_language(para, getattr(request, "_normal_reply_language", None), getattr(request, "_normal_reply_voice", None)),
                        "timestamp": msg_ts, "model": model_name, "message_id": para_id,
                        "sequence_number": msg_seq,
                        "previous_message_id": prev_id,
                    }
                    if _speaker_fields:
                        assistant_msg.update(_speaker_fields)
                    meta_item = {
                        "message_id": para_id,
                        "timestamp": msg_ts,
                        "sequence_number": msg_seq,
                        "index": len(ai_msg_ids) - 1,
                    }
                    if _speaker_fields:
                        meta_item.update(_speaker_fields)
                    ai_msg_meta.append(meta_item)
                    if len(ai_msg_ids) == 1 and generation_duration_ms is not None:
                        assistant_msg["generation_duration_ms"] = generation_duration_ms
                    char_convs.append(assistant_msg)
                    prev_id = para_id
                elif typ == "asset":
                    attachment = unit.get("attachment")
                    if not isinstance(attachment, dict):
                        continue
                    asset_mid = generate_message_id()
                    asset_msg_ids.append(asset_mid)
                    msg_ts = now_ts + i
                    msg_seq = len(char_convs)
                    rid = str(unit.get("request_id") or (attachment.get("metadata") or {}).get("request_id") or "")
                    if rid:
                        asset_msg_ids_by_request_id[rid] = asset_mid
                    asset_meta_item = {
                        "message_id": asset_mid,
                        "timestamp": msg_ts,
                        "sequence_number": msg_seq,
                        "index": len(asset_msg_ids) - 1,
                        "request_id": rid or None,
                    }
                    if _speaker_fields:
                        asset_meta_item.update(_speaker_fields)
                    asset_msg_meta.append(asset_meta_item)
                    asset_msg = {
                        "role": "assistant",
                        "content": "",
                        "rawContent": "",
                        "timestamp": msg_ts,
                        "model": model_name,
                        "message_id": asset_mid,
                        "sequence_number": msg_seq,
                        "previous_message_id": prev_id,
                        "attachments": [attachment],
                    }
                    if _speaker_fields:
                        asset_msg.update(_speaker_fields)
                    char_convs.append(asset_msg)
                    prev_id = asset_mid
            db = get_database()
            await db.init()
            convs_dao = ConversationsDAO(db)
            conv_data = {
                "id": conv_id,
                "messages": char_convs,
                "timestamp": now_ts,
                "contextSummary": (matched_conv or {}).get("contextSummary") or (matched_conv or {}).get("summary") or "",
                "contextSummaryTime": (matched_conv or {}).get("contextSummaryTime") or (matched_conv or {}).get("timestamp"),
                "contextSummaryCutoffMessageId": (matched_conv or {}).get("contextSummaryCutoffMessageId"),
                "contextSummaryCutoffTimestamp": (matched_conv or {}).get("contextSummaryCutoffTimestamp"),
                "contextSummaryCutoffSequence": (matched_conv or {}).get("contextSummaryCutoffSequence"),
            }
            transaction_hook = getattr(request, "_autonomous_before_reply_commit", None)
            delivery_session = getattr(request, '_normal_delivery_session', None)
            if transaction_hook is not None or delivery_session is not None:
                request._autonomous_pending_reply_message_ids = tuple(ai_msg_ids + asset_msg_ids)
                async def commit_on_resolved_conversation(conn):
                    # DAO may select the user's canonical normal container.
                    # All lifecycle/task checks must target that actual write.
                    request.conversation_id = conv_data['id']
                    # The foreground Agent store is created before the DAO
                    # resolves the normal-chat canonical container.  Keep its
                    # scene/memory scope aligned with that resolved ID; without
                    # this, a later turn that supplies a new client ID can stage
                    # memory for a conversation that the DAO intentionally did
                    # not create, causing the whole reply transaction to fail.
                    memory_store = getattr(request, "_autonomous_memory_store", None)
                    if memory_store is not None:
                        memory_store.conversation_id = str(conv_data['id'])
                    if transaction_hook is not None:
                        await transaction_hook(conn)
                    if delivery_session is not None:
                        delivery_session.register(request, ai_msg_ids + asset_msg_ids, db.db_path)
                ok = await convs_dao.save_conversation(request.username, request.character_id, conv_data,
                                                      before_commit=commit_on_resolved_conversation)
            else:
                ok = await convs_dao.save_conversation(request.username, request.character_id, conv_data)
            if ok:
                conv_id = str(conv_data.get("id") or conv_id)
                request.conversation_id = conv_id
                logger.info(f"💾 [DB-AutoSave] 对话已持久化: {request.username}/{request.character_id}/{conv_id[:12]}...")
                setattr(request, "_assistant_message_meta", ai_msg_meta)
                setattr(request, "_assistant_asset_message_meta", asset_msg_meta)
                if asset_msg_ids:
                    setattr(request, "_assistant_asset_message_ids", asset_msg_ids)
                    setattr(request, "_assistant_asset_message_ids_by_request_id", asset_msg_ids_by_request_id)
                if should_add_assistant:
                    try:
                        from ..delivery_outbox import enqueue_chat_complete

                        defer_chat_complete = bool(getattr(request, "_defer_chat_complete_until_voice_ready", False))
                        chat_complete_items = []
                        for idx, para in enumerate(_paragraphs):
                            para_mid = ai_msg_ids[idx] if idx < len(ai_msg_ids) else (ai_msg_ids[-1] if ai_msg_ids else "")
                            if not para_mid:
                                continue
                            item = {
                                "username": request.username,
                                "character_id": request.character_id,
                                "conversation_id": conv_id,
                                "message_id": para_mid,
                                "preview": para.strip()[:500],
                                "mode": getattr(request, "mode", "normal") or "normal",
                                "completed_at_ms": now_ts + idx,
                            }
                            if defer_chat_complete:
                                chat_complete_items.append(item)
                            else:
                                await enqueue_chat_complete(**item)
                        if defer_chat_complete:
                            deferred = list(getattr(request, "_deferred_chat_complete_payloads", None) or [])
                            deferred.extend(chat_complete_items)
                            setattr(request, "_deferred_chat_complete_payloads", deferred)
                    except Exception as obe:
                        logger.debug(f"[outbox] chat_complete 跳过: {obe}")
                try:
                    from ..long_proactive import record_presence_from_saved_messages

                    await record_presence_from_saved_messages(
                        username=request.username,
                        character_id=request.character_id,
                        conversation_id=conv_id,
                        messages=char_convs,
                        relationship_stage=str(
                            (
                                getattr(request, "_normal_planner_result", None)
                                if isinstance(getattr(request, "_normal_planner_result", None), dict)
                                else {}
                            ).get("relationship_stage")
                            or ""
                        ) if (effective_speaker_character_id(request) or request.character_id) == request.character_id else "",
                    )
                except Exception as lpe:
                    logger.debug("[LongProactive] presence update skipped: %s", lpe)
                if getattr(request, "_normal_terminal_death_action", False) and should_add_assistant:
                    try:
                        from .normal_lifecycle import mark_normal_character_dead

                        await mark_normal_character_dead(
                            request.username,
                            request.character_id,
                            conv_id,
                            message_id=str(getattr(request, "_normal_terminal_death_message_id", "") or ""),
                            reason=str(
                                getattr(
                                    request,
                                    "_normal_terminal_death_reason",
                                    "terminal_death_reply_sent",
                                )
                                or "terminal_death_reply_sent"
                            ),
                        )
                        logger.info(
                            "[NormalLifecycle] marked character dead after terminal reply: user=%s char=%s conv=%s",
                            request.username,
                            request.character_id,
                            conv_id,
                        )
                    except Exception as lifecycle_err:
                        logger.warning(
                            "[NormalLifecycle] mark dead after terminal reply failed: %s",
                            lifecycle_err,
                        )
                asst = ai_msg_ids if should_add_assistant else None
                return True, "", asst
            return False, "数据库保存返回失败", None
    except Exception as e:
        logger.error(f"❌ [DB-AutoSave] 数据库保存失败: {e}")
        return False, str(e), None


async def persist_hidden_assistant_generation(
    request,
    model_name: str,
    full_text: str,
    gen_start_ms: int = 0,
    *,
    hidden_reason: str = "superseded_by_new_user_message",
) -> tuple[bool, str, list[str] | None]:
    """Append a superseded assistant result as hidden without rewriting visible history."""
    if not request.username or not request.character_id:
        return True, "", None
    clean_content = re.sub(r'<(?:think|thinking)>.*?</(?:think|thinking)>', '', full_text or "", flags=re.DOTALL).strip()
    paragraphs = split_assistant_paragraphs(clean_content)
    has_assets = bool(
        getattr(request, "_assistant_asset_by_request_id", None)
        or getattr(request, "_assistant_asset_attachments", None)
    )
    if not paragraphs and not has_assets:
        return True, "", None
    try:
        async with galgame_locker.acquire(request.username, request.character_id):
            db = get_database()
            await db.init()
            convs_dao = ConversationsDAO(db)
            existing_convs = await convs_dao.load_conversations(request.username, request.character_id)
            conv_id = str(getattr(request, "conversation_id", "") or "").strip()
            matched_conv = next((c for c in existing_convs if str(c.get("id") or "") == conv_id), None)
            if matched_conv is None:
                request_mids = {
                    str(getattr(m, "message_id", "") or "").strip()
                    for m in (getattr(request, "messages", None) or [])
                    if str(getattr(m, "message_id", "") or "").strip()
                }
                if request_mids:
                    matched_conv = max(
                        existing_convs,
                        key=lambda c: sum(
                            1
                            for m in (c.get("messages") or [])
                            if str(m.get("message_id") or "") in request_mids
                        ),
                        default=None,
                    )
                    if matched_conv and not any(
                        str(m.get("message_id") or "") in request_mids
                        for m in (matched_conv.get("messages") or [])
                    ):
                        matched_conv = None
            if matched_conv is None and existing_convs:
                matched_conv = existing_convs[0]
            if matched_conv is not None:
                conv_id = str(matched_conv.get("id") or conv_id)
            if not conv_id:
                conv_id = f"conv_{int(time.time()*1000)}"

            now_ts = int(time.time() * 1000)
            generation_duration_ms = (now_ts - gen_start_ms) if gen_start_ms > 0 else None
            char_convs = list((matched_conv or {}).get("messages") or [])
            existing_ids = {str(m.get("message_id") or "") for m in char_convs if m.get("message_id")}

            for req_msg in getattr(request, "messages", None) or []:
                if is_summary_placeholder_message(req_msg):
                    continue
                mid = str(getattr(req_msg, "message_id", "") or "").strip()
                if mid and mid in existing_ids:
                    continue
                if getattr(req_msg, "role", None) != "user":
                    continue
                item = {
                    "role": "user",
                    "content": getattr(req_msg, "content", None) or "",
                    "timestamp": getattr(req_msg, "timestamp", None) or (now_ts - 100),
                    "image_url": getattr(req_msg, "image_url", None),
                    "message_id": mid or generate_message_id(),
                    "sequence_number": len(char_convs),
                    "previous_message_id": char_convs[-1].get("message_id") if char_convs else None,
                }
                req_attachments = getattr(req_msg, "attachments", None)
                if req_attachments is not None:
                    item["attachments"] = [
                        a.model_dump(exclude_none=True) if hasattr(a, "model_dump")
                        else a.dict(exclude_none=True) if hasattr(a, "dict")
                        else a
                        for a in (req_attachments or [])
                    ]
                char_convs.append(item)
                existing_ids.add(str(item["message_id"]))

            assistant_asset_by_request_id = getattr(request, "_assistant_asset_by_request_id", None) or {}
            assistant_asset_attachments = list(getattr(request, "_assistant_asset_attachments", None) or [])
            units = build_assistant_units(
                "\n".join(paragraphs),
                reply_sequence=getattr(request, "_assistant_reply_sequence", None),
                attachment_by_request_id=assistant_asset_by_request_id,
                fallback_attachments=assistant_asset_attachments,
            )
            prev_id = char_convs[-1].get("message_id") if char_convs else None
            hidden_ids: list[str] = []
            text_idx = 0
            _speaker_fields = speaker_message_fields(request)
            for i, unit in enumerate(units):
                typ = unit.get("type")
                mid = generate_message_id()
                msg_ts = now_ts + i
                msg = {
                    "role": "assistant",
                    "content": "",
                    "rawContent": "",
                    "timestamp": msg_ts,
                    "model": model_name,
                    "message_id": mid,
                    "sequence_number": len(char_convs),
                    "previous_message_id": prev_id,
                    "isHidden": True,
                    "hidden_reason": hidden_reason,
                }
                if _speaker_fields:
                    msg.update(_speaker_fields)
                if typ == "text":
                    para = str(unit.get("content") or "").strip()
                    if not para:
                        continue
                    msg["content"] = para
                    msg["rawContent"] = para
                    if text_idx == 0 and generation_duration_ms is not None:
                        msg["generation_duration_ms"] = generation_duration_ms
                    text_idx += 1
                elif typ == "asset":
                    attachment = unit.get("attachment")
                    if not isinstance(attachment, dict):
                        continue
                    msg["attachments"] = [attachment]
                else:
                    continue
                char_convs.append(msg)
                hidden_ids.append(mid)
                prev_id = mid

            conv_data = {
                "id": conv_id,
                "messages": char_convs,
                "timestamp": now_ts,
                "contextSummary": (matched_conv or {}).get("contextSummary") or (matched_conv or {}).get("summary") or "",
                "contextSummaryTime": (matched_conv or {}).get("contextSummaryTime") or (matched_conv or {}).get("timestamp"),
                "contextSummaryCutoffMessageId": (matched_conv or {}).get("contextSummaryCutoffMessageId"),
                "contextSummaryCutoffTimestamp": (matched_conv or {}).get("contextSummaryCutoffTimestamp"),
                "contextSummaryCutoffSequence": (matched_conv or {}).get("contextSummaryCutoffSequence"),
            }
            ok = await convs_dao.save_conversation(request.username, request.character_id, conv_data)
            if ok:
                request.conversation_id = conv_id
                logger.info(
                    "💾 [DB-AutoSave] 已隐藏保存被新输入取代的回复: %s/%s/%s ids=%s",
                    request.username,
                    request.character_id,
                    conv_id[:12],
                    len(hidden_ids),
                )
                return True, "", hidden_ids or None
            return False, "数据库保存返回失败", None
    except Exception as e:
        logger.error("❌ [DB-AutoSave] 隐藏保存被取代回复失败: %s", e)
        return False, str(e), None

def get_smart_parameters(model_name: str, mode: str = "normal", model_id: str = None, endpoint: str = "") -> dict:
    params = {}
    if mode in ("galgame", "galgame_lock"):
        try:
            from ..reasoning_config import llm_task_float

            params["temperature"] = llm_task_float(mode, "temperature", 0.3) or 0.3
        except Exception:
            params["temperature"] = 0.3
        params["web_search"] = False
        logger.info("🚫 Galgame 模式：已禁用联网，基础温度来自软件层配置: %s", params["temperature"])
    else:
        is_qwen = "dashscope.aliyuncs.com" in (endpoint or "") or "qwen" in (model_name or "").lower()
        is_grok = "grok" in (model_name or "").lower()
        if is_grok:
            params["web_search"] = False
            logger.info("🚫 对话模式：Grok 模型已强制关闭联网搜索（成本控制）")
        elif is_qwen:
            params["web_search"] = True
            logger.info("🌐 对话模式：已启用联网（Qwen 官方 Responses API）")
        else:
            params["web_search"] = False
            logger.info("🚫 对话模式：该模型不支持联网，已关闭联网搜索")
    return params
