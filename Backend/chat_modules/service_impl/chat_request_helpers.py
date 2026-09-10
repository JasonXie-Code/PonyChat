from __future__ import annotations

from typing import Optional

from Backend.chat_modules.state import is_generation_current
from Backend.chat_modules.normal_stage_logging import await_logged_normal_stage
from Backend.chat_modules.service_impl.android_normal_accept import maybe_early_android_normal_accepted_response


def normal_generation_current_for_request(request, username, character_id, client_id) -> bool:
    if (request.mode or "normal") != "normal" or request.is_summary_request:
        return True
    return is_generation_current(
        username,
        character_id,
        client_id,
        getattr(request, "_generation_token", None),
    )


async def await_normal_stage_with_generation_guard(
    awaitable,
    stage: str,
    normal_generation_current,
    superseded_error_type,
    *,
    log_context=None,
):
    return await await_logged_normal_stage(
        awaitable,
        stage,
        normal_generation_current,
        superseded_error_type,
        log_context=log_context,
    )


def story_progression_policy_messages_for_request(request, current_recent: Optional[list[dict]] = None) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add_message(msg) -> None:
        if not msg:
            return
        if isinstance(msg, dict):
            role = str(msg.get("role") or "").strip()
            content = str(msg.get("content") or "").strip()
            hidden = bool(msg.get("isHidden") or msg.get("hidden"))
            message_id = str(msg.get("message_id") or msg.get("messageId") or "").strip()
            speaker_character_id = msg.get("speaker_character_id") or msg.get("speakerCharacterId")
            speaker_name = msg.get("speaker_name") or msg.get("speakerName")
        else:
            role = str(getattr(msg, "role", "") or "").strip()
            content = str(getattr(msg, "content", "") or "").strip()
            hidden = bool(getattr(msg, "isHidden", False) or getattr(msg, "hidden", False))
            message_id = str(
                getattr(msg, "message_id", "")
                or getattr(msg, "messageId", "")
                or ""
            ).strip()
            speaker_character_id = getattr(msg, "speaker_character_id", None) or getattr(msg, "speakerCharacterId", None)
            speaker_name = getattr(msg, "speaker_name", None) or getattr(msg, "speakerName", None)
        if hidden or role not in {"user", "assistant"} or not content:
            return
        if message_id:
            key = (message_id, role, "")
            if key in seen:
                return
            seen.add(key)
        item = {"role": role, "content": content}
        if speaker_character_id:
            item["speaker_character_id"] = speaker_character_id
        if speaker_name:
            item["speaker_name"] = speaker_name
        merged.append(item)

    for item in list(current_recent or []):
        add_message(item)
    for item in list(request.messages or []):
        add_message(item)
    return merged[-80:]


async def release_normal_generation_lock_for_request(
    request,
    username,
    character_id,
    client_id,
    normal_generation_current,
    generation_locker,
    manager,
    logger,
) -> None:
    if getattr(request, "_normal_suppress_generation_lock_release", False):
        logger.debug(
            "🔒 [生成锁] multi-speaker child 跳过释放 user=%s char=%s",
            username,
            character_id[:8] if character_id else "",
        )
        return
    if username and character_id:
        if (request.mode or "normal") == "normal" and not request.is_summary_request and not normal_generation_current():
            logger.info(
                "🔒 [生成锁] 跳过旧 normal 请求释放，避免解锁新请求 user=%s char=%s client=%s token=%s",
                username,
                character_id[:8] if character_id else "",
                client_id,
                getattr(request, "_generation_token", None),
            )
            return
        await generation_locker.release(username, character_id, client_id)
        await manager.broadcast_to_user(username, {
            "type": "GENERATION_LOCK",
            "status": "unlocked",
            "character_id": character_id,
            "source": client_id,
        })
        await manager.broadcast_sync(username, "generation_complete", source=client_id, character_id=character_id)
        logger.info(f"🔓 [生成锁] 自动释放 (Mode: {request.mode})")


async def handle_quota_no_reply_if_needed(
    request,
    client_id,
    use_json_protocol,
    release_lock,
    rebuild_android_normal_request_from_server_history,
    normal_no_reply_response,
    logger,
    time_module,
):
    if not (
        (request.mode or "normal") == "normal"
        and not request.is_summary_request
        and not getattr(request, "_normal_multi_speaker_child", False)
    ):
        return None
    quota_no_reply = getattr(request, "_quota_exceeded_no_reply", None)
    if not quota_no_reply:
        return None
    save_ok = True
    save_msg = ""
    try:
        from Backend.chat_modules.runtime import run_conversation_persistence

        await rebuild_android_normal_request_from_server_history(request, client_id=client_id)
        save_ok, save_msg, _ = await run_conversation_persistence(
            request,
            "quota_no_reply",
            "",
            int(time_module.time() * 1000),
            persist_user_only=True,
        )
    except Exception as quota_save_err:
        save_ok = False
        save_msg = str(quota_save_err)
        logger.warning("[QuotaNoReply] 保存普通模式用户消息失败: %s", quota_save_err)
    await release_lock()
    return normal_no_reply_response(
        use_json_protocol,
        reason="quota_exceeded",
        save_ok=save_ok,
        save_msg=save_msg,
        quota_message=str(quota_no_reply.get("message") or "今日积分已用完"),
    )


async def handle_requested_normal_reply_speakers_if_needed(
    request,
    x_client_id,
    x_chat_auth,
    active_model,
    use_json_protocol,
    release_lock,
    username,
    character_id,
    client_id,
    config,
    logger,
    requested_reply_character_ids,
    rebuild_android_normal_request_from_server_history,
    resolve_explicit_at_reply_character_ids,
    run_normal_user_speaker_intent_router,
    mark_normal_forced_reply_characters,
    handle_normal_multi_speaker_request,
):
    if not (
        (request.mode or "normal") == "normal"
        and not request.is_summary_request
        and not getattr(request, "_normal_multi_speaker_child", False)
    ):
        return None
    requested_reply_ids = requested_reply_character_ids(request)
    if not requested_reply_ids:
        await rebuild_android_normal_request_from_server_history(request, client_id=client_id)
        requested_reply_ids = await resolve_explicit_at_reply_character_ids(request)
    if not requested_reply_ids and not (getattr(request, "_normal_unresolved_at_mentions", None) or []):
        # Harness keeps deterministic direct-name parsing. Ambiguous speaker
        # choice belongs to the one normal Agent via handoff_reply.
        if getattr(request, "_normal_autonomous_harness_requested", False):
            speaker_intent_cfg = {}
        else:
            speaker_intent_cfg = config.model_manager.get_model_for_task("chat_router") or active_model or config.model_manager.get_active_model() or {}
        requested_reply_ids = await run_normal_user_speaker_intent_router(
            request,
            speaker_intent_cfg,
            username=username,
            character_id=character_id,
            debug_mode=request.mode or "normal",
        )
    if requested_reply_ids:
        logger.info(
            "[NormalSpeaker] requested reply ids user=%s main=%s requested=%s",
            username,
            character_id[:12] if character_id else "",
            [str(rid)[:12] for rid in requested_reply_ids],
        )
    reply_ids = []
    for rid in requested_reply_ids:
        rid = str(rid or "").strip()
        if rid and rid not in reply_ids:
            reply_ids.append(rid)
    mark_normal_forced_reply_characters(request, reply_ids)
    from Backend.chat_modules.normal_speaker import _has_recent_non_main_speaker_candidate
    continue_guest_scene = (
        (not reply_ids or reply_ids == [character_id])
        and not getattr(request, "_normal_internal_proactive_trigger", False)
        and _has_recent_non_main_speaker_candidate(request)
    )
    if continue_guest_scene:
        # Keep an event consumer for the main Agent's handoff_reply on later
        # ordinary turns, even when this user message contains no fresh @.
        request._normal_continue_guest_scene = True
    if continue_guest_scene or (reply_ids and not (len(reply_ids) == 1 and reply_ids[0] == character_id)):
        return await handle_normal_multi_speaker_request(
            request=request,
            reply_character_ids=reply_ids or [character_id],
            x_client_id=x_client_id,
            x_chat_auth=x_chat_auth,
            active_model=active_model,
            use_json_protocol=use_json_protocol,
            release_lock=release_lock,
        )
    return None
