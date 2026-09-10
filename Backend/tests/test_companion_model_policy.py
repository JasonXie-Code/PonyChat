import json
from pathlib import Path

from Backend.companion_model_policy import (
    DEEPSEEK_FLASH_MODEL_ID,
    DEEPSEEK_VISION_MODEL_ID,
    choose_companion_route,
    is_high_difficulty_task,
)


def test_simple_task_uses_deepseek_flash():
    assert choose_companion_route().model_id == DEEPSEEK_FLASH_MODEL_ID


def test_image_uses_deepseek_vision_model():
    route = choose_companion_route(has_image=True)
    assert route.model_id == DEEPSEEK_VISION_MODEL_ID
    assert route.reason == "vision"


def test_explicit_hard_reasoning_uses_deepseek_vision_model():
    assert is_high_difficulty_task("请做复杂推理后决定如何操作")
    assert choose_companion_route(high_difficulty=True).model_id == DEEPSEEK_VISION_MODEL_ID


def test_ordinary_qq_message_is_not_hard_reasoning():
    assert not is_high_difficulty_task("帮我用QQ给张三发信息")


def test_deepseek_manifest_uses_requested_cloud_model():
    config_path = Path(__file__).parents[1] / "conf" / "models" / "deepseek.json"
    models = json.loads(config_path.read_text(encoding="utf-8"))["models"]
    model = next(item for item in models if item["id"] == DEEPSEEK_VISION_MODEL_ID)
    assert model["model_name"] == "deepseek-flash"
    assert model["supports_vision"] is True
    assert model["enable_thinking"] is True
    assert model["options"]["reasoning_effort"] == "low"
