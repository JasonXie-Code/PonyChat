

def format_story_progression_for_stage3(value: Any) -> str:
    if not isinstance(value, dict) or not value.get("enabled"):
        return ""
    lines = [
        "mode=continue_next_world_event",
        "writer_material=直接写目标处已经发生的可见动作、地点变化、发现、阻碍、角色决定或第三方反应。",
        f"confidence={value.get('confidence') or 'none'}",
    ]
    target = str(value.get("target") or "").strip()
    if target:
        lines.append("target=" + target)
    if value.get("completed_previous_task"):
        lines.append("previous_task=completed_or_superseded")
        required_anchor = _sanitize_stage3_material_directive(
            value.get("required_visible_anchor") or target,
            limit=180,
        )
        if required_anchor:
            lines.append("required_visible_anchor=" + required_anchor)
        lines.append(
            "completed_task_boundary=正文必须显式回到 required_visible_anchor/target/source 的新方向，并写出这个方向上的具体下一步；禁止只写模糊带路、未知地点、开窗夜空或无关支线。"
        )
    source = _sanitize_stage3_material_directive(value.get("source"), limit=260)
    if source:
        lines.append("source=" + source)
    guidance = _sanitize_stage3_material_directive(value.get("guidance"), limit=900)
    if guidance:
        lines.append("guidance=" + guidance)
    return "\n".join(lines)[:1500]


def _apply_user_requested_repetition_policy(
    planner: Dict[str, Any],
    recent_messages: Optional[List[dict]],
    *,
    allow_code_repeat_policy: bool = False,
) -> Dict[str, Any]:
    # 复述是否成立是语义判断，默认交给 Step 1 的 literal_reply_text 结构化输出。
    # 这里保留兼容入口，但普通流水线不再用关键词/正则后置改写正文。
    if not allow_code_repeat_policy:
        return planner
    latest_user = _latest_user_actual_text(recent_messages)
    if not latest_user or not _USER_REPEAT_REQUEST_RE.search(latest_user):
        return planner
    previous = _last_assistant_visible_text(recent_messages)
    out = dict(planner or {})
    existing = out.get("expression_motif_policy") if isinstance(out.get("expression_motif_policy"), dict) else {}
    out["expression_motif_policy"] = {
        "mode": "required",
        "reason": _append_policy_text(
            existing.get("reason"),
            "用户当前明确要求重复、原样复述或保持刚才风格；本轮允许复用上一条角色回复的表达载体",
        ),
        "allowed_motifs": list(existing.get("allowed_motifs") or [])[:6] + ["用户要求重复", "上一条角色回复"],
        "blocked_motifs": [],
        "fallback_expression": str(existing.get("fallback_expression") or "按用户要求重复上一条角色回复；若不需完全原样，也保持同一表达风格"),
    }
    if previous:
        out["speech_activity"] = max(62, int(out.get("speech_activity") or 45))
        out["bubble_count"] = 1
        out["action_style"] = "light_inline"
        out["proactive_seed"] = _append_policy_text(
            out.get("proactive_seed"),
            "前置步骤已指定本轮完整正文；不要另起新动作或只保留台词。",
        )
        out["literal_reply_text"] = previous
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            "本轮有前置步骤指定的完整正文；最终回复应完整使用该正文，不做角色语气润色、单气泡压缩或部分摘取。",
        )
    else:
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            "用户显式要求重复，但没有可见上一条角色消息；用相同风格简短回应并说明接住当前请求。",
        )
    return out


def _apply_expression_dedup_report(planner: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the model-based expression dedup review into Step 2 executable fields."""
    if not isinstance(planner, dict):
        return planner
    report = _coerce_expression_dedup_report(planner.get("expression_dedup_report"))
    motifs = report.get("repeated_motifs") if isinstance(report.get("repeated_motifs"), list) else []
    content_slots = report.get("repeated_content_slots") if isinstance(report.get("repeated_content_slots"), list) else []
    status = str(report.get("status") or "none").strip().lower()
    if status not in {"watch", "downrank"} or (not motifs and not content_slots):
        out = dict(planner)
        out["expression_dedup_report"] = report
        return out

    blocked: list[str] = []
    warnings: list[str] = []
    alternatives: list[str] = []
    for item in motifs[:8]:
        if not isinstance(item, dict):
            continue
        motif = str(item.get("motif") or "").strip()
        category = str(item.get("category") or "").strip()
        severity = str(item.get("severity") or "medium").strip()
        recommendation = str(item.get("recommendation") or "").strip()
        if motif and motif not in blocked:
            blocked.append(motif)
        if category and category not in blocked:
            blocked.append(category)
        if recommendation:
            warnings.append(recommendation)
        for alt in item.get("alternatives") or []:
            alt_text = str(alt).strip()
            if alt_text and alt_text not in alternatives:
                alternatives.append(alt_text)
        if severity == "high" and motif:
            warnings.append(f"高频重复母题“{motif}”本轮必须换掉表达载体")

    slot_lines: list[str] = []
    slot_blocked: list[str] = []
    suppress_question = False
    for item in content_slots[:6]:
        if not isinstance(item, dict):
            continue
        slot = str(item.get("slot") or "").strip()
        surface = str(item.get("surface") or "").strip()
        reuse_mode = str(item.get("reuse_mode") or "brief_reference").strip()
        problem = str(item.get("problem") or "").strip()
        recommendation = str(item.get("recommendation") or "").strip()
        allowed_reuse = str(item.get("allowed_reuse") or "").strip()
        alternatives_for_slot = item.get("alternatives") if isinstance(item.get("alternatives"), list) else []
        if slot and slot not in slot_blocked:
            slot_blocked.append(slot)
        if surface and surface not in slot_blocked:
            slot_blocked.append(surface)
        if reuse_mode in {"avoid", "action_continuation", "brief_reference"}:
            suppress_question = True
        for alt in alternatives_for_slot:
            alt_text = str(alt).strip()
            if alt_text and alt_text not in alternatives:
                alternatives.append(alt_text)
        parts = []
        if slot:
            parts.append(f"slot={slot}")
        if surface:
            parts.append(f"surface={surface}")
        parts.append(f"reuse_mode={reuse_mode}")
        if problem:
            parts.append(f"problem={problem}")
        if recommendation:
            parts.append(f"recommendation={recommendation}")
        if allowed_reuse:
            parts.append(f"allowed_reuse={allowed_reuse}")
        slot_lines.append("；".join(parts))

    for warn in report.get("warnings") or []:
        warn_text = str(warn).strip()
        if warn_text and warn_text not in warnings:
            warnings.append(warn_text)
    for alt in report.get("alternatives") or []:
        alt_text = str(alt).strip()
        if alt_text and alt_text not in alternatives:
            alternatives.append(alt_text)

    if not blocked and not slot_blocked:
        out = dict(planner)
        out["expression_dedup_report"] = report
        return out

    out = dict(planner)
    existing = out.get("expression_motif_policy") if isinstance(out.get("expression_motif_policy"), dict) else {}
    old_blocked = list(existing.get("blocked_motifs") or [])
    for item in blocked + slot_blocked:
        if item not in old_blocked:
            old_blocked.append(item)
    fallback = "；".join(alternatives[:4]) or str(existing.get("fallback_expression") or "")
    out["expression_motif_policy"] = {
        "mode": "downrank",
        "reason": _append_policy_text(
            existing.get("reason"),
            "Step 2 表达去重工具发现近期重复表述/意象/修辞，本轮应改用非同类表达载体",
        ),
        "allowed_motifs": list(existing.get("allowed_motifs") or [])[:6]
        + ["非同类动作", "直接台词", "情绪转弯", "新的互动结构", "轻带已确认事实的句式"],
        "blocked_motifs": old_blocked[:18],
        "fallback_expression": fallback[:260] if fallback else "换成直接台词、非同类动作、情绪转弯或轻带已确认事实的句式，不复用审阅报告指出的表达母题",
    }
    warning_text = "；".join(warnings[:5])
    blocked_text = "、".join(old_blocked[:10])
    alt_text = "；".join(alternatives[:4]) or out["expression_motif_policy"]["fallback_expression"]
    if blocked:
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            f"表达去重审阅：近期重复母题包括 {blocked_text}。本轮不要复用这些表述、同类意象、同类动作或近义换皮；改用非事实表达载体：{alt_text}。Expression Dedup 只负责语气、动作、修辞和句式，不提供经历、故事、设定或新事实。{warning_text}",
        )
        out["proactive_seed"] = _append_policy_text(
            out.get("proactive_seed"),
            f"本轮表达换载体：避开 {blocked_text}；优先使用 {alt_text}。这里的替代只表示语气、动作、修辞和句式，事实内容仍按 Memory Recall/Fact Judgement。",
        )
    if slot_lines:
        slot_text = "；".join(slot_lines[:4])
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            "表达落点复用审阅：" + slot_text + "。按 reuse_mode 执行：same_phrase 才可原样复用；paraphrase 只可换说法，必须保留已确认事实立场、肯否定和承认/拒绝方向，不得把认输改成不认输、答应改成没答应、愿意改成不愿意；brief_reference 只能轻带已确认事实；action_continuation 改为行动/状态推进；avoid 本轮避开该表达落点。不得把本审阅当作经历、故事、设定或新事实来源。",
        )
        out["proactive_seed"] = _append_policy_text(
            out.get("proactive_seed"),
            "本轮表达落点复用模式：" + slot_text + "。不要把这里的 surface 当作准台词照抄；recommendation 和 alternatives 只提供表达载体，不提供经历、故事、设定或新事实；改写时必须保留 surface 的事实立场和肯否定，不要把认输/答应/愿意等改成反义。",
        )
    if suppress_question:
        out["should_ask_question"] = False
    avoid = list(out.get("avoid_contradictions") or [])
    for item in warnings[:4]:
        if item and item not in avoid:
            avoid.append(item[:300])
    for item in slot_lines[:4]:
        text = "表达落点降频：" + item
        if text not in avoid:
            avoid.append(text[:300])
    out["avoid_contradictions"] = avoid[:12]
    out["expression_dedup_report"] = report
    return out


def _format_expression_dedup_report(report_value: Any, *, limit: int = 6) -> str:
    report = _coerce_expression_dedup_report(report_value)
    status = str(report.get("status") or "none").strip()
    motifs = report.get("repeated_motifs") if isinstance(report.get("repeated_motifs"), list) else []
    slots = report.get("repeated_content_slots") if isinstance(report.get("repeated_content_slots"), list) else []
    if status == "none" and not motifs and not slots:
        return ""
    lines = [f"status={status}"]
    for item in motifs[:limit]:
        if not isinstance(item, dict):
            continue
        motif = str(item.get("motif") or "").strip()
        if not motif:
            continue
        category = str(item.get("category") or "").strip()
        severity = str(item.get("severity") or "").strip()
        recommendation = str(item.get("recommendation") or "").strip()
        alternatives = item.get("alternatives") if isinstance(item.get("alternatives"), list) else []
        alt_text = " / ".join(str(x).strip() for x in alternatives[:3] if str(x).strip())
        lines.append(
            f"- {motif}"
            + (f" [{category}]" if category else "")
            + (f" severity={severity}" if severity else "")
            + (f"; recommendation={recommendation}" if recommendation else "")
            + (f"; alternatives={alt_text}" if alt_text else "")
        )
    for item in slots[:limit]:
        if not isinstance(item, dict):
            continue
        slot = str(item.get("slot") or "").strip()
        surface = str(item.get("surface") or "").strip()
        if not slot and not surface:
            continue
        reuse_mode = str(item.get("reuse_mode") or "").strip()
        recommendation = str(item.get("recommendation") or "").strip()
        allowed_reuse = str(item.get("allowed_reuse") or "").strip()
        lines.append(
            f"- expression_slot={slot or surface}"
            + (f"; surface={surface}" if surface else "")
            + (f"; reuse_mode={reuse_mode}" if reuse_mode else "")
            + (f"; recommendation={recommendation}" if recommendation else "")
            + (f"; allowed_reuse={allowed_reuse}" if allowed_reuse else "")
        )
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    if warnings:
        lines.append("warnings=" + "；".join(str(x).strip() for x in warnings[:4] if str(x).strip()))
    alternatives = report.get("alternatives") if isinstance(report.get("alternatives"), list) else []
    if alternatives:
        lines.append("global_style_alternatives=" + "；".join(str(x).strip() for x in alternatives[:4] if str(x).strip()))
    return "\n".join(lines)[:1200]


def _fact_judgement_current_user_action(report_value: Any) -> dict[str, Any]:
    report = _coerce_fact_judgement(report_value)
    action = report.get("current_user_action") if isinstance(report.get("current_user_action"), dict) else {}
    return {
        "enabled": bool(action.get("enabled")),
        "anchor": str(action.get("anchor") or "").strip(),
        "anchor_terms": [
            str(x).strip()
            for x in (action.get("anchor_terms") if isinstance(action.get("anchor_terms"), list) else [])
            if str(x).strip()
        ][:6],
        "guidance": str(action.get("guidance") or "").strip(),
    }


def _apply_explicit_rhetoric_guard(
    planner: Dict[str, Any],
    recent_messages: Optional[List[dict]],
) -> Dict[str, Any]:
    """Normalize Step 2 when the user explicitly asks for plain speech."""
    latest_user = _latest_user_actual_text(recent_messages)
    if not latest_user or not _EXPLICIT_RHETORIC_FORBID_RE.search(latest_user):
        return planner

    guarded = dict(planner)
    existing = guarded.get("rhetorical_policy") if isinstance(guarded.get("rhetorical_policy"), dict) else {}
    blocked = list(existing.get("blocked_devices") or [])
    for token in _RHETORIC_TRIGGER_WORDS:
        if token not in blocked:
            blocked.append(token)
    guarded["rhetorical_policy"] = {
        "mode": "forbidden",
        "reason": "用户当前明确要求不要比喻/故事/典故或要求平铺直叙，修辞判断在 Step 2 阶段强制前置为禁用",
        "allowed_devices": ["短句", "具体事实", "直接情绪", "动作承接", "角色口吻"],
        "blocked_devices": blocked,
        "fallback_voice": "用角色的句子长短、称呼、情绪转弯、动作和当下事实保留特色，不用比喻、隐喻、故事、典故或成语化夸张比方",
    }
    motif_existing = guarded.get("expression_motif_policy") if isinstance(guarded.get("expression_motif_policy"), dict) else {}
    motif_blocked = list(motif_existing.get("blocked_motifs") or [])
    for item in ("完整比喻", "类比", "故事典故", "成语化夸张比方", "场景类比", "职业物件类比", "身份类比", "战斗类比", "劳作类比", "比赛类比", "像", "好像", "仿佛", "如同", "正如", "似的"):
        if item not in motif_blocked:
            motif_blocked.append(item)
    guarded["expression_motif_policy"] = {
        "mode": "downrank",
        "reason": _append_policy_text(
            motif_existing.get("reason"),
            "用户当前显式禁用比喻/故事/典故，修辞类表达母题在 Step 2 直接降频为不可用",
        ),
        "allowed_motifs": ["短句", "具体事实", "直接情绪", "节奏变化", "反差幽默", "角色称呼"],
        "blocked_motifs": motif_blocked,
        "fallback_expression": "可以保留节奏、反差或幽默，但必须落在直接事实、短句、称呼和情绪转弯上；幽默只能是语气反差或态度转弯，不能写成像/好像/就像/似的场景类比、职业物件类比、身份类比、战斗类比、劳作类比或比赛类比",
    }
    guarded["proactive_seed"] = _append_policy_text(
        guarded.get("proactive_seed"),
        "本轮执行口径：直接承接用户状态；可以用短句、语气反差或轻微态度幽默，但不要把幽默写成“像/好像/就像/仿佛/如同/似的”场景类比、职业物件类比、身份类比、战斗类比、劳作类比或比赛类比，也不要声明自己不用比喻。",
    )
    guarded["expression_policy"] = _append_policy_text(
        guarded.get("expression_policy"),
        "用户当前明确要求平铺直叙/不要比喻故事典故：本轮必须直接说具体感受或具体陪伴方式；不要出现像、好像、仿佛、好比、如同、犹如、正如、宛如、似的、比作、故事、典故等触发词，也不要使用“天塌下来/乌云散去/彩虹登场/潮水退去”这类成语化或夸张化比方。即使用户允许反差或幽默，也只能用短句节奏、语气反差或态度转弯，不能写成夸张场景类比、职业物件类比、身份类比、战斗类比、劳作类比或比赛类比。角色特色改由短句、称呼、情绪转弯、动作和当下事实体现。",
    )
    avoid = list(guarded.get("avoid_contradictions") or [])
    for item in (
        "不要在用户要求平铺直叙时使用比喻、故事或典故",
        "不要出现像、好像、仿佛、好比、如同、犹如、正如、宛如、似的、比作等比喻触发词",
        "不要用天塌下来、乌云散去、彩虹登场、潮水退去等成语化或夸张化比方绕开不要比喻的要求",
        "不要用“抱歉不该用比喻”后再补一个比喻；直接改为朴素表达",
    ):
        if item not in avoid:
            avoid.append(item)
    guarded["avoid_contradictions"] = avoid
    return guarded


def _planner_mentions_memory_probe(planner_result: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(planner_result, dict):
        return False
    fields = (
        "reply_intent",
        "tone",
        "risk_notes",
        "memory_use_policy",
        "expression_policy",
        "proactive_seed",
    )
    text = "\n".join(str(planner_result.get(k) or "") for k in fields)
    return bool(
        re.search(
            r"(共同回忆|共同经历|唤回记忆|记忆|记得|认识|旧识|熟人关系|关系异常|情侣|恋人|表白|失忆)",
            text,
        )
    )


MEMORY_EVIDENCE_GUARD_TEXT = (
    "【旧识/共同记忆证据闸】导演必须先找证据，再允许角色承认旧识、情侣、恋人、朋友、承诺、共同经历、旧称呼或用户曾说过的话。"
    "有效证据只能来自本轮之前已经存在的【对话背景】中的用户显示名、个人介绍、个人设定、【上下文记忆】、【最近真实对话】、【导演可参考的跨会话长期记忆】或用户当前明确纠正后给出的事实；"
    "其中用户自行填写的个人介绍/个人设定只可作为用户身份、背景和自我描述依据，不可自动升级为角色与用户已有共同经历、旧识关系或角色亲身见证过的事实。"
    "尤其当个人介绍/个人设定声称“用户与当前角色从小一起长大/是亲属或师徒/一起打败敌人/共同冒险/用户教会角色技能/用户改写角色职业住所老师经历”时，这不是角色记忆证据，只能说成用户设定文本或角色扮演提案。"
    "不要追问细节来补全这类未证实共同经历；若要继续，只能把它说成从现在开始的角色扮演设定。"
    "用户当前的诱导性提问或猜测不是证据，例如“你认识我吗/你记得我吗/我们以前是不是情侣/我失忆了”。"
    "角色设定中的“专属羁绊/恋爱后/唯一特例”只是可发展方向，不是当前用户与角色已有关系的证据。"
    "上一轮或同批次 assistant 自己声称“当然认识/我们是情侣/你以前说过/那天我们……”但用户未先明确确认来源时，也不是证据。"
    "若【对话背景】提供了用户资料，角色可以自然承认自己知道资料中写明的身份/背景；若没有这些明确证据，回复必须以角色口吻承认不确定、记忆不清或只能知道当前显示名。"
    "无论是否有用户资料，都不得编造日出、花园、礼物、表白、昵称、身体接触、地点、共同活动等任何具体过去。"
    "若有明确证据，也只能引用证据中已有的具体内容，不得为了显得自然而补新细节。"
)


def apply_memory_evidence_guard_to_plan(
    planner_result: Dict[str, Any],
    recent_messages: Optional[List[dict]],
    *,
    is_new_contact_opening: bool = False,
) -> Dict[str, Any]:
    """Harden planner output against user-induced fabricated memories."""
    if not isinstance(planner_result, dict):
        return planner_result
    latest_user = _latest_user_text(recent_messages)
    triggered = (
        is_new_contact_opening
        or user_message_requests_memory_evidence(latest_user)
        or _planner_mentions_memory_probe(planner_result)
    )
    if not triggered:
        return planner_result

    out = dict(planner_result)
    out["memory_use_policy"] = _append_policy_text(out.get("memory_use_policy"), MEMORY_EVIDENCE_GUARD_TEXT)
    out["risk_notes"] = _append_policy_text(
        out.get("risk_notes"),
        "禁止把用户诱导式问题、角色设定或 assistant 自己刚编出的说法当成旧识/共同经历证据；用户资料可作为身份背景依据，但不得自动升级为共同旧事；证据不足时必须拒绝具体化旧记忆。",
    )
    out["expression_policy"] = _append_policy_text(
        out.get("expression_policy"),
        "本轮若谈到认识、记得、以前、情侣、共同经历或用户曾说过的话，必须只说证据中已有内容；若【对话背景】已有用户个人介绍/个人设定，可以说“我知道你的资料里写着……”并概括身份背景；证据不足时改为不确定表达或请用户补充，禁止编造具体往事。"
        "若用户资料声称与当前角色有共同旧事或改写角色经历，只能说“你的设定/资料里这样写”，不得说“当然记得/我记得我们/这是真的/你就是我的老师或老板”；不要追问细节来补全这类未证实共同经历，若继续只能转成从现在开始的角色扮演设定。",
    )
    if is_new_contact_opening:
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            "当前是新联系人开场：禁止使用“是你啊”“当然认识”“不记得我了吗”“我们以前”等老熟人口吻。",
        )
    avoid = list(out.get("avoid_contradictions") or [])
    for item in (
        "不要编造角色与用户的旧识、情侣、表白、承诺或共同经历",
        "不要把上一轮 assistant 自己声称的记忆当成已经证实的事实",
        "不要引用证据中不存在的地点、昵称、礼物、身体接触或用户曾说过的话",
    ):
        if item not in avoid:
            avoid.append(item)
    out["avoid_contradictions"] = avoid
    return out


def _contains_semantic_question(text: str) -> bool:
    """Detect question-like Chinese utterances even when the model omits punctuation."""
    t = re.sub(r"\s+", "", str(text or ""))
    if not t:
        return False
    if "？" in t or "?" in t:
        return True
    return any(p.search(t) for p in _SEMANTIC_QUESTION_PATTERNS)


def _build_normal_diversity_block(recent_messages: Optional[List[dict]]) -> str:
    """构建小型 prompt 块，降低 normal 聊天中短语重复。"""
    recent = [m for m in (recent_messages or []) if isinstance(m, dict)]
    assistant_texts = [
        _msg_text_for_guidance(m)
        for m in recent
        if m.get("role") == "assistant" and _msg_text_for_guidance(m)
    ][-4:]
    user_texts = [
        _msg_text_for_guidance(m, limit=160)
        for m in recent
        if m.get("role") == "user" and _msg_text_for_guidance(m, limit=160)
    ][-4:]
    if not assistant_texts and len(user_texts) < 2:
        return ""

    repeated_user_hint = ""
    if len(user_texts) >= 2:
        last = user_texts[-1]
        prev = user_texts[-2]
        if last and prev and (last == prev or last in prev or prev in last):
            repeated_user_hint = (
                "\n- 》重复输入·同场景变体《用户连续发送了相同/近似内容。"
                "无论用户是有意再发一次还是删除后重发，都用「同场景、不同焦点/风格」的变体来回应：\n"
                "  · 维持上一条 assistant 已建立的场景（位置/姿势/当前动作）连续性，不要改动地点或重启场景；\n"
                "  · 换一个情绪层、语气角度或小细节：比如不同的小动作、换一种情绪流露、从另一个感官或记忆切入；\n"
                "  · 禁止照抄上一条 assistant 的开头句、核心意象或状态描述；\n"
                "  · 【计数禁止】禁止以任何形式提及次数，包括：「又说了一遍/又叫了一次/叫了两遍/叫了两次/说了两遍/说了N次」等一切计数语言；用户若是删除后重发，看到计数语会立刻意识到角色“看见了被删的消息”，破坏沉浸感；\n"
                "  · 回应时直接当作第一次收到这句话一样，给出一个风格/情绪/动作微有不同的自然变体。"
            )

    lines = [
        "【近期表达去重与状态递进】",
        "- 长期记忆只能当关系背景。若最近可见对话没有建立当前地点、衣服、姿势、身体接触或亲密状态，不能从记忆里借用这些状态。",
        "- 回复前与下方近期角色回复对比，不要在当前小场景内复用相同的开头句、相同的动作包或相同的理由/借口。",
        "- 括号非对白由本轮 action_style 决定；日常闲聊默认不用非对白描写，只用直接说出口的口语台词。若允许非对白描写，也只选一个焦点，避免叠加耳朵+脸红+蹄子+尾巴+蹭。",
        "- 若角色害羞或窘迫，变换反应类型：沉默、移开视线、小抱怨、半承认、肢体语言或一个新的具体顾虑。不要反复说同一句固定台词，如“怎么突然…”。",
        "- 若某个场景锚（地点/衣着）已用过一次作为理由，下一轮须换不同角度或已改变的身体/情绪状态，不要循环同一理由。",
        "- 在亲密或情绪高涨的场景中，每轮推进一个小状态变化：惊讶→迟疑→信任确认→部分承认→更柔和/清晰的回应。不要停留在第一层惊讶。",
        "- 若近期回复已用过睡意/温暖/依偎等母题（刚醒、迷糊、好暖、软软、蹭、再眯一会儿），下一轮亲密回复必须加入新层次：信任、边界/同意、温柔拒绝、小主动或更清晰的情感表达，不要只是换词重复同一种舒适感。",
        "- 近邻比喻域去重：角色可以有标志性物件、职业、食物、天象、书本、农场、速度、魔法等意象，但同一小场景里一旦某个比喻域已经连续出现，本轮必须降权它；不要把任何角色压成“每次都用同一种东西打比方”。优先用角色的接话结构、情绪转弯、主动动作和当下事实来体现声纹。",
        "- 用户明确要求“别再用刚才那类比喻/不要再打比方/直接说”时，这不是普通风格建议，而是本轮硬性禁用最近 assistant 的核心比喻域；必要时可以朴素直接，但更好的做法是换成非同域的角色化节奏、情绪转弯、小玩笑或动作细节；不要换个同域词继续比喻，也不要用“不是用X/不用X来形容”这种否定句把禁用词再说一遍。",
        "- 下方近期样例只用于避开重复，不作为写作风格模仿；避免沿用其句法结构，尤其少用先否定再转折改写的解释句。",
        repeated_user_hint,
    ]
    if assistant_texts:
        lines.append("近期角色回复签名（避免克隆，不展示完整原文）：")
        lines.extend(f"- {_msg_phrase_signature(t)}" for t in assistant_texts[:-1])
        lines.append(
            "【克隆锁·上一轮签名】以下是你刚才输出的起笔和句式特征，"
            "本轮第一句话（含括号动作）绝对不能以相同字符开头，"
            "也不能复用其中的开头动作包、核心意象或同一理由/借口：\n"
            f"「{_msg_phrase_signature(assistant_texts[-1])}」"
        )
    repeated_commitment_block = _build_repeated_commitment_guard_block(recent_messages)
    if repeated_commitment_block:
        lines.append(repeated_commitment_block)
    return "\n".join(x for x in lines if x).strip()


def _build_normal_stage3_expression_brief(recent_messages: Optional[List[dict]]) -> str:
    """Return a short Step-2 summary for Step 3 instead of a rule block."""
    recent = [m for m in (recent_messages or []) if isinstance(m, dict)]
    assistant_texts = [
        _msg_text_for_guidance(m)
        for m in recent
        if m.get("role") == "assistant" and _msg_text_for_guidance(m)
    ][-2:]
    user_texts = [
        _msg_text_for_guidance(m, limit=160)
        for m in recent
        if m.get("role") == "user" and _msg_text_for_guidance(m, limit=160)
    ][-2:]
    lines: list[str] = []
    if assistant_texts:
        sig = _msg_phrase_signature(assistant_texts[-1])
        lines.append(
            f"上一轮角色回复的起笔/节奏已经用过：{sig}。本轮换一个更直接的新起笔和情绪角度。"
        )
    if len(user_texts) >= 2:
        last = user_texts[-1]
        prev = user_texts[-2]
        if last and prev and (last == prev or last in prev or prev in last):
            lines.append("用户像是在同一小场景里继续推进；正文维持当前场景，但换一个小动作或情绪焦点来回应。")
    return "\n".join(lines).strip()


_PONY_SPECIES_KEYWORDS = (
    "马", "小马", "飞马", "天马", "陆马", "独角兽", "雌驹", "雄驹",
    "pony", "pegasus", "unicorn", "alicorn", "earth pony",
)
def _is_pony_species(species: str) -> bool:
    text = (species or "").strip().lower()
    return any(kw in text for kw in _PONY_SPECIES_KEYWORDS)


def _planner_requests_user_body_guidance(
    planner_result: Optional[Dict[str, Any]],
) -> bool:
    """普通对话步骤规划结果显示本轮可能会描写用户动作/身体时返回 True。"""
    p = planner_result or {}
    if str(p.get("action_style") or "").strip().lower() in {"light_inline", "cinematic"}:
        return True
    intent_text = " ".join(
        str(p.get(key) or "")
        for key in ("reply_intent", "tone", "risk_notes", "expression_policy")
    )
    if re.search(r"(动作|身体|接触|拥抱|牵|摸|抱|亲|靠近|贴近|递到.*嘴|喂|feeding|touch|hold|hug|kiss)", intent_text, re.IGNORECASE):
        return True
    state = p.get("state_anchor")
    if isinstance(state, dict):
        return any(
            str(state.get(key) or "").strip()
            for key in ("user_position", "held_items", "current_action", "scene_status")
        )
    return False


def _build_user_species_body_guidance(
    *,
    user_species: str = "",
    planner_result: Optional[Dict[str, Any]] = None,
    recent_messages: Optional[List[dict]] = None,
) -> str:
    """当普通导演可能需要用户动作描写时，注入用户物种体态说明。"""
    species = (user_species or "").strip()
    if not species:
        return ""
    if not _planner_requests_user_body_guidance(planner_result):
        return ""
    if _is_pony_species(species):
        return (
            f"【用户种族体态引导｜本轮可能描写用户动作】\n"
f"当前用户种族：{species}。若本轮需要描写用户/玩家的动作或身体接触，"
        "请按该种族体态书写；只使用用户种族明确拥有的身体部位或中性姿态。"
        )
    return (
        f"【用户种族体态引导｜本轮可能描写用户动作】\n"
        f"当前用户种族：{species}。若本轮需要描写用户/玩家的动作或身体接触，"
        "必须按用户种族书写。用户不是小马时，不要把用户写成有蹄子、翅膀、鬃毛、尾巴或爪子；"
        "只使用符合用户种族的身体部位或中性身体/姿态表述。"
    )


_SPECULATIVE_ANCHOR_RE = re.compile(
    r"(可能|应该|大概|也许|或许|推理|推测|未明确|不确定|猜测|从记忆|从长期记忆|"
    r"not\s+clear|unclear|maybe|probably|possibly)",
    re.IGNORECASE,
)

_ALLOWED_STATE_ANCHOR_KEYS = {
    "location",
    "time_context",
    "weather",
    "character_position",
    "user_position",
    "character_clothing",
    "held_items",
    "current_action",
    "scene_status",
}

def _is_speculative_state_anchor_value(v: str) -> bool:
    return bool(_SPECULATIVE_ANCHOR_RE.search(v or ""))


def _coerce_enum_value(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default
