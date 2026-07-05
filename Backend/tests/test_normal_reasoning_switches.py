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
from Backend.galgame.seq_llm import (
    _reasoning_task_from_stage,
    prepare_galgame_sequential_payload,
)


def test_normal_thinking_switches_default_off():
    assert NORMAL_DIRECTOR_THINKING_HIGH is False
    assert NORMAL_MAIN_REPLY_THINKING_HIGH is False


def test_reasoning_control_software_layer_defaults():
    assert get_software_reasoning()["enabled"] is False
    assert get_software_reasoning()["depth"] == "high"
    assert get_software_reasoning("context_memory")["locked"] is True
    assert get_software_reasoning("normal_main_reply")["enabled"] is False
    assert get_software_reasoning("normal_main_reply")["locked"] is True
    assert get_software_reasoning("normal_main_reply")["depth"] == "minimal"
    assert get_software_reasoning("normal_director")["locked"] is True
    assert get_software_reasoning("normal_director")["depth"] == "minimal"
    assert get_software_reasoning("normal_voice_reply")["locked"] is True
    assert get_software_reasoning("normal_voice_reply")["depth"] == "minimal"
    assert get_software_reasoning("normal_planner")["locked"] is True
    assert get_software_reasoning("normal_planner")["depth"] == "minimal"
    assert get_software_reasoning("web_search")["locked"] is True
    assert get_software_reasoning("web_search")["depth"] == "minimal"
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
    assert coerce_driver_depth(driver, "low") == "high"

    name, driver = get_reasoning_driver(
        "qwen3-plus",
        {"supports_enable_thinking": True},
        "https://dashscope.aliyuncs.com",
    )
    assert name == "qwen_enable_thinking"
    assert coerce_driver_depth(driver, "auto") == "auto"


def test_galgame_step_reasoning_tasks_are_configured_off():
    assert get_software_reasoning("galgame")["locked"] is True
    assert get_software_reasoning("galgame_lock")["locked"] is True
    assert get_software_reasoning("galgame_seq_step_1_director")["enabled"] is False
    assert get_software_reasoning("galgame_seq_step_2_vitals")["locked"] is True
    assert _reasoning_task_from_stage("SEQ_STEP_1_DIRECTOR_REQUEST", "galgame") == "galgame_seq_step_1_director"
    assert _reasoning_task_from_stage("SEQ_STEP_7_RESPONSE_REQUEST", "galgame") == "galgame_seq_step_7_response"
    assert _reasoning_task_from_stage("SEQ_STEP_8_JSON_RETRY_1_REQUEST", "galgame") == "galgame_seq_step_8_json"
    assert _reasoning_task_from_stage("SEQ_STEP_10_MEMORY_REQUEST", "galgame_lock") == "galgame_seq_step_10_memory"


def test_galgame_sequential_payload_uses_software_layer_to_disable_thinking():
    payload, policy, model_cfg = prepare_galgame_sequential_payload(
        {"model": "deepseek-v4-flash", "messages": [], "reasoning_effort": "max"},
        "deepseek-v4-flash",
        "galgame_lock",
        {
            "model_name": "deepseek-v4-flash",
            "endpoint": "https://api.deepseek.com",
            "uses_v4_thinking_api": True,
            "enable_thinking": True,
        },
        reasoning_mode="enabled",
        director_reasoning_effort="max",
        reasoning_task="galgame_seq_step_1_director",
    )

    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload
    assert policy.thinking_type == "disabled"
    assert policy.deepseek_v4_api_reasoning_effort is None
    assert model_cfg["enable_thinking"] is True


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
