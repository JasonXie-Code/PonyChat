# -*- coding: utf-8 -*-
"""DeepSeek V4 Flash 冒烟：配置、helpers、model_manager schema、reasoning_policy 保留字段。

运行（仓库根目录，PYTHONPATH 含项目根）：
  pip install -r Backend/conf/requirements.txt
  set PYTHONPATH=%CD%  # 或 export PYTHONPATH=$PWD
  python -m pytest Backend/tests/test_deepseek_v4_smoke.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEEPSEEK_JSON = BACKEND_ROOT / "conf" / "models" / "deepseek.json"


@pytest.fixture(scope="module")
def deepseek_model_cfg() -> dict:
    data = json.loads(DEEPSEEK_JSON.read_text(encoding="utf-8"))
    assert "models" in data and len(data["models"]) >= 1
    return data["models"][0]


def test_deepseek_json_shape(deepseek_model_cfg: dict) -> None:
    m = deepseek_model_cfg
    assert m.get("model_name") == "deepseek-v4-flash"
    assert m.get("uses_v4_thinking_api") is True
    assert "model_name_no_thinking" not in m
    assert "max_tokens_no_thinking" not in m
    assert m.get("endpoint") == "https://api.deepseek.com"


def test_helpers() -> None:
    from Backend.chat_modules.service import _coerce_reasoning
    from Backend.reasoning_policy import (
        is_deepseek_v4_model,
        map_ds_v4_api_reasoning_effort,
        resolve_reasoning_policy,
    )

    assert is_deepseek_v4_model({"uses_v4_thinking_api": True}, "any", "")
    assert not is_deepseek_v4_model({}, "deepseek-v4-pro", "https://api.deepseek.com")
    assert is_deepseek_v4_model({}, "deepseek-v4-flash", "https://api.deepseek.com")
    assert map_ds_v4_api_reasoning_effort("low") == "high"
    assert map_ds_v4_api_reasoning_effort("max") == "max"
    assert _coerce_reasoning("max") == "max"
    pol = resolve_reasoning_policy(
        "deepseek-v4-flash",
        "normal",
        "max",
        active_model={"uses_v4_thinking_api": True, "enable_thinking": True},
        endpoint="",
    )
    assert pol.is_deepseek_v4 and pol.thinking_type == "enabled"
    assert pol.deepseek_v4_api_reasoning_effort == "max"


def test_model_manager_no_thinking_budget(deepseek_model_cfg: dict) -> None:
    from Backend.model_manager import ModelManager

    schema = ModelManager()._build_config_schema(deepseek_model_cfg)
    keys = [x.get("key") for x in schema]
    assert "thinking_budget" not in keys
    assert "reasoning_effort" in keys
    assert keys.count("enable_thinking") == 1
    re = next(x for x in schema if x.get("key") == "reasoning_effort")
    vals = {o["value"] for o in re.get("options", [])}
    assert vals == {"high", "max"}


def test_apply_model_param_policy_keeps_thinking() -> None:
    from Backend.reasoning_policy import apply_model_param_policy

    payload = {
        "model": "deepseek-v4-flash",
        "messages": [],
        "stream": False,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
    }
    out = apply_model_param_policy(
        dict(payload), "deepseek-v4-flash", "https://api.deepseek.com"
    )
    assert out.get("thinking", {}).get("type") == "enabled"
    assert out.get("reasoning_effort") == "max"
