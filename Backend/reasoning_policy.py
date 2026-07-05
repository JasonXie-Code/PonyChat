from dataclasses import dataclass
from typing import Optional
import logging

from .reasoning_config import (
    coerce_driver_depth,
    get_reasoning_driver,
    get_software_reasoning,
)


logger = logging.getLogger(__name__)


@dataclass
class ReasoningPolicy:
    # Chat Completions 兼容参数
    effort: Optional[str] = None  # minimal/low/medium/high
    # Responses API（豆包等）或 DeepSeek V4 thinking.type
    thinking_type: Optional[str] = None  # enabled/disabled
    reasoning_effort: Optional[str] = None  # minimal/low/medium/high（豆包等）
    # DeepSeek V4 /chat/completions：单模型 + thinking + 顶层 reasoning_effort（仅 high|max）
    is_deepseek_v4: bool = False
    deepseek_v4_api_reasoning_effort: Optional[str] = None  # "high" | "max"；思考关闭时为 None


def _normalize_effort(effort: Optional[str]) -> str:
    v = str(effort or "").strip().lower()
    if v in ("minimal", "low", "medium", "high"):
        return v
    return "high"


def _normalize_effort_for_model(
    model_name: str,
    active_model: Optional[dict],
    endpoint: str,
    requested_effort: Optional[str],
) -> str:
    _, driver = get_reasoning_driver(model_name, active_model, endpoint)
    return coerce_driver_depth(driver, requested_effort) or _normalize_effort(requested_effort)


def is_deepseek_v4_model(
    active_model: Optional[dict], model_name: str, endpoint: str
) -> bool:
    am = active_model or {}
    if bool(am.get("uses_v4_thinking_api")):
        return True
    ep = (endpoint or "").lower()
    mn = (model_name or "").lower()
    return "api.deepseek.com" in ep and mn == "deepseek-v4-flash"


def map_ds_v4_api_reasoning_effort(raw: Optional[str]) -> str:
    v = str(raw or "high").strip().lower()
    return "max" if v == "max" else "high"


def _resolve_proactive_policy(model_name: str, am: dict, ep: str) -> ReasoningPolicy:
    """
    主动消息：只产出一条短句，必须关闭「思考/推理链」。
    否则 max_output_tokens 会被 reasoning 占满，正文无法输出（见 ChatMonitor proactive 仅 reasoning、incomplete）。
    覆盖：DeepSeek V4、豆包/Seed 等；与主对话的 galgame 强制关思考语义一致（仅作用域不同）。
    """
    if is_deepseek_v4_model(am, model_name, ep):
        return ReasoningPolicy(
            effort=None,
            thinking_type="disabled",
            reasoning_effort=None,
            is_deepseek_v4=True,
            deepseek_v4_api_reasoning_effort=None,
        )
    ml = (model_name or "").lower()
    if any(k in ml for k in ("doubao", "seed")):
        return ReasoningPolicy(
            effort=None,
            thinking_type="disabled",
            reasoning_effort=None,
            is_deepseek_v4=False,
            deepseek_v4_api_reasoning_effort=None,
        )
    return ReasoningPolicy(
        effort=None,
        thinking_type="disabled",
        reasoning_effort=None,
        is_deepseek_v4=False,
        deepseek_v4_api_reasoning_effort=None,
    )


def _resolve_deepseek_v4_policy(
    mode: str, active_model: dict, configured_effort: Optional[str]
) -> ReasoningPolicy:
    """DeepSeek V4：thinking.type + 顶层 reasoning_effort（high|max）。"""
    gal = str(mode or "") in ("galgame", "galgame_lock")
    en = active_model.get("enable_thinking")
    th_on = (not gal) and (en is not False)
    ep = str(active_model.get("endpoint") or "")
    depth = _normalize_effort_for_model(
        str(active_model.get("model_name") or active_model.get("id") or "deepseek-v4-flash"),
        active_model,
        ep,
        configured_effort,
    )
    v4_eff = map_ds_v4_api_reasoning_effort(depth) if th_on else None
    return ReasoningPolicy(
        effort=None,
        thinking_type="enabled" if th_on else "disabled",
        reasoning_effort=None,
        is_deepseek_v4=True,
        deepseek_v4_api_reasoning_effort=v4_eff,
    )


def resolve_reasoning_policy(
    model_name: str,
    mode: str,
    configured_effort: Optional[str] = None,
    *,
    active_model: Optional[dict] = None,
    endpoint: Optional[str] = None,
) -> ReasoningPolicy:
    """
    统一思考策略（后端单点控制）：
    - 不依赖前端传入；
    - mode 可用于按业务场景覆写；
    - model_name 用于按模型能力差异化处理。
    - active_model / endpoint：用于识别 DeepSeek V4（uses_v4_thinking_api 或 官方端点+模型名）
    """
    am = active_model or {}
    ep = str(endpoint or am.get("endpoint") or "")

    if str(mode or "").strip() == "proactive":
        return _resolve_proactive_policy(model_name, am, ep)

    if is_deepseek_v4_model(am, model_name, ep):
        return _resolve_deepseek_v4_policy(str(mode or ""), am, configured_effort)

    model_lower = str(model_name or "").lower()
    default_effort = _normalize_effort_for_model(model_name, am, ep, configured_effort)

    # 豆包/seed：统一走 Responses API 的 thinking+reasoning 控制
    if any(k in model_lower for k in ("doubao", "seed")):
        effort = default_effort
        return ReasoningPolicy(
            effort=effort,
            thinking_type="enabled",
            reasoning_effort=effort,
            is_deepseek_v4=False,
            deepseek_v4_api_reasoning_effort=None,
        )

    # Grok-3-mini：允许走 reasoning_effort（由参数策略层最终保留）
    if "grok-3-mini" in model_lower:
        return ReasoningPolicy(
            effort=default_effort,
            thinking_type=None,
            reasoning_effort=None,
            is_deepseek_v4=False,
            deepseek_v4_api_reasoning_effort=None,
        )

    # 显式非推理模型：关闭思考
    if "non-reasoning" in model_lower:
        return ReasoningPolicy(
            effort=None,
            thinking_type="disabled",
            reasoning_effort=None,
            is_deepseek_v4=False,
            deepseek_v4_api_reasoning_effort=None,
        )

    # 其他模型按默认 high（或后端配置）处理
    # 仅用于支持 reasoning_effort 的兼容路径，Responses 的 thinking 字段不强制下发
    return ReasoningPolicy(
        effort=default_effort,
        thinking_type=None,
        reasoning_effort=None,
        is_deepseek_v4=False,
        deepseek_v4_api_reasoning_effort=None,
    )


def resolve_software_reasoning_policy(
    task: str,
    model_name: str,
    *,
    active_model: Optional[dict] = None,
    endpoint: Optional[str] = None,
    mode: Optional[str] = None,
    requested_enabled: Optional[bool] = None,
    requested_effort: Optional[str] = None,
) -> ReasoningPolicy:
    """Resolve software-level thinking choice, then translate through model driver."""
    cfg = get_software_reasoning(task)
    locked = bool(cfg.get("locked"))
    enabled = bool(cfg.get("enabled")) if locked or requested_enabled is None else bool(requested_enabled)
    effort = str(cfg.get("depth") or "high") if locked or requested_effort is None else str(requested_effort)

    am = dict(active_model or {})
    am["enable_thinking"] = enabled
    policy = resolve_reasoning_policy(
        model_name,
        mode or task,
        configured_effort=effort,
        active_model=am,
        endpoint=endpoint,
    )
    if not enabled:
        policy.thinking_type = "disabled"
        policy.reasoning_effort = None
        policy.effort = None
        if policy.is_deepseek_v4:
            policy.deepseek_v4_api_reasoning_effort = None
    return policy


def apply_model_param_policy(payload: dict, model_name: str, endpoint: str) -> dict:
    """
    统一参数兼容策略（单点管理）：
    - 兼容 xAI Grok 的参数约束
    - 云端 Chat Completions：多数厂商不接收 top_k/top_p/min_p，统一剔除以防报错
    """
    if not isinstance(payload, dict):
        return payload

    model_lower = str(model_name or "").lower()
    endpoint_lower = str(endpoint or "").lower()

    # 先做全局参数收敛：仅保留三类控制参数 + 必要协议字段
    allowed_keys = {
        "model", "messages", "input", "stream",
        "temperature", "max_completion_tokens", "max_tokens", "max_output_tokens",
        "response_format",  # galgame/json 输出约束
        "thinking", "reasoning", "reasoning_effort",
        "enable_thinking",  # Qwen3.5 / 豆包 思考开关
        "thinking_budget",  # Qwen3.5 思考预算（token 数）
        "tools",  # Responses API 工具（如 web_search）
    }
    for k in ("top_p", "top_k", "min_p"):
        payload.pop(k, None)
    dropped_keys = [k for k in list(payload.keys()) if k not in allowed_keys]
    for k in dropped_keys:
        payload.pop(k, None)
    if dropped_keys:
        logger.info("🧩 [ParamPolicy] dropped non-essential keys: %s", dropped_keys)

    # DeepSeek V4（api.deepseek.com + deepseek-v4-flash）：
    # 思考关闭时直接移除 reasoning_effort；思考开启时 "minimal"/"low"/"medium" → "high"。
    # 背景：memory layer 等后台任务固定写 reasoning_effort="minimal"，
    # 但 DeepSeek V4 API 只接受 high/low/medium/max/xhigh，且关思考时该字段无意义。
    if is_deepseek_v4_model(None, model_name, endpoint):
        thinking = payload.get("thinking")
        thinking_disabled = isinstance(thinking, dict) and thinking.get("type") == "disabled"
        if thinking_disabled:
            if payload.pop("reasoning_effort", None) is not None:
                logger.info("🧩 [ParamPolicy] deepseek-v4: thinking=disabled → removed reasoning_effort")
        elif "reasoning_effort" in payload:
            effort_val = payload["reasoning_effort"]
            if effort_val not in ("high", "max", "low", "medium", "xhigh"):
                payload["reasoning_effort"] = "high"
                logger.info("🧩 [ParamPolicy] deepseek-v4: reasoning_effort %r → 'high'", effort_val)
        return payload

    # Grok（含 api 易中转）：按模型硬编码规则处理
    is_grok = ("api.x.ai" in endpoint_lower) or ("grok" in model_lower)
    if not is_grok:
        return payload

    model_key = "grok-unknown"
    supports_reasoning_effort = False
    unsupported_keys: tuple[str, ...] = ()

    if "grok-3-mini" in model_lower:
        model_key = "grok-3-mini"
        supports_reasoning_effort = True
        # xAI 只接受 "high" / "low"，将 "minimal" → "low"，"medium" → "high"
        _effort_val = payload.get("reasoning_effort")
        if _effort_val == "minimal":
            payload["reasoning_effort"] = "low"
            logger.info("🧩 [ParamPolicy] grok-3-mini: reasoning_effort 'minimal' → 'low'")
        elif _effort_val == "medium":
            payload["reasoning_effort"] = "high"
            logger.info("🧩 [ParamPolicy] grok-3-mini: reasoning_effort 'medium' → 'high'")
    elif "grok-4" in model_lower and "non-reasoning" in model_lower:
        model_key = "grok-4-non-reasoning"
    elif "grok-4" in model_lower and "reasoning" in model_lower:
        model_key = "grok-4-reasoning"
        unsupported_keys = (
            "presence_penalty", "frequency_penalty",
            "presencePenalty", "frequencyPenalty",
            "stop",
        )
    elif "grok-3" in model_lower and "non-reasoning" in model_lower:
        model_key = "grok-3-non-reasoning"
    elif "grok-3" in model_lower and "reasoning" in model_lower:
        model_key = "grok-3-reasoning"
        unsupported_keys = (
            "presence_penalty", "frequency_penalty",
            "presencePenalty", "frequencyPenalty",
            "stop",
        )
    elif "grok-2" in model_lower:
        model_key = "grok-2"

    if not supports_reasoning_effort:
        removed_reasoning = False
        if "reasoning_effort" in payload:
            payload.pop("reasoning_effort", None)
            removed_reasoning = True
        reasoning_obj = payload.get("reasoning")
        if isinstance(reasoning_obj, dict) and "effort" in reasoning_obj:
            payload.pop("reasoning", None)
            removed_reasoning = True
        if removed_reasoning:
            logger.info("🧩 [ParamPolicy] %s: removed unsupported reasoning params", model_key)

    removed_keys: list[str] = []
    for key in unsupported_keys:
        if key in payload:
            payload.pop(key, None)
            removed_keys.append(key)
    if removed_keys:
        logger.info("🧩 [ParamPolicy] %s: removed unsupported keys %s", model_key, removed_keys)

    return payload
