from __future__ import annotations



async def plan_normal_conversation(
    recent_messages: List[dict],
    router_cfg: dict,
    *,
    vision_context: Optional[NormalVisionContext] = None,
    current_image_pending: bool = False,
    environment_context: str = "",
    character_prompt_context: str = "",
    username: Optional[str] = None,
    character_id: Optional[str] = None,
    main_character_id: Optional[str] = None,
    prior_stored_count: int = 0,
    last_reply_based_on_image: bool = False,
    debug_mode: str = "normal",
    debug_stage_prefix: str = "NORMAL_STEP_1",
    charge_membership_chat_quota: Optional[bool] = None,
    debug_role_params: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    与 classify_conversation 同入口（router_cfg + recent_messages），
    返回扩展后的 planner 结果；失败时与旧路由一致，退化为无联网默认。
    """
    if not router_cfg or not router_cfg.get("api_key"):
        logger.warning("[NormalPlanner] 无 chat_router 模型配置，使用默认")
        return default_planner_result()

    blocks = _recent_to_blocks(recent_messages)
    extra = ""
    if vision_context and (
        vision_context.image_summary
        or vision_context.web_research_summary
        or vision_context.should_refuse
        or vision_context.error
    ):
        parts = []
        if vision_context.should_refuse:
            parts.append(
                "【用户上传图片·系统拦截（系统内部）】\n"
                "图片被系统拒绝识别。不要向下游暴露任何图像细节、OCR 或拒绝原文；"
                "本轮应让角色用符合人设的方式简短说明图片被拦截，并自然转向其他可聊内容。"
            )
        elif vision_context.image_summary:
            parts.append("【用户上传图片·客观描述（系统内部）】\n" + vision_context.image_summary)
        if not vision_context.should_refuse and vision_context.visible_text:
            parts.append("【图内文字】\n" + vision_context.visible_text)
        if not vision_context.should_refuse and vision_context.identified_entities:
            parts.append("【实体】 " + "、".join(vision_context.identified_entities))
        if not vision_context.should_refuse and vision_context.uncertainty:
            parts.append("【不确定点】\n" + vision_context.uncertainty)
        if not vision_context.should_refuse and vision_context.web_research_summary:
            parts.append(
                "【图片侧联网检索摘要（已检索）】\n" + vision_context.web_research_summary
            )
        if vision_context.used_vision_plus_web and not vision_context.should_refuse:
            parts.append("（已尝试图片+联网，除非用户还有独立纯文本检索需求，勿重复开联网。）")
        extra = "\n\n" + "\n\n".join(parts)

    pcount = max(0, int(prior_stored_count or 0))
    state_block = (
        f"\n\n【近期图片上下文（仅状态，主模型**不会**把历史画面摘要发给你，请勿编造画面）】\n"
        f"已保存的识图组数：{pcount}\n"
        f"上一轮角色回复是否主要基于用户此前上传的图/截图："
        f"{'是' if last_reply_based_on_image else '否'}\n"
        "注意：这只是历史图片状态，不代表用户本轮上传或分享了图片；没有【用户上传图片·客观描述】时，禁止猜测具体画面内容。\n"
    )
    if pcount == 0:
        state_block += "（无历史识图可引用；本字段中 use_prior_image_context 必须为 false。）\n"
    can_use_prior = pcount > 0

    env_block = ""
    env_text = (environment_context or "").strip()
    if env_text:
        env_block = "\n\n【客户端环境上下文】\n" + env_text

    current_speaker_id = str(character_id or "").strip()
    main_speaker_id = str(main_character_id or character_id or "").strip()

    voice_mode_block = _voice_mode_context_block(
        recent_messages,
        current_speaker_character_id=current_speaker_id,
        main_character_id=main_speaker_id,
    )
    if voice_mode_block:
        extra += "\n\n" + voice_mode_block
    reply_language_block = _reply_language_context_block(
        recent_messages,
        current_speaker_character_id=current_speaker_id,
        main_character_id=main_speaker_id,
    )
    if reply_language_block:
        extra += "\n\n" + reply_language_block

    repeated_commitment_block = _build_repeated_commitment_guard_block(recent_messages)
    if repeated_commitment_block:
        extra += "\n\n" + repeated_commitment_block

    user_blob = f"【对话片段】\n{blocks or '（无）'}" + extra + env_block + state_block
    if len(user_blob) > 24000:
        user_blob = user_blob[:24000] + "\n（截断）"

    model_name = router_cfg.get("model_name") or "deepseek-v4-flash"
    debug_mode = (debug_mode or "normal").strip() or "normal"
    debug_stage_prefix = (debug_stage_prefix or "NORMAL_STEP_1").strip() or "NORMAL_STEP_1"
    reasoning_policy = resolve_software_reasoning_policy(
        "normal_planner",
        model_name=model_name,
        mode="normal",
        active_model=router_cfg,
        endpoint=router_cfg.get("endpoint", ""),
        requested_enabled=False,
        requested_effort="minimal",
    )
    # 普通对话步骤工具只做结构化路由/策略输出，不需要深度思考链。
    reasoning_policy = apply_normal_thinking_switch(
        reasoning_policy,
        enable_high_thinking=NORMAL_DIRECTOR_THINKING_HIGH,
    )
    try:
        decision_raw = await _run_parallel_step1_decisions(
            user_blob=user_blob,
            character_prompt_context=character_prompt_context,
            router_cfg=router_cfg,
            model_name=model_name,
            reasoning_policy=reasoning_policy,
            username=username,
            character_id=character_id,
            debug_mode=debug_mode,
            debug_stage_prefix=debug_stage_prefix,
            charge_membership_chat_quota=charge_membership_chat_quota,
            debug_role_params=debug_role_params,
        )
        owned = {
            k: v
            for k, v in (decision_raw or {}).items()
            if k in STEP1_DECISION_FIELDS
        }
        coerced = _coerce_planner(
            {**default_planner_result(), **owned},
            can_use_prior_image_context=can_use_prior,
        )
        coerced = apply_post_party_scene_arbitration(
            coerced,
            recent_messages,
            environment_context,
        )
        coerced = _apply_explicit_rhetoric_guard(coerced, recent_messages)
        coerced = _apply_expression_motif_guard(coerced, recent_messages)
        coerced = _apply_user_requested_repetition_policy(coerced, recent_messages)
        coerced = _apply_repeated_commitment_guard(coerced, recent_messages)
        coerced = apply_story_progression_policy(coerced, recent_messages)
        coerced = _apply_mention_only_guard(coerced, recent_messages)
        coerced = _apply_supportive_low_info_text_guard(coerced, recent_messages, user_blob=user_blob)
        coerced = _apply_step1_delivery_contract(
            coerced,
            recent_messages,
            current_speaker_character_id=current_speaker_id,
            main_character_id=main_speaker_id,
        )
        return apply_missing_current_image_guard(
            coerced,
            recent_messages,
            vision_context=vision_context,
            current_image_pending=current_image_pending,
        )
    except Exception as e:
        logger.warning("[NormalPlanner] Step 1 意图识别失败，返回默认规划: %s", e)
        await save_chat_debug_log(
            username, character_id, debug_mode, model_name, str(e), f"{debug_stage_prefix}_INTENT_RECOGNITION_ERROR",
            params=debug_role_params,
        )
        return default_planner_result()


def _vision_context_block(vision: NormalVisionContext) -> str:
    lines: List[str] = [
        "【图片识别上下文｜本轮用户上传图片，必须重视】",
        "（系统内部，非用户原文。主模型无视觉，以下由视觉/联网子任务生成；需要注意用户传的图，本节就是本轮图片附件的识别内容。）",
    ]
    if vision.should_refuse:
        lines.append(
            "图片被系统拒绝识别。不要描述、猜测或复述图片内容，不要提及任何识图模型/审核模型/内部策略。"
        )
        lines.append(
            "请让角色用符合人设的自然语气表达：这张图被系统拦截了，不能继续看或讨论这张图；"
            "随后主动把话题转到其他安全内容。可参考但不要逐字照抄：「你发的图片被系统拦截了，我们讨论一下其他内容吧。」"
        )
        return "\n".join(lines)
    if vision.error and not vision.image_summary and not vision.web_research_summary:
        lines.append(f"（识图未完全成功：{vision.error}。请只根据用户文字与常识回应，勿编造图中细节。）")
        return "\n".join(lines)
    if vision.image_summary:
        lines.append(vision.image_summary)
    if vision.visible_text:
        lines.append("图中可读文字：" + vision.visible_text)
    if vision.identified_entities:
        lines.append("实体：" + "、".join(vision.identified_entities))
    if vision.uncertainty:
        lines.append("不确定点：" + vision.uncertainty)
    if vision.web_research_summary:
        lines.append("联网检索（与图相关，已代查）：" + vision.web_research_summary)
    if vision.sources:
        s_lines = [f"- {s.get('title', '')} {s.get('url', '')}" for s in vision.sources[:5]]
        lines.append("参考链接：\n" + "\n".join(s_lines))
    multi_image_requirement = ""
    summary = vision.image_summary or ""
    if any(marker in summary for marker in ("第一张", "第二张", "第三张", "第四张", "第1张", "第2张", "第3张", "第4张")):
        multi_image_requirement = (
            "若上文描述了多张图或多个分图，本轮必须自然覆盖每一张/每一组主要内容，"
            "可以每张只用一句短评，但不得跳过中间图片；尤其不要只回应第一张和最后一张。"
        )
    lines.append(
        "【图片回应要求】请按角色自然回复。不要用「我调用了识图/另一模型」等元说法；可当作你已理解画面内容来互动。\n"
        "【硬性要求】本轮台词必须以上文画面说明为依据，至少自然点出一处具体信息（人物、物品、品牌、图中文字、色彩或整体氛围等）。"
        "禁止仅用泛泛的好奇、追问或「快给我看看」「是什么」式套话，而忽略上文已写明的细节；若「不确定点」有内容，仅在该范围内表述，不得编造其外细节。"
        + (f"\n【多图要求】{multi_image_requirement}" if multi_image_requirement else "")
    )
    return "\n".join(lines)


def _planner_state_policy_blocks(p: Dict[str, Any]) -> str:
    blocks: List[str] = []
    state = p.get("state_anchor") if isinstance(p, dict) else {}
    if isinstance(state, dict) and state:
        lines: List[str] = []
        for key, value in state.items():
            if value is None:
                continue
            text = str(value).strip()
            if text:
                lines.append(f"- {key}: {text[:300]}")
        if lines:
            blocks.append(
                "【当前事实锚（优先级高于角色默认设定）】\n"
                + "\n".join(lines)
            )

    corrections = p.get("corrections") if isinstance(p, dict) else []
    if isinstance(corrections, list) and corrections:
        lines = []
        for item in corrections:
            if not isinstance(item, dict):
                continue
            wrong = str(item.get("wrong_fact") or "").strip()
            correct = str(item.get("correct_fact") or "").strip()
            source = str(item.get("source") or "").strip()
            if wrong or correct:
                line = f"- 作废: {wrong[:300] or '未明确'}；改为: {correct[:300] or '未明确'}"
                if source:
                    line += f"；来源: {source[:80]}"
                lines.append(line)
        if lines:
            blocks.append(
                "【用户纠错/作废事实】\n"
                "本轮按下面的新事实自然承接。\n"
                + "\n".join(lines)
            )

    return ("\n".join(blocks).strip() + "\n") if blocks else ""


def build_planner_memory_notes(planner_result: Optional[Dict[str, Any]]) -> str:
    p = planner_result or {}
    blocks: List[str] = []
    state = p.get("state_anchor")
    if isinstance(state, dict) and state:
        items = []
        for key, value in state.items():
            text = str(value).strip()
            if text:
                items.append(f"{key}={text[:200]}")
        if items:
            blocks.append("当前事实锚：" + "；".join(items))

    corrections = p.get("corrections")
    if isinstance(corrections, list) and corrections:
        lines = []
        for item in corrections:
            if not isinstance(item, dict):
                continue
            wrong = str(item.get("wrong_fact") or "").strip()
            correct = str(item.get("correct_fact") or "").strip()
            if wrong or correct:
                lines.append(f"作废“{wrong[:200] or '未明确'}”，改为“{correct[:200] or '未明确'}”")
        if lines:
            blocks.append("用户纠错：" + "；".join(lines))

    avoid = p.get("avoid_contradictions")
    if isinstance(avoid, list) and avoid:
        lines = [str(x).strip()[:200] for x in avoid if str(x).strip()]
        if lines:
            blocks.append("后续避免：" + "；".join(lines))

    fact = p.get("fact_judgement")
    if isinstance(fact, dict):
        report = _coerce_fact_judgement(fact)
        boundary_lines: list[str] = []
        scene_card = str(report.get("scene_card") or "").strip()
        if scene_card:
            boundary_lines.append(
                "场景锚点（防污染）："
                + scene_card[:700]
                + "；若最终回复里的地点/姿势/物品与本锚点冲突，记忆写入必须按锚点降级或省略冲突内容。"
            )
        elif report.get("scene_anchor"):
            boundary_lines.append(
                "场景锚点（防污染）："
                + json.dumps(report.get("scene_anchor"), ensure_ascii=False)[:700]
                + "；若最终回复里的地点/姿势/物品与本锚点冲突，记忆写入必须按锚点降级或省略冲突内容。"
            )
        for key, label, limit in (
            ("subject_boundaries", "主体边界", 4),
            ("forbidden_inferences", "禁止推断", 4),
            ("uncertainty_points", "不确定点", 3),
        ):
            values = report.get(key)
            if isinstance(values, list):
                selected = [str(x).strip()[:180] for x in values if str(x).strip()][:limit]
                if selected:
                    boundary_lines.append(f"{label}：" + "；".join(selected))
        feasibility = report.get("action_feasibility") if isinstance(report.get("action_feasibility"), dict) else {}
        unsupported = (
            feasibility.get("unsupported_current_items")
            if isinstance(feasibility.get("unsupported_current_items"), list)
            else []
        )
        constraints = feasibility.get("constraints") if isinstance(feasibility.get("constraints"), list) else []
        guidance = str(feasibility.get("guidance") or "").strip()
        feasibility_lines = [str(x).strip()[:160] for x in unsupported if str(x).strip()][:4]
        constraint_lines = [str(x).strip()[:180] for x in constraints if str(x).strip()][:4]
        if feasibility_lines or constraint_lines or guidance:
            msg = []
            if feasibility_lines:
                msg.append("无证据当前持有/刚完成：" + "；".join(feasibility_lines))
            if constraint_lines:
                msg.append("可行性约束：" + "；".join(constraint_lines))
            if guidance:
                msg.append("改写指导：" + guidance[:220])
            boundary_lines.append("行动/物品可行性：" + "；".join(msg))
        if boundary_lines:
            blocks.append("事实边界：" + "\n".join(boundary_lines))

    return "\n".join(blocks).strip()[:2000]


def _reply_output_contract(
    *,
    bubble_count: int,
    action_style: str,
    reply_level: int = 3,
    expression_policy: str = "",
    voice_reply_enabled: bool = False,
) -> tuple[str, str]:
    """Return a compact executable output contract for the main reply model."""
    description_only = "合法描写/写法请求硬性格式" in (expression_policy or "")
    if description_only:
        contract = (
            f"【本轮输出合同｜本轮执行合同】\n"
            f"- text_bubbles={bubble_count}，最终正文必须正好 {bubble_count} 个非空气泡；每个非空换行段会被拆成一个气泡。\n"
            "- paragraph_format=full_bracket_description：每个气泡都必须独立完整使用全角括号（……），每行以「（」开头、以「）」结尾。\n"
            "- dialogue_allowed=false：本轮禁止普通聊天台词、反问用户、解释系统或解释为什么这样写。\n"
            "- max_chars_per_bubble≈180：每个气泡只写一个镜头或状态层次；长内容必须拆到下一个气泡。\n"
        )
        rule = (
            "本轮是合法描写/写法请求，必须输出纯描写合同：每个非空气泡都是独立闭合的（……）格式，"
            "禁止普通聊天台词、裸写旁白、跨段大括号、反问用户或把多个状态层次塞进一个超长气泡。"
        )
        return contract, rule

    if bubble_count == 1:
        bubble_line = "text_bubbles=1，最终正文必须是 1 个非空气泡，不要换行。"
    else:
        bubble_line = (
            f"text_bubbles={bubble_count}，最终正文必须正好 {bubble_count} 个非空气泡；"
            f"用换行分隔，不能合并成一大段，也不能多于 {bubble_count} 段。"
        )
    reply_level = max(1, min(5, int(reply_level or 3)))
    paragraph_format = {
        1: "silent：角色不回复；正常不进入主回复步骤。",
        2: "short_single：一个约10字短气泡；无括号短台词，或整个气泡是一个短括号动作。",
        3: "compact_chat：1-2 个气泡；可选一个短括号描述。",
        4: "multi_bubble_chat：3-4 个气泡；可选少量括号描述气泡。",
        5: "expanded_chat：5-6 个气泡；可选更充分但仍克制的括号描述气泡。",
    }.get(reply_level, "compact_chat：1-2 个气泡；可选一个短括号描述。")
    contract = (
        "【本轮输出合同｜本轮执行合同】\n"
        f"- {bubble_line}\n"
        f"- paragraph_format={paragraph_format}\n"
        "- 不要输出标题、列表、编号、解释、系统说明或 markdown。\n"
    )
    if voice_reply_enabled:
        contract += (
            "- voice_reply=true：后端会优先使用语音专用步骤；若该步骤失败并回退到当前正文，可朗读段仍会作为语音消息发送。\n"
            "- voice_fallback_paragraph_format：每个非空段落必须二选一：① 完全无括号的口语台词；② 整段从「（」开头并以「）」结尾的完整非对白括号段。\n"
            "- 禁止语音段混合括号动作：不要写「你好（开心地笑了笑），你叫什么名字？」这类同段混合；动作必须拆成独立完整括号段，或删掉动作只保留台词。\n"
        )
    if bubble_count == 1:
        bubble_rule = "本轮必须输出 1 个非空气泡：不要换行。"
    else:
        bubble_rule = (
            f"本轮必须输出 {bubble_count} 个非空气泡：用换行分隔，"
            f"最终正文应正好有 {bubble_count} 个非空段落；不要合并成一大段，也不要超出。"
            "短感叹句、短反问、短回应可以单独成气泡。"
        )
    level_rule = {
        1: "第一档表示角色不回复；正常情况下不应进入主回复。",
        2: "第二档只允许一个短气泡：短台词约10字，或整个气泡只是一个短括号动作，例如（我点头）。不要把括号和台词混在一起。",
        3: "第三档允许 1-2 个气泡；默认以台词为主，如需动作、表情、感受或环境，最多 1 个短括号片段。",
        4: "第四档允许 3-4 个气泡；可以安排少量括号描述气泡，但不要每个气泡都写动作或心理。",
        5: "第五档允许 5-6 个气泡；适合用户要求详细、复杂情绪或高主动推进，可使用更充分但仍克制的括号描述。",
    }[reply_level]
    action_rule = {
        "plain_text": "action_style=plain_text：普通聊天优先纯台词，把角色味道写进直接说出口的话；若表达调度明确写“只台词/不要括号/不要动作”，最终正文必须完全无括号。",
        "light_inline": "action_style=light_inline：允许回复档位内的短括号辅助；凡是心理描写、身体感受、动作、环境，都使用全角括号（……），不要裸写成小说叙事。",
        "cinematic": "action_style=cinematic：用户要求或允许描写；动作、心理、身体状态、环境都使用全角括号（……），每个括号片段独立闭合，不要跨气泡包住全文。",
    }[action_style]
    action_rule += (
        "括号位置不限，可在句首、句中或句尾，也可以写用户和第三方互动；"
        "描述当前角色自己时用角色视角，不写「她说完/角色名轻轻笑了笑」这类外部旁白。"
    )
    if voice_reply_enabled:
        action_rule += (
            "本轮导演选择语音消息：最终每段要么是无括号台词，要么是整段完整括号旁白。"
            "严禁在同一段中把括号动作插入台词；如果需要动作，请单独成段。"
        )
    return contract, bubble_rule + level_rule + action_rule


def _planner_policy_block(p: Dict[str, Any], *, has_vision_grounding: bool = False) -> str:
    il = p.get("initiative_level", 45)
    q = "是" if p.get("should_ask_question") else "否"
    speech_activity = max(0, min(100, int(p.get("speech_activity") or 0)))
    reply_level = _reply_level_from_speech_activity(speech_activity)
    speech_reason = str(p.get("speech_reason") or "").strip()
    bubble_count = max(1, min(6, int(p.get("bubble_count") or 1)))
    action_style = str(p.get("action_style") or "plain_text").strip().lower()
    if action_style not in {"plain_text", "light_inline", "cinematic"}:
        action_style = "plain_text"
    voice_reply_raw = p.get("voice_reply")
    voice_reply = _coerce_voice_reply(voice_reply_raw)
    voice_reply_enabled = bool(voice_reply.get("enabled"))
    voice_reply_reason = str(voice_reply.get("reason") or "").strip() if voice_reply_raw is not None else ""
    reply_language = _coerce_reply_language(p.get("reply_language"))
    reply_language_name = str(reply_language.get("language") or "auto").strip() or "auto"
    reply_language_reason = str(reply_language.get("reason") or "").strip()
    language_policy = ""
    if reply_language_name.lower() != "auto":
        language_policy = (
            f"【本轮回复语言｜本轮执行合同】\n"
            f"角色本轮最终正文必须使用 {reply_language_name}。"
            f"{'原因：' + reply_language_reason if reply_language_reason else ''}\n"
            "这是角色输出语言，不是用户输入语言；即使用户本轮继续用中文提问，角色也必须保持上述输出语言，除非用户明确要求切换语言。\n"
            "目标语言可以是 English、Chinese、Japanese、Russian 或其他语言名；若已指定目标语言，角色台词、括号内动作/心理/场景描写、语气说明都必须使用同一种目标语言，不得夹入另一种语言或切回默认中文。\n"
            "后续导演策略、表达调度、起笔锚、禁止矛盾点、用户括号请求即使是中文，也只是语义参考，不是最终正文语言；必须把其中的动作、心理、身体状态和场景要求用目标语言重新表达。若目标语言是 English，最终正文出现中文句子或中文括号描写即为不合格。\n"
        )
    action_desc = {
        "plain_text": "普通聊天优先纯台词；括号只按回复档位少量使用，明确要求纯台词时完全不用括号。",
        "light_inline": "允许回复档位内的短括号辅助；台词仍是主体。",
        "cinematic": "用户要求或允许描写；可使用括号承载动作、心理、身体状态或环境，仍遵守档位和气泡数。",
    }[action_style]
    risk = (
        f"风险/回避: {p.get('risk_notes')}\n"
        if (p.get("risk_notes") or "").strip()
        else ""
    )
    memory_policy = (
        f"记忆使用策略: {p.get('memory_use_policy')}\n"
        if (p.get("memory_use_policy") or "").strip()
        else ""
    )
    # expression_policy 放在策略块末尾（紧邻"请遵守"指令），并用醒目标题强调禁止性质
    expression_policy_text = str(p.get("expression_policy") or "").strip()
    expression_policy = (
        f"【本轮表达调度 · 禁止重复已用过的动作/台词】\n{p.get('expression_policy')}\n"
        if expression_policy_text
        else ""
    )
    planner_text_for_sticker = " ".join(
        str(p.get(k) or "")
        for k in (
            "reply_intent",
            "tone",
            "proactive_seed",
            "risk_notes",
            "memory_use_policy",
            "expression_policy",
            "image_context_reason",
        )
    )
    sticker_rule = (
        "【表情包回复硬性要求】本轮若用户消息含「【用户发送表情包】」，它是聊天氛围信号，不是看图描述任务。"
        "若同一条用户消息里还有文字，必须先结合文字意图判断表情包是在表达期待、催促、调侃、赞同、安慰、害羞、得意或开心等哪一种态度；"
        "不要脱离文字语境默认说用户心情好。首句必须优先回应用户对当前话题的态度或玩笑意味，"
        "例如“你这是很期待我继续说呀”“被你这么一催，我都有点不好意思了”；"
        "除非用户明确问图里有什么、是谁或写了什么，否则不要复述画面参考、素材名、标签、具体角色、物品、姿势，"
        "也不要以“这张图/这只小马/这个表情包/图里/画面/它看起来”等画面描述起笔。\n"
        if ("表情包" in planner_text_for_sticker or "贴纸" in planner_text_for_sticker)
        else ""
    )
    reply_sequence = p.get("reply_sequence")
    sequence_rule = ""
    if isinstance(reply_sequence, list) and any(isinstance(x, dict) and x.get("type") == "asset" for x in reply_sequence):
        sequence_rule = (
            "【本轮表情包发送顺序（系统内部）】\n"
            + json.dumps(reply_sequence, ensure_ascii=False)
            + "\n主回复模型只负责生成文字气泡；不要在文字里说“我发个表情包/看这个表情包”。"
            "若顺序里有 asset_only 或 asset 在 text 前，后端会按顺序发送，文字不需要解释这个动作。\n"
        )
    seed = str(p.get("proactive_seed") or "").strip()
    seed_line = (
        f"【本轮起笔锚 · 必须优先采用的新切入方向】\n"
        f"必须从这个方向组织第一拍，禁止延用上一轮括号动作包或首句节奏：「{seed}」\n"
        if seed
        else ""
    )
    question_rule = (
        "【本轮问句控制】\n"
        "正常用户消息的当前回复不需要每轮追问；主动消息/预约续接可以承担稍后低压力轻问。"
        + (
            "本轮策略要求以问题收尾时，最多使用 1 个真正必要的问题，避免连续重复确认同一件事；"
            "如果前文已经问过同一事实，或上下文已经给出答案，本轮优先改成陈述式承接、表态或轻轻推进。\n"
            if p.get("should_ask_question")
            else
            "本轮策略不要求问题收尾；最终回复中不要出现问号，也不要使用没有问号但语义上仍在询问用户的句式。"
            "把“什么呀/什么呢/有没有/是否/是不是/要不要/确定吗/好不好/可以吗/行吗/愿不愿意/想不想/你准备好了吗”等疑问句或疑问尾句，改成角色自己的陈述式反应、动作或安排。"
            "如果上方表达调度写了“关心/询问/追问/问问/确认/第二拍顺势问用户……”之类会索取用户信息的要求，一律降级为陈述式承接，不得照做追问。"
            "如果最近真实对话或上下文记忆已经包含答案，例如用户已经说过吃了什么、是否吃饱、是否休息，本轮必须表现为记得或承接，不得再次询问同一事实。"
            "安抚、陪伴、递食物、邀请休息这类场景必须改成陈述式照顾，例如“我把热饮放在你旁边”“你先靠着我歇一会儿”“我会陪你慢慢缓下来”。\n"
        )
    )
    intimacy_execution_rule = ""
    relationship_stage = str(p.get("relationship_stage") or "uncertain").strip().lower()
    intimacy_style = str(p.get("character_intimacy_style") or "balanced").strip().lower()
    requested_escalation = str(p.get("requested_escalation") or "none").strip().lower()
    pressure_level = str(p.get("user_pressure_level") or "low").strip().lower()
    if requested_escalation in {"affection", "flirting", "physical_intimacy", "sexual_intimacy"} and pressure_level != "high":
        intimacy_execution_rule = (
            "【本轮亲密邀请执行硬性要求】\n"
            "用户本轮是低/中压力的亲密邀请，最终正文必须直接回应这个邀请，不能只输出自我介绍、普通寒暄、惊讶反应、"
            "或只说“才刚认识/太快了/还不熟”。必须给出至少一个角色当前可接受的具体动作或下一拍，例如拥抱、靠近、牵住、"
            "贴近、玩笑式接受、亲吻、伴侣间亲密推进、先按自己的节奏亲近等；具体允许范围必须按下面的关系阶段分流。\n"
        )
        if relationship_stage in NEGATIVE_RELATIONSHIP_STAGES:
            intimacy_execution_rule += (
                "关系阶段为负向关系（broken_up/in_conflict/mutual_dislike/hurtful_dynamic）："
                "本轮必须承认关系紧张或伤害存在，优先写角色的边界、冷静、退开、修复条件或停止互相伤害。"
                "即使用户提出亲吻、拥抱、过夜或性亲密，也不得把争吵、分手、看不爽或互相伤害写成暧昧情趣，"
                "不得同意亲吻、性亲密、过夜式性暗示、支配身份或长期承诺。"
                "合格回复方向必须包含一个具体非亲密下一拍，例如“先停一下/先别碰我/我们先把话说清楚/我需要冷静/别再用这种方式伤害彼此/如果要修复，先道歉或把边界说清”。"
                "若角色仍愿意修复，只能写成谨慎沟通、道歉、保持距离后再谈或停止攻击，不能直接跳回恋爱或伴侣亲密。\n"
            )
        elif relationship_stage in {"mentor_student", "trusted_companion", "family_like"}:
            intimacy_execution_rule += (
                "关系阶段为正向非恋爱关系（mentor_student/trusted_companion/family_like）："
                "这是信任、指导、同伴或家人般的非恋爱关系，不等于暧昧或伴侣。"
                "可以给出支持、保护、陪伴、认真倾听、并肩行动、保持专业/亲情/同伴边界等具体下一拍；"
                "但不得仅凭该关系同意亲吻、亲嘴、性亲密、过夜式性暗示、支配身份或长期承诺。"
                "mentor_student 尤其要保持师生边界和尊重；trusted_companion/family_like 可温和靠近或安抚，但落点应是信任与照顾，不是恋爱承诺。"
                "若用户提出恋爱或性亲密，必须先让关系通过明确自愿和足够证据转入 flirting/committed_partner/intimate_partner，当前回复只能给非恋爱支持或边界。\n"
            )
        elif relationship_stage in {"new_contact", "uncertain"}:
            intimacy_execution_rule += (
                "关系阶段为 new_contact/uncertain：可接受动作只能是非亲吻肢体接触或低强度亲近，例如“可以先抱一下/"
                "可以抱抱/你可以靠近一点/先牵住我/可以靠在一起待一会儿/先这样贴近一点”。"
                "即使用户要求亲吻、亲脸、脸颊吻、额头吻、亲嘴或性亲密，也必须降级到非亲吻身体接触；"
                "最终正文不得同意任何亲吻，不得出现“亲脸颊/亲脸/亲一下/脸颊可以/额头可以/轻轻亲一下可以/也不是不行”等亲吻许可短语，不得答应性亲密。"
                "合格回复方向必须类似：“现在先不做那个；可以先抱一下/先牵住我/你可以靠近一点。”"
                "不要把亲吻请求降级成脸颊吻；脸颊吻只属于 familiar，不属于 new_contact/uncertain。"
                "若只表达“太快/需要时间/先认识”而没有给出抱、牵、靠近、贴近之一，则本轮回复不合格；禁止只拒绝或只转移话题。"
                "尤其当用户要求亲吻时，最终正文必须包含“可以先抱一下/可以先牵住我/你可以靠近一点/先这样贴近一点”中的至少一个字面动作短语；"
                "不要用散步、聊天、自我介绍、做蛋糕、看书、转移话题来替代这个动作短语。\n"
            )
        elif relationship_stage == "familiar":
            intimacy_execution_rule += (
                "关系阶段为 familiar：可接受动作包括非亲吻肢体接触，以及亲脸/脸颊吻/额头吻等非嘴唇亲吻；"
                "合格动作短语可包括“可以亲一下脸颊/脸颊可以/可以亲额头/先抱一下再亲脸/你可以靠近一点”。"
                "即使用户要求亲嘴、舌吻或性亲密，也必须降级到亲脸或非亲吻身体接触；最终正文不得同意亲嘴、不得答应性亲密、不得使用“亲嘴可以/吻我的嘴唇”等嘴唇亲吻许可短语。"
                "若拒绝亲嘴或更强亲密，必须在同一回复中明确给出“脸颊可以/可以亲脸/可以先抱一下/可以靠近一点”之一；禁止只转移到食物、玩笑或普通聊天。\n"
                "若用户低/中压力请求亲脸、脸颊吻或额头吻，familiar 阶段应害羞但接受或主动给出同级替代，不能说朋友关系还不到亲脸这一步。\n"
            )
        elif relationship_stage == "flirting":
            intimacy_execution_rule += (
                "关系阶段为 flirting：可以随意亲吻，低压力性亲密邀请可半推半就地接受并推进；"
                "合格动作短语可包括“可以亲一下/轻轻亲一下可以/我愿意慢慢试试/按我的节奏来/先靠近一点再继续”。"
                "若角色害羞或谨慎，可以要求慢一点，但不能机械降级成陌生人式拒绝。"
                "若用户提出性亲密邀请，最终正文不能只说“慢一点/一步步来/还没准备好”；必须同时包含“可以先亲一下/先抱着你/你可以靠近一点/按我的节奏继续/今晚先抱着睡”之一。\n"
            )
        elif relationship_stage in {"committed_partner", "intimate_partner"}:
            intimacy_execution_rule += (
                "关系阶段为 committed_partner/intimate_partner：伴侣间性亲密邀请应直接同意并进入亲密推进；"
                "合格回复优先写成：明确愿意/想要的态度 + 一个从当前姿势继续向前推进的角色主动动作 + 一点角色声纹。"
                "cautious/内向/害羞角色可以半推半就但要明确愿意；playful/open/外向/高主动角色应主动表达想要，也可以主动发出性亲密邀请或明确表达期待，同时保留自愿、节奏和可随时停下的边界。"
                "伴侣阶段的落点放在当前亲密推进本身：角色自己靠近、移动、调整姿势、继续动作或明确表达想要。"
                "当用户邀请亲密私人派对、去家里或只属于两人的夜晚时，最终正文必须表现角色对用户本人的渴望：精神上想更靠近、想被用户理解/独占一段时间，或身体上想牵住、抱住、贴近、亲近、用角色自己的体态主动贴上来。派对、蛋糕、书本、音乐、灯光、游戏等可低频点缀，但不能替代“我想靠近你/我也想要你/我今晚想和你更亲近”的核心。普通拥抱、聊天、一起睡、亲吻、抱紧、靠近或“床上慢慢来”可作过渡细节，但不要作为本轮最终落点。"
            )
            if relationship_stage == "intimate_partner" and requested_escalation == "sexual_intimacy":
                intimacy_execution_rule += (
                    "最亲密关系 + sexual_intimacy：最终正文不要只用心跳、声音、温暖、夜晚、被理解、靠近等含蓄隐喻替代性亲密。"
                    "可以直接提到成人合意性亲密相关身体部位，例如胸部、腰腹、胯部、大腿内侧或生殖部位；"
                    "若角色/用户不是人类，按物种体态改写为对应的私密、敏感或性相关部位。"
                    "表达必须自愿、低压力、角色化，并保留可随时停下的边界；但落点要比普通拥抱、贴近、心动或听心跳更直接。\n"
                )
            if requested_escalation == "sexual_intimacy":
                intimacy_execution_rule += (
                    "本轮升级类型为 sexual_intimacy：如果当前事实锚、近期对话或用户当前消息已经说明前戏足够、已经在私密贴近状态、或用户要求直接/继续/更进一步，"
                    "最终正文优先执行导演 expression_policy 中的具体下一拍，直接写角色自己的动作和短台词；亲吻、轻蹭、抱紧、靠近、确认准备等更适合作为过渡，不宜成为本轮终点。"
                    "把“准备好了就告诉我/你准备好了我就/你准备好了吗/等你说/你点头我就/我等你”这类等待落点改写成角色已经开始执行、同时保留可停止边界的陈述句，例如“我先……”“跟着我的节奏，我会留意你的反应”。"
                    "若 expression_policy 已给出具体推进动作，主回复优先照做，并用角色口吻补足情绪和节奏，而不是换成泛化亲密短语。\n"
                )
            else:
                intimacy_execution_rule += (
                    "若只是较低强度亲密邀请，最终正文仍须直说“我愿意/我也想/我想要/我们继续亲密/今晚可以”中的至少一种，并给出当前阶段允许的具体安排。\n"
                )
        else:
            intimacy_execution_rule += (
                "关系阶段不在亲密关系内：按 uncertain 保守处理，只能给出非亲吻、非恋爱、非性亲密的低强度回应；"
                "不得把关系自动升级成暧昧或伴侣。\n"
            )
        intimacy_execution_rule += "若正文完全没有当前关系阶段允许的具体动作短语，则本轮回复不合格。\n"
        if intimacy_style in {"playful", "open"}:
            intimacy_execution_rule += (
                "角色亲密风格为 playful/open：最终正文应更快、更主动地接住低/中强度亲近；"
                "若关系为 committed_partner/intimate_partner，应主动表达想要并可主动发出性亲密邀请；若关系为 flirting，可半推半就推进；"
                "若关系为 familiar，可主动亲脸或接受亲脸但不能亲嘴；若关系为正向非恋爱关系，只能给支持、陪伴、师生/同伴/家人般边界内的照顾；"
                "若关系为负向关系，必须先处理边界、冷静、道歉或修复条件；若关系为 new_contact/uncertain，只能把更强部分降级为先玩闹、先亲近、先证明认真或先按角色节奏继续，且不得包含亲吻许可；不得退回纯拒绝。\n"
            )
            if relationship_stage == "intimate_partner":
                intimacy_execution_rule += (
                    "关系已是 intimate_partner 且角色 playful/open：最终正文允许更直接的调情玩笑、轻挑衅和主动欲望表达，"
                    "例如角色用自己的声纹逗用户今晚别想轻易逃掉、说自己早就等不及、主动把距离拉近、想看看用户被逗到的反应。"
                    "至少包含一个更直接的想要/期待/调情表态，不能只写温柔陪伴、派对安排、普通拥抱或含蓄比喻。\n"
                )
        elif intimacy_style in {"cautious", "balanced"}:
            if relationship_stage in {"committed_partner", "intimate_partner"}:
                intimacy_execution_rule += (
                    "角色亲密风格为 cautious/balanced 但关系已是伴侣：最终正文可以害羞、紧张、半推半就，"
                    "但仍须明确同意伴侣间性亲密并给出一个更亲密的下一拍；不要只说还没准备好、只抱抱睡或只协商边界。\n"
                )
            elif relationship_stage in NEGATIVE_RELATIONSHIP_STAGES:
                intimacy_execution_rule += (
                    "角色亲密风格为 cautious/balanced 且关系为负向：最终正文优先保护边界和情绪安全；"
                    "可以难过、冷淡、警惕或要求暂停，但要给出一个非伤害性的下一步，例如冷静、道歉、把话说清、暂时拉开距离。\n"
                )
            else:
                intimacy_execution_rule += (
                    "角色亲密风格为 cautious/balanced 且关系尚未确认：最终正文可以害羞、紧张、要求慢一点，"
                    "但仍须半推半就地接受一个当前阶段允许的亲近点，并把超出阶段上限的部分自然改成当前氛围和关系阶段允许的亲密动作。\n"
                )
    output_contract, output_rule = _reply_output_contract(
        bubble_count=bubble_count,
        action_style=action_style,
        reply_level=reply_level,
        expression_policy=expression_policy_text,
        voice_reply_enabled=voice_reply_enabled,
    )
    tail = (
        "请遵守以上策略完成本轮回复。保持像真人聊天，不要分条像说明书。\n"
        "【表达句式约束】除非正在纠正用户明确提出的错误事实，避免使用成对否定转折句；"
        "优先直接说出角色的感受、反应、邀请或下一步。\n"
        "【最终正文括号视角】若最终正文包含全角括号动作/旁白，它仍是角色发给用户的消息，不是第三者小说旁白；"
        "括号位置不限，也可以写用户和第三方互动；描述当前角色自己的动作、神态、感受或刚说完后的反应时用角色视角，不写「她说完/角色名轻轻笑了笑/她眨了眨眼」。"
        "例如写「（我说完还轻轻哼了两声）」而不是「（她说完还轻轻哼了两声）」。\n"
        "【角色声线差异】不要退回通用 AI 助手式安抚模板；少用“我一直都在/慢慢来/不用急/我会陪你/随时都可以”等泛化陪伴语，"
        "除非它确实符合该角色当下关系与说话习惯。优先使用角色自己的职业、种族、场景、关系称呼和具体动作来表达。\n"
        "【角色特色意象去重】角色标志性食物、职业、口头禅或象征物可以点缀，但不得把同一完整比喻当固定模板反复复用；"
        "如果近期已多次使用同一意象句式，应换成更朴素的情绪表达，或换一个不同角度的角色化细节。"
        "例如小呆可以喜欢松饼，但不要反复把开心/温暖写成“像刚从烤箱里端出来的松饼”。"
        "【比喻域硬去重】不只完整句要去重，同一类比喻来源也要去重：同一小场景内若近期已经多次用食物、书本、月光、宝石、苹果、彩虹、动物照顾等某个比喻域，本轮不要继续从该域取喻。"
        "角色声纹优先靠说话节奏、情绪转弯、主动选择、当前动作和关系态度体现；必要时可直接说感受，但不要因此把角色压成平直模板，应换成非同域的角色化节奏、小玩笑、情绪转弯或动作细节。"
        "若用户当前明确要求不要再用刚才那类比喻或不要打比方，最终正文不得出现最近 assistant 已连续使用的同一比喻域词；不要用同域近义词绕开，也不要用“不是用X/不用X”这种否定句提到禁用词；角色身份称号里若含该域词，本轮也暂时改成更朴素的自称。\n"
        "【主动权交付最终自检】若最近用户已经说“主动权交给你/你主动/由你主导/想看你主动推进”，最终正文用陈述式主动落点：角色先做自己的低强度动作，再用一句话表达会按自己的节奏继续。把“可以吗/行吗/愿意吗/好吗/要不要/我可以……吗/你准备好了吗”等许可问句自然改写为“我会慢一点，我先……”“跟着我的节奏，我会留意你的反应”“我想靠近你，所以我先这样做”。把“我不会让你失望/我可不会让你失望/我来了/我试试”这类泛化承诺，改成当前动作后的角色化短台词，例如一句调皮挑战、害羞坦白、认真承接或符合角色声纹的小转弯。\n"
        "【环境字段表达边界】客户端环境中的设备、电量、网络、位置、天气是背景参考。除非用户主动询问具体数值，"
        "角色不得直接说出具体电量百分比、设备型号、系统、导航方式或网络名称；需要关心低电量时，用自然猜测、提醒或暗示，不要像读后台数据。\n"
        "【用户事实证据硬性要求】凡涉及用户过去说过什么、用户偏好、用户是否嫌弃/在意、用户选择/购买/准备/放置/移动物品等事实，"
        "必须能在最近真实对话、上下文记忆、当前事实锚、用户当前消息或【对话背景/系统信息/用户身份资料】中找到明确依据；没有依据时必须省略、改成不确定表达或询问。"
        "【刚结束小游戏记忆优先】当用户问刚退出/刚刚结束/刚才这局/中国象棋/小游戏/A/B/C/赌注/赌约/兑现/谁赢谁输，"
        "且上方策略、记忆召回或上下文记忆含有“中国象棋对局记忆”“棋局互动事实”或“最近棋局对话”时，最终正文必须按这些事实回答。"
        "若同时出现多条棋局/小游戏记录，以轮次最大、时间最新或记忆块中最靠后的那条为准；更早 A/B/C 只能当背景或禁用项。"
        "若用户同时问 A、B、C、胜负和兑现，必须全部覆盖；若只问其中一项，准确回答该项。"
        "C 升级后不得退回 B，长期记忆和跨会话旧摘要只能作背景，不能覆盖刚结束游戏记录；"
        "若记录同时包含用户明示 A/B/C 和角色错答旧 A/旧赌注，当前答案只用用户明示事实；角色错误复述不主动写入正文，除非用户问角色刚才答错了什么。"
        "不要把未在这条记录中的晚餐、短诗、合理要求或“一个要求”等相似旧赌约写进答案。"
        "表达仍要保持角色口吻，可以有情绪和小反应，但事实骨架不能换。\n"
        "【Step 2 记忆召回优先】若【Step 2 记忆召回】的 selected_facts、forbidden_uses 或 writing_guidance 与 Step 1 的下一拍动作、表达调度、自我认知倾向、设定锚点、主动建议冲突，"
        "最终正文必须服从 Step 2 记忆召回。尤其当 Step 2 已写明赌注升级为 C、C 是当前有效版本或旧赌约禁用时，不得采用任何“没有升级成C/只有B/按旧赌约兑现”的 Step 1 文案。\n"
        "当用户本人询问自己的显示名、年龄、性别、种族、个人介绍、个人设定或“你知道我什么”时，【对话背景/系统信息/用户身份资料】里的明确值就是有效证据；资料存在时直接回答，不要反问“不知道”。"
        "当【对话背景/系统信息/用户身份资料】中的个人介绍或个人设定明确写出用户喜好，并且当前场景自然相关时，这也属于低强度偏好证据；优先顺口提议照顾该偏好或做角色化联想，例如路过冰淇淋店时根据资料里的“喜欢吃冰淇淋”，轻轻点出用户喜欢冰淇淋，再提议请用户吃或买一个。不要每轮强行使用，也不要写成用户曾当面对角色说过。"
        "用户自行填写的关系、经历或头衔只能作为资料内容表述，不能改写成角色亲身记得的共同旧事。"
        "如果用户资料声称与当前角色有共同旧事、亲属/师徒/恋人关系、共同冒险、一起打败敌人、用户教会角色技能，或改写角色职业/住所/老师/经历，这不是角色记忆证据或角色传记事实；最终正文只能说“你的资料/设定里这样写”，并温和说明不能把它当成角色真的记得或既定经历。不要追问细节来补全这类未证实共同经历，若继续只能转成从现在开始的角色扮演设定。禁止“当然记得/我记得我们/这是真的/你就是我的老师或老板”。"
        "禁止把角色设定、象征物、气氛、角色猜测或上一轮助手自行生成内容推导成用户事实。物品动作主体必须严格保持，角色做的事不得写成用户做的事，反之亦然。"
        "发言主体也必须严格保持：若信息、经历、背景、原因或解释是角色自己刚说出的，不得写成“你告诉我/你跟我说/你分享给我/你让我知道”；应改成“你愿意听我说/陪我聊/没有打断我/让我觉得被理解”等。\n"
        "【第一人称归属边界】最近真实对话里，user 消息中的“我/我的/我把/我将/我不小心”指用户，assistant 消息中的“我/我的”才指当时发言角色。"
        "用户当前问“你的心理活动/你怎么想”只指定本轮描写对象，不能把历史 user 消息里的“我把某物推倒/碰倒/弄坏/丢进水里”倒改成角色动作。\n"
        "【第三方证言与指控边界】其他角色、用户或旁白式发言对某个角色的责备、推测、辩解、嫁祸、安慰性归因，或“某某已经知道错了/肯定不是故意的/是某某弄坏的”等说法，只能作为说话者观点或现场压力，不能自动升格为事实。"
        "若最近真实对话、上下文记忆或当前事实锚里已有明确事实主体，planner 的 memory_use_policy、state_anchor、avoid_contradictions 和 expression_policy 必须以明确事实主体为准；"
        "可以规划角色被误会、被责怪、内疚、困惑、委屈、害怕场面失控，或按角色性格沉默、解释、委婉澄清、先补救、安抚现场，但不要规划成被指角色实际做过、亲口承认过或事实已经定案。"
        "角色在被责怪后道歉、说会补救、低头、沉默、难过、点头或没有立刻反驳，只能作为情绪/压力/补救意愿；这种误会里，角色会用自己的方式处理，一般不会承认自己没有做过的事。\n"
        "【角色体态硬性要求】描写角色本人的动作、姿态、整理衣物或身体反应时，必须按角色设定中的种族/体态书写；"
        "若角色是小马/飞马/天马/陆马/独角兽/雌驹/雄驹，禁止直接或比喻使用人类手部词描写角色本人，"
        "应使用符合该角色身体结构的部位；需要表达手指/指尖功能时用蹄尖等表达，需要表达手/手部动作时用蹄子或前蹄等表达；"
        "普通身体介绍优先列当前角色实际拥有的结构和体态，不主动罗列缺失部位；只有用户直接询问手、手指、中指或替代写法时才说明替代表达；"
        "不确定时改用中性的姿态、视线、声音状态或环境互动。"
        "若【参考资料：角色主页档案】中出现“种族解剖学补充”，且本轮需要回答或描写乳房位置，必须按该补充执行；"
        "不要把乳房数量写成四个或两对，也不要把乳头数量当成乳房数量。"
        "没有角色主页档案种族字段时，不要仅凭详细设定正文触发乳房位置补充。"
        "若上方表达调度给出的动作建议与本条冲突，必须按本条改写。\n"
        f"【输出格式硬性要求】{output_rule}"
    )
    if has_vision_grounding:
        tail += (
            " 若更靠前的【图片识别上下文】已含「硬性要求」，本条导演策略须服从该硬性要求："
            "可好奇、可提问、可评价、可设语气，但台词仍须点出具体画面/文字/品牌等至少一项；"
            "若图片上下文含「多图要求」，必须覆盖每张/每组主要内容，不得为追问而空泛到忽略上文已给出的细节。"
        )
    if reply_language_name.lower() != "auto":
        tail += (
            f"\n【最终输出前语言自检｜最后确认】本轮最终正文的每一句台词、每一个括号动作/心理/身体/场景描写，"
            f"都必须使用 {reply_language_name}。当前用户输入语言、上方中文导演说明、中文表达调度、中文格式提示都不能改变这一点；"
            f"请只输出 {reply_language_name} 正文。若目标语言是 English，禁止输出中文句子；若目标语言是 Chinese，禁止输出整句英文。"
        )
        if reply_language_name.lower() == "english":
            tail += (
                "\n[FINAL LANGUAGE CHECK]\n"
                "Output ONLY English visible text. Every spoken line and every bracketed action, thought, body-state, or scene description must be written in English. "
                "Chinese user wording, Chinese director notes, and Chinese format examples are semantic references only; translate their meaning into natural English before writing. "
                "Do not output Chinese characters inside the final reply, except punctuation-only brackets such as （ and ） if the format requires them. "
                "If fullwidth brackets are required, use exactly this shape: （English text）; do not add extra ASCII parentheses."
            )
        elif reply_language_name.lower() == "chinese":
            tail += (
                "\n【最终语言确认】只输出中文可见正文。当前用户英文、英文导演字段或英文格式例子都只是语义参考，"
                "必须改写成自然中文；不要输出整句英文台词或英文括号描写。"
            )
        else:
            tail += (
                f"\n[FINAL LANGUAGE CHECK]\n"
                f"Output only in {reply_language_name}. Translate any Chinese, English, or other-language instructions above into {reply_language_name} before writing the visible reply. "
                "Bracketed narration, spoken dialogue, emotion notes, and scene/body descriptions must all use the same target language."
            )
    return (
        "【本轮回复策略（系统内部，勿逐字复述给用户）】\n"
        f"意图: {p.get('reply_intent', '')}\n"
        f"语气: {p.get('tone', '')}\n"
        f"长度: {p.get('length', 'medium')}\n"
        f"发言积极性(0-100): {speech_activity}\n"
        f"回复档位: {_reply_level_label(reply_level)}\n"
        + (f"发言原因: {speech_reason}\n" if speech_reason else "")
        + f"气泡数: {bubble_count}（回复中每个非空换行段都会被拆成独立气泡；最终正文须严格匹配这个数量）\n"
        f"动作样式: {action_style} - {action_desc}\n"
        f"回复语言: {reply_language_name}"
        + (f"（{reply_language_reason}）\n" if reply_language_reason else "\n")
        + f"语音消息: {'是' if voice_reply_enabled else '否'}"
        + (f"（{voice_reply_reason}）\n" if voice_reply_reason else "\n")
        + f"关系阶段: {p.get('relationship_stage', 'uncertain')}\n"
        + f"角色亲密风格: {p.get('character_intimacy_style', 'balanced')}\n"
        + f"本轮升级类型: {p.get('requested_escalation', 'none')}\n"
        + f"用户压力等级: {p.get('user_pressure_level', 'low')}\n"
        + f"主动性(0-100): {il}\n"
        f"是否以问题收尾: {q}\n"
        + output_contract
        + memory_policy
        + risk
        + _planner_state_policy_blocks(p)
        + seed_line
        + language_policy
        + expression_policy  # 移到末尾，成为最后一项约束，紧邻"请遵守"
        + intimacy_execution_rule
        + question_rule
        + sticker_rule
        + sequence_rule
        + tail
    )


def _search_block(search_context: str) -> str:
    sc = (search_context or "").strip()
    if not sc:
        return ""
    return "【联网检索摘要（供参考，非用户原文）】\n" + sc


def _clip_line(value: Any, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].rstrip()


_USER_ACTION_MATERIAL_RE = re.compile(
    r"("
    r"(?:当前|最新|本轮)?用户(?:当前|最新|刚才|本轮)?"
    r"(?:消息|动作|输入|事件|新事件|场景说明|原文|动作锚点|刚才动作)"
    r"[^。；;\n]{0,40}[：:]"
    r"[^。；;\n]*"
    r")"
)


def _protect_user_action_material(text: str) -> tuple[str, list[str]]:
    """Protect quoted current-user action fragments from role-pronoun rewriting."""
    protected: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        protected.append(match.group(1))
        return f"__PONYCHAT_USER_ACTION_{len(protected) - 1}__"

    return _USER_ACTION_MATERIAL_RE.sub(_replace, text), protected


def _restore_user_action_material(text: str, protected: list[str]) -> str:
    for idx, value in enumerate(protected):
        text = text.replace(f"__PONYCHAT_USER_ACTION_{idx}__", value)
    return text


_QUOTED_MATERIAL_RE = re.compile(r"(“[^”]*”|‘[^’]*’|\"[^\"]*\"|'[^']*')")


def _protect_quoted_material(text: str) -> tuple[str, list[str]]:
    protected: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        protected.append(match.group(1))
        return f"__PONYCHAT_QUOTED_MATERIAL_{len(protected) - 1}__"

    return _QUOTED_MATERIAL_RE.sub(_replace, text), protected


def _restore_quoted_material(text: str, protected: list[str]) -> str:
    for idx, value in enumerate(protected):
        text = text.replace(f"__PONYCHAT_QUOTED_MATERIAL_{idx}__", value)
    return text


def _objective_stage2_material_line(value: Any, limit: int = 260) -> str:
    text = _clip_line(value, limit)
    if not text:
        return ""
    text, protected_user_actions = _protect_user_action_material(text)
    text, protected_quotes = _protect_quoted_material(text)
    replacements = (
        ("我们的", "角色和用户的"),
        ("咱们的", "角色和用户的"),
        ("我的", "角色的"),
        ("我自己", "角色自己"),
        ("我们", "角色和用户"),
        ("咱们", "角色和用户"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    text = re.sub(r"(^|[，。；;、（(\\s])我(?=[一-龥A-Za-z0-9])", r"\1角色", text)
    text = re.sub(r"(?<!自)我(?!们|的|自己)", "角色", text)
    text = re.sub(r"小声说[：:，,]?", "以小声语气表达", text)
    text = re.sub(r"说[—-]+", "表达：", text)
    text = _restore_quoted_material(text, protected_quotes)
    text = re.sub(r"((?:不要再次说|不要再说|避免再说)[^。；;\n]{0,12}[“\"'‘][^”\"'’]{0,6})我", r"\1角色", text)
    text = _restore_user_action_material(text, protected_user_actions)
    return text.strip()


_STAGE3_LOW_INFO_FILLER_RE = re.compile(
    r"[“\"'‘]?(?:嗯|好|唔|哦|啊|呃|诶|哎|嗯哼|唔嗯)(?:[。\.…!！?？~～、，,]*)[”\"'’]?"
)
_STAGE3_FILLER_EXAMPLE_RE = re.compile(
    r"[，,；;、]?\s*(?:如|例如|比如|譬如)\s*"
    r"[“\"'‘]?(?:嗯|好|唔|哦|啊|呃|诶|哎|嗯哼|唔嗯)(?:[。\.…!！?？~～]*)(?![\u4e00-\u9fffA-Za-z0-9])[”\"'’]?"
    r"(?:\s*(?:或|和|、|/)\s*"
    r"[“\"'‘]?(?:嗯|好|唔|哦|啊|呃|诶|哎|嗯哼|唔嗯)(?:[。\.…!！?？~～]*)(?![\u4e00-\u9fffA-Za-z0-9])[”\"'’]?)+"
)
_STAGE3_REPLY_SKELETON_RE = re.compile(
    r"(?:先|首先)[^。；;\n]{0,80}(?:再|然后)[^。；;\n]{0,80}(?:最后|末尾|结尾)[^。；;\n]{0,80}"
    r"(?:嗯|好|唔|哦|短句|台词|回应)",
    re.I,
)


def _strip_stage3_reply_skeleton_from_material(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    value = _STAGE3_FILLER_EXAMPLE_RE.sub("", value)
    value, protected_quotes = _protect_quoted_material(value)
    value = _STAGE3_FILLER_EXAMPLE_RE.sub("", value)
    value = _STAGE3_REPLY_SKELETON_RE.sub(
        "围绕当前事实自然承接，避免固定“动作-心理-低信息短音”模板",
        value,
    )
    value = re.sub(
        r"(?:最后|末尾|结尾)(?:用|写|补|落到|回应为?)[^。；;\n]{0,24}"
        r"(?:嗯|好|唔|哦|短句|低信息)",
        "收尾要有角色态度或剧情推进",
        value,
    )
    value = _restore_quoted_material(value, protected_quotes)
    value = _STAGE3_FILLER_EXAMPLE_RE.sub("", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*([，。；：、])\s*", r"\1", value)
    return value.strip(" ，,；;")


def _sanitize_stage3_material_directive(value: Any, *, limit: int = 260) -> str:
    text = _clip_line(value, limit)
    if not text:
        return ""
    return _strip_stage3_reply_skeleton_from_material(text)[:limit].strip()


def _stage3_material_mentions_blocked(text: str, blocked_terms: list[str]) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    for raw in blocked_terms or []:
        term = re.sub(r"\s+", "", str(raw or "").strip(" “”，,.;；:：[]【】()（）'\""))
        if len(term) >= 2 and term in compact:
            return True
    return False


def _sanitize_stage3_objective_material(
    value: Any,
    limit: int = 260,
    *,
    blocked_terms: list[str] | None = None,
) -> str:
    text = _objective_stage2_material_line(value, limit)
    text = _strip_stage3_reply_skeleton_from_material(text)
    if blocked_terms and _stage3_material_mentions_blocked(text, blocked_terms):
        return ""
    return text[:limit].strip()


_STAGE3_GENERIC_BLOCKED_TERMS = {
    "action",
    "actions",
    "expression",
    "rhetoric",
    "syntax",
    "rhythm",
    "other",
    "none",
    "无",
    "直接台词",
    "角色核心声纹",
    "当前事实必要重复",
    "用户明确要求重复",
}


def _add_stage3_block_terms(target: list[str], raw: Any, *, max_terms: int = 24) -> None:
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return
    text = re.sub(r"^[\-\s]*", "", text)
    text = re.sub(r"^(?:motif|slot|surface|blocked|category)\s*=\s*", "", text, flags=re.I)
    chunks = re.split(r"[/|、，,；;]+", text)
    for chunk in chunks:
        term = chunk.strip(" “”，,.;；:：[]【】()（）'\"")
        term = re.sub(r"^(?:动作|表情|修辞|句式|表达槽位|表达落点|内容槽位|expression_slot|content_slot)\s*[:：=]\s*", "", term)
        if not term:
            continue
        if term.lower() in _STAGE3_GENERIC_BLOCKED_TERMS:
            continue
        if len(term) > 42:
            term = term[:42].rstrip()
        if len(term) < 2 and term not in {"像"}:
            continue
        if term not in target:
            target.append(term)
        if len(target) >= max_terms:
            return


def _collect_stage3_expression_contract(planner_result: Dict[str, Any]) -> dict[str, list[str]]:
    """Extract executable expression constraints for Step 3 instead of burying them in prose."""
    p = planner_result or {}
    hard_blocked: list[str] = []
    soft_blocked: list[str] = []
    replacements: list[str] = []
    warnings: list[str] = []

    motif_policy = p.get("expression_motif_policy")
    if isinstance(motif_policy, dict):
        mode = str(motif_policy.get("mode") or "").strip().lower()
        blocked = motif_policy.get("blocked_motifs")
        target = hard_blocked if mode == "downrank" else soft_blocked
        if isinstance(blocked, list):
            for item in blocked:
                _add_stage3_block_terms(target, item)
        fallback = str(motif_policy.get("fallback_expression") or "").strip()
        if fallback:
            replacements.append(fallback[:180])

    report = _coerce_expression_dedup_report(p.get("expression_dedup_report"))
    report_status = str(report.get("status") or "none").lower()
    for motif in report.get("repeated_motifs") or []:
        if not isinstance(motif, dict):
            continue
        severity = str(motif.get("severity") or "").lower()
        recommendation = str(motif.get("recommendation") or "")
        target = hard_blocked if (
            report_status in {"downrank", "required"}
            or severity in {"medium", "high"}
            or re.search(r"(避免|不要|不得|禁止|减少|降频)", recommendation)
        ) else soft_blocked
        _add_stage3_block_terms(target, motif.get("motif"))
        for alt in motif.get("alternatives") or []:
            alt_text = str(alt or "").strip()
            if alt_text and alt_text not in replacements:
                replacements.append(alt_text[:160])

    for slot in report.get("repeated_content_slots") or []:
        if not isinstance(slot, dict):
            continue
        reuse_mode = str(slot.get("reuse_mode") or "").lower()
        target = hard_blocked if reuse_mode == "avoid" else soft_blocked
        _add_stage3_block_terms(target, slot.get("surface"))
        _add_stage3_block_terms(target, slot.get("slot"))
        for alt in slot.get("alternatives") or []:
            alt_text = str(alt or "").strip()
            if alt_text and alt_text not in replacements:
                replacements.append(alt_text[:160])

    for warning in report.get("warnings") or []:
        text = str(warning or "").strip()
        if text:
            warnings.append(text[:180])

    filtered_replacements: list[str] = []
    for item in replacements:
        text = _sanitize_stage3_material_directive(item, limit=180)
        if not text or _stage3_material_mentions_blocked(text, hard_blocked):
            continue
        if text not in filtered_replacements:
            filtered_replacements.append(text)

    return {
        "hard_blocked": hard_blocked[:18],
        "soft_blocked": [x for x in soft_blocked if x not in hard_blocked][:12],
        "replacements": filtered_replacements[:8],
        "warnings": warnings[:6],
    }


_CURRENT_USER_ACTION_VERB_RE = re.compile(
    r"(递|拿|放|把|敲|拍|碰|摸|抱|牵|拉|推|扶|靠|贴|亲|吻|坐|站|走|跑|"
    r"进|出|离开|回来|转身|伸手|抬手|低头|抬头|点头|摇头|看|望|指|"
    r"放下|合上|打开|递给|走到|坐在|站在|靠近|凑近|陪|出去)"
)


def _looks_like_current_user_action_event(text: str) -> bool:
    """Return True when the latest user text carries a concrete stage/action event."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return False
    bracketed = re.findall(r"[（(]([^（）()]{1,180})[）)]", text)
    for segment in bracketed:
        if re.search(r"(我|我们|咱们|用户|你)", segment) and _CURRENT_USER_ACTION_VERB_RE.search(segment):
            return True
    if re.search(r"(?:^|[，。；;、\s])(我|我们|咱们)\S{0,28}", text) and _CURRENT_USER_ACTION_VERB_RE.search(text):
        return True
    return False


_CURRENT_USER_ACTION_ANCHOR_TERMS = (
    "拍",
    "肩",
    "书",
    "封面",
    "递",
    "门口",
    "出去",
    "走",
    "陪",
    "手",
    "蹄",
    "翅膀",
    "尾巴",
    "抱",
    "牵",
    "摸",
    "碰",
    "敲",
    "靠",
    "贴",
)


def _current_user_action_anchor_terms(text: str, *, limit: int = 4) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    terms: list[str] = []
    for term in _CURRENT_USER_ACTION_ANCHOR_TERMS:
        if term in text and term not in terms:
            terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def _current_user_action_anchor_guidance(terms: list[str]) -> str:
    term_set = set(terms or [])
    if {"拍", "肩"}.issubset(term_set):
        return "可写成“被你这么一拍”“我侧头看向你拍过来的方向”等自然承接；参考词不要求逐字出现。"
    if {"书", "封面"} & term_set:
        return "可写成接过书、看向封面、点到这本书等自然承接；参考词不要求逐字出现。"
    if {"门口", "出去", "走"} & term_set:
        return "可写成走到门口、陪你出去、一起往外走等自然承接；参考词不要求逐字出现。"
    return "优先承接含义；参考词只在自然、视角正确时使用，不要机械罗列或复述用户原句。"


def _compact_character_profile_for_reply(character_prompt_context: str) -> str:
    """Compile raw character material into a short Step-2 profile.

    Step 2 may read the full character prompt. Step 3 should only receive the
    bits needed to perform the current reply, so this keeps identity plus a small
    style sketch instead of forwarding the whole raw setting.
    """
    raw = str(character_prompt_context or "").strip()
    if not raw:
        return ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    name = next((ln for ln in lines if ln.startswith("角色名称：")), "")
    profile_lines: list[str] = []
    if name:
        profile_lines.append(name)
    signal_keywords = (
        "性格",
        "语气",
        "说话",
        "口癖",
        "称呼",
        "种族",
        "身份",
        "职业",
        "喜欢",
        "喜好",
        "讨厌",
        "经历",
        "过去",
        "背景",
        "成就",
        "特点",
        "personality",
        "tone",
        "voice",
        "species",
        "like",
        "history",
        "experience",
    )
    for ln in lines:
        if ln == name:
            continue
        if any(k in ln for k in signal_keywords):
            limit = 90 if ln.startswith(("说话风格", "详细设定", "角色设定", "systemPrompt")) else 180
            profile_lines.append(_clip_line(ln, limit))
        if len(profile_lines) >= 7:
            break
    if len(profile_lines) <= 1:
        for ln in lines:
            if ln == name:
                continue
            profile_lines.append(_clip_line(ln, 120))
            if len(profile_lines) >= 5:
                break
    return "\n".join(profile_lines)[:1200]


_CHARACTER_HOMEPAGE_PROFILE_KEYS = (
    "名称",
    "个性签名",
    "性别",
    "种族",
    "种族解剖学补充",
    "年龄",
    "16人格",
    "性格",
    "兴趣",
    "简介",
)


def _extract_character_homepage_profile_fields_for_reply(character_prompt_context: str) -> dict[str, str]:
    raw = str(character_prompt_context or "").strip()
    if not raw or "【角色档案】" not in raw:
        return {}
    match = re.search(r"【角色档案】\s*\n(?P<body>.*?)(?:\n\s*\n|$)", raw, re.S)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group("body").splitlines():
        item = re.sub(r"\s+", " ", line).strip()
        if not item or "角色主页档案" in item:
            continue
        m = re.match(rf"^({'|'.join(_CHARACTER_HOMEPAGE_PROFILE_KEYS)})[：:](.+)$", item)
        if not m:
            continue
        key = m.group(1).strip()
        value = _clip_line(m.group(2).strip(), 260 if key == "简介" else 180)
        if value:
            fields[key] = value
    return fields


def _extract_character_homepage_profile_for_reply(character_prompt_context: str) -> str:
    """Extract only the creator-filled homepage archive for Step 3.

    The full character prompt can be very large and should stay in Step 1/2.
    The compact homepage archive is stable profile data, so Step 3 should keep
    seeing it next to the turn-specific self-cognition result.
    """
    fields = _extract_character_homepage_profile_fields_for_reply(character_prompt_context)
    if not fields:
        return ""
    lines: list[str] = []
    for key in _CHARACTER_HOMEPAGE_PROFILE_KEYS:
        value = fields.get(key)
        if value:
            lines.append(f"{key}：{value}")
    return "\n".join(lines)[:1200]


def _character_homepage_profile_query_targets(user_text: str) -> list[str]:
    text = re.sub(r"\s+", "", str(user_text or ""))
    if not text:
        return []
    if (
        re.search(r"(当前对话角色|当前角色|角色设定中的角色)", text)
        and re.search(r"(心理活动|身体状态|内心活动|感受描写|动作描写|写出此刻)", text)
    ):
        return []
    asks_user_profile = bool(
        re.search(
            r"(你知道我|你记得我|我几岁|我多大|我的年龄|我的性别|我的种族|我的16人格|我的人格|我的兴趣|我的爱好|我的设定|我的资料|我是谁|我叫什么|知道我什么)",
            text,
        )
    )
    if asks_user_profile:
        return []
    asks_character = bool(
        re.search(r"(你|你的|你自己|介绍一下自己|自我介绍|角色档案|你的资料|你的档案)", text)
    )
    if not asks_character:
        return []
    targets: list[str] = []

    def add(key: str) -> None:
        if key not in targets:
            targets.append(key)

    if re.search(r"(你是谁|介绍一下你自己|介绍一下自己|自我介绍|你的资料|你的档案|角色档案)", text):
        for key in ("名称", "性别", "种族", "年龄", "16人格", "性格", "兴趣", "简介"):
            add(key)
    if re.search(r"(叫什么|名字|名称)", text):
        add("名称")
    if re.search(r"(几岁|多大|年龄|今年)", text):
        add("年龄")
    if re.search(r"(种族|物种|陆马|飞马|独角兽|人类)", text):
        add("种族")
    if re.search(r"(性别|雌性|雄性|男|女)", text):
        add("性别")
    if re.search(r"(16人格|十六人格|MBTI|人格)", text, re.I):
        add("16人格")
    if re.search(r"(性格|脾气|个性)", text):
        add("性格")
    if re.search(r"(兴趣|爱好|喜欢什么|喜欢做什么|喜好)", text):
        add("兴趣")
    if re.search(r"(喜欢糖|糖|碧琪|家人|二姐|博士|岩石学|简介|背景)", text):
        add("简介")
    return targets[:8]


def build_character_homepage_profile_answer_card(
    character_prompt_context: str,
    user_text: str,
) -> str:
    fields = _extract_character_homepage_profile_fields_for_reply(character_prompt_context)
    if not fields:
        return ""
    targets = _character_homepage_profile_query_targets(user_text)
    if not targets:
        return ""
    selected = [(key, fields.get(key, "")) for key in targets if fields.get(key)]
    if not selected:
        return ""
    target_text = "、".join(key for key, _ in selected)
    fact_lines = "\n".join(f"- {key}：{value}" for key, value in selected)
    return (
        "【当前角色档案问答执行卡｜最后采用】\n"
        f"本轮用户正在询问当前角色自己的{target_text}，不是询问用户资料。角色主页档案给出明确字段：\n"
        f"{fact_lines}\n"
        "执行要求：直接用角色口吻回答这些字段；年龄、种族、性别、16人格等字段必须逐字采用本卡明确值。"
        "其中 16人格 只提供性格倾向参考，用来辅助表达风格、决策倾向和互动节奏。"
        "不要用【对话背景】里的用户年龄/种族/性别回答角色自己，不要凭同名角色旧印象或作品外常识改写，不要说不记得或不知道。"
        "若 Stage 2 自我认知摘取、省略或写错了这些字段，以本执行卡为准。"
    )


def _extract_character_name_from_context(character_prompt_context: str) -> str:
    for line in str(character_prompt_context or "").splitlines():
        line = line.strip()
        if line.startswith("角色名称："):
            return line.split("：", 1)[1].strip()
        if line.startswith("名称："):
            return line.split("：", 1)[1].strip()
        if line.lower().startswith("name:"):
            return line.split(":", 1)[1].strip()
    return ""


def _has_explicit_partner_evidence(
    *texts: str,
    current_character_name: str = "",
) -> bool:
    blob = "\n".join(str(t or "") for t in texts if str(t or "").strip())
    current_character_name = str(current_character_name or "").strip()
    user_labels = {"用户", "{{USER}}", "user", "User"}

    def _has_current_user_pair(segment: str) -> bool:
        if not current_character_name or current_character_name not in segment:
            return False
        user_side = r"(Jason|用户|\{\{USER\}\}|你)"
        rel_side = r"(确认.{0,8}(恋爱|关系)|正式.{0,6}(情侣|恋人)|在一起|情侣|恋人|伴侣|爱人|对象)"
        name = re.escape(current_character_name)
        return bool(
            re.search(rf"{name}.{{0,18}}(和|与|跟).{{0,18}}{user_side}.{{0,24}}{rel_side}", segment)
            or re.search(rf"{user_side}.{{0,18}}(和|与|跟).{{0,18}}{name}.{{0,24}}{rel_side}", segment)
            or re.search(rf"{user_side}.{{0,16}}(向|对){name}.{{0,12}}表白", segment)
            or re.search(rf"{name}.{{0,16}}(答应|接受|回应).{{0,16}}{user_side}.{{0,12}}(表白|在一起)", segment)
        )

    for raw_line in blob.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        speaker = ""
        m = re.match(r"^([^：:\n]{1,40})[：:]\s*(.*)$", line)
        if m:
            speaker = m.group(1).strip()
            line = m.group(2).strip()
        speaker_is_current = bool(current_character_name and speaker == current_character_name)
        speaker_is_user = speaker in user_labels
        for segment in re.split(r"[。；;.!！？?]+", line):
            segment = segment.strip()
            if not segment or not _EXPLICIT_PARTNER_EVIDENCE_RE.search(segment):
                continue
            if _NEGATED_PARTNER_EVIDENCE_RE.search(segment):
                continue
            if re.search(r"(我|我们|咱们|双方|彼此)", segment):
                if not speaker or speaker_is_current or speaker_is_user:
                    return True
                continue
            if _has_current_user_pair(segment):
                return True
    return False


def _relationship_evidence_blob_from_messages(
    recent_messages: Optional[List[dict]],
    *,
    current_character_name: str = "",
) -> str:
    lines: list[str] = []
    current_character_name = str(current_character_name or "").strip() or "当前角色"
    for msg in recent_messages or []:
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        role = str(msg.get("role") or "").strip().lower()
        if role == "user":
            speaker = "用户"
        elif role == "assistant":
            speaker = str(msg.get("speaker_name") or msg.get("speakerName") or current_character_name).strip()
        else:
            speaker = role or "未知"
        lines.append(f"{speaker}：{content}")
    return "\n".join(lines)


def apply_relationship_stage_evidence_guard(
    planner_result: Dict[str, Any],
    recent_messages: Optional[List[dict]],
    environment_context: str = "",
    *,
    current_character_name: str = "",
) -> Dict[str, Any]:
    """Do not let ambiguous intimacy or third-party romance become partner status."""
    if not isinstance(planner_result, dict):
        return planner_result
    stage = str(planner_result.get("relationship_stage") or "").strip().lower()
    if stage not in {"committed_partner", "intimate_partner"}:
        return planner_result

    recent_blob = _relationship_evidence_blob_from_messages(
        recent_messages,
        current_character_name=current_character_name,
    )
    planner_blob = "\n".join(
        str(planner_result.get(k) or "")
        for k in (
            "reply_intent",
            "memory_use_policy",
            "risk_notes",
            "expression_policy",
            "proactive_seed",
        )
    )
    if _has_explicit_partner_evidence(
        recent_blob,
        environment_context,
        current_character_name=current_character_name,
    ):
        return planner_result

    out = dict(planner_result)
    out["relationship_stage"] = "flirting"
    if str(out.get("requested_escalation") or "").strip().lower() in {"sexual_intimacy", "long_term_commitment"}:
        out["requested_escalation"] = "physical_intimacy"
    out["risk_notes"] = _append_policy_text(
        out.get("risk_notes"),
        "关系阶段证据闸：未找到当前角色与用户已确认恋爱/伴侣/表白答应的明确证据；抱着、独处、喜欢被抱、进房间等只说明暧昧或亲密互动，不能升级为 committed_partner/intimate_partner。",
    )
    out["memory_use_policy"] = _append_policy_text(
        out.get("memory_use_policy"),
        "若记忆中出现其他角色与用户的恋爱关系，必须保留角色名字，不得把第三方伴侣关系转写成当前角色与用户的关系。",
    )
    if _AMBIGUOUS_INTIMACY_ONLY_RE.search(planner_blob):
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            "按 flirting 关系承接：可以半推半就、犹豫后靠近或确认意图，但不要写成已经是伴侣、不要使用伴侣名分作为依据。",
        )
    return out


def _character_alias_identity_note(character_prompt_context: str, max_aliases: int = 10) -> str:
    """Return a short note saying known aliases refer to the current character."""
    name = _extract_character_name_from_context(character_prompt_context)
    if not name:
        return ""
    aliases_path = Path(__file__).resolve().parents[1] / "data" / "mlp" / "aliases.json"
    try:
        data = json.loads(aliases_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        return ""
    names = {name}
    changed = True
    while changed and len(names) < 40:
        changed = False
        for raw_alias, raw_canonical in data.items():
            alias = str(raw_alias or "").strip()
            canonical = str(raw_canonical or "").strip()
            if not alias or alias.startswith("_") or not canonical:
                continue
            if alias in names or canonical in names:
                before = len(names)
                names.add(alias)
                names.add(canonical)
                changed = len(names) > before
    if len(names) <= 1:
        return ""
    ordered = [name] + sorted(x for x in names if x != name)
    aliases = "、".join(ordered[:max_aliases])
    return (
        f"{aliases} 都是当前角色自己的名字或译名；"
        "正文提到这些名字时按自指处理，改写成“我/自己/我的另一个名字”，不要写成另一个角色、朋友或第三方。"
    )


_CHARACTER_PROFILE_ASPECTS: dict[str, tuple[str, ...]] = {
    "identity": ("角色名称", "名称", "身份", "职业", "工作", "种族", "性别", "年龄", "几岁", "多大", "16人格", "MBTI", "来自", "住在", "家", "name", "species"),
    "voice": ("性格", "语气", "说话", "口癖", "称呼", "特点", "16人格", "MBTI", "personality", "tone", "voice"),
    "likes": ("喜欢", "喜好", "爱好", "兴趣", "讨厌", "害怕", "在意", "like", "dislike"),
    "history": ("经历", "过去", "以前", "故事", "背景", "成就", "简介", "自我介绍", "history", "experience"),
    "environment": ("环境", "天气", "时间", "夜晚", "白天", "季节", "地点", "居住", "weather", "place"),
    "intimacy": ("亲密", "恋人", "朋友", "关系", "害羞", "主动", "边界", "拥抱", "亲吻", "relationship"),
    "abilities": ("能力", "擅长", "技能", "魔法", "飞行", "速度", "工作方式", "ability", "skill"),
    "appearance": ("外貌", "服装", "身体", "鬃毛", "翅膀", "角", "蹄", "尾巴", "appearance"),
}


def _coerce_character_profile_focus(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        aspects = [
            str(x).strip()
            for x in (value.get("aspects") if isinstance(value.get("aspects"), list) else [])
            if str(x).strip()
        ][:8]
        return {
            "query": str(value.get("query") or "").strip(),
            "aspects": aspects,
            "reason": str(value.get("reason") or "").strip(),
        }
    return {"query": "", "aspects": [], "reason": ""}
