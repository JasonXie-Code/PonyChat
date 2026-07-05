

@router.post("/conversation/summarize_context")
async def summarize_context(req: SummarizeContextRequest):
    """
    后端主导的上下文摘要端点。
    调用 LLM 生成摘要，直接写入 DB，返回更新后的 token 用量。
    前端无需管理摘要数据，只需调用此接口并更新显示的字数统计。
    """
    KEEP_RECENT_MESSAGES = CONTEXT_SUMMARY_KEEP_RECENT_MESSAGES

    username = req.username
    character_id = req.character_id
    mode = req.mode
    conversation_id = req.conversation_id
    is_galgame = mode in ("galgame", "galgame_lock")
    is_lock_mode = mode == "galgame_lock"

    # ── 1. 从 DB 加载消息和现有摘要 ──
    try:
        db = get_database()
        await db.init()

        if is_galgame:
            game_type = "galgame_lock" if is_lock_mode else "galgame"
            gal_data = await load_galgame_state_async(username, character_id, game_type=game_type)
        else:
            conv_dao = ConversationsDAO(db)
            conversations = await conv_dao.load_conversations(username, character_id)
            target_conv = None
            if conversation_id:
                target_conv = next((c for c in conversations if c.get("id") == conversation_id), None)
            if not target_conv and conversations:
                target_conv = conversations[0]
            if not target_conv:
                raise HTTPException(status_code=404, detail="Conversation not found")
            all_messages = target_conv.get("messages") or []
            prev_summary = str(target_conv.get("contextSummary") or target_conv.get("summary") or "").strip()
            existing_cutoff_id = target_conv.get("contextSummaryCutoffMessageId")
            conversation_id = target_conv.get("id")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SummarizeCtx] DB 加载失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load messages: {e}")

    # ── Galgame / 锁分：分层记忆折叠（char_memory 转写），不再走 context_summary + 消息摘要 ──
    if is_galgame:
        from ..galgame.memory import KEEP_VERBATIM_AFTER_TRIM, run_forced_tiered_fold_from_state
        from ..utils import save_galgame_state_async

        game_type = "galgame_lock" if is_lock_mode else "galgame"
        cm = gal_data.get("char_memory") if isinstance(gal_data.get("char_memory"), dict) else {}
        entries_list = [e for e in (cm.get("entries") or []) if isinstance(e, dict)]
        if len(entries_list) < KEEP_VERBATIM_AFTER_TRIM + 1:
            return {"skipped": True, "reason": "not_enough_turns"}
        ok_fold = await run_forced_tiered_fold_from_state(
            gal_data,
            is_lock_mode=is_lock_mode,
            username=username,
            character_id=character_id,
            game_type=game_type,
        )
        if not ok_fold:
            return {"skipped": True, "reason": "tiered_fold_failed"}
        save_ok = await save_galgame_state_async(username, character_id, gal_data, game_type=game_type)
        if not save_ok:
            raise HTTPException(status_code=500, detail="Failed to persist tiered memory")
        st = str(gal_data.get("shortTermMemory") or "")
        lt = str(gal_data.get("longTermMemory") or "")
        verb_entries = (gal_data.get("char_memory") or {}).get("entries") or []
        logger.info(
            f"✅ [SummarizeCtx] 分层记忆已落库 | mode={mode} | char={character_id[:8]}... | "
            f"short={len(st)} long={len(lt)} verbatim={len(verb_entries)}"
        )
        return {
            "status": "success",
            "short_term_length": len(st),
            "long_term_length": len(lt),
            "verbatim_turns": len(verb_entries),
        }

    # 总结任务固定使用 for_summarize 专用模型（普通对话）
    active_model = app_config.model_manager.get_model_for_task("summarize")
    if not active_model:
        raise HTTPException(status_code=500, detail="No active model configured")

    # ── 2. 确定摘要范围（排除隐藏消息，保留最近 KEEP_RECENT 条） ──
    visible = [
        m for m in all_messages
        if not (m.get("isHidden") or m.get("is_hidden") if isinstance(m, dict) else False)
    ]

    if req.force:
        # 调试强制模式：跳过消息数量检查；无消息时注入占位故事
        if not visible:
            visible = [{"role": "user", "content": _DEBUG_FORCE_SUMMARIZE_STORY}]
            logger.info("[SummarizeCtx] force=True，无对话内容，注入占位故事")
        to_summarize = visible  # 全部纳入摘要，不保留最近几条
        cutoff_msg = to_summarize[-1]
    else:
        to_summarize_default, frozen_recent_tail = _split_recent_messages(visible, KEEP_RECENT_MESSAGES)
        summarize_end_idx = len(visible) - len(frozen_recent_tail)
        if summarize_end_idx <= 0:
            logger.info(f"[SummarizeCtx] 不满足总结要求，跳过：消息数不足（visible={len(visible)}，需超过 {KEEP_RECENT_MESSAGES} 条）")
            return {"skipped": True, "reason": "not_enough_messages"}

        # 增量总结：如果已有摘要，只取上次 cutoff 之后的新消息，避免把已摘要内容重复喂给 LLM。
        # cutoff 位置用 sequence_number > existing_cutoff_seq 判断（最可靠），
        # 回退到 message_id 精确匹配，再回退到 timestamp，都找不到则降级为全量。
        existing_cutoff_seq  = None
        existing_cutoff_ts   = None
        if prev_summary and existing_cutoff_id:
            # 从 visible 列表里找上次 cutoff 消息的位置
            cutoff_idx = None
            for _i, _m in enumerate(visible):
                if isinstance(_m, dict) and _m.get("message_id") == existing_cutoff_id:
                    cutoff_idx = _i
                    existing_cutoff_seq = _m.get("sequence_number")
                    existing_cutoff_ts  = _m.get("timestamp")
                    break
            if cutoff_idx is not None:
                # cutoff 之后、且位于“启动摘要时冻结的最近12条”之前的消息才纳入本轮总结
                new_after_cutoff = visible[cutoff_idx + 1 : summarize_end_idx]
                if new_after_cutoff:
                    to_summarize = new_after_cutoff
                    logger.info(
                        f"[SummarizeCtx] 增量模式：cutoff_seq={existing_cutoff_seq}，"
                        f"新增 {len(to_summarize)} 条（跳过已摘要的前 {cutoff_idx + 1} 条）"
                    )
                else:
                    # cutoff 之后没有足够新消息，无需再次总结
                    logger.info(f"[SummarizeCtx] 不满足总结要求，跳过：上次摘要后无新消息（cutoff_seq={existing_cutoff_seq}）")
                    return {"skipped": True, "reason": "no_new_messages_since_last_summary"}
            else:
                # cutoff 消息在 visible 里找不到（可能已被隐藏），降级全量
                logger.warning(
                    f"[SummarizeCtx] 找不到 cutoff_id={existing_cutoff_id}，降级为全量总结"
                )
                to_summarize = to_summarize_default
        else:
            # 首次总结，无历史摘要，全量处理
            to_summarize = to_summarize_default

        if not to_summarize:
            logger.info("[SummarizeCtx] 不满足总结要求，跳过：无可纳入摘要的消息")
            return {"skipped": True, "reason": "nothing_to_summarize"}
        cutoff_msg = to_summarize[-1]

    cutoff_message_id = (cutoff_msg.get("message_id") if isinstance(cutoff_msg, dict) else None) or None
    cutoff_timestamp = (cutoff_msg.get("timestamp") if isinstance(cutoff_msg, dict) else None) or None
    raw_seq = (cutoff_msg.get("sequence_number") if isinstance(cutoff_msg, dict) else None)
    try:
        cutoff_sequence = int(raw_seq) if raw_seq is not None else None
    except (TypeError, ValueError):
        cutoff_sequence = None

    logger.info(
        f"📝 [SummarizeCtx] mode={mode} char={character_id[:8]}... "
        f"total={len(all_messages)} visible={len(visible)} to_summarize={len(to_summarize)} "
        f"cutoff_id={str(cutoff_message_id or '')[:12] or 'None'}"
    )

    # ── 3. 构建摘要 Prompt ──
    summary_character_profile = ""
    summary_assistant_label = "角色"
    if not is_galgame:
        try:
            from ..chat_modules.character import build_character_profile_prompt_block, load_character_from_db

            _summary_char = load_character_from_db(username, character_id) or {}
            summary_assistant_label = str(_summary_char.get("name") or "").strip() or summary_assistant_label
            summary_character_profile = build_character_profile_prompt_block(_summary_char)
        except Exception as _profile_err:
            logger.debug("[SummarizeCtx] 加载角色档案供摘要参考失败: %s", _profile_err)
    scene_time_hint = _pick_scene_time_hint(all_messages, gal_data if is_galgame else {})
    prompt = _build_summary_prompt(
        to_summarize,
        prev_summary=prev_summary,
        is_galgame_mode=is_galgame,
        is_lock_mode=is_lock_mode,
        scene_time_hint=scene_time_hint,
        character_profile_context=summary_character_profile,
        user_label=USER_MEMORY_PLACEHOLDER,
        assistant_label=summary_assistant_label,
    )

    # ── 4. 调用 LLM（非流式） ──
    model_name = active_model.get("model_name") or active_model.get("id", "")
    reasoning_policy = resolve_software_reasoning_policy(
        "conversation_summary",
        model_name=model_name,
        mode=f"{mode}_summarize",
        active_model=active_model,
        endpoint=active_model.get("endpoint", ""),
    )
    body: Dict[str, Any] = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    apply_llm_task_payload_config(body, "conversation_summary", output_token_field="max_tokens")
    summary_timeout = llm_task_float("conversation_summary", "timeout_seconds", 180.0) or 180.0

    logger.info(
        f"📤 [SummarizeCtx] 发起 LLM 请求 | model={model_name} | "
        f"prompt_chars={len(prompt)} | to_summarize={len(to_summarize)} 条消息"
    )
    _summarize_start = time.monotonic()
    try:
        if not app_config.httpx_client:
            raise HTTPException(status_code=503, detail="HTTP client not ready")
        result = await asyncio.wait_for(
            call_llm_payload(
                body,
                active_model,
                task="summarize",
                httpx_client=app_config.httpx_client,
                timeout=summary_timeout,
                chat_debug_request={
                    "username": username,
                    "character_id": character_id,
                    "mode": f"{mode}_summarize",
                    "model_name": model_name,
                    "stage": "REQUEST",
                },
                record_usage="main",
                usage_meter_username=username,
                reasoning_policy=reasoning_policy,
            ),
            timeout=summary_timeout,
        )
        resp_data = result.raw_response
        if isinstance(resp_data.get("error"), dict):
            err_msg = resp_data["error"].get("message", "LLM error")
            # 内容合规拒绝（content_policy_violation 等）单独记录，与超时区分
            logger.error(f"[SummarizeCtx] LLM 返回错误对象 | model={model_name} | msg={err_msg[:200]}")
            raise HTTPException(status_code=502, detail=err_msg)
        raw_summary = (result.text or "").strip()
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - _summarize_start
        logger.error(
            f"[SummarizeCtx] LLM 调用超时（>{elapsed:.0f}s）| model={model_name} "
            f"| prompt_chars={len(prompt)} | to_summarize={len(to_summarize)} 条 "
            f"| 可能原因：模型响应慢 / 网络延迟 / 内容过长"
        )
        raise HTTPException(status_code=504, detail="Summary generation timed out")
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        _code = e.response.status_code if e.response is not None else 0
        err_text = (e.response.text[:300] if e.response is not None else "") or "Unknown error"
        logger.error(f"[SummarizeCtx] LLM API 错误 {_code}: {err_text}")
        raise HTTPException(status_code=502, detail=f"LLM API error {_code}")
    except Exception as e:
        logger.error(f"[SummarizeCtx] LLM 调用异常: {e}")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    # ── 拒绝检测：摘要完成后 is_refusal；游戏/锁分若判为拒绝则换供应商（如豆包）重试 ──
    if raw_summary and await is_refusal(raw_summary):
        if is_galgame:
            sid = str(active_model.get("id") or "")
            fb_model = _pick_summarize_refusal_fallback_model(sid)
            if fb_model:
                g_model_name = fb_model.get("model_name") or fb_model.get("id", "")
                g_reasoning_policy = resolve_software_reasoning_policy(
                    "conversation_summary",
                    model_name=g_model_name,
                    mode=f"{mode}_summarize_refusal_fallback",
                    active_model=fb_model,
                    endpoint=fb_model.get("endpoint", ""),
                )
                g_body: Dict[str, Any] = {
                    "model": g_model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                }
                apply_llm_task_payload_config(g_body, "conversation_summary", output_token_field="max_tokens")
                logger.info(
                    f"🔄 [SummarizeCtx] 摘要被判为拒绝，使用备用模型重试 | model={g_model_name} "
                    f"| user={username} char={character_id[:8]}..."
                )
                try:
                    g_result = await asyncio.wait_for(
                        call_llm_payload(
                            g_body,
                            fb_model,
                            task="summarize",
                            httpx_client=app_config.httpx_client,
                            timeout=summary_timeout,
                            chat_debug_request={
                                "username": username,
                                "character_id": character_id,
                                "mode": f"{mode}_summarize_refusal_fallback",
                                "model_name": g_model_name,
                                "stage": "REQUEST",
                            },
                            record_usage="main",
                            usage_meter_username=username,
                            reasoning_policy=g_reasoning_policy,
                        ),
                        timeout=summary_timeout,
                    )
                    g_data = g_result.raw_response
                    if isinstance(g_data.get("error"), dict):
                        err_msg = g_data["error"].get("message", "LLM error")
                        logger.error(f"[SummarizeCtx] 备用模型摘要返回错误对象 | msg={err_msg[:200]}")
                        return {"skipped": True, "reason": "refusal_detected"}
                    raw_summary = (g_result.text or "").strip()
                except asyncio.TimeoutError:
                    logger.error("[SummarizeCtx] 备用模型摘要调用超时")
                    return {"skipped": True, "reason": "refusal_detected"}
                except Exception as e:
                    logger.error(f"[SummarizeCtx] 备用模型摘要调用异常: {e}")
                    return {"skipped": True, "reason": "refusal_detected"}

                if raw_summary and not await is_refusal(raw_summary):
                    pass
                else:
                    logger.warning(
                        f"[SummarizeCtx] 备用模型摘要仍被判为拒绝或未返回内容，跳过 | "
                        f"user={username} char={character_id[:8]}..."
                    )
                    return {"skipped": True, "reason": "refusal_detected"}
            else:
                logger.warning(
                    f"[SummarizeCtx] 摘要被判为拒绝且未配置可用备用模型，跳过 | "
                    f"user={username} char={character_id[:8]}..."
                )
                return {"skipped": True, "reason": "refusal_detected"}
        else:
            logger.warning(
                f"[SummarizeCtx] LLM 拒绝生成摘要，跳过 | model={model_name} "
                f"| user={username} char={character_id[:8]}..."
            )
            return {"skipped": True, "reason": "refusal_detected"}

    summary_text = _clean_summary_text(raw_summary, is_galgame_mode=is_galgame, scene_time_hint=scene_time_hint)
    if not is_galgame:
        summary_text = normalize_user_memory_text(summary_text, username=username)
    if not summary_text:
        raise HTTPException(status_code=502, detail="LLM returned empty summary")

    if is_invalid_context_summary(summary_text):
        logger.warning(
            f"[SummarizeCtx] 摘要为合规拒答/占位模板，跳过落库 | user={username} "
            f"char={character_id[:8]}..."
        )
        return {"skipped": True, "reason": "invalid_summary_template"}

    logger.info(
        f"📥 [SummarizeCtx] 摘要生成完成 | 原始长度={len(raw_summary)} chars | "
        f"清理后长度={len(summary_text)} chars"
    )

    # ── 5. 写入 DB ──
    summary_time = int(time.time() * 1000)
    try:
        conn = await db.acquire()
        try:
            async with conn.execute(
                "SELECT id FROM users WHERE username = ? LIMIT 1",
                (username,)
            ) as cur:
                uid_row = await cur.fetchone()
            if not uid_row:
                raise HTTPException(status_code=404, detail="User not found")
            user_id = uid_row[0]

            if is_galgame:
                data_table = "galgame_lock_data" if is_lock_mode else "galgame_data"
                await conn.execute(
                    f"""UPDATE {data_table}
                        SET context_summary = ?,
                            context_summary_time = ?,
                            context_summary_cutoff_message_id = ?,
                            context_summary_cutoff_timestamp = ?,
                            context_summary_cutoff_sequence = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE character_id = ? AND user_id = ?""",
                    (
                        summary_text,
                        summary_time,
                        cutoff_message_id,
                        cutoff_timestamp,
                        cutoff_sequence,
                        character_id,
                        user_id,
                    ),
                )
            else:
                await conn.execute(
                    """UPDATE conversations
                       SET summary = ?,
                           context_summary_cutoff_message_id = ?,
                           context_summary_cutoff_timestamp = ?,
                           context_summary_cutoff_sequence = ?,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND user_id = ? AND COALESCE(is_hidden, 0) = 0""",
                    (
                        summary_text,
                        cutoff_message_id,
                        cutoff_timestamp,
                        cutoff_sequence,
                        conversation_id,
                        user_id,
                    ),
                )
            await conn.commit()
        finally:
            await db.release(conn)

        # 摘要/截断字段已通过局部 UPDATE 落库，避免全量保存覆盖并发新增消息。
    except Exception as e:
        logger.error(f"[SummarizeCtx] 摘要写入 DB 失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to persist summary: {e}")

    logger.info(
        f"✅ [SummarizeCtx] 摘要已落库 | mode={mode} | char={character_id[:8]}... | "
        f"cutoff_id={str(cutoff_message_id or '')[:12] or 'None'} | "
        f"cutoff_seq={cutoff_sequence} | cutoff_ts={cutoff_timestamp}"
    )

    # ── 6. 重新计算 token 用量（仅普通对话；Galgame 已在上方提前返回） ──
    usage = estimate_context_usage(
        messages=all_messages,
        context_summary=summary_text,
        cutoff_message_id=cutoff_message_id,
        cutoff_timestamp=cutoff_timestamp,
        cutoff_sequence=cutoff_sequence,
        source="summarize_context",
    )

    total_tokens = usage.get("total_tokens", 0)
    limit_tokens = usage.get("limit_tokens", CONTEXT_LIMIT_TOKENS)
    logger.info(
        f"📊 [SummarizeCtx] 完成 | token: {total_tokens}/{limit_tokens} "
        f"({round(total_tokens / limit_tokens * 100)}%) | summary={len(summary_text)} chars"
    )

    return {
        "status": "success",
        "total_tokens": total_tokens,
        "limit_tokens": limit_tokens,
        "summary_length": len(summary_text),
    }
