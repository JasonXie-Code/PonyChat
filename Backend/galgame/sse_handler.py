from __future__ import annotations

import asyncio
import json
import re as _re
import time

from fastapi.responses import JSONResponse, StreamingResponse

from ..config import logger
from ..utils import load_galgame_state_async, save_chat_debug_log
from .metering import reset_galgame_meter_username, set_galgame_meter_username
from .generate import _GenerationCancelled, _sequential_galgame_generate
from .handler import _handle_galgame_response
from .payload import build_galgame_step_system_prompt
from .steps import (
    _inject_options_into_raw,
    _run_step8_metadata_json,
    _run_step9_options_only,
    parse_metadata_dict_for_options,
)

# 游戏/锁分整轮分步生成墙钟上限（与 httpx 全局读超时、客户端轮询一致）
GALGAME_JOB_TIMEOUT_SECONDS = 600.0


async def handle_galgame_sse(
    *,
    request,
    model_name: str,
    payload: dict,
    api_url: str,
    headers: dict,
    provider,
    httpx_client,
    messages: list,
    request_tokens: int,
    username: str,
    character_id: str,
    client_id: str,
    effective_username: str,
    release_lock,
    active_model: dict | None = None,
    use_json: bool = False,
) -> StreamingResponse | JSONResponse:
    """
    处理 galgame / galgame_lock 分步生成，内部逻辑相同；对客户端暴露两种 HTTP 体协议：
    - Accept: application/json → 单次 JSON 响应，body 为 { protocol, mode, events }，与历史 line 装帧一一对应。
    - 否则：兼容旧 line-oriented text/event-stream（无 token 分片，装帧为历史端兼容）。
    release_lock 由生成器在 finally 中调用。
    """
    # 分步 env/body_state/thoughts 目标字数由导演 JSON 的 word_limits 决定；此处仅作导演缺省时的回退基准
    retry_scene_word_limit = 100

    async def galgame_sse_stream():
        q: asyncio.Queue = asyncio.Queue()
        job_start_time = time.time()

        async def _emit(obj: dict) -> None:
            await q.put(obj)

        async def _gal_step_callback(ev: str, payload: dict) -> None:
            if ev == "step":
                _lab = (payload.get("label") or "").strip()
                if _lab:
                    await _emit({"type": "step", "label": _lab})
            elif ev == "plan":
                await _emit({"type": "plan", "scene_fields": payload.get("scene_fields", [])})
            elif ev == "chunk":
                await _emit({"type": "chunk", "field": payload.get("field"), "content": payload.get("content", "")})
            elif ev == "metadata":
                row = {"type": "metadata"}
                row.update(payload)
                await _emit(row)
            elif ev == "options":
                await _emit({"type": "options", "options": payload.get("options")})

        async def _galgame_sse_body():
            from ..chat_modules.state import is_generation_cancelled, clear_generation_cancelled as _clear_cancel

            logger.info(
                "🔑 [galgame_sse] 启动: user=%s char=%s client_id=%r",
                username, character_id[:8] if character_id else "", client_id,
            )
            _meter_tok = set_galgame_meter_username(effective_username)
            try:
                if is_generation_cancelled(username, character_id, client_id):
                    await _emit({"type": "cancelled", "reason": "用户取消生成"})
                    return

                _game_type = "galgame_lock" if request.mode == "galgame_lock" else "galgame"
                _galgame_state = await load_galgame_state_async(request.username, request.character_id, game_type=_game_type)
                _current_score = 40
                try:
                    _current_score = int(_galgame_state.get("score", 40))
                except (ValueError, TypeError):
                    pass
                logger.info("📊 [分步生成] 读取当前分数: %s (mode=%s, game_type=%s)", _current_score, request.mode, _game_type)

                _step_char_profile = getattr(request, "_galgame_char_profile", "")
                if not _step_char_profile:
                    logger.warning("⚠️ [分步生成] request 中未找到预存的角色设定（_galgame_char_profile），精简系统提示将缺少角色身份")

                _step_sys_prompt = build_galgame_step_system_prompt(
                    char_profile=_step_char_profile,
                )

                _MAX_SCHEMA_RETRIES = 5
                result = None
                seq_generated: dict[str, str] = {}
                retry_code = ""
                retry_scope = "metadata_json_only"
                _last_options: list = []

                def _stream_cancel_check():
                    gen_cancelled = is_generation_cancelled(username, character_id, client_id)
                    if gen_cancelled:
                        logger.info(
                            "🛑 [cancel_check] 检测到取消信号: gen_cancelled=%s (user=%s char=%s client=%s)",
                            gen_cancelled, username, character_id[:8] if character_id else "", client_id,
                        )
                    return gen_cancelled

                for schema_attempt in range(_MAX_SCHEMA_RETRIES):
                    if _stream_cancel_check():
                        await _emit({"type": "cancelled", "reason": "用户取消生成"})
                        return
                    seq_result = ""
                    if schema_attempt > 0 and retry_code == "json_incomplete_schema" and seq_generated:
                        if retry_scope == "options_only" and result and result.get("raw"):
                            logger.info("🔗 [分步生成] 验证不完整，独立重试第9步（第%s/%s次）", schema_attempt + 1, _MAX_SCHEMA_RETRIES)
                            seq_result = result.get("raw", "")
                            _options = await _run_step9_options_only(
                                generated=seq_generated,
                                base_payload=payload,
                                api_url=api_url,
                                headers=headers,
                                provider=provider,
                                httpx_client=httpx_client,
                                request=request,
                                model_name=model_name,
                                is_schema_retry=True,
                                cancel_check=_stream_cancel_check,
                                active_model=active_model,
                                meta_context=parse_metadata_dict_for_options(
                                    (result or {}).get("raw")
                                ),
                            )
                            if _options:
                                seq_result = _inject_options_into_raw(seq_result, _options)
                            else:
                                logger.warning("🔗 [分步生成] 第9步独立重试未产出有效选项")
                        elif retry_scope == "metadata_json_only" and result and result.get("raw"):
                            logger.info("🔗 [分步生成] 验证不完整，独立重试第8步元数据（复用上次第9步选项，第%s/%s次）", schema_attempt + 1, _MAX_SCHEMA_RETRIES)
                            _error_detail = (result or {}).get("error", "字段不完整")
                            _hint = (
                                f"⚠️ 上次输出的 JSON 校验未通过：{_error_detail}。"
                                "请重新生成，确保所有必需的顶层字段（score/score_delta_reason/scene/relationship_stage/mood/"
                                "character_pose/player_pose/character_position/player_position/character_action/player_action/"
                                "character_gender/player_gender/character_race/player_race/character_outfit/player_outfit/"
                                "memory_tags/event_flags）"
                                "均存在且非空；memory_tags 必须为至少含 1 个非空中文短词的数组（禁止 []）；"
                                "event_flags 包含所有必需键。"
                            )
                            seq_result, seq_generated = await _run_step8_metadata_json(
                                base_payload=payload,
                                generated=seq_generated,
                                current_score=_current_score,
                                api_url=api_url,
                                headers=headers,
                                provider=provider,
                                httpx_client=httpx_client,
                                request=request,
                                model_name=model_name,
                                schema_retry_hint=_hint,
                                director_vitals=seq_generated.get("_director_vitals"),
                                cancel_check=_stream_cancel_check,
                                active_model=active_model,
                            )
                            if seq_result and _last_options:
                                seq_result = _inject_options_into_raw(seq_result, _last_options)
                    else:
                        if schema_attempt > 0:
                            logger.info("🔗 [分步生成] 验证不完整，重试第%s/%s次", schema_attempt + 1, _MAX_SCHEMA_RETRIES)
                        logger.info("🔗 [分步生成] 启用统一分步生成模式（含即时去重）")

                        _sc_cb = _gal_step_callback if schema_attempt == 0 else None
                        seq_result, seq_generated = await _sequential_galgame_generate(
                            base_payload=payload,
                            api_url=api_url,
                            headers=headers,
                            provider=provider,
                            httpx_client=httpx_client,
                            word_limit=retry_scene_word_limit,
                            request=request,
                            model_name=model_name,
                            current_score=_current_score,
                            step_system_prompt=_step_sys_prompt,
                            cancel_check=_stream_cancel_check,
                            active_model=active_model,
                            step_callback=_sc_cb,
                        )
                    if not seq_result:
                        logger.warning("🔗 [分步生成] 分步生成未产出有效结果")
                        await _emit({"type": "error", "message": "分步生成未产出有效结果"})
                        return
                    if is_generation_cancelled(username, character_id, client_id):
                        logger.info("🛑 [分步生成] 生成完成但用户已取消，跳过写库")
                        await _emit({"type": "cancelled", "reason": "用户取消生成"})
                        return
                    _log_stage = "RESPONSE" if schema_attempt == 0 else f"RESPONSE_RETRY_{schema_attempt}"
                    await save_chat_debug_log(request.username, request.character_id, request.mode, model_name, seq_result, _log_stage)
                    job_duration_ms = int((time.time() - job_start_time) * 1000)
                    _scene_text_keys = frozenset(("env", "body_state", "thoughts", "response"))
                    _generated_fields = frozenset(
                        k for k in _scene_text_keys
                        if seq_generated.get(k, "").strip()
                    )
                    result = await _handle_galgame_response(
                        request, seq_result, messages,
                        x_client_id=client_id, request_tokens=request_tokens,
                        generation_duration_ms=job_duration_ms,
                        generated_text_fields=_generated_fields,
                    )
                    if result.get("status") == "success":
                        logger.info("✅ [分步生成] 成功（用量与今日积分已在各步 call_llm_payload 中按用户计入）")
                        await _emit({"type": "result", "galgame_result": result})
                        return
                    retry_code = result.get("retry_code", "")
                    retry_err = str(result.get("error", "") or "")
                    if retry_code == "json_incomplete_schema" and schema_attempt < _MAX_SCHEMA_RETRIES - 1:
                        if "suggested_options" in retry_err:
                            retry_scope = "options_only"
                        else:
                            retry_scope = "metadata_json_only"
                        if retry_scope == "metadata_json_only" and result and result.get("raw"):
                            try:
                                _raw_body = _re.sub(
                                    r'<(?:think|thinking)>.*?</(?:think|thinking)>', '',
                                    result["raw"], flags=_re.DOTALL,
                                ).strip()
                                _parsed_opts = json.loads(_raw_body, strict=False).get("suggested_options", [])
                                if isinstance(_parsed_opts, list) and _parsed_opts:
                                    _last_options = _parsed_opts
                            except Exception:
                                pass
                        _scope_text = {"options_only": "仅第9步", "metadata_json_only": "仅第8步"}.get(retry_scope, retry_scope)
                        logger.warning("🔗 [分步生成] 验证失败: %s，将重试（%s）", retry_code, _scope_text)
                        continue
                    logger.warning("🔗 [分步生成] 验证失败: %s", retry_code or result.get("error", "unknown"))
                    await _emit({
                        "type": "error",
                        "message": result.get("error", "分步生成验证失败"),
                        "galgame_result": result if result.get("status") == "error" else None,
                    })
                    return
            except _GenerationCancelled:
                logger.info("🛑 [分步生成] 用户取消，已中止")
                await _emit({"type": "cancelled", "reason": "用户取消生成"})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("Galgame SSE failed: %s", e)
                await _emit({"type": "error", "message": str(e)})
            finally:
                reset_galgame_meter_username(_meter_tok)

        async def _runner():
            try:
                await asyncio.wait_for(_galgame_sse_body(), timeout=GALGAME_JOB_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning(
                    "⏱️ [galgame_sse] 整轮生成超过 %ss，已中止",
                    int(GALGAME_JOB_TIMEOUT_SECONDS),
                )
                await _emit({"type": "error", "message": "generation_timeout", "recovery_source": "generation_timeout"})
            finally:
                await q.put(None)

        from ..background_jobs import create_tracked_task

        task = create_tracked_task(
            _runner(),
            job_id=f"galgame:{username}:{character_id}:{int(time.time() * 1000)}",
            kind="galgame_sse",
        )
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            from ..chat_modules.state import clear_generation_cancelled
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except Exception:
                task.cancel()
            clear_generation_cancelled(username, character_id, client_id)
            await release_lock()

    if use_json:
        acc: list[dict] = []
        async for packet in galgame_sse_stream():
            t = (packet or "").strip()
            if t.startswith("data: "):
                d = t[6:].strip()
                if d == "[DONE]":
                    break
                acc.append(json.loads(d, strict=False))
        return JSONResponse(
            {
                "protocol": "ponychat_chat_v1",
                "mode": (request.mode or "galgame"),
                "events": acc,
            }
        )

    return StreamingResponse(galgame_sse_stream(), media_type="text/event-stream")
