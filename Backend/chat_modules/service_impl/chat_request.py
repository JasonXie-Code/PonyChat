from __future__ import annotations

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
            awaitable,
            stage,
            normal_generation_current,
            NormalGenerationSuperseded,
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
        resolve_explicit_at_reply_character_ids, run_normal_user_speaker_intent_router,
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
            setattr(request, "_normal_enable_guest_direct_prewrite", True)
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
    setattr(request, "_normal_enable_guest_direct_prewrite", True)
    await prepare_normal_reply_speaker(request)
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
            from .runtime import run_conversation_persistence
            conv_id = str(getattr(request, "conversation_id", "") or "").strip()
            current_state = await get_normal_character_state(
                request.username or "",
                request.character_id or "",
                conv_id,
            )
            if current_state == "dead":
                if _normal_forced_main_reply_requested(request):
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
                    return _normal_no_reply_response(
                        use_json_protocol,
                        reason=reason,
                        save_ok=save_ok,
                        save_msg=save_msg or "",
                    )
        except Exception as lifecycle_err:
            logger.warning("[NormalLifecycle] 检查死亡状态失败，继续普通生成: %s", lifecycle_err)
    lock_transferred_to_stream = False
    try:
        model_name = active_model.get("model_name", "")
        preserved_image_urls: list = []
        if (request.mode or "normal") == "normal" and not request.is_summary_request:
            preserved_image_urls = get_last_user_image_urls(request)
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
        if (request.mode or "normal") == "normal" and not request.is_summary_request:
            try:
                from .image_context_store import (
                    INJECT_MAX,
                    format_prior_injection_block,
                    get_last_n_for_injection,
                )
                from .normal_planner import (
                    NormalVisionContext,
                    apply_group_relationship_tension_policy,
                    apply_memory_evidence_guard_to_plan,
                    apply_partner_private_party_desire_guard,
                    apply_story_progression_policy,
                    augment_system_prompt_for_normal_mode,
                    build_planner_memory_notes,
                    build_normal_mode_augment_block,
                    default_planner_result,
                    finalize_normal_scene_from_fact_judgement,
                    _apply_step1_delivery_contract,
                    _extract_character_name_from_context,
                    get_last_user_text_for_vision,
                    plan_normal_conversation,
                    prepare_normal_scene_candidate,
                    run_normal_expression_dedup_review,
                    run_normal_fact_judgement_review,
                    run_normal_memory_recall_tool,
                    run_normal_self_cognition,
                    run_normal_vision,
                    is_vision_tool_error_context,
                    vision_tool_error_context,
                )
                from . import image_context_store as _img_ctx
                from .emotion_state import (
                    format_emotion_state_for_planner,
                    load_emotion_state,
                    save_from_planner as save_emotion_from_planner,
                )
                def _round_image_ok(v) -> bool:
                    return bool(
                        v
                        and (v.image_summary or v.web_research_summary or v.should_refuse)
                    )
                planner_environment_context = ""
                if request.client_context:
                    try:
                        planner_environment_context = format_client_context(request.client_context)
                    except Exception as _ctx_err:
                        logger.debug("[NormalPlanner] 客户端环境上下文格式化失败: %s", _ctx_err)
                _conv = getattr(request, "conversation_id", None)
                _speaker_character_id = effective_speaker_character_id(request) or request.character_id
                _main_character_id = request.character_id
                _speaker_context_conv = _conv
                _guest_scene_context = ""
                if is_guest_speaker(request):
                    try:
                        await ensure_guest_private_context(request)
                    except Exception as _guest_ctx_err:
                        logger.debug("[NormalSpeaker] guest 私有上下文准备失败: %s", _guest_ctx_err)
                    _speaker_context_conv = speaker_context_conversation_id(request)
                    _guest_scene_context = guest_scene_context_prompt(request)
                _emotion_state = {}
                _planner_character_context = _build_planner_character_prompt_context(
                    request.username,
                    _speaker_character_id,
                )
                _planner_step1_character_context = _build_planner_step1_character_prompt_context(
                    _planner_character_context
                )
                _normal_proactive_stage_prefix = "NORMAL_PROACTIVE" if is_internal_proactive else "NORMAL_STEP_1"
                _normal_stage2_memory_stage = (
                    "NORMAL_PROACTIVE_MEMORY_RECALL"
                    if is_internal_proactive
                    else "NORMAL_STEP_2_MEMORY_RECALL"
                )
                _normal_stage2_fact_stage = (
                    "NORMAL_PROACTIVE_FACT_JUDGEMENT"
                    if is_internal_proactive
                    else "NORMAL_STEP_2_FACT_JUDGEMENT"
                )
                _debug_role_params = normal_role_debug_params(
                    request,
                    {
                        "speaker_character_id": _speaker_character_id,
                        **proactive_debug_params,
                    },
                )
                _forced_reply_ids = normal_forced_reply_character_ids(request)
                if _forced_reply_ids:
                    forced_blocks = [
                        "【本轮指定发言者】\n"
                        "用户本轮已经通过 @、引用或发言调度指定当前角色必须参与发言；"
                        "Step 1 不得把 speech_activity 判为 0-8，bubble_count 不得为 0。"
                    ]
                    if getattr(request, "_normal_dead_spirit_reply", False):
                        forced_blocks.append(
                            "【死亡后 @ 主角色｜灵魂回应】\n"
                            "当前主角色在本对话中的生命周期状态已经是 dead。"
                            "用户本轮显式 @ 主角色，因此允许一次死后灵魂/残响回应；"
                            "这不是复活，不改变 dead 状态。"
                            "本轮正文必须一次写成固定形态：「（角色名的灵魂/残响如何出现、漂浮、从死亡位置渗出或凝在半空）一句死后残留口吻的短台词」。"
                            "括号内用第三者角度呈现死去角色的灵魂、残响或死后意识；括号外只写一句直接短台词。"
                            "保持 dead 状态和灵魂残响性质，不恢复行动、继续日常互动或安排下一步现实行动。"
                        )
                    planner_environment_context = "\n\n".join(
                        part.strip()
                        for part in (
                            planner_environment_context,
                            "\n\n".join(forced_blocks),
                        )
                        if (part or "").strip()
                    )
                _at_event_context = normal_at_event_context(request)
                _at_event_context_block = format_normal_at_event_context(request)
                if _at_event_context_block:
                    planner_environment_context = _join_nonempty_context_parts(
                        planner_environment_context,
                        _at_event_context_block,
                    )
                    setattr(request, "_normal_at_event_context", _at_event_context)
                setattr(request, "_normal_stage2_character_context", _planner_character_context)
                setattr(request, "_normal_stage2_speaker_character_id", _speaker_character_id)
                setattr(request, "_normal_stage2_speaker_context_conversation_id", _speaker_context_conv or "")
                _last_user_text_for_memory = ""
                for _m in reversed(getattr(request, "messages", None) or []):
                    if getattr(_m, "role", None) == "user" and not getattr(_m, "isHidden", False):
                        _last_user_text_for_memory = str(getattr(_m, "content", "") or "")
                        break
                u_txt = get_last_user_text_for_vision(request) if preserved_image_urls else ""
                if preserved_image_urls:
                    _current_image_pending_block = (
                        "【当前上传图片状态】\n"
                        f"本轮用户已上传 {len(preserved_image_urls)} 张图片；基础图片识别固定在 Step 2 运行，"
                        "Step 1 不得把本轮判为“没有图片/没看到图片/需要重发图片”。"
                        "若用户文字是在问图、看这个、这是什么或图片里面有什么，应保留为等待 Step 2 视觉结果后回答。\n"
                        f"用户附带文字：{u_txt or '（无文字）'}"
                    )
                    planner_environment_context = _join_nonempty_context_parts(
                        planner_environment_context,
                        _current_image_pending_block,
                    )
                async def _load_stage2_emotion_context() -> tuple[dict, str]:
                    if not (request.username and _speaker_character_id and _speaker_context_conv):
                        return {}, ""
                    try:
                        state = await load_emotion_state(
                            request.username,
                            _speaker_character_id,
                            _speaker_context_conv,
                            get_database(),
                            client_context=request.client_context,
                        )
                        return state or {}, format_emotion_state_for_planner(state or {})
                    except Exception as exc:
                        logger.debug("[EmotionState] load for stage2 failed: %s", exc)
                        return {}, ""
                async def _load_stage2_context_memory() -> str:
                    if getattr(request, "memory_enabled", True) is False:
                        return ""
                    _ctx_character_id = _speaker_character_id if is_guest_speaker(request) else _main_character_id
                    _ctx_conv = _speaker_context_conv if is_guest_speaker(request) else _conv
                    if not (request.username and _ctx_character_id and _ctx_conv):
                        return ""
                    try:
                        from ..db import get_database as _get_db_for_planner
                        from .context_memory import (
                            format_context_memory_for_prompt as _fmt_ctx_for_planner,
                            load_context_memory as _load_ctx_for_planner,
                        )
                        mem = await _load_ctx_for_planner(
                            request.username,
                            _ctx_character_id,
                            _ctx_conv,
                            _get_db_for_planner(),
                        )
                        if is_guest_speaker(request):
                            text = _fmt_ctx_for_planner(
                                mem or {},
                                recent_raw_turns=guest_private_recent_raw_turns(request) or None,
                                assistant_label=speaker_display_name(request),
                            )
                        else:
                            text = _fmt_ctx_for_planner(mem or {})
                        if (text or "").strip():
                            if is_guest_speaker(request):
                                return (
                                    "【被 @ 角色自己的普通聊天上下文记忆】\n"
                                    "以下内容属于当前发言者自己的私聊连续性和既有经历；它不是主会话角色的私有记忆。本轮应像把完整的当前发言者拉进临时群聊一样使用这些材料。"
                                    "若这些材料含有中国象棋/小游戏对局记忆，且当前用户问刚刚、刚才、刚退出的游戏、A/B/C、赌注或兑现，必须优先于跨会话长期记忆使用；多条对局记录取最新/最靠后的一条，长期记忆只能作背景，不能覆盖刚结束游戏记录。"
                                    "若这些私聊记忆包含卧室、家里、门口等旧地点，只能当历史背景；当前物理位置必须以【临时群聊现场】、场景锚点和最近主会话原文为准，不能让旧私聊位置覆盖用户刚把角色 @ 进来的共同现场。\n"
                                    + text[:6000]
                                )
                            return "【当前会话上下文记忆（供意图识别保持连续性，不得复述给用户）】\n若其中含有中国象棋/小游戏对局记忆，且当前用户问刚刚、刚才、刚退出的游戏、A/B/C、赌注或兑现，必须优先于跨会话长期记忆使用；多条对局记录取最新/最靠后的一条，长期记忆只能作背景，不能覆盖刚结束游戏记录。\n" + text[:5000]
                    except Exception as exc:
                        logger.debug("[NormalStage2] 加载会话记忆失败: %s", exc)
                    return ""
                async def _load_stage2_long_memory() -> str:
                    if getattr(request, "memory_enabled", True) is False:
                        return ""
                    if not (request.username and _speaker_character_id):
                        return ""
                    try:
                        layers = await recall_memories_layered(
                            username=request.username,
                            character_id=_speaker_character_id,
                            current_query=_last_user_text_for_memory,
                        )
                        text = format_layered_memories_for_prompt(
                            **layers,
                            suppress_d_layer=False,
                            compact_cross_chat_fragments=True,
                            fragments_first=True,
                        )
                        if (text or "").strip():
                            display_name = getattr(request, "_display_name", None) or request.username or "用户"
                            text = replace_user_placeholder(text, display_name)
                            return (
                                f"【记忆指代说明】以下跨会话长期记忆中的 {USER_MEMORY_PLACEHOLDER}、USER 或“用户”均指当前用户「{display_name}」。\n"
                                "【意图识别可参考的跨会话长期记忆】\n"
                                "这些是角色大脑里的长期记忆。只可作为背景、过去经历和偏好证据；"
                                "除非最近可见对话明确建立，不得把地点、姿势、衣服、身体接触或亲密行为当作当前正在发生。\n"
                                + text[:9000]
                            )
                    except Exception as exc:
                        logger.debug("[NormalStage2] 加载跨会话长期记忆失败: %s", exc)
                    return ""
                async def _load_stage2_guest_group_memory() -> str:
                    if getattr(request, "memory_enabled", True) is False:
                        return ""
                    if not (request.username and _speaker_character_id):
                        return ""
                    try:
                        return await load_recent_guest_group_memory_block(
                            request.username,
                            _speaker_character_id,
                            limit=4,
                        )
                    except Exception as exc:
                        logger.debug("[NormalStage2] 加载临时群聊见闻失败: %s", exc)
                        return ""
                async def _load_stage2_image_state() -> tuple[int, bool]:
                    try:
                        count, last = await asyncio.gather(
                            _img_ctx.count_stored(request.username, _main_character_id, _conv),
                            _img_ctx.get_last_reply_based_on_image(request.username, _main_character_id, _conv),
                        )
                        return count, last
                    except Exception as exc:
                        logger.debug("[NormalStage2] 加载图片上下文状态失败: %s", exc)
                        return 0, False
                async def _build_stage2_recent_chat() -> list[dict]:
                    recent = build_chat_router_recent_user_assistant(
                        request, active_model, model_name, max_messages=6
                    )
                    if len(recent) <= 1:
                        server_recent_chat = await _load_server_recent_chat_for_planner(
                            request.username,
                            _main_character_id,
                            _conv,
                            max_messages=5,
                        )
                        if server_recent_chat:
                            current_recent = list(recent or [])
                            recent = (server_recent_chat + current_recent)[-6:]
                            logger.info(
                                "[NormalStage2] 已为短请求补入服务端最近对话: server=%s current=%s final=%s conv=%s",
                                len(server_recent_chat),
                                len(current_recent),
                                len(recent),
                                str(_conv or "")[:12],
                            )
                    return await _enrich_recent_chat_voice_states(recent, _conv)
                async def _load_stage2_revision_context() -> str:
                    return await _load_recent_deleted_tail_context(
                        request.username,
                        _main_character_id,
                        _conv,
                    )
                (
                    (_emotion_state, _emotion_context),
                    _planner_mem_text,
                    _planner_long_mem,
                    _planner_guest_group_mem,
                    (prior_stored, last_b_img),
                    recent_chat,
                    revision_context,
                ) = await await_normal_stage(
                    asyncio.gather(
                        _load_stage2_emotion_context(),
                        _load_stage2_context_memory(),
                        _load_stage2_long_memory(),
                        _load_stage2_guest_group_memory(),
                        _load_stage2_image_state(),
                        _build_stage2_recent_chat(),
                        _load_stage2_revision_context(),
                    ),
                    "NORMAL_STEP_1_CONTEXT_GATHER",
                )
                vision_ctx = NormalVisionContext()
                raise_if_normal_superseded("NORMAL_STEP_1_CONTEXT_GATHER_DONE")
                _planner_base_environment_context = planner_environment_context
                _planner_mem_text_slim = _compact_normal_stage_context(_planner_mem_text, limit=2600)
                _planner_long_mem_slim = _compact_normal_stage_context(_planner_long_mem, limit=1800)
                _planner_guest_group_mem_slim = _compact_normal_stage_context(_planner_guest_group_mem, limit=1800)
                stage2_context_parts = [
                    _planner_base_environment_context,
                    _guest_scene_context,
                    _emotion_context,
                    _planner_mem_text_slim,
                    _planner_long_mem_slim,
                    _planner_guest_group_mem_slim,
                    revision_context,
                ]
                planner_environment_context = _join_nonempty_context_parts(*stage2_context_parts)
                _planner_self_cognition_environment_context = _join_nonempty_context_parts(
                    _planner_base_environment_context,
                    _guest_scene_context,
                    _emotion_context,
                    revision_context,
                )
                router_cfg = config.model_manager.get_model_for_task("chat_router")
                _normal_scene_anchor_card = ""
                _normal_scene_anchor = {}
                _scene_candidate = {}
                _scene_context_conv = _conv if is_guest_speaker(request) else (_speaker_context_conv or _conv)
                try:
                    _scene_candidate = await await_normal_stage(
                        prepare_normal_scene_candidate(
                            recent_chat,
                            router_cfg=router_cfg,
                            environment_context=planner_environment_context,
                            character_prompt_context=_planner_step1_character_context,
                            current_character_name=_extract_character_name_from_context(_planner_character_context),
                            username=request.username,
                            character_id=_speaker_character_id,
                            conversation_id=_scene_context_conv,
                            debug_mode="normal",
                            debug_stage=(
                                "NORMAL_PROACTIVE_SCENE_CANDIDATE"
                                if is_internal_proactive
                                else "NORMAL_STEP_1_SCENE_CANDIDATE"
                            ),
                            debug_role_params=_debug_role_params,
                        ),
                        "NORMAL_STEP_1_SCENE_CANDIDATE",
                    )
                    _normal_scene_anchor_card = str((_scene_candidate or {}).get("scene_card") or "").strip()
                    _normal_scene_anchor = (_scene_candidate or {}).get("scene_anchor") or {}
                    if _normal_scene_anchor_card:
                        _scene_candidate_source = str((_scene_candidate or {}).get("source") or "")
                        if _scene_candidate_source == "long_idle_prior_context":
                            _scene_candidate_context = (
                                "【上一轮普通对话场景背景｜现实时间间隔信号，供 Step 2 判断是否继承】\n"
                                + _normal_scene_anchor_card
                            )
                        else:
                            _scene_candidate_context = "【普通对话场景候选｜供 Step 2 事实与场景判断校验】\n" + _normal_scene_anchor_card
                        planner_environment_context = _join_nonempty_context_parts(
                            planner_environment_context,
                            _scene_candidate_context,
                        )
                        _planner_self_cognition_environment_context = _join_nonempty_context_parts(
                            _planner_self_cognition_environment_context,
                            _scene_candidate_context,
                        )
                    setattr(request, "_normal_scene_anchor_card", _normal_scene_anchor_card)
                    setattr(request, "_normal_scene_anchor", _normal_scene_anchor)
                except Exception as _scene_candidate_err:
                    logger.debug("[NormalScene] scene candidate skipped: %s", _scene_candidate_err)
                raise_if_normal_superseded("NORMAL_STEP_1_SCENE_CANDIDATE_DONE")
                planner_result = default_planner_result()
                if router_cfg:
                    planner_result = await await_normal_stage(
                        plan_normal_conversation(
                            recent_chat,
                            router_cfg,
                            vision_context=vision_ctx,
                            current_image_pending=bool(preserved_image_urls),
                            environment_context=planner_environment_context,
                            character_prompt_context=_planner_step1_character_context,
                            username=request.username,
                            character_id=_speaker_character_id,
                            main_character_id=_main_character_id,
                            prior_stored_count=prior_stored,
                            last_reply_based_on_image=last_b_img,
                            debug_stage_prefix=_normal_proactive_stage_prefix,
                            debug_role_params=_debug_role_params,
                        ),
                        "NORMAL_STEP_1_INTENT_RECOGNITION",
                    )
                raise_if_normal_superseded("NORMAL_STEP_1_INTENT_RECOGNITION_DONE")
                if is_new_contact_opening and not _new_contact_opening_should_preserve_user_task(_latest_user_text(request)):
                    try:
                        _new_contact_initiative = int(planner_result.get("initiative_level") or 45)
                    except Exception:
                        _new_contact_initiative = 45
                    planner_result = {
                        **planner_result,
                        "reply_intent": "新联系人自然开场",
                        "tone": "符合角色但保持刚加联系方式的礼貌距离，轻松、试探、不自来熟",
                        "length": "short",
                        "bubble_count": 1,
                        "action_style": "plain_text",
                        "initiative_level": min(_new_contact_initiative, 45),
                        "speech_activity": 45,
                        "speech_reason": "新联系人开场需要简短回应",
                        "memory_use_policy": (
                            "判别：新联系人开场。当前会话还没有角色历史回复，只能知道对方显示名和用户资料；"
                            "不要把长期记忆、角色热情或用户资料误写成已经相熟很久。"
                        ),
                        "risk_notes": (
                            "刚添加联系方式的新对话，禁止老熟人口吻；不要写“终于来找我”“好久不见”“又来啦”"
                            "或暗示双方之前已经频繁聊天。"
                        ),
                        "expression_policy": (
                            "按刚加上联系方式的人来回应问候：可以自我介绍或轻轻接住对方的你好，"
                            "再问一个低压力的问题；称呼名字可用但不要过度亲昵。"
                        ),
                    }
                planner_result = apply_memory_evidence_guard_to_plan(
                    planner_result,
                    recent_chat,
                    is_new_contact_opening=is_new_contact_opening,
                )
                planner_result = apply_partner_private_party_desire_guard(
                    planner_result,
                    recent_chat,
                    character_prompt_context=_planner_character_context,
                )
                planner_result = _apply_direct_location_query_policy(planner_result, _latest_user_text(request))
                planner_result = apply_story_progression_policy(
                    planner_result,
                    story_progression_policy_messages_for_request(request, recent_chat),
                )
                planner_result = apply_group_relationship_tension_policy(
                    planner_result,
                    recent_chat,
                    at_event_context=_at_event_context,
                    environment_context=planner_environment_context,
                    scene_anchor_card=_normal_scene_anchor_card,
                )
                try:
                    from .voice_messages import force_text_reply_when_chat_voice_disabled
                    planner_result = force_text_reply_when_chat_voice_disabled(planner_result)
                except Exception as _voice_switch_err:
                    logger.debug("[VoiceMsg] chat voice switch check failed: %s", _voice_switch_err)
                literal_reply_text = str(planner_result.get("literal_reply_text") or "").strip()
                if literal_reply_text:
                    planner_result = {
                        **planner_result,
                        "web_search": False,
                        "search_query": None,
                        "vision_web": False,
                        "use_prior_image_context": False,
                        "asset_plan": {
                            **(planner_result.get("asset_plan") or {}),
                            "enabled": False,
                            "count": 0,
                        },
                        "reply_sequence": [{"type": "text", "intent": "literal_reply"}],
                    }
                    logger.info("🧭 [普通对话] Step 1 已指定完整复述正文，跳过 Step 2 工具 user=%s char=%s", request.username, request.character_id)
                if getattr(request, "_normal_terminal_death_action", False):
                    planner_result = _apply_terminal_death_reply_policy(planner_result)
                planner_for_stage2_tools = dict(planner_result)
                async def _stage2_expression_dedup_tool():
                    if literal_reply_text or is_new_contact_opening:
                        return default_planner_result()["expression_dedup_report"]
                    try:
                        return await run_normal_expression_dedup_review(
                            recent_chat,
                            router_cfg or {},
                            character_prompt_context=_planner_step1_character_context,
                            user_species=getattr(request, "_user_species", "") or "",
                            username=request.username,
                            character_id=_speaker_character_id,
                            debug_mode="normal",
                            debug_stage=_normal_stage2_memory_stage,
                            debug_role_params=_debug_role_params,
                            charge_membership_chat_quota=True,
                        )
                    except Exception as _dedup_err:
                        logger.debug("[NormalStep2Tools] expression_dedup failed: %s", _dedup_err)
                        return default_planner_result()["expression_dedup_report"]
                async def _stage2_vision_tool():
                    if not preserved_image_urls:
                        return NormalVisionContext()
                    try:
                        base_vision = await run_normal_vision(
                            preserved_image_urls,
                            u_txt,
                            username=request.username,
                            character_id=_main_character_id,
                            force_web=False,
                        )
                    except Exception as _vision_base_err:
                        logger.debug("[NormalStep2Tools] vision failed: %s", _vision_base_err)
                        return vision_tool_error_context(str(_vision_base_err))
                    if (
                        literal_reply_text
                        or base_vision.should_refuse
                        or is_vision_tool_error_context(base_vision)
                        or not planner_for_stage2_tools.get("vision_web")
                    ):
                        return base_vision
                    try:
                        web_vision = await run_normal_vision(
                            preserved_image_urls,
                            u_txt,
                            username=request.username,
                            character_id=_main_character_id,
                            force_web=True,
                        )
                    except Exception as _vision_web_err:
                        logger.debug("[NormalStep2Tools] vision_web failed: %s", _vision_web_err)
                        return base_vision
                    if is_vision_tool_error_context(web_vision):
                        return base_vision
                    return web_vision if _round_image_ok(web_vision) else base_vision
                async def _stage2_web_search_tool():
                    if literal_reply_text:
                        return "", planner_for_stage2_tools.get("search_query")
                    if not (
                        planner_for_stage2_tools.get("web_search")
                        and planner_for_stage2_tools.get("search_query")
                    ):
                        return "", planner_for_stage2_tools.get("search_query")
                    search_query = _localize_search_query(
                        planner_for_stage2_tools["search_query"],
                        request.client_context,
                    )
                    try:
                        search_context_text = await run_web_search(
                            search_query,
                            username=request.username,
                            character_id=_speaker_character_id,
                            debug_mode="normal",
                            debug_stage="NORMAL_STEP_2_WEB_SEARCH_REQUEST",
                            debug_role_params=_debug_role_params,
                        )
                    except Exception as _web_tool_err:
                        logger.debug("[NormalStep2Tools] web_search failed: %s", _web_tool_err)
                        return "", search_query
                    return search_context_text, search_query
                async def _stage2_prior_image_tool():
                    if literal_reply_text:
                        return ""
                    if not planner_for_stage2_tools.get("use_prior_image_context"):
                        return ""
                    try:
                        return format_prior_injection_block(
                            await get_last_n_for_injection(
                                request.username,
                                _main_character_id,
                                _conv,
                                n=INJECT_MAX,
                            )
                        )
                    except Exception as _prior_tool_err:
                        logger.debug("[NormalStep2Tools] prior image context failed: %s", _prior_tool_err)
                        return ""
                async def _stage2_asset_tool():
                    if literal_reply_text:
                        return None, {}, {}
                    try:
                        from .assets import plan_assets_for_reply
                        return await plan_assets_for_reply(
                            planner_for_stage2_tools,
                            selector_model=router_cfg or {},
                            username=request.username,
                            character_id=_speaker_character_id,
                            recent_messages=recent_chat,
                            character_prompt_context=_planner_step1_character_context,
                            environment_context=planner_environment_context,
                            age_rating="all",
                            debug_role_params=_debug_role_params,
                        )
                    except Exception as _asset_err:
                        logger.debug("[Assets] plan/select assets failed: %s", _asset_err)
                        return None, {}, {}
                async def _stage2_self_cognition_tool():
                    if literal_reply_text:
                        return ""
                    try:
                        return await run_normal_self_cognition(
                            character_prompt_context=_planner_character_context,
                            user_text=_last_user_text_for_memory,
                            planner_result=planner_for_stage2_tools,
                            recent_messages=recent_chat,
                            environment_context=_planner_self_cognition_environment_context,
                            router_cfg=router_cfg or {},
                            username=request.username,
                            character_id=_speaker_character_id,
                            debug_role_params=_debug_role_params,
                        )
                    except Exception as _self_tool_err:
                        logger.debug("[NormalStep2Tools] self_cognition failed: %s", _self_tool_err)
                        return ""
                async def _stage2_memory_recall_tool():
                    if literal_reply_text:
                        return default_planner_result()["memory_recall"]
                    try:
                        return await run_normal_memory_recall_tool(
                            recent_chat,
                            router_cfg or {},
                            planner_result=planner_for_stage2_tools,
                            context_memory=_planner_mem_text,
                            long_memory=_planner_long_mem,
                            guest_group_memory=_planner_guest_group_mem,
                            character_prompt_context=_planner_character_context,
                            username=request.username,
                            character_id=_speaker_character_id,
                            debug_role_params=_debug_role_params,
                            charge_membership_chat_quota=True,
                        )
                    except Exception as _memory_recall_err:
                        logger.debug("[NormalStep2Tools] memory_recall failed: %s", _memory_recall_err)
                        return default_planner_result()["memory_recall"]
                async def _stage2_fact_judgement_tool():
                    if literal_reply_text:
                        return default_planner_result()["fact_judgement"]
                    try:
                        evidence_messages = [
                            {
                                "role": str(m.get("role") or ""),
                                "content": str(m.get("content") or ""),
                            }
                            for m in (recent_chat or [])
                            if isinstance(m, dict) and str(m.get("content") or "").strip()
                        ]
                        return await run_normal_fact_judgement_review(
                            recent_chat,
                            router_cfg or {},
                            planner_result=planner_for_stage2_tools,
                            evidence_messages=evidence_messages,
                            environment_context=planner_environment_context,
                            scene_candidate=_scene_candidate,
                            character_prompt_context=_planner_character_context,
                            user_species=getattr(request, "_user_species", "") or "",
                            username=request.username,
                            character_id=_speaker_character_id,
                            debug_mode="normal",
                            debug_stage=_normal_stage2_fact_stage,
                            debug_role_params=_debug_role_params,
                        )
                    except Exception as _fact_tool_err:
                        logger.debug("[NormalStep2Tools] fact_judgement failed: %s", _fact_tool_err)
                        return default_planner_result()["fact_judgement"]
                (
                    _expression_dedup_report,
                    vision_ctx,
                    (_search_context, _localized_search_query),
                    prior_text,
                    (_reply_sequence, _asset_by_request_id, _asset_debug),
                    _stage2_character_profile,
                    _memory_recall,
                    _fact_judgement,
                ) = await await_normal_stage(
                    asyncio.gather(
                        _stage2_expression_dedup_tool(),
                        _stage2_vision_tool(),
                        _stage2_web_search_tool(),
                        _stage2_prior_image_tool(),
                        _stage2_asset_tool(),
                        _stage2_self_cognition_tool(),
                        _stage2_memory_recall_tool(),
                        _stage2_fact_judgement_tool(),
                    ),
                    "NORMAL_STEP_2_TOOL_GATHER",
                )
                raise_if_normal_superseded("NORMAL_STEP_2_TOOL_GATHER_DONE")
                if _expression_dedup_report:
                    try:
                        from .normal_planner import _apply_expression_dedup_report
                        planner_result = _apply_expression_dedup_report(
                            {
                                **planner_result,
                                "expression_dedup_report": _expression_dedup_report,
                            }
                        )
                    except Exception as _dedup_apply_err:
                        logger.debug("[NormalStep2Tools] expression_dedup apply failed: %s", _dedup_apply_err)
                if _memory_recall:
                    planner_result = {
                        **planner_result,
                        "memory_recall": _memory_recall,
                    }
                if _fact_judgement:
                    planner_result = {
                        **planner_result,
                        "fact_judgement": _fact_judgement,
                    }
                    planner_result = _apply_model_relationship_evidence_policy(planner_result)
                    planner_result = _apply_model_description_request_policy(planner_result)
                    planner_result = _apply_direct_location_query_policy(planner_result, _latest_user_text(request))
                    if _fact_judgement_has_terminal_death(planner_result):
                        setattr(request, "_normal_terminal_death_action", True)
                        setattr(request, "_normal_terminal_death_message_id", _latest_user_message_id_from_request(request))
                        setattr(request, "_normal_terminal_death_reason", "step2_fact_judgement_terminal_event")
                        planner_result = _apply_terminal_death_reply_policy(planner_result)
                try:
                    _scene_final = await finalize_normal_scene_from_fact_judgement(
                        _fact_judgement,
                        candidate_scene_anchor=_normal_scene_anchor,
                        candidate_scene_card=_normal_scene_anchor_card,
                        recent_messages=recent_chat,
                        character_prompt_context=_planner_character_context,
                        current_character_name=_extract_character_name_from_context(_planner_character_context),
                        username=request.username,
                        character_id=_speaker_character_id,
                        conversation_id=_scene_context_conv,
                    )
                    if _scene_final and str(_scene_final.get("scene_card") or "").strip():
                        _normal_scene_anchor_card = str(_scene_final.get("scene_card") or "").strip()
                        _normal_scene_anchor = _scene_final.get("scene_anchor") or _normal_scene_anchor
                        setattr(request, "_normal_scene_anchor_card", _normal_scene_anchor_card)
                        setattr(request, "_normal_scene_anchor", _normal_scene_anchor)
                        if isinstance(planner_result.get("fact_judgement"), dict):
                            _scene_conflict_resolved = bool(_scene_final.get("scene_conflict_resolved"))
                            _fact_report = {
                                **planner_result["fact_judgement"],
                                "scene_anchor": _normal_scene_anchor,
                                "scene_card": _normal_scene_anchor_card,
                            }
                            if _scene_conflict_resolved:
                                _misleading = list(_fact_report.get("misleading_sources") or [])
                                _misleading.append("Step 2 场景位置与 Step 1 材料准备/最终 scene_card 冲突，已保留最终 scene_card。")
                                _forbidden = list(_fact_report.get("forbidden_inferences") or [])
                                _forbidden.append("不得使用已被最终 scene_card 覆盖的旧私聊位置或旧候选位置。")
                                _fact_report = {
                                    **_fact_report,
                                    "misleading_sources": _misleading[:8],
                                    "forbidden_inferences": _forbidden[:8],
                                    "writing_guidance": (
                                        "Step 3 先按最终 scene_card/scene_anchor 的 current_character.position 回答当前位置；"
                                        "旧私聊/旧候选位置若与 scene_card 冲突一律不用；"
                                        "暗号、听见内容和其他角色位置仍按记忆摘要/scene_card 中的非冲突事实回答。"
                                    ),
                                }
                            _latest_scene_user_text = _latest_user_text(request)
                            _scene_card_is_stale = any(
                                marker in _normal_scene_anchor_card
                                for marker in ("状态: stale", "background_only", "历史/作废物品", "本轮禁止写成当前物品")
                            )
                            _scene_user_continues = any(
                                marker in _latest_scene_user_text
                                for marker in ("继续", "刚才", "刚刚", "还在", "接着", "那个场景", "昨晚")
                            )
                            if _scene_card_is_stale and not _scene_user_continues:
                                _misleading = list(_fact_report.get("misleading_sources") or [])
                                _forbidden = list(_fact_report.get("forbidden_inferences") or [])
                                _misleading.append(
                                    "长间隔低连续性重开：上一条 assistant 对旧场景、红皮书、茶几或旧物品的说法只作历史回复，不是当前活动。"
                                )
                                _forbidden.append(
                                    "当前用户没有继续旧场景；最终正文不得出现红皮书、茶几、蓝色陶瓷杯、银色钥匙、落地灯、用户家客厅等旧场景/旧物品词，也不得写正在看、刚刚在看、正在拿或仍在现场。"
                                )
                                _stale_guidance = (
                                    "长间隔重开写作边界：本轮只回答角色自己的当下日常活动，活动必须与旧客厅和旧物品无关；"
                                    "可写整理笔记、准备点心、伸展、照看小动物或其他角色日常，但不要提红皮书、茶几、杯子、钥匙、落地灯或用户家客厅。"
                                )
                                _existing_guidance = str(_fact_report.get("writing_guidance") or "").strip()
                                _fact_report = {
                                    **_fact_report,
                                    "misleading_sources": _misleading[:10],
                                    "forbidden_inferences": _forbidden[:10],
                                    "writing_guidance": (
                                        (_existing_guidance + "；") if _existing_guidance else ""
                                    ) + _stale_guidance,
                                }
                            planner_result = {
                                **planner_result,
                                "fact_judgement": _fact_report,
                            }
                except Exception as _scene_finalize_err:
                    logger.debug("[NormalScene] finalize scene state failed: %s", _scene_finalize_err)
                if vision_ctx.should_refuse:
                    planner_result = {
                        **planner_result,
                        "web_search": False,
                        "search_query": None,
                        "vision_web": False,
                        "use_prior_image_context": False,
                        "image_context_reason": "当前上传图已被拦截，不引用历史识图。",
                        "reply_intent": "设界并自然转移话题",
                        "tone": "符合角色、简短自然，不展开说明系统策略或图片细节",
                        "length": "short",
                        "bubble_count": 1,
                        "initiative_level": 45,
                        "speech_activity": 45,
                        "speech_reason": "图片被拦截后仍需要一句简短设界回应",
                        "should_ask_question": False,
                        "risk_notes": "图片已被系统拒绝识别；不要描述、猜测或复述图片内容，只让角色简短说明被拦截并转向其他内容。",
                        "asset_plan": {
                            **(planner_result.get("asset_plan") or {}),
                            "enabled": False,
                            "count": 0,
                        },
                    }
                elif is_vision_tool_error_context(vision_ctx):
                    _expr = str(planner_result.get("expression_policy") or "").strip()
                    _error_policy = (
                        "当前图片识别结果不是用户原图内容，而是一张服务器视觉识别异常提示；"
                        "角色应像看见这张异常提示截图一样，简短自然地告诉用户这边识图服务似乎故障了，"
                        "不要描述用户原图里的物品、文字、颜色或细节。"
                    )
                    planner_result = {
                        **planner_result,
                        "web_search": False,
                        "search_query": None,
                        "vision_web": False,
                        "use_prior_image_context": False,
                        "image_context_reason": "本轮上传图片已进入 Step2 视觉工具，但视觉结果是服务端异常提示。",
                        "reply_intent": "说明图片识别服务异常",
                        "tone": "符合角色，简短、诚实、自然",
                        "length": "short",
                        "bubble_count": 1,
                        "speech_activity": 45,
                        "speech_reason": "用户发了图片，但视觉工具返回服务端异常提示，需要把故障自然告知用户",
                        "should_ask_question": False,
                        "expression_policy": _error_policy if not _expr else f"{_expr}；{_error_policy}",
                        "risk_notes": (
                            str(planner_result.get("risk_notes") or "").strip()
                            + "；图片识别工具返回服务端异常提示，不得假装看到用户原图。"
                        ).strip("；"),
                    }
                planner_result = apply_story_progression_policy(
                    planner_result,
                    story_progression_policy_messages_for_request(request, recent_chat),
                )
                planner_result = apply_group_relationship_tension_policy(
                    planner_result,
                    recent_chat,
                    at_event_context=_at_event_context,
                    environment_context=planner_environment_context,
                    scene_anchor_card=_normal_scene_anchor_card,
                )
                search_context = _search_context or ""
                if (
                    planner_result.get("web_search")
                    and _localized_search_query
                    and _localized_search_query != planner_result.get("search_query")
                ):
                    logger.info(
                        "[NormalPlanner] 已按客户端位置补全搜索词: %s -> %s",
                        planner_result.get("search_query"),
                        _localized_search_query,
                    )
                    planner_result = {**planner_result, "search_query": _localized_search_query}
                if planner_result.get("use_prior_image_context") and not (prior_text or "").strip():
                    planner_result = {**planner_result, "use_prior_image_context": False}
                    if not (planner_result.get("image_context_reason") or "").strip():
                        planner_result["image_context_reason"] = "无历史识图可注入"
                if _reply_sequence is not None:
                    planner_result = {**planner_result, "reply_sequence": _reply_sequence}
                    setattr(request, "_assistant_reply_sequence", _reply_sequence)
                if _asset_by_request_id:
                    setattr(request, "_assistant_asset_by_request_id", _asset_by_request_id)
                    setattr(request, "_assistant_asset_attachments", list(_asset_by_request_id.values()))
                setattr(request, "_assistant_asset_debug", _asset_debug)
                setattr(request, "_normal_stage2_character_profile", _stage2_character_profile)
                planner_result = _force_normal_planner_reply_if_requested(request, planner_result)
                if getattr(request, "_normal_dead_spirit_reply", False):
                    planner_result = _apply_dead_spirit_reply_policy(planner_result)
                    for _attr in (
                        "_assistant_asset_by_request_id",
                        "_assistant_asset_attachments",
                        "_assistant_asset_message_meta",
                        "_assistant_asset_message_ids",
                        "_assistant_asset_message_ids_by_request_id",
                    ):
                        if hasattr(request, _attr):
                            try:
                                delattr(request, _attr)
                            except Exception:
                                setattr(request, _attr, None)
                if planner_result.get("reply_sequence"):
                    setattr(request, "_assistant_reply_sequence", planner_result["reply_sequence"])
                if not (
                    getattr(request, "_normal_dead_spirit_reply", False)
                    or getattr(request, "_normal_terminal_death_action", False)
                ):
                    try:
                        _delivery_contract_recent = build_chat_router_recent_user_assistant(
                            request,
                            active_model,
                            model_name,
                            max_messages=40,
                        )
                    except Exception:
                        _delivery_contract_recent = recent_chat
                    planner_result = _apply_step1_delivery_contract(
                        planner_result,
                        _delivery_contract_recent or recent_chat,
                        current_speaker_character_id=_speaker_character_id,
                        main_character_id=_main_character_id,
                    )
                _stage3_asset_attachments = list(getattr(request, "_assistant_asset_attachments", None) or [])
                setattr(request, "_normal_stage2_vision_context", vision_ctx)
                setattr(request, "_normal_stage3_scene_anchor_card", _normal_scene_anchor_card)
                setattr(request, "_normal_stage3_guest_group_memory", _planner_guest_group_mem_slim)
                setattr(request, "_normal_stage3_revision_context", revision_context)
                setattr(request, "_normal_stage3_prior_image_context", prior_text)
                setattr(request, "_normal_stage3_search_context", search_context)
                setattr(request, "_normal_stage3_at_event_context", _at_event_context)
                setattr(request, "_normal_stage3_selected_asset_attachments", _stage3_asset_attachments)
                _augment_block = build_normal_mode_augment_block(
                    vision_context=vision_ctx,
                    search_context=search_context,
                    planner_result=planner_result,
                    prior_image_injection_text=prior_text,
                    recent_messages=recent_chat,
                    revision_context=revision_context,
                    user_species=getattr(request, "_user_species", "") or "",
                    is_new_contact_opening=is_new_contact_opening,
                    character_prompt_context=_stage2_character_profile,
                    raw_character_prompt_context=_planner_character_context,
                    scene_anchor_card=_normal_scene_anchor_card,
                    guest_group_memory=_planner_guest_group_mem_slim,
                    at_event_context=_at_event_context,
                    selected_asset_attachments=_stage3_asset_attachments,
                )
                if _augment_block:
                    setattr(request, "_planner_augment_block", _augment_block)
                setattr(request, "_normal_planner_result", planner_result)
                setattr(request, "_planner_memory_notes", build_planner_memory_notes(planner_result))
                if request.username and _speaker_character_id and _speaker_context_conv:
                    try:
                        await save_emotion_from_planner(
                            request.username,
                            _speaker_character_id,
                            _speaker_context_conv,
                            planner_result,
                            _emotion_state or {},
                            get_database(),
                        )
                    except Exception as _emotion_save_err:
                        logger.debug("[EmotionState] save from planner failed: %s", _emotion_save_err)
                use_prior = bool(
                    planner_result.get("use_prior_image_context")
                    and (prior_text or "").strip()
                )
                last_reply_flag = use_prior or (
                    bool(preserved_image_urls) and _round_image_ok(vision_ctx)
                )
                append_fields = None
                if preserved_image_urls and _round_image_ok(vision_ctx):
                    append_fields = {
                        "user_text": u_txt,
                        "image_count": len(preserved_image_urls),
                        "should_refuse": bool(vision_ctx.should_refuse),
                        "image_summary": vision_ctx.image_summary or "",
                        "visible_text": vision_ctx.visible_text or "",
                        "identified_entities": list(vision_ctx.identified_entities or []),
                        "uncertainty": vision_ctx.uncertainty or "",
                        "error": vision_ctx.error or "",
                    }
                setattr(
                    request,
                    "_normal_image_post",
                    {
                        "username": request.username,
                        "character_id": _main_character_id,
                        "conversation_id": _conv,
                        "append_fields": append_fields,
                        "last_reply_based_on_image": last_reply_flag,
                    },
                )
                raise_if_normal_superseded("NORMAL_STEP_3_BEFORE_REPLY")
            except NormalGenerationSuperseded as superseded:
                return normal_superseded_response(superseded.stage)
            except Exception as _sr_err:
                logger.warning("🧭 [智能路由/导演] 视、规划或搜索阶段异常（继续主流程）: %s", _sr_err)
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
        is_doubao_model = "ark.cn-beijing.volces.com" in endpoint_lower or any(k in model_name_lower for k in ["doubao", "seed"])
        is_qwen_model = (not is_local_model) and ("dashscope.aliyuncs.com" in endpoint_lower or "qwen" in model_name_lower)
        if is_doubao_model or is_qwen_model:
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
        _galgame_step_sys_prompt = ""
        if request.mode in ("galgame", "galgame_lock"):
            _char_profile = getattr(request, "_galgame_char_profile", "")
            if _char_profile:
                from ..galgame import build_galgame_step_system_prompt as _build_step_sys
                _galgame_step_sys_prompt = _build_step_sys(
                    char_profile=_char_profile,
                )
                for _m in messages:
                    if _m.get("role") == "system" and "placeholder" in (_m.get("content") or ""):
                        _m["content"] = _galgame_step_sys_prompt
                        break
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
        if is_doubao_model and active_model.get("enable_thinking") is False:
            reasoning_policy.thinking_type = "disabled"
            reasoning_policy.reasoning_effort = None
            reasoning_policy.effort = None
            logger.info("💭 [思考控制] Doubao 模型用户已关闭思考，thinking_type → disabled")
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
            k in model_name_lower for k in ["o1", "thinking", "doubao", "seed", "grok", "gemini"]
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
            "豆包 Responses API" if isinstance(provider, DoubaoProvider) and uses_responses_format else
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
            _enable_thinking = True if (is_doubao_model or is_qwen_model) else None
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
            def _step_param(task_key: str) -> dict:
                cfg = get_llm_task_config(task_key)
                return {
                    "temperature": cfg.get("temperature"),
                    "max_tokens": cfg.get("max_output_tokens"),
                    "timeout_seconds": cfg.get("timeout_seconds"),
                    "enable_thinking": bool(cfg.get("enabled", False)),
                    "thinking_depth": cfg.get("depth"),
                }
            log_params["note"] = "分步生成模式：此处 system 为 Step1 实际系统提示；各步实际参数见 step_params"
            log_params["step_params"] = {
                "step_1_director": _step_param("galgame_seq_step_1_director"),
                "step_2_vitals": _step_param("galgame_seq_step_2_vitals"),
                "steps_3_6_text": _step_param("galgame_seq_step_3_7_text"),
                "step_7_response": _step_param("galgame_seq_step_7_response"),
                "step_8_metadata_json": _step_param("galgame_seq_step_8_json"),
                "step_9_options": _step_param("galgame_seq_step_9_options"),
                "step_10_memory": _step_param("galgame_seq_step_10_memory"),
            }
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
            await release_lock()
