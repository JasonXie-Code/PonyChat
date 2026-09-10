

@router.get("/conversation/messages_since")
async def get_messages_since(
    username: str,
    character_id: str,
    mode: str = "normal",
    after_seq: int = -1,
    conversation_id: Optional[str] = None,
    load_full_images: bool = False
):
    """增量消息拉取：仅返回 sequence_number > after_seq 的新消息，避免传输整个会话历史。
    前端同步层在检测到版本变化后调用此接口，只拉取 delta 部分。"""
    try:
        db = get_database()
        await db.init()

        if mode in ("galgame", "galgame_lock"):
            game_type = "galgame_lock" if mode == "galgame_lock" else "galgame"
            data_table = "galgame_lock_data" if game_type == "galgame_lock" else "galgame_data"
            messages_table = "galgame_lock_messages" if game_type == "galgame_lock" else "galgame_messages"
            async with aiosqlite.connect(db.db_path) as conn:
                user_id = await db._get_user_id(conn, username)
                # 获取 active_session_id
                active_session_id = None
                async with conn.execute(
                    f"SELECT active_session_id, version, score, status FROM {data_table} WHERE character_id = ? AND user_id = ?",
                    (character_id, user_id)
                ) as cur:
                    row = await cur.fetchone()
                    if row:
                        active_session_id = row[0]
                        gal_version = row[1] or 0
                        gal_score = row[2] or 40
                        gal_status = row[3] or 'playing'
                    else:
                        return {"status": "success", "new_messages": [], "data_version": 0, "total_count": 0}

                new_messages = []
                async with conn.execute(
                    f"""SELECT role, content, raw_content, image_url, timestamp, message_id,
                               sequence_number, previous_message_id, is_hidden, suggestions, client_id, galgame_options
                        FROM {messages_table}
                        WHERE character_id = ? AND user_id = ? AND deleted_at IS NULL
                          AND COALESCE(session_id, '') = COALESCE(?, '')
                          AND COALESCE(sequence_number, 0) > ?
                        ORDER BY COALESCE(timestamp, 0) ASC, COALESCE(sequence_number, 0) ASC, rowid ASC""",
                    (character_id, user_id, active_session_id, after_seq)
                ) as cur:
                    async for row in cur:
                        msg = {
                            'role': row[0], 'content': row[1], 'timestamp': row[4],
                            'message_id': row[5], 'sequence_number': row[6],
                            'previous_message_id': row[7]
                        }
                        _raw_eff = _coerce_galgame_assistant_raw(
                            str(row[0] or ""), str(row[1] or ""), str(row[2] or "")
                        )
                        if _raw_eff:
                            msg['rawContent'] = _raw_eff
                        if row[3]: msg['image_url'] = row[3]
                        if row[9]:
                            try: msg['suggestions'] = json.loads(row[9])
                            except: msg['suggestions'] = []
                        if row[10]: msg['client_id'] = row[10]
                        if row[11]:
                            try: msg['galgameOptions'] = json.loads(row[11])
                            except: pass
                        new_messages.append(msg)

                # 获取总消息数
                total_count = 0
                async with conn.execute(
                    f"""SELECT COUNT(*) FROM {messages_table}
                        WHERE character_id = ? AND user_id = ? AND deleted_at IS NULL
                          AND COALESCE(session_id, '') = COALESCE(?, '')""",
                    (character_id, user_id, active_session_id)
                ) as cur:
                    row = await cur.fetchone()
                    total_count = row[0] if row else 0

                logger.info(f"📥 [IncrSync] Galgame增量: {character_id[:8]}... after_seq={after_seq} → {len(new_messages)} 条新消息 (共{total_count}条)")
                return {
                    "status": "success",
                    "new_messages": new_messages,
                    "data_version": gal_version,
                    "total_count": total_count,
                    "score": gal_score,
                    "game_status": gal_status
                }
        else:
            # 普通模式
            convs_dao = ConversationsDAO(db)
            async with aiosqlite.connect(db.db_path) as conn:
                await conn.execute('BEGIN IMMEDIATE')
                user_id = await db._get_user_id(conn, username)
                # 确定目标对话（最新的 or 指定的）
                if not conversation_id:
                    async with conn.execute(
                        """SELECT id FROM conversations
                           WHERE user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0
                           ORDER BY timestamp DESC LIMIT 1""",
                        (user_id, character_id)
                    ) as cur:
                        row = await cur.fetchone()
                        conversation_id = row[0] if row else None
                if not conversation_id:
                    return {"status": "success", "new_messages": [], "data_version": 0, "total_count": 0, "conversation_id": None}

                # 获取对话 version
                conv_version = 0
                async with conn.execute(
                    "SELECT version FROM conversations WHERE id = ? AND user_id=? AND character_id=? AND COALESCE(is_hidden,0)=0",
                    (conversation_id, user_id, character_id)
                ) as cur:
                    row = await cur.fetchone()
                    if not row:
                        return {"status": "success", "new_messages": [], "data_version": 0, "total_count": 0, "conversation_id": conversation_id}
                    conv_version = row[0] or 0 if row else 0

                new_messages = []
                from Backend.chat_modules.normal_delivery import pending_message_ids
                pending = sorted(pending_message_ids(username, character_id, conversation_id))
                pending_sql = f" AND (message_id IS NULL OR message_id NOT IN ({','.join('?' for _ in pending)}))" if pending else ''
                async with conn.execute(
                    f"""SELECT role, content, raw_content, image_url, timestamp, message_id,
                              sequence_number, previous_message_id, suggestions, suggestions_status, client_id, think_translations, quoted_message_json
                       FROM messages
                       WHERE conversation_id = ? AND deleted_at IS NULL AND COALESCE(is_hidden, 0) = 0
                         AND COALESCE(sequence_number, 0) > ? {pending_sql}
                       ORDER BY COALESCE(timestamp, 0) ASC, COALESCE(sequence_number, 0) ASC, rowid ASC""",
                    [conversation_id, after_seq, *pending]
                ) as cur:
                    async for row in cur:
                        msg = {
                            'role': row[0], 'content': row[1], 'timestamp': row[4],
                            'message_id': row[5], 'sequence_number': row[6],
                            'previous_message_id': row[7]
                        }
                        if row[2]: msg['rawContent'] = row[2]
                        if row[3]: msg['image_url'] = row[3]
                        if row[8]:
                            try: msg['suggestions'] = json.loads(row[8])
                            except: msg['suggestions'] = []
                        msg['suggestions_status'] = row[9] or 'none'
                        if row[10]: msg['client_id'] = row[10]
                        if row[11]:
                            try: msg['thinkTranslations'] = json.loads(row[11])
                            except: pass
                        if row[12]:
                            try: msg['quoted_message'] = json.loads(row[12])
                            except Exception: pass
                        new_messages.append(msg)
                if new_messages:
                    from ..db.message_attachments import load_attachments_for_messages
                    from ..db.message_voice_states import attach_voice_state, load_voice_states_for_messages
                    attachments_by_mid = await load_attachments_for_messages(
                        conn,
                        conversation_id,
                        [str(m.get("message_id") or "") for m in new_messages],
                    )
                    for msg in new_messages:
                        atts = attachments_by_mid.get(str(msg.get("message_id") or ""))
                        if atts:
                            msg["attachments"] = atts
                    voice_states_by_mid = await load_voice_states_for_messages(
                        conn,
                        conversation_id,
                        [str(m.get("message_id") or "") for m in new_messages],
                    )
                    for msg in new_messages:
                        attach_voice_state(msg, voice_states_by_mid.get(str(msg.get("message_id") or "")))

                total_count = 0
                async with conn.execute(
                    f"SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND deleted_at IS NULL AND COALESCE(is_hidden, 0) = 0 {pending_sql}",
                    [conversation_id, *pending]
                ) as cur:
                    row = await cur.fetchone()
                    total_count = row[0] if row else 0

                logger.info(f"📥 [IncrSync] 普通增量: {character_id[:8]}... conv={conversation_id[:8]}... after_seq={after_seq} → {len(new_messages)} 条新消息 (共{total_count}条)")
                return {
                    "status": "success",
                    "new_messages": new_messages,
                    "data_version": conv_version,
                    "total_count": total_count,
                    "conversation_id": conversation_id
                }
    except Exception as e:
        logger.error(f"增量消息拉取失败: {str(e)}")
        return {"status": "error", "new_messages": [], "data_version": 0, "total_count": 0}


@router.get("/conversation/detail")
async def get_conversation_detail(username: str, character_id: Optional[str] = None, conversation_id: Optional[str] = None, mode: str = "normal", only_latest: bool = False, load_full_images: bool = False):
    """获取特定对话的详细内容（纯数据库模式）"""
    try:
        target_id = character_id or conversation_id
        if not target_id:
            raise HTTPException(status_code=400, detail="Missing character_id or conversation_id")

        async with galgame_locker.acquire(username, target_id):
            db = get_database()
            await db.init()

            # 预加载角色 system prompt，统一叠加到 token 估算中
            _sys_prompt = await _load_system_prompt_for_character(db, username, target_id)

            # 1. Galgame / 锁分模式（按 character_id 存储；锁分使用独立表）
            if mode in ("galgame", "galgame_lock"):
                galgame_dao = GalgameDAO(db)
                game_type = "galgame_lock" if mode == "galgame_lock" else "galgame"
                galgame_data = await galgame_dao.load_galgame_data(
                    username,
                    target_id,
                    game_type=game_type,
                    source="conversation_detail"
                )
                if galgame_data:
                    messages = galgame_data.get('messages', [])
                    # 统计可见消息数量（仅用于日志/message_count 字段），实际返回包含隐藏消息
                    # 客户端 sentMessages 需与服务端消息数保持一致，才能正确判断是否跳过覆盖；
                    # 客户端已在 UI 层自行过滤隐藏消息（filter { it.isHidden != true }），无需后端预先过滤
                    display_messages = [m for m in messages if not m.get('isHidden') and not m.get('is_hidden')]
                    # 分层记忆（长期+短期）近似为「摘要占位」token；已不再使用 context_summary 截断消息链
                    _tier_for_usage = "\n\n".join(
                        x for x in (
                            str(galgame_data.get("longTermMemory") or "").strip(),
                            str(galgame_data.get("shortTermMemory") or "").strip(),
                        ) if x
                    ).strip()
                    # 使用游戏专用估算：旧轮 scene 精简 + 完整 galgame system 模板，与 service 中 request_tokens 对齐
                    usage = estimate_galgame_context_usage(
                        messages=messages,
                        context_summary=_tier_for_usage,
                        cutoff_message_id=None,
                        cutoff_timestamp=None,
                        cutoff_sequence=None,
                        system_prompt=_sys_prompt,
                        mode=mode,
                        score=galgame_data.get("score", 40),
                        source="conversation_detail",
                    )
                    fp = {"username": username, "character_id": target_id, "conversation_id": target_id, "mode": mode}
                    # 返回完整消息列表（含隐藏消息），使客户端 sentMessages 计数与服务端对齐
                    optimized_messages = optimize_messages_for_response(messages, use_placeholders=not load_full_images, fetch_params=fp)
                    logger.info(f"📥 [DB] 加载 Galgame 对话: {target_id[:8]}... ({len(display_messages)}/{len(messages)} 条可见, 分数: {galgame_data.get('score', 40)})")
                    _resp = {
                        "status": "success",
                        "success": True,
                        "messages": optimized_messages,
                        "score": galgame_data.get('score', 40),
                        "game_status": galgame_data.get('status', 'playing'),
                        "force_clear": bool(galgame_data.get('force_clear', False)),
                        "victory_celebration_ack": int(galgame_data.get('victory_celebration_ack') or 0),
                        "updated_at": galgame_data.get('updated_at'),
                        "data_version": galgame_data.get('version', 0),
                        "message_count": len(display_messages),
                        "usage": usage,
                    }
                    # 锁分模式：附带最新体征数据（供 App 初始加载时填充生命体征面板）
                    if mode == "galgame_lock":
                        _resp["char_vitals"] = galgame_data.get("char_vitals")
                        _resp["char_mood"]   = galgame_data.get("char_mood")
                        _resp["organ_fill"]  = galgame_data.get("organ_fill")
                    return _resp
                # 无数据返回默认
                return {
                    "status": "success",
                    "success": True,
                    "messages": [],
                    "score": 40,
                    "game_status": "playing",
                    "force_clear": False,
                    "victory_celebration_ack": 0,
                    "data_version": 0,
                    "message_count": 0,
                    "usage": {"total_tokens": 0, "limit_tokens": BACKEND_CONTEXT_LIMIT_TOKENS, "source": "conversation_detail"},
                }
            
            # 2. 普通模式（一角色一 id，仅精确匹配）
            convs_dao = ConversationsDAO(db)
            conversations = await convs_dao.load_conversations(username, target_id, visible_delivery_only=True)
            if conversations:
                use_placeholders = not load_full_images
                # 若调用方指定了 conversation_id，则优先定位到该对话（switchConversation 场景）
                if conversation_id:
                    matched = next((c for c in conversations if c.get('id') == conversation_id), None)
                    if matched:
                        messages = matched.get('messages', [])
                        fp = {"username": username, "character_id": target_id, "conversation_id": conversation_id, "mode": mode}
                        optimized_messages = optimize_messages_for_response(messages, use_placeholders=use_placeholders, fetch_params=fp)
                        logger.info(f"📥 [DB] 加载指定对话: {target_id[:8]}.../{conversation_id[:8]}... ({len(messages)} 条消息)")
                        optimized_conversations = []
                        for c in conversations:
                            cfp = {"username": username, "character_id": target_id, "conversation_id": c.get('id', ''), "mode": mode}
                            opt_msgs = optimize_messages_for_response(c.get('messages', []), use_placeholders=use_placeholders, fetch_params=cfp)
                            optimized_conversations.append({**c, "messages": opt_msgs})
                        return {
                            "status": "success",
                            "success": True,
                            "messages": optimized_messages,
                            "conversations": optimized_conversations,
                            "data_version": matched.get('version', 0),
                            "message_count": len(messages),
                            "usage": _estimate_context_usage_for_detail(
                                messages=messages,
                                context_summary=matched.get("contextSummary") or matched.get("summary") or "",
                                cutoff_message_id=matched.get("contextSummaryCutoffMessageId"),
                                cutoff_timestamp=matched.get("contextSummaryCutoffTimestamp"),
                                cutoff_sequence=matched.get("contextSummaryCutoffSequence"),
                                system_prompt=_sys_prompt,
                            ),
                        }
                    # conversation_id 指定的对话不存在，回退到默认行为（返回全部，选最新）
                    logger.warning(f"⚠️ [DB] 指定对话 {conversation_id[:8]}... 未找到，回退至最新对话")
                if only_latest:
                    convs_with_msgs = [c for c in conversations if c.get('messages')]
                    if convs_with_msgs:
                        latest_conv = max(convs_with_msgs, key=lambda x: x.get('timestamp', 0))
                    else:
                        latest_conv = max(conversations, key=lambda x: x.get('timestamp', 0))
                    messages = latest_conv.get('messages', [])
                    fp = {"username": username, "character_id": target_id, "conversation_id": latest_conv.get('id', ''), "mode": mode}
                    optimized_messages = optimize_messages_for_response(messages, use_placeholders=use_placeholders, fetch_params=fp)
                    logger.info(f"📥 [DB] 加载最新对话: {target_id[:8]}... ({len(messages)} 条消息)")
                    # 返回的 conversations 里也使用占位符，避免前端从 conv.messages 读到完整图
                    latest_conv_optimized = {**latest_conv, "messages": optimized_messages}
                    return {
                        "status": "success",
                        "success": True,
                        "messages": optimized_messages,
                        "conversations": [latest_conv_optimized],
                        "data_version": latest_conv.get('version', 0),
                        "message_count": len(messages),
                        "usage": _estimate_context_usage_for_detail(
                            messages=messages,
                            context_summary=latest_conv.get("contextSummary") or latest_conv.get("summary") or "",
                            cutoff_message_id=latest_conv.get("contextSummaryCutoffMessageId"),
                            cutoff_timestamp=latest_conv.get("contextSummaryCutoffTimestamp"),
                            cutoff_sequence=latest_conv.get("contextSummaryCutoffSequence"),
                            system_prompt=_sys_prompt,
                        ),
                    }
                else:
                    convs_with_msgs = [c for c in conversations if c.get('messages')]
                    if convs_with_msgs:
                        latest_conv = max(convs_with_msgs, key=lambda x: x.get('timestamp', 0))
                    else:
                        latest_conv = max(conversations, key=lambda x: x.get('timestamp', 0))
                    messages = latest_conv.get('messages', []) if latest_conv else []
                    fp = {"username": username, "character_id": target_id, "conversation_id": latest_conv.get('id', '') if latest_conv else '', "mode": mode}
                    optimized_messages = optimize_messages_for_response(messages, use_placeholders=use_placeholders, fetch_params=fp)
                    logger.info(f"📥 [DB] 加载对话: {target_id[:8]}... ({len(conversations)} 个对话, {len(messages)} 条消息)")
                    # 每个对话的 messages 都做占位符优化，避免前端合并时拿到完整图片数据
                    optimized_conversations = []
                    for c in conversations:
                        cfp = {"username": username, "character_id": target_id, "conversation_id": c.get('id', ''), "mode": mode}
                        opt_msgs = optimize_messages_for_response(c.get('messages', []), use_placeholders=use_placeholders, fetch_params=cfp)
                        optimized_conversations.append({**c, "messages": opt_msgs})
                    total_ver = sum(c.get('version', 0) for c in conversations)
                    return {
                        "status": "success",
                        "success": True,
                        "messages": optimized_messages,
                        "conversations": optimized_conversations,
                        "data_version": total_ver,
                        "message_count": len(messages),
                        "usage": _estimate_context_usage_for_detail(
                            messages=messages,
                            context_summary=(latest_conv or {}).get("contextSummary") or (latest_conv or {}).get("summary") or "",
                            cutoff_message_id=(latest_conv or {}).get("contextSummaryCutoffMessageId"),
                            cutoff_timestamp=(latest_conv or {}).get("contextSummaryCutoffTimestamp"),
                            cutoff_sequence=(latest_conv or {}).get("contextSummaryCutoffSequence"),
                            system_prompt=_sys_prompt,
                        ),
                    }
            
            return {
                "status": "success",
                "success": True,
                "messages": [],
                "conversations": [],
                "data_version": 0,
                "message_count": 0,
                "usage": {"total_tokens": 0, "limit_tokens": BACKEND_CONTEXT_LIMIT_TOKENS, "source": "conversation_detail"},
            }
    except Exception as e:
        logger.error(f"获取对话详情失败: {str(e)}")
        return {"status": "error", "success": False, "message": str(e)}


@router.post("/galgame/victory_ack")
async def post_galgame_victory_ack(payload: Dict[str, Any]):
    """客户端满分庆祝弹窗展示后写入 victory_celebration_ack=1（需已有 galgame 行）。"""
    body = payload or {}
    username = (body.get("username") or "").strip()
    character_id = (body.get("character_id") or "").strip()
    mode = (body.get("mode") or "galgame").strip()
    if not username or not character_id:
        raise HTTPException(status_code=400, detail="Missing username or character_id")
    if mode not in ("galgame", "galgame_lock"):
        raise HTTPException(status_code=400, detail="mode must be galgame or galgame_lock")
    try:
        async with galgame_locker.acquire(username, character_id):
            db = get_database()
            await db.init()
            galgame_dao = GalgameDAO(db)
            game_type = "galgame_lock" if mode == "galgame_lock" else "galgame"
            ok = await galgame_dao.set_victory_celebration_ack(
                username, character_id, game_type=game_type, value=1
            )
            if not ok:
                return {
                    "status": "error",
                    "success": False,
                    "message": "galgame row missing or update failed",
                }
            return {"status": "success", "success": True}
    except Exception as e:
        logger.error(f"❌ [galgame/victory_ack] {e}")
        return {"status": "error", "success": False, "message": str(e)}


def _resolve_image_url(m: dict, size: str) -> Optional[str]:
    """根据 size 返回 thumbnail 或 original 的 base64 URL"""
    if size == "thumbnail":
        url = m.get("image_thumbnail") or m.get("image_url")
    else:
        url = m.get("image_url")
    return url if (url and isinstance(url, str) and url.startswith("data:image")) else None


def _url_to_response(url: str):
    """将 base64 data URL 转为 Response"""
    from fastapi.responses import Response
    import base64
    header, encoded = url.split(",", 1)
    data = base64.b64decode(encoded)
    mime = "image/jpeg"
    if "png" in header:
        mime = "image/png"
    elif "webp" in header:
        mime = "image/webp"
    return Response(content=data, media_type=mime)


@router.get("/conversation/message_image")
async def get_message_image(
    username: str,
    character_id: str,
    conversation_id: str,
    message_id: str,
    mode: str = "normal",
    size: str = "thumbnail",
):
    """按需加载单条消息的图片（纯数据库模式）"""
    from fastapi.responses import Response
    from ..utils import create_image_thumbnail

    try:
        if mode in ("galgame", "galgame_lock"):
            conv_id = character_id
        else:
            conv_id = conversation_id or character_id

        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            if mode == "galgame_lock":
                table = "galgame_lock_messages"
                user_id = await db._get_user_id(conn, username)
                where = "character_id = ? AND user_id = ? AND message_id = ? AND deleted_at IS NULL"
                params = (character_id, user_id, message_id)
            elif mode == "galgame":
                table = "galgame_messages"
                user_id = await db._get_user_id(conn, username)
                where = "character_id = ? AND user_id = ? AND message_id = ? AND deleted_at IS NULL"
                params = (character_id, user_id, message_id)
            else:
                table = "messages"
                where = "conversation_id = ? AND message_id = ? AND deleted_at IS NULL AND COALESCE(is_hidden, 0) = 0"
                params = (conv_id, message_id)

            image_url = None
            image_thumbnail = None
            try:
                sql = f"SELECT image_url, image_thumbnail FROM {table} WHERE {where} LIMIT 1"
                async with conn.execute(sql, params) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        image_url, image_thumbnail = row
            except Exception:
                sql = f"SELECT image_url FROM {table} WHERE {where} LIMIT 1"
                async with conn.execute(sql, params) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        image_url = row[0]

            # Galgame：未命中且 character_id 不含 _ 时，按 character_id 前缀再查（从大厅添加的角色）
            if mode == "galgame" and row is None and "_" not in character_id:
                pattern = character_id + "_%"
                try:
                    sql = """SELECT image_url, image_thumbnail FROM galgame_messages 
                             WHERE user_id = ? AND message_id = ? AND (character_id = ? OR character_id LIKE ?) AND deleted_at IS NULL LIMIT 1"""
                    async with conn.execute(sql, (user_id, message_id, character_id, pattern)) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            image_url, image_thumbnail = row
                except Exception:
                    try:
                        sql = """SELECT image_url FROM galgame_messages 
                                 WHERE user_id = ? AND message_id = ? AND (character_id = ? OR character_id LIKE ?) AND deleted_at IS NULL LIMIT 1"""
                        async with conn.execute(sql, (user_id, message_id, character_id, pattern)) as cursor:
                            row = await cursor.fetchone()
                            if row:
                                image_url = row[0]
                    except Exception:
                        pass

            if image_url and isinstance(image_url, str) and image_url.startswith("data:image"):
                logger.debug(
                    f"🖼️ [图片调试] get_message_image 成功: conv_id={conv_id[:16] if conv_id else 'n/a'}..., "
                    f"msg_id={message_id[:20] if message_id else 'n/a'}..., size={size}, mode={mode}"
                )
                if size == "thumbnail":
                    if image_thumbnail and isinstance(image_thumbnail, str) and image_thumbnail.startswith("data:image"):
                        return _url_to_response(image_thumbnail)
                    else:
                        thumb = create_image_thumbnail(image_url)
                        return _url_to_response(thumb)
                else:
                    return _url_to_response(image_url)
            elif row is not None:
                logger.warning(f"🖼️ [图片调试] get_message_image 404 Image not found: conv_id={conv_id}, msg_id={message_id}")
                raise HTTPException(status_code=404, detail="Image not found")
            else:
                logger.warning(f"🖼️ [图片调试] get_message_image 404 Message not in DB: conv_id={conv_id}, msg_id={message_id}")
                raise HTTPException(status_code=404, detail="Message not found in DB")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取消息图片失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 上下文摘要（后端主导） ====================

class SummarizeContextRequest(BaseModel):
    username: str
    character_id: str
    mode: str = "normal"          # "normal" | "galgame" | "galgame_lock"
    conversation_id: Optional[str] = None  # normal 模式时指定对话
    force: bool = False           # 调试用：跳过消息数量检查，无消息时注入占位故事

_DEBUG_FORCE_SUMMARIZE_STORY = (
    "小镇边有一口古井，传说每逢满月夜，井底便会映出观者内心最渴望的景象。"
    "村里的少年阿远素来不信鬼神，直到那个金秋深夜，他趴在青石井沿向下张望，"
    "竟清晰地看见自己站在十年后某座陌生城市的街头，身旁有一位他从未见过的女子。"
    "那女子缓缓转过身，朝着井底浅浅一笑，随即消失无踪。阿远心跳如鼓，退开数步，惊魂未定。"
    "次日清早，他将此事告诉了村里最年长的祖父。老人沉默片刻，轻叹道："
    "「那口井枯了六十年，哪有什么镜像。你望见的，不过是自己心底藏着的念想罢了。」"
    "阿远低头沉思良久，第一次觉得未来或许并不如他所想的那般遥远而模糊。"
)


def _split_recent_messages(
    messages: list,
    keep_recent_messages: int = CONTEXT_SUMMARY_KEEP_RECENT_MESSAGES,
) -> tuple[list, list]:
    if not messages:
        return [], []
    if keep_recent_messages <= 0:
        return list(messages), []

    recent = list(messages[-keep_recent_messages:]) if len(messages) > keep_recent_messages else list(messages)
    older = list(messages[: max(0, len(messages) - len(recent))])
    return older, recent


def _strip_html_for_summary(text: str) -> str:
    """去除 HTML 标签，保留纯文本（轻量版，适用于总结预处理）。"""
    cleaned = re.sub(r"<br\s*/?>", "\n", str(text or ""), flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return cleaned.strip()


def _extract_galgame_content_for_summary(msg: dict) -> str:
    """
    从游戏/锁分模式的 assistant 消息中提取总结所需的精简文本。

    以 rawContent 整包 JSON 为唯一真源。无有效 raw 时回退到 HTML 解析。

    保留：场景描写(env)、角色回复(response/speech)、时间地点标签、记忆标签。
    丢弃：内心独白(thoughts)、HTML 标签、ion-icon、body_state（已由 env 覆盖）。
    """
    if not isinstance(msg, dict):
        return ""

    # ── 结构化真源：仅 rawContent ───────────────────────────────────────────
    _raw = str(msg.get("rawContent") or msg.get("raw_content") or "").strip()
    _from_raw = _parse_scene_metadata_from_raw(_raw) if _raw.startswith("{") else None
    scene_meta = _from_raw if isinstance(_from_raw, dict) and _from_raw else {}
    if isinstance(scene_meta, dict) and (scene_meta.get("env") or scene_meta.get("response")):
        time_loc = ""
        t = str(scene_meta.get("time") or "").strip()
        loc = str(scene_meta.get("location") or "").strip()
        if t or loc:
            time_loc = f"[{t}·{loc}]" if (t and loc) else f"[{t or loc}]"

        env_text = _strip_html_for_summary(scene_meta.get("env") or "")
        resp_text = _strip_html_for_summary(scene_meta.get("response") or "")

        tags = scene_meta.get("memory_tags") or []
        tags_line = ""
        if isinstance(tags, list) and tags:
            tags_line = "记忆标签：" + "、".join(str(t) for t in tags if t)

        parts = [p for p in [time_loc, env_text, resp_text, tags_line] if p]
        return "\n".join(parts)

    # ── 回退路径：从渲染后的 HTML content 提取 ───────────────────────────────
    content = str(msg.get("content") or "")
    if "galgame-scene-container" not in content:
        # 不是 galgame HTML，原样返回（可能是旧格式或纯文本）
        return content

    def _extract_div(cls: str) -> str:
        m = re.search(rf'class="{re.escape(cls)}"[^>]*>(.*?)</div>', content, re.DOTALL)
        return _strip_html_for_summary(m.group(1)) if m else ""

    env_text = _extract_div("gal-scene-env")
    speech_text = _extract_div("gal-scene-speech")
    # gal-scene-thought 故意跳过

    time_m = re.search(r'class="gal-time-tag"[^>]*>(?:<[^>]*>)*([^<]+)', content)
    loc_m = re.search(r'class="gal-loc-tag"[^>]*>(?:<[^>]*>)*([^<]+)', content)
    t = time_m.group(1).strip() if time_m else ""
    loc = loc_m.group(1).strip() if loc_m else ""
    time_loc = f"[{t}·{loc}]" if (t and loc) else (f"[{t or loc}]" if (t or loc) else "")

    parts = [p for p in [time_loc, env_text, speech_text] if p]
    return "\n".join(parts) if parts else _strip_html_for_summary(content)


def _build_summary_prompt(
    messages_to_summarize: list,
    prev_summary: str = "",
    is_galgame_mode: bool = False,
    is_lock_mode: bool = False,
    scene_time_hint: str = "",
    character_profile_context: str = "",
    user_label: str = USER_MEMORY_PLACEHOLDER,
    assistant_label: str = "角色",
) -> str:
    user_label = str(user_label or "").strip() or "用户"
    assistant_label = str(assistant_label or "").strip() or "角色"

    def _role_name(role: str) -> str:
        return user_label if str(role or "").lower() == "user" else assistant_label

    def _get_msg_content(m) -> str:
        role = str(m.get("role", "") if isinstance(m, dict) else getattr(m, "role", ""))
        if is_galgame_mode and role.lower() == "assistant" and isinstance(m, dict):
            return _extract_galgame_content_for_summary(m)
        return str(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")) or ""

    dialogue_content = "\n\n".join(
        f"{_role_name(m.get('role', '') if isinstance(m, dict) else getattr(m, 'role', ''))}: "
        f"{_get_msg_content(m)}"
        for m in messages_to_summarize
    )
    prev_summary = str(prev_summary or "").strip()
    prev_summary_section = (
        f"【已有的历史摘要（请将其内容融入新摘要中）】\n{prev_summary}\n\n【新增对话内容如下】\n"
        if prev_summary else ""
    )

    time_rule_section = ""
    if is_galgame_mode:
        time_rule_section = (
            "【时间规则（必须遵守）】\n"
            "1) 严禁写入现实世界时间（如\"当前系统时间\"\"2026年xx月xx日\"\"星期几\"\"CST\"等）。\n"
            "2) 仅可使用剧情内场景时间描述（如\"清晨/午后/傍晚/深夜\"）。\n"
            "3) 若无法确定具体场景时间，请写\"以剧情推进为准\"，不要杜撰现实时钟。\n"
        )
        if scene_time_hint:
            time_rule_section += f"4) 当前可参考的场景时间：{scene_time_hint}\n"

    mode_hint = (
        f"当前为{'锁分模式' if is_lock_mode else '游戏模式'}，请按剧情世界观组织记忆，不要混入现实时间。"
        if is_galgame_mode
        else "当前为普通对话模式。"
    )
    character_profile_section = ""
    character_profile_context = str(character_profile_context or "").strip()
    if character_profile_context:
        character_profile_section = (
            "【角色档案参考（只用于识别角色身份、人称、物种、性格基调；不得当成用户说过的话或对话中发生的事实）】\n"
            f"{character_profile_context}\n\n"
        )

    return (
        "你是一个对话记忆提取专家。请对以下对话内容进行深度总结（2000字以内），"
        "保留所有关键人物设定、核心剧情进展、当前情感状态和待办事项。"
        "这份总结将作为角色后续记忆的唯一来源，请尽可能精炼且准确。\n\n"
        "【人称与归因规范（必须遵守）】\n"
        f"本摘要中的用户侧是「{user_label}」，角色侧是「{assistant_label}」。"
        f"摘要正文必须继续用 {USER_MEMORY_PLACEHOLDER} 指代用户本人，不要写真实用户名或昵称；"
        "角色档案只说明角色自身身份和设定，不是用户事实；"
        "不得把角色档案中的性别、种族、性格、兴趣、简介摘要成用户的属性、偏好或发言。\n\n"
        "【情感描写规范（必须遵守）】\n"
        "描述情绪/气氛时，使用概括性语言（如：气氛热烈、非常兴奋、两人玩得很开心），"
        "禁止将对话中出现的感叹词、拟声词、角色口头禅（如：WEEEEE、哈哈哈哈、YAAAAY 等）原样写入摘要。"
        "这些偶发词汇一旦进入记忆，会被后续对话误解为角色的固定习惯，必须以情感描述替代。\n\n"
        "【称呼方向规范（必须遵守）】\n"
        "用户说“叫我X/以后叫我X/你可以叫我X”，表示用户请求角色称呼用户为 X；"
        "不得摘要成用户称呼角色为 X。只有用户说“我叫你X/以后我叫你X”，才表示用户称呼角色为 X。\n\n"
        f"{mode_hint}\n"
        f"{time_rule_section}"
        f"{character_profile_section}"
        f"{prev_summary_section}"
        f"对话内容如下：\n{dialogue_content}"
    )


def _clean_summary_text(raw: str, is_galgame_mode: bool = False, scene_time_hint: str = "") -> str:
    text = _THINK_STRIP_RE.sub("", raw).strip()
    if is_galgame_mode and _REAL_TIME_RE.search(text):
        replace_with = f"当前场景时间：{scene_time_hint.strip()}" if scene_time_hint and scene_time_hint.strip() else "以剧情推进为准"
        text = _REAL_TIME_RE.sub(replace_with, text)
    return text


def _pick_scene_time_hint(messages: list, gal_data: dict) -> str:
    if isinstance(gal_data, dict) and isinstance(gal_data.get("time"), str) and gal_data["time"].strip():
        return gal_data["time"].strip()
    for m in reversed(messages):
        if not isinstance(m, dict) or str(m.get("role") or "").lower() != "assistant":
            continue
        raw = str(m.get("rawContent") or m.get("raw_content") or "").strip()
        if not raw.startswith("{"):
            continue
        flat = _parse_scene_metadata_from_raw(raw)
        if not isinstance(flat, dict):
            continue
        t = flat.get("time")
        if t and isinstance(t, str) and t.strip():
            return t.strip()
    return ""


def _is_deepseek_model_dict(m: dict) -> bool:
    """与业务约定一致：除联网搜索外主用 DeepSeek；用 endpoint/model_name 识别。"""
    ep = str(m.get("endpoint") or "").lower()
    mn = str(m.get("model_name") or "").lower()
    return "api.deepseek.com" in ep or "deepseek" in ep or "deepseek" in mn


def _pick_summarize_refusal_fallback_model(summarize_model_id: str) -> Optional[dict]:
    """摘要被判为拒绝时仅换「另一台 DeepSeek」重试。豆包仅用于联网搜索，不作摘要兜底。"""
    try:
        for m in app_config.model_manager.get_models():
            if m.get("enabled") is False or not str(m.get("api_key") or "").strip():
                continue
            if m.get("id") == summarize_model_id:
                continue
            if _is_deepseek_model_dict(m):
                return m
    except Exception as e:
        logger.debug("[SummarizeCtx] 选备用摘要模型失败: %s", e)
    return None
