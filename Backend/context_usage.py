import json
import logging
import re
from typing import Any, Optional

from .utils import estimate_tokens
from .reasoning_config import llm_task_int

logger = logging.getLogger(__name__)

CONTEXT_LIMIT_TOKENS = llm_task_int("normal_main_reply", "context_limit_tokens", 64000) or 64000
CONTEXT_SUMMARY_KEEP_RECENT_MESSAGES = 12
_THINK_REGEX = re.compile(r"<(?:think|thinking)>[\s\S]*?</(?:think|thinking)>", re.IGNORECASE)

# build_galgame_messages 已去掉轮数硬限，此常量仅供估算函数内参考（不再截断历史）
_GALGAME_KEEP_FULL_SCENE_TURNS = 2


def _get_value(msg: Any, key: str, default: Any = None) -> Any:
    if isinstance(msg, dict):
        return msg.get(key, default)
    return getattr(msg, key, default)


def estimate_context_usage(
    messages: list,
    context_summary: str = "",
    cutoff_message_id: Optional[str] = None,
    cutoff_timestamp: Optional[int] = None,
    cutoff_sequence: Optional[int] = None,
    source: Optional[str] = None,
) -> dict:
    msgs = messages if isinstance(messages, list) else []

    cutoff_idx = -1
    if cutoff_message_id:
        for i, m in enumerate(msgs):
            mid = _get_value(m, "message_id")
            if mid and str(mid) == str(cutoff_message_id):
                cutoff_idx = i
                break

    if source == "conversation_detail":
        _method = (
            f"message_id({cutoff_idx}/{len(msgs)})" if cutoff_idx >= 0
            else f"sequence(<={cutoff_sequence})" if cutoff_sequence is not None
            else f"timestamp(<={cutoff_timestamp})" if cutoff_timestamp is not None
            else "isSummarized(field)"
        )
        _has_summary = bool(str(context_summary or "").strip())
        logger.info(
            "📊 [CtxUsage] src=%s msgs=%d cutoff_id=%s cutoff_seq=%s cutoff_ts=%s "
            "-> method=%s has_summary=%s",
            source, len(msgs),
            str(cutoff_message_id or "")[:12] or "None",
            cutoff_sequence, cutoff_timestamp,
            _method, _has_summary,
        )

    normalized = []
    for idx, m in enumerate(msgs):
        if _get_value(m, "isHidden") or _get_value(m, "is_hidden"):
            continue

        summarized = False
        if cutoff_idx >= 0:
            summarized = idx <= cutoff_idx
        elif cutoff_sequence is not None and _get_value(m, "sequence_number") is not None:
            try:
                summarized = int(_get_value(m, "sequence_number")) <= int(cutoff_sequence)
            except Exception:
                summarized = False
        elif cutoff_timestamp is not None and _get_value(m, "timestamp") is not None:
            try:
                summarized = int(_get_value(m, "timestamp")) <= int(cutoff_timestamp)
            except Exception:
                summarized = False
        else:
            summarized = bool(_get_value(m, "isSummarized", False))
        if summarized:
            continue

        role = str(_get_value(m, "role", "user"))
        content = _get_value(m, "content", "")
        if role == "assistant":
            raw_content = _get_value(m, "rawContent") or _get_value(m, "raw_content")
            if isinstance(raw_content, str) and raw_content.strip():
                content = _THINK_REGEX.sub("", raw_content).strip()

        normalized.append({"role": role, "content": content})

    summary_text = str(context_summary or "").strip()
    if summary_text:
        normalized.insert(0, {
            "role": "user",
            "content": f"[以下是本对话之前内容的摘要，请根据此记忆继续对话]\n\n{summary_text}"
        })

    total_tokens = estimate_tokens(normalized)
    usage = {
        "total_tokens": total_tokens,
        "limit_tokens": CONTEXT_LIMIT_TOKENS,
    }
    if source:
        usage["source"] = source
        logger.info(
            "📊 [CtxUsage] src=%s result: %d/%d tokens (active_msgs=%d summary=%s)",
            source, total_tokens, CONTEXT_LIMIT_TOKENS,
            len(normalized) - (1 if bool(str(context_summary or "").strip()) else 0),
            "yes" if bool(str(context_summary or "").strip()) else "no",
        )
    return usage


def _truncate_galgame_scene_json(raw_json: str, keep_full: bool) -> str:
    """
    模拟 _normalize_galgame_assistant_history 对 assistant JSON 的精简。

    keep_full=True  → 最近 2 轮：移除 suggested_options 和 _strategy_analysis
    keep_full=False → 旧轮：scene 只保留 time/location/response，其余大段文本字段删除
    """
    try:
        parsed = json.loads(raw_json, strict=False)
    except Exception:
        return raw_json
    if not isinstance(parsed, dict):
        return raw_json

    parsed.pop("suggested_options", None)
    parsed.pop("_strategy_analysis", None)

    if not keep_full:
        scene = parsed.get("scene")
        if isinstance(scene, dict):
            parsed["scene"] = {k: scene[k] for k in ("time", "location", "response") if k in scene}

    return json.dumps(parsed, ensure_ascii=False)


def _extract_prev_scene_from_last_assistant(visible: list) -> tuple[str, str]:
    """从最后一条 assistant 消息提取 env+thoughts 与 response，供 galgame system prompt 估算。"""
    prev_env_thoughts = ""
    prev_response = ""
    for m in reversed(visible):
        if str(_get_value(m, "role", "")) != "assistant":
            continue
        raw = _get_value(m, "rawContent") or _get_value(m, "raw_content") or ""
        if not isinstance(raw, str) or not raw.strip():
            continue
        clean = _THINK_REGEX.sub("", raw).strip()
        json_match = re.search(r"\{[\s\S]*\}", clean)
        if not json_match:
            continue
        try:
            data = json.loads(json_match.group(0), strict=False)
        except Exception:
            continue
        if isinstance(data, dict):
            scene = data.get("scene") or {}
            env = str(scene.get("env") or "").strip()
            thoughts = str(scene.get("thoughts") or "").strip()
            prev_env_thoughts = (env + "\n" + thoughts).strip()
            prev_response = str(scene.get("response") or "").strip()
        break
    return prev_env_thoughts, prev_response


def estimate_galgame_context_usage(
    messages: list,
    context_summary: str = "",
    cutoff_message_id: Optional[str] = None,
    cutoff_timestamp: Optional[int] = None,
    cutoff_sequence: Optional[int] = None,
    system_prompt: str = "",
    mode: str = "galgame_lock",
    score: int = 40,
    source: Optional[str] = None,
) -> dict:
    """
    游戏/锁分模式专用上下文 token 估算。

    与通用 estimate_context_usage 相比，额外模拟了实际请求（build_galgame_messages）
    的裁剪与完整 system prompt，使估算值与实际发送给模型的 token 数一致：

    1. **摘要截断**：有摘要时过滤截断点之前的消息，前置摘要占位消息；无摘要时使用全量历史。
    2. **旧轮 scene 精简**：超出最近 2 轮的 assistant JSON，scene 只保留 time/location/response。
    3. **完整 galgame system prompt**：叠加 galgame 规则模板 + 角色设定，与 service 实际 payload 一致。
    """
    msgs = messages if isinstance(messages, list) else []

    # ── 1. 定位摘要截断边界 ───────────────────────────────────────────────────
    cutoff_idx = -1
    if cutoff_message_id:
        for i, m in enumerate(msgs):
            mid = _get_value(m, "message_id")
            if mid and str(mid) == str(cutoff_message_id):
                cutoff_idx = i
                break

    # ── 2. 过滤隐藏消息 + 排除已被摘要裁剪的消息 ────────────────────────────
    visible: list = []
    for idx, m in enumerate(msgs):
        if _get_value(m, "isHidden") or _get_value(m, "is_hidden"):
            continue
        summarized = False
        if cutoff_idx >= 0:
            summarized = idx <= cutoff_idx
        elif cutoff_sequence is not None and _get_value(m, "sequence_number") is not None:
            try:
                summarized = int(_get_value(m, "sequence_number")) <= int(cutoff_sequence)
            except Exception:
                pass
        elif cutoff_timestamp is not None and _get_value(m, "timestamp") is not None:
            try:
                summarized = int(_get_value(m, "timestamp")) <= int(cutoff_timestamp)
            except Exception:
                pass
        else:
            summarized = bool(_get_value(m, "isSummarized", False))
        if not summarized:
            visible.append(m)

    visible_total = len(visible)

    # ── 3. 若有摘要，在可见消息列表最前插入摘要占位消息（与 build_galgame_messages 一致）──
    if context_summary:
        _summary_placeholder = {"role": "user", "content": f"[以下是本对话之前内容的摘要，请根据此记忆继续对话]\n\n{context_summary}"}
        visible = [_summary_placeholder] + visible

    # ── 4. 识别 assistant JSON 消息，确定哪些轮次需要 scene 精简 ─────────────
    assistant_json_indices: list[int] = []
    for i, m in enumerate(visible):
        if str(_get_value(m, "role", "")) != "assistant":
            continue
        raw = (
            _get_value(m, "rawContent")
            or _get_value(m, "raw_content")
            or _get_value(m, "content")
            or ""
        )
        if isinstance(raw, str):
            raw = _THINK_REGEX.sub("", raw).strip()
        if raw.startswith("{") and raw.endswith("}"):
            try:
                json.loads(raw, strict=False)
                assistant_json_indices.append(i)
            except Exception:
                pass

    # 超出最近 _KEEP_FULL_SCENE_TURNS 轮的 assistant JSON 做旧轮精简
    truncate_set = (
        set(assistant_json_indices[:-_GALGAME_KEEP_FULL_SCENE_TURNS])
        if len(assistant_json_indices) > _GALGAME_KEEP_FULL_SCENE_TURNS
        else set()
    )

    # ── 5. 构建估算用消息列表 ────────────────────────────────────────────────
    normalized: list = []
    for i, m in enumerate(visible):
        role = str(_get_value(m, "role", "user"))
        raw = _get_value(m, "rawContent") or _get_value(m, "raw_content") or ""
        content = _get_value(m, "content", "") or ""
        if role == "assistant":
            if isinstance(raw, str) and raw.strip():
                content = _THINK_REGEX.sub("", raw).strip()
            if content.startswith("{") and content.endswith("}"):
                content = _truncate_galgame_scene_json(content, keep_full=(i not in truncate_set))
        normalized.append({"role": role, "content": content})

    # 摘要占位已在步骤 3 注入 visible 并进入 normalized，此处勿重复插入

    # ── 6. 累计 token（含 system）────
    total_tokens = estimate_tokens(normalized)
    if system_prompt:
        total_tokens += estimate_tokens([{"role": "system", "content": str(system_prompt)}])

    usage = {
        "total_tokens": total_tokens,
        "limit_tokens": CONTEXT_LIMIT_TOKENS,
    }
    if source:
        usage["source"] = source
        logger.info(
            "📊 [GalgameCtxUsage] src=%s result: %d/%d tokens "
            "(visible=%d→capped=%d assistant_json=%d truncated=%d summary=%s sys=%s)",
            source, total_tokens, CONTEXT_LIMIT_TOKENS,
            visible_total, len(visible),
            len(assistant_json_indices), len(truncate_set),
            "yes" if str(context_summary or "").strip() else "no",
            "yes" if system_prompt else "no",
        )
    return usage
