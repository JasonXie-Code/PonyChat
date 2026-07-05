from __future__ import annotations


def _build_normal_stage3_base_messages(messages: list) -> list:
    """Build the raw-free base message list for normal Step 3.

    Step 3 is an execution-only reply writer. It should see the current user
    message plus compact Step 2 materials injected later, not raw memories or
    full character profiles that belong to earlier planning steps.
    """
    keep_system_prefixes = (
        "【对话背景】",
        "【系统信息",
        "【当前为网页体验版对话",
    )
    base: list = []
    for msg in messages or []:
        if not isinstance(msg, dict) or msg.get("role") != "system":
            continue
        content = str(msg.get("content") or "").lstrip()
        if any(content.startswith(prefix) for prefix in keep_system_prefixes):
            base.append(dict(msg))

    last_user = next(
        (
            msg
            for msg in reversed(messages or [])
            if isinstance(msg, dict) and msg.get("role") == "user"
        ),
        None,
    )
    if last_user is not None:
        base.append(dict(last_user))
    return base


async def handle_normal_nonstream_sse(
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
    chat_request_log_params: dict | None = None,
) -> StreamingResponse | JSONResponse:
    """
    处理 normal 模式：一次 LLM 非流式调用，结果通过「HTTP 体协议」回传。
    - Accept: application/json → 单次 application/json 响应，body 为 { protocol, mode, events }，与旧 line 协议一一对应。
    - 否则：兼容旧 line-oriented（text/event-stream）封装（内部仍无 token 分片，仅装帧与历史客户端一致）。
    """
    voice_character_id = effective_speaker_character_id(request) or character_id
    is_internal_proactive = bool(getattr(request, "_normal_internal_proactive_trigger", False))
    proactive_debug_params = (
        getattr(request, "_normal_proactive_debug_params", None)
        if is_internal_proactive
        else None
    )
    if not isinstance(proactive_debug_params, dict):
        proactive_debug_params = {}
    _speaker_event_fields = speaker_event_fields(request)
    last_user_msg = next(
        (
            m for m in reversed(getattr(request, "messages", None) or [])
            if getattr(m, "role", None) == "user"
        ),
        None,
    )
    accepted_job_id = (
        str(getattr(request, "_normal_accepted_job_id", "") or "").strip()
        or f"chatjob_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    )
    accepted_already_streamed = bool(getattr(request, "_normal_accepted_already_streamed", False))
    accepted_evt = {
        "type": "accepted",
        "job_id": accepted_job_id,
        "conversation_id": getattr(request, "conversation_id", None),
        "client_message_id": getattr(last_user_msg, "message_id", None) if last_user_msg else None,
        "accepted_at_ms": int(time.time() * 1000),
    }
    async def response_lines():
        delivery_marked = False
        delivery_username = username
        delivery_character_id = character_id
        delivery_conversation_id = getattr(request, "conversation_id", None) or ""
        try:
            try:
                from .message_delivery_order import mark_conversation_delivery_active
                mark_conversation_delivery_active(
                    delivery_username,
                    delivery_character_id,
                    delivery_conversation_id,
                )
                delivery_marked = bool(delivery_conversation_id)
            except Exception as _order_err:
                logger.debug("[DeliveryOrder] mark active skipped: %s", _order_err)
            _effective_log_params = chat_request_log_params
            raw_res = ""
            full_raw_res = ""
            resp_json: dict = {}
            inp_tok = 0
            out_tok = 0
            gen_start_ms = int(time.time() * 1000)
            generation_token = getattr(request, "_generation_token", None)
            async def _write_direct_guest_group_memory(assistant_text: str = "") -> None:
                await write_guest_direct_memory_once(request, assistant_text or "")
            class _NormalGenerationSuperseded(Exception):
                def __init__(self, stage: str):
                    super().__init__(stage)
                    self.stage = stage
            def _is_normal_generation_current() -> bool:
                return is_generation_current(username, character_id, client_id, generation_token)
            def _cancelled_packet(stage: str) -> str:
                logger.info(
                    "[normal_nonstream] 旧 normal 请求在阶段边界失效，停止生成 job_id=%s user=%s char=%s token=%s stage=%s",
                    accepted_job_id,
                    username,
                    character_id,
                    generation_token,
                    stage,
                )
                return (
                    "data: "
                    + json.dumps(
                        {
                            "type": "cancelled",
                            "job_id": accepted_job_id,
                            "reason": "superseded_by_new_user_message",
                            "stage": stage,
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
            def _raise_if_superseded(stage: str) -> None:
                if not _is_normal_generation_current():
                    raise _NormalGenerationSuperseded(stage)
            async def _await_generation_stage(awaitable, stage: str):
                task = asyncio.ensure_future(awaitable)
                try:
                    while not task.done():
                        if not _is_normal_generation_current():
                            task.cancel()
                            try:
                                await task
                            except asyncio.CancelledError:
                                pass
                            raise _NormalGenerationSuperseded(stage)
                        await asyncio.sleep(0.2)
                    return await task
                except asyncio.CancelledError:
                    task.cancel()
                    raise
            try:
                _raise_if_superseded("NORMAL_STEP_3_START")
            except _NormalGenerationSuperseded as superseded:
                yield _cancelled_packet(superseded.stage)
                yield "data: [DONE]\n\n"
                return
            planner_result = getattr(request, "_normal_planner_result", None) or {}
            if int(planner_result.get("bubble_count") or 0) <= 0:
                speech_reason = str(planner_result.get("speech_reason") or "").strip()
                for attr_name in (
                    "_assistant_reply_sequence",
                    "_assistant_asset_by_request_id",
                    "_assistant_asset_attachments",
                    "_assistant_asset_message_ids",
                    "_assistant_asset_message_ids_by_request_id",
                    "_assistant_message_meta",
                    "_assistant_asset_message_meta",
                ):
                    if hasattr(request, attr_name):
                        try:
                            delattr(request, attr_name)
                        except Exception:
                            setattr(request, attr_name, None)
                logger.info(
                    "[normal_nonstream] 发言积极性派生为 0 气泡，本轮不即时回复 conv=%s reason=%s",
                    getattr(request, "conversation_id", None),
                    speech_reason or "未填写",
                )
                save_ok, save_msg, _ = await run_conversation_persistence(
                    request,
                    model_name,
                    "",
                    gen_start_ms,
                    persist_user_only=True,
                )
                if save_ok:
                    await _write_direct_guest_group_memory("")
                yield f"data: {json.dumps({'type': 'no_reply', 'reason': speech_reason}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'save_status', 'success': save_ok, 'message': save_msg or ''}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
            def _rewrite_last_description_shortcut_user(msgs: list) -> tuple[list, bool, str, str, bool]:
                """把合法快捷请求转成主模型更不易误解的人称。"""
                new = list(msgs)
                for i in range(len(new) - 1, -1, -1):
                    if isinstance(new[i], dict) and new[i].get("role") == "user":
                        old = str(new[i].get("content") or "")
                        character_species = stage3_character_species or _extract_current_character_species_from_messages(new)
                        rewritten = _normalize_description_shortcut_user_message(
                            old,
                            character_species=character_species,
                        )
                        if rewritten != old:
                            item = dict(new[i])
                            item["content"] = rewritten
                            new[i] = item
                            is_story_progression = _is_story_progression_shortcut_text(old)
                            return (
                                new,
                                not is_story_progression,
                                character_species,
                                _description_shortcut_target(old) if not is_story_progression else "",
                                is_story_progression,
                            )
                        return new, False, "", "", False
                return new, False, "", "", False
            _conv_id = getattr(request, "conversation_id", None) or ""
            stage3_character_species_explicit = _extract_explicit_current_character_species_from_messages(payload.get("messages"))
            stage3_character_species = stage3_character_species_explicit or _extract_current_character_species_from_messages(payload.get("messages"))
            payload["messages"] = _build_normal_stage3_base_messages(payload.get("messages") or [])
            voice_reply_base_payload = copy.deepcopy(payload)
            payload["messages"] = _inject_sys_before_last_user(
                payload["messages"], NORMAL_STAGE3_MINIMAL_REPLY_GUARD
            )
            logger.debug("🧭 [NormalStage3] 已注入最小主回复守门")
            (
                payload["messages"],
                _description_shortcut_rewritten,
                _description_shortcut_character_species,
                _description_shortcut_target_name,
                _story_progression_shortcut_rewritten,
            ) = _rewrite_last_description_shortcut_user(
                payload["messages"]
            )
            if _description_shortcut_rewritten or _story_progression_shortcut_rewritten:
                payload["thinking"] = {"type": "disabled"}
                payload.pop("reasoning_effort", None)
                payload.pop("reasoning", None)
                if isinstance(_effective_log_params, dict):
                    _effective_log_params = {
                        **_effective_log_params,
                        "enable_thinking": False,
                        "thinking_depth": None,
                    }
                logger.debug("🧭 [合法快捷请求] 已规范化最后 user 消息，避免主模型误认自身身份")
            _main_reply_thinking_enabled = _payload_thinking_enabled(payload, _effective_log_params)
            if _main_reply_thinking_enabled:
                try:
                    from .character import NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT
                    payload["messages"] = _inject_sys_before_last_user(
                        payload["messages"], NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT
                    )
                    logger.debug("🧭 [普通对话思考人称守门] 已注入（内部思考人称校验 system）")
                except Exception as _reasoning_guard_err:
                    logger.debug("🧭 [普通对话思考人称守门] 注入失败（跳过）: %s", _reasoning_guard_err)
            else:
                logger.debug("🧭 [普通对话思考人称守门] 思考未开启，跳过注入")
            _planner_block = getattr(request, "_planner_augment_block", None) or ""
            if _planner_block:
                payload["messages"] = _inject_sys_before_last_user(payload["messages"], _planner_block)
                logger.debug("🎬 [导演策略] 已注入（最后 system）")
            if getattr(request, "_normal_dead_spirit_reply", False):
                payload["messages"] = _inject_sys_before_last_user(
                    payload["messages"],
                    NORMAL_DEAD_SPIRIT_STAGE3_GUARD,
                )
                logger.debug("👻 [NormalLifecycle] 已注入死亡后 @ 主角色灵魂回复硬约束")
            if _description_shortcut_rewritten:
                payload["messages"] = _inject_sys_before_last_user(
                    payload["messages"],
                    _description_shortcut_stage3_contract(
                        character_species=_description_shortcut_character_species,
                        target=_description_shortcut_target_name,
                    ),
                )
                logger.debug("🧭 [描写回合硬性输出合同] 已注入（覆盖普通聊天台词规则）")
            if _story_progression_shortcut_rewritten:
                payload["messages"] = _inject_sys_before_last_user(
                    payload["messages"],
                    _story_progression_shortcut_guidance(),
                )
                logger.debug("🎬 [推进剧情快捷请求] 已注入剧情推进合同")
            stage3_expected_bubbles = _normal_stage3_expected_bubble_count(planner_result)
            stage3_reply_level = _normal_stage3_reply_level_from_planner(planner_result)
            stage3_action_style = str(planner_result.get("action_style") or "plain_text").strip().lower()
            if stage3_action_style not in {"plain_text", "light_inline", "cinematic"}:
                stage3_action_style = "plain_text"
            stage3_structured_output = True
            payload["response_format"] = {"type": "json_object"}
            stage3_source_text = _normal_stage3_source_text_from_messages(payload.get("messages"))
            payload["messages"] = _inject_sys_before_last_user(
                payload["messages"],
                _normal_stage3_json_output_protocol(
                    planner_result,
                    character_species=stage3_character_species,
                    character_species_from_profile=bool(stage3_character_species_explicit),
                ),
            )
            logger.debug(
                "🧩 [NormalStage3] 已启用结构化 bubbles 输出协议 expected=%s level=%s",
                stage3_expected_bubbles,
                stage3_reply_level,
            )
            skip_main_reply_generation = is_asset_only_reply_sequence_with_assets(
                getattr(request, "_assistant_reply_sequence", None),
                attachment_by_request_id=getattr(request, "_assistant_asset_by_request_id", None) or {},
                fallback_attachments=list(getattr(request, "_assistant_asset_attachments", None) or []),
            )
            if skip_main_reply_generation:
                logger.info(
                    "[Assets] 本轮 reply_sequence 只有真实表情包/贴纸，跳过 Step3 主文本生成 conv=%s",
                    str(getattr(request, "conversation_id", "") or "")[:12],
                )
            try:
                _raise_if_superseded("NORMAL_STEP_3_BEFORE_MODEL")
            except _NormalGenerationSuperseded as superseded:
                yield _cancelled_packet(superseded.stage)
                yield "data: [DONE]\n\n"
                return
            voice_reply_generated = False
            if getattr(request, "voice_enabled", None) is False and isinstance(planner_result, dict):
                previous_voice = planner_result.get("voice_reply") if isinstance(planner_result.get("voice_reply"), dict) else {}
                previous_reason = str((previous_voice or {}).get("reason") or "").strip()
                planner_result = {
                    **planner_result,
                    "voice_reply": {
                        **(previous_voice or {}),
                        "enabled": False,
                        "reason": (
                            "当前客户端禁用语音，后端直接返回文本回复。"
                            + (f" 原导演原因：{previous_reason}" if previous_reason else "")
                        ),
                    },
                }
            try:
                from .voice_messages import (
                    chat_voice_service_enabled,
                    force_text_reply_when_chat_voice_disabled,
                    planner_voice_reply_enabled as _planner_voice_enabled,
                )
                planner_result = force_text_reply_when_chat_voice_disabled(planner_result)
                _director_voice_enabled = _planner_voice_enabled(planner_result) and chat_voice_service_enabled()
            except Exception:
                _director_voice_enabled = False
            if _director_voice_enabled and not skip_main_reply_generation:
                try:
                    from .normal_voice_reply import generate_normal_voice_reply
                    voice_reply_result = await _await_generation_stage(
                        generate_normal_voice_reply(
                            request=request,
                            base_payload=voice_reply_base_payload,
                            active_model=active_model or {},
                            api_url=api_url,
                            headers=headers,
                            httpx_client=httpx_client,
                            planner_result=planner_result,
                        ),
                        "NORMAL_STEP_3_VOICE_REPLY",
                    )
                    raw_res = voice_reply_result.raw_text
                    full_raw_res = raw_res
                    resp_json = voice_reply_result.raw_response or {}
                    inp_tok = voice_reply_result.usage_input
                    out_tok = voice_reply_result.usage_output
                    if inp_tok == 0 and out_tok == 0:
                        inp_tok = request_tokens
                        out_tok = estimate_output_tokens(full_raw_res)
                    setattr(
                        request,
                        "_normal_voice_sentences_by_text_index",
                        voice_reply_result.voice_sentences_by_text_index,
                    )
                    voice_reply_generated = True
                    logger.info(
                        "[VoiceReply] director voice step ready conv=%s text_chars=%s voice_paragraphs=%s",
                        str(getattr(request, "conversation_id", None) or "")[:12],
                        len(raw_res),
                        len(voice_reply_result.voice_sentences_by_text_index),
                    )
                    if effective_username and full_raw_res.strip():
                        try:
                            users = get_users_dao()
                            await users.increment_usage(effective_username, inp_tok, out_tok, llm_api_calls=1)
                            await get_membership_dao().increment_by(effective_username, 1)
                        except Exception as usage_err:
                            logger.warning(f"⚠️ 累计用户用量失败: {usage_err}")
                    try:
                        _raise_if_superseded("NORMAL_STEP_3_VOICE_REPLY_DONE")
                    except _NormalGenerationSuperseded as superseded:
                        yield _cancelled_packet(superseded.stage)
                        yield "data: [DONE]\n\n"
                        return
                except _NormalGenerationSuperseded as superseded:
                    yield _cancelled_packet(superseded.stage)
                    yield "data: [DONE]\n\n"
                    return
                except Exception as voice_reply_err:
                    logger.error("[VoiceReply] dedicated voice step failed; no text fallback: %s", voice_reply_err)
                    yield f"data: {json.dumps({'error': '聊天生成失败'}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
            if _effective_log_params is not None and not voice_reply_generated and not skip_main_reply_generation:
                _lp = normal_role_debug_params(
                    request,
                    {
                        **_effective_log_params,
                        **proactive_debug_params,
                        "note": "普通对话：与实际上游一致（原始记忆已在 Step2 压缩为主回复素材包，Step3 messages 仅保留当前 user 与压缩素材）",
                        "speaker_character_id": voice_character_id,
                        "pipeline": (
                            proactive_debug_params.get("pipeline")
                            if is_internal_proactive
                            else "normal_main_reply"
                        ) or "normal_proactive_core",
                    },
                )
                try:
                    await save_chat_debug_log(
                        request.username,
                        request.character_id,
                        request.mode,
                        model_name,
                        copy.deepcopy(payload),
                        (
                            "NORMAL_PROACTIVE_GENERATION_REQUEST"
                            if is_internal_proactive
                            else "NORMAL_STEP_3_MAIN_REPLY_REQUEST"
                        ),
                        params=_lp,
                    )
                except Exception as _req_log_err:
                    logger.warning("保存 REQUEST 调试日志失败: %s", _req_log_err)
            stage3_structure_retry_count = 0
            while not voice_reply_generated and not skip_main_reply_generation:
                try:
                    llm_res = await _await_generation_stage(
                        call_llm_payload(
                            payload,
                            active_model or {},
                            task=str(request.mode or "normal"),
                            httpx_client=httpx_client,
                            request_payload_final=True,
                            api_url=api_url,
                            headers=headers,
                        ),
                        "NORMAL_STEP_3_MAIN_REPLY",
                    )
                except _NormalGenerationSuperseded as superseded:
                    yield _cancelled_packet(superseded.stage)
                    yield "data: [DONE]\n\n"
                    return
                except httpx.HTTPStatusError as status_err:
                    status_code = status_err.response.status_code if status_err.response is not None else 0
                    err_msg = status_err.response.text if status_err.response is not None else str(status_err)
                    logger.error(f"❌ [normal_nonstream] LLM 返回错误状态 {status_code}: {err_msg}")
                    yield f"data: {json.dumps({'error': err_msg}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                except httpx.RequestError as req_err:
                    logger.error(f"❌ [normal_nonstream] 网络请求失败: {req_err}")
                    yield f"data: {json.dumps({'error': f'Network Error: {str(req_err)}'}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                resp_json = llm_res.raw_response
                reasoning = llm_res.reasoning or ""
                raw_res = sanitize_assistant_strip_thinking_blocks(
                    sanitize_assistant_strip_markers(llm_res.text or "", active_model)
                )
                stage3_json_error = ""
                stage3_structured_meta: dict = {}
                stage3_structured_unusable = False
                if stage3_structured_output:
                    parsed_res, stage3_structured_meta, stage3_json_error = _coerce_normal_stage3_bubbles(
                        raw_res,
                        expected_count=stage3_expected_bubbles,
                        action_style=stage3_action_style,
                        reply_level=stage3_reply_level,
                        planner_result=planner_result,
                        stage3_source_text=stage3_source_text,
                    )
                    if not stage3_json_error:
                        raw_res = parsed_res
                    else:
                        hard_visible_error = _normal_stage3_error_requires_retry(stage3_json_error)
                        if hard_visible_error:
                            raw_res = ""
                            stage3_structured_meta = {"hard_visible_error": stage3_json_error}
                            stage3_structured_unusable = True
                        else:
                            fallback_res, fallback_meta = _best_effort_normal_stage3_bubbles(
                                raw_res,
                                expected_count=stage3_expected_bubbles,
                            )
                            if fallback_res:
                                raw_res = fallback_res
                                stage3_structured_meta = fallback_meta
                            else:
                                raw_res = ""
                                stage3_structured_meta = fallback_meta
                                stage3_structured_unusable = True
                raw_res = _sanitize_normal_visible_reply(
                    raw_res,
                    single_bubble=stage3_expected_bubbles == 1,
                )
                stage3_language_error = _normal_stage3_language_violation_reason(
                    raw_res,
                    planner_result,
                )
                if stage3_language_error:
                    stage3_json_error = stage3_json_error or stage3_language_error
                    stage3_structured_meta = {
                        **(stage3_structured_meta or {}),
                        "language_contract_violation": stage3_language_error,
                    }
                    stage3_structured_unusable = True
                    raw_res = ""
                if stage3_structured_output and raw_res.strip() and _looks_like_stage3_json_scaffold(raw_res):
                    repaired_res, repaired_meta = _best_effort_normal_stage3_bubbles(
                        raw_res,
                        expected_count=stage3_expected_bubbles,
                    )
                    if repaired_res and not _looks_like_stage3_json_scaffold(repaired_res):
                        raw_res = _sanitize_normal_visible_reply(
                            repaired_res,
                            single_bubble=stage3_expected_bubbles == 1,
                        )
                        stage3_structured_meta = {
                            **(stage3_structured_meta or {}),
                            **repaired_meta,
                            "json_scaffold_repaired_after_sanitize": True,
                        }
                    else:
                        stage3_structured_unusable = True
                        stage3_json_error = stage3_json_error or "Stage3 JSON scaffold leaked into visible reply."
                        stage3_structured_meta = {
                            **(stage3_structured_meta or {}),
                            **(repaired_meta or {}),
                            "json_scaffold_unrepairable": True,
                        }
                        raw_res = ""
                setattr(request, "_normal_stage3_handoff", {})
                full_raw_res = raw_res
                if reasoning:
                    full_raw_res = f"<think>\n{reasoning}\n</think>\n{raw_res}"
                await save_chat_debug_log(
                    request.username,
                    request.character_id,
                    request.mode,
                    model_name,
                    _build_main_response_debug_payload(
                        raw_response=resp_json,
                        content=raw_res,
                        reasoning=reasoning,
                        full_raw_content=full_raw_res,
                        request_tokens_estimate=request_tokens,
                    ),
                    (
                        "NORMAL_PROACTIVE_GENERATION_RESPONSE"
                        if is_internal_proactive
                        else "NORMAL_STEP_3_MAIN_REPLY_RESPONSE"
                    ),
                    params=normal_role_debug_params(
                        request,
                        {
                            **(_effective_log_params or {}),
                            **proactive_debug_params,
                            "pipeline": (
                                proactive_debug_params.get("pipeline")
                                if is_internal_proactive
                                else "normal_main_reply"
                            ) or "normal_proactive_core",
                            "conversation_id": getattr(request, "conversation_id", None),
                            "client_id": client_id,
                            "json_protocol": bool(use_json),
                            "speaker_character_id": voice_character_id,
                            "structured_output": stage3_structured_output,
                            "expected_bubbles": stage3_expected_bubbles,
                            "reply_level": stage3_reply_level,
                            "reply_level_label": _normal_reply_level_label(stage3_reply_level),
                            "action_style": stage3_action_style,
                            "structured_output_meta": stage3_structured_meta,
                            "structured_output_error": stage3_json_error,
                            "structure_retry_count": stage3_structure_retry_count,
                            "max_structure_retries": _MAX_STAGE3_STRUCTURE_RETRIES,
                        },
                    ),
                )
                if effective_username and full_raw_res.strip():
                    inp_tok, out_tok = extract_usage_from_response(resp_json)
                    if inp_tok == 0 and out_tok == 0:
                        inp_tok = request_tokens
                        out_tok = estimate_output_tokens(full_raw_res)
                    try:
                        users = get_users_dao()
                        await users.increment_usage(effective_username, inp_tok, out_tok, llm_api_calls=1)
                        await get_membership_dao().increment_by(effective_username, 1)
                    except Exception as usage_err:
                        logger.warning(f"⚠️ 累计用户用量失败: {usage_err}")
                try:
                    _raise_if_superseded("NORMAL_STEP_3_MAIN_REPLY_DONE")
                except _NormalGenerationSuperseded as superseded:
                    yield _cancelled_packet(superseded.stage)
                    yield "data: [DONE]\n\n"
                    return
                if stage3_structured_unusable:
                    logger.error("❌ [normal_nonstream] Stage3 结构化输出无法提取可见正文：%s", stage3_json_error)
                    if stage3_structure_retry_count < _MAX_STAGE3_STRUCTURE_RETRIES:
                        stage3_structure_retry_count += 1
                        payload["messages"] = _inject_sys_before_last_user(
                            payload["messages"],
                            "【结构修正重试】"
                            "上一次回复的结构或可见正文不符合本轮 Step 3 合同，后端无法安全交付给用户。"
                            "请只重新输出一个合法 JSON object，不要写 Markdown，不要写解释，不要输出 JSON 片段。"
                            f"上一次不合格原因：{stage3_json_error or '结构或正文不符合本轮约束'}。"
                            "必须包含 bubble_count、bubbles、used_facts；"
                            "bubbles 数组长度必须等于 bubble_count，每项必须包含 index/type/parts/purpose；"
                            "parts 必须是非空数组，每个 part 必须包含 kind/text；"
                            "kind=speech 表示角色说出口的台词，其他 kind 表示后端要加全角括号的补充描写；"
                            "parts[*].text 内部不得换行，也不得自己写括号。"
                            f"本轮 bubble_count 必须等于 {stage3_expected_bubbles}。",
                        )
                        logger.warning(
                            "🔁 [normal_nonstream] Stage3 结构本地修复失败，执行结构修正重试 %s/%s：%s",
                            stage3_structure_retry_count,
                            _MAX_STAGE3_STRUCTURE_RETRIES,
                            stage3_json_error,
                        )
                        continue
                    yield f"data: {json.dumps({'error': '聊天生成失败'}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                clean_content = re.sub(
                    r'<(?:think|thinking)>.*?</(?:think|thinking)>', '',
                    full_raw_res, flags=re.DOTALL,
                ).strip()
                _asset_only_reply = is_asset_only_reply_sequence_with_assets(
                    getattr(request, "_assistant_reply_sequence", None),
                    attachment_by_request_id=getattr(request, "_assistant_asset_by_request_id", None) or {},
                    fallback_attachments=list(getattr(request, "_assistant_asset_attachments", None) or []),
                )
                if len(clean_content) == 0 and not _asset_only_reply:
                    logger.error("❌ [normal_nonstream] 单次生成返回空正文或仅思维链")
                    yield f"data: {json.dumps({'error': '聊天生成失败'}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                if stage3_json_error:
                    logger.warning(
                        "⚠️ [normal_nonstream] Stage3 结构化输出不合格，已本地兜底修复：%s",
                        stage3_json_error,
                    )
                break
            try:
                _raise_if_superseded("NORMAL_STEP_3_BEFORE_SIDE_EFFECTS")
            except _NormalGenerationSuperseded as superseded:
                yield _cancelled_packet(superseded.stage)
                yield "data: [DONE]\n\n"
                return
            setattr(request, "_normal_handoff_router_result", {})
            if (
                getattr(request, "_normal_enable_stage3_handoff_events", False)
                and raw_res.strip()
                and _normal_handoff_router_has_recent_non_main_speaker(
                    request,
                    current_character_id=voice_character_id,
                )
            ):
                _handoff_candidates = _normal_stage3_handoff_candidates(
                    request,
                    current_character_id=voice_character_id,
                )
                if _handoff_candidates:
                    _router_cfg = model_manager.get_model_for_task("chat_router") or active_model or model_manager.get_active_model() or {}
                    try:
                        _handoff_router_result = await _await_generation_stage(
                            run_normal_handoff_router_decision(
                                request,
                                _router_cfg,
                                current_reply_text=raw_res,
                                current_character_id=voice_character_id,
                                current_character_name=speaker_display_name(request),
                                candidates=_handoff_candidates,
                                username=request.username,
                                character_id=request.character_id,
                                debug_mode=request.mode or "normal",
                            ),
                            "NORMAL_STEP_4_HANDOFF_ROUTER",
                        )
                        setattr(request, "_normal_handoff_router_result", _handoff_router_result or {})
                        if _handoff_router_result:
                            logger.info(
                                "[NormalHandoffRouter] handoff decided user=%s from=%s to=%s reason=%s",
                                request.username,
                                str(voice_character_id or "")[:12],
                                str(_handoff_router_result.get("reply_character_id") or "")[:12],
                                str(_handoff_router_result.get("reason") or "")[:120],
                            )
                    except _NormalGenerationSuperseded as superseded:
                        yield _cancelled_packet(superseded.stage)
                        yield "data: [DONE]\n\n"
                        return
                    except Exception as _handoff_router_err:
                        logger.debug("[NormalHandoffRouter] skipped after error: %s", _handoff_router_err)
            else:
                logger.debug(
                    "[NormalHandoffRouter] disabled enable=%s raw=%s recent_non_main=%s",
                    bool(getattr(request, "_normal_enable_stage3_handoff_events", False)),
                    bool(raw_res.strip()),
                    _normal_handoff_router_has_recent_non_main_speaker(
                        request,
                        current_character_id=voice_character_id,
                    ),
                )
            if raw_res.strip():
                _post = getattr(request, "_normal_image_post", None)
                if isinstance(_post, dict):
                    try:
                        from .image_context_store import (
                            append_from_vision_fields,
                            set_last_reply_based_on_image,
                        )
                        _af = _post.get("append_fields")
                        if isinstance(_af, dict) and _af:
                            await append_from_vision_fields(
                                _post.get("username"),
                                _post.get("character_id"),
                                _post.get("conversation_id"),
                                user_text=_af.get("user_text", "") or "",
                                image_count=int(_af.get("image_count") or 0),
                                should_refuse=bool(_af.get("should_refuse")),
                                image_summary=_af.get("image_summary") or "",
                                visible_text=_af.get("visible_text") or "",
                                identified_entities=_af.get("identified_entities"),
                                uncertainty=_af.get("uncertainty") or "",
                                error=_af.get("error") or "",
                            )
                        if isinstance(_post.get("last_reply_based_on_image"), bool):
                            await set_last_reply_based_on_image(
                                _post.get("username"),
                                _post.get("character_id"),
                                _post.get("conversation_id"),
                                _post["last_reply_based_on_image"],
                            )
                    except Exception as _pimg:
                        logger.warning("🖼️ [NormalImage] 状态写入失败: %s", _pimg)
            try:
                _raise_if_superseded("NORMAL_STEP_3_BEFORE_METADATA")
            except _NormalGenerationSuperseded as superseded:
                yield _cancelled_packet(superseded.stage)
                yield "data: [DONE]\n\n"
                return
            if inp_tok == 0 and out_tok == 0 and not skip_main_reply_generation:
                inp_tok = request_tokens
                out_tok = estimate_output_tokens(full_raw_res)
            metadata_evt = {
                "metadata": {
                    "model": model_name,
                    "job_id": accepted_job_id,
                    "usage": {
                        "input_tokens": inp_tok,
                        "output_tokens": out_tok,
                    },
                }
            }
            yield f"data: {json.dumps(metadata_evt, ensure_ascii=False)}\n\n"
            if getattr(request, "crisis_hotline_enabled", True) is not False:
                from .state import CRISIS_KEYWORDS
                _last_user_msg = next(
                    (m for m in reversed(request.messages or []) if getattr(m, "role", "") == "user"),
                    None,
                )
                _user_text = str(getattr(_last_user_msg, "content", "") or "").strip() if _last_user_msg else ""
                if any(kw in _user_text for kw in CRISIS_KEYWORDS):
                    logger.info("🆘 [CrisisDetect] 检测到危机关键词，下发 crisis_triggered 事件")
                    yield f"data: {json.dumps({'type': 'crisis_triggered'}, ensure_ascii=False)}\n\n"
            try:
                _raise_if_superseded("NORMAL_STEP_3_BEFORE_PERSIST")
            except _NormalGenerationSuperseded as superseded:
                yield _cancelled_packet(superseded.stage)
                yield "data: [DONE]\n\n"
                return
            if is_internal_proactive:
                trigger_mid = str(getattr(request, "_normal_internal_trigger_message_id", "") or "").strip()
                for msg in getattr(request, "messages", None) or []:
                    if (
                        trigger_mid
                        and str(getattr(msg, "message_id", "") or "").strip() == trigger_mid
                    ):
                        try:
                            msg.isHidden = True
                        except Exception:
                            setattr(msg, "isHidden", True)
            try:
                defer_chat_complete_until_voice_ready = bool(voice_reply_generated)
                setattr(request, "_defer_chat_complete_until_voice_ready", defer_chat_complete_until_voice_ready)
                save_ok, save_msg, asst_ids = await _await_generation_stage(
                    run_conversation_persistence(request, model_name, full_raw_res, gen_start_ms),
                    "NORMAL_STEP_3_PERSIST",
                )
                _raise_if_superseded("NORMAL_STEP_3_PERSIST_DONE")
            except _NormalGenerationSuperseded as superseded:
                yield _cancelled_packet(superseded.stage)
                yield "data: [DONE]\n\n"
                return
            save_evt = {
                "type": "save_status",
                "success": save_ok,
                "message": save_msg or "",
            }
            if _speaker_event_fields:
                save_evt.update(_speaker_event_fields)
            if asst_ids:
                save_evt["assistant_message_ids"] = asst_ids
                save_evt["assistant_message_id"] = asst_ids[-1]  # 旧客户端兼容
            asst_meta = list(getattr(request, "_assistant_message_meta", None) or [])
            asset_meta = list(getattr(request, "_assistant_asset_message_meta", None) or [])
            if asst_meta:
                save_evt["assistant_messages"] = asst_meta
            if asset_meta:
                save_evt["assistant_assets"] = asset_meta
            units = build_assistant_units(
                raw_res,
                reply_sequence=getattr(request, "_assistant_reply_sequence", None),
                attachment_by_request_id=getattr(request, "_assistant_asset_by_request_id", None) or {},
                fallback_attachments=list(getattr(request, "_assistant_asset_attachments", None) or []),
            )
            voice_sentences_by_text_index = getattr(request, "_normal_voice_sentences_by_text_index", None) or {}
            if isinstance(voice_sentences_by_text_index, dict) and voice_sentences_by_text_index:
                _voice_text_idx = 0
                for unit in units:
                    if unit.get("type") != "text":
                        continue
                    sentence_entries = voice_sentences_by_text_index.get(_voice_text_idx)
                    if isinstance(sentence_entries, list) and sentence_entries:
                        unit["voice_sentences"] = sentence_entries
                    _voice_text_idx += 1
            total_text = sum(1 for u in units if u.get("type") == "text")
            total_assets = sum(1 for u in units if u.get("type") == "asset")
            asset_msg_ids = list(getattr(request, "_assistant_asset_message_ids", None) or [])
            asset_msg_ids_by_request_id = getattr(request, "_assistant_asset_message_ids_by_request_id", None) or {}
            voice_results_by_message_id: dict[str, dict] = {}
            if save_ok and asst_meta and use_json:
                try:
                    from .voice_messages import prepare_voice_generation_for_messages
                    voice_results_by_message_id = await _await_generation_stage(
                        prepare_voice_generation_for_messages(
                            username=username,
                            character_id=voice_character_id,
                            conversation_id=getattr(request, "conversation_id", None) or "",
                            assistant_meta=asst_meta,
                            assistant_units=units,
                            planner_result=planner_result,
                        ),
                        "NORMAL_STEP_3_VOICE_PREPARE",
                    )
                except _NormalGenerationSuperseded as superseded:
                    yield _cancelled_packet(superseded.stage)
                    yield "data: [DONE]\n\n"
                    return
                except Exception as _voice_err:
                    logger.warning("[VoiceMsg] sync prepare failed: %s", _voice_err)
            async def _flush_deferred_chat_complete(message_id: str | None = None) -> None:
                if not defer_chat_complete_until_voice_ready:
                    return
                payloads = list(getattr(request, "_deferred_chat_complete_payloads", None) or [])
                if not payloads:
                    return
                target_mid = str(message_id or "").strip()
                remaining: list[dict] = []
                try:
                    from ..delivery_outbox import enqueue_chat_complete
                except Exception as _outbox_err:
                    logger.debug("[outbox] deferred chat_complete unavailable: %s", _outbox_err)
                    return
                for item in payloads:
                    if not isinstance(item, dict):
                        continue
                    item_mid = str(item.get("message_id") or "").strip()
                    if target_mid and item_mid != target_mid:
                        remaining.append(item)
                        continue
                    try:
                        send_item = dict(item)
                        voice_result = voice_results_by_message_id.get(item_mid)
                        if isinstance(voice_result, dict):
                            voice_state = voice_result.get("voice_state")
                            audio_transfer = voice_result.get("audio_transfer")
                            if isinstance(voice_state, dict) and voice_state:
                                send_item["voice_state"] = voice_state
                            if isinstance(audio_transfer, dict) and audio_transfer:
                                send_item["audio_transfer"] = audio_transfer
                        await enqueue_chat_complete(**send_item)
                    except Exception as _outbox_err:
                        remaining.append(item)
                        logger.debug("[outbox] deferred chat_complete skipped: %s", _outbox_err)
                setattr(request, "_deferred_chat_complete_payloads", remaining if target_mid else [])
            def _attach_voice_result(evt: dict) -> None:
                message_id = str(evt.get("id") or evt.get("message_id") or "").strip()
                if not message_id:
                    return
                result = voice_results_by_message_id.get(message_id)
                if not result:
                    return
                voice_state = result.get("voice_state")
                audio_transfer = result.get("audio_transfer")
                if voice_state and audio_transfer:
                    evt["voice_state"] = voice_state
                    evt["audio_transfer"] = audio_transfer
            def _attach_speaker_event(evt: dict) -> None:
                if _speaker_event_fields:
                    evt.update(_speaker_event_fields)
            def _message_part_delay_seconds(
                current_content: str,
                *,
                current_voice_result: dict | None = None,
            ) -> float:
                try:
                    from .voice_messages import voice_result_display_delay_seconds
                    voice_delay = voice_result_display_delay_seconds(current_voice_result, current_content)
                except Exception as exc:
                    logger.debug("[VoiceMsg] display delay helper failed: %s", exc)
                    voice_delay = None
                if voice_delay is not None:
                    return voice_delay
                return max(0.3, min(len(str(current_content or "")) / 10.0, 8.0)) + random.uniform(1.0, 3.0)
            delivery_schedule_base_ms = int(time.time() * 1000)
            next_display_at_server_ms = delivery_schedule_base_ms
            def _set_message_display_schedule(evt: dict, delay_seconds: float) -> None:
                nonlocal next_display_at_server_ms
                delay = max(0.0, float(delay_seconds or 0.0))
                evt["display_delay_seconds"] = round(delay, 3)
                evt["display_delay_ms"] = int(delay * 1000)
                next_display_at_server_ms += evt["display_delay_ms"]
                evt["display_at_server_ms"] = next_display_at_server_ms
                evt["server_now_ms"] = delivery_schedule_base_ms
            first_visible_delivery_pending = True
            def _consume_delivery_delay(delay_seconds: float) -> float:
                nonlocal first_visible_delivery_pending
                delay = max(0.0, float(delay_seconds or 0.0))
                if first_visible_delivery_pending:
                    first_visible_delivery_pending = False
                    return 0.0
                return delay
            voice_prepare_tasks_by_message_id: dict[str, asyncio.Task] = {}
            def _cancel_voice_prepare_tasks() -> None:
                for task in voice_prepare_tasks_by_message_id.values():
                    if not task.done():
                        task.cancel()
            if save_ok and asst_meta and not use_json:
                try:
                    from .voice_messages import prepare_voice_generation_for_message
                    _voice_text_idx = 0
                    for unit in units:
                        if unit.get("type") != "text":
                            continue
                        message_id = ""
                        if _voice_text_idx < len(asst_meta):
                            message_id = str(asst_meta[_voice_text_idx].get("message_id") or "").strip()
                        content = str(unit.get("content") or "").strip()
                        if message_id and content:
                            voice_prepare_tasks_by_message_id[message_id] = asyncio.create_task(
                                prepare_voice_generation_for_message(
                                    username=username,
                                    character_id=voice_character_id,
                                    conversation_id=getattr(request, "conversation_id", None) or "",
                                    message_id=message_id,
                                    content=content,
                                    voice_sentences=unit.get("voice_sentences") or [],
                                    planner_result=planner_result,
                                )
                            )
                        _voice_text_idx += 1
                except Exception as _voice_err:
                    logger.warning("[VoiceMsg] single prepare prewarm failed: %s", _voice_err)
            try:
                _raise_if_superseded("NORMAL_STEP_3_VOICE_PREPARE_STARTED")
            except _NormalGenerationSuperseded as superseded:
                _cancel_voice_prepare_tasks()
                yield _cancelled_packet(superseded.stage)
                yield "data: [DONE]\n\n"
                return
            async def _attach_voice_result_for_current_text(evt: dict, unit: dict) -> None:
                _raise_if_superseded("NORMAL_STEP_3_VOICE_ATTACH_START")
                message_id = str(evt.get("id") or evt.get("message_id") or "").strip()
                if not message_id and not save_ok:
                    message_id = f"msg_transient_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
                    evt["id"] = message_id
                    evt["message_id"] = message_id
                if not message_id:
                    return
                if message_id in voice_results_by_message_id:
                    _attach_voice_result(evt)
                    return
                task = voice_prepare_tasks_by_message_id.get(message_id)
                if task is not None:
                    try:
                        result = await _await_generation_stage(task, "NORMAL_STEP_3_VOICE_ATTACH")
                    except _NormalGenerationSuperseded:
                        raise
                    except Exception as _voice_err:
                        logger.warning("[VoiceMsg] single prewarmed prepare failed mid=%s: %s", message_id[:10], _voice_err)
                        return
                    if result:
                        voice_results_by_message_id[message_id] = result
                        _attach_voice_result(evt)
                    return
                try:
                    from .voice_messages import prepare_voice_generation_for_message
                    if save_ok:
                        result = await _await_generation_stage(
                            prepare_voice_generation_for_message(
                                username=username,
                                character_id=voice_character_id,
                                conversation_id=getattr(request, "conversation_id", None) or "",
                                message_id=message_id,
                                content=str(unit.get("content") or ""),
                                voice_sentences=unit.get("voice_sentences") or [],
                                planner_result=planner_result,
                            ),
                            "NORMAL_STEP_3_VOICE_ATTACH",
                        )
                    else:
                        from .voice_messages import (
                            _character_voice_config,
                            _reply_language_from_planner,
                            is_voice_lab_available,
                            planner_voice_reply_enabled,
                            synthesize_message_voice,
                        )
                        result = {}
                        if planner_voice_reply_enabled(planner_result) and is_voice_lab_available():
                            config = _character_voice_config(username, voice_character_id)
                            if config.get("enabled"):
                                result = await _await_generation_stage(
                                    synthesize_message_voice(
                                        username=username,
                                        character_id=voice_character_id,
                                        conversation_id=getattr(request, "conversation_id", None) or "transient",
                                        message_id=message_id,
                                        content=str(unit.get("content") or ""),
                                        voice_id=config.get("voice_id"),
                                        instruct=config.get("instruct") or "",
                                        voice_sentences=unit.get("voice_sentences") or [],
                                        reply_language=_reply_language_from_planner(planner_result),
                                        push_update=False,
                                        persist=False,
                                    ),
                                    "NORMAL_STEP_3_VOICE_ATTACH",
                                )
                                if result:
                                    logger.warning(
                                        "[VoiceMsg] transient voice attached after save failure conv=%s mid=%s",
                                        str(getattr(request, "conversation_id", "") or "")[:12],
                                        message_id[:10],
                                    )
                    if result:
                        _raise_if_superseded("NORMAL_STEP_3_VOICE_ATTACH_DONE")
                        voice_results_by_message_id[message_id] = result
                        _attach_voice_result(evt)
                except _NormalGenerationSuperseded:
                    raise
                except Exception as _voice_err:
                    logger.warning("[VoiceMsg] single prepare failed mid=%s: %s", message_id[:10], _voice_err)
            if use_json:
                try:
                    _raise_if_superseded("NORMAL_STEP_3_BEFORE_DELIVERY")
                except _NormalGenerationSuperseded as superseded:
                    _cancel_voice_prepare_tasks()
                    yield _cancelled_packet(superseded.stage)
                    yield "data: [DONE]\n\n"
                    return
                await _flush_deferred_chat_complete()
                if (
                    not skip_main_reply_generation
                    and _should_emit_json_compat_delta(voice_reply_generated=voice_reply_generated)
                ):
                    content_evt = {"choices": [{"delta": {"content": raw_res}}]}
                    yield f"data: {json.dumps(content_evt, ensure_ascii=False)}\n\n"
                text_idx = 0
                for unit in units:
                    if unit.get("type") != "text":
                        continue
                    para = str(unit.get("content") or "").strip()
                    if not para:
                        continue
                    para_evt: dict = {
                        "type": "assistant_paragraph",
                        "content": para,
                        "index": text_idx,
                        "total": total_text,
                    }
                    _attach_speaker_event(para_evt)
                    if asst_ids and text_idx < len(asst_ids):
                        para_evt["id"] = asst_ids[text_idx]
                    if text_idx < len(asst_meta):
                        meta = asst_meta[text_idx]
                        if meta.get("timestamp"):
                            para_evt["timestamp"] = meta.get("timestamp")
                        if meta.get("sequence_number") is not None:
                            para_evt["sequence_number"] = meta.get("sequence_number")
                    try:
                        await _attach_voice_result_for_current_text(para_evt, unit)
                        current_message_id = str(para_evt.get("id") or para_evt.get("message_id") or "").strip()
                        current_voice_result = voice_results_by_message_id.get(current_message_id)
                        delay_seconds = _message_part_delay_seconds(
                            para,
                            current_voice_result=current_voice_result,
                        )
                        delay_seconds = _consume_delivery_delay(delay_seconds)
                        _set_message_display_schedule(para_evt, delay_seconds)
                        _raise_if_superseded("NORMAL_STEP_3_BEFORE_EMIT_TEXT")
                    except _NormalGenerationSuperseded as superseded:
                        _cancel_voice_prepare_tasks()
                        yield _cancelled_packet(superseded.stage)
                        yield "data: [DONE]\n\n"
                        return
                    text_idx += 1
                    yield f"data: {json.dumps(para_evt, ensure_ascii=False)}\n\n"
                    await _flush_deferred_chat_complete(str(para_evt.get("id") or para_evt.get("message_id") or "").strip())
                asset_idx = 0
                for unit in units:
                    if unit.get("type") != "asset":
                        continue
                    attachment = unit.get("attachment")
                    if not isinstance(attachment, dict):
                        continue
                    rid = str(unit.get("request_id") or (attachment.get("metadata") or {}).get("request_id") or "")
                    asset_evt = {
                        "type": "assistant_asset",
                        "attachment": attachment,
                        "index": asset_idx,
                        "total": total_assets,
                    }
                    _attach_speaker_event(asset_evt)
                    if rid and rid in asset_msg_ids_by_request_id:
                        asset_evt["message_id"] = asset_msg_ids_by_request_id[rid]
                    elif asset_idx < len(asset_msg_ids):
                        asset_evt["message_id"] = asset_msg_ids[asset_idx]
                    if asset_idx < len(asset_meta):
                        meta = asset_meta[asset_idx]
                        if meta.get("timestamp"):
                            asset_evt["timestamp"] = meta.get("timestamp")
                        if meta.get("sequence_number") is not None:
                            asset_evt["sequence_number"] = meta.get("sequence_number")
                    try:
                        delay_seconds = _message_part_delay_seconds("")
                        delay_seconds = _consume_delivery_delay(delay_seconds)
                        _set_message_display_schedule(asset_evt, delay_seconds)
                        _raise_if_superseded("NORMAL_STEP_3_BEFORE_EMIT_ASSET")
                    except _NormalGenerationSuperseded as superseded:
                        _cancel_voice_prepare_tasks()
                        yield _cancelled_packet(superseded.stage)
                        yield "data: [DONE]\n\n"
                        return
                    asset_idx += 1
                    yield f"data: {json.dumps(asset_evt, ensure_ascii=False)}\n\n"
            else:
                text_idx = 0
                asset_idx = 0
                for i, unit in enumerate(units):
                    if unit.get("type") == "text":
                        para = str(unit.get("content") or "").strip()
                        if not para:
                            continue
                        para_evt: dict = {
                            "type": "assistant_paragraph",
                            "content": para,
                            "index": text_idx,
                            "total": total_text,
                        }
                        _attach_speaker_event(para_evt)
                        if asst_ids and text_idx < len(asst_ids):
                            para_evt["id"] = asst_ids[text_idx]
                        if text_idx < len(asst_meta):
                            meta = asst_meta[text_idx]
                            if meta.get("timestamp"):
                                para_evt["timestamp"] = meta.get("timestamp")
                            if meta.get("sequence_number") is not None:
                                para_evt["sequence_number"] = meta.get("sequence_number")
                        try:
                            await _attach_voice_result_for_current_text(para_evt, unit)
                            current_message_id = str(para_evt.get("id") or para_evt.get("message_id") or "").strip()
                            current_voice_result = voice_results_by_message_id.get(current_message_id)
                            delay_seconds = _message_part_delay_seconds(
                                para,
                                current_voice_result=current_voice_result,
                            )
                            delay_seconds = _consume_delivery_delay(delay_seconds)
                            _set_message_display_schedule(para_evt, delay_seconds)
                            _raise_if_superseded("NORMAL_STEP_3_BEFORE_EMIT_TEXT")
                        except _NormalGenerationSuperseded as superseded:
                            _cancel_voice_prepare_tasks()
                            yield _cancelled_packet(superseded.stage)
                            yield "data: [DONE]\n\n"
                            return
                        text_idx += 1
                        yield f"data: {json.dumps(para_evt, ensure_ascii=False)}\n\n"
                        await _flush_deferred_chat_complete(str(para_evt.get("id") or para_evt.get("message_id") or "").strip())
                    elif unit.get("type") == "asset":
                        attachment = unit.get("attachment")
                        if not isinstance(attachment, dict):
                            continue
                        rid = str(unit.get("request_id") or (attachment.get("metadata") or {}).get("request_id") or "")
                        asset_evt = {
                            "type": "assistant_asset",
                            "attachment": attachment,
                            "index": asset_idx,
                            "total": total_assets,
                        }
                        _attach_speaker_event(asset_evt)
                        if rid and rid in asset_msg_ids_by_request_id:
                            asset_evt["message_id"] = asset_msg_ids_by_request_id[rid]
                        elif asset_idx < len(asset_msg_ids):
                            asset_evt["message_id"] = asset_msg_ids[asset_idx]
                        if asset_idx < len(asset_meta):
                            meta = asset_meta[asset_idx]
                            if meta.get("timestamp"):
                                asset_evt["timestamp"] = meta.get("timestamp")
                            if meta.get("sequence_number") is not None:
                                asset_evt["sequence_number"] = meta.get("sequence_number")
                        try:
                            delay_seconds = _message_part_delay_seconds("")
                            delay_seconds = _consume_delivery_delay(delay_seconds)
                            _set_message_display_schedule(asset_evt, delay_seconds)
                            _raise_if_superseded("NORMAL_STEP_3_BEFORE_EMIT_ASSET")
                        except _NormalGenerationSuperseded as superseded:
                            _cancel_voice_prepare_tasks()
                            yield _cancelled_packet(superseded.stage)
                            yield "data: [DONE]\n\n"
                            return
                        asset_idx += 1
                        yield f"data: {json.dumps(asset_evt, ensure_ascii=False)}\n\n"
            await _flush_deferred_chat_complete()
            try:
                _raise_if_superseded("NORMAL_STEP_3_BEFORE_SAVE_STATUS")
            except _NormalGenerationSuperseded as superseded:
                _cancel_voice_prepare_tasks()
                yield _cancelled_packet(superseded.stage)
                yield "data: [DONE]\n\n"
                return
            yield f"data: {json.dumps(save_evt, ensure_ascii=False)}\n\n"
            handoff = getattr(request, "_normal_handoff_router_result", None)
            if (
                getattr(request, "_normal_enable_stage3_handoff_events", False)
                and isinstance(handoff, dict)
                and str(handoff.get("reply_character_id") or "").strip()
            ):
                yield f"data: {json.dumps({'type': 'normal_handoff_request', **handoff}, ensure_ascii=False)}\n\n"
            _last_user_for_guest_memory = next(
                (m for m in reversed(request.messages or []) if getattr(m, "role", "") == "user"),
                None,
            )
            _user_text_for_guest_memory = (
                str(getattr(_last_user_for_guest_memory, "content", "") or "").strip()
                if _last_user_for_guest_memory
                else ""
            )
            await _write_direct_guest_group_memory(raw_res)
            if save_ok and raw_res.strip():
                logger.info("💾 [normal_nonstream] 对话已写入数据库")
                if (getattr(request, "memory_enabled", True) is not False) and username and character_id:
                    try:
                        from ..memory.consolidator import register_chat_activity
                        register_chat_activity(username=username, character_id=character_id)
                        if is_guest_speaker(request) and voice_character_id != character_id:
                            register_chat_activity(username=username, character_id=voice_character_id)
                    except Exception as _solid_err:
                        logger.warning("🧠 [MemConsolidator] 注册普通对话活动失败: %s", _solid_err)
                _user_text = (
                    str(getattr(request, "_normal_internal_proactive_memory_user_message", "") or "").strip()
                    if is_internal_proactive
                    else _user_text_for_guest_memory
                ) or _user_text_for_guest_memory
                _main_postprocess_assistant_text = guest_main_memory_assistant_message(request, raw_res)
                if _conv_id and username and character_id:
                    try:
                        from ..db import get_database as _get_db2
                        from .normal_postprocess import schedule_normal_step4_memory_relation
                        _is_guest_turn = is_guest_speaker(request) and voice_character_id != character_id
                        _guest_group_memory_extract_specs: list[dict[str, Any]] = []
                        if _is_guest_turn:
                            try:
                                _guest_group_memory_extract_specs = await guest_group_memory_extract_specs(
                                    request,
                                    username=username,
                                    participant_ids=guest_group_participant_character_ids(request),
                                    latest_user_text=_user_text,
                                    assistant_text=raw_res,
                                )
                            except Exception as _guest_mem_spec_err:
                                logger.debug("[NormalSpeaker] 构造临时群聊记忆提取任务失败: %s", _guest_mem_spec_err)
                        schedule_normal_step4_memory_relation(
                            username=username,
                            character_id=character_id,
                            conversation_id=_conv_id,
                            user_message=_user_text,
                            assistant_message=_main_postprocess_assistant_text,
                            db=_get_db2(),
                            messages_for_bubbles=list(request.messages or []),
                            entry_at_ms=int(time.time() * 1000),
                            planner_memory_notes=getattr(request, "_planner_memory_notes", "") or "",
                            memory_enabled=(getattr(request, "memory_enabled", True) is not False),
                            extra_memory_extract_specs=_guest_group_memory_extract_specs,
                        )
                        if _is_guest_turn:
                            await ensure_guest_private_context(request)
                            _guest_private_conv_id = speaker_context_conversation_id(request)
                            if _guest_private_conv_id:
                                schedule_normal_step4_memory_relation(
                                    username=username,
                                    character_id=voice_character_id,
                                    conversation_id=_guest_private_conv_id,
                                    user_message=guest_memory_user_message(request, _user_text),
                                    assistant_message=raw_res,
                                    db=_get_db2(),
                                    messages_for_bubbles=list(request.messages or []),
                                    entry_at_ms=int(time.time() * 1000),
                                    planner_memory_notes=getattr(request, "_planner_memory_notes", "") or "",
                                    memory_enabled=(getattr(request, "memory_enabled", True) is not False),
                                )
                    except Exception as _mem_upd_err:
                        logger.warning("🧠 [NormalStep4] 触发记忆/关系提取失败: %s", _mem_upd_err)
                try:
                    from ..scheduled_followup import schedule_from_planner, schedule_step4_next_turn_prep_decision
                    if is_guest_speaker(request):
                        logger.debug("[ScheduledFollowup] guest speaker turn; skip passive follow-up scheduling")
                    elif is_internal_proactive and not bool(getattr(request, "_normal_allow_proactive_reschedule_after_send", False)):
                        logger.debug("[ScheduledFollowup] internal proactive turn; skip chained follow-up scheduling")
                    else:
                        await schedule_from_planner(request, asst_ids, raw_res)
                        _source_message_id = str(asst_ids[-1] or "").strip() if asst_ids else ""
                        if _conv_id and username and character_id and _source_message_id:
                            _recent_for_step4_next_turn = [
                                {
                                    "role": getattr(m, "role", ""),
                                    "content": getattr(m, "content", ""),
                                }
                                for m in (request.messages or [])
                                if not getattr(m, "isHidden", False)
                            ]
                            schedule_step4_next_turn_prep_decision(
                                username=username,
                                character_id=character_id,
                                conversation_id=_conv_id,
                                source_message_id=_source_message_id,
                                user_message=_user_text,
                                assistant_message=raw_res,
                                recent_messages=_recent_for_step4_next_turn,
                                planner=getattr(request, "_normal_planner_result", None) or {},
                                character_profile=getattr(request, "_normal_stage2_character_profile", "") or "",
                                is_new_contact_opening=bool(getattr(request, "_is_new_contact_opening", False)),
                                chain_id=str(getattr(request, "_scheduled_followup_chain_id", "") or ""),
                                chain_count=int(getattr(request, "_scheduled_followup_chain_count", 0) or 0),
                            )
                except Exception as _sf_err:
                    logger.warning("[ScheduledFollowup] schedule passive/active task failed: %s", _sf_err)
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.exception("❌ [normal_nonstream] 未预期错误: %s", exc)
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if delivery_marked:
                try:
                    from .message_delivery_order import clear_conversation_delivery_active
                    clear_conversation_delivery_active(
                        delivery_username,
                        delivery_character_id,
                        delivery_conversation_id,
                    )
                except Exception as _order_err:
                    logger.debug("[DeliveryOrder] clear active skipped: %s", _order_err)
            await release_lock()
    if use_json:
        out: list[dict] = [] if accepted_already_streamed else [accepted_evt]
        async for packet in response_lines():
            t = (packet or "").strip()
            if t.startswith("data: "):
                d = t[6:].strip()
                if d == "[DONE]":
                    break
                out.append(json.loads(d))
        if not out or out[-1].get("type") != "done":
            out.append({"type": "done"})
        return JSONResponse(
            {
                "protocol": "ponychat_chat_v1",
                "mode": "normal",
                "events": out,
            }
        )
    async def detached_stream_lines():
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        async def pump_generation() -> None:
            try:
                async for packet in response_lines():
                    await queue.put(packet)
            except Exception as exc:
                logger.exception("鉂?[normal_nonstream] background generation failed: %s", exc)
                await queue.put(f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n")
                await queue.put("data: [DONE]\n\n")
            finally:
                await queue.put(None)
        from ..background_jobs import create_tracked_task
        create_tracked_task(
            pump_generation(),
            job_id=accepted_job_id,
            kind="normal_chat",
        )
        if not accepted_already_streamed:
            yield f"data: {json.dumps(accepted_evt, ensure_ascii=False)}\n\n"
        done_sent = False
        try:
            while True:
                packet = await queue.get()
                if packet is None:
                    break
                if (packet or "").strip() == "data: [DONE]":
                    done_sent = True
                yield packet
            if not done_sent:
                yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            logger.info(
                "[normal_nonstream] client disconnected after accept; background job continues job_id=%s user=%s char=%s",
                accepted_job_id,
                username,
                character_id,
            )
            return
    return StreamingResponse(
        detached_stream_lines(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
