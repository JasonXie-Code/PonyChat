from Backend.chat_modules.normal_reasoning_switches import (
    NORMAL_DIRECTOR_THINKING_HIGH,
    NORMAL_MAIN_REPLY_THINKING_HIGH,
    apply_normal_thinking_switch,
)
from Backend.reasoning_config import (
    coerce_driver_depth,
    get_llm_task_config,
    get_reasoning_driver,
    get_software_reasoning,
)
from Backend.reasoning_policy import ReasoningPolicy


def test_normal_thinking_switches_default_off():
    assert NORMAL_DIRECTOR_THINKING_HIGH is False
    assert NORMAL_MAIN_REPLY_THINKING_HIGH is False


def test_reasoning_control_software_layer_defaults():
    assert get_software_reasoning()["enabled"] is True
    assert get_software_reasoning()["depth"] == "low"
    assert get_software_reasoning("context_memory")["locked"] is True
    assert get_software_reasoning("normal_main_reply")["enabled"] is True
    assert get_software_reasoning("normal_main_reply")["locked"] is True
    assert get_software_reasoning("normal_main_reply")["depth"] == "low"
    assert get_software_reasoning("proactive_decision")["locked"] is True
    assert get_software_reasoning("proactive_decision")["depth"] == "low"
    assert get_software_reasoning("web_search")["locked"] is True
    assert get_software_reasoning("web_search")["depth"] == "low"
    assert get_llm_task_config("normal_main_reply")["temperature"] == 1.0
    assert get_llm_task_config("normal_main_reply")["max_output_tokens"] == 16384
    assert get_llm_task_config("normal_main_reply")["context_limit_tokens"] == 64000
    assert get_llm_task_config("companion_agent_action")["timeout_seconds"] == 120


def test_reasoning_driver_depth_fallbacks():
    name, driver = get_reasoning_driver(
        "deepseek-v4-flash",
        {"uses_v4_thinking_api": True},
        "https://api.deepseek.com",
    )
    assert name == "deepseek_v4"
    assert coerce_driver_depth(driver, "max") == "max"
    assert coerce_driver_depth(driver, "low") == "low"

    name, driver = get_reasoning_driver(
        "qwen3-plus",
        {"supports_enable_thinking": True},
        "https://dashscope.aliyuncs.com",
    )
    assert name == "qwen_enable_thinking"
    assert coerce_driver_depth(driver, "auto") == "auto"


def test_game_agent_reasoning_tasks_are_configured():
    assert get_software_reasoning("galgame")["locked"] is True
    assert get_software_reasoning("galgame_lock")["locked"] is True


def test_apply_normal_thinking_switch_disables_deepseek_v4_reasoning():
    policy = ReasoningPolicy(
        effort="high",
        thinking_type="enabled",
        reasoning_effort="high",
        is_deepseek_v4=True,
        deepseek_v4_api_reasoning_effort="high",
    )

    result = apply_normal_thinking_switch(policy, enable_high_thinking=False)

    assert result.thinking_type == "disabled"
    assert result.reasoning_effort is None
    assert result.effort is None
    assert result.deepseek_v4_api_reasoning_effort is None


def test_apply_normal_thinking_switch_enables_high_deepseek_v4_reasoning():
    policy = ReasoningPolicy(
        thinking_type="disabled",
        is_deepseek_v4=True,
    )

    result = apply_normal_thinking_switch(policy, enable_high_thinking=True)

    assert result.thinking_type == "enabled"
    assert result.reasoning_effort == "high"
    assert result.effort == "high"
    assert result.deepseek_v4_api_reasoning_effort == "high"
