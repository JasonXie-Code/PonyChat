from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

from ..config import logger
from ..context_usage import (
    estimate_context_usage,
    CONTEXT_LIMIT_TOKENS,
    CONTEXT_SUMMARY_KEEP_RECENT_MESSAGES,
)
from ..db import ConversationsDAO, get_database
from ..utils import ChatMessage, ChatRequest


cancelled_generation_keys: Set[Tuple[str, str, str]] = set()
_generation_versions: Dict[Tuple[str, str, str], int] = {}

CRISIS_KEYWORDS = (
    "想死", "去死", "自杀", "结束生命", "不想活", "活不下去",
    "割腕", "跳楼", "轻生", "自残", "了结", "消失算了",
)
CRISIS_NOTICE = (
    "\n\n---\n💙 **温馨提示**：如果你正处于困难时期，请记得寻求帮助。"
    "**北京心理危机研究与干预中心**：010-82951332 | "
    "**全国心理援助热线**：400-161-9995"
)

BACKEND_CONTEXT_LIMIT_TOKENS = CONTEXT_LIMIT_TOKENS
KEEP_RECENT_MESSAGES = CONTEXT_SUMMARY_KEEP_RECENT_MESSAGES


def estimate_request_context_tokens(messages: List[ChatMessage]) -> int:
    usage = estimate_context_usage(messages=messages, source="chat_request")
    return int(usage.get("total_tokens") or 0)


def split_recent_messages(
    messages: List[ChatMessage],
    keep_recent_messages: int = KEEP_RECENT_MESSAGES,
) -> tuple[List[ChatMessage], List[ChatMessage]]:
    if not messages:
        return [], []
    if keep_recent_messages <= 0:
        return list(messages), []

    recent = list(messages[-keep_recent_messages:]) if len(messages) > keep_recent_messages else list(messages)
    older_count = max(0, len(messages) - len(recent))
    return list(messages[:older_count]), recent


def build_summary_prompt_from_request(request: ChatRequest) -> Optional[str]:
    summary_msgs = request.summary_messages or []
    if not summary_msgs:
        return None

    def _role_name(role: str) -> str:
        return "用户" if str(role or "").lower() == "user" else "角色"

    dialogue_content = "\n\n".join(
        f"{_role_name(getattr(m, 'role', ''))}: {str(getattr(m, 'content', '') or '')}"
        for m in summary_msgs
    )
    prev_summary = str(request.summary_prev_summary or "").strip()
    prev_summary_section = (
        f"【已有的历史摘要（请将其内容融入新摘要中）】\n{prev_summary}\n\n【新增对话内容如下】\n"
        if prev_summary else ""
    )

    scene_time_hint = str(request.summary_scene_time_hint or "").strip()
    is_galgame_mode = bool(request.summary_is_galgame_mode)
    is_lock_mode = bool(request.summary_is_lock_mode)

    time_rule_section = ""
    if is_galgame_mode:
        time_rule_section = (
            "【时间规则（必须遵守）】\n"
            "1) 严禁写入现实世界时间（如\"当前系统时间\"\"2026年xx月xx日\"\"星期几\"\"CST\"等）。\n"
            "2) 仅可使用剧情内场景时间描述（如\"清晨/午后/傍晚/深夜\"）。\n"
            "3) 若无法确定具体场景时间，请写\"以剧情推进为准\"，不要杜撰现实时钟。\n"
        )
        if scene_time_hint:
            time_rule_section += f"4) 当前可参考的场景时间：{scene_time_hint}\n"

    mode_hint = (
        f"当前为{'锁分模式' if is_lock_mode else '游戏模式'}，请按剧情世界观组织记忆，不要混入现实时间。"
        if is_galgame_mode
        else "当前为普通对话模式。"
    )

    return (
        "你是一个对话记忆提取专家。请对以下对话内容进行深度总结（2000字以内），"
        "保留所有关键人物设定、核心剧情进展、当前情感状态和待办事项。"
        "这份总结将作为角色后续记忆的唯一来源，请尽可能精炼且准确。\n\n"
        f"{mode_hint}\n"
        f"{time_rule_section}"
        f"{prev_summary_section}"
        f"对话内容如下：\n{dialogue_content}"
    )


def is_summary_placeholder_message(msg: ChatMessage) -> bool:
    if not msg or getattr(msg, "role", "") != "user":
        return False
    content = str(getattr(msg, "content", "") or "")
    return content.startswith("[以下是本对话之前内容的摘要")


def apply_summary_cutoff_to_messages(
    messages: List[ChatMessage],
    cutoff_message_id: Optional[str] = None,
    cutoff_timestamp: Optional[int] = None,
    cutoff_sequence: Optional[int] = None,
) -> List[ChatMessage]:
    if not messages:
        return []

    cutoff_idx = -1
    if cutoff_message_id:
        for i, m in enumerate(messages):
            if getattr(m, "message_id", None) and str(m.message_id) == str(cutoff_message_id):
                cutoff_idx = i
                break

    out: List[ChatMessage] = []
    for idx, m in enumerate(messages):
        if getattr(m, "isHidden", False):
            continue

        summarized = False
        if cutoff_idx >= 0:
            summarized = idx <= cutoff_idx
        elif cutoff_sequence is not None and getattr(m, "sequence_number", None) is not None:
            try:
                summarized = int(m.sequence_number) <= int(cutoff_sequence)
            except Exception:
                summarized = False
        elif cutoff_timestamp is not None and getattr(m, "timestamp", None):
            try:
                summarized = int(m.timestamp) <= int(cutoff_timestamp)
            except Exception:
                summarized = False
        else:
            summarized = bool(getattr(m, "isSummarized", False))

        if not summarized:
            out.append(m)
    return out


async def load_persisted_context_summary_state(
    username: Optional[str],
    character_id: Optional[str],
    mode: str,
    conversation_id: Optional[str],
) -> Dict[str, Any]:
    if not username or not character_id:
        return {}
    try:
        db = get_database()
        await db.init()
        conv_dao = ConversationsDAO(db)
        conversations = await conv_dao.load_conversations(username, character_id)
        target = None
        if conversation_id:
            target = next((c for c in conversations if c.get("id") == conversation_id), None)
        if not target and conversations:
            target = conversations[0]
        if not target:
            return {}
        return {
            "contextSummary": target.get("contextSummary") or target.get("summary") or "",
            "contextSummaryTime": target.get("contextSummaryTime") or target.get("timestamp"),
            "contextSummaryCutoffMessageId": target.get("contextSummaryCutoffMessageId"),
            "contextSummaryCutoffTimestamp": target.get("contextSummaryCutoffTimestamp"),
            "contextSummaryCutoffSequence": target.get("contextSummaryCutoffSequence"),
        }
    except Exception as e:
        logger.warning(f"⚠️ [ContextSummary] 读取后端摘要状态失败: {e}")
        return {}


async def apply_backend_context_summary_if_needed(request: ChatRequest) -> None:
    setattr(request, "_model_context_messages", [m.copy(deep=True) for m in (request.messages or [])])
    if request.is_summary_request or not request.messages:
        return

    state = await load_persisted_context_summary_state(
        username=request.username,
        character_id=request.character_id,
        mode=request.mode,
        conversation_id=getattr(request, "conversation_id", None),
    )
    summary_text = str(state.get("contextSummary") or "").strip()
    if not summary_text:
        return

    real_messages = [m for m in request.messages if not is_summary_placeholder_message(m)]
    filtered = apply_summary_cutoff_to_messages(
        real_messages,
        cutoff_message_id=state.get("contextSummaryCutoffMessageId"),
        cutoff_timestamp=state.get("contextSummaryCutoffTimestamp"),
        cutoff_sequence=state.get("contextSummaryCutoffSequence"),
    )
    has_cutoff = bool(
        state.get("contextSummaryCutoffMessageId")
        or state.get("contextSummaryCutoffTimestamp")
        or state.get("contextSummaryCutoffSequence") is not None
    )
    if not has_cutoff:
        visible = [m for m in real_messages if not getattr(m, "isHidden", False)]
        _, filtered = split_recent_messages(visible, KEEP_RECENT_MESSAGES)

    summary_msg = ChatMessage(
        role="user",
        content=f"[以下是本对话之前内容的摘要，请根据此记忆继续对话]\n\n{summary_text}",
        timestamp=state.get("contextSummaryTime"),
        message_id=None,
        sequence_number=None,
        previous_message_id=None,
        isHidden=True,
    )
    setattr(request, "_model_context_messages", [summary_msg, *[m.copy(deep=True) for m in filtered]])


def get_model_context_messages(request: ChatRequest) -> List[ChatMessage]:
    messages = getattr(request, "_model_context_messages", None)
    if isinstance(messages, list):
        return messages
    return list(request.messages or [])


def build_generation_key(username: str, character_id: str, client_id: str) -> Tuple[str, str, str]:
    return (str(username or ""), str(character_id or ""), str(client_id or "unknown"))


def begin_generation(username: str, character_id: str, client_id: str) -> int:
    key = build_generation_key(username, character_id, client_id)
    token = int(_generation_versions.get(key) or 0) + 1
    _generation_versions[key] = token
    cancelled_generation_keys.discard(key)
    return token


def retire_generation(username: str, character_id: str, client_id: str) -> int:
    key = build_generation_key(username, character_id, client_id)
    token = int(_generation_versions.get(key) or 0) + 1
    _generation_versions[key] = token
    cancelled_generation_keys.add(key)
    return token


def is_generation_current(username: str, character_id: str, client_id: str, token: int | None) -> bool:
    if token is None:
        return True
    key = build_generation_key(username, character_id, client_id)
    return int(_generation_versions.get(key) or 0) == int(token)


def mark_generation_cancelled(username: str, character_id: str, client_id: str) -> None:
    retire_generation(username, character_id, client_id)


def clear_generation_cancelled(username: str, character_id: str, client_id: str) -> None:
    cancelled_generation_keys.discard(build_generation_key(username, character_id, client_id))


def is_generation_cancelled(username: str, character_id: str, client_id: str) -> bool:
    return build_generation_key(username, character_id, client_id) in cancelled_generation_keys


def validate_message_sequence(messages: list, expected_sequence: int = None, last_message_id: str = None) -> dict:
    result = {
        "is_valid": True,
        "errors": [],
        "warnings": [],
        "duplicate_ids": set(),
        "missing_sequences": []
    }
    if not messages:
        return result

    seen_ids = set()
    last_id = None
    prev_seq = None
    for i, msg in enumerate(messages):
        msg_id = getattr(msg, "message_id", None) if hasattr(msg, "message_id") else msg.get("message_id")
        seq_num = getattr(msg, "sequence_number", None) if hasattr(msg, "sequence_number") else msg.get("sequence_number")
        prev_id = getattr(msg, "previous_message_id", None) if hasattr(msg, "previous_message_id") else msg.get("previous_message_id")

        if msg_id:
            if msg_id in seen_ids:
                result["duplicate_ids"].add(msg_id)
                result["warnings"].append(f"重复的消息ID: {msg_id} (索引 {i})")
            seen_ids.add(msg_id)

        if seq_num is not None:
            # 允许序号存在缺口（例如隐藏消息/摘要裁剪后发送的是可见消息子集），
            # 但必须保持严格递增，防止乱序或回退。
            if prev_seq is not None and seq_num <= prev_seq:
                result["warnings"].append(f"消息 #{i} 序号非递增: 前一条 {prev_seq}, 当前 {seq_num}")
            prev_seq = seq_num

        if i > 0 and prev_id and prev_id != last_id:
            result["warnings"].append(f"消息 #{i} 的 previous_message_id 不匹配")

        last_id = msg_id

    if expected_sequence is not None and len(messages) != expected_sequence:
        result["warnings"].append(f"消息数量不匹配: 期望 {expected_sequence}, 实际 {len(messages)}")
    if last_message_id and last_id and last_message_id != last_id:
        result["warnings"].append(f"最后消息ID不匹配: 期望 {last_message_id}, 实际 {last_id}")
    if result["duplicate_ids"]:
        result["is_valid"] = False
        result["errors"].append("存在重复的消息ID")
    return result


def deduplicate_messages(messages: list) -> list:
    seen_ids = set()
    unique_messages = []
    for msg in messages:
        msg_id = msg.get("message_id") if isinstance(msg, dict) else getattr(msg, "message_id", None)
        if msg_id:
            if msg_id in seen_ids:
                logger.info(f"🔒 [消息校验] 去除重复消息: {msg_id}")
                continue
            seen_ids.add(msg_id)
        unique_messages.append(msg)
    return unique_messages


def fix_message_validation(messages: list, generate_message_id) -> list:
    fixed_messages = []
    previous_id = None
    for i, msg in enumerate(messages):
        if isinstance(msg, dict):
            fixed_msg = msg.copy()
        else:
            fixed_msg = msg.dict() if hasattr(msg, "dict") else dict(msg)

        if not fixed_msg.get("message_id"):
            fixed_msg["message_id"] = generate_message_id()
        if not fixed_msg.get("timestamp"):
            fixed_msg["timestamp"] = int(time.time() * 1000) - (len(messages) - i) * 1000
        fixed_msg["sequence_number"] = i
        fixed_msg["previous_message_id"] = previous_id
        previous_id = fixed_msg["message_id"]
        fixed_messages.append(fixed_msg)
    return fixed_messages
