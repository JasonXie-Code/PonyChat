"""
用户侧「当前对话模型」解析（与全局清单 `model_manager.get_active_model` 配合）。

约定（勿重复造默认）：
  - 已登录用户：读 `user_settings.active_model_id` → 无效则修正为 DEFAULT_FALLBACK_MODEL_ID 并回退
  - 无用户名 / 未设置：走 `get_default_active_model()` → 固定优先 DeepSeek 视觉（与清单默认一致）
  - 全局清单层：见 `model_manager.DEFAULT_FALLBACK_MODEL_ID` 与 `ModelManager.get_active_model()`

说明：陪玩通过 companion_model_policy 统一使用 DeepSeek 视觉模型。

主对话/游戏在 `resolve_auth_and_quota` 中统一使用后端选定的 chat 模型，忽略用户偏好和请求 model_id。本模块用于其余模式或非聊天路径。
"""
from __future__ import annotations

from typing import Optional

from .config import logger, model_manager
from .db import get_database
from .db.settings_dao import SettingsDAO
from .model_manager import DEFAULT_FALLBACK_MODEL_ID


def _get_enabled_model_by_id(model_id: str) -> Optional[dict]:
    target_id = str(model_id or "").strip()
    if not target_id:
        return None
    for model in model_manager.get_models():
        if model.get("id") == target_id and model.get("enabled") is not False:
            return model
    return None


def get_default_active_model() -> Optional[dict]:
    """Use the configured global model when the user has no preference."""
    return model_manager.get_active_model()


async def _load_user_settings(username: str) -> dict:
    username = str(username or "").strip()
    if not username:
        return {}
    db = get_database()
    await db.init()
    settings = await SettingsDAO(db).load_settings(username)
    return settings if isinstance(settings, dict) else {}


async def get_user_active_model(username: str) -> Optional[dict]:
    username = str(username or "").strip()
    if username:
        try:
            settings = await _load_user_settings(username)
            preferred_id = str(settings.get("active_model_id") or "").strip()
            preferred_model = _get_enabled_model_by_id(preferred_id)
            if preferred_model:
                return preferred_model
            if preferred_id:
                logger.info(
                    "⚠️ [模型大厅] 用户 %s 的激活模型 %s 不可用，回退 %s",
                    username,
                    preferred_id,
                    DEFAULT_FALLBACK_MODEL_ID,
                )
                fb = _get_enabled_model_by_id(DEFAULT_FALLBACK_MODEL_ID)
                if fb:
                    try:
                        db = get_database()
                        await db.init()
                        await SettingsDAO(db).merge_settings(username, {"active_model_id": fb.get("id")})
                    except Exception as e:
                        logger.warning("⚠️ [模型大厅] 修正用户激活模型到默认失败 (%s): %s", username, e)
                    return fb
        except Exception as e:
            logger.warning("⚠️ [模型大厅] 读取用户激活模型失败 (%s): %s", username, e)
    return get_default_active_model()


async def get_user_active_model_id(username: str) -> str:
    active_model = await get_user_active_model(username)
    return str(active_model.get("id") or "") if active_model else ""


async def set_user_active_model(username: str, model_id: str) -> tuple[bool, Optional[dict]]:
    username = str(username or "").strip()
    target_model = _get_enabled_model_by_id(model_id)
    if not username or target_model is None:
        return False, target_model

    db = get_database()
    await db.init()
    ok = await SettingsDAO(db).merge_settings(username, {"active_model_id": target_model.get("id")})
    return ok, target_model
