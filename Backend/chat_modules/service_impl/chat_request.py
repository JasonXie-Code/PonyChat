from __future__ import annotations

from Backend.chat_modules.normal_agent import NormalAgentError

from Backend.chat_modules.service_impl.chat_request_helpers import await_normal_stage_with_generation_guard, handle_quota_no_reply_if_needed, handle_requested_normal_reply_speakers_if_needed, maybe_early_android_normal_accepted_response, normal_generation_current_for_request, release_normal_generation_lock_for_request, story_progression_policy_messages_for_request

async def handle_chat_request(
    request: ChatRequest,
    x_client_id: Optional[str],
    x_chat_auth: Optional[str],
    active_model: dict,
    use_json_protocol: bool = False,
):
    ctx = await resolve_auth_and_quota(request, x_client_id, x_chat_auth, active_model)
    active_model = ctx["active_model"]
    request_tokens = ctx["request_tokens"]
    client_id = ctx["client_id"]
    character_id = ctx["character_id"]
    username = ctx["username"]
    effective_username = ctx["effective_username"]
    if (request.mode or "normal") == "normal" and request.is_summary_request:
        from Backend.agent_memory.jobs import enqueue
        enqueue(config.DB_PATH, effective_username, character_id, immediate=True)
        return JSONResponse(status_code=202, content={"status": "queued", "engine": "agent-memory"})
    autonomous = (request.mode or "normal") == "normal" and not request.is_summary_request
    setattr(request, "_normal_autonomous_harness_requested", autonomous)
    if autonomous:
        setattr(request, "_normal_enable_stage3_handoff_events", True)
    is_internal_proactive = bool(getattr(request, "_normal_internal_proactive_trigger", False))
    proactive_debug_params = (
        getattr(request, "_normal_proactive_debug_params", None)
        if is_internal_proactive
        else None
    )
    if not isinstance(proactive_debug_params, dict):
        proactive_debug_params = {}
    def normal_generation_current() -> bool:
        return normal_generation_current_for_request(request, username, character_id, client_id)
    def normal_superseded_response(stage: str):
        logger.info(
            "[NormalSupersede] 旧请求在阶段边界失效，停止后续生成 user=%s char=%s client=%s token=%s stage=%s",
            username,
            character_id,
            client_id,
            getattr(request, "_generation_token", None),
            stage,
        )
        return _normal_debounce_cancelled_response(use_json_protocol, stage=stage)
    def raise_if_normal_superseded(stage: str) -> None:
        if not normal_generation_current():
            raise NormalGenerationSuperseded(stage)
    async def await_normal_stage(awaitable, stage: str):
        return await await_normal_stage_with_generation_guard(
            awaitable, stage, normal_generation_current, NormalGenerationSuperseded,
            log_context={"user": username, "char": character_id, "conv": getattr(request, "conversation_id", None)},
        )
    async def release_lock():
        await release_normal_generation_lock_for_request(
            request,
            username,
            character_id,
            client_id,
            normal_generation_current,
            generation_locker,
            manager,
            logger,
        )
    quota_response = await handle_quota_no_reply_if_needed(
        request, client_id, use_json_protocol, release_lock,
        _rebuild_android_normal_request_from_server_history,
        _normal_no_reply_response, logger, time,
    )
    if quota_response is not None:
        return quota_response
    speaker_response = await handle_requested_normal_reply_speakers_if_needed(
        request, x_client_id, x_chat_auth, active_model, use_json_protocol, release_lock,
        username, character_id, client_id, config, logger, requested_reply_character_ids,
        _rebuild_android_normal_request_from_server_history,
        resolve_explicit_at_reply_character_ids,
        run_normal_user_speaker_intent_router,
        mark_normal_forced_reply_characters, _handle_normal_multi_speaker_request,
    )
    if speaker_response is not None:
        return speaker_response
    early_accepted_response = await maybe_early_android_normal_accepted_response(
        request, x_client_id, x_chat_auth, active_model, use_json_protocol, client_id,
        is_internal_proactive, _ANDROID_DELTA_CLIENT_IDS, _latest_visible_user_batch,
        _persist_android_normal_user_delta, handle_chat_request, logger)
    if early_accepted_response is not None: return early_accepted_response
    if (request.mode or "normal") == "normal" and not request.is_summary_request:
        generation_token = getattr(request, "_generation_token", None)
        if not bool(getattr(request, "_normal_multi_speaker_child", False)):
            if not bool(getattr(request, "_normal_accepted_already_streamed", False)): await _persist_android_normal_user_delta(request, client_id=client_id)
            setattr(request, "_normal_enable_guest_direct_prewrite", not autonomous)
            await prepare_normal_reply_speaker(request)
        debounce_ms = _normal_reply_debounce_ms()
        if debounce_ms > 0:
            await asyncio.sleep(debounce_ms / 1000.0)
        if not is_generation_current(username, character_id, client_id, generation_token):
            logger.info(
                "[NormalDebounce] 旧请求已被新用户消息取代，跳过生成 user=%s char=%s client=%s token=%s debounce_ms=%s",
                username,
                character_id,
                client_id,
                generation_token,
                debounce_ms,
            )
            return _normal_debounce_cancelled_response(use_json_protocol, stage="NORMAL_DEBOUNCE")
    await _rebuild_android_normal_request_from_server_history(request, client_id=client_id)
    setattr(request, "_normal_enable_guest_direct_prewrite", not autonomous)
    await prepare_normal_reply_speaker(request)
    from .autonomous_shortcuts import is_description_shortcut, is_story_shortcut
    shortcut_text = next((m.content for m in reversed(request.messages or []) if m.role=='user' and not getattr(m,'isHidden',False)), '')
    request._normal_shortcut_no_auxiliary = is_description_shortcut(shortcut_text) or is_story_shortcut(shortcut_text)
    if not autonomous:
        _collapse_unreplied_user_tail_for_model_context(request)
    request_tokens = int(getattr(request, "_android_delta_request_tokens", request_tokens) or request_tokens)
    if (request.mode or "normal") == "normal" and not request.is_summary_request:
        try:
            from .state import estimate_request_context_tokens, get_model_context_messages
            request_tokens = estimate_request_context_tokens(get_model_context_messages(request))
        except Exception as token_err:
            logger.debug("[NormalPending] 合并后重算 token 失败: %s", token_err)
    if (request.mode or "normal") == "normal" and not request.is_summary_request and not is_internal_proactive:
        try:
            _last_user_for_followup = next(
                (
                    m for m in reversed(getattr(request, "messages", None) or [])
                    if getattr(m, "role", None) == "user"
                    and not getattr(m, "isHidden", False)
                ),
                None,
            )
            if _last_user_for_followup is not None:
                from ..scheduled_followup import (
                    cancel_pending_for_user_message,
                    cancel_pending_step4_next_turn_prep_decision,
                )
                cancel_pending_step4_next_turn_prep_decision(
                    request.username,
                    request.character_id,
                    getattr(request, "conversation_id", None),
                )
                await cancel_pending_for_user_message(
                    request.username,
                    request.character_id,
                    getattr(request, "conversation_id", None),
                )
        except Exception as _sf_cancel_err:
            logger.debug("[ScheduledFollowup] cancel on user message failed: %s", _sf_cancel_err)
        if not autonomous:
            try:
                from .normal_postprocess import wait_for_normal_step4_memory_relation
                await wait_for_normal_step4_memory_relation(
                    request.username,
                    request.character_id,
                    getattr(request, "conversation_id", None),
                )
            except Exception as _normal_post_wait_err:
                logger.warning("[NormalStage4] 等待上一轮记忆/关系提取失败，继续本轮: %s", _normal_post_wait_err)
        try:
            raise_if_normal_superseded("NORMAL_PRE_STAGE_1")
        except NormalGenerationSuperseded as superseded:
            return normal_superseded_response(superseded.stage)
    if (request.mode or "normal") == "normal" and not request.is_summary_request:
        try:
            from .normal_lifecycle import (
                get_normal_character_state,
            )
            from .normal_speaker import explicit_user_at_reply_requested
            from .runtime import run_conversation_persistence
            conv_id = str(getattr(request, "conversation_id", "") or "").strip()
            lifecycle_speaker = effective_speaker_character_id(request) or request.character_id
            current_state = await get_normal_character_state(
                request.username or "",
                lifecycle_speaker or "",
                conv_id,
            )
            if current_state == "dead":
                if explicit_user_at_reply_requested(request, lifecycle_speaker):
                    setattr(request, "_normal_dead_spirit_reply", True)
                    logger.info(
                        "[NormalLifecycle] dead main character @ requested; allowing spirit reply user=%s char=%s conv=%s",
                        request.username,
                        (request.character_id or "")[:12],
                        conv_id[:12],
                    )
                else:
                    save_ok, save_msg, _ = await run_conversation_persistence(
                        request,
                        "normal_lifecycle",
                        "",
                        int(time.time() * 1000),
                        persist_user_only=True,
                    )
                    conv_id = str(getattr(request, "conversation_id", "") or conv_id or "").strip()
                    reason = "character_already_dead"
                    logger.info(
                        "[NormalLifecycle] no_reply user=%s char=%s conv=%s reason=%s save_ok=%s",
                        request.username,
                        (request.character_id or "")[:12],
                        conv_id[:12],
                        reason,
                        save_ok,
                    )
                    await release_lock()
                    return _normal_no_reply_response(
                        use_json_protocol,
                        reason=reason,
                        save_ok=save_ok,
                        save_msg=save_msg or "",
                    )
        except Exception as lifecycle_err:
            logger.error("[NormalLifecycle] 检查死亡状态失败，停止生成: %s", lifecycle_err)
            await release_lock()
            raise HTTPException(status_code=503, detail="角色状态暂时无法确认，请稍后重试") from lifecycle_err
    lock_transferred_to_stream = False
    try:
        model_name = active_model.get("model_name", "")
        preserved_image_urls: list = []
        if (request.mode or "normal") == "normal" and not request.is_summary_request:
            preserved_image_urls = get_last_user_image_urls(request)
        if autonomous:
            from .autonomous_service import prepare_autonomous_request
            from .normal_nonstream import handle_normal_nonstream_sse
            speaker = effective_speaker_character_id(request) or character_id
            profile = _build_planner_character_prompt_context(username, speaker)
            environment = format_client_context(request.client_context) if request.client_context else ""
            opening = await _is_new_contact_opening(request, username, speaker, request.conversation_id)
            request._is_new_contact_opening = opening
            environment += '\n' + await build_user_context(request, effective_username, is_new_contact_opening=opening, compact=True)
            try:
                messages = await await_normal_stage(prepare_autonomous_request(
                    request, active_model, profile=profile, environment=environment,
                    image_urls=preserved_image_urls), "NORMAL_AGENT_AUTONOMOUS")
                raise_if_normal_superseded("NORMAL_AGENT_BEFORE_DELIVERY")
            except NormalGenerationSuperseded as superseded:
                return normal_superseded_response(superseded.stage)
            except NormalAgentError as agent_error:
                raise HTTPException(status_code=502, detail=str(agent_error)) from agent_error
            response = await handle_normal_nonstream_sse(
                request=request, model_name=model_name, payload={"messages": messages},
                api_url="", headers={}, provider=None, httpx_client=config.httpx_client,
                messages=messages, request_tokens=request_tokens, username=username,
                character_id=character_id, client_id=client_id, effective_username=effective_username,
                release_lock=release_lock, active_model=active_model, use_json=use_json_protocol,
                chat_request_log_params={"pipeline": "harness-autonomous"})
            lock_transferred_to_stream = True
            return response
        is_new_contact_opening = False
        if (request.mode or "normal") == "normal" and not request.is_summary_request:
            is_new_contact_opening = await _is_new_contact_opening(
                request,
                request.username,
                request.character_id,
                getattr(request, "conversation_id", None),
            )
            setattr(request, "_is_new_contact_opening", is_new_contact_opening)
            if is_new_contact_opening:
                logger.info("👋 [NewContactOpening] 当前普通对话尚无角色历史回复，按刚添加联系方式处理")
        user_context_prompt = await build_user_context(
            request,
            effective_username,
            is_new_contact_opening=is_new_contact_opening,
        )
        messages, _memory_on, request_tokens = await assemble_messages(
            request=request,
            active_model=active_model,
            model_name=model_name,
            user_context_prompt=user_context_prompt,
        )
        messages = await build_galgame_messages(
            request=request,
            messages=messages,
        )
        log_char = load_character_from_db(request.username, request.character_id) if request.character_id else {}
        log_char_name = (log_char.get("name") or request.character_id or "—") if log_char else (request.character_id or "—")
        log_mode = {"galgame": "游戏模式", "galgame_lock": "锁分模式", "normal": "对话模式"}.get(request.mode or "normal", request.mode or "normal")
        log_model_display = active_model.get("name") or model_name or "—"
        log_model_api = f" (api: {model_name})" if model_name and model_name != log_model_display else ""
        logger.info(f"💬 [对话生成]  用户={request.username or '—'}  角色={log_char_name}  模型={log_model_display}{log_model_api}  {log_mode}")
        user_settings = await _load_cloud_user_settings(request.username)
        params = get_smart_parameters(model_name, request.mode, active_model.get("id"), active_model.get("endpoint", ""))
        for noisy_key in ("top_p", "repeat_penalty", "presence_penalty", "frequency_penalty", "stop"):
            params.pop(noisy_key, None)
        model_name_lower = (model_name or "").lower()
        endpoint_lower = str(active_model.get("endpoint", "") or "").lower()
        is_local_model = any(s in endpoint_lower for s in ("127.0.0.1", "localhost", "0.0.0.0"))
        is_qwen_model = (not is_local_model) and ("dashscope.aliyuncs.com" in endpoint_lower or "qwen" in model_name_lower)
        if is_qwen_model:
            params["web_search"] = (request.mode == "normal")
        else:
            params.pop("web_search", None)
        params, active_model = _apply_cloud_and_request_settings(
            params=params,
            request=request,
            active_model=active_model,
            user_settings=user_settings,
        )
        _request_mode = request.mode or "normal"
        _software_task = {
            "normal": "normal_main_reply",
            "galgame": "galgame",
            "galgame_lock": "galgame_lock",
            "proactive": "proactive",
        }.get(_request_mode, _request_mode)
        _task_cfg = get_llm_task_config(_software_task)
        if "temperature" in _task_cfg:
            params["temperature"] = _task_cfg["temperature"]
            logger.info("🌡️ [%s] 温度来自软件层配置: %s", _software_task, params["temperature"])
        if request.mode in ("galgame", "galgame_lock"):
            active_model = {**active_model, "enable_thinking": False}
        model_name = active_model.get("model_name", model_name)
        is_ds_v4 = is_deepseek_v4_model(active_model, model_name, active_model.get("endpoint", ""))
        _no_think_name = active_model.get("model_name_no_thinking")
        if _no_think_name and (not is_ds_v4) and active_model.get("enable_thinking") is False:
            model_name = _no_think_name
            logger.info(f"💭 [思考控制] DeepSeek 关闭思考，切换 model_name → {model_name}")
        model_options = active_model.get("options") if isinstance(active_model.get("options"), dict) else {}
        configured_max_tokens = model_options.get("max_tokens")
        if "max_completion_tokens" not in params and isinstance(configured_max_tokens, (int, float)) and int(configured_max_tokens) > 0:
            params["max_completion_tokens"] = int(configured_max_tokens)
            logger.info(f"📏 [输出上限] 已设置最大输出: {params['max_completion_tokens']:,} tokens")
        _no_think_max = active_model.get("max_tokens_no_thinking")
        if _no_think_max and model_name == active_model.get("model_name_no_thinking"):
            _no_think_max = int(_no_think_max)
            if params.get("max_completion_tokens", 0) > _no_think_max:
                params["max_completion_tokens"] = _no_think_max
                logger.info(f"📏 [输出上限] DeepSeek 非思考模式上限: {_no_think_max:,} tokens")
        task_max_tokens = llm_task_int(_software_task, "max_output_tokens", DEFAULT_LLM_OUTPUT_MAX_TOKENS)
        params["max_completion_tokens"] = int(task_max_tokens or DEFAULT_LLM_OUTPUT_MAX_TOKENS)
        logger.info("📏 [%s] 输出上限来自软件层配置: %s tokens", _software_task, params["max_completion_tokens"])
        headers = {"Authorization": f"Bearer {active_model.get('api_key', '')}", "Content-Type": "application/json"}
        provider = get_provider(model_name, active_model.get("endpoint", ""), active_model)
        messages = provider.preprocess_messages(messages, active_model)
        request_tokens = _estimate_tokens(messages)
        ctx_limit_tokens = llm_task_int(_software_task, "context_limit_tokens", _CTX_LIMIT_TOKENS) or _CTX_LIMIT_TOKENS
        ctx_pct = round(request_tokens / ctx_limit_tokens * 100, 1)
        ctx_tag = "🔴" if ctx_pct >= 90 else ("🟡" if ctx_pct >= 70 else "🟢")
        summary_flag = " [已摘要]" if any(
            isinstance(m.get("content"), str) and m["content"].startswith("[以下是本对话之前内容的摘要")
            for m in messages if m.get("role") in ("user", "system")
        ) else ""
        logger.info(
            f"{ctx_tag} [上下文] {request_tokens:,}/{ctx_limit_tokens:,} tokens "
            f"({ctx_pct}%)  消息数={len(messages)}"
            f"  模式={request.mode or 'normal'}"
            f"  用户={request.username or '-'}"
            f"  角色={log_char_name}"
            f"{summary_flag}"
        )
        if request_tokens >= ctx_limit_tokens:
            logger.warning(f"⚠️ [上下文超限] {request_tokens:,}/{ctx_limit_tokens:,} tokens，已超软限制，继续处理")
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
        }
        system_msgs = [m for m in messages if m["role"] == "system"]
        if system_msgs:
            logger.debug("=" * 50)
            logger.debug(f"🔍 [Payload Check] 发往 {model_name} 的 System Prompts ({len(system_msgs)} 条):")
            for i, m in enumerate(system_msgs):
                logger.debug(f"  [{i+1}] {m['content'][:100]}..." if len(m["content"]) > 100 else f"  [{i+1}] {m['content']}")
        if len(messages) > 0 and messages[-1]["role"] == "user":
            last_content = messages[-1]["content"]
            if isinstance(last_content, str) and "【指令加强" in last_content:
                logger.debug("🔍 [Payload Check] 尾部锚点注入: ✅ 检测到防遗忘指令")
            logger.debug("=" * 50)
        for opt in ["temperature", "max_completion_tokens"]:
            if opt in params:
                payload[opt] = params[opt]
        if request.is_summary_request:
            payload["temperature"] = 0.3
        if "max_completion_tokens" in payload:
            is_xai_model = "api.x.ai" in active_model.get("endpoint", "") or "grok" in model_name.lower()
            is_openai_model = "api.openai.com" in active_model.get("endpoint", "") or any(k in model_name.lower() for k in ["gpt-4", "gpt-5", "o1", "o3"])
            if not is_xai_model and not is_openai_model:
                payload["max_tokens"] = payload.pop("max_completion_tokens")
                logger.debug("🔄 参数适配：max_completion_tokens -> max_tokens (非 xAI/OpenAI 模型)")
        reasoning_policy = resolve_software_reasoning_policy(
            _software_task,
            model_name=model_name,
            mode=_request_mode,
            requested_enabled=(
                bool(active_model.get("enable_thinking", True))
                if _request_mode == "normal"
                else None
            ),
            requested_effort=params.get("reasoning_effort") or "high",
            active_model=active_model,
            endpoint=active_model.get("endpoint", ""),
        )
        if request.mode in ("galgame", "galgame_lock") and reasoning_policy.thinking_type == "disabled":
            logger.info("💭 [思考控制] 游戏/锁分模式：软件层配置禁用思考")
        if (request.mode or "normal") == "normal":
            reasoning_policy = apply_normal_thinking_switch(
                reasoning_policy,
                enable_high_thinking=NORMAL_MAIN_REPLY_THINKING_HIGH,
            )
        if reasoning_policy.is_deepseek_v4:
            t = reasoning_policy.thinking_type or "disabled"
            payload["thinking"] = {"type": t}
            if t == "enabled" and reasoning_policy.deepseek_v4_api_reasoning_effort:
                payload["reasoning_effort"] = reasoning_policy.deepseek_v4_api_reasoning_effort
            else:
                payload.pop("reasoning_effort", None)
        target_effort = reasoning_policy.effort
        if (not reasoning_policy.is_deepseek_v4) and any(
            k in model_name_lower for k in ["o1", "thinking", "grok", "gemini"]
        ):
            if target_effort:
                payload["reasoning_effort"] = target_effort
        if request.mode in ("galgame", "galgame_lock"):
            payload["response_format"] = {"type": "json_object"}
            logger.debug("🎮 Galgame/锁分模式：已启用 JSON mode 强制输出")
        payload, api_url, uses_responses_format = provider.build_payload(
            payload,
            params,
            active_model,
            request_mode=request.mode,
            reasoning_policy=reasoning_policy,
            normalize_image_url=normalize_image_url_for_model,
        )
        endpoint = active_model.get("endpoint", "")
        payload = apply_model_param_policy(payload=payload, model_name=model_name, endpoint=endpoint)
        force_default_output_token_limit(payload, model_name=model_name, endpoint=endpoint)
        api_type_label = (
            ("xAI Responses API" if isinstance(provider, XaiProvider) and uses_responses_format else
             ("Qwen 官方 Responses API" if isinstance(provider, QwenProvider) and uses_responses_format else "Chat Completions API"))
        )
        web_search_on = bool(payload.get("web_search"))
        json_mode_on = bool(payload.get("response_format"))
        max_out_tok = payload.get("max_completion_tokens") or payload.get("max_tokens") or payload.get("max_output_tokens")
        temp_val = payload.get("temperature")
        upstream_stream_on = bool(payload.get("stream"))
        api_cfg_parts = [
            f"接口类型={api_type_label}",
            f"联网搜索={'开启' if web_search_on else '关闭'}",
            f"JSON强制输出={'开启' if json_mode_on else '关闭'}",
            f"上游stream={'开启' if upstream_stream_on else '关闭'}",
        ]
        if max_out_tok:
            api_cfg_parts.append(f"最大输出={max_out_tok:,} tokens")
        if temp_val is not None:
            api_cfg_parts.append(f"温度={temp_val}")
        logger.info(f"🚀 [API配置]  {'  |  '.join(api_cfg_parts)}")
        logger.info("─" * 55)
        _p = payload  # 经 provider 转换与 policy 剥离后的最终 payload
        _enable_thinking = None
        _thinking_depth = None
        if isinstance(_p.get("thinking"), dict):
            _enable_thinking = _p["thinking"].get("type") != "disabled"
            if _enable_thinking and isinstance(_p.get("reasoning"), dict):
                _thinking_depth = _p["reasoning"].get("effort")
            elif _enable_thinking and _p.get("reasoning_effort"):
                _thinking_depth = _p.get("reasoning_effort")
        elif "enable_thinking" in _p:
            _enable_thinking = bool(_p["enable_thinking"])
            if _enable_thinking:
                tb = _p.get("thinking_budget")
                if isinstance(tb, int) and tb > 0:
                    if tb <= 4096:
                        _thinking_depth = f"低 (~{tb//1024}K tokens)"
                    elif tb <= 16384:
                        _thinking_depth = f"中 (~{tb//1024}K tokens)"
                    else:
                        _thinking_depth = f"高 (~{tb//1024}K tokens)"
                elif params.get("thinking_budget") and params["thinking_budget"] != "auto":
                    _thinking_depth = params["thinking_budget"]
        elif _p.get("reasoning_effort"):
            _enable_thinking = True
            _thinking_depth = _p["reasoning_effort"]
        elif params.get("reasoning_effort"):
            _enable_thinking = True if (is_qwen_model) else None
            _thinking_depth = params["reasoning_effort"]
        elif active_model.get("model_name_no_thinking"):
            _enable_thinking = (model_name != active_model.get("model_name_no_thinking"))
        _web_search = bool(params.get("web_search", False))
        if isinstance(_p.get("tools"), list):
            _web_search = any(
                isinstance(t, dict) and t.get("type") in ("web_search", "builtin_function", "web_extractor")
                for t in _p["tools"]
            )
        _temperature = _p.get("temperature") or params.get("temperature")
        _max_tokens = _p.get("max_completion_tokens") or _p.get("max_tokens") or _p.get("max_output_tokens") or params.get("max_completion_tokens")
        log_params = {
            "api_url": api_url,
            "api_format": api_type_label,
            "temperature": _temperature,
            "max_tokens": _max_tokens,
            "enable_thinking": _enable_thinking,
            "thinking_depth": _thinking_depth,
            "web_search": _web_search,
            "stream": bool(_p.get("stream")),
        }
        if (request.mode or "normal") == "normal" and not request.is_summary_request:
            log_params.update(normal_role_debug_params(request))
            if is_internal_proactive:
                log_params.update(proactive_debug_params)
                log_params["pipeline"] = proactive_debug_params.get("pipeline") or "normal_proactive_core"
        if request.mode in ("galgame", "galgame_lock"):
            log_params["pipeline"] = "game-agent"
            log_params["note"] = "游戏整轮由单一 Agent 生成；校验失败时重新生成完整输出。"
        if (request.mode or "normal") != "normal":
            await save_chat_debug_log(
                request.username, request.character_id, request.mode, model_name,
                payload, "REQUEST", params=log_params,
            )
        response, lock_transferred_to_stream = await handle_nonstream_request(
            request=request,
            model_name=model_name,
            payload=payload,
            api_url=api_url,
            headers=headers,
            provider=provider,
            params=params,
            uses_responses_format=uses_responses_format,
            messages=messages,
            request_tokens=request_tokens,
            username=username,
            character_id=character_id,
            client_id=client_id,
            effective_username=effective_username,
            release_lock=release_lock,
            active_model=active_model,
            use_json_protocol=use_json_protocol,
            chat_request_log_params=log_params,
        )
        return response
    except Exception as e:
        logger.error(f"Chat request failed: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if not lock_transferred_to_stream:
            autonomous_store = getattr(request, "_autonomous_memory_store", None)
            if autonomous_store is not None:
                autonomous_store.discard()
            await release_lock()
