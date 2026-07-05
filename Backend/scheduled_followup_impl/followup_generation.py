

async def _run_step4_next_turn_prep_decision(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    source_message_id: str,
    user_message: str,
    assistant_message: str,
    recent_messages: list[dict[str, Any]],
    planner: dict[str, Any],
    character_profile: str,
    is_new_contact_opening: bool,
    chain_id: str = "",
    chain_count: int = 0,
) -> Optional[str]:
    settings = await load_proactive_settings(username)
    if not settings.enabled:
        logger.info("[ScheduledFollowup] skip Step 4 active task: proactive messages disabled username=%s", username)
        return None
    if await _is_consecutive_proactive_limit_reached(conversation_id):
        logger.info(
            "[ScheduledFollowup] skip Step 4 active task: consecutive proactive limit reached conv=%s",
            conversation_id[:12],
        )
        return None
    if _is_user_conversation_end(user_message):
        logger.info("[ScheduledFollowup] skip Step 4 active task: user ended conversation")
        return None
    if not str(assistant_message or "").strip():
        return None

    cfg = model_manager.get_model_for_task("chat_router") or model_manager.get_active_model()
    if not cfg or not cfg.get("api_key"):
        return None
    model_name = str(cfg.get("model_name") or cfg.get("id") or "deepseek-v4-flash")
    reasoning_policy = resolve_software_reasoning_policy(
        "normal_planner",
        model_name=model_name,
        mode="normal",
        active_model=cfg,
        endpoint=str(cfg.get("endpoint") or ""),
        requested_enabled=False,
        requested_effort="minimal",
    )
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM},
            {
                "role": "user",
                "content": _build_step4_next_turn_prep_decision_blob(
                    user_message=user_message,
                    assistant_message=assistant_message,
                    recent_messages=recent_messages,
                    planner=planner,
                    character_profile=character_profile,
                    is_new_contact_opening=is_new_contact_opening,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "normal_planner")
    res = await call_llm_payload(
        payload,
        cfg,
        task="classify",
        timeout=llm_task_float("normal_planner", "timeout_seconds", 45.0) or 45.0,
        reasoning_policy=reasoning_policy,
        chat_debug_request={
            "username": username,
            "character_id": character_id,
            "mode": "normal",
            "model_name": model_name,
            "stage": "NORMAL_STEP_4_ACTIVE_TASK_DECISION_REQUEST",
            "params": {
                "task_semantics": "active_task",
                "source_message_id": source_message_id,
                "conversation_id": conversation_id,
            },
        },
        record_usage="main",
        usage_meter_username=username,
        charge_membership_chat_quota=True,
    )
    await asyncio.sleep(0)
    data = _loads_json_object_from_text(res.text or "")
    plan = coerce_scheduled_followup(
        data.get("scheduled_followup") if isinstance(data, dict) else None,
        is_new_contact_opening=is_new_contact_opening,
    )
    plan = _apply_step4_subject_integrity_guard(
        plan,
        user_message=user_message,
        assistant_message=assistant_message,
    )
    if not plan.get("enabled"):
        logger.info("[ScheduledFollowup] Step 4 active task disabled conv=%s", conversation_id[:12])
        return None
    if _is_early_morning_time_mismatch(str(plan.get("seed") or "")):
        logger.info("[ScheduledFollowup] skip Step 4 active task: morning/daytime seed during early hours")
        return None
    return await _schedule_active_followup_plan(
        username=username,
        character_id=character_id,
        conversation_id=conversation_id,
        source_message_id=source_message_id,
        plan=plan,
        planner={
            "task_semantics": "active_task",
            "step4_next_turn_prep_decision": data,
            "step1_intent": _step4_next_turn_planner_excerpt(planner),
        },
        assistant_text=assistant_message,
        latest_user_text=user_message,
        chain_id=chain_id,
        chain_count=chain_count,
        settings=settings,
    )


async def cancel_pending_for_user_message(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str],
    *,
    reason: str = "user_replied",
) -> int:
    if not username or not character_id or not conversation_id:
        return 0
    _cancel_pending_step4_followup_generation(
        username,
        character_id,
        conversation_id,
        reason=reason,
    )
    db = get_database()
    await db.init()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await _configure_noncritical_conn(conn)
            cur = await conn.execute(
                """
                UPDATE scheduled_followups
                   SET status='cancelled',
                       cancel_reason=?,
                       updated_at_ms=?
                 WHERE username=?
                   AND character_id=?
                   AND conversation_id=?
                   AND status IN ('pending', 'processing')
                   AND cancel_if_user_replies=1
                """,
                (reason, _now_ms(), username, character_id, conversation_id),
            )
            await conn.commit()
            return int(cur.rowcount or 0)
    except Exception as exc:
        if _is_sqlite_locked(exc):
            logger.debug("[ScheduledFollowup] cancel pending skipped: database is locked")
        else:
            logger.warning("[ScheduledFollowup] cancel pending failed: %s", exc)
        return 0


async def schedule_from_planner(
    request: ChatRequest,
    assistant_message_ids: Optional[list[str]],
    assistant_text: str,
) -> Optional[str]:
    if (request.mode or "normal") != "normal" or request.is_summary_request:
        return None
    username = (request.username or "").strip()
    character_id = (request.character_id or "").strip()
    conversation_id = (request.conversation_id or "").strip()
    if not username or not character_id or not conversation_id:
        return None
    settings = await load_proactive_settings(username)
    if not settings.enabled:
        logger.info("[ScheduledFollowup] skip passive task: proactive messages disabled username=%s", username)
        return None
    planner = getattr(request, "_normal_planner_result", None) or {}
    agreed_task = coerce_user_agreed_task(planner.get("user_agreed_task"))
    if not agreed_task.get("enabled"):
        return None
    source_message_id = ""
    if assistant_message_ids:
        source_message_id = str(assistant_message_ids[-1] or "").strip()
    if not source_message_id:
        return None
    return await _create_proactive_task_from_agreed(
        username=username,
        character_id=character_id,
        conversation_id=conversation_id,
        source_message_id=source_message_id,
        agreed_task=agreed_task,
        planner=planner,
    )


async def _source_has_user_reply_after_message(
    conn: aiosqlite.Connection,
    conversation_id: str,
    source_message_id: str,
) -> bool:
    async with conn.execute(
        """
        SELECT sequence_number, timestamp
          FROM messages
         WHERE conversation_id=?
           AND message_id=?
           AND role='assistant'
           AND deleted_at IS NULL
           AND COALESCE(is_hidden, 0)=0
         LIMIT 1
        """,
        (conversation_id, source_message_id),
    ) as cur:
        src = await cur.fetchone()
    if not src:
        return True
    src_seq = int(src[0] or 0)
    src_ts = int(src[1] or 0)
    async with conn.execute(
        """
        SELECT 1
          FROM messages
         WHERE conversation_id=?
           AND role='user'
           AND deleted_at IS NULL
           AND COALESCE(is_hidden, 0)=0
           AND (
                COALESCE(sequence_number, 0) > ?
                OR (COALESCE(sequence_number, 0)=? AND COALESCE(timestamp, 0) > ?)
           )
         LIMIT 1
        """,
        (conversation_id, src_seq, src_seq, src_ts),
    ) as cur:
        return bool(await cur.fetchone())


async def _schedule_active_followup_plan(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    source_message_id: str,
    plan: dict[str, Any],
    planner: dict[str, Any],
    assistant_text: str,
    latest_user_text: str = "",
    chain_id: str = "",
    chain_count: int = 0,
    settings: Any = None,
) -> Optional[str]:
    if not plan.get("enabled"):
        return None
    plan = _apply_step4_subject_integrity_guard(
        plan,
        user_message=latest_user_text,
        assistant_message=assistant_text,
    )
    if _is_user_conversation_end(latest_user_text):
        logger.info("[ScheduledFollowup] skip schedule: user ended conversation")
        return None
    if _is_early_morning_time_mismatch(str(plan.get("seed") or "")):
        logger.info("[ScheduledFollowup] skip schedule: morning/daytime seed during early hours")
        return None
    settings = settings or await load_proactive_settings(username)
    if not settings.enabled:
        logger.info("[ScheduledFollowup] skip active task: proactive messages disabled username=%s", username)
        return None
    db = get_database()
    await db.init()
    delay_seconds = max(
        MIN_DELAY_SECONDS,
        min(MAX_DELAY_SECONDS, apply_frequency_to_delay_seconds(int(plan["target_delay_seconds"]), settings.frequency)),
    )
    expires_seconds = max(
        delay_seconds,
        min(MAX_EXPIRES_SECONDS, apply_frequency_to_delay_seconds(int(plan["expires_seconds"]), settings.frequency)),
    )
    plan = {
        **plan,
        "target_delay_seconds": delay_seconds,
        "expires_seconds": expires_seconds,
        "task_semantics": "active_task",
    }
    now_ms = _now_ms()
    due_at = now_ms + delay_seconds * 1000
    expires_at = now_ms + expires_seconds * 1000
    followup_id = f"sf_{uuid.uuid4().hex}"
    chain_id = str(chain_id or "").strip() or followup_id
    chain_count = int(chain_count or 0)

    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await _configure_noncritical_conn(conn)
            if await _source_has_user_reply_after_message(conn, conversation_id, source_message_id):
                logger.info(
                    "[ScheduledFollowup] skip Step 4 active task: user replied before schedule conv=%s",
                    conversation_id[:12],
                )
                return None
            limit = await proactive_reply_limit_reached(conn, conversation_id)
            if limit.get("reached"):
                logger.info(
                    "[ScheduledFollowup] skip schedule: consecutive proactive limit reached conv=%s count=%s limit=%s",
                    conversation_id[:12],
                    limit.get("count"),
                    limit.get("limit"),
                )
                return None
            await _cancel_pending_in_conn(
                conn,
                username,
                character_id,
                conversation_id,
                reason="replaced_by_new_assistant_reply",
            )
            await conn.execute(
                """
                INSERT INTO scheduled_followups (
                    id, username, character_id, conversation_id, source_message_id,
                    status, due_at_ms, expires_at_ms, cancel_if_user_replies,
                    allow_reschedule_after_send, seed, reason, pressure_level,
                    chain_id, chain_count, planner_json, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    followup_id,
                    username,
                    character_id,
                    conversation_id,
                    source_message_id,
                    due_at,
                    expires_at,
                    1 if plan.get("cancel_if_user_replies") else 0,
                    1 if plan.get("allow_reschedule_after_send") else 0,
                    str(plan.get("seed") or ""),
                    str(plan.get("reason") or ""),
                    str(plan.get("pressure_level") or "low"),
                    chain_id,
                    chain_count,
                    json.dumps({**planner, "scheduled_followup": plan}, ensure_ascii=False),
                    now_ms,
                    now_ms,
                ),
            )
            await conn.commit()
        logger.info(
            "[ScheduledFollowup] scheduled id=%s conv=%s delay=%ss seed=%s",
            followup_id,
            conversation_id[:12],
            delay_seconds,
            str(plan.get("seed") or "")[:80],
        )
        try:
            from .proactive_tasks import create_layered_auto_tasks

            await create_layered_auto_tasks(
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                seed=str(plan.get("seed") or assistant_text or ""),
                reason=str(plan.get("reason") or ""),
            )
        except Exception as exc:
            logger.warning("[ProactiveTasks] create layered tasks from planner failed: %s", exc)
        return followup_id
    except Exception as exc:
        if _is_sqlite_locked(exc):
            logger.debug("[ScheduledFollowup] schedule skipped: database is locked")
        else:
            logger.warning("[ScheduledFollowup] schedule failed: %s", exc)
        return None


async def scheduled_followup_loop() -> None:
    logger.info("[ScheduledFollowup] scheduler started")
    recovered = await recover_interrupted_processing_followups()
    if recovered:
        logger.info("[ScheduledFollowup] recovered %s interrupted processing task(s)", recovered)
    while not is_shutdown_requested():
        try:
            await process_due_followups()
            if is_shutdown_requested():
                break
            try:
                from .proactive_tasks import process_due_proactive_tasks

                await process_due_proactive_tasks()
            except Exception as exc:
                if _is_sqlite_locked(exc):
                    logger.debug("[ProactiveTasks] loop tick skipped: database is locked")
                else:
                    logger.warning("[ProactiveTasks] loop tick failed: %s", exc)
            try:
                from .long_proactive import process_long_proactive_tick

                await process_long_proactive_tick()
            except Exception as exc:
                if _is_sqlite_locked(exc):
                    logger.debug("[LongProactive] loop tick skipped: database is locked")
                else:
                    logger.warning("[LongProactive] loop tick failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_sqlite_locked(exc):
                logger.debug("[ScheduledFollowup] loop tick skipped: database is locked")
            else:
                logger.warning("[ScheduledFollowup] loop tick failed: %s", exc)
        await asyncio.sleep(LOOP_INTERVAL_SECONDS)
    logger.info("[ScheduledFollowup] scheduler stopped for shutdown")


async def recover_interrupted_processing_followups() -> int:
    db = get_database()
    await db.init()
    now = _now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await _configure_noncritical_conn(conn)
        cur = await conn.execute(
            """
            UPDATE scheduled_followups
               SET status='pending',
                   cancel_reason=NULL,
                   updated_at_ms=?,
                   due_at_ms=CASE WHEN due_at_ms > ? THEN due_at_ms ELSE ? END
             WHERE status='processing'
               AND sent_message_id IS NULL
            """,
            (now, now, now + 5000),
        )
        await conn.commit()
        return int(cur.rowcount or 0)


async def process_due_followups() -> int:
    db = get_database()
    await db.init()
    now = _now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await _configure_noncritical_conn(conn)
        await conn.execute(
            """
            UPDATE scheduled_followups
               SET status='expired', cancel_reason='expired', updated_at_ms=?
             WHERE status='pending' AND expires_at_ms > 0 AND expires_at_ms < ?
            """,
            (now, now),
        )
        await conn.commit()
        async with conn.execute(
            """
            SELECT *
              FROM scheduled_followups
             WHERE status='pending' AND due_at_ms <= ?
             ORDER BY due_at_ms ASC
             LIMIT ?
            """,
            (now, MAX_DUE_BATCH),
        ) as cur:
            rows = await cur.fetchall()

    processed = 0
    for row in rows:
        if is_shutdown_requested():
            logger.info("[ScheduledFollowup] shutdown requested; due tasks left pending")
            break
        ok = await _process_one_due(dict(row))
        if ok:
            processed += 1
    return processed


async def _process_one_due(task: dict[str, Any]) -> bool:
    task_id = str(task.get("id") or "")
    username = str(task.get("username") or "")
    character_id = str(task.get("character_id") or "")
    conversation_id = str(task.get("conversation_id") or "")
    if not task_id or not username or not character_id or not conversation_id:
        return False

    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await _configure_noncritical_conn(conn)
        cur = await conn.execute(
            """
            UPDATE scheduled_followups
               SET status='processing', updated_at_ms=?
             WHERE id=? AND status='pending'
            """,
            (_now_ms(), task_id),
        )
        await conn.commit()
        if int(cur.rowcount or 0) <= 0:
            return False

    async with galgame_locker.acquire(username, character_id):
        validation = await _validate_task_still_sendable(task)
        if not validation.get("ok"):
            await _finish_task(task_id, "cancelled", cancel_reason=validation.get("reason") or "not_sendable")
            return True

        generation_task = asyncio.create_task(
            _generate_followup_via_normal_pipeline(task, validation.get("recent_messages") or [])
        )
        _pending_step4_followup_generation_tasks[task_id] = (
            username,
            character_id,
            conversation_id,
            generation_task,
        )
        try:
            generated = await generation_task
        except asyncio.CancelledError:
            if is_shutdown_requested():
                generation_task.cancel()
                await _requeue_processing_followup(task_id)
                logger.info(
                    "[ScheduledFollowup] shutdown requeued processing task=%s conv=%s",
                    task_id,
                    conversation_id[:12],
                )
                return True
            logger.info(
                "[ScheduledFollowup] Step 4 follow-up generation cancelled task=%s conv=%s",
                task_id,
                conversation_id[:12],
            )
            await _finish_task(task_id, "cancelled", cancel_reason="user_replied_during_generation")
            return True
        finally:
            current = _pending_step4_followup_generation_tasks.get(task_id)
            if current and current[3] is generation_task:
                _pending_step4_followup_generation_tasks.pop(task_id, None)
        if not await _is_task_processing(task_id):
            logger.info("[ScheduledFollowup] skip generated message: task no longer processing id=%s", task_id)
            return True
        if not generated.get("should_send"):
            await _finish_task(task_id, "cancelled", cancel_reason=generated.get("reason") or "director_cancelled")
            return True

        if generated.get("persisted_by_normal_core"):
            if is_shutdown_requested():
                await _requeue_processing_followup(task_id)
                logger.info("[ScheduledFollowup] shutdown before normal-core audit; requeued task=%s", task_id)
                return True
            content = str(generated.get("message") or "").strip()
            message_ids = [
                str(mid or "").strip()
                for mid in (generated.get("assistant_message_ids") or [])
                if str(mid or "").strip()
            ]
            if not content or not message_ids:
                await _finish_task(task_id, "failed", cancel_reason="normal_core_missing_message_id")
                return True
            segments = [p.strip() for p in re.split(r"\n+", content) if p.strip()]
            if not segments:
                segments = [content]
            proactive_ids = []
            for idx, message_id in enumerate(message_ids):
                segment = segments[idx] if idx < len(segments) else segments[-1]
                proactive_ids.append(
                    await _record_proactive_audit_only(
                        task,
                        segment,
                        message_id,
                    )
                )
            await _finish_task(task_id, "sent", sent_message_id=message_ids[-1])
            logger.info(
                "[ScheduledFollowup] sent via normal core task=%s proactive=%s conv=%s messages=%s",
                task_id,
                proactive_ids,
                conversation_id[:12],
                message_ids,
            )
            return True

        active_model = generated.get("active_model") if isinstance(generated.get("active_model"), dict) else {}
        content = clean_generated_proactive_content(str(generated.get("message") or "").strip(), active_model)
        if not content:
            await _finish_task(task_id, "cancelled", cancel_reason="empty_message")
            return True
        content_check = _validate_generated_followup_content(
            content,
            validation.get("recent_messages") or [],
            source_message_id=str(task.get("source_message_id") or ""),
        )
        if not content_check.get("ok"):
            await _finish_task(task_id, "cancelled", cancel_reason=content_check.get("reason") or "low_value_followup")
            return True
        if _is_early_morning_time_mismatch(content):
            await _finish_task(task_id, "cancelled", cancel_reason="early_hours_morning_content")
            return True

        recheck = await _validate_task_still_sendable(task)
        if not recheck.get("ok"):
            await _finish_task(task_id, "cancelled", cancel_reason=recheck.get("reason") or "not_sendable_after_generation")
            return True
        if not await _is_task_processing(task_id):
            logger.info("[ScheduledFollowup] skip append: task no longer processing id=%s", task_id)
            return True

        try:
            from .chat_modules.message_delivery_order import wait_for_conversation_delivery_slot

            can_deliver = await wait_for_conversation_delivery_slot(
                task.get("username"),
                task.get("character_id"),
                task.get("conversation_id"),
                reason="scheduled_followup",
            )
        except Exception as exc:
            logger.debug("[ScheduledFollowup] delivery wait skipped: %s", exc)
            can_deliver = True
        if not can_deliver:
            await _finish_task(task_id, "cancelled", cancel_reason="delivery_order_timeout")
            return True

        recheck = await _validate_task_still_sendable(task)
        if not recheck.get("ok"):
            await _finish_task(task_id, "cancelled", cancel_reason=recheck.get("reason") or "not_sendable_after_delivery_wait")
            return True
        if is_shutdown_requested():
            await _requeue_processing_followup(task_id)
            logger.info("[ScheduledFollowup] shutdown before append; requeued task=%s", task_id)
            return True

        should_follow_voice = _latest_assistant_was_voice(validation.get("recent_messages") or [])
        message_parts = await _append_assistant_message(task, content)
        if not message_parts:
            if not await _is_task_processing(task_id):
                logger.info("[ScheduledFollowup] append skipped after cancellation id=%s", task_id)
                return True
            await _finish_task(task_id, "failed", cancel_reason="persist_failed")
            return True

        voice_results_by_message_id: dict[str, dict[str, Any]] = {}
        if should_follow_voice:
            voice_results_by_message_id = await _prepare_voice_for_scheduled_parts(
                task,
                message_parts,
                generated.get("request") if isinstance(generated.get("request"), ChatRequest) else None,
            )

        proactive_ids = []
        for idx, (message_id, segment) in enumerate(message_parts):
            if idx > 0:
                await asyncio.sleep(
                    _scheduled_message_part_delay_seconds(
                        segment,
                        current_voice_result=voice_results_by_message_id.get(message_id),
                    )
                )
            proactive_ids.append(
                await _record_proactive_and_push_chat_complete(
                    task,
                    segment,
                    message_id,
                    voice_result=voice_results_by_message_id.get(message_id),
                )
            )
        last_message_id = message_parts[-1][0]
        pipeline_request = generated.get("request")
        if isinstance(pipeline_request, ChatRequest):
            await _after_scheduled_message_saved(task, pipeline_request, content, last_message_id)
        logger.info(
            "[ScheduledFollowup] sent task=%s proactive=%s conv=%s messages=%s",
            task_id,
            proactive_ids,
            conversation_id[:12],
            [mid for mid, _segment in message_parts],
        )
        return True


async def _validate_task_still_sendable(task: dict[str, Any]) -> dict[str, Any]:
    db = get_database()
    source_message_id = str(task.get("source_message_id") or "")
    settings = await load_proactive_settings(str(task.get("username") or ""))
    if not settings.enabled:
        return {"ok": False, "reason": "proactive_messages_disabled"}
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT c.is_hidden, u.id AS user_id
              FROM conversations c
              JOIN users u ON u.id = c.user_id
             WHERE u.username=? AND c.character_id=? AND c.id=?
            """,
            (task["username"], task["character_id"], task["conversation_id"]),
        ) as cur:
            conv = await cur.fetchone()
        if not conv:
            return {"ok": False, "reason": "conversation_missing"}
        if int(conv["is_hidden"] or 0) != 0:
            return {"ok": False, "reason": "conversation_hidden"}

        async with conn.execute(
            """
            SELECT sequence_number, timestamp
              FROM messages
             WHERE conversation_id=?
               AND message_id=?
               AND role='assistant'
               AND deleted_at IS NULL
               AND COALESCE(is_hidden, 0)=0
             LIMIT 1
            """,
            (task["conversation_id"], source_message_id),
        ) as cur:
            src = await cur.fetchone()
        if not src:
            return {"ok": False, "reason": "source_message_missing"}
        src_seq = int(src["sequence_number"] or 0)
        src_ts = int(src["timestamp"] or 0)

        if int(task.get("cancel_if_user_replies") or 0) == 1:
            async with conn.execute(
                """
                SELECT 1
                  FROM messages
                 WHERE conversation_id=?
                   AND role='user'
                   AND deleted_at IS NULL
                   AND COALESCE(is_hidden, 0)=0
                   AND (
                        COALESCE(sequence_number, 0) > ?
                        OR (COALESCE(sequence_number, 0)=? AND COALESCE(timestamp, 0) > ?)
                   )
                 LIMIT 1
                """,
                (task["conversation_id"], src_seq, src_seq, src_ts),
            ) as cur:
                user_after = await cur.fetchone()
            if user_after:
                return {"ok": False, "reason": "user_replied_after_source"}

        day_ago = _now_ms() - 24 * 60 * 60 * 1000
        async with conn.execute(
            """
            SELECT COUNT(*)
              FROM messages
             WHERE conversation_id=?
               AND role='assistant'
               AND client_id='scheduled_followup'
               AND deleted_at IS NULL
               AND COALESCE(is_hidden, 0)=0
               AND COALESCE(timestamp, 0)>=?
            """,
            (task["conversation_id"], day_ago),
        ) as cur:
            count_row = await cur.fetchone()
        if int(count_row[0] if count_row else 0) >= MAX_AUTO_MESSAGES_PER_CONVERSATION_PER_DAY:
            return {"ok": False, "reason": "daily_auto_limit"}

        limit = await proactive_reply_limit_reached(conn, task["conversation_id"])
        if limit.get("reached"):
            return {
                "ok": False,
                "reason": str(limit.get("reason") or "consecutive_proactive_limit"),
                "consecutive_proactive_reply_groups": int(limit.get("count") or 0),
                "consecutive_proactive_reply_limit": int(limit.get("limit") or 0),
            }

        async with conn.execute(
            """
            SELECT m.role, m.content, m.timestamp, m.message_id, m.sequence_number,
                   mvs.voice_status, mvs.voice_id, mvs.voice_cache_key
              FROM messages m
              LEFT JOIN message_voice_states mvs
                     ON mvs.conversation_id = m.conversation_id
                    AND mvs.message_id = m.message_id
             WHERE m.conversation_id=?
               AND m.deleted_at IS NULL
               AND COALESCE(m.is_hidden, 0)=0
             ORDER BY COALESCE(m.sequence_number, 0) DESC, COALESCE(m.timestamp, 0) DESC, m.rowid DESC
             LIMIT ?
            """,
            (task["conversation_id"], MAX_RECENT_MESSAGES),
        ) as cur:
            recent = await cur.fetchall()
    messages = [
        {
            "role": r["role"],
            "content": r["content"],
            "timestamp": r["timestamp"],
            "message_id": r["message_id"],
            "sequence_number": r["sequence_number"],
            "voice_state": {
                "voice_status": r["voice_status"],
                "voice_id": r["voice_id"],
                "voice_cache_key": r["voice_cache_key"],
            } if r["voice_status"] else None,
            "voice_status": r["voice_status"],
        }
        for r in reversed(recent)
    ]
    latest_user_text = _latest_user_text(messages)
    seed_text = str(task.get("seed") or "")
    if _is_user_conversation_end(latest_user_text):
        return {"ok": False, "reason": "user_ended_conversation"}
    if _is_early_morning_time_mismatch(seed_text):
        return {"ok": False, "reason": "early_hours_morning_seed"}
    if _is_reminder_task(task):
        meta = _planner_json(task)
        agreed = coerce_user_agreed_task(meta.get("user_agreed_task"))
        window = int(agreed.get("natural_window_seconds") or REMINDER_NATURAL_WINDOW_SECONDS)
        due_at = int(task.get("due_at_ms") or 0)
        if due_at > 0 and _now_ms() - due_at > window * 1000:
            return {"ok": False, "reason": "reminder_natural_window_elapsed"}
    return {"ok": True, "recent_messages": messages}


def _normal_core_json_events(response: Any) -> list[dict[str, Any]]:
    body = getattr(response, "body", b"")
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = str(body or "")
    if not text.strip():
        return []
    data = json.loads(text)
    events = data.get("events") if isinstance(data, dict) else None
    return [event for event in (events or []) if isinstance(event, dict)]


def _parse_normal_core_generation_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    paragraphs: list[str] = []
    assistant_message_ids: list[str] = []
    reason = ""
    save_failed = False
    for event in events or []:
        typ = str(event.get("type") or "").strip()
        if typ == "assistant_paragraph":
            content = str(event.get("content") or "").strip()
            if content:
                paragraphs.append(content)
            mid = str(event.get("id") or event.get("message_id") or "").strip()
            if mid and mid not in assistant_message_ids:
                assistant_message_ids.append(mid)
        elif typ == "save_status":
            if event.get("success") is False:
                save_failed = True
                reason = str(event.get("message") or "normal_core_save_failed").strip()
            for mid in event.get("assistant_message_ids") or []:
                mid = str(mid or "").strip()
                if mid and mid not in assistant_message_ids:
                    assistant_message_ids.append(mid)
        elif typ in {"no_reply", "cancelled"}:
            reason = str(event.get("reason") or typ).strip()
        elif "error" in event:
            reason = str(event.get("error") or "normal_core_error").strip()
    if save_failed:
        return {"message": "", "assistant_message_ids": [], "reason": reason or "normal_core_save_failed"}
    message = "\n".join(paragraphs).strip()
    return {
        "message": message,
        "assistant_message_ids": assistant_message_ids,
        "reason": reason,
    }


async def _generate_followup_via_normal_pipeline(
    task: dict[str, Any],
    recent_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    settings = await load_proactive_settings(str(task.get("username") or ""))
    if not settings.enabled:
        return {"should_send": False, "reason": "proactive_messages_disabled"}
    active_model = model_manager.get_model_for_task("chat") or model_manager.get_active_model()
    if not active_model:
        return {"should_send": False, "reason": "no_model"}
    model_name = str(active_model.get("model_name") or active_model.get("id") or "")
    if not model_name:
        return {"should_send": False, "reason": "no_model_name"}

    trigger_type = _scheduled_trigger_type(task)
    debug_params = _scheduled_proactive_debug_params(
        task,
        pipeline="normal_proactive_core",
    )
    trigger_message_id = f"sf_trigger_{task.get('id') or uuid.uuid4().hex}"
    trigger_text = _join_nonempty_context_parts(
        _normal_proactive_fact_priority_context(trigger_type),
        _build_due_trigger_text(task),
        _scheduled_voice_inertia_prompt(recent_messages),
    )
    request_messages = _recent_rows_to_chat_messages(recent_messages)
    request_messages.append(
        ChatMessage(
            role="user",
            content=trigger_text,
            timestamp=_now_ms(),
            message_id=trigger_message_id,
        )
    )
    request = ChatRequest(
        messages=request_messages,
        username=str(task.get("username") or ""),
        character_id=str(task.get("character_id") or ""),
        conversation_id=str(task.get("conversation_id") or ""),
        mode="normal",
        memory_enabled=settings.memory_enabled,
        crisis_hotline_enabled=False,
        stream=False,
        enable_thinking=False,
    )
    setattr(request, "_scheduled_followup_chain_id", str(task.get("chain_id") or task.get("id") or "").strip())
    setattr(request, "_scheduled_followup_chain_count", int(task.get("chain_count") or 0) + 1)
    setattr(request, "_normal_internal_proactive_trigger", True)
    setattr(request, "_normal_internal_trigger_message_id", trigger_message_id)
    setattr(request, "_normal_internal_proactive_source_message_id", str(task.get("source_message_id") or "").strip())
    setattr(request, "_normal_persist_append_only", True)
    setattr(request, "_normal_skip_persistence_galgame_lock", True)
    setattr(request, "_normal_proactive_debug_params", debug_params)
    setattr(
        request,
        "_normal_allow_proactive_reschedule_after_send",
        bool(int(task.get("allow_reschedule_after_send") or 0)),
    )
    setattr(request, "_normal_internal_proactive_memory_user_message", _scheduled_memory_user_message(task))

    try:
        from .chat_modules.service import handle_chat_request

        response = await handle_chat_request(
            request,
            "scheduled_followup",
            None,
            active_model,
            use_json_protocol=True,
        )
        events = _normal_core_json_events(response)
        parsed = _parse_normal_core_generation_events(events)
        content = parsed.get("message", "")
        return {
            "should_send": bool(content),
            "reason": parsed.get("reason") or ("sent_by_normal_core" if content else "empty_message"),
            "message": content,
            "request": request,
            "active_model": active_model,
            "persisted_by_normal_core": bool(content),
            "assistant_message_ids": parsed.get("assistant_message_ids") or [],
            "events": events,
        }
    except Exception as exc:
        logger.warning("[ScheduledFollowup] normal core generation failed: %s", exc)
        return {"should_send": False, "reason": "generation_failed", "message": "", "active_model": active_model}


async def _run_scheduled_normal_planner(
    request: ChatRequest,
    active_model: dict,
    model_name: str,
    *,
    recent_chat: Optional[list[dict[str, Any]]] = None,
    router_cfg: Optional[dict[str, Any]] = None,
    environment_context: str = "",
    character_prompt_context: str = "",
    debug_role_params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from .chat_modules.normal_planner import (
        NormalVisionContext,
        default_planner_result,
        plan_normal_conversation,
    )

    planner_result = default_planner_result()
    router_cfg = router_cfg if router_cfg is not None else model_manager.get_model_for_task("chat_router")
    if not router_cfg:
        planner_result["memory_use_policy"] = "判别：普通对话。无导演模型配置，沿用最近对话自然续接。"
        planner_result["expression_policy"] = "按普通对话最近上下文自然生成下一条角色消息；默认使用中文。"
        try:
            from .chat_modules.voice_messages import force_text_reply_when_chat_voice_disabled

            planner_result = force_text_reply_when_chat_voice_disabled(planner_result)
        except Exception as exc:
            logger.debug("[ScheduledFollowup] chat voice switch fallback check failed: %s", exc)
        return planner_result

    if recent_chat is None:
        recent_chat = build_chat_router_recent_user_assistant(
            request,
            active_model,
            model_name,
            max_messages=6,
        )
    if not character_prompt_context:
        character_prompt_context = _build_planner_character_prompt_context(
            request.username,
            request.character_id,
        )
    planner_result = await plan_normal_conversation(
        recent_chat,
        router_cfg,
        vision_context=NormalVisionContext(),
        environment_context=environment_context,
        character_prompt_context=character_prompt_context,
        username=request.username,
        character_id=request.character_id,
        prior_stored_count=0,
        last_reply_based_on_image=False,
        debug_mode="normal",
        debug_stage_prefix="NORMAL_PROACTIVE",
        charge_membership_chat_quota=True,
        debug_role_params=debug_role_params,
    )
    try:
        from .chat_modules.voice_messages import force_text_reply_when_chat_voice_disabled

        planner_result = force_text_reply_when_chat_voice_disabled(planner_result)
    except Exception as exc:
        logger.debug("[ScheduledFollowup] chat voice switch check failed: %s", exc)
    return planner_result


async def _after_scheduled_message_saved(
    task: dict[str, Any],
    request: ChatRequest,
    content: str,
    message_id: str,
) -> None:
    username = str(task.get("username") or "")
    character_id = str(task.get("character_id") or "")
    conversation_id = str(task.get("conversation_id") or "")
    if username and character_id:
        try:
            from .memory.consolidator import register_chat_activity

            register_chat_activity(username=username, character_id=character_id)
        except Exception as exc:
            logger.warning("[ScheduledFollowup] register memory consolidator failed: %s", exc)

    if username and character_id and conversation_id and request.memory_enabled is not False:
        try:
            from .chat_modules.context_memory import schedule_context_memory_update

            schedule_context_memory_update(
                username,
                character_id,
                conversation_id,
                user_message=_scheduled_memory_user_message(task),
                assistant_message=content,
                db=get_database(),
                messages_for_bubbles=None,
                entry_at_ms=_now_ms(),
                planner_memory_notes=getattr(request, "_planner_memory_notes", "") or "",
            )
        except Exception as exc:
            logger.warning("[ScheduledFollowup] schedule context memory update failed: %s", exc)

    if bool(int(task.get("allow_reschedule_after_send") or 0)):
        try:
            recent_for_step4_next_turn = [
                {"role": getattr(m, "role", ""), "content": getattr(m, "content", "")}
                for m in (request.messages or [])
                if not getattr(m, "isHidden", False)
            ]
            schedule_step4_next_turn_prep_decision(
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
                source_message_id=message_id,
                user_message=_scheduled_memory_user_message(task),
                assistant_message=content,
                recent_messages=recent_for_step4_next_turn,
                planner=getattr(request, "_normal_planner_result", None) or {},
                character_profile=getattr(request, "_normal_stage2_character_profile", "") or "",
                is_new_contact_opening=False,
                chain_id=str(task.get("chain_id") or task.get("id") or ""),
                chain_count=int(task.get("chain_count") or 0) + 1,
            )
        except Exception as exc:
            logger.warning("[ScheduledFollowup] schedule chained followup from normal planner failed: %s", exc)


def _recent_rows_to_chat_messages(rows: list[dict[str, Any]]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for row in rows or []:
        role = str(row.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        messages.append(
            ChatMessage(
                role=role,
                content=content,
                timestamp=_coerce_int(row.get("timestamp"), 0) or None,
                message_id=str(row.get("message_id") or "").strip() or None,
                sequence_number=_coerce_int(row.get("sequence_number"), 0),
                voice_state=row.get("voice_state") if isinstance(row.get("voice_state"), dict) else None,
                voice_status=str(row.get("voice_status") or "").strip() or None,
            )
        )
    return messages


def _format_local_time(ts_ms: int) -> str:
    if ts_ms <= 0:
        return "未知"
    return datetime.fromtimestamp(ts_ms / 1000, tz=LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _format_agreed_task_time_context(task: dict[str, Any]) -> str:
    meta = _planner_json(task)
    agreed = coerce_user_agreed_task(meta.get("user_agreed_task"))
    if not agreed.get("enabled"):
        return ""
    now = _now_ms()
    due_at = int(task.get("due_at_ms") or 0)
    created_at = int(task.get("created_at_ms") or 0)
    late_seconds = max(0, int((now - due_at) / 1000)) if due_at > 0 else 0
    window = int(agreed.get("natural_window_seconds") or REMINDER_NATURAL_WINDOW_SECONDS)
    return (
        "【用户约定任务时间事实｜系统内部】\n"
        f"任务类型：{agreed.get('task_type')}\n"
        f"约定内容：{agreed.get('summary')}\n"
        f"创建时间：{_format_local_time(created_at)}\n"
        f"目标提醒时间：{_format_local_time(due_at)}\n"
        f"当前时间：{_format_local_time(now)}\n"
        f"自然浮动窗口：约 {window // 60 if window >= 60 else window} {'分钟' if window >= 60 else '秒'}\n"
        f"当前时间状态：{_rough_late_label(late_seconds)}\n"
        "表达要求：角色可以自然地说差不多到了、刚结束一会儿、稍微晚了一点；"
        "不要精确报秒，不要表现得像机器闹钟；但也不要在明显过晚时假装刚刚准点。"
    )


def _strip_task_type_prefix(text: str) -> str:
    return re.sub(r"^\[[^\]]{1,40}\]\s*", "", str(text or "").strip()).strip()


def _normalize_passive_task_summary(text: str) -> str:
    summary = _strip_task_type_prefix(text)
    summary = re.sub(r"^按用户在聊天里约定的定时任务自然提醒[:：]\s*", "", summary)
    replacements = (
        ("提醒我", "提醒用户"),
        ("叫我", "叫用户"),
        ("喊我", "喊用户"),
        ("催我", "催用户"),
        ("让我", "让用户"),
        ("问我", "问用户"),
        ("给我", "给用户"),
        ("帮我", "帮用户"),
    )
    for src, dst in replacements:
        summary = summary.replace(src, dst)
    return summary.strip()


def _format_passive_task_intent_context(task: dict[str, Any]) -> str:
    meta = _planner_json(task)
    agreed = coerce_user_agreed_task(meta.get("user_agreed_task"))
    raw_summary = str(agreed.get("summary") or "").strip() if agreed.get("enabled") else ""
    seed = _strip_task_type_prefix(str(task.get("seed") or ""))
    reason = str(task.get("reason") or "")
    is_passive_task = bool(raw_summary) or reason.startswith("proactive_task:") or str(task.get("id") or "").startswith("pt_")
    if not is_passive_task:
        return ""
    summary = _normalize_passive_task_summary(raw_summary or seed)
    if not summary:
        return ""
    return (
        "【用户约定/手动创建的被动任务｜系统内部】\n"
        f"任务内容：{summary}\n"
        "语义主体：角色只负责开口提醒；任务动作的执行者是用户本人，不是角色。\n"
        "表达要求：把任务里的“我/用户”一律理解为用户本人；"
        "不要把站起来、喝水、起床、休息、复盘、检查账单等动作写成角色自己要去做。"
        "角色可以用自己的口吻陪伴、鼓励或轻轻催促用户完成这件事。"
    )
