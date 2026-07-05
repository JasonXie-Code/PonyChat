from __future__ import annotations

import json

from .species_anatomy import equine_species_prompt_line, profile_species_has_equine_anatomy



_FACT_EVIDENCE_SYSTEM_MARKERS = (
    "【对话背景】",
    "【系统信息",
    "【用户档案",
    "【上下文记忆】",
    "【当前会话上下文记忆",
    "【被 @ 角色自己的普通聊天上下文记忆】",
    "【记忆指代说明】",
    "【意图识别可参考的跨会话长期记忆】",
    "【导演可参考的跨会话长期记忆】",
    "【长期记忆",
    "【短期记忆",
    "【中期记忆",
    "【当前事实锚",
    "【本轮临时发言者】",
    "【环境上下文】",
    "【当前环境】",
    "【用户上传图片",
    "【视觉",
    "【联网",
)

_FACT_EVIDENCE_SYSTEM_EXCLUDE_MARKERS = (
    "【角色设定参考",
    "【完整角色设定参考",
    "<CHARACTER_PROMPT_REFERENCE>",
    "ROLEPLAY_ANCHOR_PROMPT",
    "NORMAL_MODE_OUTPUT_STYLE_PROMPT",
    "用口语文字回复，像真人在聊天窗口里打字",
    "你就是上方设定中描述的那个角色",
)


def _compact_fact_evidence_system_content(content: str, *, max_len: int = 1800) -> str:
    raw = str(content or "").strip()
    if not raw:
        return ""
    if any(marker in raw for marker in _FACT_EVIDENCE_SYSTEM_EXCLUDE_MARKERS):
        kept: list[str] = []
        sections = re.split(r"(?=【[^】]{1,40}】)", raw)
        for section in sections:
            text = section.strip()
            if not text:
                continue
            if any(marker in text for marker in _FACT_EVIDENCE_SYSTEM_EXCLUDE_MARKERS):
                continue
            if any(marker in text for marker in _FACT_EVIDENCE_SYSTEM_MARKERS):
                kept.append(text[:700])
        return "\n\n".join(kept)[:max_len].strip()
    if any(marker in raw for marker in _FACT_EVIDENCE_SYSTEM_MARKERS):
        return raw[:max_len]
    return ""


def _fact_guard_evidence_from_messages(messages: Optional[List[dict]], *, limit: int = 18000) -> str:
    if not messages:
        return ""
    parts: list[str] = []
    for msg in messages[-24:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip()
        content = str(msg.get("content") or "").strip()
        if not role or not content:
            continue
        if role == "system":
            content = _compact_fact_evidence_system_content(content)
            if not content:
                continue
            label = "system"
            max_len = 1800
        elif role == "user":
            label = "user"
            max_len = 1200
        elif role == "assistant":
            label = "assistant"
            max_len = 1200
        else:
            label = role[:40]
            max_len = 900
        parts.append(f"[{label}]\n{content[:max_len]}")
    text = "\n\n".join(parts)
    return text[-limit:]


def _format_fact_judgement_scene_candidate(scene_candidate: Any, *, limit: int = 2200) -> tuple[str, str]:
    """Return (current_candidate, prior_background) from structured Step 1 output."""
    if not isinstance(scene_candidate, dict):
        return "", ""
    pieces: list[str] = []
    anchor = scene_candidate.get("scene_anchor")
    if isinstance(anchor, dict) and anchor:
        pieces.append("scene_anchor JSON:\n" + json.dumps(anchor, ensure_ascii=False)[:1200])
    card = str(scene_candidate.get("scene_card") or "").strip()
    if card:
        pieces.append("scene_card:\n" + card[:limit])
    text = "\n".join(piece for piece in pieces if piece.strip()).strip()[:limit]
    if not text:
        return "", ""
    source = str(scene_candidate.get("source") or "").strip()
    if source == "long_idle_prior_context":
        return "", text
    return text, ""


def _dialogue_perspective_hint_block(recent_messages: Optional[List[dict]]) -> str:
    latest_user = _latest_user_actual_text(recent_messages)
    lines = ["【对话代词解析结果｜高优先级】"]
    added_you_me_action_hint = False
    if latest_user and re.search(r"你.{0,10}(?:拉着|拉住|牵着|拽着|带着|带|把|让).{0,8}我", latest_user):
        lines.append(
            "- 当前 user 原文含“你…我”动作句，按聊天视角解析为：当前角色是“你”的动作主体或要求对象，当前用户是“我”。"
            "例如“你拉着我到了楼上”必须整理成“当前角色拉着当前用户上楼”；禁止写成“当前用户拉着当前角色上楼”或“当前角色被用户拉上楼”。"
        )
        added_you_me_action_hint = True
    if not added_you_me_action_hint:
        for msg in (recent_messages or [])[-8:]:
            if not isinstance(msg, dict) or str(msg.get("role") or "") != "user":
                continue
            content = re.sub(r"\s+", " ", str(msg.get("content") or "")).strip()
            if not content:
                continue
            if not re.search(r"你.{0,10}(?:拉着|拉住|牵着|拽着|带着|带|把|让).{0,8}我", content):
                continue
            quote = content[:120]
            lines.append(
                f"- 最近 user 原文「{quote}」含“你…我”动作句，按聊天视角解析为：当前角色是“你”的动作主体或要求对象，当前用户是“我”。"
                "例如“你拉着我到了楼上”必须整理成“当前角色拉着当前用户上楼”；禁止写成“当前用户拉着当前角色上楼”或“当前角色被用户拉上楼”。"
                "后续用户再发“请写你的心理活动/继续描写”不会改变这条历史动作主体。"
            )
            break
    for msg in (recent_messages or [])[-8:]:
        if not isinstance(msg, dict) or str(msg.get("role") or "") != "user":
            continue
        content = re.sub(r"\s+", " ", str(msg.get("content") or "")).strip()
        if not content:
            continue
        if not re.search(r"你.{0,10}帮我.{0,18}(?:脱|拿|取|打开|关上|推开|拉开|扶|抱|放|系|解|弄|处理)", content):
            continue
        quote = content[:120]
        lines.append(
            f"- 最近 user 原文「{quote}」解析为：当前角色执行“帮我…”后的动作，当前用户是受益方或接受方。"
            "例如“你帮我脱掉了裤子”必须整理成“当前角色帮当前用户脱掉裤子 / 当前用户的裤子已脱下”；"
            "禁止压缩成“当前用户主动脱裤子”“当前用户帮当前角色脱裤子”或“当前角色的裤子被用户脱掉”。"
            "后续用户再发“请写你的心理活动/继续描写”不会改变这条历史动作主体。"
        )
        break
    for msg in (recent_messages or [])[-8:]:
        if not isinstance(msg, dict) or str(msg.get("role") or "") != "assistant":
            continue
        content = re.sub(r"\s+", " ", str(msg.get("content") or "")).strip()
        if not content:
            continue
        if not re.search(r"你.{0,18}(?:答应|答应过|说过|承诺).{0,36}让我(?:也)?舒服", content):
            continue
        quote = content[:120]
        lines.append(
            f"- 最近 assistant 原文「{quote}」解析为：当前用户承诺/答应让当前角色舒服。"
            "Step 2 的 available_facts/selected_facts 必须写成“用户答应让当前角色舒服”；"
            "forbidden_inferences/forbidden_uses/writing_guidance 必须避免“当前角色承诺/答应/准备/要让用户舒服”。"
            "禁止生成“柔柔的承诺'让你舒服'”“兑现我的承诺”“我答应过，现在该让我照顾你”这类反向材料。"
        )
        break
    for msg in (recent_messages or [])[-8:]:
        if not isinstance(msg, dict) or str(msg.get("role") or "") != "user":
            continue
        content = re.sub(r"\s+", " ", str(msg.get("content") or "")).strip()
        if not content:
            continue
        if not re.search(r"(?:然后|之后|等会|待会|一会儿|接下来|如果|只要|你先).{0,24}我(?:就)?会.{0,24}(?:高潮|顶峰|释放|余韵)", content):
            continue
        quote = content[:120]
        lines.append(
            f"- 最近 user 原文「{quote}」含未来条件/承诺。只能整理成“用户给出继续信号/未来目标”，"
            "不能作为角色可复述台词，不能写成当前角色自己说过这句话，也不能把其中的未来目标整理成已经发生的高潮/顶峰/释放/余韵或事后事实。"
            "若需要进入 selected_facts，只能用中性摘要；forbidden_uses 应提醒 Step 3 不要复述用户旧条件句或把它改成角色台词。"
        )
        break
    return "\n".join(lines) if len(lines) > 1 else ""


def _fact_judgement_current_state_digest(
    *,
    recent_messages: Optional[List[dict]],
    planner_result: Optional[dict],
    scene_candidate: Optional[dict] = None,
) -> str:
    latest_user = _latest_user_actual_text(recent_messages)
    scene_candidate_text, prior_scene_background = _format_fact_judgement_scene_candidate(
        scene_candidate,
        limit=2200,
    )
    plan = planner_result or {}
    state_anchor = plan.get("state_anchor") if isinstance(plan.get("state_anchor"), dict) else {}
    retrieval_keywords = plan.get("retrieval_keywords") if isinstance(plan.get("retrieval_keywords"), dict) else {}
    lines = [
        "【当前状态摘要｜本轮最高优先级】",
        "- 当前用户消息: " + (latest_user[:500] if latest_user else "（无）"),
    ]
    perspective_hint = _dialogue_perspective_hint_block(recent_messages)
    if perspective_hint:
        lines.extend(["", perspective_hint, ""])
    if latest_user:
        lines.append(
            "- 本轮现场护栏: 若当前用户消息已经写出正在发生的动作、物品使用方式、身体状态、看到的画面或递交/触碰/站立关系，"
            "available_facts/current_scene_facts/scene_card 必须先按这句话建立当前事实；上下文记忆、长期记忆、旧场景物品和旧身体装饰只能补充兼容背景。"
            "没有被当前用户消息、最近可见对话或当前场景候选明确延续的旧物品、旧姿势、旧随身物、旧身体装饰，不得写成当前可见、正在晃动、正在持有或此刻发生；"
            "也不得在 current_scene_facts、scene_card 或 writing_guidance 中用未响/未拿着/自然垂下等否定式重新提到，只能放入 history_facts/forbidden_uses。"
        )
        lines.append(
            "- 步骤传输规则: Step 2 的当前场景候选只来自上方结构化 scene_candidate 字段；"
            "下方环境/记忆/检索上下文只是低优先级参考，不得反向覆盖结构化 scene_candidate。"
        )
        lines.append(
            "- 本轮对话代词视角: 当前 user 消息里的“我/我的/我被”指当前用户；user 对当前角色说的“你/你的/你拉着我/你带我/你让我”指当前角色作为施动者或要求对象。"
            "例如用户写“你拉着我到了楼上”时，事实是当前角色拉着当前用户上楼，不能倒写成用户拉着当前角色。"
        )
    lines.append(
        "- 近期 assistant 代词视角: assistant 消息里的“我/我的/让我”指当时发言角色，“你/你的”通常指当前用户/被对话者。"
        "例如角色说“你答应过这次结束就上楼让我也舒服”，事实是用户答应让角色舒服，不能倒写成角色承诺让用户舒服。"
    )
    idle_gap_ms = _normal_scene_idle_gap_ms(recent_messages, None)
    if idle_gap_ms >= _NORMAL_SCENE_IDLE_STALE_GAP_MS:
        hours = round(idle_gap_ms / 3600000, 1)
        lines.append(
            f"- 现实时间间隔信号: 距离上一条用户消息约 {hours:g} 小时；"
            "请根据当前用户原文自行判断是否继承上一场具体物理状态，并输出 continuity_decision。"
        )
    if prior_scene_background:
        lines.append(
            "- 上一轮场景背景: 见下方【上一轮场景背景｜由 continuity_decision 判断是否继承】；它不是自动当前事实。"
        )
    elif scene_candidate_text:
        lines.append(
            "- 当前场景候选/场景锚点: 见下方【当前场景候选｜优先于旧记忆和角色默认住处】。"
        )
    else:
        lines.append("- 当前场景候选/场景锚点: （无结构化候选）")
    if state_anchor:
        lines.append(
            "- Step 1 state_anchor: "
            + json.dumps(state_anchor, ensure_ascii=False)[:900]
        )
    if retrieval_keywords:
        scene_terms = retrieval_keywords.get("scene") if isinstance(retrieval_keywords.get("scene"), list) else []
        memory_terms = retrieval_keywords.get("memory") if isinstance(retrieval_keywords.get("memory"), list) else []
        if scene_terms or memory_terms:
            lines.append(
                "- Step 1 检索意图: scene="
                + "、".join(str(x) for x in scene_terms[:8])
                + "；memory="
                + "、".join(str(x) for x in memory_terms[:8])
            )
    if prior_scene_background:
        lines.append(
            "- 仲裁口径: 先根据现实时间间隔和当前用户原文输出 continuity_decision；只有判断为 continue_scene 时，才把上一轮背景卡里的 location、position/posture、items 继承为当前事实。"
        )
    else:
        lines.append(
            "- 仲裁口径: 当前用户消息没有明确移动/换房间/改变姿势/拿放物品/重置场景时，保持当前场景候选里的 location、position/posture、items；旧记忆和角色稳定卧室/床/房间设定不能覆盖。"
        )
    if prior_scene_background:
        lines.extend(["", "【上一轮场景背景｜由 continuity_decision 判断是否继承】", prior_scene_background])
    if scene_candidate_text:
        lines.extend(["", "【当前场景候选｜优先于旧记忆和角色默认住处】", scene_candidate_text])
    return "\n".join(lines).strip()


def _build_fact_judgement_user_body_profile_block(*, user_species: str = "") -> str:
    species = re.sub(r"\s+", " ", str(user_species or "")).strip()
    if not species:
        return ""
    return (
        "【当前用户体态资料｜高优先级】\n"
        f"- 当前用户种族：{species}\n"
        "- 当当前用户、用户显示名、玩家或用户消息里的“我/我的”成为动作、身体部位、拿取方式或可见身体描写的主体时，"
        "必须按当前用户种族整理事实和边界；不要把当前角色的种族体态、身体部位或能力转移给用户。\n"
        "- 若当前角色与当前用户种族不同，fact_judgement 必须在 subject_boundaries、forbidden_inferences 或 writing_guidance 中保持两者体态分离。"
    )


def _extract_fact_judgement_character_profile_species(character_prompt_context: str) -> str:
    try:
        fields = _extract_character_homepage_profile_fields_for_reply(character_prompt_context)
        species = str(fields.get("种族") or "").strip()
        if species:
            return _clip_line(re.sub(r"\s+", " ", species), 80)
    except Exception:
        pass
    raw = str(character_prompt_context or "")
    for pattern in (
        r"['\"]?profileSpecies['\"]?\s*[:：]\s*['\"]?([^'\"\n\r,，。；;}]+)",
        r"(?:^|\n)\s*[-*]?\s*种族[：:]\s*([^\n，,；;。]+)",
        r"(?:^|\n)\s*[-*]?\s*species[：:]\s*([^\n，,；;。]+)",
    ):
        match = re.search(pattern, raw, re.I)
        if match:
            return _clip_line(re.sub(r"\s+", " ", match.group(1).strip()), 80)
    return ""


def _build_fact_judgement_character_body_profile_block(*, character_prompt_context: str = "") -> str:
    species = _extract_fact_judgement_character_profile_species(character_prompt_context)
    if not species:
        return ""
    lines = [
        "【当前角色体态资料｜Step 2 事实边界专用｜高优先级】",
        f"- 当前角色主页种族：{species}",
        "- 本段只供 Step 2 工具整理事实边界；Step 3 不再接收独立的物种、体态或解剖兜底提示。",
    ]
    if profile_species_has_equine_anatomy(species):
        species_line = equine_species_prompt_line(species)
        if species_line:
            lines.append("- " + species_line)
        lines.append(
            "- 马/小马类四蹄事实：当前角色以及同种马/小马类幼驹、小马驹、小雌驹、小雄驹的默认完整体态是四蹄；"
            "“健康”“全乎”“完整”只能整理为四蹄齐全或身体状态正常。"
            "若最近对话、场景卡、上下文记忆、旧摘要或 Step 1 材料出现“六只蹄子、六蹄、多出一对蹄子、额外蹄肢”等说法，"
            "必须列为 misleading_sources、forbidden_inferences 或 history_facts，不得进入 available_facts、current_scene_facts、scene_card 或 writing_guidance 的可写事实；"
            "writing_guidance 应要求 Step 3 按四蹄体态描写，不要把错误蹄数当作健康状态复述。"
        )
        lines.append(
            "- 马/小马类乳房事实：若本轮需要回答或描写当前角色自己的乳房位置，"
            "按事实解剖学定义为位于胯间、后腿之间，一共两个乳房；"
            "不要写成人类胸前、胸口、胸部或上半身位置，也不要把乳头数量当作乳房数量。"
            "数量硬边界：输出给 Step 3 的 available_facts、current_scene_facts、selected_facts、"
            "writing_guidance 和 forbidden 项都必须保持“一共两个乳房”；"
            "“四个/两对乳房”“没有乳房结构”“不存在乳房”“不适用”都是错误乳房边界，旧记忆或 Step 1 检索词若这样写只能列为误导或禁止项。"
        )
        lines.append(
            "- 马/小马类胸口边界：胸口/胸前/胸部只表示前胸、胸膛或覆盖绒毛的上半身区域；"
            "那里没有乳房/乳头/乳腺区。若用户说“胸口有什么”，可回答胸膛/绒毛等可见体表；"
            "若问乳房或奶头，位置仍是胯间、后腿之间，不能把“胸”和“乳房”混成同一部位。"
            "若用户组合问“胸口有什么，肚子下面有什么”，Step 2 必须同时给两边答案："
            "胸口=胸膛/绒毛/无乳房，肚子下面/后腿之间=乳房或乳腺区所在位置。"
            "若用户问“肚子下方的位置和可爱标记的位置是不是同一个地方”或要求区分胸前、肚子下方、臀部侧面，"
            "Step 2 必须明确输出三点：胸前=胸膛/绒毛/无乳房；肚子下方/胯间/后腿之间=乳房或乳腺区；"
            "臀部侧面=可爱标记位置，左右各一个。"
        )
        lines.append(
            "- 马/小马类涂抹/放置仲裁：若用户要求涂到当前角色自己的乳房/奶头/乳腺区，"
            "而最近动作写实际涂在胯间、后腿之间、下腹靠后或乳腺区，应整理为“已涂在乳房所在位置/胯间后腿之间”，"
            "不能写成“不是乳房”“涂错位置”“与用户要求不同”。"
            "若旧记忆、场景卡或 Step 1 材料写“胸前也可以”“胸前是乳房”“涂在胯间而非乳房”“位置和他说得不一样”，"
            "必须列为 misleading_sources/forbidden_inferences，并要求 Step 3 保持：胸口只有胸膛/绒毛，乳房在胯间后腿之间。"
        )
        lines.append(
            "- 马/小马类肢体术语事实：当前角色自己的手指/指尖功能应写为蹄尖或前蹄；"
            "同一句身体动作里如果已经以蹄子、前蹄或蹄为主体，不得再混入人类指尖、手指或手部末端。"
            "例如“蹄子撑着床单，指尖泛白”这类混用，应在 Step 2 事实边界中整理为蹄尖、蹄缘、前蹄或蹄子等蹄类表述，再交给 Step 3。"
            "重点是不让小马角色把自己的身体末端写成指尖/手指；不需要强制逐字保留原句其他动作或状态。"
        )
    else:
        lines.append(
            "- 若本轮涉及当前角色身体结构、身体部位位置、动作能力或可见身体描写，"
            "按当前角色主页种族和角色设定整理 subject_boundaries / forbidden_inferences / writing_guidance。"
        )
    lines.append(
        "- 若 Step 1 的 expression_policy、proactive_seed 或 literal_reply_text 给出具体身体部位答案，"
        "它仍只是意图/写作计划，不是事实来源；与本段冲突时应列为 misleading_sources 或 forbidden_inferences，"
        "再用本段整理后的事实边界交给 Step 3。"
    )
    return "\n".join(lines).strip()


def format_fact_judgement_for_stage3(fact_judgement: Any) -> str:
    report = _coerce_fact_judgement(fact_judgement)
    lines: list[str] = []
    status = str(report.get("status") or "none")
    if status != "none":
        lines.append(f"状态：{status}")
    for title, key in (
        ("可用事实", "available_facts"),
        ("误导来源", "misleading_sources"),
        ("误会", "misunderstandings"),
        ("禁止推断", "forbidden_inferences"),
        ("主体边界", "subject_boundaries"),
        ("第三方说法边界", "third_party_claims"),
        ("不确定点", "uncertainty_points"),
    ):
        items = report.get(key)
        if isinstance(items, list) and items:
            lines.append(title + "：")
            lines.extend(f"- {str(item).strip()}" for item in items if str(item).strip())
    if report.get("must_ask_user"):
        lines.append("需要用户补充：是")
    guidance = _sanitize_stage3_material_directive(report.get("writing_guidance"), limit=520)
    if guidance:
        lines.append("写作指导：" + guidance)
    description_request = report.get("description_request") if isinstance(report.get("description_request"), dict) else {}
    if description_request.get("enabled"):
        dialogue_allowed = description_request.get("dialogue_allowed")
        lines.append(
            "描写请求："
            + f"target={description_request.get('target') or '未指定'}；"
            + f"intensity={description_request.get('intensity') or 'normal'}；"
            + ("完整括号气泡；" if description_request.get("full_bracket_bubbles") else "")
            + ("dialogue_allowed=false；" if dialogue_allowed is False else "dialogue_allowed=true；")
            + _sanitize_stage3_material_directive(description_request.get("reason"), limit=220)
        )
    action = report.get("current_user_action") if isinstance(report.get("current_user_action"), dict) else {}
    if action.get("enabled"):
        terms = action.get("anchor_terms") if isinstance(action.get("anchor_terms"), list) else []
        term_text = "、".join(str(x).strip() for x in terms if str(x).strip())
        action_guidance = _sanitize_stage3_material_directive(action.get("guidance"), limit=260)
        lines.append(
            "当前用户动作："
            + str(action.get("anchor") or "").strip()
            + (f"；参考词={term_text}" if term_text else "")
            + (f"；{action_guidance}" if action_guidance else "")
        )
    terminal = report.get("terminal_event") if isinstance(report.get("terminal_event"), dict) else {}
    if str(terminal.get("event_type") or "none") != "none":
        lines.append(
            "终局事件："
            + f"type={terminal.get('event_type')}；confidence={terminal.get('confidence') or 'none'}；"
            + str(terminal.get("reason") or "").strip()
        )
    feasibility = report.get("action_feasibility") if isinstance(report.get("action_feasibility"), dict) else {}
    feasibility_bits: list[str] = []
    feasibility_status = str(feasibility.get("status") or "ok").strip()
    if feasibility_status and feasibility_status != "ok":
        feasibility_bits.append(f"status={feasibility_status}")
    current_activity = str(feasibility.get("current_activity") or "").strip()
    if current_activity:
        feasibility_bits.append("当前活动=" + current_activity)
    supported_items = feasibility.get("supported_items") if isinstance(feasibility.get("supported_items"), list) else []
    if supported_items:
        feasibility_bits.append(
            "已证实随身/可用物品=" + "、".join(str(x).strip() for x in supported_items if str(x).strip())
        )
    unsupported_items = (
        feasibility.get("unsupported_current_items")
        if isinstance(feasibility.get("unsupported_current_items"), list)
        else []
    )
    if unsupported_items:
        feasibility_bits.append(
            "无证据当前持有/刚完成=" + "、".join(str(x).strip() for x in unsupported_items if str(x).strip())
        )
    constraints = feasibility.get("constraints") if isinstance(feasibility.get("constraints"), list) else []
    if constraints:
        feasibility_bits.append("可行性约束=" + "；".join(str(x).strip() for x in constraints if str(x).strip()))
    guidance_feas = str(feasibility.get("guidance") or "").strip()
    if guidance_feas:
        feasibility_bits.append("改写指导=" + guidance_feas)
    if feasibility_bits:
        lines.append("行动/物品可行性：" + "；".join(feasibility_bits))
        if unsupported_items or constraints or feasibility_status != "ok":
            lines.append(
                "行动/物品可行性优先级：本段高于 expression_policy、proactive_seed、自我认知倾向和角色风味。"
                "无证据当前持有/刚完成的物品，不得写成已经带着、新烤/新做、昨天多做、早上刚做、还温着或已经放进包里；"
                "只能改成未来计划、回家确认/拿取、路上购买、下次准备或省略。"
            )
    body_profile = report.get("body_profile_anchors") if isinstance(report.get("body_profile_anchors"), dict) else {}
    if body_profile.get("applies_to_current_character"):
        body_bits: list[str] = []
        species = str(body_profile.get("species_value") or "").strip()
        species_source = str(body_profile.get("species_source") or "").strip()
        mammary_position = str(body_profile.get("mammary_position") or "").strip()
        mammary_boundary = str(body_profile.get("mammary_boundary") or "").strip()
        limb_terms = body_profile.get("current_character_limb_terms") if isinstance(body_profile.get("current_character_limb_terms"), list) else []
        forbidden_terms = body_profile.get("forbidden_terms") if isinstance(body_profile.get("forbidden_terms"), list) else []
        body_guidance = str(body_profile.get("guidance") or "").strip()
        if species:
            body_bits.append("主页种族=" + species)
        if species_source:
            body_bits.append("来源=" + species_source)
        if mammary_position:
            body_bits.append("乳房/乳尖位置=" + mammary_position)
        if mammary_boundary:
            body_bits.append("乳房边界=" + mammary_boundary)
        if limb_terms:
            body_bits.append("当前角色身体末端用词=" + "、".join(str(x).strip() for x in limb_terms if str(x).strip()))
        if forbidden_terms:
            body_bits.append("禁用当前角色身体词=" + "、".join(str(x).strip() for x in forbidden_terms if str(x).strip()))
        if body_guidance:
            body_bits.append("指导=" + body_guidance)
        if body_bits:
            lines.append("当前角色体态锚点：" + "；".join(body_bits))
            lines.append(
                "当前角色体态锚点优先级：本段来自 Step 2 对角色主页种族的事实仲裁；"
                "Step 3 必须按这里的正向部位位置和动作末端用词写当前角色本人，"
                "同时保持用户身体仍按用户资料或用户原文主体判断。"
            )
    physical_state = report.get("physical_state") if isinstance(report.get("physical_state"), dict) else {}
    physical_bits: list[str] = []

    def _append_physical_subject(label: str, raw_subject: Any) -> None:
        subject = raw_subject if isinstance(raw_subject, dict) else {}
        subject_bits: list[str] = []
        for key, title in (
            ("intoxication", "醉酒"),
            ("stamina", "体力"),
            ("fatigue", "疲惫"),
            ("injury", "伤势"),
            ("sleep_state", "睡眠/清醒"),
            ("sensory_residue", "感官残留"),
            ("other", "其他"),
        ):
            value = str(subject.get(key) or "").strip()
            if value:
                subject_bits.append(f"{title}={value}")
        scope = str(subject.get("scope") or "").strip()
        evidence = str(subject.get("evidence") or "").strip()
        if scope and scope != "unknown":
            subject_bits.append(f"scope={scope}")
        if evidence:
            subject_bits.append(f"证据={evidence}")
        if subject_bits:
            physical_bits.append(label + "=" + "、".join(subject_bits))

    _append_physical_subject("当前角色", physical_state.get("current_character"))
    _append_physical_subject("用户", physical_state.get("user"))
    stale_states = physical_state.get("stale_states") if isinstance(physical_state.get("stale_states"), list) else []
    if stale_states:
        physical_bits.append("作废/背景状态=" + "；".join(str(x).strip() for x in stale_states if str(x).strip()))
    reset_policy = str(physical_state.get("reset_policy") or "").strip()
    if reset_policy and reset_policy != "unknown":
        physical_bits.append("继承策略=" + reset_policy)
    physical_guidance = str(physical_state.get("guidance") or "").strip()
    if physical_guidance:
        physical_bits.append("指导=" + physical_guidance)
    if physical_bits:
        lines.append("身体状态边界：" + "；".join(physical_bits))
        lines.append(
            "身体状态优先级：只继承 scope=current_scene/same_scene 且有证据的状态；"
            "physical_state.stale_states、forbidden_inferences 或 forbidden_current_items 中的旧醉酒、疲惫、伤势、牙膏味、酒味、咖啡味等不得写成当前身体状态或当前感官残留。"
        )
    boundary_probe = json.dumps(report, ensure_ascii=False, default=str)
    sensory_boundary_needed = bool(physical_bits) or bool(description_request.get("enabled")) or any(
        term in boundary_probe for term in ("牙膏", "薄荷", "酒味", "咖啡", "醉", "体力", "疲惫", "伤势", "感官")
    )
    if sensory_boundary_needed:
        lines.append(
            "身体/感官新增边界：无当前用户消息、最近对话、场景锚点或 physical_state 证据时，"
            "不得新编牙膏/薄荷/酒味/咖啡味、醉意、体力不支、伤势等残留；"
            "清晨刚醒或换场景不能默认已刷牙、洗漱、喝酒、喝咖啡或继承上一场状态。"
        )
    continuity = report.get("continuity_decision") if isinstance(report.get("continuity_decision"), dict) else {}
    continuity_bits: list[str] = []
    try:
        gap = float(continuity.get("idle_gap_hours") or 0)
    except Exception:
        gap = 0.0
    if gap:
        continuity_bits.append(f"现实间隔约 {gap:g} 小时")
    user_intent = str(continuity.get("user_intent") or "").strip()
    prior_treatment = str(continuity.get("prior_scene_treatment") or "").strip()
    reason = str(continuity.get("reason") or "").strip()
    if user_intent and user_intent != "uncertain":
        continuity_bits.append("用户连续性意图=" + user_intent)
    if prior_treatment and prior_treatment != "uncertain":
        continuity_bits.append("旧场景处理=" + prior_treatment)
    if reason:
        continuity_bits.append("理由=" + reason)
    if continuity_bits:
        lines.append("连续性判断：" + "；".join(continuity_bits))
        if user_intent == "background_only_reopen" or prior_treatment == "background_only":
            lines.append(
                "连续性写作边界：上一轮具体地点、姿势、身体接触、手头物品和正在做的动作只作历史背景；"
                "最终正文从角色自己的当下活动起笔，不要把用户写成仍在腿边、怀里、贴着、同一沙发微观姿势或旧物品旁，"
                "也不要主动提旧物品名或写成正在看/刚刚在看/翻旧物品；除非当前用户重新建立了这些距离、姿势或明确要求继续旧场景。"
            )
    if report.get("scene_anchor") or report.get("scene_card"):
        lines.append(
            "场景表达提示：场景位置是连续性核对锚点；最终正文不需要逐字复述微观位置名，"
            "可以自然使用“她的床边/门口那边/还在那个房间里”等说法，但不能串角色、串房间或回到更旧的私聊位置。"
        )
    if not lines:
        return ""
    return "\n".join(lines)[:2200]


_MEMORY_RECALL_QUERY_TYPES = {
    "ordinary",
    "memory_probe",
    "preference_probe",
    "relationship_probe",
    "activity_history",
    "current_scene",
    "group_recall",
    "description_context",
    "uncertain",
}


_MEMORY_RECALL_OUTPUT_BLOCKED_MARKERS = (
    "【上下文记忆】",
    "【当前会话上下文记忆",
    "【被 @ 角色自己的普通聊天上下文记忆】",
    "【记忆指代说明】",
    "【意图识别可参考的跨会话长期记忆】",
    "【导演可参考的跨会话长期记忆】",
    "【当前角色最近临时群聊见闻｜跨会话可用事实】",
    "【近期周记忆】",
    "【近几天的记忆】",
    "【近期月度记忆】",
    "【记忆碎片】",
    "[最近真实对话（原文）]",
    "最近真实对话（原文）",
    "以下是各轮已发生事实",
    "只描述已发生之事",
    "禁止复述",
    "不得凭角色设定",
    "若与最近真实对话",
    "请据此继续对话",
    "response_format",
    "memory_recall JSON",
)

_STAGE2_TOOL_STAGE3_CHAR_LIMIT = 500
_STAGE2_SELF_COGNITION_STAGE3_CHAR_LIMIT = _STAGE2_TOOL_STAGE3_CHAR_LIMIT
_STAGE2_MEMORY_RECALL_STAGE3_CHAR_LIMIT = 1400


def _clip_stage2_material_lines(lines: list[str], *, limit: int) -> str:
    out: list[str] = []
    remaining = max(0, int(limit or 0))
    for raw in lines:
        text = re.sub(r"\s+", " ", str(raw or "").strip())
        if not text or remaining <= 0:
            continue
        addition = text if not out else "\n" + text
        if len(addition) <= remaining:
            out.append(text)
            remaining -= len(addition)
            continue
        newline_len = 1 if out else 0
        allowed = remaining - newline_len
        suffix = "..."
        if allowed >= 24 + len(suffix):
            out.append(text[: allowed - len(suffix)].rstrip("；;,，、 ") + suffix)
        break
    return "\n".join(out)


def _memory_recall_output_looks_like_scaffold(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return True
    if any(marker in raw for marker in _MEMORY_RECALL_OUTPUT_BLOCKED_MARKERS):
        return True
    if re.search(r"\b(user|assistant|system)\s*[:：].+\b(user|assistant|system)\s*[:：]", raw, re.I):
        return True
    if re.search(r"(输出结构|只输出|JSON|字段).{0,20}(selected_facts|memory_recall|query_type)", raw, re.I):
        return True
    return False


def _clean_memory_recall_fact_text(raw: Any, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(raw or "").strip())
    if _memory_recall_output_looks_like_scaffold(text):
        return ""
    return text[:limit]


def _coerce_memory_recall(value: Any) -> dict[str, Any]:
    default = dict(default_planner_result()["memory_recall"])
    if not isinstance(value, dict):
        return default
    if isinstance(value.get("memory_recall"), dict):
        nested = value["memory_recall"]
        top_level_keys = {
            "status",
            "query_type",
            "selected_facts",
            "current_scene_facts",
            "history_facts",
            "preferences",
            "relationship_facts",
            "group_recall_facts",
            "forbidden_uses",
            "writing_guidance",
        }
        material_keys = top_level_keys - {"status", "query_type"}
        if not any(value.get(key) for key in material_keys) and any(nested.get(key) for key in material_keys):
            value = {**value, **nested}
        elif any(nested.get(key) for key in material_keys) and any(value.get(key) for key in {"status", "query_type"}):
            merged = {**nested, **{key: value.get(key) for key in ("status", "query_type") if value.get(key)}}
            value = merged
        if not any(value.get(key) for key in top_level_keys):
            value = nested

    def _clean_text(raw: Any, *, limit: int) -> str:
        return re.sub(r"\s+", " ", str(raw or "").strip())[:limit]

    def _coerce_time_order(raw: Any) -> int | None:
        if raw is None or raw == "":
            return None
        try:
            value = int(raw)
        except Exception:
            return None
        if value <= 0:
            return None
        return min(value, 999)

    def _extract_time_from_text(text: str) -> str:
        match = re.search(
            r"(20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}(?:[日T\s]+(?:\d{1,2}[:：]\d{1,2}(?::\d{1,2})?)?)?)",
            text,
        )
        if match:
            return _clean_text(match.group(1), limit=60)
        match = re.search(r"(20\d{2}年\d{1,2}月\d{1,2}日|20\d{2}年\d{1,2}月|第\d+轮)", text)
        if match:
            return _clean_text(match.group(1), limit=60)
        return ""

    def _clip_items(raw: Any, *, limit: int = 8, item_limit: int = 160) -> list[Any]:
        if isinstance(raw, str):
            raw_items = [raw]
        elif isinstance(raw, list):
            raw_items = raw
        else:
            raw_items = []
        out: list[Any] = []
        seen: set[str] = set()
        for item in raw_items:
            if isinstance(item, dict):
                fact = _clean_memory_recall_fact_text(item.get("fact") or item.get("text"), limit=item_limit)
                if not fact:
                    continue
                occurred_at = _clean_text(
                    item.get("occurred_at")
                    or item.get("timestamp")
                    or item.get("created_at")
                    or item.get("date")
                    or item.get("time"),
                    limit=60,
                ) or _extract_time_from_text(fact)
                time_hint = _clean_text(
                    item.get("time_hint")
                    or item.get("time_context")
                    or item.get("when")
                    or item.get("turn"),
                    limit=80,
                )
                clean = {
                    "fact": fact,
                    "source": _clean_text(item.get("source"), limit=80),
                    "scope": _clean_text(item.get("scope"), limit=40),
                    "confidence": _clean_text(item.get("confidence"), limit=20),
                }
                if occurred_at:
                    clean["occurred_at"] = occurred_at
                if time_hint and time_hint != occurred_at:
                    clean["time_hint"] = time_hint
                time_order = _coerce_time_order(
                    item.get("time_order")
                    if item.get("time_order") is not None
                    else item.get("order")
                    if item.get("order") is not None
                    else item.get("sequence")
                )
                if time_order is not None:
                    clean["time_order"] = time_order
                key = clean["fact"]
                if key in seen:
                    continue
                seen.add(key)
                out.append(clean)
            else:
                text = _clean_memory_recall_fact_text(item, limit=item_limit)
                if not text or text in seen:
                    continue
                seen.add(text)
                out.append(text)
            if len(out) >= limit:
                break
        return out

    status = str(value.get("status") or default["status"]).strip().lower()
    if status not in {"none", "used", "uncertain"}:
        status = "used" if any(value.get(k) for k in ("selected_facts", "preferences", "history_facts")) else "none"
    query_type = str(value.get("query_type") or default["query_type"]).strip().lower()
    if query_type not in _MEMORY_RECALL_QUERY_TYPES:
        query_type = "ordinary"

    return {
        "status": status,
        "query_type": query_type,
        "selected_facts": _clip_items(value.get("selected_facts"), limit=10, item_limit=180),
        "current_scene_facts": _clip_items(value.get("current_scene_facts"), limit=5, item_limit=160),
        "history_facts": _clip_items(value.get("history_facts"), limit=8, item_limit=180),
        "preferences": _clip_items(value.get("preferences"), limit=6, item_limit=160),
        "relationship_facts": _clip_items(value.get("relationship_facts"), limit=6, item_limit=160),
        "group_recall_facts": _clip_items(value.get("group_recall_facts"), limit=5, item_limit=180),
        "forbidden_uses": _clip_items(value.get("forbidden_uses"), limit=6, item_limit=180),
        "writing_guidance": _clean_memory_recall_fact_text(value.get("writing_guidance"), limit=360),
    }


def format_memory_recall_for_stage3(memory_recall: Any) -> str:
    report = _coerce_memory_recall(memory_recall)
    lines: list[str] = []
    rule_lines: list[str] = []
    status = str(report.get("status") or "none")
    query_type = str(report.get("query_type") or "ordinary")
    has_material = status != "none" or any(
        report.get(k)
        for k in (
            "selected_facts",
            "current_scene_facts",
            "history_facts",
            "preferences",
            "relationship_facts",
            "group_recall_facts",
            "forbidden_uses",
            "writing_guidance",
        )
    )
    if not has_material:
        return ""
    lines.append(f"状态：{status}；query_type={query_type}")
    if query_type == "memory_probe":
        rule_lines.append("记忆抽查优先规则：若用户或写作指导指定某个轮次、旧约定、特别词、记忆碎片/日摘/周摘/月摘/年意识层，只回答该目标事实；引号内特别词/暗号/M编号必须原样复制，不改字形。")
    if query_type == "current_scene":
        rule_lines.append("当前现场记忆规则：只按最近可见对话、Step 2 场景锚点和事实边界回答当前装备/食物/物品/地点；长期偏好和旧经历只作背景，不能替换当前精确名称或子类型。")
    if query_type == "description_context":
        rule_lines.append("描写回合记忆规则：当前动作、姿势、身体接触、地点和物品状态以最近可见对话、Step 2 场景锚点和事实边界为准；长期记忆只可作为过去经历/情绪背景，不能改写成当前正在发生。")

    def _time_sort_key(index: int, item: Any) -> tuple[int, tuple[int, ...], int]:
        if not isinstance(item, dict):
            return (3, (), index)
        order = item.get("time_order")
        if isinstance(order, int):
            return (0, (order,), index)
        time_text = str(item.get("occurred_at") or "").strip()
        match = re.search(
            r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})(?:[日T\s]+(\d{1,2})[:：](\d{1,2})(?::(\d{1,2}))?)?",
            time_text,
        )
        if match:
            parts = [int(x) if x is not None else 0 for x in match.groups()]
            return (1, tuple(parts), index)
        turn_match = re.search(r"第(\d+)轮", str(item.get("time_hint") or time_text))
        if turn_match:
            return (2, (int(turn_match.group(1)),), index)
        return (3, (), index)

    def _sorted_memory_items(items: Any) -> list[Any]:
        if not isinstance(items, list):
            return []
        return [
            item
            for _, item in sorted(
                enumerate(items),
                key=lambda pair: _time_sort_key(pair[0], pair[1]),
            )
        ]

    def _item_text(item: Any) -> str:
        if isinstance(item, dict):
            fact = _clean_memory_recall_fact_text(item.get("fact"), limit=180)
            if not fact:
                return ""
            time_parts = [
                str(item.get("occurred_at") or "").strip(),
                str(item.get("time_hint") or "").strip(),
            ]
            time_label = " / ".join(part for i, part in enumerate(time_parts) if part and part not in time_parts[:i])
            meta = "，".join(
                part
                for part in (
                    f"source={item.get('source')}" if item.get("source") else "",
                    f"scope={item.get('scope')}" if item.get("scope") else "",
                    f"confidence={item.get('confidence')}" if item.get("confidence") else "",
                )
                if part
            )
            prefix = f"[{time_label}] " if time_label else ""
            return prefix + fact + (f"（{meta}）" if meta else "")
        return _clean_memory_recall_fact_text(item, limit=180)

    direct_fact_items: list[Any] = []
    history_fact_items: list[Any] = []
    seen_fact_texts: set[str] = set()
    downgraded_background_history = False

    def _is_long_term_memory_item(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        scope = str(item.get("scope") or "").strip().lower()
        source = str(item.get("source") or "").strip()
        return scope == "long_term" or "长期" in source

    def _is_past_timeline_item(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        time_text = " ".join(
            str(item.get(key) or "").strip()
            for key in ("occurred_at", "time_hint")
            if str(item.get(key) or "").strip()
        )
        if not time_text:
            return False
        if re.search(r"(当前|现在|本轮|此刻|正在|刚才|刚刚|最近可见|当前现场|当前场景)", time_text):
            return False
        return bool(
            re.search(
                r"(昨天|前天|以前|之前|过去|早前|上次|上一场|旧|很久前|第\s*\d+\s*轮前|20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2})",
                time_text,
            )
        )

    for key in (
        "selected_facts",
        "current_scene_facts",
        "history_facts",
        "preferences",
        "relationship_facts",
        "group_recall_facts",
    ):
        for item in report.get(key) or []:
            fact_key = str(item.get("fact") if isinstance(item, dict) else item).strip()
            if not fact_key or fact_key in seen_fact_texts:
                continue
            seen_fact_texts.add(fact_key)
            downgrade_long_term = query_type in {"description_context", "current_scene"} and _is_long_term_memory_item(item)
            downgrade_past_context = (
                query_type in {"description_context", "current_scene"}
                and key in {"selected_facts", "preferences", "relationship_facts", "group_recall_facts"}
                and _is_past_timeline_item(item)
            )
            if key == "history_facts" or downgrade_long_term or downgrade_past_context:
                history_fact_items.append(item)
                if key != "history_facts":
                    downgraded_background_history = True
            else:
                direct_fact_items.append(item)
    direct_fact_items = _sorted_memory_items(direct_fact_items)
    history_fact_items = _sorted_memory_items(history_fact_items)
    if direct_fact_items:
        lines.append("可直接使用的记忆事实（按时间顺序）：")
        for item in direct_fact_items:
            text = _item_text(item)
            if text:
                lines.append("- " + text)
    if history_fact_items:
        lines.append("历史背景/过去经历（不得当作当前正在发生的动作、姿势、身体接触、地点或物品状态）：")
        for item in history_fact_items:
            text = _item_text(item)
            if text:
                lines.append("- " + text)

    forbidden_items = _sorted_memory_items(report.get("forbidden_uses"))
    if forbidden_items or downgraded_background_history:
        lines.append("禁止使用：")
        for item in forbidden_items:
            text = _item_text(item)
            if text:
                lines.append("- " + text)
        if downgraded_background_history:
            if query_type == "current_scene":
                lines.append("- 上述旧/低优先级记忆只作为历史背景；当前现场问题只按最近可见对话、场景锚点和事实边界回答，不得覆盖当前装备、食物、物品名称、地点或子类型。")
            else:
                lines.append("- 上述旧/低优先级记忆只作为历史背景；不得把其中的旧动作、旧姿势、旧身体接触、旧地点或旧物品状态写成当前正在发生。当前动作和当前位置以最近可见对话、场景锚点和事实边界为准。")
    guidance = _sanitize_stage3_material_directive(report.get("writing_guidance"), limit=360)
    if guidance:
        lines.append("写作指导：" + guidance)
    lines.extend(rule_lines)
    lines.append("Step 3 只能使用本段已筛选记忆；不要回查、复述或扩写原始长期记忆/群聊原文。")
    return _clip_stage2_material_lines(
        lines,
        limit=_STAGE2_MEMORY_RECALL_STAGE3_CHAR_LIMIT,
    )


def _stage3_setting_anchor_lines(profile: str, *, limit: int = 4) -> list[str]:
    text = str(profile or "")
    match = re.search(r"设定锚点：(.+?)(?:\n本轮倾向：|\n本轮不倾向：|\n本轮优先避免：|\Z)", text, re.S)
    if not match:
        return []
    raw = match.group(1)
    parts = re.split(r"[；;\n]+", raw)
    anchors: list[str] = []
    for part in parts:
        item = re.sub(r"\s+", " ", str(part or "").strip(" -\t\r\n"))
        if item:
            anchors.append(item)
        if len(anchors) >= limit:
            break
    return anchors


def _stage3_should_prioritize_setting_anchors(
    *,
    current_user_text: str,
    planner_result: Optional[dict],
    profile: str,
) -> bool:
    if "设定锚点：" not in str(profile or ""):
        return False
    current_text = re.sub(r"\s+", " ", str(current_user_text or "")).strip()
    if re.search(
        r"(前\s*\d+\s*轮|旧约定|旧计划|抽查旧计划|特别词|记忆碎片|日摘|周摘|月摘|年摘|分层记忆|记忆层|层记忆|留下过一条|以前.{0,12}(?:约定|留下)|之前.{0,12}(?:约定|留下))",
        current_text,
    ):
        return False
    retrieval_terms = _planner_retrieval_keyword_terms(
        planner_result,
        categories=("character_setting",),
        limit=24,
    )
    current_setting_probe = bool(
        re.search(
            r"(那个|那件|那位|那条|这个|这里|对方|谁|哪位|叫什么|什么名字|没有自我介绍|没自我介绍|没有说出口|没说出口|冷门|独特|专属|只属于|隐藏私设|专属设定|私人物件|罕见私人物件|专名|住处|家在哪里|家在哪|房间|床单|家具|摆设|装饰|物件|小物件|地点|店铺|学校|农场|城镇|工作地|常去地点|亲友|同伴|伙伴|助手|宠物|老师|家人|姐姐|妹妹|兄弟|姐妹|父母|母亲|父亲|关系|是谁|哪里|哪儿)",
            current_text,
        )
    )
    if not current_setting_probe:
        return False
    fuzzy_terms = _infer_fuzzy_setting_probe_terms(
        current_user_text,
        " ".join(retrieval_terms),
        str(planner_result or ""),
        limit=18,
    )
    blob = " ".join(
        str(x or "")
        for x in (
            current_user_text,
            " ".join(retrieval_terms),
            " ".join(fuzzy_terms),
        )
    )
    return bool(
        fuzzy_terms
        or re.search(
            r"(亲友|朋友|同伴|伙伴|助手|宠物|老师|家人|姐姐|妹妹|兄弟|姐妹|父母|母亲|父亲|住处|家里|房间|床单|家具|物件|物品|地点|店铺|学校|农场|城镇|工作地|常去|名字|关系|是谁|哪里|哪儿)",
            blob,
        )
    )


def _stage3_strip_lower_priority_entity_guidance(text: str) -> str:
    """Keep lower-priority boundary material from choosing named setting entities."""
    lines = str(text or "").splitlines()
    out: list[str] = []
    skip_bullets = False
    skipped_titles = (
        "可用事实",
        "可用记忆事实",
        "可直接使用的记忆事实",
        "历史背景/过去经历",
        "禁止使用",
        "禁止推断",
        "主体边界",
        "写作指导",
    )
    section_title_re = re.compile(r"^[^\n：:]{1,28}[：:]")
    for raw in lines:
        line = str(raw or "").strip()
        if not line:
            continue
        if any(line.startswith(title) for title in skipped_titles):
            skip_bullets = True
            continue
        if skip_bullets:
            if line.startswith("- "):
                continue
            if section_title_re.match(line):
                skip_bullets = False
            else:
                continue
        out.append(line)
    return "\n".join(out)


def _stage3_focus_setting_anchor_lines(lines: list[str]) -> list[str]:
    priority_markers = (
        "CANARY",
        "隐藏",
        "私设",
        "私有",
        "专属",
        "罕见",
        "专名",
        "只属于",
        "亲近帮手",
        "门边",
        "围巾",
        "记事帮手",
        "八角",
        "小风铃",
    )
    focused = [line for line in lines if any(marker in line for marker in priority_markers)]
    return focused or lines


def _stage3_neutralize_profile_for_setting_query(profile: str) -> str:
    text = str(profile or "")
    if "\n设定锚点：" in text:
        head, rest = text.split("\n设定锚点：", 1)
        rest = "\n设定锚点：" + rest
    else:
        head, rest = text, ""
    parts = re.split(r"(?<=[。；;])", head)
    kept: list[str] = []
    relation_re = re.compile(
        r"(?:有.{0,8})?(助手|伙伴|宠物|哥哥|姐姐|妹妹|兄弟|姐妹|父亲|母亲|朋友|同伴|老师|导师).{0,30}(?:是|为|叫|名|关系|[，,。；;]|$)"
    )
    for part in parts:
        item = str(part or "").strip()
        if not item:
            continue
        if relation_re.search(item):
            continue
        kept.append(item)
    neutral = "".join(kept).strip() or head.strip()
    return (neutral + rest).strip()


def _stage3_profile_with_focused_setting_anchors(profile: str, lines: list[str]) -> str:
    text = str(profile or "").strip()
    if "\n设定锚点：" in text:
        head, _ = text.split("\n设定锚点：", 1)
    else:
        head = text
    neutral_head = _stage3_neutralize_profile_for_setting_query(head)
    if not lines:
        return neutral_head
    return (neutral_head.rstrip() + "\n设定锚点：" + "；".join(lines)).strip()


def _stage3_neutralize_entity_selection_examples(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"[（(][^）)]{1,80}[）)]", "（具体实体以设定锚点为准）", raw)
    raw = re.sub(r"（如[^）]{1,120}）", "（具体实体以设定锚点为准）", raw)
    raw = re.sub(r"如[「『][^」』]{1,80}[」』]", "具体实体以设定锚点为准", raw)
    raw = re.sub(r"如果角色设定中有明确的[^。；]{1,120}?优先使用[^。；]{0,100}[；。]?", "具体实体以设定锚点为准。", raw)
    raw = re.sub(r"优先使用[^。；]{1,100}[；。]?", "具体实体以设定锚点为准。", raw)
    raw = re.sub(r"优先介绍[^。；]{1,100}[；。]?", "具体实体以设定锚点为准。", raw)
    raw = re.sub(r"补充[\u4e00-\u9fffA-Za-z0-9_·]{1,24}的", "补充该对象的", raw)
    raw = re.sub(r"(具体实体以设定锚点为准[。，；;]?\s*){2,}", "具体实体以设定锚点为准。", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _extract_memory_recall_query_type(user_text: str, planner_result: Optional[dict] = None) -> str:
    text = str(user_text or "").strip()
    retrieval_terms = _planner_retrieval_keyword_terms(
        planner_result,
        categories=("memory", "scene"),
    )
    plan_blob = " ".join(
        str((planner_result or {}).get(k) or "")
        for k in ("reply_intent", "memory_use_policy", "expression_policy", "emotion_blend")
    )
    blob = text + " " + plan_blob + " " + " ".join(retrieval_terms)
    if re.search(r"(群聊|刚才.*(看见|看到|听见|听到|聊了什么|发生)|你.*(同意|拒绝).*吗)", blob):
        return "group_recall"
    if re.search(r"(现在在哪|你在哪|当前位置|哪个位置|在什么地方|在哪个房间|我们在哪|在用什么|正在用什么|用什么滑雪|吃着什么|喝着什么|拿着什么|看着什么)", text):
        return "current_scene"
    if re.search(r"(去过哪里|到过哪里|走过哪里|路线|行程|今天.*哪里|之前.*地方)", blob):
        return "activity_history"
    if re.search(r"(喜欢|偏好|爱吃|爱喝|讨厌|害怕|在意|记得.*喜欢)", blob):
        return "preference_probe"
    if re.search(r"(第一次|哪一天|什么时候|几月几号|日期|纪念日).{0,16}(老婆|老公|宝贝|称呼|叫我|喊我|我喊|我叫|表白|求婚)|(?:老婆|老公|宝贝).{0,16}(第一次|哪一天|什么时候|几月几号|日期|纪念日)", blob):
        return "relationship_probe"
    if re.search(r"(关系|恋人|情侣|伴侣|喜欢我|爱我|表白|承诺|我们.*什么)", blob):
        return "relationship_probe"
    if _memory_recall_needs_description_context(text, planner_result):
        return "description_context"
    if re.search(r"(暗号|特别词|关键词|小物件|小东西|冷门小物|旧约定|约定|约好|那件|那个|那条|代表什么|含义|意思|抽查)", blob):
        return "memory_probe"
    if re.search(r"(记得|还记不记得|以前|之前|共同|一起|发生过|经历|说过|做过)", blob):
        return "memory_probe"
    if retrieval_terms:
        if re.search(r"(现在在哪|你在哪|当前位置|哪个位置|在什么地方|在哪个房间|我们在哪|在用什么|正在用什么|用什么滑雪|吃着什么|喝着什么|拿着什么|看着什么)", blob):
            return "current_scene"
        return "memory_probe"
    return "ordinary"


def _memory_recall_needs_description_context(user_text: str, planner_result: Optional[dict]) -> bool:
    plan = planner_result or {}
    fact = plan.get("fact_judgement") if isinstance(plan.get("fact_judgement"), dict) else {}
    desc = fact.get("description_request") if isinstance(fact.get("description_request"), dict) else {}
    if desc.get("enabled"):
        return True
    blob = " ".join(
        str(plan.get(k) or "")
        for k in (
            "reply_intent",
            "memory_use_policy",
            "expression_policy",
            "emotion_blend",
            "character_profile_focus",
        )
    )
    text = str(user_text or "")
    return bool(
        re.search(
            r"(心理活动|内心活动|心里想|怎么想|感受|情绪|身体状态|看到的画面|动作表情|详细写出|只描写|纯描写|描写)",
            text + " " + blob,
        )
    )
