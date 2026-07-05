

class GalgameDAO:
    """Galgame 数据访问对象"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def _table_names(self, game_type: str = "galgame"):
        """锁分模式使用独立表 galgame_lock_data / galgame_lock_messages"""
        if game_type == "galgame_lock":
            return "galgame_lock_data", "galgame_lock_messages"
        return "galgame_data", "galgame_messages"

    async def _self_heal_from_snapshot(
        self,
        username: str,
        char_id: str,
        snapshot: Dict,
        game_type: str,
        reason: str,
        source: str = "unknown",
    ) -> None:
        """
        快照恢复后的自愈回写：
        将已恢复的数据落回 DB，减少同角色反复触发 db_row_missing/db_messages_empty。
        失败不影响主流程。
        """
        if not isinstance(snapshot, dict):
            return
        messages = snapshot.get("messages") or []
        if not isinstance(messages, list) or len(messages) == 0:
            return
        try:
            healed_payload = {
                "score": snapshot.get("score", 40),
                "status": snapshot.get("status", "playing"),
                "version": snapshot.get("version", 1),
                "relationship_stage": snapshot.get("relationship_stage", ""),
                "mood": snapshot.get("mood", ""),
                "memory_tags": snapshot.get("memory_tags", []),
                "event_flags": snapshot.get("event_flags", {}),
                "score_delta_reason": snapshot.get("score_delta_reason", ""),
                "char_memory": snapshot.get("char_memory"),
                "shortTermMemory": snapshot.get("shortTermMemory"),
                "shortTermMemoryStartTurn": snapshot.get("shortTermMemoryStartTurn"),
                "shortTermMemoryCutoffTurn": snapshot.get("shortTermMemoryCutoffTurn"),
                "longTermMemory": snapshot.get("longTermMemory"),
                "longTermMemoryCutoffTurn": snapshot.get("longTermMemoryCutoffTurn"),
                "messages": messages,
                # 自愈回写代表“有数据”，避免误写成清空态
                "force_clear": False,
            }
            healed_ok = await self.save_galgame_data(
                username=username,
                char_id=char_id,
                galgame_data=healed_payload,
                allow_overwrite_with_fewer=False,
                game_type=game_type
            )
            if healed_ok:
                logger.info(
                    "🩹 [快照自愈] mode=%s reason=%s source=%s user=%s char=%s messages=%s",
                    ("galgame_lock" if game_type == "galgame_lock" else "galgame"),
                    reason,
                    source,
                    username,
                    char_id,
                    len(messages),
                )
            else:
                logger.warning(
                    "⚠️ [快照自愈] 回写失败 mode=%s reason=%s source=%s user=%s char=%s messages=%s",
                    ("galgame_lock" if game_type == "galgame_lock" else "galgame"),
                    reason,
                    source,
                    username,
                    char_id,
                    len(messages),
                )
        except Exception as heal_err:
            logger.warning(
                "⚠️ [快照自愈] 异常 mode=%s reason=%s source=%s user=%s char=%s err=%s",
                ("galgame_lock" if game_type == "galgame_lock" else "galgame"),
                reason,
                source,
                username,
                char_id,
                heal_err,
            )

    async def save_galgame_data(
        self,
        username: str,
        char_id: str,
        galgame_data: Dict,
        allow_overwrite_with_fewer: bool = False,
        game_type: str = "galgame"
    ) -> bool:
        """
        保存 Galgame 数据到数据库

        参数：
            username: 用户名
            char_id: 角色ID
            galgame_data: Galgame 数据，包含 messages, score, status 等
            allow_overwrite_with_fewer: 为 True 时允许用更少消息覆盖（如前端 save_intent=user_edit 用户主动删除/编辑）
            game_type: 'galgame' 普通游戏 | 'galgame_lock' 锁分模式（独立存储）

        返回：
            是否成功
        """
        data_table, messages_table = self._table_names(game_type)
        messages = galgame_data.get('messages', [])
        stage = "init"
        tx_started = False
        active_session_id = None
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                stage = "open_connection"
                await conn.execute("PRAGMA foreign_keys = ON")
                await conn.execute("PRAGMA busy_timeout = 5000")
                stage = "resolve_user"
                user_id = await self.db._get_user_id(conn, username)
                stage = "load_active_session"
                async with conn.execute(
                    f"SELECT active_session_id FROM {data_table} WHERE character_id = ? AND user_id = ?",
                    (char_id, user_id)
                ) as cur:
                    row = await cur.fetchone()
                    active_session_id = row[0] if row else None

                # 🛡️ [防误删] 除非 allow_overwrite_with_fewer（用户主动编辑），否则禁止用空或更少数据覆盖
                if not allow_overwrite_with_fewer:
                    async with conn.execute(
                        f"""SELECT COUNT(*) FROM {messages_table}
                            WHERE character_id = ? AND user_id = ?
                              AND deleted_at IS NULL
                              AND COALESCE(session_id, '') = COALESCE(?, '')""",
                        (char_id, user_id, active_session_id)
                    ) as cur:
                        row = await cur.fetchone()
                        existing_count = row[0] if row else 0
                    if existing_count > 0 and len(messages) < existing_count:
                        logger.warning(
                            f"🛡️ [防误删] 拒绝用更少消息覆盖 Galgame: {char_id[:8]}... "
                            f"(前端 {len(messages)} 条, 后端 {existing_count} 条)"
                        )
                        return True  # 返回 True 避免调用方无限重试

                score = galgame_data.get('score', 40)
                status = galgame_data.get('status', 'playing')
                incoming_version = galgame_data.get('version', 1)
                relationship_stage = str(galgame_data.get('relationship_stage', '') or '').strip()
                mood = str(galgame_data.get('mood', '') or '').strip()
                memory_tags = galgame_data.get('memory_tags', [])
                if not isinstance(memory_tags, list):
                    memory_tags = []
                memory_tags_json = json.dumps(memory_tags, ensure_ascii=False)
                event_flags = galgame_data.get('event_flags', {})
                if not isinstance(event_flags, dict):
                    event_flags = {}
                event_flags_json = json.dumps(event_flags, ensure_ascii=False)
                score_delta_reason = str(galgame_data.get('score_delta_reason', '') or '').strip()
                # 摘要字段保护：前端 payload 未携带这些字段时，必须保留后端已落库的摘要状态
                # 否则 auto_sync 会把已总结状态覆盖为空，导致 token 统计回退为全量。
                existing_context_summary = ""
                existing_context_summary_time = None
                existing_cutoff_message_id = None
                existing_cutoff_timestamp = None
                existing_cutoff_sequence = None
                existing_char_memory_json = ""
                existing_short_term_memory = ""
                existing_short_term_memory_start_turn = None
                existing_short_term_memory_cutoff_turn = None
                existing_long_term_memory = ""
                existing_long_term_memory_cutoff_turn = None
                async with conn.execute(
                    f"""SELECT context_summary, context_summary_time,
                               context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence,
                               char_memory_json,
                               short_term_memory, short_term_memory_start_turn, short_term_memory_cutoff_turn,
                               long_term_memory, long_term_memory_cutoff_turn,
                               COALESCE(victory_celebration_ack, 0)
                        FROM {data_table}
                        WHERE character_id = ? AND user_id = ?""",
                    (char_id, user_id)
                ) as sc:
                    summary_row = await sc.fetchone()
                    existing_victory_ack = 0
                    if summary_row:
                        existing_context_summary = str(summary_row[0] or "").strip()
                        existing_context_summary_time = summary_row[1]
                        existing_cutoff_message_id = summary_row[2]
                        existing_cutoff_timestamp = summary_row[3]
                        existing_cutoff_sequence = summary_row[4]
                        existing_char_memory_json = str(summary_row[5] or "").strip() if len(summary_row) > 5 else ""
                        if len(summary_row) > 6:
                            existing_short_term_memory = str(summary_row[6] or "").strip()
                        if len(summary_row) > 7:
                            existing_short_term_memory_start_turn = summary_row[7]
                        if len(summary_row) > 8:
                            existing_short_term_memory_cutoff_turn = summary_row[8]
                        if len(summary_row) > 9:
                            existing_long_term_memory = str(summary_row[9] or "").strip()
                        if len(summary_row) > 10:
                            existing_long_term_memory_cutoff_turn = summary_row[10]
                        if len(summary_row) > 11:
                            try:
                                existing_victory_ack = int(summary_row[11] or 0)
                            except Exception:
                                existing_victory_ack = 0

                try:
                    score_int = int(score if score is not None else 40)
                except Exception:
                    score_int = 40
                if score_int < 100:
                    victory_ack_val = 0
                else:
                    _vp = galgame_data.get("victory_celebration_ack")
                    if _vp is None:
                        _vp = galgame_data.get("victoryCelebrationAck")
                    if _vp is not None:
                        victory_ack_val = 1 if _vp in (True, 1, "1") else 0
                    else:
                        victory_ack_val = existing_victory_ack

                def _pick_payload_value(*keys, fallback=None):
                    for k in keys:
                        if k in galgame_data:
                            return galgame_data.get(k)
                    return fallback

                context_summary = str(_pick_payload_value('contextSummary', 'context_summary', fallback=existing_context_summary) or '').strip()
                context_summary_time = _pick_payload_value('contextSummaryTime', 'context_summary_time', fallback=existing_context_summary_time)
                context_summary_cutoff_message_id = _pick_payload_value(
                    'contextSummaryCutoffMessageId', 'context_summary_cutoff_message_id',
                    fallback=existing_cutoff_message_id
                )
                context_summary_cutoff_timestamp = _pick_payload_value(
                    'contextSummaryCutoffTimestamp', 'context_summary_cutoff_timestamp',
                    fallback=existing_cutoff_timestamp
                )
                context_summary_cutoff_sequence = _pick_payload_value(
                    'contextSummaryCutoffSequence', 'context_summary_cutoff_sequence',
                    fallback=existing_cutoff_sequence
                )
                _cm_pick = _pick_payload_value("char_memory", "charMemory", fallback=None)
                if isinstance(_cm_pick, dict):
                    char_memory_json = json.dumps(_cm_pick, ensure_ascii=False)
                elif isinstance(_cm_pick, str) and _cm_pick.strip():
                    char_memory_json = _cm_pick.strip()
                else:
                    char_memory_json = existing_char_memory_json or ""

                short_term_memory = str(
                    _pick_payload_value(
                        "shortTermMemory", "short_term_memory",
                        fallback=existing_short_term_memory,
                    )
                    or ""
                ).strip()
                short_term_memory_start_turn = _pick_payload_value(
                    "shortTermMemoryStartTurn", "short_term_memory_start_turn",
                    fallback=existing_short_term_memory_start_turn,
                )
                short_term_memory_cutoff_turn = _pick_payload_value(
                    "shortTermMemoryCutoffTurn", "short_term_memory_cutoff_turn",
                    fallback=existing_short_term_memory_cutoff_turn,
                )
                long_term_memory = str(
                    _pick_payload_value(
                        "longTermMemory", "long_term_memory",
                        fallback=existing_long_term_memory,
                    )
                    or ""
                ).strip()
                long_term_memory_cutoff_turn = _pick_payload_value(
                    "longTermMemoryCutoffTurn", "long_term_memory_cutoff_turn",
                    fallback=existing_long_term_memory_cutoff_turn,
                )
                # 有消息时清除 force_clear；前端传 force_clear 时按前端值持久化
                force_clear_val = 1 if galgame_data.get('force_clear') and len(messages) == 0 else 0

                # 🔧 [事务保护] 从第一次写操作前进入显式事务，避免“写入后再 BEGIN”触发嵌套事务报错
                stage = "begin_transaction"
                await conn.execute("BEGIN IMMEDIATE")
                tx_started = True
                try:
                    # 确保角色存在
                    stage = "ensure_character"
                    async with conn.execute(
                        "SELECT id FROM characters WHERE id = ? AND user_id = ?",
                        (char_id, user_id)
                    ) as cursor:
                        char_exists = await cursor.fetchone()
                        if not char_exists:
                            await conn.execute(
                                """INSERT OR IGNORE INTO characters 
                                   (id, user_id, name, avatar, prompt, bio, data)
                                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                (char_id, user_id, '未知角色', None, '', '', json.dumps({'id': char_id}))
                            )
                            logger.warning(f"⚠️ [DB] 角色 {char_id[:8]}... 不存在，已创建占位符")

                    if not active_session_id:
                        stage = "bind_legacy_session_id"
                        active_session_id = _new_session_id()
                        # 兼容旧数据：首次启用会话隔离时，将历史无 session_id 消息绑定到当前会话
                        await conn.execute(
                            f"""UPDATE {messages_table}
                                SET session_id = ?
                                WHERE character_id = ? AND user_id = ? AND session_id IS NULL""",
                            (active_session_id, char_id, user_id)
                        )

                    # 自动递增 version：取 max(已有版本, 前端版本) + 1
                    stage = "auto_increment_version"
                    existing_gal_version = 0
                    async with conn.execute(
                        f"SELECT version FROM {data_table} WHERE character_id = ? AND user_id = ?",
                        (char_id, user_id)
                    ) as vc:
                        vrow = await vc.fetchone()
                        if vrow:
                            existing_gal_version = vrow[0] or 0
                    version = max(existing_gal_version, incoming_version) + 1

                    # 锁分模式：序列化三组体征对象（普通 galgame 表无这三列，条件写入）
                    import json as _json
                    _char_vitals_json = None
                    _char_mood_json = None
                    _organ_fill_json = None
                    _character_gender_val = ""
                    if game_type == "galgame_lock":
                        _cv = galgame_data.get("char_vitals")
                        _cm = galgame_data.get("char_mood")
                        _of = galgame_data.get("organ_fill")
                        if isinstance(_cv, dict):
                            _char_vitals_json = _json.dumps(_cv, ensure_ascii=False)
                        if isinstance(_cm, dict):
                            _char_mood_json = _json.dumps(_cm, ensure_ascii=False)
                        if isinstance(_of, dict):
                            _organ_fill_json = _json.dumps(_of, ensure_ascii=False)
                        _character_gender_val = str(galgame_data.get("character_gender") or "").strip()

                    stage = "upsert_galgame_data"
                    if game_type == "galgame_lock":
                        await conn.execute(
                            f"""INSERT OR REPLACE INTO {data_table}
                               (character_id, user_id, score, status, version, relationship_stage, mood, memory_tags, event_flags, score_delta_reason,
                                context_summary, context_summary_time, context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence,
                                char_memory_json, short_term_memory, short_term_memory_start_turn, short_term_memory_cutoff_turn,
                                long_term_memory, long_term_memory_cutoff_turn,
                                force_clear, active_session_id, char_vitals, char_mood, organ_fill, character_gender,
                                victory_celebration_ack, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                            (
                                char_id, user_id, score, status, version,
                                relationship_stage, mood, memory_tags_json, event_flags_json,
                                score_delta_reason, context_summary, context_summary_time,
                                context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence,
                                char_memory_json,
                                short_term_memory or None,
                                short_term_memory_start_turn,
                                short_term_memory_cutoff_turn,
                                long_term_memory or None,
                                long_term_memory_cutoff_turn,
                                force_clear_val, active_session_id,
                                _char_vitals_json, _char_mood_json, _organ_fill_json, _character_gender_val,
                                victory_ack_val,
                            )
                        )
                    else:
                        await conn.execute(
                            f"""INSERT OR REPLACE INTO {data_table}
                               (character_id, user_id, score, status, version, relationship_stage, mood, memory_tags, event_flags, score_delta_reason,
                                context_summary, context_summary_time, context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence,
                                char_memory_json, short_term_memory, short_term_memory_start_turn, short_term_memory_cutoff_turn,
                                long_term_memory, long_term_memory_cutoff_turn,
                                force_clear, active_session_id, victory_celebration_ack, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                            (
                                char_id, user_id, score, status, version,
                                relationship_stage, mood, memory_tags_json, event_flags_json,
                                score_delta_reason, context_summary, context_summary_time,
                                context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence,
                                char_memory_json,
                                short_term_memory or None,
                                short_term_memory_start_turn,
                                short_term_memory_cutoff_turn,
                                long_term_memory or None,
                                long_term_memory_cutoff_turn,
                                force_clear_val, active_session_id,
                                victory_ack_val,
                            )
                        )

                    stage = "upsert_messages"
                    messages = galgame_data.get('messages', [])
                    # 预读当前会话下已存在的图片信息，避免后续被空/占位符覆盖
                    existing_images = {}
                    async with conn.execute(
                        f"SELECT message_id, image_url, image_thumbnail FROM {messages_table} "
                        f"WHERE character_id = ? AND user_id = ? "
                        f"  AND COALESCE(session_id, '') = COALESCE(?, '') "
                        f"  AND deleted_at IS NULL",
                        (char_id, user_id, active_session_id)
                    ) as cur:
                        async for row in cur:
                            mid, iu, it = row[0], row[1], row[2]
                            if mid and (iu or it):
                                existing_images[mid] = (iu, it)
                    seen_message_ids = set()
                    incoming_message_ids = []
                    for idx, msg in enumerate(messages):
                        message_id = msg.get('message_id')
                        if not message_id:
                            message_id = msg.get('id') or f"{char_id}_gal_msg_{idx}_{int(time.time() * 1000)}"
                        
                        if message_id in seen_message_ids:
                            logger.warning(f"⚠️ [DB] 跳过重复 Galgame 消息ID: {message_id}")
                            continue
                        seen_message_ids.add(message_id)
                        incoming_message_ids.append(message_id)
                        
                        msg_id = msg.get('id') or f"{char_id}_gal_msg_{idx}"
                        role = msg.get('role', 'user')
                        content = msg.get('content', '')
                        raw_content = _coerce_galgame_assistant_raw(
                            role, str(content or ""), str(msg.get("rawContent", "") or "")
                        )
                        # 标记这次同步是否显式携带 image_url 字段
                        has_image_field = 'image_url' in msg
                        image_url = msg.get('image_url')
                        image_thumbnail = None
                        # 🔧 [图片保护 - Galgame]
                        if has_image_field:
                            if image_url and isinstance(image_url, str) and image_url.startswith('data:image'):
                                is_draw = msg.get('is_draw_image') is True
                                image_url = compress_image_to_jpg(image_url, skip_compress=is_draw)
                                image_thumbnail = create_image_thumbnail(image_url)
                            else:
                                # 显式带入空或非 data:image：视为清空图片
                                existing = existing_images.get(message_id)
                                if existing and image_url is None:
                                    # 若前端传的是完全空值，默认保留已有图，避免误删
                                    image_url, image_thumbnail = existing
                        else:
                            # 未显式同步图片字段：沿用库中已有的图片
                            existing = existing_images.get(message_id)
                            if existing:
                                image_url, image_thumbnail = existing
                        msg_timestamp = msg.get('timestamp', 0)
                        # 统一重建连续序号，避免历史脏数据/并发覆盖造成序号乱序后影响读取顺序
                        sequence_number = idx
                        previous_message_id = msg.get('previous_message_id')
                        is_hidden = 1 if msg.get('isHidden') or msg.get('is_hidden') else 0
                        suggestions = json.dumps(msg.get('suggestions', [])) if msg.get('suggestions') else None
                        client_id = msg.get('client_id')
                        generation_duration_ms = msg.get('generation_duration_ms')
                        if generation_duration_ms is None:
                            generation_duration_ms = msg.get('generationDurationMs')
                        try:
                            generation_duration_ms = int(generation_duration_ms) if generation_duration_ms is not None else None
                        except Exception:
                            generation_duration_ms = None
                        # 🎮 [修复] 保存游戏选项，确保重启后选项不丢失
                        galgame_options = json.dumps(msg.get('galgameOptions', [])) if msg.get('galgameOptions') else None
                        # scene_metadata 列保留，运行时不再写入（唯一真源为 raw_content）
                        scene_metadata = None
                        
                        await conn.execute(
                            f"""INSERT OR REPLACE INTO {messages_table} 
                               (id, character_id, user_id, role, content, raw_content, scene_metadata, image_url, timestamp,
                                message_id, sequence_number, previous_message_id, is_hidden, suggestions, client_id, generation_duration_ms, image_thumbnail, galgame_options, session_id, deleted_at, delete_reason)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)""",
                            (msg_id, char_id, user_id, role, content, raw_content, scene_metadata, image_url, msg_timestamp,
                             message_id, sequence_number, previous_message_id, is_hidden, suggestions, client_id, generation_duration_ms, image_thumbnail, galgame_options, active_session_id)
                        )
                    # 🛡️ [软删除] 当前会话中未再出现的消息仅标记删除，不做物理删除
                    stage = "soft_delete_messages"
                    if incoming_message_ids:
                        async with conn.execute(
                            f"""SELECT COUNT(*) FROM {messages_table}
                                WHERE character_id = ? AND user_id = ?
                                  AND COALESCE(session_id, '') = COALESCE(?, '')
                                  AND deleted_at IS NULL
                                  AND message_id NOT IN ({",".join(["?"] * len(incoming_message_ids))})""",
                            (char_id, user_id, active_session_id, *incoming_message_ids),
                        ) as diff_cur:
                            diff_row = await diff_cur.fetchone()
                            diff_soft_delete_count = diff_row[0] if diff_row else 0
                        async with conn.execute(
                            f"""SELECT COUNT(*) FROM {messages_table}
                                WHERE character_id = ? AND user_id = ?
                                  AND COALESCE(session_id, '') = COALESCE(?, '')
                                  AND deleted_at IS NULL
                                  AND message_id IS NULL""",
                            (char_id, user_id, active_session_id),
                        ) as legacy_cur:
                            legacy_row = await legacy_cur.fetchone()
                            legacy_soft_delete_count = legacy_row[0] if legacy_row else 0

                        placeholders = ",".join(["?"] * len(incoming_message_ids))
                        await conn.execute(
                            f"""UPDATE {messages_table}
                                SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                                    delete_reason = COALESCE(delete_reason, 'user_removed_from_galgame_session')
                                WHERE character_id = ? AND user_id = ?
                                  AND COALESCE(session_id, '') = COALESCE(?, '')
                                  AND deleted_at IS NULL
                                  AND message_id NOT IN ({placeholders})""",
                            (char_id, user_id, active_session_id, *incoming_message_ids)
                        )
                        await conn.execute(
                            f"""UPDATE {messages_table}
                                SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                                    delete_reason = COALESCE(delete_reason, 'legacy_null_message_id')
                                WHERE character_id = ? AND user_id = ?
                                  AND COALESCE(session_id, '') = COALESCE(?, '')
                                  AND deleted_at IS NULL
                                  AND message_id IS NULL""",
                            (char_id, user_id, active_session_id)
                        )
                        if (diff_soft_delete_count + legacy_soft_delete_count) > 0:
                            await write_deletion_audit(
                                conn,
                                action="soft_delete",
                                object_type="galgame_message",
                                object_id=f"{char_id}:{active_session_id or 'default'}",
                                user_id=user_id,
                                username=username,
                                character_id=char_id,
                                operator=f"user:{username}",
                                reason="sync_prune_galgame_session_messages",
                                source="sync",
                                details={
                                    "game_type": game_type,
                                    "session_id": active_session_id,
                                    "diff_soft_deleted": diff_soft_delete_count,
                                    "legacy_null_mid_soft_deleted": legacy_soft_delete_count,
                                },
                            )
                    else:
                        # 🛡️ [防空覆盖] 与普通对话一致：如果传入的消息列表为空，但后端已有未删除的消息，
                        # 且非 force_clear，则拒绝全量软删除，避免前端异常导致数据丢失
                        existing_gal_cur = await conn.execute(
                            f"SELECT COUNT(*) FROM {messages_table} WHERE character_id = ? AND user_id = ? AND COALESCE(session_id, '') = COALESCE(?, '') AND deleted_at IS NULL",
                            (char_id, user_id, active_session_id)
                        )
                        existing_gal_row = await existing_gal_cur.fetchone()
                        existing_gal_count = existing_gal_row[0] if existing_gal_row else 0
                        
                        if existing_gal_count > 0 and force_clear_val == 0:
                            logger.warning(
                                f"🛡️ [Galgame-防空覆盖] 拒绝清空消息: {char_id[:8]}... "
                                f"(后端有 {existing_gal_count} 条活跃消息, 前端传入 0 条, force_clear=False) — 跳过软删除"
                            )
                        else:
                            await conn.execute(
                                f"""UPDATE {messages_table}
                                    SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                                        delete_reason = COALESCE(delete_reason, 'session_cleared')
                                    WHERE character_id = ? AND user_id = ?
                                      AND COALESCE(session_id, '') = COALESCE(?, '')
                                      AND deleted_at IS NULL""",
                                (char_id, user_id, active_session_id)
                            )
                            if existing_gal_count > 0:
                                await write_deletion_audit(
                                    conn,
                                    action="soft_delete",
                                    object_type="galgame_message",
                                    object_id=f"{char_id}:{active_session_id or 'default'}",
                                    user_id=user_id,
                                    username=username,
                                    character_id=char_id,
                                    operator=f"user:{username}",
                                    reason="galgame_session_cleared",
                                    source="sync",
                                    details={
                                        "game_type": game_type,
                                        "session_id": active_session_id,
                                        "soft_deleted_messages": existing_gal_count,
                                        "force_clear": bool(force_clear_val),
                                    },
                                )
                    
                    stage = "commit_transaction"
                    await conn.execute("COMMIT")
                    tx_started = False
                except Exception:
                    if tx_started:
                        try:
                            await conn.execute("ROLLBACK")
                        except Exception as rollback_err:
                            logger.error(
                                f"❌ [DB] Galgame 回滚失败: user={username}, char_id={char_id}, "
                                f"game_type={game_type}, stage={stage}, err={rollback_err}"
                            )
                        finally:
                            tx_started = False
                    raise
                # 🛡️ [角色级防丢失] 仅对非空消息持久化恢复快照，防止误清空后该角色整段历史不可恢复
                stage = "write_snapshot"
                if len(messages) > 0:
                    _snap_char_memory: dict = {"entries": []}
                    try:
                        if char_memory_json:
                            _snap_p = json.loads(char_memory_json)
                            if isinstance(_snap_p, dict):
                                _snap_char_memory = _snap_p
                    except Exception:
                        pass
                    await _write_recovery_snapshot(
                        username,
                        char_id,
                        game_type,
                        {
                            "score": score,
                            "status": status,
                            "version": version,
                            "relationship_stage": relationship_stage,
                            "mood": mood,
                            "memory_tags": memory_tags,
                            "event_flags": event_flags,
                            "score_delta_reason": score_delta_reason,
                            "contextSummary": context_summary,
                            "contextSummaryTime": context_summary_time,
                            "contextSummaryCutoffMessageId": context_summary_cutoff_message_id,
                            "contextSummaryCutoffTimestamp": context_summary_cutoff_timestamp,
                            "contextSummaryCutoffSequence": context_summary_cutoff_sequence,
                            "char_memory": _snap_char_memory,
                            "shortTermMemory": short_term_memory,
                            "shortTermMemoryStartTurn": short_term_memory_start_turn,
                            "shortTermMemoryCutoffTurn": short_term_memory_cutoff_turn,
                            "longTermMemory": long_term_memory,
                            "longTermMemoryCutoffTurn": long_term_memory_cutoff_turn,
                            "messages": messages,
                            "force_clear": False,
                            "updated_at": int(time.time() * 1000),
                        }
                    )
                
                logger.info(f"💾 [DB] Galgame{'锁分' if game_type == 'galgame_lock' else ''} 已写入: char_id={char_id[:12]}..., messages={len(messages)}, score={score}")
                return True
                
        except Exception as e:
            logger.error(
                "❌ [DB] 保存 Galgame 数据失败: "
                f"user={username}, char_id={char_id}, game_type={game_type}, "
                f"stage={stage}, tx_started={tx_started}, "
                f"active_session_id={active_session_id}, messages={len(messages)}, err={e}"
            )
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def load_galgame_data(
        self,
        username: str,
        char_id: str,
        game_type: str = "galgame",
        source: str = "unknown",
    ) -> Optional[Dict]:
        """
        加载 Galgame 数据
        
        参数：
            username: 用户名
            char_id: 角色ID
            game_type: 'galgame' 普通游戏 | 'galgame_lock' 锁分模式
            
        返回：
            Galgame 数据字典，如果不存在则返回 None
        """
        data_table, messages_table = self._table_names(game_type)
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                user_id = await self.db._get_user_id(conn, username)
                
                # 加载游戏状态（含 force_clear、updated_at：用于保存时按时间比较，避免旧数据覆盖新数据）
                # 锁分模式额外读取三组体征列（普通 galgame 表无这三列，通过 game_type 区分）
                _extra_cols = ", char_vitals, char_mood, organ_fill, character_gender" if game_type == "galgame_lock" else ""
                _tier_cols = (
                    ", short_term_memory, short_term_memory_start_turn, short_term_memory_cutoff_turn, "
                    "long_term_memory, long_term_memory_cutoff_turn"
                )
                async with conn.execute(
                    f"""SELECT score, status, version, relationship_stage, mood, memory_tags, event_flags, score_delta_reason,
                               context_summary, context_summary_time, context_summary_cutoff_message_id, context_summary_cutoff_timestamp, context_summary_cutoff_sequence,
                               COALESCE(force_clear, 0), updated_at, active_session_id, char_memory_json{_extra_cols}{_tier_cols},
                               COALESCE(victory_celebration_ack, 0)
                        FROM {data_table} WHERE character_id = ? AND user_id = ?""",
                    (char_id, user_id)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        snapshot = await _load_recovery_snapshot(username, char_id, game_type)
                        if snapshot:
                            lock = await _get_recovery_lock(username, char_id, game_type)
                            async with lock:
                                async with conn.execute(
                                    f"""SELECT 1 FROM {data_table}
                                        WHERE character_id = ? AND user_id = ?""",
                                    (char_id, user_id)
                                ) as recheck_cursor:
                                    recheck_row = await recheck_cursor.fetchone()
                                if recheck_row:
                                    # 另一并发请求已完成自愈，直接走常规加载，避免重复恢复和重复告警。
                                    return await self.load_galgame_data(
                                        username=username,
                                        char_id=char_id,
                                        game_type=game_type,
                                        source=f"{source}:post_recovery_recheck"
                                    )
                                snapshot["force_clear"] = False
                                snapshot["_recovered_from_snapshot"] = True
                                snap_path = _snapshot_path(username, char_id, game_type)
                                snap_mtime = None
                                try:
                                    if snap_path.exists():
                                        snap_mtime = int(snap_path.stat().st_mtime * 1000)
                                except Exception:
                                    snap_mtime = None
                                should_warn, elapsed_ms = _should_emit_recovery_warning(
                                    username=username,
                                    char_id=char_id,
                                    game_type=game_type,
                                    reason="db_row_missing",
                                )
                                if should_warn:
                                    logger.warning(
                                        "🛡️ [快照恢复] mode=%s reason=db_row_missing source=%s user=%s char=%s "
                                        "snapshot_messages=%s snapshot_updated_at=%s snapshot_file_mtime=%s snapshot_path=%s",
                                        ("galgame_lock" if game_type == "galgame_lock" else "galgame"),
                                        source,
                                        username,
                                        char_id,
                                        len(snapshot.get("messages") or []),
                                        snapshot.get("updated_at"),
                                        snap_mtime,
                                        str(snap_path),
                                    )
                                else:
                                    logger.info(
                                        "🛡️ [快照恢复-抑制] mode=%s reason=db_row_missing source=%s user=%s char=%s "
                                        "elapsed_ms=%s snapshot_messages=%s",
                                        ("galgame_lock" if game_type == "galgame_lock" else "galgame"),
                                        source,
                                        username,
                                        char_id,
                                        elapsed_ms,
                                        len(snapshot.get("messages") or []),
                                    )
                                await self._self_heal_from_snapshot(
                                    username=username,
                                    char_id=char_id,
                                    snapshot=snapshot,
                                    game_type=game_type,
                                    reason="db_row_missing",
                                    source=source,
                                )
                                return snapshot
                        logger.debug(f"📥 [DB] Galgame 数据不存在: {char_id[:8]}...")
                        return None
                    
                    score, status, version = row[0], row[1], row[2]
                    relationship_stage = str(row[3] or "").strip() if len(row) > 3 else ""
                    mood = str(row[4] or "").strip() if len(row) > 4 else ""
                    memory_tags = []
                    if len(row) > 5 and row[5]:
                        try:
                            parsed_tags = json.loads(row[5])
                            if isinstance(parsed_tags, list):
                                memory_tags = parsed_tags
                        except Exception:
                            memory_tags = []
                    event_flags = {}
                    if len(row) > 6 and row[6]:
                        try:
                            parsed_flags = json.loads(row[6])
                            if isinstance(parsed_flags, dict):
                                event_flags = parsed_flags
                        except Exception:
                            event_flags = {}
                    score_delta_reason = str(row[7] or "").strip() if len(row) > 7 else ""
                    context_summary = str(row[8] or "").strip() if len(row) > 8 else ""
                    context_summary_time = row[9] if len(row) > 9 else None
                    context_summary_cutoff_message_id = row[10] if len(row) > 10 else None
                    context_summary_cutoff_timestamp = row[11] if len(row) > 11 else None
                    context_summary_cutoff_sequence = row[12] if len(row) > 12 else None
                    force_clear = bool(row[13]) if len(row) > 13 else False
                    updated_at = row[14] if len(row) > 14 else None
                    active_session_id = row[15] if len(row) > 15 else None
                    char_memory_loaded: dict | None = None
                    if len(row) > 16 and row[16]:
                        try:
                            _cm_parsed = json.loads(row[16])
                            if isinstance(_cm_parsed, dict):
                                char_memory_loaded = _cm_parsed
                        except Exception:
                            char_memory_loaded = None

                    # 锁分模式：解析三组体征列及角色性别（紧随 char_memory_json 之后）
                    char_vitals_loaded = None
                    char_mood_loaded = None
                    organ_fill_loaded = None
                    character_gender_loaded = ""
                    if game_type == "galgame_lock":
                        def _parse_vitals_col(val):
                            if not val:
                                return None
                            try:
                                parsed = json.loads(val)
                                return parsed if isinstance(parsed, dict) else None
                            except Exception:
                                return None
                        char_vitals_loaded = _parse_vitals_col(row[17] if len(row) > 17 else None)
                        char_mood_loaded   = _parse_vitals_col(row[18] if len(row) > 18 else None)
                        organ_fill_loaded  = _parse_vitals_col(row[19] if len(row) > 19 else None)
                        character_gender_loaded = str(row[20] or "").strip() if len(row) > 20 else ""

                    _tier_base = 21 if game_type == "galgame_lock" else 17
                    short_term_memory_loaded = str(row[_tier_base] or "").strip() if len(row) > _tier_base else ""
                    short_term_memory_start_turn_loaded = row[_tier_base + 1] if len(row) > _tier_base + 1 else None
                    short_term_memory_cutoff_turn_loaded = row[_tier_base + 2] if len(row) > _tier_base + 2 else None
                    long_term_memory_loaded = str(row[_tier_base + 3] or "").strip() if len(row) > _tier_base + 3 else ""
                    long_term_memory_cutoff_turn_loaded = row[_tier_base + 4] if len(row) > _tier_base + 4 else None
                    try:
                        victory_celebration_ack_loaded = int(row[-1] or 0) if row else 0
                    except Exception:
                        victory_celebration_ack_loaded = 0

                # 加载消息
                messages = []
                async with conn.execute(
                    f"""SELECT role, content, raw_content, image_url, timestamp, message_id,
                              sequence_number, previous_message_id, is_hidden, suggestions, client_id, generation_duration_ms, galgame_options
                       FROM {messages_table} 
                       WHERE character_id = ? AND user_id = ?
                         AND deleted_at IS NULL
                         AND COALESCE(session_id, '') = COALESCE(?, '')
                       ORDER BY COALESCE(timestamp, 0) ASC, COALESCE(sequence_number, 0) ASC, rowid ASC""",
                    (char_id, user_id, active_session_id)
                ) as msg_cursor:
                    async for msg_row in msg_cursor:
                        role, content, raw_content, image_url, msg_timestamp, message_id, \
                        sequence_number, previous_message_id, is_hidden, suggestions_json, client_id, generation_duration_ms, galgame_options_json = msg_row
                        
                        msg = {
                            'role': role,
                            'content': content,
                            'timestamp': msg_timestamp,
                            'message_id': message_id,
                            'sequence_number': sequence_number,
                            'previous_message_id': previous_message_id,
                        }

                        # 🔧 [修复] 返回 rawContent；旧行只有 JSON 在 content 时，读取侧补 raw，与写入侧 _coerce 一致
                        if raw_content:
                            msg['rawContent'] = raw_content
                        elif role == "assistant" and (content or "").strip().startswith("{"):
                            msg['rawContent'] = (content or "").strip()
                        
                        if image_url:
                            msg['image_url'] = image_url
                        if is_hidden:
                            msg['isHidden'] = True
                            msg['is_hidden'] = True
                        if suggestions_json:
                            try:
                                msg['suggestions'] = json.loads(suggestions_json)
                            except:
                                msg['suggestions'] = []
                        if client_id:
                            msg['client_id'] = client_id
                        if generation_duration_ms is not None:
                            try:
                                msg['generation_duration_ms'] = int(generation_duration_ms)
                            except Exception:
                                pass
                        # 🎮 [修复] 恢复游戏选项，确保重启后最后一条消息的选项能正常显示
                        if galgame_options_json:
                            try:
                                msg['galgameOptions'] = json.loads(galgame_options_json)
                            except:
                                msg['galgameOptions'] = []
                        
                        messages.append(msg)
                
                result = {
                    'score': score,
                    'status': status,
                    'version': version,
                    'relationship_stage': relationship_stage,
                    'mood': mood,
                    'memory_tags': memory_tags,
                    'event_flags': event_flags,
                    'score_delta_reason': score_delta_reason,
                    'contextSummary': context_summary,
                    'contextSummaryTime': context_summary_time,
                    'contextSummaryCutoffMessageId': context_summary_cutoff_message_id,
                    'contextSummaryCutoffTimestamp': context_summary_cutoff_timestamp,
                    'contextSummaryCutoffSequence': context_summary_cutoff_sequence,
                    'char_memory': char_memory_loaded or {"entries": []},
                    'shortTermMemory': short_term_memory_loaded,
                    'shortTermMemoryStartTurn': short_term_memory_start_turn_loaded,
                    'shortTermMemoryCutoffTurn': short_term_memory_cutoff_turn_loaded,
                    'longTermMemory': long_term_memory_loaded,
                    'longTermMemoryCutoffTurn': long_term_memory_cutoff_turn_loaded,
                    'messages': messages,
                    'force_clear': force_clear,
                    'updated_at': updated_at,
                    'active_session_id': active_session_id,
                    'victory_celebration_ack': victory_celebration_ack_loaded,
                    **({"char_vitals": char_vitals_loaded,
                        "char_mood":   char_mood_loaded,
                        "organ_fill":  organ_fill_loaded,
                        "character_gender": character_gender_loaded} if game_type == "galgame_lock" else {})
                }
                # 🛡️ [角色级防丢失] 数据行存在但消息为空且未标记 force_clear，判定为异常空读，回退到最近快照
                if len(messages) == 0 and not force_clear:
                    snapshot = await _load_recovery_snapshot(username, char_id, game_type)
                    if snapshot:
                        lock = await _get_recovery_lock(username, char_id, game_type)
                        async with lock:
                            # 进入锁后复查，避免并发恢复导致重复告警。
                            async with conn.execute(
                                f"""SELECT COUNT(*) FROM {messages_table}
                                    WHERE character_id = ? AND user_id = ?
                                      AND deleted_at IS NULL
                                      AND COALESCE(session_id, '') = COALESCE(?, '')""",
                                (char_id, user_id, active_session_id)
                            ) as recheck_msg_cursor:
                                recheck_msg_row = await recheck_msg_cursor.fetchone()
                            recheck_count = recheck_msg_row[0] if recheck_msg_row else 0
                            if recheck_count > 0:
                                return await self.load_galgame_data(
                                    username=username,
                                    char_id=char_id,
                                    game_type=game_type,
                                    source=f"{source}:post_recovery_recheck"
                                )
                            snapshot["force_clear"] = False
                            snapshot["updated_at"] = updated_at or snapshot.get("updated_at")
                            snapshot["_recovered_from_snapshot"] = True
                            snap_path = _snapshot_path(username, char_id, game_type)
                            snap_mtime = None
                            try:
                                if snap_path.exists():
                                    snap_mtime = int(snap_path.stat().st_mtime * 1000)
                            except Exception:
                                snap_mtime = None
                            should_warn, elapsed_ms = _should_emit_recovery_warning(
                                username=username,
                                char_id=char_id,
                                game_type=game_type,
                                reason="db_messages_empty",
                            )
                            if should_warn:
                                logger.warning(
                                    "🛡️ [快照恢复] mode=%s reason=db_messages_empty source=%s user=%s char=%s "
                                    "active_session_id=%s db_updated_at=%s snapshot_messages=%s snapshot_updated_at=%s "
                                    "snapshot_file_mtime=%s snapshot_path=%s",
                                    ("galgame_lock" if game_type == "galgame_lock" else "galgame"),
                                    source,
                                    username,
                                    char_id,
                                    active_session_id,
                                    updated_at,
                                    len(snapshot.get("messages") or []),
                                    snapshot.get("updated_at"),
                                    snap_mtime,
                                    str(snap_path),
                                )
                            else:
                                logger.info(
                                    "🛡️ [快照恢复-抑制] mode=%s reason=db_messages_empty source=%s user=%s char=%s "
                                    "elapsed_ms=%s active_session_id=%s snapshot_messages=%s",
                                    ("galgame_lock" if game_type == "galgame_lock" else "galgame"),
                                    source,
                                    username,
                                    char_id,
                                    elapsed_ms,
                                    active_session_id,
                                    len(snapshot.get("messages") or []),
                                )
                            await self._self_heal_from_snapshot(
                                username=username,
                                char_id=char_id,
                                snapshot=snapshot,
                                game_type=game_type,
                                reason="db_messages_empty",
                                source=source,
                            )
                            return snapshot
                
                logger.debug(f"📥 [DB] 加载 Galgame 数据: {char_id[:8]}... ({len(messages)} 条消息, 分数: {score})")
                return result
                
        except Exception as e:
            logger.error(f"❌ [DB] 加载 Galgame 数据失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    async def load_galgame_data_resolved(
        self,
        username: str,
        char_id: str,
        source: str = "unknown",
    ) -> tuple:
        """
        解析 character_id 并加载 Galgame 数据，与 get_conversation_detail 的解析逻辑一致。
        用于保存前防误删：避免因前端传短 id（如 5b35488a）而 DB 存完整 UUID 导致 load 得到 None、误判为可覆盖。
        返回 (resolved_char_id, data)，data 为 None 时 resolved_char_id 为传入的 char_id。
        """
        data = await self.load_galgame_data(username, char_id, source=source)
        if data is not None:
            return (char_id, data)
        if "_" in char_id:
            return (char_id, None)
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                user_id = await self.db._get_user_id(conn, username)
                pattern_underscore = char_id + "_%"
                pattern_any = char_id + "%"
                async with conn.execute(
                    """SELECT character_id FROM galgame_data 
                       WHERE user_id = ? AND (character_id = ? OR character_id LIKE ? OR character_id LIKE ?)
                       ORDER BY LENGTH(character_id) DESC, updated_at DESC LIMIT 1""",
                    (user_id, char_id, pattern_underscore, pattern_any)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        resolved_char_id = row[0]
                        data = await self.load_galgame_data(username, resolved_char_id, source=source)
                        return (resolved_char_id, data)
        except Exception as e:
            logger.warning(f"⚠️ [DB] 解析 character_id 失败: {e}")
        return (char_id, None)
    
    async def load_galgame_data_by_char_id_prefix(
        self,
        username: str,
        char_id: str,
        source: str = "unknown",
    ) -> Optional[Dict]:
        """
        按角色 ID 或「角色ID_后缀」加载 Galgame 数据（用于从大厅添加的角色：id 为 originalId_timestamp，重进时可能只传 originalId）。
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                user_id = await self.db._get_user_id(conn, username)
                pattern = char_id + "_%"
                # 🛡️ [防丢失] 同一角色可能有多条（短 id 空记录 + 完整 UUID 有消息），优先取「有消息」的那条，避免整段对话消失显示开始界面
                async with conn.execute(
                    """SELECT g.character_id, g.score, g.status, g.version FROM galgame_data g
                       WHERE g.user_id = ? AND (g.character_id = ? OR g.character_id LIKE ?)
                       ORDER BY (SELECT COUNT(*) FROM galgame_messages m WHERE m.character_id = g.character_id AND m.user_id = g.user_id) DESC, g.updated_at DESC LIMIT 1""",
                    (user_id, char_id, pattern)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return None
                    resolved_char_id, score, status, version = row
                
                # 用查到的 character_id 再走一次完整加载（消息等）
                return await self.load_galgame_data(username, resolved_char_id, source=source)
                
        except Exception as e:
            logger.error(f"❌ [DB] 按前缀加载 Galgame 数据失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def set_victory_celebration_ack(
        self,
        username: str,
        char_id: str,
        game_type: str = "galgame",
        value: int = 1,
    ) -> bool:
        """将满分庆祝弹窗已展示标记写入 galgame_data / galgame_lock_data（仅 UPDATE 已有行）。"""
        data_table, _ = self._table_names(game_type)
        v = 1 if int(value or 0) else 0
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                user_id = await self.db._get_user_id(conn, username)
                cur = await conn.execute(
                    f"""UPDATE {data_table}
                        SET victory_celebration_ack = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE character_id = ? AND user_id = ?""",
                    (v, char_id, user_id),
                )
                await conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            logger.error(f"❌ [DB] set_victory_celebration_ack 失败: {e}")
            return False
    
    async def reset_galgame_data(
        self,
        username: str,
        char_id: str,
        game_type: str = "galgame"
    ) -> bool:
        """
        重置 Galgame 数据。一角色一 id，仅按 character_id 精确操作。
        game_type: 'galgame' | 'galgame_lock'
        """
        data_table, messages_table = self._table_names(game_type)
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                user_id = await self.db._get_user_id(conn, username)
                await conn.execute("PRAGMA busy_timeout = 5000")
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    new_session_id = _new_session_id()
                    await conn.execute(
                        f"""INSERT OR REPLACE INTO {data_table} 
                           (character_id, user_id, score, status, version, force_clear, active_session_id, updated_at)
                           VALUES (?, ?, 40, 'playing', 1, 1, ?, CURRENT_TIMESTAMP)""",
                        (char_id, user_id, new_session_id)
                    )
                    await conn.execute("COMMIT")
                except Exception:
                    await conn.execute("ROLLBACK")
                    raise
                logger.info(f"🔄 [DB] 重置 Galgame{'锁分' if game_type == 'galgame_lock' else ''} 数据: {char_id[:8]}...")
                _last_reset_at[(username, char_id, game_type)] = time.time()
                return True
                
        except Exception as e:
            logger.error(f"❌ [DB] 重置 Galgame 数据失败: {e}")
            return False

    @staticmethod
    def was_recently_reset(username: str, char_id: str, game_type: str = "galgame") -> bool:
        """该角色是否在宽限期内被重置过（用于拒绝 auto_sync 用更多消息覆盖）。"""
        key = (username, char_id, game_type)
        if key not in _last_reset_at:
            # 兼容旧 key（无 game_type）
            if game_type == "galgame" and (username, char_id) in _last_reset_at:
                return (time.time() - _last_reset_at[(username, char_id)]) <= RESET_GRACE_SECONDS
            return False
        return (time.time() - _last_reset_at[key]) <= RESET_GRACE_SECONDS

    async def get_sync_fingerprint(self, username: str) -> Dict[str, str]:
        """
        获取 Galgame 数据的同步指纹（按角色的 updated_at），用于定时同步时判断是否有变更。
        同时包含普通 galgame 和锁分 galgame_lock 的数据，确保锁分变更也能触发前端同步。
        返回: { character_id: "updated_at 字符串", ... }
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as conn:
                user_id = await self.db._get_user_id(conn, username)
                if user_id is None:
                    return {}
                result = {}
                # 普通 Galgame
                async with conn.execute(
                    """SELECT character_id, updated_at FROM galgame_data WHERE user_id = ?""",
                    (user_id,)
                ) as cursor:
                    async for row in cursor:
                        char_id, updated = row
                        if char_id and updated:
                            result[char_id] = str(updated)
                # 🛡️ [锁分同步] 同时查询锁分表，取两表中较新的 updated_at
                try:
                    async with conn.execute(
                        """SELECT character_id, updated_at FROM galgame_lock_data WHERE user_id = ?""",
                        (user_id,)
                    ) as cursor:
                        async for row in cursor:
                            char_id, updated = row
                            if char_id and updated:
                                lock_key = f"{char_id}_lock"
                                result[lock_key] = str(updated)
                except Exception:
                    pass  # 旧数据库可能无此表
                return result
        except Exception as e:
            logger.error(f"❌ [DB] Galgame 同步指纹获取失败: {e}")
            return {}
