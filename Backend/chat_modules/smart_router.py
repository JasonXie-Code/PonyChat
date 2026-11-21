"""
智能模型路由：DeepSeek 视觉模型以 low 思考模式分类对话氛围；联网能力由模型清单显式声明。
所有 LLM 往返经 save_chat_debug_log 落盘（var/.chatlogs），供 ChatMonitor 同步。
"""

from __future__ import annotations

from .Prompts import SMART_ROUTER_SEARCH_SYSTEM

from typing import Any, Dict, Optional

from ..config import logger, model_manager
from ..providers.llm_call import call_llm_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..reasoning_policy import resolve_software_reasoning_policy
from ..utils import save_chat_debug_log



async def run_web_search(
    search_query: str,
    model_cfg: Optional[dict] = None,
    *,
    username: Optional[str] = None,
    character_id: Optional[str] = None,
    debug_mode: str = "web_search",
    debug_stage: str = "REQUEST",
    debug_role_params: Optional[dict] = None,
) -> str:
    """调用具备联网能力的模型，返回纯文本摘要。"""
    cfg = model_cfg or model_manager.get_model_for_task("web_search")
    if not cfg or not cfg.get("api_key"):
        logger.warning("[SmartRouter] 无联网配置，跳过搜索")
        return ""

    if not cfg.get("supports_web_search"):
        return "当前未配置实时联网检索工具；不能声称已检索或提供已核实的实时信息。"

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
            {"role": "system", "content": SMART_ROUTER_SEARCH_SYSTEM},
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
