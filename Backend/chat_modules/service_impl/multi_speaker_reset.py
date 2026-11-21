from __future__ import annotations



_NORMAL_MULTI_SPEAKER_RESET_ATTRS = (
    "_normal_speaker_character_id",
    "_normal_speaker_character_name",
    "_normal_speaker_character_avatar",
    "_normal_speaker_is_guest",
    "_normal_speaker_recent_context",
    "_normal_speaker_private_context",
    "_normal_speaker_private_conversation_id",
    "_normal_stage2_character_context",
    "_normal_stage2_context_memory",
    "_normal_stage2_long_memory",
    "_normal_planner_result",
    "_normal_voice_reply_result",
    "_normal_voice_sentences_by_text_index",
    "_normal_handoff_router_result",
    "_assistant_message_meta",
    "_assistant_asset_message_meta",
    "_assistant_asset_message_ids",
    "_assistant_asset_message_ids_by_request_id",
    "_assistant_reply_sequence",
    "_assistant_asset_by_request_id",
    "_assistant_asset_attachments",
    "_normal_terminal_death_action",
    "_normal_terminal_death_message_id",
    "_normal_terminal_death_reason",
    "_normal_committed_death_message_id",
    "_normal_live_turn",
    "_normal_reply_batch",
    "_normal_dead_spirit_reply",
    "_normal_auto_handoff",
    "_normal_guest_direct_memory_written",
)


def _clone_normal_request_for_multi_speaker(
    request: ChatRequest, reply_character_id: str, *, is_auto_handoff: bool = False,
) -> ChatRequest:
    reply_character_id = str(reply_character_id or "").strip()
    original_reply_ids = normal_forced_reply_character_ids(request) or requested_reply_character_ids(request)
    from .normal_speaker import _explicit_reply_character_ids
    selected_ids = getattr(request, "_normal_user_selected_reply_character_ids", None)
    if selected_ids is None:
        selected_ids = _explicit_reply_character_ids(request)
    # Runtime state contains locks, transactions and Agent sessions. Remove it
    # from a shallow model copy before deep-copying the child-owned payload.
    child = request.model_copy(deep=False)
    reset_attrs = (*_NORMAL_MULTI_SPEAKER_RESET_ATTRS, *[k for k in vars(child) if k.startswith("_autonomous_")])
    for attr in reset_attrs:
        if hasattr(child, attr):
            delattr(child, attr)
    child = child.model_copy(deep=True)
    batch = getattr(request, '_normal_reply_batch', None)
    if batch is not None:
        child._normal_reply_batch = batch
    child.reply_character_id = reply_character_id
    child.reply_character_ids = None
    setattr(child, "_normal_multi_speaker_child", True)
    setattr(child, "_normal_multi_original_reply_character_ids", list(original_reply_ids or []))
    setattr(child, "_normal_user_selected_reply_character_ids", list(selected_ids))
    setattr(child, "_normal_auto_handoff", is_auto_handoff)
    setattr(child, "_normal_suppress_generation_lock_release", True)
    setattr(child, "_normal_enable_stage3_handoff_events", True)
    mark_normal_forced_reply_characters(child, [reply_character_id] if reply_character_id and not is_auto_handoff else [])
    return child


def _force_normal_planner_reply_if_requested(request: ChatRequest, planner_result: dict[str, Any]) -> dict[str, Any]:
    forced_ids = normal_forced_reply_character_ids(request)
    if not forced_ids:
        return planner_result
    try:
        bubble_count = int((planner_result or {}).get("bubble_count") or 0)
    except Exception:
        bubble_count = 0
    if bubble_count > 0:
        return planner_result

    forced = dict(planner_result or {})
    try:
        speech_activity = int(forced.get("speech_activity") or 0)
    except Exception:
        speech_activity = 0
    forced["speech_activity"] = max(45, speech_activity)
    forced["bubble_count"] = 1
    forced["speech_reason"] = "用户本轮明确指定该角色发言，必须生成至少一个回复气泡。"
    forced["should_ask_question"] = False
    if not forced.get("reply_sequence"):
        forced["reply_sequence"] = [{"type": "text", "intent": "forced_reply"}]
    if isinstance(forced.get("voice_reply"), dict) and not forced["voice_reply"].get("enabled"):
        forced["voice_reply"] = {
            **forced["voice_reply"],
            "reason": forced["speech_reason"],
        }
    logger.info(
        "[NormalSpeaker] forced reply lifted no-reply planner result user=%s main=%s forced=%s",
        getattr(request, "username", ""),
        (getattr(request, "character_id", "") or "")[:12],
        [sid[:12] for sid in forced_ids],
    )
    return forced


def _normal_forced_main_reply_requested(request: ChatRequest) -> bool:
    main_id = str(getattr(request, "character_id", "") or "").strip()
    return bool(main_id and main_id in normal_forced_reply_character_ids(request))


def _normal_planner_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


async def _normal_handoff_target_allowed(
    request: ChatRequest,
    reply_id: str,
    *,
    current_reply_id: str,
) -> bool:
    reply_id = str(reply_id or "").strip()
    current_reply_id = str(current_reply_id or "").strip()
    if not reply_id or reply_id == current_reply_id:
        return False
    if reply_id == str(getattr(request, "character_id", "") or "").strip():
        return True
    try:
        return bool(await load_owned_visible_character(getattr(request, "username", None), reply_id))
    except Exception as exc:
        logger.debug("[NormalSpeaker] handoff target validation failed id=%s: %s", reply_id[:12], exc)
        return False


def _normal_user_active_for_role_handoff(request: ChatRequest) -> bool:
    turn = getattr(request, "_normal_live_turn", None)
    if turn is not None and turn.routing_waiting:
        return False
    username = str(getattr(request, "username", "") or "").strip()
    character_id = str(getattr(request, "character_id", "") or "").strip()
    mode = str(getattr(request, "mode", "") or "normal").strip() or "normal"
    conversation_id = str(getattr(request, "conversation_id", "") or "").strip()
    username = str(username or "").strip()
    if not username or not character_id or not conversation_id:
        return False
    try:
        return manager.is_active_chat(
            username,
            character_id=character_id,
            mode=mode,
            conversation_id=conversation_id,
        )
    except Exception as exc:
        logger.debug("[NormalSpeaker] active chat check failed user=%s: %s", username, exc)
        return False


async def _iter_chat_response_events(response: Any):
    if isinstance(response, JSONResponse):
        try:
            payload = json.loads((response.body or b"{}").decode("utf-8"))
        except Exception:
            payload = {}
        for event in payload.get("events") or []:
            if isinstance(event, dict) and event.get("type") == "done":
                continue
            yield event
        return

    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is None:
        return

    buffer = ""
    async for chunk in body_iterator:
        if isinstance(chunk, bytes):
            buffer += chunk.decode("utf-8", errors="ignore")
        else:
            buffer += str(chunk or "")
        while "\n\n" in buffer:
            packet, buffer = buffer.split("\n\n", 1)
            for line in packet.splitlines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                if data == "[DONE]":
                    yield None
                    continue
                try:
                    yield json.loads(data)
                except Exception:
                    yield {"error": data}

    tail = buffer.strip()
    if tail.startswith("data:"):
        data = tail[5:].strip()
        if data == "[DONE]":
            yield None
        elif data:
            try:
                yield json.loads(data)
            except Exception:
                yield {"error": data}


def _normal_multi_error_event(
    detail: Any,
    *,
    status_code: int | None = None,
    index: int,
    total: int,
    reply_id: str,
) -> dict[str, Any]:
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("reason") or detail.get("error") or detail.get("status") or detail)
        raw_detail = detail
    else:
        message = str(detail or "多角色回复失败")
        raw_detail = detail
    event: dict[str, Any] = {
        "type": "error",
        "message": message,
        "multi_reply_index": index,
        "multi_reply_total": total,
        "multi_reply_character_id": reply_id,
    }
    if status_code is not None:
        event["status_code"] = status_code
    if raw_detail:
        event["detail"] = raw_detail
    return event


_NORMAL_DISPLAY_DELAY_EVENT_TYPES = {"assistant_paragraph", "assistant_asset"}


def _normal_message_event_delay_seconds(event: dict[str, Any]) -> float:
    if not isinstance(event, dict) or event.get("type") not in _NORMAL_DISPLAY_DELAY_EVENT_TYPES:
        return 0.0
    existing = event.get("display_delay_seconds")
    if existing is not None:
        try:
            return max(0.0, float(existing))
        except (TypeError, ValueError):
            pass

    content = str(event.get("content") or "")
    voice_result = None
    if event.get("voice_state") and event.get("audio_transfer"):
        voice_result = {
            "voice_state": event.get("voice_state"),
            "audio_transfer": event.get("audio_transfer"),
        }
    try:
        from .voice_messages import voice_result_display_delay_seconds

        voice_delay = voice_result_display_delay_seconds(voice_result, content)
    except Exception as exc:
        logger.debug("[NormalSpeaker] display delay helper failed: %s", exc)
        voice_delay = None
    if voice_delay is not None:
        return max(0.0, float(voice_delay))
    from Backend.chat_modules.normal_delivery import normal_text_bubble_delay_seconds
    return normal_text_bubble_delay_seconds(content)


def _annotate_normal_message_event_delay(
    event: dict[str, Any],
    *,
    server_now_ms: int,
    display_at_server_ms: int,
    delay_seconds: float | None = None,
) -> int:
    if delay_seconds is None:
        delay_seconds = _normal_message_event_delay_seconds(event)
    if isinstance(event, dict) and event.get("type") in _NORMAL_DISPLAY_DELAY_EVENT_TYPES:
        event["display_delay_seconds"] = round(delay_seconds, 3)
        event["display_delay_ms"] = int(delay_seconds * 1000)
        event["display_at_server_ms"] = display_at_server_ms
        event["server_now_ms"] = server_now_ms
    return int(delay_seconds * 1000)


async def _handle_normal_multi_speaker_request(
    *,
    request: ChatRequest,
    reply_character_ids: list[str],
    x_client_id: Optional[str],
    x_chat_auth: Optional[str],
    active_model: dict,
    use_json_protocol: bool,
    release_lock,
):
    from Backend.chat_modules.normal_delivery import DeliveryCancelled, NormalDeliverySession
    delivery_session = NormalDeliverySession()
    planned_json_delivery = use_json_protocol and not bool(getattr(request, '_normal_internal_proactive_trigger', False))
    released = False
    live_turn = getattr(request, "_normal_live_turn", None)
    keep_main_inbox = bool(getattr(request, "_normal_continue_guest_scene", False)
                           and reply_character_ids == [request.character_id])
    if live_turn is not None:
        # Each guest has independent tools, identity and private state. The
        # parent remains the reconnectable transport owner, not a shared inbox.
        with live_turn.guard:
            if not keep_main_inbox:
                live_turn.accepting = False
            live_turn.delivery_owner_only = True
        if not keep_main_inbox:
            live_turn.input_ready.set()

    async def release_once() -> None:
        nonlocal released
        if released:
            return
        released = True
        if not planned_json_delivery:
            await delivery_session.finish()
        await release_lock()

    if live_turn is not None:
        try:
            await _persist_android_normal_user_delta(request, client_id=x_client_id or "")
        except BaseException:
            await release_once()
            raise

    async def run_child_events():
        if live_turn is not None:
            latest_user = next((m for m in reversed(request.messages or [])
                                if m.role == "user" and not getattr(m, "isHidden", False)), None)
            yield {"type": "accepted", "job_id": live_turn.job_id,
                   "conversation_id": request.conversation_id,
                   "client_message_id": getattr(latest_user, "message_id", None),
                   "accepted_at_ms": int(time.time() * 1000)}
        stop = False
        queue: list[tuple[str, bool]] = [
            (str(rid or "").strip(), False) for rid in reply_character_ids if str(rid or "").strip()
        ]
        max_role_turns_without_user = 30
        index = 0
        first_visible_event_pending = True
        display_schedule_base_ms = int(time.time() * 1000)
        next_display_at_server_ms = display_schedule_base_ms

        async def emit_child_events(events: list[dict[str, Any]]):
            nonlocal first_visible_event_pending, next_display_at_server_ms
            for event in events:
                if not isinstance(event, dict):
                    continue
                if event.get("type") not in _NORMAL_DISPLAY_DELAY_EVENT_TYPES:
                    yield event
                    continue
                for key in (
                    "display_delay_seconds",
                    "display_delay_ms",
                    "display_at_server_ms",
                    "server_now_ms",
                    "delivery_paced",
                ):
                    event.pop(key, None)
                delay_seconds = _normal_message_event_delay_seconds(event)
                if first_visible_event_pending:
                    first_visible_event_pending = False
                    delay_seconds = 0.0
                delay_ms = int(max(0.0, float(delay_seconds or 0.0)) * 1000)
                next_display_at_server_ms += delay_ms
                _annotate_normal_message_event_delay(
                    event,
                    server_now_ms=display_schedule_base_ms,
                    display_at_server_ms=next_display_at_server_ms,
                    delay_seconds=delay_seconds,
                )
                if not planned_json_delivery:
                    await delivery_session.release(event, request, delay_seconds=delay_seconds)
                yield event

        async def collect_child_events(reply_id: str, child_index: int, total_hint: int,
                                       *, is_auto_handoff: bool = False) -> dict[str, Any]:
            child_events: list[dict[str, Any]] = []
            handoff: dict[str, str] = {}
            child_stop = False
            try:
                child_request = _clone_normal_request_for_multi_speaker(
                    request, reply_id, is_auto_handoff=is_auto_handoff)
                child_request._normal_delivery_session = delivery_session
                child_request._normal_delivery_managed_by_parent = True
                initial_main = keep_main_inbox and child_index == 0 and not is_auto_handoff
                if initial_main:
                    if not normal_forced_reply_character_ids(request):
                        child_request.reply_character_id = None
                        mark_normal_forced_reply_characters(child_request, [])
                    if live_turn is not None:
                        # Only this first main Agent receives ordinary user
                        # supplements. Guest handoffs never share its inbox.
                        child_request._normal_live_turn = live_turn
                child_response = await handle_chat_request(
                    child_request,
                    x_client_id,
                    x_chat_auth,
                    active_model,
                    use_json_protocol=use_json_protocol,
                )
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, (dict, str)) else str(exc.detail)
                return {
                    "events": [
                        _normal_multi_error_event(
                            detail,
                            status_code=exc.status_code,
                            index=child_index,
                            total=total_hint,
                            reply_id=reply_id,
                        )
                    ],
                    "handoff": {},
                    "stop": True,
                }

            async for event in _iter_chat_response_events(child_response):
                if event is None:
                    continue
                if isinstance(event, dict) and event.get("type") == "normal_handoff_request":
                    handoff_id = str(event.get("reply_character_id") or "").strip()
                    if handoff_id:
                        handoff = {
                            "reply_character_id": handoff_id,
                            "reason": str(event.get("reason") or "")[:240],
                        }
                    continue
                if isinstance(event, dict):
                    if event.get("error") and event.get("type") != "error":
                        event = _normal_multi_error_event(
                            event.get("error"),
                            status_code=event.get("status_code"),
                            index=child_index,
                            total=total_hint,
                            reply_id=reply_id,
                        )
                        child_stop = True
                    else:
                        event = {
                            **event,
                            "multi_reply_index": child_index,
                            "multi_reply_total": total_hint,
                            "multi_reply_character_id": reply_id,
                        }
                        if event.get("error") or event.get("type") == "cancelled":
                            child_stop = True
                child_events.append(event)
            if initial_main and live_turn is not None:
                with live_turn.guard:
                    live_turn.accepting = False
                live_turn.input_ready.set()
            return {"events": child_events, "handoff": handoff, "stop": child_stop}

        async def maybe_queue_handoff(current_reply_id: str, handoff: dict[str, str], next_index: int) -> None:
            handoff_id = str((handoff or {}).get("reply_character_id") or "").strip()
            if not handoff_id:
                return
            if next_index >= max_role_turns_without_user:
                logger.info(
                    "[NormalSpeaker] Stage3 handoff ignored by max turns user=%s from=%s to=%s limit=%s",
                    getattr(request, "username", ""),
                    current_reply_id[:12],
                    handoff_id[:12],
                    max_role_turns_without_user,
                )
                return
            if not _normal_user_active_for_role_handoff(request):
                logger.info(
                    "[NormalSpeaker] Stage3 handoff ignored because chat inactive user=%s main=%s conv=%s from=%s to=%s",
                    getattr(request, "username", ""),
                    (getattr(request, "character_id", "") or "")[:12],
                    (getattr(request, "conversation_id", "") or "")[:12],
                    current_reply_id[:12],
                    handoff_id[:12],
                )
                return
            if await _normal_handoff_target_allowed(request, handoff_id, current_reply_id=current_reply_id):
                queue.append((handoff_id, True))
                logger.info(
                    "[NormalSpeaker] Stage3 handoff queued user=%s from=%s to=%s reason=%s",
                    getattr(request, "username", ""),
                    current_reply_id[:12],
                    handoff_id[:12],
                    str((handoff or {}).get("reason") or "")[:120],
                )
            else:
                logger.info(
                    "[NormalSpeaker] Stage3 handoff ignored user=%s from=%s to=%s",
                    getattr(request, "username", ""),
                    current_reply_id[:12],
                    handoff_id[:12],
                )

        while queue and not stop:
            if index >= max_role_turns_without_user:
                logger.info(
                    "[NormalSpeaker] Stage3 handoff stopped by max turns user=%s main=%s limit=%s",
                    getattr(request, "username", ""),
                    (getattr(request, "character_id", "") or "")[:12],
                    max_role_turns_without_user,
                )
                break

            if len(queue) > 1 and not queue[0][1]:
                batch: list[tuple[str, bool]] = []
                while queue and not queue[0][1] and index + len(batch) < max_role_turns_without_user:
                    batch.append(queue.pop(0))
                batch_ids = [rid for rid, _ in batch if rid]
                total_hint = index + len(batch_ids) + len(queue)
                logger.info(
                    "[NormalSpeaker] parallel initial batch user=%s main=%s speakers=%s",
                    getattr(request, "username", ""),
                    (getattr(request, "character_id", "") or "")[:12],
                    [sid[:12] for sid in batch_ids],
                )
                results = await asyncio.gather(
                    *[
                        collect_child_events(reply_id, index + offset, total_hint)
                        for offset, reply_id in enumerate(batch_ids)
                    ]
                )
                for result in results:
                    async for event in emit_child_events(result.get("events") or []):
                        yield event
                    if result.get("stop"):
                        stop = True
                index += len(batch_ids)
                if stop:
                    break
                if results and batch_ids:
                    await maybe_queue_handoff(batch_ids[-1], results[-1].get("handoff") or {}, index)
                continue

            reply_id, is_auto_handoff = queue.pop(0)
            if not reply_id:
                continue
            if is_auto_handoff and not _normal_user_active_for_role_handoff(request):
                logger.info(
                    "[NormalSpeaker] Stage3 handoff stopped because chat inactive user=%s main=%s conv=%s next=%s",
                    getattr(request, "username", ""),
                    (getattr(request, "character_id", "") or "")[:12],
                    (getattr(request, "conversation_id", "") or "")[:12],
                    reply_id[:12],
                )
                break
            result = await collect_child_events(reply_id, index, index + 1 + len(queue),
                                                is_auto_handoff=is_auto_handoff)
            async for event in emit_child_events(result.get("events") or []):
                yield event
            if result.get("stop"):
                break
            index += 1
            await maybe_queue_handoff(reply_id, result.get("handoff") or {}, index)

    logger.info(
        "[NormalSpeaker] 多角色 @ 顺序回复 user=%s main=%s speakers=%s",
        getattr(request, "username", ""),
        (getattr(request, "character_id", "") or "")[:12],
        [sid[:12] for sid in reply_character_ids],
    )

    if use_json_protocol:
        events: list[dict] = []
        try:
            async for event in run_child_events():
                if isinstance(event, dict):
                    events.append(event)
        except DeliveryCancelled as exc:
            events.append({'type': 'cancelled', 'reason': str(exc)})
        except BaseException:
            await delivery_session.finish()
            raise
        finally:
            await release_once()
        if not events or events[-1].get("type") != "done":
            events.append({"type": "done"})
        if planned_json_delivery:
            delivery_session.dispatch_json(events, request)
        return JSONResponse(
            {
                "protocol": "ponychat_chat_v1",
                "mode": "normal",
                "events": events,
            }
        )

    async def _lines():
        try:
            async for event in run_child_events():
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except DeliveryCancelled as exc:
            yield f"data: {json.dumps({'type': 'cancelled', 'reason': str(exc)})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            await release_once()

    return StreamingResponse(
        _lines(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
