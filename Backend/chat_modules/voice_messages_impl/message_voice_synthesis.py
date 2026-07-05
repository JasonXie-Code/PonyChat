from __future__ import annotations



async def _synthesize_message_voice_impl(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    message_id: str,
    content: str,
    voice_id: str | None = None,
    instruct: str | None = None,
    voice_sentences: list[dict[str, Any]] | None = None,
    reply_language: str | None = None,
    push_update: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    config = _character_voice_config(username, character_id)
    selected_voice = (voice_id or config.get("voice_id") or "speaker:serena").strip()
    selected_instruct = (instruct if instruct is not None else config.get("instruct") or "").strip()
    sentence_entries = normalize_voice_sentence_entries(voice_sentences)
    tts_text, fragments = split_voice_reply_text(content)
    if sentence_entries:
        tts_text = join_voice_sentence_texts(sentence_entries)
    if not tts_text:
        failed = normalize_voice_state({"voice_status": "failed", "voice_error": "empty_tts_text"})
        if persist:
            await upsert_voice_state(get_database(), conversation_id=conversation_id, message_id=message_id, state=failed)
        return {"ok": False, "voice_state": failed, "audio_transfer": None, "error": "empty_tts_text"}

    if persist:
        try:
            cached = await get_cached_message_voice_audio(
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
                message_id=message_id,
            )
            if cached:
                logger.debug("[VoiceMsg] serve cached audio mid=%s", message_id[:10])
                return cached
        except Exception as exc:
            logger.warning("[VoiceMsg] cache lookup skipped mid=%s: %s", message_id[:10], exc)

        try:
            pending = await save_pending_voice_state(
                conversation_id=conversation_id,
                message_id=message_id,
                voice_id=selected_voice,
                tts_text=tts_text,
                text_fragments=fragments,
                voice_sentences=sentence_entries,
            )
            if push_update:
                await _push_message_updated(
                    username=username,
                    character_id=character_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    patch=pending,
                )
        except Exception as exc:
            logger.warning("[VoiceMsg] pending state save skipped mid=%s: %s", message_id[:10], exc)
    try:
        voice_fallback_error = ""
        actual_voice_id = selected_voice
        profile_id = str(config.get("voice_profile_id") or "").strip()
        if not profile_id and is_ponychat_voice_profile_id(selected_voice):
            profile_id = selected_voice
        if not profile_id and is_cosyvoice_enabled():
            profile_id = _legacy_qwen_id_to_pony_profile_id(selected_voice)
        profile = (
            await _load_or_recover_voice_profile(
                username=username,
                character_id=character_id,
                profile_id=profile_id,
                config=config,
                selected_voice=selected_voice,
            )
            if profile_id
            else None
        )
        if profile:
            profile_mode = str(profile.get("source_mode") or config.get("source_mode") or "").strip().lower()
            recipe_type = "clone" if profile.get("audio_data") else "instruct"
            recipe_segments = sentence_entries if sentence_entries else None
            reference_mime_type = str(profile.get("mime_type") or "audio/wav")
            reference_ext = "mp3" if reference_mime_type == "audio/mpeg" else "wav"
            if is_cosyvoice_enabled():
                cosy_text, cosy_instruct = _recipe_text_and_instruct(
                    fallback_text=tts_text,
                    segments=recipe_segments,
                    profile=profile,
                    selected_instruct=selected_instruct,
                )
                result, voice_fallback_error, actual_voice_id = await _synthesize_cosyvoice_profile_with_recovery(
                    profile=profile,
                    character_id=character_id,
                    text=cosy_text,
                    instruct=cosy_instruct,
                    language=reply_language or None,
                )
            else:
                qwen_cached_voice_id = str(profile.get("qwen_cached_voice_id") or "").strip()
                if not qwen_cached_voice_id and recipe_type == "instruct":
                    design_instruct = str(profile.get("description") or selected_instruct or "").strip()
                    if design_instruct:
                        try:
                            registered_profile = await upsert_character_design_voice_profile(
                                get_database(),
                                username=username,
                                character_id=character_id,
                                character_name=str(profile.get("display_name") or character_id),
                                voice_profile_id=str(profile.get("voice_profile_id") or profile_id),
                                instruct=design_instruct,
                                force_replace=False,
                            )
                            if registered_profile:
                                profile = {**profile, **registered_profile}
                                qwen_cached_voice_id = str(registered_profile.get("qwen_cached_voice_id") or "").strip()
                                if qwen_cached_voice_id:
                                    logger.info(
                                        "[VoiceMsg] registered missing qwen design voice profile=%s qwen_voice=%s",
                                        profile.get("voice_profile_id") or profile_id,
                                        qwen_cached_voice_id,
                                    )
                        except Exception as exc:
                            logger.warning(
                                "[VoiceMsg] qwen design voice registration skipped profile=%s: %s",
                                profile.get("voice_profile_id") or profile_id,
                                exc,
                            )
                if qwen_cached_voice_id:
                    qwen_runtime_voice_id = (
                        qwen_cached_voice_id
                        if qwen_cached_voice_id.lower().startswith("qwen3tts:")
                        else f"qwen3tts:{qwen_cached_voice_id}"
                    )
                    try:
                        result = (
                            await _synthesize_sentence_voice_audio(
                                sentences=sentence_entries,
                                voice_id=qwen_runtime_voice_id,
                                instruct=selected_instruct,
                                reply_language=str(reply_language or ""),
                            )
                            if sentence_entries
                            else await synthesize_tts(
                                text=tts_text,
                                voice_id=qwen_runtime_voice_id,
                                instruct=selected_instruct,
                                language=reply_language or None,
                            )
                        )
                        actual_voice_id = qwen_runtime_voice_id
                    except VoiceLabError as exc:
                        voice_fallback_error = f"{exc.code}:{str(exc)}"[:300]
                        logger.warning(
                            "[VoiceMsg] qwen cached voice failed; falling back to recipe profile=%s voice=%s: %s",
                            profile.get("voice_profile_id") or profile_id,
                            qwen_runtime_voice_id,
                            voice_fallback_error,
                        )
                        result = await synthesize_recipe_tts(
                            text=None if recipe_segments else tts_text,
                            segments=recipe_segments,
                            recipe_type=recipe_type,
                            voice_profile_id=str(profile.get("voice_profile_id") or profile_id),
                            voice_description=str(profile.get("description") or selected_instruct or "").strip(),
                            reference_audio=profile.get("audio_data") if recipe_type == "clone" else None,
                            reference_filename=f"{str(profile.get('voice_profile_id') or 'ponyvoice').replace(':', '_')}.{reference_ext}",
                            reference_mime_type=reference_mime_type,
                            reference_text=str(profile.get("transcript") or config.get("reference_text") or ""),
                            extra_instruct=str(profile.get("extra_instruct") or selected_instruct or ""),
                            language=reply_language or None,
                            ignore_circuit=True,
                        )
                else:
                    result = await synthesize_recipe_tts(
                        text=None if recipe_segments else tts_text,
                        segments=recipe_segments,
                        recipe_type=recipe_type,
                        voice_profile_id=str(profile.get("voice_profile_id") or profile_id),
                        voice_description=str(profile.get("description") or selected_instruct or "").strip(),
                        reference_audio=profile.get("audio_data") if recipe_type == "clone" else None,
                        reference_filename=f"{str(profile.get('voice_profile_id') or 'ponyvoice').replace(':', '_')}.{reference_ext}",
                        reference_mime_type=reference_mime_type,
                        reference_text=str(profile.get("transcript") or config.get("reference_text") or ""),
                        extra_instruct=str(profile.get("extra_instruct") or selected_instruct or ""),
                        language=reply_language or None,
                    )
            selected_voice = str(profile.get("voice_profile_id") or profile_id)
        else:
            if is_cosyvoice_enabled():
                if sentence_entries:
                    direct_text = join_voice_sentence_texts(sentence_entries)
                    direct_instruct = selected_instruct
                    segment_prompts = [
                        str(item.get("instruct") or item.get("emotion_prompt") or item.get("emotionPrompt") or "").strip()
                        for item in sentence_entries
                    ]
                    segment_prompts = [x for x in segment_prompts if x]
                    if segment_prompts:
                        direct_instruct = "；".join(x for x in [direct_instruct, "；".join(segment_prompts)] if x)
                else:
                    direct_text = tts_text
                    direct_instruct = selected_instruct
                result, voice_fallback_error, actual_voice_id = await _synthesize_direct_cosyvoice_with_recovery(
                    text=direct_text,
                    voice_id=selected_voice,
                    instruct=direct_instruct,
                    language=reply_language or None,
                )
            else:
                result = (
                    await _synthesize_sentence_voice_audio(
                        sentences=sentence_entries,
                        voice_id=selected_voice,
                        instruct=selected_instruct,
                        reply_language=str(reply_language or ""),
                    )
                    if sentence_entries
                    else await synthesize_tts(
                        text=tts_text,
                        voice_id=selected_voice,
                        instruct=selected_instruct,
                        language=reply_language or None,
                    )
                )
                actual_voice_id = selected_voice
        cache_key = f"{conversation_id}:{message_id}:{result.job_id}:{result.variant}"
        ready_payload = {
            "voice_status": "ready",
            "voice_id": selected_voice,
            "voice_job_id": result.job_id,
            "voice_cache_key": cache_key,
            "tts_text": tts_text,
            "transcript": tts_text,
            "text_fragments": fragments,
            "voice_sentences": sentence_entries,
        }
        if actual_voice_id and actual_voice_id != selected_voice:
            ready_payload["actual_voice_id"] = actual_voice_id
            ready_payload["actualVoiceId"] = actual_voice_id
        if voice_fallback_error:
            ready_payload["voice_fallback"] = True
            ready_payload["voiceFallback"] = True
        ready = normalize_voice_state(ready_payload)
        audio_transfer = {
            "kind": "bytes",
            "mime": result.mime_type,
            "variant": result.variant,
            "data_base64": base64.b64encode(result.audio_bytes).decode("ascii"),
            "expires_hint_seconds": 86400,
        }
        if persist and push_update:
            try:
                await _push_message_updated(
                    username=username,
                    character_id=character_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    patch={**ready, "audio_transfer": audio_transfer},
                )
            except Exception as exc:
                logger.debug("[VoiceMsg] ready update push skipped mid=%s: %s", message_id[:10], exc)
        if persist:
            try:
                await upsert_voice_state(get_database(), conversation_id=conversation_id, message_id=message_id, state=ready)
            except Exception as exc:
                logger.warning("[VoiceMsg] ready state save skipped mid=%s: %s", message_id[:10], exc)
        await _charge_voice_message_credit(
            username=username,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        return {"ok": True, "voice_state": ready, "audio_transfer": audio_transfer, "error": ""}
    except VoiceLabError as exc:
        logger.warning("[VoiceMsg] synth failed code=%s msg=%s", exc.code, exc)
        failed = normalize_voice_state(
            {
                "voice_status": "failed",
                "voice_id": selected_voice,
                "tts_text": tts_text,
                "transcript": tts_text,
                "text_fragments": fragments,
                "voice_sentences": sentence_entries,
                "voice_error": exc.code,
            }
        )
        if persist:
            try:
                await upsert_voice_state(get_database(), conversation_id=conversation_id, message_id=message_id, state=failed)
            except Exception as save_exc:
                logger.warning("[VoiceMsg] failed state save skipped mid=%s: %s", message_id[:10], save_exc)
        if persist and push_update:
            await _push_message_updated(
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
                message_id=message_id,
                patch=failed,
            )
        return {"ok": False, "voice_state": failed, "audio_transfer": None, "error": exc.code}


async def save_failed_voice_state(
    *,
    conversation_id: str,
    message_id: str,
    voice_id: str,
    tts_text: str,
    text_fragments: list[str],
    voice_error: str,
    voice_sentences: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    failed = normalize_voice_state(
        {
            "voice_status": "failed",
            "voice_id": voice_id,
            "tts_text": tts_text,
            "transcript": tts_text,
            "text_fragments": text_fragments,
            "voice_sentences": voice_sentences or [],
            "voice_error": voice_error,
        }
    )
    await upsert_voice_state(get_database(), conversation_id=conversation_id, message_id=message_id, state=failed)
    return failed


def _voice_sync_timeout_seconds() -> float:
    raw = os.getenv("PONYCHAT_CHAT_VOICE_SYNC_TIMEOUT_SECONDS") or "180"
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return 180.0


async def prepare_voice_generation_for_messages(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    assistant_meta: list[dict[str, Any]],
    assistant_units: list[dict[str, Any]],
    planner_result: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Synchronously prepare voice payloads for a normal reply.

    When the director selects voice, the client should receive the final voice
    bubble directly. If TTS is too slow, we fail the voice state and the caller
    sends the original text as fallback without any later replacement push.
    """
    if not username or not character_id or not conversation_id:
        return {}
    if not planner_voice_reply_enabled(planner_result):
        logger.debug("[VoiceMsg] director selected text reply; skip sync voice")
        return {}
    if not chat_voice_service_enabled():
        logger.info("[VoiceMsg] chat voice disabled; send text fallback without TTS")
        return {}
    config = _character_voice_config(username, character_id)
    if not config["enabled"]:
        logger.debug("[VoiceMsg] director selected voice but character voice disabled")
        return {}
    if not is_voice_lab_available():
        logger.debug("[VoiceMsg] director selected voice but voice lab unavailable")
        return {}

    eligible: list[dict[str, Any]] = []
    text_units = [u for u in assistant_units if isinstance(u, dict) and u.get("type") == "text"]
    for idx, unit in enumerate(text_units):
        meta = assistant_meta[idx] if idx < len(assistant_meta) else {}
        message_id = str(meta.get("message_id") or "").strip()
        content = str(unit.get("content") or "").strip()
        if not message_id or not content:
            continue
        sentence_entries = normalize_voice_sentence_entries(unit.get("voice_sentences"))
        tts_text, fragments = split_voice_reply_text(content)
        if sentence_entries:
            tts_text = join_voice_sentence_texts(sentence_entries)
        if not tts_text:
            continue
        eligible.append(
            {
                "message_id": message_id,
                "content": content,
                "tts_text": tts_text,
                "fragments": fragments,
                "voice_sentences": sentence_entries,
            }
        )
    if not eligible:
        return {}

    reply_language = _reply_language_from_planner(planner_result)
    timeout = _voice_sync_timeout_seconds() if timeout_seconds is None else max(1.0, float(timeout_seconds))
    tasks: dict[str, asyncio.Task] = {}
    by_mid = {item["message_id"]: item for item in eligible}
    for item in eligible:
        mid = item["message_id"]
        tasks[mid] = asyncio.create_task(
            synthesize_message_voice(
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
                message_id=mid,
                content=item["content"],
                voice_id=config["voice_id"],
                instruct=config.get("instruct") or "",
                voice_sentences=item.get("voice_sentences") or [],
                reply_language=reply_language,
                push_update=False,
            )
        )

    started = time.time()
    done, pending = await asyncio.wait(tasks.values(), timeout=timeout)
    results: dict[str, dict[str, Any]] = {}
    for task in done:
        mid = next((key for key, value in tasks.items() if value is task), "")
        try:
            result = task.result()
        except asyncio.CancelledError:
            continue
        except Exception as exc:
            logger.warning("[VoiceMsg] sync synth failed mid=%s: %s", mid[:10], exc)
            item = by_mid.get(mid)
            if item:
                await save_failed_voice_state(
                    conversation_id=conversation_id,
                    message_id=mid,
                    voice_id=config["voice_id"],
                    tts_text=item["tts_text"],
                    text_fragments=item["fragments"],
                    voice_sentences=item.get("voice_sentences") or [],
                    voice_error="voice_sync_error",
                )
            continue
        if result.get("ok") and result.get("voice_state") and result.get("audio_transfer"):
            results[mid] = result

    if pending:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for mid, task in tasks.items():
            if task in pending:
                item = by_mid.get(mid)
                if item:
                    await save_failed_voice_state(
                        conversation_id=conversation_id,
                        message_id=mid,
                        voice_id=config["voice_id"],
                        tts_text=item["tts_text"],
                        text_fragments=item["fragments"],
                        voice_sentences=item.get("voice_sentences") or [],
                        voice_error="voice_timeout",
                    )
        logger.warning(
            "[VoiceMsg] sync voice timeout conv=%s ready=%s/%s elapsed=%.1fs",
            conversation_id[:12],
            len(results),
            len(eligible),
            time.time() - started,
        )
    else:
        logger.debug(
            "[VoiceMsg] sync voice ready conv=%s ready=%s/%s elapsed=%.1fs",
            conversation_id[:12],
            len(results),
            len(eligible),
            time.time() - started,
        )
    return results


async def prepare_voice_generation_for_message(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    message_id: str,
    content: str,
    voice_sentences: list[dict[str, Any]] | None = None,
    planner_result: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Synchronously prepare voice payload for one assistant message."""
    if not username or not character_id or not conversation_id or not message_id:
        return {}
    if not planner_voice_reply_enabled(planner_result):
        return {}
    if not chat_voice_service_enabled():
        return {}
    config = _character_voice_config(username, character_id)
    if not config["enabled"] or not is_voice_lab_available():
        return {}
    text = str(content or "").strip()
    if not text:
        return {}
    sentence_entries = normalize_voice_sentence_entries(voice_sentences)
    tts_text, fragments = split_voice_reply_text(text)
    if sentence_entries:
        tts_text = join_voice_sentence_texts(sentence_entries)
    if not tts_text:
        return {}

    reply_language = _reply_language_from_planner(planner_result)
    timeout = _voice_sync_timeout_seconds() if timeout_seconds is None else max(1.0, float(timeout_seconds))
    task = asyncio.create_task(
        synthesize_message_voice(
            username=username,
            character_id=character_id,
            conversation_id=conversation_id,
            message_id=message_id,
            content=text,
            voice_id=config["voice_id"],
            instruct=config.get("instruct") or "",
            voice_sentences=sentence_entries,
            reply_language=reply_language,
            push_update=False,
        )
    )
    try:
        result = await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await save_failed_voice_state(
            conversation_id=conversation_id,
            message_id=message_id,
            voice_id=config["voice_id"],
            tts_text=tts_text,
            text_fragments=fragments,
            voice_sentences=sentence_entries,
            voice_error="voice_timeout",
        )
        logger.warning("[VoiceMsg] single sync voice timeout mid=%s", message_id[:10])
        return {}
    except Exception as exc:
        await save_failed_voice_state(
            conversation_id=conversation_id,
            message_id=message_id,
            voice_id=config["voice_id"],
            tts_text=tts_text,
            text_fragments=fragments,
            voice_sentences=sentence_entries,
            voice_error="voice_sync_error",
        )
        logger.warning("[VoiceMsg] single sync synth failed mid=%s: %s", message_id[:10], exc)
        return {}
    if result.get("ok") and result.get("voice_state") and result.get("audio_transfer"):
        return result
    return {}


async def schedule_voice_generation_for_messages(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    assistant_meta: list[dict[str, Any]],
    assistant_units: list[dict[str, Any]],
    planner_result: dict[str, Any] | None = None,
) -> None:
    if not username or not character_id or not conversation_id:
        return
    if not planner_voice_reply_enabled(planner_result):
        logger.debug("[VoiceMsg] director selected text reply; skip voice schedule")
        return
    if not chat_voice_service_enabled():
        logger.debug("[VoiceMsg] chat voice disabled; skip voice schedule")
        return
    config = _character_voice_config(username, character_id)
    if not config["enabled"]:
        logger.debug("[VoiceMsg] director selected voice but character voice disabled")
        return
    if not is_voice_lab_available():
        logger.debug("[VoiceMsg] director selected voice but voice lab unavailable")
        return
    reply_language = _reply_language_from_planner(planner_result)
    text_units = [u for u in assistant_units if isinstance(u, dict) and u.get("type") == "text"]
    for idx, unit in enumerate(text_units):
        meta = assistant_meta[idx] if idx < len(assistant_meta) else {}
        message_id = str(meta.get("message_id") or "").strip()
        content = str(unit.get("content") or "").strip()
        if not message_id or not content:
            continue
        sentence_entries = normalize_voice_sentence_entries(unit.get("voice_sentences"))
        tts_text, fragments = split_voice_reply_text(content)
        if sentence_entries:
            tts_text = join_voice_sentence_texts(sentence_entries)
        if not tts_text:
            continue
        try:
            await save_pending_voice_state(
                conversation_id=conversation_id,
                message_id=message_id,
                voice_id=config["voice_id"],
                tts_text=tts_text,
                text_fragments=fragments,
                voice_sentences=sentence_entries,
            )
        except Exception as exc:
            logger.warning("[VoiceMsg] pending save failed mid=%s: %s", message_id[:10], exc)
            continue
        asyncio.create_task(
            synthesize_message_voice(
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
                message_id=message_id,
                content=content,
                voice_id=config["voice_id"],
                instruct=config.get("instruct") or "",
                voice_sentences=sentence_entries,
                reply_language=reply_language,
                push_update=True,
            )
        )


async def _push_message_updated(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    message_id: str,
    patch: dict[str, Any],
) -> None:
    try:
        await manager.broadcast_to_user(
            username,
            {
                "type": "message_updated",
                "character_id": character_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "updated_at_ms": int(time.time() * 1000),
                "patch": patch,
            },
        )
    except Exception as exc:
        logger.debug("[VoiceMsg] WS message_updated skipped: %s", exc)


async def recover_pending_voice_messages(
    *,
    limit: int = 6,
    min_age_seconds: float = 12.0,
    max_age_seconds: float = 3600.0,
) -> int:
    """Resume persisted pending voice messages after restart or task loss."""
    import aiosqlite

    db = get_database()
    await db.init()
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - int(max(1.0, min_age_seconds) * 1000)
    floor_ms = now_ms - int(max(max_age_seconds, min_age_seconds + 1.0) * 1000)
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute(f"PRAGMA busy_timeout = {_voice_db_busy_timeout_ms()}")
        async with conn.execute(
            """
            SELECT mvs.conversation_id,
                   mvs.message_id,
                   mvs.voice_id,
                   mvs.tts_text,
                   mvs.transcript,
                   mvs.voice_sentences_json,
                   m.content AS message_content,
                   c.character_id,
                   u.username
              FROM message_voice_states mvs
              JOIN messages m
                ON m.conversation_id = mvs.conversation_id
               AND m.message_id = mvs.message_id
              JOIN conversations c
                ON c.id = mvs.conversation_id
              JOIN users u
                ON u.id = c.user_id
             WHERE mvs.voice_status = 'pending'
               AND mvs.updated_at <= ?
               AND mvs.updated_at >= ?
               AND m.role = 'assistant'
               AND m.deleted_at IS NULL
               AND COALESCE(m.is_hidden, 0) = 0
             ORDER BY mvs.updated_at ASC
             LIMIT ?
            """,
            (cutoff_ms, floor_ms, max(1, int(limit))),
        ) as cur:
            rows = [dict(row) for row in await cur.fetchall()]

    recovered = 0
    for row in rows:
        conv_id = str(row.get("conversation_id") or "").strip()
        message_id = str(row.get("message_id") or "").strip()
        if not conv_id or not message_id or (conv_id, message_id) in _ACTIVE_VOICE_SYNTH_KEYS:
            continue
        sentence_entries: list[dict[str, Any]] = []
        try:
            parsed = json.loads(row.get("voice_sentences_json") or "[]")
            if isinstance(parsed, list):
                sentence_entries = [item for item in parsed if isinstance(item, dict)]
        except Exception:
            sentence_entries = []
        content = str(row.get("tts_text") or row.get("transcript") or row.get("message_content") or "").strip()
        if not content and sentence_entries:
            content = join_voice_sentence_texts(normalize_voice_sentence_entries(sentence_entries))
        if not content:
            continue
        try:
            result = await synthesize_message_voice(
                username=str(row.get("username") or ""),
                character_id=str(row.get("character_id") or ""),
                conversation_id=conv_id,
                message_id=message_id,
                content=content,
                voice_id=str(row.get("voice_id") or ""),
                voice_sentences=sentence_entries,
                push_update=True,
                persist=True,
            )
            if result.get("ok"):
                recovered += 1
                logger.info("[VoiceMsg] recovered pending voice conv=%s mid=%s", conv_id[:12], message_id[:10])
        except Exception as exc:
            logger.warning("[VoiceMsg] recover pending failed conv=%s mid=%s: %s", conv_id[:12], message_id[:10], exc)
    return recovered


async def pending_voice_recovery_loop() -> None:
    await asyncio.sleep(float(os.getenv("PONYCHAT_VOICE_RECOVERY_START_DELAY") or "8"))
    logger.info("[VoiceMsg] pending voice recovery loop started")
    while True:
        try:
            recovered = await recover_pending_voice_messages()
            if recovered:
                logger.info("[VoiceMsg] recovered %s pending voice message(s)", recovered)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[VoiceMsg] pending voice recovery loop failed: %s", exc)
        await asyncio.sleep(float(os.getenv("PONYCHAT_VOICE_RECOVERY_INTERVAL") or "30"))
