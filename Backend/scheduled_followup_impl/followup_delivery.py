

def _format_subject_integrity_context(task: dict[str, Any]) -> str:
    meta = _planner_json(task)
    candidates: list[Any] = []
    if isinstance(meta.get("scheduled_followup"), dict):
        candidates.append(meta.get("scheduled_followup"))
    step4 = meta.get("step4_next_turn_prep_decision")
    if isinstance(step4, dict) and isinstance(step4.get("scheduled_followup"), dict):
        candidates.append(step4.get("scheduled_followup"))
    candidates.append(task)
    for item in candidates:
        if not isinstance(item, dict):
            continue
        subject = item.get("subject_integrity")
        if not isinstance(subject, dict):
            continue
        evaluated = str(subject.get("evaluated_subject") or "").strip()
        check = str(subject.get("seed_subject_check") or "").strip()
        source = str(subject.get("source_character_action") or subject.get("source_user_action") or "").strip()
        if not (evaluated or check or source):
            continue
        lines = ["【主动任务主体核对｜系统内部】"]
        if evaluated:
            lines.append(f"被评价主体：{evaluated}")
        if source:
            lines.append(f"证据：{source}")
        if check:
            lines.append(check)
        lines.append("本次主动消息必须沿用这个主体归属；不得把用户被夸/被关心/被保护改写成角色自己被夸、被关心或被保护。")
        return "\n".join(lines)
    return ""


def _build_due_trigger_text(task: dict[str, Any]) -> str:
    time_context = _format_agreed_task_time_context(task)
    passive_task_context = _format_passive_task_intent_context(task)
    subject_integrity_context = _format_subject_integrity_context(task)
    seed = str(task.get("seed") or "").strip()
    seed_for_generation = _normalize_passive_task_summary(seed) if passive_task_context else seed
    reason = str(task.get("reason") or "").strip()
    parts = [
        "【内部触发事件】",
        "用户未发送新消息；本段为内部触发说明，回复时不得复述或提到。",
        "这是角色自然发出下一条普通聊天消息的机会。",
        "请像普通对话一样，仅根据最近可见对话、角色设定、记忆和当前事实生成角色消息。",
        "如果上一条角色消息以问题、邀请、确认或等待用户表态结尾，表示用户尚未回答；禁止替用户回答，禁止把角色自己的问题当成已经得到回应。",
        "上一条可见 assistant 的问句、邀请或猜测来源于角色自己；本次主动消息避开直接回答这些问句，也不得说成“你刚才问我/你说想要/你同意了”。",
        "如果要续接角色自己的问题，只能以角色自我补充、自我缓和、补一句新想法、承认自己刚才有点害羞或让用户不用急着回答的方式继续。",
        "用户没回可以被角色轻轻理解成默认继续当前氛围，但这不是复述上一条的理由。",
        "本次主动消息必须比上一条 assistant 多一个新拍子：可新增一个轻问题、换一个低压力话题、补一个角色自己的新想法、推进一个小决定、给出新选择，或把氛围转向下一步；禁止把上一条换句话重复一遍。",
        "新拍子必须承担明确功能：提出新选择、补充新信息、改变角色自己的下一步动作、设置一个小约定、转入新阶段或给用户新的低压力台阶；只重复已完成事实、等待语气、紧张期待、耳朵/尾巴/呼吸等同类小动作，不算新拍子。",
        "上一条已经说过的完成事实（如已经戴好、已经看不见、已经躺下/到达/拿到、已经在等）不得再作为本条开头或主体；必要时只能极短带过，正文重点必须落在新的功能性推进上。",
        "如果上一条 assistant 让用户在故事/经历/话题之间选择，本次主动消息不得原样重复同一组选择，也不得催问“还没想好听哪个故事吗”。先检查最近可见对话：已经讲过、展开过或反复提出的故事主题只能作为历史背景；若要继续叙事，必须直接进入未展开的新经历、第二次/后来发生的事、角色自己的新细节，或回到当前场景动作/亲密接触。",
        "如果最近一条真实 user 是明确问题或调侃追问，而上一条 assistant 没有回答问题、只沿旧问候/天气/早餐/生活安排/泛亲密动作滑走，本次主动消息不得继续旧话题自转。若确实要发送，优先补答或承认刚才跑偏，再回到用户刚问的点；早安、阳光、早餐只能作为回答后的轻点缀。",
        "若想不到有意义的新拍子，宁可不发送，也不要复述上一条。",
        "本次主动消息只能轻轻补充、等待、换一个低压力小动作或延续陪伴感；不能编造用户的喜好、同意、回答或新动作。",
        "若上一条 assistant 只是泛安慰（如'辛苦了/我在/泡茶/陪着你/靠着/画星星'）而未锚定用户前文具体事实，本次主动消息必须补一个锚定用户前文事实的新角度、轻判断或低压力安排；禁止再发一轮泛安慰。"
        "中文日常聊天很少使用长横线；插入语、突然想起、揭晓惊喜或情绪转弯，优先写成逗号、句号、省略号、换行、重复字或感叹号的聊天节奏。",
        "例外：若上一条角色是在让用户猜一个角色自己掌握的信息（如礼物颜色、藏了什么、准备了什么），角色可以没忍住自己揭晓答案；但仍不得声称用户猜对、喜欢、同意或已经回答。",
    ]
    if time_context:
        parts.append(time_context)
    if passive_task_context:
        parts.append(passive_task_context)
    if subject_integrity_context:
        parts.append(subject_integrity_context)
    if seed_for_generation:
        parts.append(
            "【本次主动续接内部意图草稿】\n"
            f"{seed_for_generation[:600]}\n"
            "这段草稿只提供角色下一拍方向；它不代表用户回答，也不新增事实；"
            "若它与最近可见对话冲突，必须以最近可见对话为准；"
            "执行草稿时必须加入新信息、新角度或新问题，不能只复述上一条；"
            "若本次是用户约定/手动创建的被动任务，必须优先遵守上面的被动任务语义主体。"
        )
    if reason:
        parts.append(f"内部原因：{reason[:300]}")
    return "\n".join(parts)


def _join_nonempty_context_parts(*parts: str) -> str:
    return "\n\n".join(str(part or "").strip() for part in parts if str(part or "").strip())


def _scheduled_trigger_type(task: dict[str, Any]) -> str:
    return str(task.get("reason") or "scheduled_followup").strip() or "scheduled_followup"


def _scheduled_proactive_debug_params(
    task: dict[str, Any],
    *,
    request_tokens: Optional[int] = None,
    pipeline: str = "normal_proactive",
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "trigger_type": _scheduled_trigger_type(task),
        "trigger_id": task.get("id"),
        "pipeline": pipeline,
        "conversation_id": task.get("conversation_id"),
    }
    if request_tokens is not None:
        params["request_tokens_estimate"] = request_tokens
    return params


def _normal_proactive_fact_priority_context(trigger_type: str) -> str:
    return (
        "【普通回复主动触发上下文｜系统内部】\n"
        f"本轮是 normal assistant reply 的主动触发方式，trigger_type={trigger_type or 'scheduled_followup'}。"
        "用户没有新可见消息；最后一条 user 是内部触发说明，不是用户原话，也不得在正文中复述。\n"
        "事实优先级：最近可见对话、当前会话上下文记忆、近期临时群聊见闻、Step 2 fact_judgement 和 scene_anchor "
        "> 更早的长期记忆、旧摘要、旧计划、旧意图草稿。\n"
        "如果近期材料显示某个事件已经完成，旧记忆里的“仍在进行/准备明天去做/之后要做”的计划必须降级为历史背景或 forbidden_uses；"
        "不得让时间线倒退到已完成事件之前。"
    )


async def _load_scheduled_normal_context_inputs(
    request: ChatRequest,
    *,
    recent_chat: list[dict[str, Any]],
) -> dict[str, Any]:
    username = request.username or ""
    character_id = request.character_id or ""
    conversation_id = request.conversation_id or ""
    if not (username and character_id):
        return {
            "context_memory": "",
            "long_memory": "",
            "guest_group_memory": "",
            "context_memory_slim": "",
            "long_memory_slim": "",
            "guest_group_memory_slim": "",
        }
    try:
        from .chat_modules.context_memory import format_context_memory_for_prompt, load_context_memory
        from .chat_modules.normal_speaker import load_recent_guest_group_memory_block
        from .chat_modules.service_impl.normal_reply_debounce import _compact_normal_stage_context
        from .db.memory_dao import recall_memories_layered, format_layered_memories_for_prompt
        from .user_identity import USER_MEMORY_PLACEHOLDER, replace_user_placeholder
    except Exception as exc:
        logger.debug("[ScheduledFollowup] normal context helper unavailable: %s", exc)
        return {
            "context_memory": "",
            "long_memory": "",
            "guest_group_memory": "",
            "context_memory_slim": "",
            "long_memory_slim": "",
            "guest_group_memory_slim": "",
        }

    display_name = (getattr(request, "_display_name", None) or username or "用户").strip() or "用户"
    context_memory = ""
    long_memory = ""
    guest_group_memory = ""

    if getattr(request, "memory_enabled", True) is not False and conversation_id:
        try:
            mem = await load_context_memory(username, character_id, conversation_id, get_database())
            text = format_context_memory_for_prompt(mem or {})
            if (text or "").strip():
                context_memory = (
                    f"【记忆指代说明】以下上下文记忆中的 {USER_MEMORY_PLACEHOLDER}、USER 或“用户”均指当前用户「{display_name}」。\n"
                    "【当前会话上下文记忆（供意图识别保持连续性，不得复述给用户）】\n"
                    + replace_user_placeholder(text, display_name)[:6000]
                )
        except Exception as exc:
            logger.debug("[ScheduledFollowup] load normal context memory failed: %s", exc)

        try:
            latest_trigger_text = ""
            for item in reversed(recent_chat or []):
                if str(item.get("role") or "") == "user":
                    latest_trigger_text = str(item.get("content") or "")
                    break
            layers = await recall_memories_layered(
                username=username,
                character_id=character_id,
                current_query=latest_trigger_text,
            )
            text = format_layered_memories_for_prompt(
                **layers,
                suppress_d_layer=False,
                compact_cross_chat_fragments=True,
                fragments_first=True,
            )
            if (text or "").strip():
                long_memory = (
                    f"【记忆指代说明】以下跨会话长期记忆中的 {USER_MEMORY_PLACEHOLDER}、USER 或“用户”均指当前用户「{display_name}」。\n"
                    "【意图识别可参考的跨会话长期记忆】\n"
                    "这些是角色大脑里的长期记忆。只可作为背景、过去经历、偏好证据或较早计划；"
                    "若与近期可见对话、上下文记忆或临时群聊见闻冲突，必须降级为 history_facts/forbidden_uses。\n"
                    + replace_user_placeholder(text, display_name)[:9000]
                )
        except Exception as exc:
            logger.debug("[ScheduledFollowup] load layered long memory failed: %s", exc)

        try:
            guest_group_memory = await load_recent_guest_group_memory_block(username, character_id, limit=4)
        except Exception as exc:
            logger.debug("[ScheduledFollowup] load guest group memory failed: %s", exc)

    return {
        "context_memory": context_memory,
        "long_memory": long_memory,
        "guest_group_memory": guest_group_memory,
        "context_memory_slim": _compact_normal_stage_context(context_memory, limit=2600),
        "long_memory_slim": _compact_normal_stage_context(long_memory, limit=1800),
        "guest_group_memory_slim": _compact_normal_stage_context(guest_group_memory, limit=1800),
    }


def _scheduled_voice_inertia_prompt(recent_messages: list[dict[str, Any]]) -> str:
    try:
        from .chat_modules.voice_messages import chat_voice_service_enabled

        if not chat_voice_service_enabled():
            return ""
    except Exception as exc:
        logger.debug("[ScheduledFollowup] voice inertia switch check failed: %s", exc)
        return ""
    if not _latest_assistant_was_voice(recent_messages):
        return ""
    return (
        "【上一轮语音回复惯性｜系统内部】\n"
        "最近有效角色承载方式是语音消息；如果中间只有 App 内置详细描写快捷消息产生的一次性文本描写，不视为用户切换到文本。用户没有明确要求切换到文本，所以本次主动续接必须继续按语音消息写。\n"
        "最终输出只写角色会直接说出口的可朗读台词：不要写括号动作、括号心理、舞台说明、旁白说明、markdown、列表或补充注释。\n"
        "不要使用全角/半角括号包住动作或语气说明；如果用户没有明确要求括号说明，就把动作感转化为语气和措辞。\n"
        "文本内容本身仍保留正常聊天气泡正文，但它会进入 TTS；因此不要输出任何不该被朗读的说明。"
    )


async def _inject_context_memory_for_scheduled(
    request: ChatRequest,
    messages: list[dict],
) -> list[dict]:
    username = request.username or ""
    character_id = request.character_id or ""
    conversation_id = request.conversation_id or ""
    if not (username and character_id and conversation_id):
        return messages
    try:
        from .chat_modules.character import load_character_from_db
        from .chat_modules.context_memory import (
            format_context_memory_for_prompt,
            inject_context_memory_into_messages,
            load_context_memory,
        )
        from .user_identity import USER_MEMORY_PLACEHOLDER, replace_user_placeholder

        ctx_mem = await load_context_memory(username, character_id, conversation_id, get_database())
        all_msgs = list(messages)
        sys_msgs = [m for m in all_msgs if m.get("role") == "system"]
        ua_msgs = [m for m in all_msgs if m.get("role") in ("user", "assistant")]
        last_user_pos = next(
            (i for i in range(len(ua_msgs) - 1, -1, -1) if ua_msgs[i].get("role") == "user"),
            -1,
        )
        history_turns: list[tuple[str, str]] = []
        compact_messages = all_msgs
        if last_user_pos >= 0:
            history_turns = [
                (m["role"], str(m.get("content", "")))
                for m in ua_msgs[:last_user_pos]
                if m.get("role") in ("user", "assistant")
            ]
            compact_messages = sys_msgs + [ua_msgs[last_user_pos]]

        user_label = (getattr(request, "_display_name", None) or username or "").strip() or "用户"
        char_data = load_character_from_db(username, character_id) or {}
        assistant_label = str(char_data.get("name") or "").strip() or "角色"
        ctx_text = format_context_memory_for_prompt(
            ctx_mem or {},
            recent_raw_turns=history_turns or None,
            user_label=user_label,
            assistant_label=assistant_label,
        )
        if ctx_text.strip():
            ctx_text = (
                f"【记忆指代说明】以下上下文记忆中的 {USER_MEMORY_PLACEHOLDER}、USER 或“用户”均指当前用户「{user_label}」。\n"
                + replace_user_placeholder(ctx_text, user_label)
            )
            return inject_context_memory_into_messages(list(compact_messages), ctx_text)
        return compact_messages
    except Exception as exc:
        logger.warning("[ScheduledFollowup] inject context memory failed: %s", exc)
        return messages


def _inject_sys_before_last_user(messages: list[dict], content: str) -> list[dict]:
    new_messages = list(messages)
    for i in range(len(new_messages) - 1, -1, -1):
        if isinstance(new_messages[i], dict) and new_messages[i].get("role") == "user":
            new_messages.insert(i, {"role": "system", "content": content})
            return new_messages
    new_messages.append({"role": "system", "content": content})
    return new_messages


def _build_planner_character_prompt_context(username: Optional[str], character_id: Optional[str]) -> str:
    if not username or not character_id:
        return ""
    try:
        from .chat_modules.character import load_character_from_db

        character = load_character_from_db(username, character_id) or {}
        prompt = str(character.get("prompt") or "").strip()
        if not prompt:
            return ""
        name = str(character.get("name") or character_id).strip()
        return f"角色名称：{name}\n\n{prompt}"
    except Exception as exc:
        logger.debug("[ScheduledFollowup] load planner character prompt failed: %s", exc)
        return ""


def _scheduled_memory_user_message(task: dict[str, Any]) -> str:
    seed = str(task.get("seed") or "").strip()
    if seed:
        return f"用户没有发送新消息；角色在等待一段时间后按先前安排主动续接，意图是：{seed[:300]}。"
    return "用户没有发送新消息；角色在等待一段时间后按先前安排主动续接。"


async def _append_assistant_message(task: dict[str, Any], content: str) -> list[tuple[str, str]]:
    db = get_database()
    segments = [p.strip() for p in re.split(r"\n+", (content or "").strip()) if p.strip()]
    if not segments and (content or "").strip():
        segments = [(content or "").strip()]
    if not segments:
        return []
    now = _now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await _configure_noncritical_conn(conn)
        try:
            await conn.execute("BEGIN IMMEDIATE")
            async with conn.execute(
                "SELECT status FROM scheduled_followups WHERE id=? LIMIT 1",
                (task["id"],),
            ) as cur:
                task_row = await cur.fetchone()
            is_scheduled_followup = bool(task_row)
            if not task_row:
                async with conn.execute(
                    "SELECT status FROM proactive_tasks WHERE id=? LIMIT 1",
                    (task["id"],),
                ) as cur:
                    task_row = await cur.fetchone()
            if not task_row or str(task_row[0] or "") != "processing":
                await conn.rollback()
                return []

            async with conn.execute(
                """
                SELECT message_id, sequence_number
                  FROM messages
                 WHERE conversation_id=?
                   AND deleted_at IS NULL
                 ORDER BY COALESCE(sequence_number, 0) DESC, COALESCE(timestamp, 0) DESC, rowid DESC
                 LIMIT 1
                """,
                (task["conversation_id"],),
            ) as cur:
                prev = await cur.fetchone()
            prev_id = prev[0] if prev else None
            next_seq = int(prev[1] or 0) + 1 if prev else 0
            saved_parts: list[tuple[str, str]] = []
            for idx, segment in enumerate(segments):
                message_id = generate_message_id()
                row_id = f"{task['conversation_id']}_{message_id}"
                await conn.execute(
                    """
                    INSERT INTO messages (
                        id, conversation_id, role, content, raw_content, image_url,
                        timestamp, message_id, sequence_number, previous_message_id,
                        suggestions, suggestions_status, client_id, generation_duration_ms
                    ) VALUES (?, ?, 'assistant', ?, ?, NULL, ?, ?, ?, ?, NULL, 'none', 'scheduled_followup', NULL)
                    """,
                    (row_id, task["conversation_id"], segment, segment, now + idx, message_id, next_seq + idx, prev_id),
                )
                saved_parts.append((message_id, segment))
                prev_id = message_id
            await conn.execute(
                """
                UPDATE conversations
                   SET timestamp=?, updated_at=CURRENT_TIMESTAMP
                 WHERE id=?
                """,
                (now, task["conversation_id"]),
            )
            if is_scheduled_followup:
                await conn.execute(
                    """
                    UPDATE scheduled_followups
                       SET status='sent',
                           sent_message_id=?,
                           updated_at_ms=?
                     WHERE id=? AND status='processing'
                    """,
                    (saved_parts[-1][0], now, task["id"]),
                )
            await conn.commit()
            return saved_parts
        except Exception as exc:
            await conn.rollback()
            if _is_sqlite_locked(exc):
                logger.debug("[ScheduledFollowup] append assistant skipped: database is locked")
            else:
                logger.warning("[ScheduledFollowup] append assistant failed: %s", exc)
            return []


async def _prepare_voice_for_scheduled_parts(
    task: dict[str, Any],
    message_parts: list[tuple[str, str]],
    request: Optional[ChatRequest],
) -> dict[str, dict[str, Any]]:
    if not message_parts:
        return {}
    try:
        from .chat_modules.voice_messages import prepare_voice_generation_for_messages

        planner_result = getattr(request, "_normal_planner_result", None) if isinstance(request, ChatRequest) else {}
        forced_planner = {
            **(planner_result if isinstance(planner_result, dict) else {}),
            "voice_reply": {
                **((planner_result or {}).get("voice_reply") if isinstance((planner_result or {}).get("voice_reply"), dict) else {}),
                "enabled": True,
                "reason": "scheduled_followup_inherits_previous_voice_reply",
            },
        }
        assistant_meta = [{"message_id": message_id} for message_id, _segment in message_parts]
        assistant_units = [
            {
                "type": "text",
                "content": segment,
            }
            for _message_id, segment in message_parts
        ]
        return await prepare_voice_generation_for_messages(
            username=str(task.get("username") or ""),
            character_id=str(task.get("character_id") or ""),
            conversation_id=str(task.get("conversation_id") or ""),
            assistant_meta=assistant_meta,
            assistant_units=assistant_units,
            planner_result=forced_planner,
        )
    except Exception as exc:
        logger.warning("[ScheduledFollowup] prepare inherited voice generation failed: %s", exc)
        return {}


async def _record_proactive_and_push_chat_complete(
    task: dict[str, Any],
    content: str,
    message_id: str,
    *,
    voice_result: Optional[dict[str, Any]] = None,
) -> Optional[int]:
    """Record proactive delivery for audit, then notify clients via normal chat_complete."""
    db = get_database()
    proactive_id: Optional[int] = None
    message_timestamp_ms: Optional[int] = None
    async with aiosqlite.connect(db.db_path) as conn:
        await _configure_noncritical_conn(conn)
        await conn.execute("PRAGMA foreign_keys = ON")
        async with conn.execute("SELECT id FROM users WHERE username=?", (task["username"],)) as cur:
            user = await cur.fetchone()
        if not user:
            return None
        user_id = int(user[0])
        async with conn.execute(
            """
            SELECT timestamp
              FROM messages
             WHERE conversation_id=? AND message_id=? AND role='assistant'
             LIMIT 1
            """,
            (task["conversation_id"], message_id),
        ) as cur:
            message_row = await cur.fetchone()
        if message_row:
            try:
                message_timestamp_ms = int(message_row[0] or 0) or None
            except Exception:
                message_timestamp_ms = None
        cur = await conn.execute(
            """
            INSERT INTO proactive_messages
                (user_id, character_id, trigger_type, content, message_id, is_read, read_at)
            VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            """,
            (
                user_id,
                task["character_id"],
                str(task.get("reason") or "scheduled_followup")[:80],
                content,
                message_id,
            ),
        )
        proactive_id = int(cur.lastrowid)
        await conn.commit()

    await enqueue_chat_complete(
        username=str(task["username"]),
        character_id=str(task["character_id"]),
        conversation_id=str(task["conversation_id"]),
        message_id=str(message_id),
        preview=str(content or ""),
        mode="normal",
        completed_at_ms=message_timestamp_ms or _now_ms(),
        message_count=1,
        assistant_message_ids=[str(message_id)],
        voice_state=voice_result.get("voice_state") if isinstance(voice_result, dict) else None,
        audio_transfer=voice_result.get("audio_transfer") if isinstance(voice_result, dict) else None,
    )
    return proactive_id


async def _record_proactive_audit_only(
    task: dict[str, Any],
    content: str,
    message_id: str,
) -> Optional[int]:
    """Record proactive delivery for audit; normal core already pushed chat_complete."""
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        await _configure_noncritical_conn(conn)
        await conn.execute("PRAGMA foreign_keys = ON")
        async with conn.execute("SELECT id FROM users WHERE username=?", (task["username"],)) as cur:
            user = await cur.fetchone()
        if not user:
            return None
        cur = await conn.execute(
            """
            INSERT INTO proactive_messages
                (user_id, character_id, trigger_type, content, message_id, is_read, read_at)
            VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            """,
            (
                int(user[0]),
                task["character_id"],
                str(task.get("reason") or "scheduled_followup")[:80],
                content,
                message_id,
            ),
        )
        proactive_id = int(cur.lastrowid)
        await conn.commit()
    return proactive_id


async def _finish_task(
    task_id: str,
    status: str,
    *,
    sent_message_id: Optional[str] = None,
    cancel_reason: Optional[str] = None,
) -> None:
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        await _configure_noncritical_conn(conn)
        await conn.execute(
            """
            UPDATE scheduled_followups
               SET status=?, sent_message_id=COALESCE(?, sent_message_id),
                   cancel_reason=COALESCE(?, cancel_reason), updated_at_ms=?
             WHERE id=?
            """,
            (status, sent_message_id, cancel_reason, _now_ms(), task_id),
        )
        await conn.commit()


async def _requeue_processing_followup(task_id: str) -> None:
    if not task_id:
        return
    db = get_database()
    now = _now_ms()
    async with aiosqlite.connect(db.db_path) as conn:
        await _configure_noncritical_conn(conn)
        await conn.execute(
            """
            UPDATE scheduled_followups
               SET status='pending',
                   cancel_reason=NULL,
                   updated_at_ms=?,
                   due_at_ms=CASE WHEN due_at_ms > ? THEN due_at_ms ELSE ? END
             WHERE id=?
               AND status='processing'
               AND sent_message_id IS NULL
            """,
            (now, now, now + 5000, task_id),
        )
        await conn.commit()


async def _is_task_processing(task_id: str) -> bool:
    if not task_id:
        return False
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute(
            "SELECT status FROM scheduled_followups WHERE id=? LIMIT 1",
            (task_id,),
        ) as cur:
            row = await cur.fetchone()
    return bool(row and str(row[0] or "") == "processing")


async def _cancel_pending_in_conn(
    conn: aiosqlite.Connection,
    username: str,
    character_id: str,
    conversation_id: str,
    *,
    reason: str,
) -> None:
    await conn.execute(
        """
        UPDATE scheduled_followups
           SET status='cancelled', cancel_reason=?, updated_at_ms=?
         WHERE username=? AND character_id=? AND conversation_id=?
           AND status IN ('pending', 'processing')
        """,
        (reason, _now_ms(), username, character_id, conversation_id),
    )


async def _is_consecutive_proactive_limit_reached(conversation_id: str) -> bool:
    conversation_id = str(conversation_id or "").strip()
    if not conversation_id:
        return False
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await _configure_noncritical_conn(conn)
        limit = await proactive_reply_limit_reached(conn, conversation_id)
    return bool(limit.get("reached"))


def _now_ms() -> int:
    return int(time.time() * 1000)
