

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

    if not is_galgame:
        from Backend.agent_memory.jobs import enqueue
        from Backend.agent_memory.evidence import LOCAL
        from datetime import datetime
        db = get_database()
        await db.init()
        from asyncio import to_thread
        await to_thread(enqueue, db.db_path, username, character_id, immediate=True,
                target_period={"category": "daily", "period": datetime.now(LOCAL).date().isoformat()})
        return {"status": "queued", "summary_length": 0,
                "message": "角色正在整理本日记忆，完成后可在记忆页面查看"}
    game_type = "galgame_lock" if is_lock_mode else "galgame"
    gal_data = await load_galgame_state_async(username, character_id, game_type=game_type)

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
