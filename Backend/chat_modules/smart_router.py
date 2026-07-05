"""
智能模型路由：for_chat_router 模型（当前为 DeepSeek 非思考）分类对话氛围；豆包作联网搜索工具。
所有 LLM 往返经 save_chat_debug_log 落盘（var/.chatlogs），供 ChatMonitor 同步。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from ..config import logger, model_manager
from ..providers.llm_call import call_llm_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..reasoning_policy import resolve_software_reasoning_policy
from ..utils import save_chat_debug_log

_CLASSIFIER_SYSTEM = """你是对话路由器。只根据给出的最近若干条 user/assistant 对话，判断：
1) web_search：用户是否明确需要**实时外部信息**（新闻、天气、股价、赛事、当前时间地点事实、"今天/最新"等）；日常情感闲聊、虚构角色扮演不需要联网则为 false。
2) search_query：若 web_search 为 true，给出**中文或英文关键词**，只保留事实检索词；若不需要搜索则为 null。

**只输出一行合法 JSON**，键名与类型固定，禁止 markdown、禁止解释：
{"web_search": true/false, "search_query": "关键词或null"}
"""


def _strip_code_fence(text: str) -> str:
    s = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s


def _parse_router_json(text: str) -> Dict[str, Any]:
    raw = _strip_code_fence(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 尝试截取首尾花括号
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            data = json.loads(raw[i : j + 1])
        else:
            raise
    return data


def _message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") in ("text", "input_text"):
                parts.append(str(p.get("text") or ""))
            elif p.get("type") == "image_url":
                parts.append("[图片]")
        return " ".join(parts)
    return str(content)


def _recent_to_blocks(recent_messages: List[dict]) -> str:
    lines: List[str] = []
    for m in recent_messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role") or ""
        if role not in ("user", "assistant"):
            continue
        text = _message_text(m.get("content"))
        if not text.strip():
            continue
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


def default_router_result() -> Dict[str, Any]:
    """冷启动或无历史时的兜底。"""
    return {"web_search": False, "search_query": None}


async def classify_conversation(
    recent_messages: List[dict],
    router_cfg: dict,
    *,
    username: Optional[str] = None,
    character_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    调用 for_chat_router 模型（DeepSeek 非思考）输出 JSON。
    recent_messages: 仅 user/assistant，建议最多 6 条（≤3 轮）。
    """
    if not router_cfg or not router_cfg.get("api_key"):
        logger.warning("[SmartRouter] 无 chat_router 模型配置，使用默认分类结果")
        return default_router_result()

    blocks = _recent_to_blocks(recent_messages)
    if not blocks.strip():
        return default_router_result()

    model_name = router_cfg.get("model_name") or "deepseek-v4-flash"
    reasoning_policy = resolve_software_reasoning_policy(
        "smart_router_classify",
        model_name=model_name,
        mode="chat_router",
        active_model=router_cfg,
        endpoint=router_cfg.get("endpoint", ""),
    )
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _CLASSIFIER_SYSTEM},
            {"role": "user", "content": f"【对话片段】\n{blocks}"},
        ],
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "smart_router_classify")

    try:
        from ..providers.llm_call import call_llm_payload

        try:
            _cls = await call_llm_payload(
                payload,
                router_cfg,
                task="classify",
                timeout=llm_task_float("smart_router_classify", "timeout_seconds", 45.0) or 45.0,
                reasoning_policy=reasoning_policy,
                chat_debug_request={
                    "username": username,
                    "character_id": character_id,
                    "mode": "chat_router",
                    "model_name": model_name,
                    "stage": "REQUEST",
                },
                record_usage="main",
                usage_meter_username=username,
            )
        except httpx.HTTPStatusError as e:
            _code = e.response.status_code if e.response is not None else 0
            _txt = (e.response.text if e.response is not None else "") or ""
            await save_chat_debug_log(
                username,
                character_id,
                "chat_router",
                model_name,
                _txt,
                f"ERROR_{_code}",
            )
            logger.warning("[SmartRouter] 分类器 HTTP %s", _code)
            return default_router_result()
        text = (_cls.text or "").strip()
        parsed = _parse_router_json(text)
        web = bool(parsed.get("web_search"))
        sq = parsed.get("search_query")
        if sq is not None and not isinstance(sq, str):
            sq = str(sq) if sq else None
        if isinstance(sq, str):
            sq = sq.strip() or None
        if web and not sq:
            logger.info("[SmartRouter] web_search=true 但无 search_query，视为不搜索")
            web = False
        return {
            "web_search": web,
            "search_query": sq if web else None,
        }
    except Exception as e:
        logger.warning("[SmartRouter] 分类失败: %s", e)
        await save_chat_debug_log(
            username, character_id, "chat_router", model_name, str(e), "ERROR"
        )
        return default_router_result()


_SEARCH_SYSTEM = (
    "你是联网搜索摘要助手。根据用户给出的搜索关键词，利用联网能力检索并**只用客观短句**总结与关键词最相关的事实"
    "（日期、数字、结论），勿编造；勿输出成人或色情内容；勿使用 Markdown。"
    "若无法检索到有效信息，明确说「未查到可靠结果」。"
    "\n\n最后执行要求：直接输出可交给下一阶段使用的搜索摘要，不要解释你的检索过程。"
)


async def run_web_search(
    search_query: str,
    doubao_cfg: Optional[dict] = None,
    *,
    username: Optional[str] = None,
    character_id: Optional[str] = None,
    debug_mode: str = "web_search",
    debug_stage: str = "REQUEST",
    debug_role_params: Optional[dict] = None,
) -> str:
    """调用豆包 mini（联网工具），返回纯文本摘要。"""
    cfg = doubao_cfg or model_manager.get_model_for_task("web_search")
    if not cfg or not cfg.get("api_key"):
        logger.warning("[SmartRouter] 无豆包联网配置，跳过搜索")
        return ""

    q = (search_query or "").strip()
    if not q:
        return ""

    model_id = cfg.get("model_name") or ""
    reasoning_policy = resolve_software_reasoning_policy(
        "web_search",
        model_name=model_id,
        mode="web_search",
        active_model=cfg,
        endpoint=cfg.get("endpoint", ""),
        requested_enabled=False,
        requested_effort="minimal",
    )

    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": _SEARCH_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"【搜索关键词】\n{q}\n\n"
                    "【本阶段任务】\n"
                    "联网检索后，只输出与关键词最相关的客观短句摘要，供普通对话 Step 3 主回复使用。"
                ),
            },
        ],
        "stream": False,
        "web_search": True,
    }
    apply_llm_task_payload_config(payload, "web_search")

    try:
        result = await call_llm_payload(
            payload,
            cfg,
            task="web_search",
            timeout=llm_task_float("web_search", "timeout_seconds", 90.0) or 90.0,
            reasoning_policy=reasoning_policy,
            chat_debug_request={
                "username": username,
                "character_id": character_id,
                "mode": (debug_mode or "web_search").strip() or "web_search",
                "model_name": model_id,
                "stage": (debug_stage or "REQUEST").strip() or "REQUEST",
                "params": debug_role_params,
            },
            record_usage="main",
            usage_meter_username=username,
        )
        return (result.text or "").strip()
    except Exception as e:
        logger.warning("[SmartRouter] 联网搜索失败: %s", e)
        await save_chat_debug_log(
            username,
            character_id,
            (debug_mode or "web_search").strip() or "web_search",
            model_id,
            str(e),
            f"{(debug_stage or 'REQUEST').strip() or 'REQUEST'}_ERROR",
            params=debug_role_params,
        )
        return ""


def augment_system_prompt_for_router(
    messages: List[dict],
    router_result: Dict[str, Any],
    search_context: str,
) -> None:
    """将联网摘要写入首条 system 消息（原地修改 messages）。"""
    sc = (search_context or "").strip()
    if not sc:
        return
    blob = "【联网检索摘要（供参考，非用户原文）】\n" + sc
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "system":
            continue
        c = m.get("content")
        if isinstance(c, str):
            m["content"] = c.rstrip() + "\n\n" + blob
        return
    messages.insert(0, {"role": "system", "content": blob})
