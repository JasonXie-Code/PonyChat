

def _normal_stage3_selected_asset_block(
    selected_asset_attachments: Optional[List[Any]],
    reply_sequence: Any,
) -> str:
    raw_items = selected_asset_attachments or []
    if isinstance(raw_items, dict):
        raw_items = list(raw_items.values())
    attachments: list[dict[str, Any]] = []
    iterable_items = raw_items if isinstance(raw_items, list) else []
    for raw in iterable_items:
        item = _coerce_stage3_asset_attachment(raw)
        if item:
            attachments.append(item)
    if not attachments:
        return ""

    by_request_id: dict[str, dict[str, Any]] = {}
    for item in attachments:
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        rid = str(item.get("request_id") or meta.get("request_id") or "").strip()
        if rid and rid not in by_request_id:
            by_request_id[rid] = item

    ordered: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    if isinstance(reply_sequence, list):
        for node in reply_sequence:
            if not isinstance(node, dict) or str(node.get("type") or "") != "asset":
                continue
            rid = str(node.get("request_id") or "").strip()
            item = by_request_id.get(rid)
            if item and id(item) not in seen_ids:
                ordered.append(item)
                seen_ids.add(id(item))
    for item in attachments:
        if id(item) not in seen_ids:
            ordered.append(item)
            seen_ids.add(id(item))

    lines: list[str] = []
    for idx, item in enumerate(ordered[:4], 1):
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        rid = str(item.get("request_id") or meta.get("request_id") or "").strip()
        name = _stage3_asset_value_text(item.get("name") or meta.get("name"))
        pieces: list[str] = []
        if rid:
            pieces.append(f"request_id={rid}")
        for label, value in (
            ("素材名", name),
            ("含义概括", meta.get("intro")),
            ("情绪", meta.get("emotions")),
            ("场景/用途", meta.get("scenes")),
            ("标签", meta.get("custom_tags") or meta.get("tags")),
            ("图中文字", meta.get("image_text")),
            ("画面参考", meta.get("detail")),
            ("选择理由", meta.get("selection_reason")),
        ):
            text = _stage3_asset_value_text(value)
            if text:
                pieces.append(f"{label}：{text[:260]}")
        if pieces:
            lines.append(f"- {idx}. " + "；".join(pieces))
    if not lines:
        return ""
    return (
        "【本轮将发送的表情包/贴纸（Step 2 已选定）】\n"
        "这些附件会按 reply_sequence 真实发送。Step 3 写文字时必须把它们当成本轮已选定内容，不能重新想象另一张表情包，不能把正文写成与下列含义不一致的画面或动作。\n"
        "如果本轮同时有文字气泡，文字只负责自然配合这张表情包的态度；默认不要复述素材名、图中角色、画面细节或标签，除非用户明确询问图里有什么。\n"
        + "\n".join(lines)
    )


def _stage3_unresolved_at_names(at_event_context: Any) -> list[str]:
    if not isinstance(at_event_context, dict) or not at_event_context.get("enabled"):
        return []
    names: list[str] = []
    for value in at_event_context.get("unresolved_at_mentions") or []:
        text = str(value or "").strip()
        if text and text not in names:
            names.append(text[:40])
    return names[:4]


def _stage3_is_recent_minigame_memory_query(text: str) -> bool:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    if not raw:
        return False
    return bool(
        re.search(r"(刚刚|刚才|刚结束|刚退出|结束那局|退出游戏).{0,30}(象棋|棋局|小游戏|游戏)", raw)
        or re.search(r"(象棋|棋局|小游戏).{0,40}(口令|赌注|赌约|胜利留言|棋盘老师|兑现|A|B|C)", raw, re.I)
        or re.search(r"(赌注|赌约).{0,24}(升级|C|兑现|胜利留言|棋盘老师)", raw, re.I)
        or "棋盘老师" in raw
    )


def _format_unresolved_at_for_stage3(at_event_context: Any) -> str:
    names = _stage3_unresolved_at_names(at_event_context)
    if not names:
        return ""
    names_text = "、".join(names)
    return (
        "current_unresolved_at_mentions=" + names_text + "\n"
        "含义：这些名字来自当前用户消息中未解析成可发言角色的 @；当前主角色继续回应，未解析角色不得入场、发言、行动或收到消息。\n"
        "精确名字硬锚：最终正文必须逐字回应 current_unresolved_at_mentions 中的名字；不得把长期记忆、角色设定或最近对话里的其他熟人名字替换成本轮 @ 对象。"
        "若其他熟人不是当前用户实际 @ 的名字，本轮不要提那些其他人，也不要替那些其他人评价。\n"
        "认识证据标准：只有完整角色设定、长期记忆或最近上下文中明确出现这个 exact name，并显示主角色认识/听过/有印象，才算认识；"
        "当前用户刚刚 @ 了这个名字、名字看起来像角色名、或模型能想象性格，都不算认识证据。\n"
        "认识分支：如果完整角色设定、长期记忆或最近上下文明示当前主角色认识这个 exact name，可说明这个 exact name 不在这里/没在当前现场/没有被叫到，"
        "再用可能/大概/我猜/她或许会/准会等主角色视角谨慎推测或代答；不得伪造对方亲口回答或当前动作。\n"
        "不认识分支：如果没有证据说明当前主角色认识这个 exact name，或只是拿不准/不确定，就按不认识处理。"
        "正文必须字面表达“我不认识/没听过/不知道是谁/哪位”等疑惑，然后只给当前主角色自己的评价或追问对方是谁。"
        "不认识分支的正文模板是：“exact name？我不认识/没听过这个名字。<当前主角色自己的评价或追问>”。"
        "不要说这个 exact name 不在这里/今天没跟来/没在附近后继续替对方评价，也不要把无证据的人写成有性格、有想法或会喜欢什么；"
        "不认识分支里除 exact name 本身外，不要再提小露、朋友、其他熟人、她/他/对方的性子、如果也在、要是看到、会喜欢或会觉得。"
    )


def _normal_reply_frame_block(
    planner_result: Dict[str, Any],
    *,
    character_prompt_context: str = "",
    raw_character_prompt_context: str = "",
    current_user_text: str = "",
    has_vision_grounding: bool = False,
    expression_brief: str = "",
    scene_anchor_card: str = "",
    at_event_context: Optional[Dict[str, Any]] = None,
    selected_asset_attachments: Optional[List[Any]] = None,
) -> str:
    p = planner_result or {}
    literal_reply = str(p.get("literal_reply_text") or "").strip()
    if literal_reply:
        return (
            "【本轮回复写法】\n"
            "复述指令：逐字输出下面的内容作为最终正文，不增删、不改写、不补写。\n"
            "需要被复述的内容：\n"
            f"{literal_reply[:1200]}"
        )
    reply_language = _coerce_reply_language(p.get("reply_language"))
    voice_reply = _coerce_voice_reply(p.get("voice_reply"))
    action_style = str(p.get("action_style") or "plain_text").strip().lower()
    if action_style not in {"plain_text", "light_inline", "cinematic"}:
        action_style = "plain_text"
    speech_activity = max(0, min(100, int(p.get("speech_activity") or 45)))
    reply_level = _reply_level_from_speech_activity(speech_activity)
    bubble_count = max(1, min(6, int(p.get("bubble_count") or 1)))
    should_ask = bool(p.get("should_ask_question"))
    character_context_text = str(character_prompt_context or "").strip()
    raw_character_context = str(raw_character_prompt_context or "").strip()
    homepage_fields = _extract_character_homepage_profile_fields_for_reply(
        raw_character_context or character_context_text
    )
    homepage_profile = _extract_character_homepage_profile_for_reply(
        raw_character_context or character_context_text
    )
    if (
        "本轮倾向：" in character_context_text
        or "本轮不倾向：" in character_context_text
        or "本轮优先避免：" in character_context_text
    ):
        profile_raw = character_context_text[:1600]
    else:
        profile_raw = _compact_character_profile_for_reply(
            character_context_text or raw_character_context
    )
    profile, self_likely, self_unlikely = _split_stage2_character_profile_context(profile_raw)
    alias_note = _character_alias_identity_note(raw_character_context or character_context_text)
    state_parts = _planner_state_policy_blocks(p)
    scene_anchor_card = str(scene_anchor_card or "").strip()
    scene_location_conflict_guard = (
        "当前地点硬锚：本轮若【Step 2 场景锚点卡】给出 active location/position，"
        "正文里解释当前动作、衣服、身体状态、物品位置或环境感受时，地点只能来自这张卡和事实边界。"
        "长期记忆、上下文摘要、角色主页、稳定设定或旧回复里的其他地点（例如旧住处、旧交通工具、旧房间、店铺、农场、篷车/马车等）"
        "只能作为历史背景或不提；不得写成当前所在地点，也不得写成“因为那里太热/太冷/太挤/太安静”等当前原因。"
    ) if scene_anchor_card else ""
    current_user_text = re.sub(r"\s+", " ", str(current_user_text or "")).strip()
    body_fact_lines = _stage3_character_body_fact_lines(homepage_fields, current_user_text)
    user_home_visit_lines = _stage3_user_home_visit_lines(current_user_text, scene_anchor_card)
    setting_anchor_priority = _stage3_should_prioritize_setting_anchors(
        current_user_text=current_user_text,
        planner_result=p,
        profile=profile,
    )
    minigame_memory_query = _stage3_is_recent_minigame_memory_query(current_user_text)
    if minigame_memory_query:
        setting_anchor_priority = False
    if setting_anchor_priority:
        scene_anchor_card = _stage3_neutralize_entity_selection_examples(scene_anchor_card)
    profile_base_for_stage3 = _stage3_neutralize_profile_for_setting_query(profile) if setting_anchor_priority else profile
    setting_anchor_lines = (
        _stage3_focus_setting_anchor_lines(_stage3_setting_anchor_lines(profile_base_for_stage3))
        if setting_anchor_priority
        else []
    )
    profile_for_stage3 = (
        _stage3_profile_with_focused_setting_anchors(profile, setting_anchor_lines)
        if setting_anchor_priority
        else profile_base_for_stage3
    )
    fact_action = _fact_judgement_current_user_action(p.get("fact_judgement"))
    feasibility_guard = _stage3_action_feasibility_guard(p.get("fact_judgement"))
    scene_boundary_guard = _stage3_scene_boundary_guard(p.get("fact_judgement"))
    concession_boundary_guard = _stage3_concession_boundary_guard(p.get("fact_judgement"))
    suppressed_feasibility_materials: list[str] = []
    current_user_action_event = bool(fact_action.get("enabled"))
    current_user_action_anchor = str(fact_action.get("anchor") or "").strip()
    current_user_action_terms = list(fact_action.get("anchor_terms") or [])
    current_user_action_terms_text = "、".join(current_user_action_terms)
    current_user_action_guidance = (
        _sanitize_stage3_material_directive(fact_action.get("guidance"), limit=260)
        or _current_user_action_anchor_guidance(current_user_action_terms)
    )
    expression_contract = _collect_stage3_expression_contract(p)
    supportive_low_info_guard = (
        "低信息承接后" in str(p.get("proactive_seed") or "")
        or "压力/疲惫倾诉后只回了一个低信息承接词" in str(p.get("expression_policy") or "")
        or any("倾诉后低信息回应" in str(item or "") for item in (p.get("avoid_contradictions") or []))
    )
    support_haystack = "\n".join(
        [
            str(p.get("reply_intent") or ""),
            str(p.get("tone") or ""),
            str(p.get("expression_policy") or ""),
            str(p.get("proactive_seed") or ""),
            str(p.get("speech_reason") or ""),
            "\n".join(str(item or "") for item in (p.get("avoid_contradictions") or [])),
        ]
    )
    supportive_scene_guard = supportive_low_info_guard or any(
        marker in support_haystack
        for marker in ("安慰", "陪伴", "开导", "吐槽", "压力", "疲惫", "自我怀疑", "被否定", "高负荷", "返工")
    )
    writing_lines: list[str] = [
        "正文写 bubbles[*].parts；不要输出旧 content 字段。",
        "kind=speech 写角色台词并原样显示；其他 kind 写动作/心理/状态/画面等补充，后端加全角括号，text 不写括号。",
        "第一人称状态句也不是台词：例如“我声音比平时低了一点/我的语气很坚定/我嗓音发颤/我声线压低”必须写成 voice_state 或 body_state part，不得写成 speech。",
        "当前用户问题优先：如果【当前用户消息】是在提问、调侃追问或反问，首个 speech 必须先回应这个问题/调侃点，至少明确主体、态度或事实边界之一；早安、天气、早餐、再躺一会、旧生活安排、害羞动作或转移话题只能放在回答之后，不能成为主内容。",
        "故事/经历选项去重：如果当前用户是在继续剧情，而上一条 assistant 让用户在故事/经历/话题之间选择，先看最近可见对话哪些选项已经讲过、展开过或反复提出；已用选项只能轻带为历史背景。正文应直接进入未展开选项、第二次/后来经历、当前场景下一拍、亲密接触或真实转折，不要再次问“想听哪个故事/还没想好听哪个”。",
    ]
    if action_style != "plain_text":
        writing_lines.extend(
            [
                "台词/描写边界硬规则：speech 只放台词；动作、神态、心理、身体/声音状态或旁白说明放非 speech kind。",
                "台词和动作穿插时按显示顺序拆 parts，不混在同一个 part。",
            ]
        )
    if bubble_count == 1:
        writing_lines.append("本轮是单气泡回复：最终正文只能有 1 个非空段落，不要换行、不要空行。")
        if reply_level == 2:
            if supportive_low_info_guard:
                writing_lines.append("本轮虽是短回应，但低信息陪伴硬约束优先：只能写短台词，或短括号动作加一句短台词；禁止只输出一个括号动作。")
            else:
                writing_lines.append("本轮是第二档短回应：写约 10 字的短台词；也可以只输出一个短括号动作气泡，例如（我点头）。")
        else:
            writing_lines.append("单气泡只取一个核心落点；不要把表达调度里的每个动作、每个细节逐项展开。但若当前用户是在核对多个事实槽位（位置、姿势、物品分别在哪里），同一段必须逐项答全这些槽位。")
            writing_lines.append("普通单气泡长度优先控制在 40-90 个中文字符左右；当前场景状态核对可放宽到约 150 个中文字符，以答全点名槽位为先。")
        writing_lines.append("语气和节奏用逗号、句号、省略号、重复字或感叹号在同一段里组织，不用换行制造停顿。")
        writing_lines.append("中文日常聊天很少用长横线；插入语、拉长音、情绪转弯和补充说明优先写成逗号、句号、省略号或重复字。")
    else:
        writing_lines.extend(
            [
                "语气和节奏优先用逗号、句号、省略号或换行来组织，让短句自然接上，少用说明书式连接。",
                "中文日常聊天很少用长横线；插入语、拉长音、情绪转弯和补充说明优先写成逗号、句号、省略号、换行、重复字或感叹号的聊天节奏。",
                f"正文组织成 {bubble_count} 个非空气泡；在 JSON 中对应 {bubble_count} 个 bubbles 项，不要在 parts[*].text 内写换行。",
            ]
        )
    writing_lines.append(f"本轮回复档位：{_reply_level_label(reply_level)}。气泡数和括号数量都按这个档位执行。")
    if action_style == "plain_text":
        writing_lines.append("用户没有要求详细描写：优先只写角色直接说出口的台词；若表达调度明确要求纯台词或不要动作，则完全不用括号。")
    elif action_style == "light_inline":
        writing_lines.append("用户没有要求长描写：如果确实需要动作或状态，只使用回复档位允许的短全角括号片段；台词仍然是主体，不使用引号对白。")
        writing_lines.append("括号可放在句首、句中或句尾；括号里可以写角色、用户和第三方互动；描述当前角色自己的动作、神态或感受时用角色视角，不写外部旁白。")
    else:
        writing_lines.append("用户本轮要求或允许详细描写：可写场景化内容；动作、状态或心理气泡用完整的（……）承载，括号可写角色、用户和第三方互动；台词直接另写，不使用小说式引号对白或裸叙事段。")
    if current_user_action_event:
        writing_lines.append(
            "本轮 Step 2 已确认当前用户动作，动作承接高于 plain_text 口径：即使普通聊天优先台词，也必须先用短台词或短括号点出该动作造成的即时反应。"
        )
    if supportive_scene_guard:
        writing_lines.append(
            "支持性回复事实锚：若本轮按智慧/理性/分析/主动吐槽/较长安慰来写，正文前半段要自然保留用户已经说过的至少一个具体线索，例如工作时长、环境、返工、反馈模糊或自我怀疑；短句陪伴型角色不强制点名事实，但不能把长回复写成只有角色自己的类比和泛安慰。"
        )
    if supportive_low_info_guard:
        writing_lines.append(
            "低信息陪伴硬约束：最终正文可以很短，但不能只有 action/thought/body_state 等非 speech part、静默、递物、坐旁边，也不能只说“嗯/好/我在/我陪着你”。如果写动作，必须配一个角色化短 speech part；优先使用当前角色的声纹、价值判断、照顾习惯或身体动作带出的语气，不要套用休息、陪坐、我在类安全安慰模板。温柔内向角色可以一句轻声陪伴；审美/体面/细致照顾型角色要保留体面照顾或替用户收住狼狈感的语气；智慧/理性角色要保留秩序感、边界感或小结论；外向、高表达、理性型或稳重型角色的可见短台词不能只剩“我在/我陪着/歇会儿”，更不能是纯动作加单字语气词，要带一点自己的措辞、判断、照顾习惯或说话节奏；面对单字低信息时尤其要保留护短、轻吐槽、短促打气、替用户挡一下情绪、转移情绪或轻安排的态度，不能只落成休息加在场。身体动作必须服从 Step 3 已注入的当前角色种族体态边界和用户种族体态边界；角色专属身体部位只能属于角色自己，不要写到用户身上。"
        )
    if current_user_action_terms:
        writing_lines.append(
            "当前动作/要求不能只用“这种方式/这样/突然/你来了/有什么事”等代词或泛化问候糊过去；首个气泡要体现角色已经接住其含义或承接结果，但不需要逐字复述用户原句。"
        )
        writing_lines.append(
            "如果当前用户是在要求角色主动行动、推进、靠近或“你来动”，角色回复必须由当前角色自己承接动作或明确接过主动权；不要把动作任务转派回用户。"
        )
    lang = str(reply_language.get("language") or "auto").strip() or "auto"
    if lang.lower() != "auto":
        writing_lines.append(f"正文整体使用 {lang}。")
    if not should_ask:
        writing_lines.append("本轮用陈述式收尾，把关心、同意或推进写成角色自己的表态和安排。")
        writing_lines.append(
            "低信息承接：先承接最近可见上一拍；推进强度服从 Step 2 自我认知的本轮倾向/不倾向。适合主导推进时可带流程和默认选择；适合共同推进时只推进一小拍再留观察或选择；适合用户带领时只轻承接、表达感受、确认或等待，不独自带完整行动线。不要重复同一许可，不跳新话题或旧活动。"
        )
    if voice_reply.get("enabled"):
        writing_lines.append("本轮承载为语音时，文本用短句口语；动作片段和台词拆成清晰的小段。")
    if has_vision_grounding:
        writing_lines.append(
            "本轮有用户图片附件或已注入历史图片识别内容；需要注意用户传的图。"
            "若用户当前消息在展示、询问或回指图片，正文必须优先依据【图片识别上下文】或【历史图片上下文】回应，"
            "并自然点到其中的具体画面、文字或实体。"
        )
    bubble_plan_lines = [
        f"本轮 bubble_count 必须为 {bubble_count}；bubbles 数组长度也必须为 {bubble_count}。",
        "每个 bubbles[*].parts 是一个气泡内部的有序段落数组，不写规则说明或后台术语。",
        "每个 part 必须含 kind/text；speech 原样显示，其他 kind 后端加括号；text 不换行、不自写括号。",
        "若一个气泡里先说出台词、随后描述声音/语气/嗓音/声线/呼吸等状态，必须拆成 speech -> voice_state/body_state；不要把状态句继续标成 speech。",
        "purpose 只作内部标签，可从 answer_user、react_to_user、advance_scene、soft_close、acknowledge、clarify 中选择。",
    ]
    if action_style != "plain_text":
        bubble_plan_lines.insert(
            2,
            "动作/心理/状态不得写进 speech；台词不得写进非 speech kind。",
        )
    if current_user_action_terms:
        bubble_plan_lines.insert(
            1,
            "首个 bubbles[0].parts 语义约束：必须自然承接 Step 2 的当前用户动作/要求，体现其核心含义；不要为了证明承接而机械复述用户原句或硬塞参考词。参考词只在自然、符合角色口吻且人称视角正确时使用："
            + current_user_action_terms_text
            + "；"
            + current_user_action_guidance
            + "如果只写转身、抬头、问候、早上好、你来了、有什么事、这种打招呼方式，或把用户要求角色执行的动作转派回用户，而没有体现用户刚才动作/要求造成的即时反应或承接结果，则本轮输出不合格；used_facts 必须写入这条当前用户动作事实。",
        )
    if action_style == "cinematic":
        bubble_plan_lines.append("本轮描写请求优先：每个 bubble 可用 thought/body_state/scene/visual/action 等非 speech parts 表达心理、身体、环境或动作镜头；不要把多个层次塞进同一个 part。")
    elif action_style == "plain_text":
        bubble_plan_lines.append("普通聊天优先纯台词；若不需要动作描写，每个 bubble 只写 speech part。")
    else:
        bubble_plan_lines.append("可使用短 action/body_state/expression part，但 speech 台词仍然是主体；一个 part 只承载一个小节奏。")
    if supportive_low_info_guard:
        bubble_plan_lines.append("低信息陪伴硬约束：parts 不得只有非 speech 动作；不得是“嗯/好/我在/我陪着你”这类机械承接；必须有一个角色化 speech part 接住用户的低落、沉默或叹气。高表达/审美/理性/稳重角色的短台词要保留自己的口吻，不要只靠动作或单字语气词来补角色味。")

    story_progression_text = format_story_progression_for_stage3(p.get("story_progression"))
    current_user_text_for_stage3 = _stage3_display_current_user_text(
        current_user_text,
        story_progression_text,
    )
    non_intimate_story_progression = bool(
        story_progression_text and "成人合意亲密" not in story_progression_text
    )
    unresolved_at_names = _stage3_unresolved_at_names(at_event_context)
    unresolved_at_text = _format_unresolved_at_for_stage3(at_event_context)
    unresolved_at_names_text = "、".join(unresolved_at_names)
    story_progression_raw = (
        p.get("story_progression") if isinstance(p.get("story_progression"), dict) else {}
    )
    completed_story_progression = bool(
        non_intimate_story_progression
        and story_progression_raw.get("completed_previous_task")
    )
    story_required_anchor = _sanitize_stage3_objective_material(
        story_progression_raw.get("required_visible_anchor")
        or story_progression_raw.get("target"),
        180,
    )
    story_source_brief = _sanitize_stage3_material_directive(
        story_progression_raw.get("source"),
        limit=220,
    )
    if non_intimate_story_progression:
        if bubble_count >= 2:
            bubble_plan_lines.append(
                "后续动作气泡顺序：第 1 个气泡可以用一句话承接位置变化或行动接续，第 2 个气泡必须落到目标处已经发生的可见进展；不要两个气泡都停在出发、带路、路上或说明目标位置。"
            )
        else:
            bubble_plan_lines.append(
                "后续动作单气泡口径：同一个气泡内直接写到目标处已经发生的可见进展，不停在出发、带路、路上或说明目标位置。"
            )
        if completed_story_progression:
            anchor_label = story_required_anchor or "target/source 中的新方向"
            bubble_plan_lines.append(
                "已完成任务后推进口径：前一插入任务/旧目标已经完成，本轮必须显式落到「"
                + anchor_label
                + "」或 source 中的原计划/下一阶段，并让这个方向发生一个可见动作、决定、物品变化、线索或第三方反应；"
                "不要只写“我知道你要干嘛”“跟我来”“去的地方不远”、未知目的地、开窗、夜空或无关外部支线。"
            )
    final_checks: list[str] = []
    if bubble_count == 1:
        final_checks.append("单气泡自检：最终正文只有一段，没有换行或空行；普通回复只选择一个关键动作/状态和一个核心事实点。若用户问多个当前场景槽位，则本条例外，必须在同一段内逐项答全位置、姿势和被点名物品。")
    if reply_level == 2:
        if supportive_low_info_guard:
            final_checks.append("第二档低信息陪伴自检：最终正文约 10-30 字；禁止纯括号动作，禁止只说“我在”，高表达角色也禁止纯动作加单字语气词；必须有一句短台词接住情绪。")
        else:
            final_checks.append("第二档自检：最终正文约 10 字；若使用括号，整个气泡只能是一个短括号动作，不能混合台词。")
    if supportive_low_info_guard:
        final_checks.append("低信息陪伴自检：正文里有角色化可见文本承接情绪；不是纯动作、纯静默或休息、陪坐、我在类模板化组合。")
    if action_style != "plain_text":
        final_checks.append(
            "台词/描写边界自检：动作、神态、心理、身体或声音状态都在完整括号内；括号外只剩台词。"
        )
        final_checks.append(
            "声音状态自检：我声音/我的语气/嗓音/声线/呼吸等状态句不能裸露在 speech 里，必须用 voice_state 或 body_state。"
        )
    if non_intimate_story_progression:
        final_checks.append(
            "后续动作自检：最终正文已经让用户看见世界内具体事件、抵达/进入目标或目标处的一步进展；没有只停在原地提议、准备、带路、重复许可或继续说“走吧/回屋吧”。"
        )
        if completed_story_progression:
            anchor_label = story_required_anchor or "target/source 的新方向"
            final_checks.append(
                "已完成任务推进自检：最终正文显式落到「"
                + anchor_label
                + "」或 source 中的原计划/下一阶段；没有只写“我知道你要干嘛”“跟我来”“去的地方不远”、未知地点、开窗夜空或无关支线。"
            )
    must_lines = [
        f"意图：{_clip_line(p.get('reply_intent'), 180) or '自然承接'}",
        f"语气：{_clip_line(p.get('tone'), 200) or '符合角色、口语自然'}",
        f"回复档位：{_reply_level_label(reply_level)}",
    ]
    if body_fact_lines:
        must_lines.append(
            "当前角色身体事实硬锚："
            + "；".join(body_fact_lines)
            + " 用户正在问这些身体/标记/手蹄事实时，最终正文必须直接给出对应位置或正确用词，不能只用含糊的“腹部/身体两侧/换个说法”。"
        )
        final_checks.append("身体事实自检：正文已经按当前角色主页种族回答乳房/可爱标记/手蹄位置或用词，没有混成人类和小马体态。")
    if user_home_visit_lines:
        must_lines.append(
            "用户家首次来访硬锚："
            + "；".join(user_home_visit_lines)
            + " 回答地点、画面、房间归属、熟悉程度、物品位置或旧回忆时必须按此执行。"
        )
        final_checks.append("用户家来访自检：正文没有把用户家/用户房间说成角色自己家/自己房间，也没有编入角色住处装饰或用户家储物。")
    if current_user_action_event:
        must_lines.append(
            "当前用户动作硬锚："
            + _clip_line(current_user_action_anchor or current_user_text, 260)
            + "。最终正文第一拍必须体现这个新动作/新场景造成的即时反应，不能只延续上一轮计划、旧话题或旧动作。"
        )
    if current_user_action_terms:
        must_lines.append(
            "首拍语义承接：最终正文第一拍必须体现当前用户动作/要求的核心含义；参考词仅在自然、符合角色口吻且人称视角正确时使用，不要求逐字复述："
            + current_user_action_terms_text
            + "；不能只写“嗯/好/走吧/带路/你想往哪边走/转过身/早上好/有什么事”等泛化反应，也不要把用户对角色说的“你……”类命令原样当成角色台词或转派回用户。"
        )
    if unresolved_at_text:
        must_lines.append(
            "未解析 @ 当前名字硬锚：最终正文必须逐字回应「"
            + unresolved_at_names_text
            + "」。若主角色认识这个 exact name，说明对方不在当前现场并用主角色视角谨慎推测；"
            "若无证据认识或只是拿不准，必须字面说不认识/没听过/不知道是谁/哪位；用户刚刚 @ 这个名字本身不算认识证据。"
            "不认识分支说完疑惑后，只能写当前主角色自己的评价或追问对方是谁；不得用记忆或设定里的其他熟人替换当前 @ 名字，也不得在陌生名场景里替对方评价。"
        )
    next_beat_limit = 260 if bubble_count == 1 else 520
    expression_limit = 420 if bubble_count == 1 else 900
    next_beat = _sanitize_stage3_objective_material(
        p.get("proactive_seed"),
        next_beat_limit,
        blocked_terms=expression_contract["hard_blocked"],
    )
    if next_beat and _stage3_material_conflicts_action_feasibility(next_beat, feasibility_guard):
        suppressed_feasibility_materials.append("proactive_seed/下一拍动作含无证据当前物品或刚完成动作")
        next_beat = ""
    if next_beat and _stage3_material_conflicts_scene_boundary(next_beat, scene_boundary_guard):
        suppressed_feasibility_materials.append(
            "proactive_seed/下一拍动作含已被 Step 2 场景事实边界降级的位置或地点建议"
        )
        next_beat = ""
    if next_beat and _stage3_material_conflicts_concession_boundary(next_beat, concession_boundary_guard):
        suppressed_feasibility_materials.append("proactive_seed/下一拍动作含已被 Step 2 禁止的服输反向材料")
        next_beat = ""
    if next_beat:
        must_lines.append("下一拍动作：" + next_beat)
    if story_progression_text:
        if "成人合意亲密" in story_progression_text:
            if "高潮后的余韵" in story_progression_text or "已经达到" in story_progression_text:
                must_lines.append(
                    "亲密继续硬锚：当前成人合意亲密高潮节点已达到；本轮可进入余韵、安抚、清理、确认感受、抱住休息或温柔收束，但仍承接刚发生的亲密状态，不跳无关日常或第三方事件。"
                )
            else:
                must_lines.append(
                    "亲密正反馈硬锚：当前是成人合意亲密场景的继续信号；高潮/释放/余韵尚未明确出现。本轮必须继续当前亲密接触链条，加深身体贴近、节奏、主动动作或明确想要；不得把落点改成睡觉、休息、喝水、聊天、散步、吃东西、换地点、清理、毛巾、热水、厨房、饰品、动物、农场、任务或其他非亲密内容。内向、害羞、温柔或照顾型角色也必须主动推进，只是动作和台词可以更轻；极内向或寡言角色也要有自己的轻微主动意愿或靠近动作，不能只说好/你说了算/听你的；若已有特殊亲密关系/玩法约定，按该关系和角色主体性推进。"
                )
                if "自然抵达高潮/释放/余韵节点" in story_progression_text or "正文需要字面出现" in story_progression_text:
                    must_lines.append(
                        "亲密高点硬落点：当前亲密段落已经充分铺垫，本轮应自然抵达高潮/顶峰/释放/余韵节点，正文需要字面出现“高潮”“顶峰”“释放”或“余韵”之一；不要继续写成再来一轮、要不要、你准备好了吗、清理、喝水、毛巾或日常转场。"
                    )
                    final_checks.append(
                        "亲密高点自检：正文已经字面出现高潮、顶峰、释放或余韵之一；没有用清理/毛巾/喝水/休息/厨房/任务/动物/农场/饰品替代。"
                    )
        else:
            must_lines.append(
                "后续动作硬锚：本轮必须产生具体世界内事件；若已有 target，直接到达/进入 target 或在 target 处发生任务进展。"
                "若场景锚点仍停在旧地点，把它当作行动起点，用自然过渡直接落到目标处的可见进展；这不是突然切换。"
                "若 target、场景锚点或事实边界给出明确地点名，正文落点必须保留该地点名或同一地点；不要把目标地点替换成工具间、厨房、卧室、住所、门口或其他相邻/常见地点。"
                "优先写成已到达后的画面：角色或第三方已经坐下、打开、拿起、检查、包扎、翻找、发现、修好一小步或产生明确反应。"
            )
            if completed_story_progression:
                anchor_label = story_required_anchor or "target/source 中的新方向"
                source_clause = ("；source=" + story_source_brief) if story_source_brief else ""
                must_lines.append(
                    "已完成任务后的后续动作硬锚：前一插入任务、旧目标或过渡阶段已经完成；本轮必须显式回到/开启「"
                    + anchor_label
                    + "」这个新方向"
                    + source_clause
                    + "，并写出该方向上的一个具体下一步。"
                    "不要只写模糊带路、未知地点、开窗、夜空、突然换地方或外部订单/敲门/NPC支线来替代原计划。"
                )
    expression_policy = _sanitize_stage3_objective_material(p.get("expression_policy"), expression_limit)
    if expression_policy and _stage3_material_conflicts_action_feasibility(expression_policy, feasibility_guard):
        suppressed_feasibility_materials.append("expression_policy/表达调度含无证据当前物品或刚完成动作")
        expression_policy = ""
    if expression_policy and _stage3_material_conflicts_scene_boundary(expression_policy, scene_boundary_guard):
        suppressed_feasibility_materials.append(
            "expression_policy/表达调度含已被 Step 2 场景事实边界降级的位置或地点建议"
        )
        expression_policy = ""
    if expression_policy and _stage3_material_conflicts_concession_boundary(
        expression_policy,
        concession_boundary_guard,
    ):
        suppressed_feasibility_materials.append("expression_policy/表达调度含已被 Step 2 禁止的服输反向材料")
        expression_policy = ""
    if expression_policy and setting_anchor_priority:
        expression_policy = _stage3_neutralize_entity_selection_examples(expression_policy)
    if expression_policy:
        if bubble_count == 1:
            must_lines.append("单气泡执行口径：普通回复只取表达调度中的关键落点；若当前用户核对位置/姿势/多个物品，则同一段逐项答全，不按“一个事实点”压缩。")
        if setting_anchor_priority:
            must_lines.append(
                "表达调度：" + expression_policy
                + "；本条只提供动作节奏/介绍方式，不提供未明说实体的具体名字或关系选择。"
            )
        else:
            must_lines.append("表达调度：" + expression_policy)
    if self_likely:
        self_likely_must = _sanitize_stage3_objective_material(
            self_likely,
            420,
            blocked_terms=expression_contract["hard_blocked"],
        )
        if self_likely_must and setting_anchor_priority:
            self_likely_must = _stage3_neutralize_entity_selection_examples(self_likely_must)
        if self_likely_must and _stage3_material_conflicts_action_feasibility(self_likely_must, feasibility_guard):
            suppressed_feasibility_materials.append("Step 2 自我认知倾向含无证据当前物品或刚完成动作")
            self_likely_must = ""
        if self_likely_must and _stage3_material_conflicts_scene_boundary(self_likely_must, scene_boundary_guard):
            suppressed_feasibility_materials.append(
                "Step 2 自我认知倾向含已被 Step 2 场景事实边界降级的位置或地点建议"
            )
            self_likely_must = ""
        if self_likely_must and _stage3_material_conflicts_concession_boundary(
            self_likely_must,
            concession_boundary_guard,
        ):
            suppressed_feasibility_materials.append("Step 2 自我认知倾向含已被 Step 2 禁止的服输反向材料")
            self_likely_must = ""
    else:
        self_likely_must = ""
    if self_likely_must:
        must_lines.append(
            "Step 2 自我认知倾向："
            + self_likely_must
            + "。低信息承接时按这里决定本轮主动性；倾诉、疲惫、自我怀疑或一字叹气后的陪伴场景，也按这里决定本轮支持风格，不把所有角色写成同一种开导模板。"
        )
    rp = p.get("rhetorical_policy")
    if isinstance(rp, dict):
        rp_mode = _clip_line(rp.get("mode"), 40) or "plain"
        rp_reason = _clip_line(rp.get("reason"), 180)
        rp_allowed_raw = rp.get("allowed_devices") if isinstance(rp.get("allowed_devices"), list) else []
        rp_blocked_raw = rp.get("blocked_devices") if isinstance(rp.get("blocked_devices"), list) else []
        rp_allowed = "、".join(_clip_line(x, 40) for x in rp_allowed_raw if _clip_line(x, 40)) or "无"
        rp_blocked = "、".join(_clip_line(x, 40) for x in rp_blocked_raw if _clip_line(x, 40)) or "无"
        rp_fallback = _clip_line(rp.get("fallback_voice"), 160)
        must_lines.append(
            "修辞策略："
            f"mode={rp_mode}；reason={rp_reason or '按本轮语境和近期重复度控制'}；"
            f"allowed={rp_allowed}；blocked={rp_blocked}；fallback={rp_fallback or '用角色节奏、动作和具体事实保留声纹'}。"
            "若 mode=forbidden/plain，最终正文不得使用完整比喻、隐喻、故事、典故或成语化夸张比方；若 blocked 包含“像/好像/仿佛/好比/如同/犹如/正如/宛如/似的/比作/故事/典故/天塌下来/乌云/彩虹/潮水”等触发词，正文也不得出现这些词本身；若 mode=light，只能用轻量词汇或句式；若 mode=full，仍需避开 blocked。"
        )
    mp = p.get("expression_motif_policy")
    if isinstance(mp, dict):
        mp_mode = _clip_line(mp.get("mode"), 40) or "optional"
        mp_reason = _clip_line(mp.get("reason"), 220)
        mp_allowed_raw = mp.get("allowed_motifs") if isinstance(mp.get("allowed_motifs"), list) else []
        mp_blocked_raw = mp.get("blocked_motifs") if isinstance(mp.get("blocked_motifs"), list) else []
        mp_allowed = "、".join(_clip_line(x, 50) for x in mp_allowed_raw if _clip_line(x, 50)) or "无"
        mp_blocked = "、".join(_clip_line(x, 50) for x in mp_blocked_raw if _clip_line(x, 50)) or "无"
        mp_fallback = _sanitize_stage3_material_directive(mp.get("fallback_expression"), limit=180)
        if mp_fallback and _stage3_material_mentions_blocked(mp_fallback, expression_contract["hard_blocked"]):
            mp_fallback = ""
        must_lines.append(
            "表达母题策略："
            f"mode={mp_mode}；reason={mp_reason or '按近期重复度与当前语境控制'}；"
            f"allowed={mp_allowed}；blocked={mp_blocked}；fallback={mp_fallback or '换用非同类的角色化表达'}。"
            "若 mode=downrank，最终正文不得复用 blocked 或近义改写；除非用户明确要求重复、剧情事实连续性必须重复或角色核心身份必须重复。"
        )
    dedup_text = _format_expression_dedup_report(p.get("expression_dedup_report"), limit=5)
    if dedup_text:
        must_lines.append(
            "表达去重审阅："
            + _objective_stage2_material_line(
                dedup_text.replace("\n", "；"),
                520,
            )
            + "。本条是 Step 2 的表达观察报告，只用于选择非同类语气、动作、修辞、句式或节奏；它不是事实来源，不提供经历、故事、设定、人物地点事件或回忆内容。事实只按 Memory Recall、Fact Judgement、当前用户消息和设定锚点执行；不要在正文解释报告本身。"
        )
    relationship_stage = str(p.get("relationship_stage") or "uncertain").strip().lower()
    requested_escalation = str(p.get("requested_escalation") or "none").strip().lower()
    pressure_level = str(p.get("user_pressure_level") or "low").strip().lower()
    positive_feedback_user_text = bool(
        re.search(
            r"(靠近|靠过来|贴近|牵|抱|亲|吻|继续|别急着停|不急着停|不想停|没想停|舍不得停|今晚|想要|我也想)",
            current_user_text,
        )
    )
    if (
        relationship_stage in {"committed_partner", "intimate_partner"}
        and (
            requested_escalation in {"affection", "physical_intimacy", "sexual_intimacy"}
            or positive_feedback_user_text
        )
        and pressure_level != "high"
    ):
        must_lines.append(
            "伴侣亲密正反馈执行：若当前用户是在靠近、调情、亲吻、表达想继续或不急着停，最终回复必须体现角色自己的轻微主动意愿、靠近动作、想继续或愿意更近；"
            "外向角色可更热烈，内向/害羞/温柔/寡言角色可以只用一句短台词或一个小动作，但不能只剩“嗯/好/可以/点头/红脸/听你的/你说了算”。"
            "本条优先于“不要主动调情/避免热烈长句”和表达母题降频：可以不长篇、不露骨、不换成强势性格，但最短也要有角色自己的“我也想/别停/再一下/我愿意”这类短促愿意，或一个非同类的主动迎合动作。"
        )
        final_checks.append(
            "伴侣正反馈自检：去掉括号动作后，正文不能只剩“嗯/好/可以”等单字或纯被动许可；点头、红脸、耳朵动不算主动。"
            "至少有一句可见台词表达角色自己的我也想、不想停、继续、再一下、别停、愿意，或括号内出现明确主动迎合动作。"
        )
    if (
        relationship_stage == "intimate_partner"
        and requested_escalation == "sexual_intimacy"
        and pressure_level != "high"
    ):
        must_lines.append(
            "最高亲密硬性落点：最终正文至少自然出现一个成人合意性亲密相关身体部位，"
            "可用胸部、腰腹、胯部、大腿内侧、私密部位、敏感部位或生殖部位等词，按角色/用户物种体态自然改写；"
            "不能只用心跳、呼吸、体温、夜晚、温暖、普通贴近或派对物件替代。"
        )
        final_checks.append(
            "最高亲密自检：正文必须字面出现胸部、腰腹、胯部、大腿内侧、私密部位、敏感部位或生殖部位中的至少一个具体部位词；"
            "“身体每一寸”“体温”“呼吸”“心跳”“贴近”“整个人属于你”不算具体部位。"
        )
    must_lines.append(
        f"关系结论：stage={p.get('relationship_stage', 'uncertain')}，intimacy_style={p.get('character_intimacy_style', 'balanced')}，escalation={p.get('requested_escalation', 'none')}，pressure={p.get('user_pressure_level', 'low')}"
    )
    memory = _clip_line(p.get("memory_use_policy"), 360)
    if setting_anchor_priority and not minigame_memory_query:
        memory = ""
    memory_recall_text = format_memory_recall_for_stage3(p.get("memory_recall"))
    if setting_anchor_priority and not minigame_memory_query:
        memory_recall_text = _stage3_strip_lower_priority_entity_guidance(memory_recall_text)
    if setting_anchor_lines:
        must_lines.insert(
            0,
            "设定锚点硬落点：本轮若回答未明说的私人物件、门边熟人、亲友、地点或冷门细节，答案来源必须是这些设定锚点；"
            "表达调度、事实边界、记忆摘要里的具体人名/物件名/关系名只作低优先级背景或示例，不能覆盖锚点专名/关系/地点；锚点专名逐字复制，不改字形："
            + "；".join(setting_anchor_lines)
        )
    fact_judgement_text = format_fact_judgement_for_stage3(p.get("fact_judgement"))
    if setting_anchor_priority:
        fact_judgement_text = _stage3_strip_lower_priority_entity_guidance(fact_judgement_text)
    group_relationship_text = format_group_relationship_tension_for_stage3(
        p.get("group_relationship_tension")
    )
    story_progression_text = format_story_progression_for_stage3(p.get("story_progression"))
    emotion = _clip_line(p.get("emotion_blend"), 240)
    avoid_lines = _stage3_avoid_lines(p, self_unlikely)
    if setting_anchor_priority:
        entity_choice_re = re.compile(r"(门边|熟人|名字|关系|介绍).{0,24}(?:是|优先|使用|说明|叫|名)")
        avoid_lines = [line for line in avoid_lines if not entity_choice_re.search(str(line or ""))]
    if expression_contract["hard_blocked"]:
        avoid_lines.append(
            "本轮必须改用其他表达载体，避开这些表达母题/内容槽："
            + "、".join(expression_contract["hard_blocked"])
        )
    if expression_contract["warnings"]:
        avoid_lines.extend(expression_contract["warnings"])
    if body_fact_lines:
        avoid_lines.append(
            "身体事实禁混："
            + "；".join(body_fact_lines)
            + " 不得把这些事实改成反向位置，也不得只回答与问题无关的身体区域。"
        )
    if user_home_visit_lines:
        avoid_lines.append(
            "用户家来访禁混："
            + "；".join(user_home_visit_lines)
        )
    if suppressed_feasibility_materials:
        avoid_lines.append(
            "已移除与 Step 2 事实边界/行动可行性冲突的低优先级素材："
            + "；".join(dict.fromkeys(suppressed_feasibility_materials))
            + "。最终正文按 Step 2 场景锚点、事实边界或行动可行性改写；不要恢复被降级的旧位置、旧地点、无证据物品或刚完成动作。"
        )
    if scene_location_conflict_guard:
        avoid_lines.append(scene_location_conflict_guard)
    if unresolved_at_text:
        avoid_lines.append(
            "未解析 @ 禁止替换对象：当前用户 @ 的名字是「"
            + unresolved_at_names_text
            + "」；不要回答小露、朋友、其他熟人或任何未被当前用户 @ 的名字；陌生名没有认识证据时，不要写成“她没在/以她的性子/她会喜欢”。"
            "仅凭用户 @ 这个名字不能写“她今天没跟来/她不在这里/她会觉得”。"
            "不认识分支里不要再出现小露、朋友、其他熟人、她/他/对方的性子、如果也在、要是看到、会喜欢或会觉得。"
        )
    flavor_lines: list[str] = []
    if self_likely:
        self_likely_flavor = _sanitize_stage3_objective_material(
            self_likely,
            420,
            blocked_terms=expression_contract["hard_blocked"],
        )
        if self_likely_flavor and setting_anchor_priority:
            self_likely_flavor = _stage3_neutralize_entity_selection_examples(self_likely_flavor)
        if self_likely_flavor and _stage3_material_conflicts_action_feasibility(
            self_likely_flavor,
            feasibility_guard,
        ):
            self_likely_flavor = ""
        if self_likely_flavor and _stage3_material_conflicts_scene_boundary(
            self_likely_flavor,
            scene_boundary_guard,
        ):
            self_likely_flavor = ""
        if self_likely_flavor and _stage3_material_conflicts_concession_boundary(
            self_likely_flavor,
            concession_boundary_guard,
        ):
            self_likely_flavor = ""
        if self_likely_flavor:
            flavor_lines.append("可选倾向：" + self_likely_flavor)
    flavor_lines.append("角色风味只能点缀执行合同；若和【必须执行】冲突，优先执行合同。")

    priority_lines = [
        "P0 禁止项最高：事实边界、禁止推断、物种体态、用户明确禁令和表达硬禁用项不可违背。",
        "P0 旧事/引语归属硬禁：不得把希望/感觉/推测改写成某人说过、发生过、承诺过；摘要词同禁；只有素材给同一主体原话，才可写旧话。",
        "P0 stale/background_only 场景禁当前化：若任一事实边界或场景卡把旧地点、旧姿势、旧茶几、旧杯子、旧钥匙、旧书标为 stale/background_only/历史/作废/本轮禁止当前，且当前用户没有明确说继续旧场景，则正文不得主动提这些旧物名，也不得写正在看、刚刚在看、正在拿、仍在场或当前可见。",
        "P1 当前用户消息优先：先承接【本轮新事件】；若其他素材主体冲突，按用户原文和事实边界修正。",
        "P1 当前场景审计问句必须答全：若当前用户问现在位置、姿势、看到的画面、物品分别在哪里或点名多个物品/角色，最终正文必须覆盖每个被点名槽位；不能只答位置，不能只说“在你旁边/东西都在原处/没动过”。单气泡也要列齐这些事实。",
        "P1 完成式递交动作按已完成执行：当前用户消息若说“把 X 递给我/给我/交给我”并追问现在状态，X 的当前 holder/location 应写成用户处/用户手里；不得写成仍在角色手里、正准备递、递到面前但未交付。优先使用“X 在你手里/你这里/已经给你”这类完成状态表达。",
        "P1 体态改写请求：若用户要求身体术语应该怎么改，重点是按事实边界消除错误的人类身体部位词；不要让小马/马类角色把自己的身体末端写成指尖、手指或人类手部末端。允许自然改成蹄尖、蹄缘、前蹄、蹄子等蹄类表达。",
        "P1 提议/带路主体优先：移动、回家、去某处、邀请或带路必须按最近真实对话和事实边界保留发起者；用户提议回家/去某处时，不得写成角色开口让用户来、角色带用户回来或用户跟着角色回来。",
        "P1 当前动作方式优先：用户本轮给出怎样吃/喝/拿/递/碰/站/看/使用某物时，即使没有说“当前事实/现在/只有/只是”，最终正文也必须按本轮动作方式写；旧偏好、旧记忆、旧随身物和旧身体装饰不能把当前“沾/递/看/站/握住”改成旧的“舔/抱/系着/拿着”。",
        "P1 问题类型仲裁：问当前现场（在用什么/正在吃什么/现在拿着什么）时答最近对话/scene_anchor 里的精确名称和子类型；问旧记忆（之前说过/以前评价/还记得）时答 Memory Recall 命中的旧事实。长期偏好不能把当前“双板/蔬菜沙拉/青铜地图筒”替换成旧偏好或泛化词，当前现场也不能替代旧记忆答案。",
        "P2 事实边界次之：主体、归属、位置和已发生事实只按【Step 2 场景锚点卡】、【Step 2 记忆调用摘要】、【事实边界】与【当前事实锚】执行；若【事实边界】和【Step 2 记忆调用摘要】对身体结构、数量、主体或当前位置冲突，事实边界压过记忆摘要，记忆里的冲突项只当误导/禁用背景。",
        "P2 死亡/离场边界：若材料说某具名角色已死、已无生命迹象、有墓碑、已离场或当前不可参与，稳定亲属/同伴设定只作关系背景；不得写成该角色当前会醒来、看到、开门、询问、责怪、问东问西或正在屋内睡觉。",
        "P2 跨会话旧物禁升格：其他 conversation、长期/上下文记忆或上一场出现过的具体物品、身体装饰和地点，不是当前画面/身体状态；当前用户消息、最近可见对话或 scene_anchor 没有继续带入时，不得写成当前可见、正在持有、正在触碰、还在场，也不要否定式提到。",
        "P2 记忆禁升格：Step 2 记忆调用摘要里的 history_facts/forbidden_uses，事实边界里的 stale/background/unsupported_current_items，都不是当前可见事实；不得把这些内容写成此刻正在晃动、触碰、持有、看到或发生。若 writing_guidance 和 forbidden_uses 冲突，forbidden_uses 优先。",
        "P2 身体状态禁升格：physical_state.stale_states、stale/background、forbidden_current_items 非当前；旧醉酒/疲惫/伤势/牙膏味/酒味/咖啡味不得写成此刻体感。",
        "P2 长间隔 stale 禁当前化：若场景锚点卡状态为 stale、身体继承策略为 background_only、或列出历史/作废物品/本轮禁止当前项，除非当前用户明确说继续/刚才/还在/接着/那个场景，否则不得把旧地点、旧姿势、旧茶几、旧杯子、旧钥匙、旧书等写成正在看、刚刚在看、刚才在看、正在拿、仍在场、当前可见或当前所在；低连续性问候里也不要主动提这些旧物名。",
        "P3 表达去重：满足 P1/P2 后只换语气、动作、修辞、句式；Expression Dedup 不是事实来源。",
        "P4 角色风味最后：只作点缀，不能覆盖 P0-P3。",
    ]
    if body_fact_lines:
        priority_lines.insert(
            1,
            "P0 当前角色身体事实硬锚：用户问乳房/乳腺、胸前/肚子下方/臀部侧面、可爱标记、手/蹄等事实时，"
            "必须按【当前角色身体事实硬锚】回答；角色风味、寒暄、新联系人开场和稳定房间设定都不能覆盖。"
        )
    if user_home_visit_lines:
        priority_lines.insert(
            1,
            "P0 用户家首次来访硬锚：当前地点归属、熟悉程度、用户家储物和旧回忆必须按【用户家首次来访硬锚】执行；"
            "角色稳定住处、卧室、海报、奖杯、宠物或旧回复不能覆盖。"
        )
    if scene_location_conflict_guard:
        priority_lines.insert(
            8,
            "P2 当前地点冲突仲裁：当前地点、当前角色 position/posture 以及用来解释当前动作/衣服/身体状态的环境理由都必须跟随【Step 2 场景锚点卡】；长期记忆、上下文摘要、角色稳定住处、旧交通工具或旧回复里的其他地点只作历史，不能覆盖当前地点。",
        )
    if non_intimate_story_progression:
        priority_lines.insert(
            3,
            "P1 后续动作素材：沿最近目标/行动方向继续；场景锚点是起点，不是禁止抵达目标的终点。",
        )
        if completed_story_progression:
            anchor_label = story_required_anchor or "target/source 中的新方向"
            priority_lines.insert(
                4,
                "P1 已完成任务后续航：前一插入任务/旧目标已经完成，本轮最高优先级是显式落到「"
                + anchor_label
                + "」或 source 中的原计划/下一阶段；不得用模糊带路、未知地点、开窗夜空或无关支线替代。"
            )
    if unresolved_at_text:
        priority_lines.insert(
            1,
            "P0 未解析 @ 精确名字：本轮只判断并回应当前用户实际 @ 的「"
            + unresolved_at_names_text
            + "」；不得用记忆里的其他熟人或旁支角色顶替。认识证据必须来自设定/记忆/最近上下文中 exact name 的明确关系，用户刚刚 @ 不算证据；若无认识证据或只是拿不准，正文必须字面说不认识/没听过/不知道是谁/哪位，然后只给当前主角色自己的评价或追问对方是谁。"
        )
    if setting_anchor_priority:
        priority_lines.insert(
            1,
            "P0 设定锚点查询：用户问未明说实体时，具体名字、关系、地点、物件专名以【本轮相关角色设定】的设定锚点为准；表达调度、事实边界和记忆摘要里的同类人名/物名只作背景或示例，不参与实体选择。",
        )
    if minigame_memory_query:
        priority_lines.insert(
            1,
            "P0 刚结束小游戏/象棋记忆查询：当前用户在问刚结束游戏、A/B/C、赌注、口令、胜利留言、棋盘老师或兑现主体时，"
            "【Step 2 记忆调用摘要】里的 selected_facts/writing_guidance/forbidden_uses 高于设定锚点、场景锚点、Step 1 下一拍动作和表达调度。"
            "最终正文必须逐项答 A、B、C、胜负和兑现主体；C 中的“棋盘老师”必须原样出现，不得改成“那声称呼/一个要求/合理要求”。"
            "若 Step 2 同时给出用户明示 A/B/C 和角色错答旧 A/旧赌注，正文只答用户明示事实；不要主动写角色错误复述，除非用户问角色刚才答错了什么。"
        )
    if "设定锚点：" in profile_for_stage3:
        priority_lines.insert(
            3,
            "P2 稳定设定锚点：若用户问到未明说的私人物件、门边熟人、亲友、地点或冷门细节，优先使用【本轮相关角色设定】里的设定锚点；它来自完整角色设定，优先于同名作品常识或默认印象。",
        )
    if setting_anchor_priority:
        priority_lines.insert(
            4,
            "P2 设定锚点覆盖同类记忆：当【本轮相关角色设定】和【Step 2 记忆调用摘要】对同一类未明说实体给出不同专名、关系、物件或地点时，以设定锚点回答；记忆摘要只作背景，写作指导不得改写答案来源。",
        )
    if expression_contract["hard_blocked"]:
        priority_lines.append(
            "P0 本轮表达硬禁用/换载体：避开 "
            + "、".join(expression_contract["hard_blocked"])
            + "；最终正文优先采用替代表达和新动作组合。"
        )
    if has_vision_grounding:
        priority_lines.append(
            "P1 本轮图片输入优先：需要注意用户传的图；当用户当前消息是在展示、询问或回指图片时，"
            "必须先承接【图片识别上下文】或【历史图片上下文】里的画面说明，再兼顾场景锚点和其他事实边界。"
        )
    if expression_contract["soft_blocked"]:
        priority_lines.append(
            "P3 本轮表达降频："
            + "、".join(expression_contract["soft_blocked"])
            + "。除非当前用户消息必须承接，否则换角度。"
        )
    if expression_contract["replacements"]:
        priority_lines.append(
            "P3 表达载体建议（非事实素材）："
            + "；".join(expression_contract["replacements"])
            + "。这里只能当作语气、动作、修辞或句式方向；不得复制其中任何经历、故事、设定、人物、地点、事件或时间线，事实内容仍只按 P2。"
        )
    if suppressed_feasibility_materials:
        priority_lines.append(
            "P0 Step 2 事实边界/行动可行性已压过低优先级素材；被移除的素材不得在最终正文恢复为当前事实。"
        )
    if current_user_text_for_stage3:
        priority_lines.append(
            "P1 当前用户消息只表示用户做了/说了这些事；不要把第一人称动作改成角色动作。"
        )
        priority_lines.append(
            "P1 当前用户若是在核对场景状态，必须按用户点名顺序答位置、姿势和每个物品状态；短回复也要保留足够事实，不得用寒暄、情绪或泛化代词替代。合格形态示例是同一段内列齐“我在 X、姿势 Y；杯子在 A；钥匙在 B；书在 C”。"
        )
    if current_user_action_event:
        priority_lines.append("P1 若当前用户消息包含动作或场景说明，最终正文第一拍先响应该新事件。")
    if story_progression_text:
        if "成人合意亲密" in story_progression_text:
            priority_lines.append(
                "P1 亲密正反馈：当前用户在成人合意亲密场景中给出继续信号；未明确出现高潮/释放/余韵前，优先继续当前亲密链条并加深接触，压过普通地点/任务/休息/清理/毛巾/喝水/厨房/饰品/动物/农场/转场规则。外向角色可以更快抵达，内向/害羞/温柔角色允许慢热但仍要主动推进；极内向或寡言角色也要有自己的轻微主动意愿或靠近动作，不能只让用户决定；通用压力/第三人/公开隐私边界低于已建立的特殊亲密关系或玩法约定，当前用户明确停止/不适/退出时才按退出信号处理。"
            )
        else:
            priority_lines.append(
                "P1 后续动作素材：当前用户明确允许继续行动链，必须越过原地铺垫并落到具体世界内进展；"
                "若上文已有目的地/任务，优先写抵达、进入、开始执行或出现新情况。"
            )
            if completed_story_progression:
                anchor_label = story_required_anchor or "target/source 中的新方向"
                priority_lines.append(
                    "P1 已完成任务后推进：前一任务已完成，正文必须显式回到/开启「"
                    + anchor_label
                    + "」或 source 中的原计划/下一阶段，并写一个具体下一步；不要只写“我知道你要干嘛/跟我来/去的地方不远”。"
                )
    if group_relationship_text:
        priority_lines.append(
            "P1 临时 @ 群聊关系张力：若用户只 @ 当前角色，优先让当前角色评价现场、推进一拍或抛出问题；"
            "若存在伴侣/暧昧忠诚冲突，按角色性格表现对应强度，不要签到式回应。"
        )
    if current_user_action_terms:
        priority_lines.append(
            "P1 当前动作/要求含参考词时，正文第一拍必须承接其核心含义，不可只写泛化反应；参考词只在自然、视角正确时使用，不要求逐字复述："
            + current_user_action_terms_text
            + "。"
        )
    if expression_contract["hard_blocked"]:
        final_checks.append("P0 自检：最终正文没有复用本轮表达硬禁用词、近义动作或已标记 avoid 的内容槽。")
    final_checks.append(
        "旧事/引语自检：说过、那天、求婚、承诺、答应、约定等旧事必须有同一主体证据；摘要同禁"
    )
    if suppressed_feasibility_materials:
        final_checks.append(
            "P0 自检：最终正文没有把无证据当前物品写成已经带着、刚做、新烤/新做、昨天多做、早上刚做、还温着或已放进包里。"
        )
    if current_user_action_terms:
        final_checks.append(
            "首个气泡自检：bubbles[0].parts 已体现当前动作/要求的核心含义；没有为了证明承接而机械复述用户原句。参考词："
            + current_user_action_terms_text
            + "。"
        )
    final_checks.append(
        "场景锚点自检：若用户问当前地点/姿势/物品状态，正文已答到用户点名的每个槽位；若 scene_card 标为 stale/background_only，正文没有把历史物品或旧位置写成当前正在发生，也没有在低连续性问候里主动提旧物名。"
    )
    if setting_anchor_lines:
        final_checks.append(
            "设定锚点自检：如果本轮回答的是未明说实体/冷门设定，正文已经采用【本轮相关角色设定】中的专名、关系或独特描述，没有被记忆摘要里的旧物件/旧人物/写作指导覆盖。"
        )
    if scene_location_conflict_guard:
        final_checks.append(
            "当前地点自检：正文没有用 Step 2 场景锚点卡以外的旧地点、角色默认住处、旧交通工具或旧回复地点解释当前动作、衣服、身体状态、物品位置或环境感受。"
        )
    if unresolved_at_text:
        final_checks.append(
            "未解析 @ 自检：正文已经逐字回应「"
            + unresolved_at_names_text
            + "」；没有把其他熟人名替换成本轮 @ 对象。若没有认识证据，正文包含不认识/没听过/不知道是谁/哪位，并且没有替对方评价。"
        )
    selected_asset_context = _normal_stage3_selected_asset_block(
        selected_asset_attachments,
        p.get("reply_sequence"),
    )
    if selected_asset_context:
        final_checks.append(
            "表情包配文自检：如果本轮有文字气泡，文字已经贴合【本轮将发送的表情包/贴纸】的含义；没有另编一张不存在的表情包内容，也没有在文字里重复承诺“我发一个表情包”。"
        )

    sections = ["【普通对话 Step 3 主回复素材包】"]
    sections.append("【执行优先级合同】\n" + "\n".join(f"- {x}" for x in priority_lines if x.strip()))
    if scene_anchor_card:
        scene_anchor_intro = (
            "本节是当前画面、地点、角色位置/姿势和物品状态的最高优先级锚点；先读本节，再读记忆和角色设定。\n"
            "【Step 2 场景锚点卡｜时间、地点、各角色位置/姿势、物品】\n"
            "这是本轮普通对话的物理连续性强锚。无明确移动、换房间、姿势变化、拿放物品或重置时，必须保持卡片里的 location、各角色 position/posture 和 items。"
            "全局地点不等于每个角色的位置；写当前角色动作时优先用当前角色自己的 position/posture。角色稳定住处、卧室/床等高相关词和旧记忆不能覆盖当前锚点。"
            "若记忆、主页或旧回复里出现与本卡不同的地点，它们不能用来解释当前动作、衣服、身体状态、物品位置或环境感受；当前解释必须落在本卡地点/位置上。"
            "若本卡包含“状态: stale”“background_only”“历史/作废物品”或“本轮禁止写成当前物品”，这些内容不是当前画面；除非当前用户明确要求继续旧场景，最终正文禁止把这些历史地点/姿势/物品写成正在看、刚刚在看、正在拿、仍在现场或当前所在；低连续性问候里不要主动提旧物名。"
            "若用户正在问当前位置、姿势或物品分别在哪里，必须按本卡逐项回答用户点名的当前槽位；可以自然措辞，但不能漏掉被点名物品，不能被单气泡短答规则压缩成只答位置。"
        )
        if non_intimate_story_progression:
            scene_anchor_intro += (
                "后续动作例外：当前用户已经允许继续行动链，本节场景锚点只表示行动起点；"
                "若【后续动作素材】已有目标、下一方向或任务，应沿该方向自然越过原地准备/带路铺垫，直接写到抵达/进入目标，或目标处发生一个可见进展；这不算突然切换场景或时间。"
                "正文的重心放在目标处已经发生什么，而不是目标在哪里或正准备过去。"
            )
        scene_anchor_intro += (
            "若用户追问“现在在哪/刚才听见什么/刚才看见什么”，优先按此卡的角色-地点关系回答，不要用更旧的私聊位置覆盖群聊锚点。"
            "若同一句同时问当前位置、暗号/听见什么、另一个角色在哪，当前位置和其他角色位置优先看此卡与事实边界；若用户明确承接刚才群聊，且 Step 2 记忆调用摘要或事实边界里的临时群聊事实给出了当前角色/其他角色所在群聊位置，可把它作为比旧私聊场景更新的位置证据；暗号/听见/看见/同意/拒绝只看 Step 2 记忆调用摘要或事实边界里的临时群聊事实，两类材料都要答到。"
            "微观位置词只用于核对连续性，不要求逐字复述；若用户问其他角色在哪，回答保持角色名和位置关系清楚即可，可自然写成“她在她的床边那里/门口那边”。不能把 A 的位置写成 B 的位置，也不能回到更旧的私聊位置。\n"
        )
        sections.append(
            "【当前场景状态｜Step 2 场景锚点卡】\n"
            + scene_anchor_intro
            + scene_anchor_card[:1800]
        )
    if fact_judgement_text:
        sections.append(
            "【事实边界（已由 Step 2 判断，Step 3 只按此执行）】\n"
            + fact_judgement_text
        )
    if user_home_visit_lines:
        sections.append(
            "【用户家首次来访硬锚｜当前场景归属】\n"
            + "\n".join(f"- {line}" for line in user_home_visit_lines)
        )
    if body_fact_lines:
        sections.append(
            "【当前角色身体事实硬锚｜主页种族字段】\n"
            + "\n".join(f"- {line}" for line in body_fact_lines)
        )
    if state_parts.strip():
        sections.append("【当前事实锚｜低于场景状态卡，高于旧记忆】\n" + state_parts.strip()[:1200])
    if current_user_text_for_stage3:
        sections.append(
            "【本轮新事件（当前用户消息，优先承接）】\n"
            + current_user_text_for_stage3[:900]
            + "\n当前用户消息是本轮最高优先级的新输入。若它与表达调度中的旧事件、旧动作或旧话题侧重点不同，先承接当前用户消息；旧事件只作为背景余韵。"
        )
    if unresolved_at_text:
        sections.append(
            "【未解析 @ 当前名字硬锚｜先读】\n"
            "本节优先于记忆摘要和角色风味，防止把记忆里的其他人物误当成本轮 @ 对象。\n"
            + unresolved_at_text
        )
    if current_user_action_terms:
        sections.append(
            "【首个气泡语义锚点】\n"
            "- bubbles[0].parts 必须自然承接 Step 2 的当前用户动作/要求，体现其核心含义；不要为了证明承接而机械复述用户原句或硬塞参考词。参考词只在自然、符合角色口吻且人称视角正确时使用："
            + current_user_action_terms_text
            + "\n- "
            + current_user_action_guidance
            + "\n- 不合格写法：只写“嗯”“好”“收到啦”“走吧”“你带路”“转过身”“早上好”“有什么事”“这种打招呼方式”等泛化回应，而没有体现用户刚才动作/要求造成的即时反应或承接结果；也不要把用户对角色说的“你……”类命令原样当成角色台词，或把该动作任务转派回用户。"
        )
    if memory_recall_text:
        memory_intro = (
            "这是 Step 2 从原始长期记忆、上下文记忆、临时群聊见闻和最近对话中压缩出的记忆摘要；Step 3 不再读取原始记忆，也不得把摘要里的抽象关系词扩写成不存在的旧事细节或逐字引语。若本段分成“可直接使用”和“历史背景”，只有可直接使用部分能当本轮事实；历史背景不得写成当前正在发生的动作、姿势、身体接触或物品状态。"
        )
        if scene_location_conflict_guard:
            memory_intro += (
                "若记忆摘要或上下文摘要里的地点与【Step 2 场景锚点卡】不同，该地点只算历史背景或旧回复内容；"
                "不得把它写成当前所在地点，也不得拿它解释当前动作、衣服、身体状态、物品位置或环境感受。"
            )
        if setting_anchor_priority:
            memory_intro += (
                "但本轮属于设定锚点查询时，记忆摘要只能用于避免已发生事实冲突，不能覆盖【本轮相关角色设定】里的专名、关系、物件或地点锚点。"
            )
        sections.append(
            "【Step 2 记忆调用摘要｜已筛选，可供本轮直接使用】\n"
            + memory_intro
            + "\n"
            + memory_recall_text
        )
    if memory:
        sections.append("【本轮可用事实】\n" + memory)
    if group_relationship_text:
        sections.append(
            "【临时 @ 群聊关系张力】\n"
            "这是本轮 @ 临时群聊的关系/现场反应口径；它不等于关系确认请求，必须服从角色设定和可见证据。\n"
            + group_relationship_text
        )
    if unresolved_at_text:
        sections.append("【未解析 @ 当前名字硬锚｜输出前复核】\n" + unresolved_at_text)
    if story_progression_text:
        story_intro = (
            "本节给出本轮应写到的后续动作；它要求可见的世界内进展，不是原地再确认。\n"
        )
        if "成人合意亲密" in story_progression_text:
            story_intro = (
                "本节给出本轮应写到的亲密继续动作；当前是成人合意亲密场景。"
                "未明确出现高潮、顶峰、释放、余韵或事后前，世界内进展就是继续当前亲密链条，而不是地点、任务、休息、清理、毛巾、喝水、厨房、饰品、动物、农场或日常转场；内向角色也必须主动推进，只是更轻，极内向或寡言角色也要有自己的轻微主动意愿或靠近动作，不能只让用户决定。若有已建立的特殊亲密关系或玩法约定，按该关系和角色主体性执行，不套普通伴侣模板。"
                + "\n"
            )
        else:
            story_intro += (
                "若当前场景锚点仍在上一地点，它只提供起始位置和事实边界；本轮应沿最近目标/行动方向自然转场到后续世界内事件，并让用户看见抵达、进入或目标处的一步进展。\n"
                "合格正文要把重点落到目标处已发生的动作、发现、处理或第三方反应，例如已经进屋坐下换药、已经来到围栏旁检查、已经翻开记录本看到线索。\n"
                "如果目标、场景锚点或事实边界已经给出明确地点名，推进时必须沿用这个地点名或同一地点，不能把它换成工具间、厨房、卧室、住所、门口或其他相邻/常见地点。\n"
            )
            if completed_story_progression:
                anchor_label = story_required_anchor or "target/source 中的新方向"
                story_intro += (
                    "本轮还是已完成插入任务后的推进：前一任务只能作为历史背景，正文必须显式落到「"
                    + anchor_label
                    + "」或 source 中的原计划/下一阶段；不能只用“我知道你要干嘛”“跟我来”“去的地方不远”、未知地点、开窗夜空或新支线替代。\n"
                )
        sections.append(
            "【后续动作素材】\n"
            + story_intro
            + story_progression_text
        )
    if selected_asset_context:
        sections.append(selected_asset_context)
    if setting_anchor_lines:
        sections.append(
            "【本轮设定答案锚点】\n"
            "问冷门/未明说设定时用本节专名；问当前画面/位置/姿势/物品状态时只按【Step 2 场景锚点卡】，稳定住处/房间装饰不能覆盖，除非 scene_anchor 明确在该房间。\n"
            + "\n".join(f"- {line}" for line in setting_anchor_lines)
        )
    if homepage_profile:
        sections.append(
            "【参考资料：角色主页档案（每轮固定注入）】\n"
            "这些字段来自角色主页档案，属于稳定角色设定；当用户询问角色自己的年龄、性别、种族、16人格、性格、兴趣、简介或身份时，优先使用这里的明确字段；它们不是当前可见场景证据。\n"
            "其中 16人格 只提供性格倾向参考，用来辅助表达风格、决策倾向和互动节奏。\n"
            "若【事实边界】、【必须执行】或【避免跑偏】已经给出当前立场、结果、动作主体或位置，主页档案里的性格词只能作口吻背景，不能覆盖当前已确认事实；例如已确认认输后，不要再从主页简介里的好胜/不服输写回当前不服输。\n"
            + homepage_profile
        )
    if profile_for_stage3:
        sections.append(
            "【参考资料：本轮相关角色设定（已由 Step 2 自我认知摘取，非完整设定）】\n"
            "当前画面/位置/姿势/物品以【当前场景状态】为准。\n"
            + profile_for_stage3
        )
    if alias_note:
        sections.append("【当前角色别名归属】\n" + alias_note)
    if expression_brief.strip():
        sections.append("【表达变化】\n" + expression_brief.strip()[:700])
    if emotion:
        sections.append("【情绪融合】\n" + emotion)
    if flavor_lines:
        sections.append("【可选角色风味】\n" + "\n".join(f"- {x}" for x in flavor_lines if x.strip()))
    sections.append("【必须执行】\n" + "\n".join(f"- {x}" for x in must_lines if x.strip()))
    if avoid_lines:
        sections.append("【避免跑偏】\n" + "\n".join(f"- {x}" for x in avoid_lines if x.strip()))
    sections.append("【JSON 气泡规划】\n" + "\n".join(f"- {x}" for x in bubble_plan_lines if x.strip()))
    sections.append("【正文写法】\n" + "\n".join(f"- {x}" for x in writing_lines if x.strip()))
    if memory_recall_text:
        sections.append(
            "【最终事实覆盖复核｜Step 2 记忆召回优先】\n"
            "如果本节与前面的下一拍动作、表达调度、自我认知倾向、设定锚点或主动建议冲突，最终正文必须按本节写；"
            "本节中的 forbidden_uses 不得被更早材料重新启用。尤其当本节写明赌注升级为 C、C 是当前有效版本或旧赌约禁用时，"
            "不得输出“没有升级成C/只有B/按旧赌约兑现”。用户问 A/B/C、赌注或兑现时，A、B、C、胜负和兑现主体必须逐项答全；"
            "C 中的专名如“棋盘老师”必须原样出现，不得改写成“那声称呼/合理要求/一个要求”。"
            "若本节同时给出用户明示 A/B/C 和角色错答旧 A/旧赌注，最终正文只答用户明示事实；角色错误复述不能作为当前 A/B/C 答案，也不要主动写入正文，除非用户问角色刚才答错了什么。\n"
            + memory_recall_text[:1800]
        )
    if final_checks:
        sections.append("【输出前自检】\n" + "\n".join(f"- {x}" for x in final_checks if x.strip()))
    sections.append("输出 Step 3 JSON；正文写 bubbles[*].parts。")
    return "\n\n".join(sections)


def build_normal_mode_augment_block(
    *,
    vision_context: Optional[NormalVisionContext] = None,
    search_context: str = "",
    planner_result: Optional[Dict[str, Any]] = None,
    prior_image_injection_text: str = "",
    recent_messages: Optional[List[dict]] = None,
    revision_context: str = "",
    user_species: str = "",
    is_new_contact_opening: bool = False,
    character_prompt_context: str = "",
    raw_character_prompt_context: str = "",
    scene_anchor_card: str = "",
    guest_group_memory: str = "",
    compact_reply_frame: bool = True,
    at_event_context: Optional[Dict[str, Any]] = None,
    selected_asset_attachments: Optional[List[Any]] = None,
) -> str:
    """构建导演增强块字符串（不修改消息列表），供延迟注入使用。
    包含：图片上下文(本轮) -> 历史图片上下文 -> 联网摘要 -> 本轮导演策略。
    """
    parts: List[str] = []
    if vision_context and (
        vision_context.image_summary
        or vision_context.web_research_summary
        or vision_context.should_refuse
        or vision_context.error
    ):
        parts.append(_vision_context_block(vision_context))
    pr = planner_result or {}
    use_prior = bool(pr.get("use_prior_image_context")) and bool(
        (prior_image_injection_text or "").strip()
    )
    if use_prior and prior_image_injection_text:
        parts.append(prior_image_injection_text.strip())
    has_vision_grounding = bool(
        (vision_context
        and not vision_context.should_refuse
        and (vision_context.image_summary or vision_context.web_research_summary))
        or (use_prior and bool((prior_image_injection_text or "").strip()))
    )
    sb = _search_block(search_context)
    if sb:
        parts.append(sb)
    current_user_text = _latest_user_actual_text(recent_messages)
    guest_group_memory_text = str(guest_group_memory or "").strip()
    if guest_group_memory_text and re.search(
        r"(刚才群聊|群聊之后|群聊里|被\s*@|暗号|口令|特别词|听见|看见|现在.*(?:位置|在哪|哪里|哪儿)|当前位置|哪个位置|另一个角色在哪)",
        current_user_text,
    ):
        parts.append(
            "【当前角色最近临时群聊见闻｜供本轮正文直接使用】\n"
            "用户正在追问刚才群聊/暗号/位置时，本节是当前角色自己的最近见闻。"
            "如果本节明确写了当前角色或其他角色在群聊现场的位置，而旧 scene_anchor 仍指向更早私聊房间，"
            "本轮正文应把本节位置当作更新的近因证据；若下方 Step 2 场景锚点卡仍写旧测试房间、窗边地毯或旧私聊位置，"
            "且当前用户说的是“刚才群聊之后/刚才群聊里/被 @ 以后”，本节群聊位置优先，正文不得回答旧私聊位置。"
            "暗号/口令/特别词必须逐字复述完整短语。\n"
            + guest_group_memory_text[:1400]
        )
    # Step 2 已经处理近期重复风险；Step 3 只接收一小段正向表达变化。
    expression_brief = _build_normal_stage3_expression_brief(recent_messages)
    if planner_result:
        if not compact_reply_frame:
            try:
                from .emotion_state import format_emotion_block_for_reply

                emotion_block = format_emotion_block_for_reply(planner_result, None)
                if emotion_block:
                    parts.append(emotion_block)
            except Exception:
                pass
        if compact_reply_frame:
            parts.append(
                _normal_reply_frame_block(
                    planner_result,
                    character_prompt_context=character_prompt_context,
                    raw_character_prompt_context=raw_character_prompt_context,
                    current_user_text=current_user_text,
                    has_vision_grounding=has_vision_grounding,
                    expression_brief=expression_brief,
                    scene_anchor_card=scene_anchor_card,
                    at_event_context=at_event_context,
                    selected_asset_attachments=selected_asset_attachments,
                )
            )
        else:
            selected_asset_context = _normal_stage3_selected_asset_block(
                selected_asset_attachments,
                pr.get("reply_sequence"),
            )
            if selected_asset_context:
                parts.append(selected_asset_context)
            parts.append(
                _planner_policy_block(planner_result, has_vision_grounding=has_vision_grounding)
            )
    if (not compact_reply_frame) and (
        is_new_contact_opening
        or user_message_requests_memory_evidence(_latest_user_text(recent_messages))
        or _planner_mentions_memory_probe(planner_result)
    ):
        parts.append(MEMORY_EVIDENCE_GUARD_TEXT)
    if (not compact_reply_frame) and is_new_contact_opening:
        parts.append(
            "【新联系人开场硬性边界】\n"
            "当前用户与角色刚刚添加联系方式，当前会话尚无角色历史回复。角色可以知道对方显示名，但必须把对方当作刚认识、刚开始聊天的人来对待。\n"
            "必须避免老熟人、久别重逢或已经很亲密的口吻，例如“是你啊”“当然认识”“不记得我了吗”“你终于来找我了”“好久不见”“又来啦”“我等你好久了”。\n"
            "优先使用自然问候、简短自我介绍、轻量好奇或低压力问题；即使角色性格外向，也只能表现为友好热情，不能越过新联系人边界。"
        )
    user_species_block = _build_user_species_body_guidance(
        user_species=user_species,
        planner_result=planner_result,
        recent_messages=recent_messages,
    )
    if user_species_block:
        parts.append(user_species_block)
    if (revision_context or "").strip():
        parts.append((revision_context or "").strip())
    return "\n\n".join(parts)
