

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


def _followup_interaction_contract(task: dict[str, Any]) -> str:
    chain_count = max(0, int(task.get("chain_count") or 0))
    followup_index = chain_count + 1
    if followup_index <= 1:
        continuation_mode = "share_or_one_light_opening"
        closing_shape = "open_statement_or_one_light_question"
        interaction_position = "initial_followup"
    else:
        continuation_mode = "share_or_self_action_or_topic_shift"
        closing_shape = "open_statement"
        interaction_position = "continued_silence"
    return (
        "【本次跟进交互合同｜系统内部】\n"
        f"followup_index: {followup_index}\n"
        f"interaction_position: {interaction_position}\n"
        "response_dependency: none\n"
        "message_value: self_contained\n"
        f"continuation_mode: {continuation_mode}\n"
        f"closing_shape: {closing_shape}\n"
        "请先从最近两条 assistant 中识别重复的具体名词、动作目标和对话功能，"
        "并把已经连续使用的素材写入 expression_motif_policy.blocked_motifs；"
        "proactive_seed 与 expression_policy 选择不同的语义轴。"
        "初次跟进可以留一个轻量开口；continued_silence 表示此前的主动消息也尚未得到回应，"
        "此时用角色自己的新观察、可独立完成的动作、当下决定或自然话题转弯构成完整消息。"
        "把交流余地落实在消息自足和开放结尾上，把句尾留给这条消息的新内容。"
    )


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
        _followup_interaction_contract(task),
        "请像普通对话一样，仅根据最近可见对话、角色设定、记忆和当前事实生成角色消息。",
        "如果上一条角色消息以问题、邀请、确认或等待用户表态结尾，表示用户尚未回答；禁止替用户回答，禁止把角色自己的问题当成已经得到回应。",
        "上一条可见 assistant 的问句、邀请或猜测来源于角色自己；本次主动消息避开直接回答这些问句，也不得说成“你刚才问我/你说想要/你同意了”。",
        "如果上一条角色留下了问题或邀请，本次从角色自身继续：深化此刻真实感受、自然修正刚才的语气、回应双方关系、分享当下观察，或完成一个不依赖用户表态的小动作。让这条消息即使暂时没有回应也能自然成立，并给用户留下可以随意接入的话头。过去经历、第三方事件和现成资源只在本轮事实依据明确列出时使用。",
        "用户未回复只表示暂时没有新事实；角色继续的是自己的想法、观察和行动，而不是用户尚未作出的决定。",
        "本次主动消息比上一条 assistant 多一个新拍子：可加入角色的新观察、自己完成的小动作、新决定、一个轻问题或自然话题转弯，让消息自身提供新的内容。",
        "新拍子承担明确功能：补充新信息、改变角色自己的下一步动作、设置一个小约定、转入新阶段，或让对话出现新的可接入位置；只重复已完成事实、等待语气、紧张期待、耳朵/尾巴/呼吸等同类小动作，不算新拍子。",
        "上一条已经说过的完成事实（如已经戴好、已经看不见、已经躺下/到达/拿到、已经在等）不得再作为本条开头或主体；必要时只能极短带过，正文重点必须落在新的功能性推进上。",
        "如果上一条 assistant 让用户在故事/经历/话题之间选择，本次主动消息不重复同一组选择，也不催问。先检查最近可见对话：有明确证据而尚未展开的经历可以继续；没有对应依据时，就回到角色当前感受、双方关系、当前场景动作、亲密接触或未来共同计划，让新鲜感来自观察和情绪深化，而不是临时补一段旧事。",
        "如果最近一条真实 user 是明确问题或调侃追问，而上一条 assistant 没有回答问题、只沿旧问候/天气/早餐/生活安排/泛亲密动作滑走，本次主动消息不得继续旧话题自转。若确实要发送，优先补答或承认刚才跑偏，再回到用户刚问的点；早安、阳光、早餐只能作为回答后的轻点缀。",
        "若想不到有意义的新拍子，宁可不发送，也不要复述上一条。",
        "本次主动消息优先把角色自己的观察、想法、决定或可独立完成的小动作写完整；用户的喜好、同意、回答和新动作仍保持未知。",
        "最近由用户上传、发送、展示或转发的图片、表情包、文件和文字片段仍是用户提供的内容；除非最近真实对话明确角色此前拥有或保存它，主动消息只能回应用户发来的内容，不能说成角色收藏、角色手机里还有、角色偷偷存下或角色曾把它发给用户。",
        "主动消息需要的新拍子可以是角色此刻新产生的想法、态度、决定或下一步动作；所谓补充新信息不等于补写来历。附件来源、第三方旧事、群聊传播、醉酒/生病/事故状态、见证过程和具体时间线必须有最近真实对话、已筛选记忆或场景事实支持；没有证据时就留在当前反应和当下推进上。",
        "给第三方或过去补具体情节之前，先确认能指出它来自哪条已有对话、记忆或角色主页明确事实；角色的一般性格与朋友关系不等于某次旧事发生过。没有来源时，用角色当前看到的细节、即时感受、联想、决定或接下来想做的小事形成新拍子。",
        "接下来想做的小事若依赖照片、手机内容、收藏、礼物、食物、成品或道具，也要先有它当前存在且由角色掌握的证据；没有证据时写成未来设想、共同讨论或无需现成物品的当下回应。",
        "由于用户没有发送新事实，本次默认外部事实增量为零：新拍子优先来自角色此刻的主观反应、对现有内容的新理解、关系中的当前感受、未来设想或共同讨论。只有最近可见对话、已筛选记忆或场景事实明确给出时，才补过去事件、第三方具体行为或角色现成资源。",
        "若上一条 assistant 只是泛安慰（如'辛苦了/我在/泡茶/陪着你/靠着/画星星'）而未锚定用户前文具体事实，本次主动消息补一个锚定用户前文事实的新角度、轻判断或具体安排，让内容自然向前一步。"
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
            "草稿中的写作属性只决定消息结构；正文落在具体的新信息、新角度、角色动作或决定上；"
            "执行草稿时必须加入新信息、新角度或新问题，不能只复述上一条；"
            "若本次是用户约定/手动创建的被动任务，必须优先遵守上面的被动任务语义主体。"
        )
    if reason and passive_task_context:
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
        "Step 1 的 proactive_seed、expression_policy、literal_reply_text 和主动意图草稿都只是写作计划，不属于上述事实来源；其中新增的附件来源、媒体所有权、角色收藏/设备内容、第三方经历、群聊传播、醉酒/生病/事故状态或具体时间线必须由最近可见对话或已筛选证据另行支持，否则应进入 misleading_sources/forbidden_inferences/uncertainty_points，不能进入 available_facts、subject_boundaries 或 writing_guidance。\n"
        "用户最近发送、上传、展示或转发的图片、表情包、文件和文字片段默认由用户提供；没有独立证据时，不得改写为角色此前收藏、保存在角色手机中或由角色掌握来源。\n"
        "请逐项核对计划里所有过去式、第三方行为和媒体传播陈述的来源；无法对应到独立证据的原意要进入 misleading_sources/forbidden_inferences，并让 writing_guidance 改用当前观察、感受、联想、决定或下一步动作。最近 assistant 首次说出的无依据旧事只能证明角色这样说过，不能反过来成为该旧事真实发生的证据。\n"
        "照片、视频、聊天记录、手机内容、收藏、礼物、食物、成品和道具等可立即展示或使用的资源也要逐项找独立证据；没有证据时进入 action_feasibility.unsupported_current_items，writing_guidance 采用未来设想或不依赖现成资源的当下推进。\n"
        "本轮没有新用户消息，默认外部事实增量为零；如果 Step 1 的 fact_basis=[]，其计划中新增的过去事件、第三方具体行为和角色现成资源必须全部降级，writing_guidance 只能使用已核验可用事实以及当前主观反应、未来设想或共同讨论。fact_basis 非空时仍需逐条对照真实证据，来源标签本身不算证据。\n"
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
                    "记忆正文只提供事实，不作为表达方式依据：不得复用其中的用词、句式、比喻、语气或口癖。\n"
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
            from .chat_modules.normal_lifecycle import scheduled_character_is_dead_on_connection
            if await scheduled_character_is_dead_on_connection(conn, task):
                await conn.rollback()
                return []
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
