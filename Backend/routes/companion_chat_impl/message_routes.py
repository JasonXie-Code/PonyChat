

async def _write_companion_memory(
    username: str,
    character_id: str,
    char_name: str,
    history: list,
    duration_seconds: int,
    frame_count: int,
    last_reaction: str,
) -> bool:
    """Write role-scoped memories shared by Companion and normal PonyChat chat."""
    try:
        from ..db.memory_dao import add_memory
        from ..memory.extractor import do_extract as _do_extract

        memory_content, importance, preferences = await _generate_companion_memory_summary(
            char_name=char_name,
            history=history,
            duration_seconds=duration_seconds,
            frame_count=frame_count,
            username=username,
        )

        if not memory_content:
            # LLM 失败兜底：保留统计信息，重要度按时长简单估算
            duration_min = max(1, duration_seconds // 60)
            user_label = username or "用户"
            activity_desc = f"分析了 {frame_count} 张截图" if frame_count > 0 else "语音/文字对话"
            memory_content = (
                f"和{user_label}一起聊了约 {duration_min} 分钟"
                f"（{activity_desc}）。"
            )
            if last_reaction:
                memory_content += f"最后{char_name}说：{last_reaction}"
            # 兜底重要度：按时长简单估算
            importance = 4
            if duration_min >= 5:
                importance = 5
            if duration_min >= 15:
                importance = 6
            if duration_min >= 30:
                importance = 7
            preferences = []

        await add_memory(
            username=username,
            character_id=character_id,
            memory_type="activity",
            content=memory_content,
            importance=importance,
        )
        logger.info(f"🎮 [Companion/memory] 陪玩记忆已写入 (importance={importance}): {memory_content[:60]}…")

        # 将提取到的用户偏好单独写入 preference 类型记忆（importance=8，高优先级召回）
        for pref in preferences:
            await add_memory(
                username=username,
                character_id=character_id,
                memory_type="preference",
                content=pref,
                importance=8,
            )
            logger.info(f"🎮 [Companion/memory] 用户偏好已写入: {pref}")

        # 补充提取 episode / relationship 类型记忆
        # activity 和 preference 已由上方专用摘要处理，这里只补充两种通用类型
        if history:
            ep_written = await _do_extract(
                username=username,
                character_id=character_id,
                messages=history,
                types=["episode", "relationship"],
                source="companion",
            )
            if ep_written:
                logger.info(f"🎮 [Companion/memory] 补充提取 episode/relationship {ep_written} 条")
        return True

    except Exception as e:
        logger.warning(f"[Companion/end] 写记忆失败: {e}")
        return False


# ── POST /api/companion/end（结束会话） ─────────────────────────────────────────

class EndRequest(BaseModel):
    character_id: str
    username: str
    duration_seconds: int = 0


@router.post("/api/companion/end")
async def end_companion(
    body: EndRequest,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """
    陪玩结束时调用：
    1. 清理服务端会话状态
    2. 保存完整对话记录到 companion_sessions 表
    3. 写入 activity 类型记忆（供主动消息追问"那局赢了吗？"）
    """
    auth_username = await _verify(x_chat_auth)
    if not auth_username or auth_username != body.username:
        return {"status": "error", "message": "unauthorized"}

    sess_key = _session_key(body.username, body.character_id)
    session = _companion_sessions.pop(sess_key, None)

    has_frames = session and session["frame_count"] > 0
    has_messages = session and bool(session.get("display_messages"))
    if not session or (not has_frames and not has_messages):
        return {"status": "ok", "message": "no_session"}

    frame_count = session["frame_count"]
    last_reaction = session["last_reaction"]
    display_messages = session.get("display_messages", [])
    started_at = session.get("start_iso", datetime.now().isoformat())

    # 加载角色名（用于展示）
    char_row = await _load_character_row(body.username, body.character_id)
    char_name = char_row["name"] if char_row else "角色"

    # ── 1. 保存会话历史到 DB ──────────────────────────────────────────────────
    session_id = str(uuid.uuid4())
    try:
        db = get_database()
        conn = await db.acquire()
        try:
            async with conn.execute(
                "SELECT id FROM users WHERE username = ? LIMIT 1", (body.username,)
            ) as cur:
                uid_row = await cur.fetchone()
            if uid_row:
                user_id = uid_row[0]
                await conn.execute(
                    """INSERT INTO companion_sessions
                       (id, user_id, character_id, character_name, started_at,
                        duration_seconds, frame_count, messages)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        user_id,
                        body.character_id,
                        char_name,
                        started_at,
                        body.duration_seconds,
                        frame_count,
                        json.dumps(display_messages, ensure_ascii=False),
                    ),
                )
                await conn.commit()
                logger.info(
                    f"🎮 [Companion/end] 会话已写入 DB: {session_id[:8]}... "
                    f"({frame_count} 帧, {body.duration_seconds}s)"
                )
        finally:
            await db.release(conn)
    except Exception as e:
        logger.warning(f"[Companion/end] 写入 DB 失败: {e}")

    # ── 2. 同步确认写入统一角色记忆 ───────────────────────────────────────────
    # 身份切换必须等旧角色记忆落库后才能完成，避免用户马上回到普通聊天时
    # 看不到刚才在 Companion 中共同经历的内容。
    history = session.get("history", [])
    memory_persisted = True
    if history:
        memory_persisted = await _write_companion_memory(
            username=body.username,
            character_id=body.character_id,
            char_name=char_name,
            history=history,
            duration_seconds=body.duration_seconds,
            frame_count=frame_count,
            last_reaction=last_reaction,
        )

    return {
        "status": "ok" if memory_persisted else "partial",
        "session_id": session_id,
        "memory_persisted": memory_persisted,
    }


# ── GET /api/companion/sessions（会话列表） ─────────────────────────────────────

@router.get("/api/companion/sessions")
async def get_companion_sessions(
    username: str,
    character_id: str,
    limit: int = 50,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """返回该角色的陪玩历史列表（不含消息正文，仅摘要）。"""
    auth_username = await _verify(x_chat_auth)
    if not auth_username:
        return {"status": "error", "message": "unauthorized"}

    db = get_database()
    conn = await db.acquire()
    try:
        async with conn.execute(
            "SELECT id FROM users WHERE username = ? LIMIT 1", (username,)
        ) as cur:
            uid_row = await cur.fetchone()
        if not uid_row:
            return {"status": "ok", "sessions": []}
        user_id = uid_row[0]

        async with conn.execute(
            """SELECT id, character_name, started_at, ended_at,
                      duration_seconds, frame_count,
                      json_array_length(messages) AS msg_count
               FROM companion_sessions
               WHERE user_id = ? AND character_id = ?
               ORDER BY ended_at DESC
               LIMIT ?""",
            (user_id, character_id, limit),
        ) as cur:
            rows = await cur.fetchall()

        sessions = [
            {
                "id": r[0],
                "character_name": r[1],
                "started_at": r[2],
                "ended_at": r[3],
                "duration_seconds": r[4],
                "frame_count": r[5],
                "message_count": r[6] or 0,
            }
            for r in rows
        ]
        return {"status": "ok", "sessions": sessions}
    except Exception as e:
        logger.warning(f"[Companion/sessions] 查询失败: {e}")
        return {"status": "error", "sessions": []}
    finally:
        await db.release(conn)


@router.get("/api/companion/sessions/{session_id}/messages")
async def get_companion_session_messages(
    session_id: str,
    username: str,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """返回指定陪玩会话的完整消息列表。"""
    auth_username = await _verify(x_chat_auth)
    if not auth_username:
        return {"status": "error", "message": "unauthorized"}

    db = get_database()
    conn = await db.acquire()
    try:
        async with conn.execute(
            "SELECT id FROM users WHERE username = ? LIMIT 1", (username,)
        ) as cur:
            uid_row = await cur.fetchone()
        if not uid_row:
            return {"status": "error", "message": "user_not_found"}
        user_id = uid_row[0]

        async with conn.execute(
            "SELECT messages FROM companion_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return {"status": "error", "message": "session_not_found"}

        messages = json.loads(row[0]) if row[0] else []
        return {"status": "ok", "messages": messages}
    except Exception as e:
        logger.warning(f"[Companion/messages] 查询失败: {e}")
        return {"status": "error", "messages": []}
    finally:
        await db.release(conn)


@router.delete("/api/companion/sessions/{session_id}")
async def delete_companion_session(
    session_id: str,
    username: str,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """删除指定陪玩会话记录。"""
    auth_username = await _verify(x_chat_auth)
    if not auth_username:
        return {"status": "error", "message": "unauthorized"}

    db = get_database()
    conn = await db.acquire()
    try:
        async with conn.execute(
            "SELECT id FROM users WHERE username = ? LIMIT 1", (username,)
        ) as cur:
            uid_row = await cur.fetchone()
        if not uid_row:
            return {"status": "error", "message": "user_not_found"}
        user_id = uid_row[0]
        await conn.execute(
            "DELETE FROM companion_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
        await conn.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.warning(f"[Companion/delete] 失败: {e}")
        return {"status": "error"}
    finally:
        await db.release(conn)


# ── 启动扫描：批量生成缺失/过期的精简版 Prompt ────────────────────────────────

async def companion_prompt_warmup() -> None:
    """
    服务启动时调用：扫描所有 prompt > 2000 字且精简版缺失或已过期的角色，
    逐个排队生成 companion_prompt，每次生成间隔 3 秒避免 API 过载。
    """
    if not COMPANION_SLIM_PROMPT_ENABLED:
        return
    logger.info("[Companion] 开始扫描需要生成精简 Prompt 的角色……")
    db = get_database()
    await db.init()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            # prompt 列是角色设定的权威来源；characters.data 不再保存冗余 prompt。
            async with conn.execute(
                """SELECT c.id, c.data, c.name, c.prompt, c.companion_prompt,
                          c.companion_prompt_updated_at, c.updated_at
                   FROM characters c
                   WHERE COALESCE(c.is_hidden, 0) = 0
                     AND length(COALESCE(c.prompt, '')) > 2000"""
            ) as cur:
                rows = await cur.fetchall()
    except Exception as e:
        logger.warning(f"[Companion] 扫描角色失败: {e}")
        return

    pending = []
    for r in rows:
        char_id, data_json, name, db_prompt, companion_prompt, cp_updated_at, updated_at = r
        try:
            char_data = json.loads(data_json) if data_json else {}
        except Exception:
            continue
        full_prompt = (db_prompt or "").strip()
        if len(full_prompt) <= 2000:
            continue
        row_dict = {
            "id": char_id,
            "name": char_data.get("name") or name or "角色",
            "full_prompt": full_prompt,
            "companion_prompt": companion_prompt,
            "companion_prompt_updated_at": cp_updated_at,
            "updated_at": updated_at,
        }
        if _is_companion_prompt_stale(row_dict):
            pending.append(row_dict)

    if not pending:
        logger.info("[Companion] 所有角色精简 Prompt 均已是最新，无需生成")
        return

    logger.info(f"[Companion] 共 {len(pending)} 个角色需要生成/更新精简 Prompt，开始排队……")
    for i, row_dict in enumerate(pending):
        try:
            await _generate_and_save_companion_prompt(
                character_id=row_dict["id"],
                full_prompt=row_dict["full_prompt"],
                char_name=row_dict["name"],
            )
            logger.info(
                f"[Companion] [{i+1}/{len(pending)}] "
                f"角色 {row_dict['id'][:8]}... 精简 Prompt 生成完毕"
            )
        except Exception as e:
            logger.warning(
                f"[Companion] [{i+1}/{len(pending)}] "
                f"角色 {row_dict['id'][:8]}... 生成失败: {e}"
            )
        # 每次生成后等待 3 秒，避免密集调用 API
        if i < len(pending) - 1:
            await asyncio.sleep(3)

    logger.info("[Companion] 精简 Prompt 批量生成完成")


# ── 调试帧存图 ───────────────────────────────────────────────────────────────

def _save_frame_debug(username: str, image_base64: str) -> None:
    """
    将陪玩截图以 JPEG 形式落盘到 var/chatlogs/frame_debug/{username}/ 供离线调试。
    文件名为毫秒级 Unix 时间戳。
    """
    if not image_base64:
        return
    try:
        import pathlib as _pathlib
        debug_dir = _pathlib.Path(_CHAT_LOGS_DIR) / "frame_debug" / username
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts_ms = int(time.time() * 1000)
        file_path = debug_dir / f"{ts_ms}.jpg"
        file_path.write_bytes(base64.b64decode(image_base64))
        logger.info(f"[Companion/frame_debug] 已存帧 {file_path.name} ({len(image_base64) * 3 // 4} bytes)")
    except Exception as e:
        logger.warning(f"[Companion/frame_debug] 存帧失败: {e}")


# ── 日志工具 ─────────────────────────────────────────────────────────────────

def _write_companion_log(
    username: str,
    char_name: Optional[str],
    request_payload: dict,
    raw_response: str,
    reaction: str = "",
    error: str = "",
) -> None:
    try:
        now = datetime.now()
        ts = now.strftime("%Y%m%d_%H%M%S_") + f"{now.microsecond // 1000:03d}"
        filename = f"{ts}_companion_{username}.js"
        log_dir = os.path.normpath(os.path.join(
            _CHAT_LOGS_DIR,
            now.strftime("%Y-%m-%d"),
            now.strftime("%H"),
        ))
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, filename)

        safe_messages = []
        for msg in request_payload.get("messages", []):
            content = msg.get("content")
            if isinstance(content, list):
                content = [
                    {"type": p["type"], "text": p.get("text", "")} if p["type"] == "text"
                    else {"type": p["type"], "image_url": "<omitted>"}
                    for p in content
                ]
            safe_messages.append({**msg, "content": content})

        safe_payload = {**request_payload, "messages": safe_messages}

        meta = {
            "timestamp": now.isoformat(),
            "username": username,
            "character_name": char_name or "",
            "model": request_payload.get("model", _MINI_MODEL["model_name"]),
            "reaction": reaction,
            "error": error,
        }
        header = json.dumps(meta, ensure_ascii=False, indent=4)
        req_str = json.dumps(safe_payload, ensure_ascii=False, indent=4)
        # 将 JSON 字符串值中的转义序列还原为可读字符，让 IDE 可以正确换行显示
        req_str = req_str.replace("\\n", "\n").replace("\\t", "\t")
        safe_req = req_str.replace("`", "\\`").replace("${", "\\${")
        safe_raw = raw_response.replace("`", "\\`").replace("${", "\\${")
        content_str = (
            f"const debug_log = {{\n"
            f"    ...{header[1:-1]},\n"
            f'    "request_payload": `{safe_req}`,\n'
            f'    "raw_response": `{safe_raw}`\n'
            f"}};\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(content_str)
    except Exception as e:
        logger.warning(f"[Companion] 写日志失败: {e}")


def _write_companion_sub_log(
    mode: str,
    username: str,
    request_payload: dict,
    raw_response: str,
    result: str = "",
    error: str = "",
    character_name: str = "",
) -> None:
    """写入 companion 子任务（图片描述、记忆生成、agent决策等）的 ChatLogs 日志。"""
    try:
        now = datetime.now()
        ts = now.strftime("%Y%m%d_%H%M%S_") + f"{now.microsecond // 1000:03d}"
        filename = f"{ts}_companion_{mode}_{username}.js"
        log_dir = os.path.normpath(os.path.join(
            _CHAT_LOGS_DIR,
            now.strftime("%Y-%m-%d"),
            now.strftime("%H"),
        ))
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, filename)

        safe_messages = []
        for msg in request_payload.get("messages", []):
            content = msg.get("content")
            if isinstance(content, list):
                content = [
                    {"type": p.get("type"), "text": p.get("text", "")} if p.get("type") == "text"
                    else {"type": p.get("type"), "image_url": "<omitted>"}
                    for p in content
                ]
            safe_messages.append({**msg, "content": content})

        safe_payload = {**request_payload, "messages": safe_messages}

        meta = {
            "timestamp": now.isoformat(),
            "username": username,
            "character_name": character_name,
            "mode": f"companion_{mode}",
            "model": request_payload.get("model", _MINI_MODEL["model_name"]),
            "result": result,
            "error": error,
        }
        header = json.dumps(meta, ensure_ascii=False, indent=4)
        req_str = json.dumps(safe_payload, ensure_ascii=False, indent=4)
        # 将 JSON 字符串值中的转义序列还原为可读字符，让 IDE 可以正确换行显示
        req_str = req_str.replace("\\n", "\n").replace("\\t", "\t")
        safe_req = req_str.replace("`", "\\`").replace("${", "\\${")
        safe_raw = raw_response.replace("`", "\\`").replace("${", "\\${")
        content_str = (
            f"const debug_log = {{\n"
            f"    ...{header[1:-1]},\n"
            f'    "request_payload": `{safe_req}`,\n'
            f'    "raw_response": `{safe_raw}`\n'
            f"}};\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(content_str)
    except Exception as e:
        logger.warning(f"[Companion] 写子日志失败({mode}): {e}")
