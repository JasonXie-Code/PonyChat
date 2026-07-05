from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_CONFIG_PATH = Path(__file__).resolve().parent / "conf" / "reasoning_control.json"


@lru_cache(maxsize=1)
def load_reasoning_config() -> dict[str, Any]:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "version": "fallback",
            "software": {"default": {"enabled": False, "depth": "high"}, "tasks": {}},
            "drivers": {},
        }


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def get_software_reasoning(task: str = "") -> dict[str, Any]:
    software = _dict(load_reasoning_config().get("software"))
    default_cfg = _dict(software.get("default"))
    tasks = _dict(software.get("tasks"))
    task_cfg = _dict(tasks.get(str(task or "").strip()))
    merged = {**default_cfg, **task_cfg}
    return {
        "enabled": bool(merged.get("enabled", False)),
        "depth": str(merged.get("depth") or "high").strip().lower() or "high",
        "locked": bool(merged.get("locked", False)),
    }


def get_llm_task_config(task: str = "") -> dict[str, Any]:
    software = _dict(load_reasoning_config().get("software"))
    default_cfg = _dict(software.get("default"))
    tasks = _dict(software.get("tasks"))
    task_cfg = _dict(tasks.get(str(task or "").strip()))
    return {**default_cfg, **task_cfg}


def llm_task_float(task: str, key: str, default: float | None = None) -> float | None:
    value = get_llm_task_config(task).get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def llm_task_int(task: str, key: str, default: int | None = None) -> int | None:
    value = get_llm_task_config(task).get(key)
    try:
        n = int(value)
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default


def apply_llm_task_payload_config(
    payload: dict[str, Any],
    task: str,
    *,
    output_token_field: str = "max_completion_tokens",
    include_temperature: bool = True,
) -> dict[str, Any]:
    cfg = get_llm_task_config(task)
    if include_temperature and "temperature" in cfg:
        temp = llm_task_float(task, "temperature")
        if temp is not None:
            payload["temperature"] = temp
    max_tokens = llm_task_int(task, "max_output_tokens")
    if max_tokens is not None:
        for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
            payload.pop(key, None)
        payload[output_token_field] = max_tokens
    return payload


def software_thinking_enabled(task: str = "", *, default: bool = False) -> bool:
    cfg = get_software_reasoning(task)
    if task and not cfg:
        return bool(default)
    return bool(cfg.get("enabled", default))


def software_reasoning_depth(task: str = "", *, default: str | None = "high") -> str | None:
    cfg = get_software_reasoning(task)
    return str(cfg.get("depth") or default).strip().lower() or default


def _driver_matches(driver: dict[str, Any], model_name: str, active_model: dict, endpoint: str) -> bool:
    match = _dict(driver.get("match"))
    model_lower = str(model_name or "").lower()
    endpoint_lower = str(endpoint or "").lower()
    if match.get("default") is True:
        return True
    if "uses_v4_thinking_api" in match and bool(active_model.get("uses_v4_thinking_api")) == bool(match["uses_v4_thinking_api"]):
        return True
    if "supports_enable_thinking" in match and bool(active_model.get("supports_enable_thinking")) == bool(match["supports_enable_thinking"]):
        return True
    contains = match.get("model_name_contains")
    if isinstance(contains, list) and any(str(item).lower() in model_lower for item in contains):
        return True
    ep_contains = match.get("endpoint_contains")
    if isinstance(ep_contains, list) and any(str(item).lower() in endpoint_lower for item in ep_contains):
        return True
    return False


def get_reasoning_driver(model_name: str, active_model: dict | None = None, endpoint: str = "") -> tuple[str, dict[str, Any]]:
    drivers = _dict(load_reasoning_config().get("drivers"))
    am = active_model or {}
    ep = str(endpoint or am.get("endpoint") or "")
    default: tuple[str, dict[str, Any]] = ("generic_reasoning_effort", _dict(drivers.get("generic_reasoning_effort")))
    for name, driver in drivers.items():
        d = _dict(driver)
        if name == "generic_reasoning_effort":
            default = (name, d)
            continue
        if _driver_matches(d, model_name, am, ep):
            return name, d
    return default


def coerce_driver_depth(driver: dict[str, Any], requested_depth: str | None) -> str | None:
    enable = _dict(driver.get("enable"))
    supported = enable.get("supported_depths")
    fallback = str(enable.get("fallback_depth") or "high").strip().lower()
    requested = str(requested_depth or fallback).strip().lower()
    if isinstance(supported, list):
        allowed = [str(item).strip().lower() for item in supported]
        if requested in allowed:
            return requested
        return fallback if fallback in allowed else (allowed[0] if allowed else None)
    return requested or fallback
