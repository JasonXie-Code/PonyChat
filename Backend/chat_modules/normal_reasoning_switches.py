from __future__ import annotations

from ..reasoning_policy import ReasoningPolicy

# Normal chat is split into small deterministic stages, so every normal-stage
# model call should answer directly without hidden reasoning.
NORMAL_DIRECTOR_THINKING_HIGH = False
NORMAL_MAIN_REPLY_THINKING_HIGH = False


def apply_normal_thinking_switch(
    reasoning_policy: ReasoningPolicy,
    *,
    enable_high_thinking: bool,
) -> ReasoningPolicy:
    """Apply the normal-chat thinking switch to one request's reasoning policy."""
    if reasoning_policy.is_deepseek_v4 and reasoning_policy.deepseek_v4_api_reasoning_effort == "low":
        return reasoning_policy
    if enable_high_thinking:
        reasoning_policy.thinking_type = "enabled"
        reasoning_policy.reasoning_effort = "high"
        reasoning_policy.effort = "high"
        if reasoning_policy.is_deepseek_v4:
            reasoning_policy.deepseek_v4_api_reasoning_effort = "high"
        return reasoning_policy

    reasoning_policy.thinking_type = "disabled"
    reasoning_policy.reasoning_effort = None
    reasoning_policy.effort = None
    if reasoning_policy.is_deepseek_v4:
        reasoning_policy.deepseek_v4_api_reasoning_effort = None
    return reasoning_policy
