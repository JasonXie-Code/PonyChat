from __future__ import annotations

from Backend.chat_modules.normal_stage_logging import await_logged_normal_stage


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
    交付已生成的普通 Agent 回复，通过「HTTP 体协议」回传。
    - Accept: application/json → 单次 application/json 响应，body 为 { protocol, mode, events }，与旧 line 协议一一对应。
    - 否则：兼容旧 line-oriented（text/event-stream）封装（内部仍无 token 分片，仅装帧与历史客户端一致）。
    """
    if not getattr(request, "_autonomous_harness", False):
        raise ValueError("Normal delivery requires a completed Agent turn")
    voice_character_id = effective_speaker_character_id(request) or character_id
    is_internal_proactive = bool(getattr(request, "_normal_internal_proactive_trigger", False))
    from .normal_delivery import DeliveryCancelled, NormalDeliverySession
    parent_managed_delivery = bool(getattr(request, '_normal_delivery_managed_by_parent', False))
    delivery_session = getattr(request, '_normal_delivery_session', None) or NormalDeliverySession()
    request._normal_delivery_session = delivery_session
    planned_json_delivery = use_json and not is_internal_proactive and not parent_managed_delivery
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
            gen_start_ms = int(time.time() * 1000)
            generation_token = getattr(request, "_generation_token", None)
            class _NormalGenerationSuperseded(Exception):
                def __init__(self, stage: str):
                    super().__init__(stage)
                    self.stage = stage
            def _is_normal_generation_current() -> bool:
                batch = getattr(request, '_normal_reply_batch', None)
                if batch is not None and not batch.current(request._normal_reply_revision):
                    return False
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
                return await await_logged_normal_stage(
                    awaitable,
                    stage,
                    _is_normal_generation_current,
                    _NormalGenerationSuperseded,
                    log_context={
                        "user": username,
                        "char": character_id,
                        "conv": getattr(request, "conversation_id", None),
                        "job": accepted_job_id,
                    },
                )
            try:
                _raise_if_superseded("NORMAL_STEP_3_START")
            except _NormalGenerationSuperseded as superseded:
                yield _cancelled_packet(superseded.stage)
                yield "data: [DONE]\n\n"
                return
            planner_result = getattr(request, "_normal_planner_result", None) or {}
            if getattr(request, '_normal_shortcut_no_auxiliary', False):
                request._assistant_asset_attachments = []
                request._assistant_asset_by_request_id = {}
                request._assistant_reply_sequence = [{'type':'text','intent':'shortcut'}]
            if int(planner_result.get("bubble_count") or 0) <= 0 and not getattr(request, '_assistant_asset_attachments', None):
                request._autonomous_generation_is_current = _is_normal_generation_current
                speech_reason = str(planner_result.get("speech_reason") or "").strip()
                from .autonomous_service import autonomous_delivery_content
                await autonomous_delivery_content(request, effective_username)
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
                    "[normal_nonstream] Agent 选择零文字气泡，本轮不即时回复 conv=%s reason=%s",
                    getattr(request, "conversation_id", None),
                    speech_reason or "未填写",
                )
                try:
                    save_ok, save_msg, _ = await _await_generation_stage(
                        run_conversation_persistence(request, model_name, "", gen_start_ms,
                                                     persist_user_only=True),
                        "NORMAL_AGENT_SILENCE_PERSIST",
                    )
                except _NormalGenerationSuperseded as superseded:
                    yield _cancelled_packet(superseded.stage)
                    yield "data: [DONE]\n\n"
                    return
                if not save_ok:
                    yield f"data: {json.dumps({'type': 'error', 'error': '回复或记忆保存失败，请重试。'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'no_reply', 'reason': speech_reason}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'save_status', 'success': save_ok, 'message': save_msg or ''}, ensure_ascii=False)}\n\n"
                handoff = getattr(request, "_normal_handoff_router_result", None)
                if (save_ok and getattr(request, "_normal_enable_stage3_handoff_events", False)
                        and isinstance(handoff, dict) and str(handoff.get("reply_character_id") or "").strip()):
                    yield f"data: {json.dumps({'type': 'normal_handoff_request', **handoff}, ensure_ascii=False)}\n\n"
                from .autonomous_service import finalize_autonomous_memory
                try:
                    await asyncio.to_thread(finalize_autonomous_memory, request, save_ok=save_ok,
                                            generation_is_current=_is_normal_generation_current)
                except Exception as memory_error:
                    logger.warning("[AutonomousChat] memory draft not committed: %s", memory_error)
                yield "data: [DONE]\n\n"
                return
            from .autonomous_service import autonomous_delivery_content
            raw_res, inp_tok, out_tok = await autonomous_delivery_content(request, effective_username)
            full_raw_res = raw_res
            try:
                _raise_if_superseded("NORMAL_STEP_3_BEFORE_SIDE_EFFECTS")
            except _NormalGenerationSuperseded as superseded:
                yield _cancelled_packet(superseded.stage)
                yield "data: [DONE]\n\n"
                return
            if getattr(request, '_normal_shortcut_no_auxiliary', False):
                from .expression_context import emoji_symbols
                if emoji_symbols(raw_res):
                    yield f"data: {json.dumps({'error': '快捷回复格式校验失败，请重试'}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
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
                defer_chat_complete_until_voice_ready = True
                setattr(request, "_defer_chat_complete_until_voice_ready", defer_chat_complete_until_voice_ready)
                request._autonomous_generation_is_current = _is_normal_generation_current
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
            if not save_ok:
                yield f"data: {json.dumps({'type': 'error', 'error': '回复或记忆保存失败，请重试。'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps(save_evt, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
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
            if asst_meta and use_json:
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
                from .normal_delivery import normal_text_bubble_delay_seconds
                return normal_text_bubble_delay_seconds(current_content)
            delivery_schedule_base_ms = int(time.time() * 1000)
            next_display_at_server_ms = delivery_schedule_base_ms
            async def _set_message_display_schedule(evt: dict, delay_seconds: float) -> None:
                nonlocal next_display_at_server_ms
                delay = max(0.0, float(delay_seconds or 0.0))
                evt["display_delay_seconds"] = round(delay, 3)
                evt["display_delay_ms"] = int(delay * 1000)
                next_display_at_server_ms += evt["display_delay_ms"]
                evt["display_at_server_ms"] = next_display_at_server_ms
                evt["server_now_ms"] = delivery_schedule_base_ms
                if not parent_managed_delivery and not planned_json_delivery:
                    await delivery_session.release(evt, request, delay_seconds=delay)
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
            if asst_meta and not use_json:
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
                        await _set_message_display_schedule(para_evt, delay_seconds)
                        _raise_if_superseded("NORMAL_STEP_3_BEFORE_EMIT_TEXT")
                    except _NormalGenerationSuperseded as superseded:
                        _cancel_voice_prepare_tasks()
                        yield _cancelled_packet(superseded.stage)
                        yield "data: [DONE]\n\n"
                        return
                    text_idx += 1
                    yield f"data: {json.dumps(para_evt, ensure_ascii=False)}\n\n"
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
                        await _set_message_display_schedule(asset_evt, delay_seconds)
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
                            await _set_message_display_schedule(para_evt, delay_seconds)
                            _raise_if_superseded("NORMAL_STEP_3_BEFORE_EMIT_TEXT")
                        except _NormalGenerationSuperseded as superseded:
                            _cancel_voice_prepare_tasks()
                            yield _cancelled_packet(superseded.stage)
                            yield "data: [DONE]\n\n"
                            return
                        text_idx += 1
                        yield f"data: {json.dumps(para_evt, ensure_ascii=False)}\n\n"
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
                            await _set_message_display_schedule(asset_evt, delay_seconds)
                            _raise_if_superseded("NORMAL_STEP_3_BEFORE_EMIT_ASSET")
                        except _NormalGenerationSuperseded as superseded:
                            _cancel_voice_prepare_tasks()
                            yield _cancelled_packet(superseded.stage)
                            yield "data: [DONE]\n\n"
                            return
                        asset_idx += 1
                        yield f"data: {json.dumps(asset_evt, ensure_ascii=False)}\n\n"
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
            from .autonomous_service import finalize_autonomous_memory
            try:
                await asyncio.to_thread(finalize_autonomous_memory, request, save_ok=save_ok,
                                        generation_is_current=_is_normal_generation_current)
            except Exception as memory_error:
                logger.warning("[AutonomousChat] memory draft not committed: %s", memory_error)
            yield "data: [DONE]\n\n"
            return
        except DeliveryCancelled as exc:
            yield f"data: {json.dumps({'type': 'cancelled', 'reason': str(exc)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.exception("❌ [normal_nonstream] 未预期错误: %s", exc)
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if not parent_managed_delivery and not planned_json_delivery:
                if delivery_session.pending and not _is_normal_generation_current():
                    delivery_session.cancelled = True
                await delivery_session.finish()
            autonomous_store = getattr(request, "_autonomous_memory_store", None)
            if autonomous_store is not None:
                autonomous_store.discard()
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
    if getattr(request, '_normal_reply_batch', None) is not None and not use_json:
        # The durable batch owns cancellation/restart and transport independence.
        # Do not detach a second pump that could deliver a superseded attempt.
        return StreamingResponse(response_lines(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})
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
        if planned_json_delivery:
            delivery_session.dispatch_json(out, request)
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
