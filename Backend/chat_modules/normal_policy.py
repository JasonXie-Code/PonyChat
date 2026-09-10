from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any, Dict

from .Prompts import NORMAL_POLICY_DEFAULT as DEFAULT_POLICY, PLANNER_POLICY_RUNTIME_APPEND as _PLANNER_POLICY_RUNTIME_APPEND
from ..config import logger


POLICY_FILE = Path(__file__).resolve().parents[1] / "conf" / "normal_mode_policy.json"
_CACHE_TTL_SECONDS = 5.0
_cache: Dict[str, Any] | None = None
_cache_mtime: float = 0.0
_cache_time: float = 0.0






def _normalize_policy(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_POLICY)
    merged = copy.deepcopy(DEFAULT_POLICY)
    for key, value in data.items():
        if key in {"shared_reply_policy", "planner_policy", "reply_policy", "voice_policy", "version"}:
            merged[key] = str(value or "").strip() or merged[key]
        elif key == "enabled":
            merged[key] = bool(value)
        else:
            merged[key] = value
    return merged


def _load_from_disk() -> Dict[str, Any]:
    if not POLICY_FILE.exists():
        return copy.deepcopy(DEFAULT_POLICY)
    with open(POLICY_FILE, "r", encoding="utf-8") as f:
        return _normalize_policy(json.load(f))


def get_normal_mode_policy(force_reload: bool = False) -> Dict[str, Any]:
    global _cache, _cache_mtime, _cache_time
    now = time.time()
    try:
        mtime = POLICY_FILE.stat().st_mtime if POLICY_FILE.exists() else 0.0
        if (
            not force_reload
            and _cache is not None
            and now - _cache_time < _CACHE_TTL_SECONDS
            and mtime == _cache_mtime
        ):
            return copy.deepcopy(_cache)
        policy = _load_from_disk()
        _cache = policy
        _cache_mtime = mtime
        _cache_time = now
        return copy.deepcopy(policy)
    except Exception as exc:
        logger.warning("[NormalPolicy] 加载普通对话策略失败，使用默认策略: %s", exc)
        return copy.deepcopy(DEFAULT_POLICY)


def get_policy_version() -> str:
    return str(get_normal_mode_policy().get("version") or DEFAULT_POLICY["version"])


def get_planner_policy_text() -> str:
    policy = get_normal_mode_policy()
    if not policy.get("enabled", True):
        return ""
    text = str(policy.get("planner_policy") or "").strip()
    if _PLANNER_POLICY_RUNTIME_APPEND not in text:
        text = "\n".join(x for x in (text, _PLANNER_POLICY_RUNTIME_APPEND) if x)
    return text


def get_reply_policy_text() -> str:
    policy = get_normal_mode_policy()
    if not policy.get("enabled", True):
        return ""
    return "\n\n".join(
        x
        for x in (
            str(policy.get("shared_reply_policy") or "").strip(),
            str(policy.get("reply_policy") or "").strip(),
        )
        if x
    )


def get_voice_policy_text() -> str:
    policy = get_normal_mode_policy()
    if not policy.get("enabled", True):
        return ""
    return "\n\n".join(
        x
        for x in (
            str(policy.get("shared_reply_policy") or "").strip(),
            str(policy.get("voice_policy") or "").strip(),
        )
        if x
    )


def write_normal_mode_policy(data: Dict[str, Any]) -> Dict[str, Any]:
    policy = _normalize_policy(data)
    POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = POLICY_FILE.with_suffix(POLICY_FILE.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(policy, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(POLICY_FILE)
    return get_normal_mode_policy(force_reload=True)
