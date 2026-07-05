"""
Galgame 分步 / 记忆摘要：与 chat_modules.service 中 galgame、galgame_lock 主对话
一致的思考策略与 payload 字段（关思考、DeepSeek V4 `thinking`、非 V4 的 reasoning_effort），
再经 `call_llm_payload` + `reasoning_policy` 下发，避免各处分叉。

- `reasoning_mode=disabled`（默认）：分步/记忆 — 与主对话游戏模式一致，强制关思考。
- `reasoning_mode=enabled`：第 1 步导演在配置开启思考时 — 用 `normal` 解析思考策略，并设 `enable_thinking=True`。
"""

from __future__ import annotations

import copy
from typing import Any, Literal, Optional

import httpx

from ..providers.base import LLMResponse
from ..providers.llm_call import call_llm_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..reasoning_policy import ReasoningPolicy, resolve_software_reasoning_policy


def _reasoning_task_from_stage(stage: str | None, mode: str) -> str:
    s = str(stage or "").upper()
    if "SEQ_STEP_1_DIRECTOR" in s:
        return "galgame_seq_step_1_director"
    if "SEQ_STEP_2_VITALS" in s:
        return "galgame_seq_step_2_vitals"
    if "SEQ_STEP_8_JSON" in s:
        return "galgame_seq_step_8_json"
    if "SEQ_STEP_9_OPTIONS" in s:
        return "galgame_seq_step_9_options"
    if "SEQ_STEP_10" in s:
        return "galgame_seq_step_10_memory"
    if "SEQ_STEP_7_RESPONSE" in s:
        return "galgame_seq_step_7_response"
    if any(f"SEQ_STEP_{i}_" in s for i in range(3, 8)):
        return "galgame_seq_step_3_7_text"
    if str(mode) in ("galgame", "galgame_lock"):
        return str(mode)
    return "galgame_seq_default"


def _galgame_patched_model_cfg(active_model: dict, mode: str) -> dict:
    if str(mode) in ("galgame", "galgame_lock"):
        return {**active_model, "enable_thinking": False}
    return active_model


def prepare_galgame_sequential_payload(
    payload: dict,
    model_name: str,
    mode: str,
    active_model: dict,
    *,
    configured_reasoning_effort: str = "high",
    reasoning_mode: Literal["disabled", "enabled"] = "disabled",
    director_reasoning_effort: Optional[str] = None,
    reasoning_task: str = "",
) -> tuple[dict, ReasoningPolicy, dict]:
    """
    对齐 service 在 galgame/锁分 下对 reasoning_policy 与 body 的构造（不添加 response_format、不经 build_payload）。
    第三项为传给 `call_llm_payload` 的 model_cfg（`disabled` 时 galgame 模式含 enable_thinking=False；
    `enabled` 时为 enable_thinking=True 以便 resolve 出开启思考策略）。
    """
    out = copy.deepcopy(payload)
    ep = str(active_model.get("endpoint") or "")
    model_name_lower = (model_name or "").lower()
    endpoint_lower = ep.lower()
    is_doubao_model = "ark.cn-beijing.volces.com" in endpoint_lower or any(
        k in model_name_lower for k in ("doubao", "seed")
    )

    mname = str(model_name or "").strip() or (
        (active_model.get("model_name") or active_model.get("id") or "")
    )

    requested_enabled = reasoning_mode == "enabled"
    eff_in = str(director_reasoning_effort or configured_reasoning_effort or "high").strip() or "high"
    task_key = reasoning_task or "galgame_seq_default"
    apply_llm_task_payload_config(out, task_key, output_token_field="max_tokens")
    am = {**active_model, "enable_thinking": requested_enabled}
    if not requested_enabled:
        am = _galgame_patched_model_cfg(am, mode)
    rp = resolve_software_reasoning_policy(
        task_key,
        mname,
        active_model=am,
        endpoint=ep,
        mode=str(mode) or "galgame",
        requested_enabled=requested_enabled,
        requested_effort=eff_in,
    )
    if is_doubao_model and rp.thinking_type == "disabled":
        rp.reasoning_effort = None
        rp.effort = None

    if rp.is_deepseek_v4:
        t = rp.thinking_type or "disabled"
        out["thinking"] = {"type": t}
        if t == "enabled" and rp.deepseek_v4_api_reasoning_effort:
            out["reasoning_effort"] = rp.deepseek_v4_api_reasoning_effort
        else:
            out.pop("reasoning_effort", None)
    target_effort = rp.effort
    if (not rp.is_deepseek_v4) and any(
        k in model_name_lower
        for k in ("o1", "thinking", "doubao", "seed", "grok", "gemini")
    ):
        if target_effort:
            out["reasoning_effort"] = target_effort

    return out, rp, am


async def call_llm_galgame_sequential(
    payload: dict,
    active_model: dict,
    *,
    mode: str,
    model_name: str,
    httpx_client: httpx.AsyncClient,
    timeout: float,
    chat_debug_request: Optional[dict[str, Any]] = None,
    reasoning_mode: Literal["disabled", "enabled"] = "disabled",
    director_reasoning_effort: Optional[str] = None,
    configured_reasoning_effort: str = "high",
    **llm_extras: Any,
) -> LLMResponse:
    reasoning_task = _reasoning_task_from_stage(
        (chat_debug_request or {}).get("stage") if isinstance(chat_debug_request, dict) else None,
        mode,
    )
    p2, rp, am = prepare_galgame_sequential_payload(
        payload,
        model_name,
        mode,
        active_model,
        configured_reasoning_effort=configured_reasoning_effort,
        reasoning_mode=reasoning_mode,
        director_reasoning_effort=director_reasoning_effort,
        reasoning_task=reasoning_task,
    )
    task_timeout = llm_task_float(reasoning_task, "timeout_seconds", float(timeout)) or float(timeout)
    return await call_llm_payload(
        p2,
        am,
        task=mode,
        httpx_client=httpx_client,
        timeout=task_timeout,
        chat_debug_request=chat_debug_request,
        reasoning_policy=rp,
        **llm_extras,
    )
