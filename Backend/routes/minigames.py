from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..chat_modules.context_memory import schedule_context_memory_update
from ..config import logger, model_manager
from ..db import get_database, get_membership_dao
from ..providers.llm_call import call_llm_payload
from ..reasoning_policy import ReasoningPolicy, is_deepseek_v4_model
from ..utils import ClientContext, save_chat_debug_log
from .minigames_xiangqi_common import (
    PLAY_STYLE_LABELS,
    POWER_TIER_LABELS,
    _candidate_tags_for_policy,
    _safe_stabilize_power_tier,
)
from .minigames_xiangqi_history import (
    _build_xiangqi_character_profile,
    _coerce_xiangqi_undo_result,
    _load_execute_context,
    _load_prepare_context,
    _normalize_execute_result,
    _xiangqi_memory_commit_messages,
    _xiangqi_reply_style_state,
    _xiangqi_user_resigned_fallback_text,
)
from .minigames_xiangqi_prompts import (
    _execute_prompt,
    _fallback_prepare,
    _normalize_prepare_card,
    _prepare_prompt,
)


router = APIRouter(prefix="/api/minigames", tags=["Minigames"])

class XiangqiPrepareRequest(BaseModel):
    username: str = ""
    character_id: Optional[str] = Field(default=None, alias="character_id")
    conversation_id: Optional[str] = Field(default=None, alias="conversation_id")
    character_name: str = Field(default="对手", alias="character_name")
    user_name: str = Field(default="你", alias="user_name")
    player_side: str = Field(default="red", alias="player_side")
    game_memory: dict[str, Any] = Field(default_factory=dict, alias="game_memory")
    voice_reply_enabled: bool = Field(default=False, alias="voice_reply_enabled")
    client_context: Optional[ClientContext] = Field(default=None, alias="client_context")


class XiangqiExecuteRequest(BaseModel):
    username: str = ""
    character_id: Optional[str] = Field(default=None, alias="character_id")
    conversation_id: Optional[str] = Field(default=None, alias="conversation_id")
    game_id: str = Field(default="", alias="game_id")
    character_name: str = Field(default="对手", alias="character_name")
    user_name: str = Field(default="你", alias="user_name")
    player_side: str = Field(default="red", alias="player_side")
    turn: str = "black"
    board_state: dict[str, Any] = Field(default_factory=dict, alias="board_state")
    move_history: list[dict[str, Any]] = Field(default_factory=list, alias="move_history")
    dialogue_history: list[dict[str, Any]] = Field(default_factory=list, alias="dialogue_history")
    legal_moves: list[dict[str, Any]] = Field(default_factory=list, alias="legal_moves")
    move_candidates: list[dict[str, Any]] = Field(default_factory=list, alias="move_candidates")
    user_message: str = Field(default="", alias="user_message")
    event_context: dict[str, Any] = Field(default_factory=dict, alias="event_context")
    entry_card: dict[str, Any] = Field(default_factory=dict, alias="entry_card")
    game_memory: dict[str, Any] = Field(default_factory=dict, alias="game_memory")
    voice_reply_enabled: bool = Field(default=False, alias="voice_reply_enabled")
    client_context: Optional[ClientContext] = Field(default=None, alias="client_context")


class XiangqiMemoryCommitRequest(BaseModel):
    username: str = ""
    character_id: Optional[str] = Field(default=None, alias="character_id")
    conversation_id: Optional[str] = Field(default=None, alias="conversation_id")
    character_name: str = Field(default="对手", alias="character_name")
    user_name: str = Field(default="你", alias="user_name")
    reason: str = Field(default="game_finished", alias="reason")
    game_record: dict[str, Any] = Field(default_factory=dict, alias="game_record")
    client_context: Optional[ClientContext] = Field(default=None, alias="client_context")


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


async def _auth_username(username: str, x_chat_auth: Optional[str]) -> str:
    requested = str(username or "").strip()
    token = str(x_chat_auth or "").strip()
    if not token:
        return requested
    from ..routes import auth as auth_module

    verified = await auth_module.auth_token_verify(token)
    if not verified:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "error": "auth_expired", "message": "登录已失效，请重新登录"},
        )
    if requested and requested != verified:
        raise HTTPException(
            status_code=403,
            detail={"status": "error", "error": "forbidden", "message": "账号信息不匹配，请重新登录"},
        )
    return verified


async def _check_quota(username: str) -> None:
    if not username:
        return
    try:
        quota = await get_membership_dao().check_daily_quota(username)
        if not quota.get("allowed", True):
            raise HTTPException(
                status_code=429,
                detail={
                    "status": "quota_exceeded",
                    "message": quota.get("reason", "今日积分已用完"),
                    "membership_type": quota.get("membership_type", "free"),
                    "daily_limit": quota.get("limit", 100),
                    "remaining": 0,
                },
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("⚠️ [Xiangqi] 配额检查失败（允许继续）: %s", exc)


def _chess_model_no_thinking() -> tuple[dict[str, Any], str, ReasoningPolicy]:
    active_model = model_manager.get_model_for_task("chat") or model_manager.get_active_model()
    if not active_model:
        raise RuntimeError("No active model")
    model_cfg = dict(active_model)
    model_cfg["enable_thinking"] = False
    model_cfg.pop("thinking_budget", None)
    model_cfg.pop("reasoning_effort", None)
    endpoint = str(model_cfg.get("endpoint") or "")
    model_name = str(model_cfg.get("model_name") or model_cfg.get("id") or "")
    is_ds_v4 = is_deepseek_v4_model(model_cfg, model_name, endpoint)
    no_think_name = str(model_cfg.get("model_name_no_thinking") or "").strip()
    if no_think_name and not is_ds_v4:
        model_cfg["model_name"] = no_think_name
        model_name = no_think_name
    policy = ReasoningPolicy(
        effort=None,
        thinking_type="disabled",
        reasoning_effort=None,
        is_deepseek_v4=is_ds_v4,
        deepseek_v4_api_reasoning_effort=None,
    )
    return model_cfg, model_name, policy


def _force_chess_payload_no_thinking(payload: dict[str, Any]) -> dict[str, Any]:
    payload["enable_thinking"] = False
    payload["thinking"] = {"type": "disabled"}
    payload.pop("thinking_budget", None)
    payload.pop("reasoning_effort", None)
    payload.pop("reasoning", None)
    return payload


async def _call_chess_llm(
    *,
    username: str,
    character_id: str,
    step: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> tuple[str, str, dict[str, Any]]:
    active_model, model_name, reasoning_policy = _chess_model_no_thinking()
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "max_completion_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    _force_chess_payload_no_thinking(payload)
    stage = "XIANGQI_PREPARE_REQUEST" if step == "prepare" else "XIANGQI_EXECUTE_REQUEST"
    params = {
        "step": "准备步骤" if step == "prepare" else "执行步骤",
        "software_task": "normal_main_reply",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "json_mode": True,
        "enable_thinking": False,
    }
    started = time.perf_counter()
    response = await call_llm_payload(
        payload,
        active_model,
        task="normal",
        timeout=75.0,
        reasoning_policy=reasoning_policy,
        chat_debug_request={
            "username": username or None,
            "character_id": character_id or None,
            "mode": "chinese_chess",
            "stage": stage,
            "model_name": model_name,
            "params": params,
        },
        record_usage="main" if username else "none",
        usage_meter_username=username or None,
        llm_api_calls=1,
        charge_membership_chat_quota=bool(username),
    )
    parsed = _extract_json_object(response.text)
    parsed["_duration_ms"] = int((time.perf_counter() - started) * 1000)
    return response.text, model_name, parsed


@router.post("/xiangqi/prepare")
async def prepare_xiangqi_entry(
    req: XiangqiPrepareRequest,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    username = await _auth_username(req.username, x_chat_auth)
    req.username = username
    await _check_quota(username)
    character_id = str(req.character_id or "").strip()
    fallback = _fallback_prepare(req)
    try:
        ctx = await _load_prepare_context(req)
        messages = _prepare_prompt(req, ctx)
        raw_text, model_name, parsed = await _call_chess_llm(
            username=username,
            character_id=character_id,
            step="prepare",
            messages=messages,
            max_tokens=800,
            temperature=0.35,
        )
        if not parsed:
            raise ValueError("model returned non-json prepare result")
        card = _normalize_prepare_card(parsed, fallback)
        card, stability = await _safe_stabilize_power_tier(req, card)
        await save_chat_debug_log(
            username or None,
            character_id or None,
            "chinese_chess",
            model_name,
            {
                "raw_text": raw_text,
                "entry_card": card,
                "power_tier_stability": stability,
            },
            "XIANGQI_PREPARE_PARSED",
            params={"step": "准备步骤"},
        )
        return {
            "status": "ok",
            "step": "prepare",
            "entry_card": card,
            "card_text": "",
            "fallback": False,
            "duration_ms": int(card.get("_duration_ms") or 0),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("⚠️ [Xiangqi] 准备步骤失败，使用 fallback: %s", exc)
        fallback, stability = await _safe_stabilize_power_tier(req, fallback)
        await save_chat_debug_log(
            username or None,
            character_id or None,
            "chinese_chess",
            "fallback",
            {"error": str(exc), "entry_card": fallback, "power_tier_stability": stability},
            "XIANGQI_PREPARE_ERROR",
            params={"step": "准备步骤"},
        )
        return {
            "status": "ok",
            "step": "prepare",
            "entry_card": fallback,
            "card_text": "",
            "fallback": True,
            "error": str(exc),
            "duration_ms": 0,
        }


@router.post("/xiangqi/memory")
async def commit_xiangqi_memory(
    req: XiangqiMemoryCommitRequest,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    username = await _auth_username(req.username, x_chat_auth)
    req.username = username
    character_id = str(req.character_id or "").strip()
    conversation_id = str(req.conversation_id or "").strip()
    if not username or not character_id or not conversation_id:
        return {
            "status": "ok",
            "scheduled": False,
            "reason": "missing_identity_or_conversation",
        }
    if not isinstance(req.game_record, dict) or not req.game_record:
        return {
            "status": "ok",
            "scheduled": False,
            "reason": "empty_game_record",
        }
    user_message, assistant_message, planner_notes = _xiangqi_memory_commit_messages(req)
    record = req.game_record
    entry_at_ms = None
    try:
        raw_ended_at = record.get("ended_at_ms")
        entry_at_ms = int(raw_ended_at) if raw_ended_at is not None else None
    except Exception:
        entry_at_ms = None
    schedule_context_memory_update(
        username,
        character_id,
        conversation_id,
        user_message,
        assistant_message,
        get_database(),
        entry_at_ms=entry_at_ms,
        planner_memory_notes=planner_notes,
    )
    await save_chat_debug_log(
        username or None,
        character_id or None,
        "chinese_chess",
        "memory",
        {
            "reason": req.reason,
            "game_record": req.game_record,
            "assistant_message": assistant_message,
        },
        "XIANGQI_MEMORY_COMMIT",
        params={"step": "memory", "conversation_id": conversation_id},
    )
    return {
        "status": "ok",
        "scheduled": True,
    }


@router.post("/xiangqi/execute")
async def execute_xiangqi_step(
    req: XiangqiExecuteRequest,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    username = await _auth_username(req.username, x_chat_auth)
    req.username = username
    await _check_quota(username)
    character_id = str(req.character_id or "").strip()
    try:
        try:
            role_context = await _load_execute_context(req)
        except Exception as ctx_exc:
            logger.warning("⚠️ [Xiangqi] 执行步骤加载普通角色上下文失败，降级为空上下文: %s", ctx_exc)
            role_context = {}
        raw_text, model_name, parsed = await _call_chess_llm(
            username=username,
            character_id=character_id,
            step="execute",
            messages=_execute_prompt(req, role_context),
            max_tokens=900,
            temperature=0.48,
        )
        if not parsed:
            raise ValueError("model returned non-json execute result")
        parsed = _coerce_xiangqi_undo_result(req, _normalize_execute_result(parsed))
        await save_chat_debug_log(
            username or None,
            character_id or None,
            "chinese_chess",
            model_name,
            {"raw_text": raw_text, "execute_result": parsed},
            "XIANGQI_EXECUTE_PARSED",
            params={"step": "执行步骤", "game_id": req.game_id},
        )
        return {
            "status": "ok",
            "step": "execute",
            "result": parsed,
            "fallback": False,
            "duration_ms": int(parsed.get("_duration_ms") or 0),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("⚠️ [Xiangqi] 执行步骤失败，返回 chat_only fallback: %s", exc)
        event_type = str((req.event_context or {}).get("event_type") or "").strip()
        is_undo_request = event_type == "user_undo_request"
        is_user_resigned = event_type == "user_resigned"
        fallback_text = (
            "我先不悔这步，继续下吧。" if is_undo_request else
            _xiangqi_user_resigned_fallback_text(req) if is_user_resigned else
            "我再看一下局面，先稳一点。"
        )
        fallback = {
            "schema_version": 2,
            "action": "reject_undo" if is_undo_request else "chat_only",
            "selected_move_id": None,
            "近期重复词": [],
            "character_reply": {
                "reaction_text": fallback_text,
                "move_reason_text": "",
                "casual_chat_text": "",
                "text": fallback_text,
                "tts_text": fallback_text,
                "emotion": "thinking",
                "style_tags": ["保守", "自然"],
            },
            "move": None,
            "next_plan": {"summary": "", "candidate_move": None, "targets": []},
            "ui": {"highlight_cells": [], "show_thinking": False},
            "safety": {"confidence": 0.0, "needs_legal_retry": True, "candidate_source": "client_generated"},
            "private": {"brief_reason": "执行步骤失败，客户端应使用本地合法走法 fallback。", "risk_level": "medium"},
        }
        await save_chat_debug_log(
            username or None,
            character_id or None,
            "chinese_chess",
            "fallback",
            {"error": str(exc), "execute_result": fallback},
            "XIANGQI_EXECUTE_ERROR",
            params={"step": "执行步骤", "game_id": req.game_id},
        )
        return {
            "status": "ok",
            "step": "execute",
            "result": fallback,
            "fallback": True,
            "error": str(exc),
            "duration_ms": 0,
        }
