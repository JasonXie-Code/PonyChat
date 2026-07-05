

def _last_assistant_reply_language(
    recent_messages: Optional[List[dict]],
    *,
    current_speaker_character_id: str = "",
    main_character_id: str = "",
) -> str:
    for msg in _iter_effective_assistant_messages(
        recent_messages,
        current_speaker_character_id=current_speaker_character_id,
        main_character_id=main_character_id,
    ):
        for text in _assistant_reply_language_text_candidates(msg):
            language = _detect_reply_language_from_text(text)
            if language:
                return language
    return ""


def _reply_language_context_block(
    recent_messages: Optional[List[dict]],
    *,
    current_speaker_character_id: str = "",
    main_character_id: str = "",
) -> str:
    last_language = _last_assistant_reply_language(
        recent_messages,
        current_speaker_character_id=current_speaker_character_id,
        main_character_id=main_character_id,
    )
    if not last_language:
        speaker_id = str(current_speaker_character_id or "").strip()
        main_id = str(main_character_id or "").strip()
        if speaker_id and main_id and speaker_id != main_id:
            return "\n".join([
                "【被 @ 角色回复语言默认（系统内部）】",
                "当前被 @ 发言者在这个主会话里还没有自己的有效回复语言记录。",
                "除非用户本轮明确要求 English、中文、Japanese、Russian 或其他回复语言，本轮默认使用 Chinese；不要继承主会话角色或其他被 @ 角色的语言惯性。",
                "这个默认只属于“当前主会话里的当前发言者”，不是该角色自己的私聊全局设置。",
            ])
        return ""
    return "\n".join([
        "【上一轮回复语言状态（系统内部）】",
        f"上一条可见角色消息的输出语言：{last_language}。",
        "这是角色输出语言，不是用户输入语言。若用户本轮没有明确要求切换回复语言，必须延续上一条角色输出语言；用户用中文提问、换话题、问题很短、没有再次说“英文/English”，都不等于要求角色切回中文。",
        "App 内置心理/身体/画面详细描写快捷消息只是一次性查看，不是语言切换；即使连续多轮使用这些描写快捷消息，每个快捷回合也必须沿用第一次描写快捷消息前的回复语言，且不会刷新后续语言惯性。「（请推进剧情发展）」同样不是语言切换指令。",
        "请把该状态写入 reply_language 字段，并由 reply_language 决定主回复/语音回复的输出语言。",
    ])


def _msg_text_for_guidance(msg: Any, limit: int = 220) -> str:
    if not isinstance(msg, dict):
        return ""
    text = msg.get("content")
    if not isinstance(text, str):
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit] + "..."
    return text


def _msg_phrase_signature(text: str) -> str:
    """返回小型防克隆签名，不展示完整回复作为风格样本。"""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return ""
    has_contrast = "不是" in t or "而是" in t or "并非" in t
    opener = "（已隐藏，含解释性对照句）" if has_contrast else t[:24] + ("..." if len(t) > 24 else "")
    traits = []
    if t.startswith("（"):
        traits.append("括号动作开头")
    if "？" in t or "?" in t or _contains_semantic_question(t):
        traits.append("含问句")
    if has_contrast:
        traits.append("含解释性对照句")
    if "……" in t:
        traits.append("含停顿省略号")
    trait_text = "；".join(traits) if traits else "普通口语"
    return f"起笔片段「{opener}」；{trait_text}"


_REPEATED_COMMITMENT_TERMS = (
    "明天早上",
    "明天",
    "早上",
    "蓝莓松饼",
    "蓝莓",
    "松饼",
    "焦边",
    "亮晶晶",
    "靠窗",
    "耳朵发烫",
    "耳朵",
)
_COMMITMENT_PROGRESS_MARKERS = (
    "一定",
    "会",
    "我会",
    "要",
    "准备",
    "计划",
    "等着",
    "留出来",
    "放在",
    "烤",
)
_COMMITMENT_ACK_RE = re.compile(
    r"(好不好|好啦|好呀|可以|行|说好了|不笑话|不会笑|我就想吃|想吃|要吃|等着吃|都要吃|都听你的)"
)


def _is_commitment_ack_user_text(text: str) -> bool:
    """Return True when the user is accepting/cute-pushing an already promised plan."""
    t = re.sub(r"\s+", "", str(text or ""))
    if not t or len(t) > 80:
        return False
    if any(q in t for q in ("怎么", "为什么", "多少", "几点", "哪", "什么")):
        return False
    return bool(_COMMITMENT_ACK_RE.search(t))


def _remove_at_mention_tokens(text: str) -> str:
    return re.sub(r"[@＠][^\s@＠,，。！？!?;；:：、）)\]】》」』\"'“”‘’…]+", "", text or "")


def _is_mention_only_user_text(text: str) -> bool:
    if not re.search(r"[@＠]", str(text or "")):
        return False
    stripped = _remove_at_mention_tokens(text)
    stripped = re.sub(r"[\s,，。！？!?;；:：、（）()\[\]【】《》「」『』\"'“”‘’…~～·\-—_]+", "", stripped)
    return bool((text or "").strip()) and not stripped


_ASSISTANT_SPEAKER_WRAPPER_RE = re.compile(r"^【([^】\n]{1,40})在当前对话中的发言】\s*")


def _mention_only_target_names(text: str) -> List[str]:
    names: List[str] = []
    for raw in re.findall(r"[@＠]([^\s@＠,，。！？!?;；:：、）)\]】》」』\"'“”‘’…]+)", text or ""):
        name = re.sub(r"^[\s]+|[\s]+$", "", str(raw or ""))
        if name and name not in names:
            names.append(name)
    return names[:6]


def _assistant_speaker_names_from_message(msg: dict) -> List[str]:
    names: List[str] = []
    for key in ("speaker_name", "speakerName", "speaker_display_name", "speakerDisplayName"):
        value = msg.get(key)
        if isinstance(value, str):
            name = value.strip()
            if name and name not in names:
                names.append(name)

    content = str(msg.get("content") or "").strip()
    wrapper = _ASSISTANT_SPEAKER_WRAPPER_RE.match(content)
    if wrapper:
        name = wrapper.group(1).strip()
        if name and name not in names:
            names.append(name)
    return names


def _strip_assistant_speaker_wrapper(text: str) -> str:
    return _ASSISTANT_SPEAKER_WRAPPER_RE.sub("", str(text or "").strip(), count=1).strip()


def _mention_name_matches(candidate: str, targets: List[str]) -> bool:
    c = re.sub(r"\s+", "", str(candidate or ""))
    if not c:
        return False
    for target in targets:
        t = re.sub(r"\s+", "", str(target or ""))
        if not t:
            continue
        if c == t or c in t or t in c:
            return True
    return False


def _last_assistant_reply_for_mention_target(
    recent_messages: Optional[List[dict]],
    target_names: List[str],
) -> Optional[dict]:
    if not target_names:
        return None

    seen_latest_user = False
    inspected = 0
    for msg in reversed(recent_messages or []):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "user" and not seen_latest_user:
            seen_latest_user = True
            continue
        if not seen_latest_user:
            continue
        inspected += 1
        if inspected > 24:
            break
        if role != "assistant":
            continue
        speakers = _assistant_speaker_names_from_message(msg)
        if not any(_mention_name_matches(speaker, target_names) for speaker in speakers):
            continue
        content = _strip_assistant_speaker_wrapper(str(msg.get("content") or ""))
        if not content:
            continue
        matched_name = next(
            (
                speaker
                for speaker in speakers
                if _mention_name_matches(speaker, target_names)
            ),
            target_names[0],
        )
        return {
            "speaker_name": matched_name,
            "content": content[:800],
        }
    return None


def _repeated_commitment_terms(recent_messages: Optional[List[dict]]) -> list[str]:
    """Detect repeated promise/topic anchors that can make a scene tread water."""
    recent = [m for m in (recent_messages or []) if isinstance(m, dict)]
    assistant_texts = [
        re.sub(r"\s+", "", str(m.get("content") or ""))
        for m in recent
        if m.get("role") == "assistant" and str(m.get("content") or "").strip()
    ][-4:]
    if len(assistant_texts) < 2:
        return []

    future_like_count = sum(
        1 for text in assistant_texts
        if any(marker in text for marker in _COMMITMENT_PROGRESS_MARKERS)
    )
    if future_like_count < 2:
        return []

    repeated = [
        term for term in _REPEATED_COMMITMENT_TERMS
        if sum(1 for text in assistant_texts if term in text) >= 2
    ]
    concrete = [t for t in repeated if t not in {"明天", "早上", "耳朵"}]
    if len(concrete) < 2:
        return []
    return repeated[:8]


def _build_repeated_commitment_guard_block(recent_messages: Optional[List[dict]]) -> str:
    terms = _repeated_commitment_terms(recent_messages)
    if not terms:
        return ""
    actual_user = _latest_user_actual_text(recent_messages)
    short_user_hint = ""
    if actual_user and len(actual_user) <= 24:
        short_user_hint = "当前用户新消息很短，更像是在接梗、撒娇、确认或轻轻推进；不要用长篇第二拍重讲旧计划。"
    block = (
        "【局部原地踏步风险】\n"
        f"最近角色回复已经连续复用同一承诺/话题锚点：{'、'.join(terms)}。这些内容已经被用户看见。\n"
        "本轮禁止继续套用「先害羞/抱怨一拍，再重申同一承诺或同一物品细节一拍」的固定两拍结构。\n"
        "除非用户明确询问这个计划的具体细节，否则 expression_policy 必须要求直接回应用户最新意图；"
        "若确实需要提到该计划，只能一笔带过，并且必须推进状态、换新方向或给出角色自己的新决定，不能把上一轮换词复述。\n"
        "speech_activity 通常应降到第二档或第三档的一气泡区间；主动任务不在 Step 1 判断，后续 Step 4 若需要也必须提供与这些锚点无关的新价值。\n"
        + short_user_hint
    )
    if _is_commitment_ack_user_text(actual_user):
        block += (
            "\n【已成立承诺的硬性推进要求】\n"
            "用户最新消息是在接受、撒娇催促或表达期待，不是在询问计划细节。角色已经答应过这件事，本轮主内容禁止继续确认同一承诺。\n"
            "禁止把回复写成这些短版复述：『那就说好了』『明天你只管等着吃』『我负责烤』『一定会烤好』『你等着就好』。\n"
            "本轮必须换到当下互动或新状态：可以回应用户馋/期待的样子、接住“不笑话你”的关系信号、给一个新的玩笑条件、轻轻转到现在能做的小动作或小选择；"
            "如果提到旧计划，只能作为半句背景，不能成为句子的落点。"
        )
    return block


def _apply_repeated_commitment_guard(
    planner: Dict[str, Any],
    recent_messages: Optional[List[dict]],
) -> Dict[str, Any]:
    terms = _repeated_commitment_terms(recent_messages)
    if not terms:
        return planner

    guarded = dict(planner)
    term_text = "、".join(terms)
    addition = (
        f"检测到近期已多次重复承诺/话题锚点（{term_text}）。"
        "本轮不要继续使用“害羞/抱怨 + 重申同一承诺”的两拍结构；"
        "优先直接回应用户最新意图。若必须提到旧计划，只能很短地带过，并推进状态或换新方向。"
    )
    guarded["expression_policy"] = _append_policy_text(
        guarded.get("expression_policy"),
        addition,
    )

    avoid = list(guarded.get("avoid_contradictions") or [])
    for item in (
        "不要把上一轮关于同一承诺或同一物品细节的内容换词复述",
        f"不要连续复用这些锚点：{term_text}",
        "不要用第二个气泡再次重讲已经说过的计划细节",
    ):
        if item not in avoid:
            avoid.append(item)
    guarded["avoid_contradictions"] = avoid

    actual_user = _latest_user_actual_text(recent_messages)
    if actual_user and len(actual_user) <= 24:
        guarded["bubble_count"] = 1
    if _is_commitment_ack_user_text(actual_user):
        guarded["reply_intent"] = "承接用户期待，避免重申已成立承诺，换到当下互动或新状态"
        guarded["expression_policy"] = _append_policy_text(
            guarded.get("expression_policy"),
            "用户是在接受/撒娇催促已成立的承诺，不是在询问计划细节；本轮主内容不得继续确认“明天等着吃/我负责烤/一定会烤好”。必须换成当下反应、关系信号或新状态推进。",
        )
        for item in (
            "不要写“那就说好了”作为开头或核心回应",
            "不要写“明天你只管等着吃/你等着就好/我负责烤/一定会烤好”等短版复述",
            "不要把已成立承诺再次确认当成本轮回复的主要内容",
        ):
            if item not in avoid:
                avoid.append(item)
        guarded["avoid_contradictions"] = avoid

    return guarded


_SUPPORTIVE_LOW_INFO_RE = re.compile(
    r"^(嗯+|唔+|哦+|好|好的|好吧|行|没事|算了|唉+|哎+|哎呀|啊)$"
)
_SUPPORTIVE_STRESS_RE = re.compile(
    r"累|压力|工作|学习|实习|基层|两班倒|十二小时|12小时|加班|熬夜|睡不够|"
    r"脑子空|心里堵|堵得慌|难受|委屈|崩溃|撑不住|硬撑|消耗|垃圾场|"
    r"返工|方案|反馈|否定|不够好|怀疑|能力|不适合|不想说"
)


def _compact_dialogue_text(text: str) -> str:
    return re.sub(r"[\s，,。.!！?？、；;：:“”\"'（）()~～…—-]+", "", str(text or ""))


def _previous_user_text_before_latest(recent_messages: Optional[List[dict]]) -> str:
    seen_latest_user = False
    for msg in reversed(recent_messages or []):
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").lower() != "user":
            continue
        if not seen_latest_user:
            seen_latest_user = True
            continue
        text = str(msg.get("content") or "").strip()
        if text:
            return text
    return ""


def _user_texts_from_step1_user_blob(user_blob: Optional[str]) -> List[str]:
    """Extract user turns from the Step 1 dialogue block when message history is stale."""
    if not user_blob:
        return []
    texts: List[str] = []
    for match in re.finditer(r"(?m)^user:\s*(.+)$", str(user_blob)):
        text = match.group(1).strip()
        if text:
            texts.append(text)
    return texts


def _is_supportive_low_info_continuation(
    recent_messages: Optional[List[dict]],
    user_blob: Optional[str] = None,
) -> bool:
    latest = _compact_dialogue_text(_latest_user_actual_text(recent_messages))
    previous_candidates: List[str] = []
    previous_user = _previous_user_text_before_latest(recent_messages)
    if previous_user:
        previous_candidates.append(previous_user)

    blob_users = _user_texts_from_step1_user_blob(user_blob)
    if blob_users:
        blob_latest = _compact_dialogue_text(blob_users[-1])
        if not latest or not _SUPPORTIVE_LOW_INFO_RE.match(latest):
            latest = blob_latest
        previous_candidates.extend(reversed(blob_users[:-1]))

    if not latest or not _SUPPORTIVE_LOW_INFO_RE.match(latest):
        return False
    if any(_SUPPORTIVE_STRESS_RE.search(text) for text in previous_candidates):
        return True
    for msg in list(recent_messages or [])[-8:]:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").lower() == "user" and _SUPPORTIVE_STRESS_RE.search(str(msg.get("content") or "")):
            return True
    return False


def _apply_supportive_low_info_text_guard(
    planner: Dict[str, Any],
    recent_messages: Optional[List[dict]],
    user_blob: Optional[str] = None,
) -> Dict[str, Any]:
    if not _is_supportive_low_info_continuation(recent_messages, user_blob=user_blob):
        return planner

    guarded = dict(planner)
    guarded["should_ask_question"] = False
    guarded["bubble_count"] = max(1, int(guarded.get("bubble_count") or 1))
    guarded["speech_activity"] = max(36, int(guarded.get("speech_activity") or 36))
    if str(guarded.get("action_style") or "").strip().lower() == "cinematic":
        guarded["action_style"] = "light_inline"

    addition = (
        "检测到用户是在压力/疲惫倾诉后只回了一个低信息承接词。最终正文可以很短、可以安静陪伴，"
        "但不能纯动作、纯静默、只说“嗯/好/我在/我陪着你”，也不能只把茶/水/物件推过去。"
        "必须有一小句角色化的直接文本接住情绪，但不要把所有角色都写成同一套休息、陪坐、我在类固定模板。"
        "外向角色可压低音量但保留活力、护短或轻吐槽；智慧角色可给一句有秩序感的轻梳理；"
        "讲究体面的角色可照顾用户的狼狈感；温柔内向角色可只用一两句很轻的陪伴；朴实稳重角色可短句稳住用户。"
        "智慧/理性角色短陪伴也不要退成“嗯/我在”或只有动作，至少要有一句秩序感、边界感或小结论。"
        "审美/体面/细致照顾型角色短陪伴也要带出体面照顾或替用户收住狼狈感的语气，不能只写“不想说就不说/我在这儿”。"
        "外向/高表达角色面对单字叹气时，短台词也要有护短、轻吐槽、短促打气或替用户挡一下情绪的态度，不能只落成休息加在场。"
        "外向/高表达角色即使只回一个气泡，也不能把可见文本压成单字或“我在呢”；短句里必须能看出角色自己的态度、节奏或照顾习惯。"
    )
    guarded["expression_policy"] = _append_policy_text(addition, guarded.get("expression_policy"))
    guarded["proactive_seed"] = _append_policy_text(
        "低信息承接后，若使用动作，必须配一小句角色化短文本；不要只写静态陪伴动作，也不要套用同一组安全安慰短语。",
        guarded.get("proactive_seed"),
    )
    avoid = list(guarded.get("avoid_contradictions") or [])
    for item in (
        "倾诉后低信息回应不得只输出纯动作或纯静默",
        "不要只说“嗯/好/我在/我陪着你”",
        "智慧/理性角色不要只写“嗯/我在”或纯动作；需要一句秩序感、边界感或小结论",
        "外向/高表达角色不要只写休息加在场；需要保留护短、轻吐槽、短促打气或替用户挡一下情绪的态度",
        "外向/高表达角色不要用纯动作加单字语气词收尾；可见文本里必须有角色态度、说话节奏或照顾习惯",
        "审美/体面/细致照顾型角色不要只写“不想说就不说/我在这儿”；需要带出体面照顾或替用户收住狼狈感的语气",
        "不要只写推茶、递水、坐旁边、翅膀环住等静态动作而没有一句文本承接",
        "不要把所有低信息陪伴写成同一套休息、陪坐、我在类模板",
    ):
        if item not in avoid:
            avoid.append(item)
    guarded["avoid_contradictions"] = avoid
    return guarded


def _apply_mention_only_guard(
    planner: Dict[str, Any],
    recent_messages: Optional[List[dict]],
) -> Dict[str, Any]:
    latest_user = _latest_user_actual_text(recent_messages)
    if not _is_mention_only_user_text(latest_user):
        return planner

    mention_targets = _mention_only_target_names(latest_user)
    prior_mention_reply = _last_assistant_reply_for_mention_target(recent_messages, mention_targets)

    guarded = dict(planner)
    guarded["reply_intent"] = "仅@点名：让当前角色基于当前现场发表反应或评价"
    guarded["requested_escalation"] = "none"
    guarded["user_pressure_level"] = "low"
    guarded["bubble_count"] = 1
    guarded["speech_activity"] = min(int(guarded.get("speech_activity") or 45), 45)
    guarded["speech_reason"] = (
        "用户只@点名，没有附加正文；这是把发言权交给角色评价当前现场，不是隐含关系确认或承诺请求。"
    )
    guarded["risk_notes"] = _append_policy_text(
        guarded.get("risk_notes"),
        "仅@点名不能推断成关系确认、承诺确认、回答未写出的提问或执行未写出的动作；只按当前现场给角色反应/评价。若当前角色与用户已有明确伴侣关系，且现场出现用户与其他伴侣/暧昧对象的亲密或忠诚冲突，可以按角色性格表现吃醋、委屈、压抑、调侃、质问或选择不在意。",
    )
    guarded["memory_use_policy"] = _append_policy_text(
        guarded.get("memory_use_policy"),
        "本轮可使用最近现场和场景锚点来理解角色看见/听见了什么；不要把第三方刚才的说法升级成用户要求当前角色承认。",
    )
    guarded["expression_policy"] = (
        "用户本轮只有@点名；按“把镜头切给当前角色”处理。"
        "角色应基于眼前现场、刚才听到的话和自身性格给一句具体反应、评价或小幅推进；"
        "若现场涉及用户与其他已确认伴侣/暧昧对象的亲密互动，且当前角色与用户也有伴侣或强占有/忠诚期待证据，可按角色设定产生嫉妒、受伤、沉默、试探、调侃或边界反应；"
        "不要只说“我在/怎么了”，也不要把@解释成让角色确认关系、承诺、同意某件未写出的事。"
    )
    guarded["proactive_seed"] = (
        "先接住被点名这一拍，再对当前现场作简短评价或反应；若现场很少，也给带角色态度的观察。"
    )
    guarded["reactive_emotion"] = {
        "label": "attentive",
        "intensity": 30,
        "stance_to_user": "responsive",
        "trigger": "用户只@点名，把发言权交给当前角色",
        "decay": "fast",
    }
    guarded["emotion_blend"] = "被点名后的注意和角色自身对现场的即时态度叠加。"

    if prior_mention_reply:
        speaker_name = str(prior_mention_reply.get("speaker_name") or "当前角色").strip() or "当前角色"
        guarded["reply_intent"] = "仅@点名：切回已在场角色，承接上一轮并递进当前现场"
        guarded["speech_reason"] = (
            "用户只@点名，且同一角色近期已经在临时群聊中发过言；这是把发言权切回该角色，"
            "需要承接上一轮和期间现场变化，不是重新入场。"
        )
        guarded["risk_notes"] = _append_policy_text(
            guarded.get("risk_notes"),
            "同一角色再次被@时，最主要风险是把它误当第一次入场，导致重复上一轮已经说过的邀请、评价、任务说明或物品说明。必须把上一轮发言视为已发生的现场背景。",
        )
        guarded["memory_use_policy"] = _append_policy_text(
            guarded.get("memory_use_policy"),
            f"同一角色「{speaker_name}」已在近期临时群聊中回应过一次；本轮是把发言权切回该角色。必须使用该角色上一轮发言、其他角色随后反应和当前现场状态作为背景，不能重置现场。",
        )
        guarded["expression_policy"] = _append_policy_text(
            guarded.get("expression_policy"),
            "同一角色二次或多次被@时，必须承接自己上一轮发言和期间其他角色反应，给出递进、转折、新信息、新动作或新问题；不得换词复述上一轮的邀请、评价、任务或物品说明。若上一轮已经发出邀请、提出试吃/查看/帮忙、交代去做某事或评价了现场，本轮应推进到邀请后的下一拍：回应在场角色的反应、补充新的具体差异、把人带入当前场景、递出/拿起相关物品、安排新的互动位置、抛出下一步问题，或按角色性格对关系信号作进一步反应。",
        )
        guarded["proactive_seed"] = _append_policy_text(
            guarded.get("proactive_seed"),
            "把话切回当前角色：基于上一轮发言后的现场变化推进下一拍，避免重新开场或重复上一轮落点。",
        )

    avoid = list(guarded.get("avoid_contradictions") or [])
    for item in (
        "仅@点名不得推断为关系确认、承诺确认或要求角色承认第三方说法",
        "不要输出空泛签到句，如“我在”“怎么了”“你找我？”",
        "不要把第三方刚说过的话直接改写成当前角色自己的确认",
        "不要强制所有角色都吃醋；嫉妒强度必须服从已证实关系、现场冲突和角色性格",
    ):
        if item not in avoid:
            avoid.append(item)
    if prior_mention_reply:
        for item in (
            "不要把当前@当成第一次入场；同一角色已经在当前临时群聊中发过言",
            "不要把上一轮已经说过的邀请、评价、任务说明或物品说明换词复述",
            "不要停留在上一轮动作之前；必须承接期间其他角色反应并推进下一拍",
        ):
            if item not in avoid:
                avoid.append(item)
    guarded["avoid_contradictions"] = avoid

    sequence = guarded.get("reply_sequence")
    if isinstance(sequence, list) and sequence:
        intent = (
            "承接同一角色上一轮发言，递进或转折当前现场"
            if prior_mention_reply
            else "对当前现场作角色化反应或评价"
        )
        guarded["reply_sequence"] = [{"type": "text", "intent": intent}]

    focus = guarded.get("character_profile_focus")
    if isinstance(focus, dict):
        new_focus = dict(focus)
        if prior_mention_reply:
            new_focus["query"] = "当前角色在临时群聊中再次被@点名时如何承接上一轮并推进现场"
            new_focus["reason"] = "用户只@点名且该角色近期已经发言，重点是角色如何延续现场、避免重复上一轮，并按自身性格递进。"
        else:
            new_focus["query"] = "当前角色被@点名后如何观察现场并发表简短反应"
            new_focus["reason"] = "用户只@点名，重点是角色看见当前现场后的态度和声纹，不是关系确认。"
        guarded["character_profile_focus"] = new_focus

    return guarded


_GROUP_PARTNER_RE = re.compile(
    r"(老婆|老公|夫妻|情侣|恋人|女朋友|男朋友|伴侣|爱人|恋爱|在一起|表白|求婚|订婚|结婚|婚姻)"
)
_GROUP_FLIRT_RE = re.compile(
    r"(喜欢|爱你|我爱|亲亲|亲吻|吻|抱|拥抱|怀里|贴着|靠在|床上|同床|约会|暧昧|脸红|害羞)"
)
_GROUP_SEXUAL_RE = re.compile(
    r"(性亲密|做爱|性交|进入|插入|私密部位|生殖|高潮|床上亲密|发生过亲密关系)"
)
_GROUP_OPEN_REL_RE = re.compile(r"(开放关系|多伴侣|都接受|大家都知道|不介意.*伴侣|允许.*伴侣)")


def _group_relationship_default() -> dict[str, Any]:
    return dict(default_planner_result()["group_relationship_tension"])


def _relationship_stage_bucket(stage: str) -> str:
    stage = str(stage or "").strip().lower()
    if stage in {"committed_partner", "intimate_partner"}:
        return "partner"
    if stage == "flirting":
        return "flirting"
    if stage in NEGATIVE_RELATIONSHIP_STAGES:
        return "conflict"
    if stage == "familiar":
        return "friend"
    if stage in NON_ROMANTIC_POSITIVE_RELATIONSHIP_STAGES:
        return "friend"
    return "unknown"


def _line_mentions_name_or_user(line: str, name: str) -> bool:
    name = str(name or "").strip()
    if not name:
        return False
    return name in line and bool(re.search(r"(Jason|用户|{{USER}}|USER|你|他|她)", line))
