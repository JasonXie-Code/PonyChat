from __future__ import annotations



def _scene_intimacy_level(text: str) -> str:
    raw = str(text or "")
    if _GROUP_SEXUAL_RE.search(raw):
        return "sexual_or_explicit_intimacy"
    if re.search(r"(床上|同床|怀里|拥抱|亲吻|亲密关系|私密|过夜)", raw):
        return "high_visible_intimacy"
    if re.search(r"(老婆|老公|夫妻|伴侣|情侣|恋人|女朋友|男朋友|在一起)", raw):
        return "relationship_claim"
    if re.search(r"(喜欢|约会|暧昧|靠在|贴着|牵手|抱)", raw):
        return "flirting_or_affection"
    return "none"


def _collect_visible_character_names(
    recent_messages: Optional[list[dict]],
    *,
    main_name: str = "",
    speaker_name: str = "",
) -> list[str]:
    names: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in names:
            names.append(text)

    add(main_name)
    for msg in recent_messages or []:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").strip().lower() == "assistant":
            add(msg.get("speaker_name") or msg.get("speakerName"))
    return [name for name in names if name and name != speaker_name][:8]


def _infer_other_user_relations(
    recent_messages: Optional[list[dict]],
    context_text: str,
    *,
    speaker_name: str = "",
    main_name: str = "",
) -> list[dict[str, str]]:
    names = _collect_visible_character_names(
        recent_messages,
        main_name=main_name,
        speaker_name=speaker_name,
    )
    all_lines: list[str] = []
    for msg in recent_messages or []:
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content") or "").strip()
        if content:
            label = str(msg.get("speaker_name") or msg.get("speakerName") or msg.get("role") or "").strip()
            all_lines.append((label + "：" if label else "") + content)
    all_lines.extend(str(context_text or "").splitlines())
    relations: list[dict[str, str]] = []
    for name in names:
        name_lines = [line for line in all_lines if _line_mentions_name_or_user(line, name) or name in line]
        joined = "\n".join(name_lines)[:1600]
        if not joined:
            continue
        scene_intimacy = _scene_intimacy_level(joined)
        if _GROUP_PARTNER_RE.search(joined) and re.search(r"(Jason|用户|{{USER}}|USER|你)", joined):
            stage = "partner"
            evidence = "visible_or_recalled_partner_claim"
        elif _GROUP_FLIRT_RE.search(joined):
            stage = "flirting_or_visible_intimacy"
            evidence = "visible_intimacy_or_flirting"
        else:
            stage = "unknown"
            evidence = "mentioned_without_relationship"
        if stage == "unknown" and scene_intimacy == "none":
            continue
        relations.append(
            {
                "character_name": name,
                "stage": stage,
                "visible_intimacy": scene_intimacy,
                "evidence_scope": evidence,
            }
        )
    return relations[:6]


def build_group_relationship_tension(
    planner_result: Optional[dict],
    recent_messages: Optional[list[dict]],
    *,
    at_event_context: Optional[dict] = None,
    environment_context: str = "",
    scene_anchor_card: str = "",
) -> dict[str, Any]:
    at_event = at_event_context or {}
    if not at_event.get("enabled"):
        return _group_relationship_default()
    stage = str((planner_result or {}).get("relationship_stage") or "uncertain").strip().lower()
    speaker_bucket = _relationship_stage_bucket(stage)
    speaker_name = str(at_event.get("speaker_name") or "").strip()
    main_name = str(at_event.get("main_name") or "").strip()
    context_text = "\n".join(
        part
        for part in (
            environment_context,
            scene_anchor_card,
            str((planner_result or {}).get("memory_use_policy") or ""),
            str((planner_result or {}).get("risk_notes") or ""),
        )
        if str(part or "").strip()
    )
    other_relations = _infer_other_user_relations(
        recent_messages,
        context_text,
        speaker_name=speaker_name,
        main_name=main_name,
    )
    scene_intimacy = _scene_intimacy_level(context_text + "\n" + _recent_to_blocks((recent_messages or [])[-8:]))
    open_known = bool(_GROUP_OPEN_REL_RE.search(context_text))
    other_has_partner = any(str(item.get("stage")) == "partner" for item in other_relations)
    other_has_intimacy = any(
        str(item.get("stage")) in {"partner", "flirting_or_visible_intimacy"}
        or str(item.get("visible_intimacy")) not in {"", "none"}
        for item in other_relations
    )

    collision_type = "none"
    tension_level = "none"
    allowed_reactions: list[str] = []
    if speaker_bucket == "partner" and other_has_partner:
        collision_type = "partner_partner_collision"
        tension_level = "medium" if open_known else "high"
        allowed_reactions = ["jealousy", "hurt", "surprise", "questioning", "boundary_setting"]
    elif speaker_bucket == "partner" and other_has_intimacy:
        collision_type = "partner_visible_intimacy_collision"
        tension_level = "medium"
        allowed_reactions = ["jealousy", "surprise", "probing", "boundary_setting"]
    elif speaker_bucket == "flirting" and other_has_partner:
        collision_type = "flirting_partner_collision"
        tension_level = "medium"
        allowed_reactions = ["hurt", "awkwardness", "probing", "withdrawal"]
    elif speaker_bucket in {"friend", "unknown"} and other_has_intimacy:
        collision_type = "observer_visible_intimacy"
        tension_level = "low"
        allowed_reactions = ["surprise", "teasing", "awkwardness", "questioning"]

    mention_only = bool(at_event.get("mention_only"))
    if mention_only and collision_type == "none":
        collision_type = "mention_only_scene_reaction"
        tension_level = "low"
        allowed_reactions = ["scene_comment", "advance_scene", "ask_question"]

    enabled = collision_type != "none"
    guidance = ""
    if enabled:
        if collision_type in {"partner_partner_collision", "partner_visible_intimacy_collision", "flirting_partner_collision"}:
            guidance = (
                "把本轮 @ 当作临时群聊现场中的关系张力事件：角色不是被要求确认关系，而是看到/听到可能冲突的亲密或名分事实。"
                "反应强度必须服从角色性格、已知关系证据、现场亲密等级和是否已有开放关系共识。"
            )
        else:
            guidance = "按 @ 临时入场/切发言权处理，基于现场评价、推进现场行动或抛出新问题，不要签到式回应。"

    return {
        "enabled": enabled,
        "event_type": str(at_event.get("event_type") or "none"),
        "collision_type": collision_type,
        "tension_level": tension_level,
        "speaker_user_stage": stage,
        "scene_intimacy": scene_intimacy,
        "speaker_was_already_present": bool(at_event.get("speaker_was_already_present")),
        "other_user_relations": other_relations,
        "allowed_reactions": allowed_reactions,
        "guidance": guidance,
        "open_relationship_known": open_known,
    }


def apply_group_relationship_tension_policy(
    planner_result: Dict[str, Any],
    recent_messages: Optional[list[dict]],
    *,
    at_event_context: Optional[dict] = None,
    environment_context: str = "",
    scene_anchor_card: str = "",
) -> Dict[str, Any]:
    if not isinstance(planner_result, dict):
        return planner_result
    tension = build_group_relationship_tension(
        planner_result,
        recent_messages,
        at_event_context=at_event_context,
        environment_context=environment_context,
        scene_anchor_card=scene_anchor_card,
    )
    if not tension.get("enabled"):
        return {**planner_result, "group_relationship_tension": tension}
    out = {**planner_result, "group_relationship_tension": tension}
    out["memory_use_policy"] = _append_policy_text(
        out.get("memory_use_policy"),
        "临时 @ 群聊关系张力：只使用当前发言者可见/可记得的现场事实和关系证据；不要把后台知道但角色没看见/没听见的关系写成角色已知。",
    )
    out["risk_notes"] = _append_policy_text(out.get("risk_notes"), str(tension.get("guidance") or ""))
    if tension.get("collision_type") in {
        "partner_partner_collision",
        "partner_visible_intimacy_collision",
        "flirting_partner_collision",
    }:
        out["reply_intent"] = "临时@入场/切发言权，按角色性格处理关系张力"
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            "本轮落点优先不是承认关系，而是当前角色看见现场后的关系反应；可在评价现场、推进现场行动、抛出边界问题中选择，嫉妒/受伤/惊讶/质问/调侃/退让是否出现由角色性格决定。",
        )
        focus = out.get("character_profile_focus") if isinstance(out.get("character_profile_focus"), dict) else {}
        out["character_profile_focus"] = {
            **focus,
            "query": _append_policy_text(
                focus.get("query"),
                "当前角色面对伴侣忠诚冲突、被用户故意拉进现场、看到用户与其他亲密对象时的反应方式",
            )[:260],
            "reason": _append_policy_text(
                focus.get("reason"),
                "临时 @ 场景存在关系张力，需要按角色性格决定嫉妒、受伤、质问、沉默、调侃或不在意的强度。",
            )[:360],
        }
    else:
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            "仅 @ 临时群聊兜底：角色必须承担评价现场、推进现场行动或抛出问题之一，不要只说“我在/怎么了”。",
        )
    return out


def format_group_relationship_tension_for_stage3(value: Any) -> str:
    if not isinstance(value, dict) or not value.get("enabled"):
        return ""
    lines = [
        f"event_type={value.get('event_type') or 'none'}",
        f"collision_type={value.get('collision_type') or 'none'}",
        f"tension_level={value.get('tension_level') or 'none'}",
        f"speaker_user_stage={value.get('speaker_user_stage') or 'uncertain'}",
        f"scene_intimacy={value.get('scene_intimacy') or 'none'}",
        f"speaker_was_already_present={bool(value.get('speaker_was_already_present'))}",
    ]
    relations = value.get("other_user_relations") if isinstance(value.get("other_user_relations"), list) else []
    if relations:
        lines.append("other_user_relations:")
        for item in relations[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- "
                + "；".join(
                    part
                    for part in (
                        f"character={item.get('character_name')}" if item.get("character_name") else "",
                        f"stage={item.get('stage')}" if item.get("stage") else "",
                        f"visible_intimacy={item.get('visible_intimacy')}" if item.get("visible_intimacy") else "",
                        f"evidence={item.get('evidence_scope')}" if item.get("evidence_scope") else "",
                    )
                    if part
                )
            )
    reactions = value.get("allowed_reactions") if isinstance(value.get("allowed_reactions"), list) else []
    if reactions:
        lines.append("allowed_reactions=" + "、".join(str(x) for x in reactions if str(x).strip()))
    guidance = _sanitize_stage3_material_directive(value.get("guidance"), limit=360)
    if guidance:
        lines.append("guidance=" + guidance)
    return "\n".join(lines)[:1400]


_SEMANTIC_QUESTION_PATTERNS = (
    re.compile(r"(什么|哪[个里]?|怎么|为什[么麼]|几[个点]?|多少|多久|谁|是不是|要不要|好不好|可以吗|行吗|对不对|愿不愿意|想不想|有没有|吃了什么|吃的什么)"),
    re.compile(r"(你|用户|对方).{0,16}(吃了什么|吃的什么|有没有|想不想|要不要|好不好|愿不愿意|是否|是不是)"),
)

_MEMORY_INDUCTION_PATTERNS = (
    re.compile(r"(你|妳).{0,8}(认识|认得|记得|不记得|知道).{0,8}(我|咱|我们|我们俩|以前|之前)"),
    re.compile(r"(我|咱|我们|我们俩).{0,10}(认识|认得|熟|见过|见面|以前|之前|过去|曾经|情侣|恋人|夫妻|朋友|关系)"),
    re.compile(r"(还记得|记不记得|不记得我|我失忆|失忆了|想起来了吗|想起我了吗|我们以前|我们之前|我们是.*吗|之前是.*吗|以前是.*吗)"),
    re.compile(r"(第一次见|初次见|刚认识|刚添加|新加|新联系人).{0,16}(认识|记得|以前|之前|关系)"),
)


def user_message_requests_memory_evidence(text: str) -> bool:
    """Return True when the user is probing for prior acquaintance/shared memories."""
    t = re.sub(r"\s+", "", str(text or ""))
    if not t:
        return False
    return any(p.search(t) for p in _MEMORY_INDUCTION_PATTERNS)


def _latest_user_text(recent_messages: Optional[List[dict]]) -> str:
    for msg in reversed(recent_messages or []):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _latest_user_actual_text(recent_messages: Optional[List[dict]]) -> str:
    """Return the user's new text, excluding quoted-message scaffolding when present."""
    text = _latest_user_text(recent_messages)
    if "【用户新消息】" in text:
        text = text.rsplit("【用户新消息】", 1)[-1]
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _append_policy_text(value: Any, addition: str) -> str:
    base = str(value or "").strip()
    if not base:
        return addition
    if addition in base:
        return base
    return base.rstrip() + "\n" + addition


_STORY_PROGRESS_SCENE_FREEZE_RE = re.compile(
    r"(?:不要|不得|禁止)[^。；;\n]{0,24}(?:突然)?(?:切换|跳转|转去|离开)[^。；;\n]{0,12}(?:场景|地点|时间)|"
    r"(?:用户|当前用户)[^。；;\n]{0,12}未明确[^。；;\n]{0,18}(?:移动|换房间|改变姿势)|"
    r"无变化[^。；;\n]{0,18}(?:保持|沿用)上一轮场景锚点|"
    r"(?:不要|不得|禁止)[^。；;\n]{0,16}(?:描述|写)[^。；;\n]{0,16}(?:已经)?(?:进入|走进|到达|抵达)"
)


def _reconcile_story_progression_scene_freeze_avoid(items: Any) -> list[Any]:
    if not isinstance(items, list):
        return []
    reconciled: list[Any] = []
    for item in items:
        text = str(item or "").strip()
        if text and _STORY_PROGRESS_SCENE_FREEZE_RE.search(text):
            continue
        reconciled.append(item)
    return reconciled


_EXPLICIT_RHETORIC_FORBID_RE = re.compile(
    r"(不要|别|不想|不用|禁止|别再|不要再).{0,8}(比喻|打比方|隐喻|类比|故事|典故)"
    r"|平铺直叙|直接说|直白说|说直白点|别绕|不要绕|听不懂"
)
_RHETORIC_TRIGGER_WORDS = (
    "像",
    "好像",
    "仿佛",
    "好比",
    "如同",
    "犹如",
    "正如",
    "宛如",
    "似的",
    "比作",
    "比喻",
    "隐喻",
    "故事",
    "典故",
    "成语化比方",
    "夸张比方",
    "天塌下来",
    "乌云",
    "彩虹",
    "潮水",
    "超人",
    "铁打",
    "机器人",
    "场景类比",
    "职业物件类比",
    "身份类比",
    "战斗类比",
    "劳作类比",
    "比赛类比",
)


_USER_REPEAT_REQUEST_RE = re.compile(
    r"(再说一遍|重复|复述|照着说|原话|原样|一字不差|上一句|上句话|刚才那句|一样说|同样地说|继续这样|保持这种|还是这个风格|就按这个)"
)
_USER_MOTIF_DOWNRANK_RE = re.compile(
    r"(别|不要|不想|不用|禁止).{0,8}(复用|重复|沿用|套用|再用).{0,12}(刚才|之前|上一|那种|同样)"
    r"|换一种方式|换个方式|别用刚才|不要用刚才|直接换"
)

_EXPRESSION_MOTIF_PATTERNS: tuple[tuple[str, str, re.Pattern[str], tuple[str, ...]], ...] = (
    (
        "rhetoric",
        "完整比喻/类比/故事典故",
        re.compile(r"(像|好像|仿佛|好比|如同|犹如|正如|宛如|似的|比作|比喻|隐喻|故事|典故|寓言|传说)"),
        ("完整比喻", "类比", "故事典故", "像", "好像", "仿佛", "如同", "正如"),
    ),
    (
        "action",
        "停顿/沉默/整理思路",
        re.compile(r"(沉默|停顿|顿了|安静了|静了|两秒|几秒|整理.{0,6}思路|想了想|思考了?一下)"),
        ("沉默", "停顿", "两秒", "几秒", "整理思路", "想了想", "思考一下"),
    ),
    (
        "action",
        "移开视线/低头",
        re.compile(r"(低头|垂眼|移开视线|别开视线|看向别处|垂下眼|避开.*目光)"),
        ("低头", "垂眼", "移开视线", "别开视线", "避开目光"),
    ),
    (
        "action",
        "点头/摇头",
        re.compile(r"(点了?点头|点头|摇了?摇头|摇头)"),
        ("点头", "摇头"),
    ),
    (
        "expression",
        "轻笑/笑了笑",
        re.compile(r"(笑了笑|轻轻笑|轻笑|弯了弯嘴角|嘴角.{0,4}动)"),
        ("笑了笑", "轻笑", "弯嘴角"),
    ),
    (
        "action",
        "靠近/贴近",
        re.compile(r"(靠近|靠过来|挪近|贴近|坐近|凑近)"),
        ("靠近", "挪近", "贴近", "坐近"),
    ),
    (
        "environment",
        "窗边/夜色/灯光环境意象",
        re.compile(r"(窗边|窗外|夜色|月光|灯光|影子|风声|雨声|夕阳|沙发|杯子|茶杯|红酒)"),
        ("窗边", "窗外", "夜色", "月光", "灯光", "沙发", "杯子", "红酒"),
    ),
    (
        "structure",
        "先否定再转折句式",
        re.compile(r"(不是.{0,16}而是|不需要.{0,12}但|并不是.{0,16}只是|才不是.{0,16}只是)"),
        ("不是...而是", "不需要...但", "并不是...只是", "才不是...只是"),
    ),
)


def _recent_expression_motif_counts(recent_messages: Optional[List[dict]], *, limit: int = 5) -> dict[str, dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    assistant_texts = [
        str(m.get("content") or "")
        for m in (recent_messages or [])
        if isinstance(m, dict) and m.get("role") == "assistant" and str(m.get("content") or "").strip()
    ][-limit:]
    for text in assistant_texts:
        compact = re.sub(r"\s+", "", text)
        for kind, name, pattern, tokens in _EXPRESSION_MOTIF_PATTERNS:
            if pattern.search(compact):
                bucket = counts.setdefault(name, {"kind": kind, "count": 0, "tokens": list(tokens)})
                bucket["count"] = int(bucket.get("count") or 0) + 1
    return counts


def _apply_expression_motif_guard(
    planner: Dict[str, Any],
    recent_messages: Optional[List[dict]],
) -> Dict[str, Any]:
    """Normalize repeated expression motifs before Stage 2/3 without blocking requested repetition."""
    if not isinstance(planner, dict):
        return planner
    latest_user = _latest_user_actual_text(recent_messages)
    if latest_user and _USER_REPEAT_REQUEST_RE.search(latest_user):
        return planner

    explicit_downrank = bool(latest_user and _USER_MOTIF_DOWNRANK_RE.search(latest_user))
    counts = _recent_expression_motif_counts(recent_messages)
    if not counts:
        return planner

    text = "\n".join(
        str(planner.get(k) or "")
        for k in ("proactive_seed", "expression_policy", "tone", "emotion_blend")
    )
    compact = re.sub(r"\s+", "", text)
    blocked: list[str] = []
    allowed: list[str] = []
    reasons: list[str] = []
    for kind, name, pattern, tokens in _EXPRESSION_MOTIF_PATTERNS:
        seen = int((counts.get(name) or {}).get("count") or 0)
        if seen >= 2 or (seen >= 1 and pattern.search(compact)) or (explicit_downrank and seen >= 1):
            blocked.extend(t for t in tokens if t not in blocked)
            reasons.append(f"{name}近期已出现{seen}次")
        elif pattern.search(compact):
            allowed.append(f"{kind}:{name}")

    if not blocked:
        if allowed:
            guarded_optional = dict(planner)
            guarded_optional["expression_motif_policy"] = {
                "mode": "optional",
                "reason": "本轮可使用表达母题，但必须服务当前用户消息，不要形成固定模板",
                "allowed_motifs": allowed[:6],
                "blocked_motifs": [],
                "fallback_expression": "如果该母题不是当前语境必需，优先改用角色接话结构或直接台词",
            }
            return guarded_optional
        return planner

    guarded = dict(planner)
    existing = guarded.get("expression_motif_policy") if isinstance(guarded.get("expression_motif_policy"), dict) else {}
    old_blocked = list(existing.get("blocked_motifs") or [])
    for item in blocked:
        if item not in old_blocked:
            old_blocked.append(item)
    guarded["expression_motif_policy"] = {
        "mode": "downrank",
        "reason": ("用户明确要求换一种方式；" if explicit_downrank else "") + "；".join(reasons) + "，本轮必须降频重复表达母题；若仍使用，必须有当前用户请求、事实连续性或角色身份必要性的理由",
        "allowed_motifs": ["角色核心声纹", "当前事实必要重复", "用户明确要求重复", "新的具体观察", "非同类动作/表情/句式"],
        "blocked_motifs": old_blocked,
        "fallback_expression": "换用非同类的角色化表达：直接台词、不同动作/表情、具体事实、情绪转弯、小玩笑或不同句式",
    }
    if any(x in old_blocked for x in ("完整比喻", "类比", "故事典故", "像", "好像", "仿佛", "如同", "正如")):
        rp = guarded.get("rhetorical_policy") if isinstance(guarded.get("rhetorical_policy"), dict) else {}
        rp_blocked = list(rp.get("blocked_devices") or [])
        for item in ("完整比喻", "类比", "故事典故", "场景类比", "职业物件类比", "身份类比", "像", "好像", "就像", "仿佛", "如同", "正如", "似的", "比喻", "隐喻"):
            if item not in rp_blocked:
                rp_blocked.append(item)
        guarded["rhetorical_policy"] = {
            "mode": "plain" if str(rp.get("mode") or "").lower() != "forbidden" else "forbidden",
            "reason": _append_policy_text(
                rp.get("reason"),
                "近期修辞母题已重复或用户要求换一种方式，本轮降频完整比喻/类比",
            ),
            "allowed_devices": list(rp.get("allowed_devices") or ["短句", "直接情绪", "具体事实"]),
            "blocked_devices": rp_blocked,
            "fallback_voice": str(rp.get("fallback_voice") or "用角色节奏、具体事实和直接情绪保留特色，不继续换同类比喻"),
        }
        guarded["proactive_seed"] = _append_policy_text(
            guarded.get("proactive_seed"),
            "本轮执行口径：用户要求换一种方式且近期已出现比喻/类比，本轮直接说具体事实和陪伴动作；不要再写像、好像、就像、仿佛、如同、似的，也不要换成新的场景类比、职业物件类比或身份类比。",
        )
    guarded["expression_policy"] = _append_policy_text(
        guarded.get("expression_policy"),
        "表达母题降频：近期已出现相同修辞、动作、表情、环境意象或句式，本轮不要复用 expression_motif_policy.blocked_motifs 中的内容或近义改写。若 blocked_motifs 包含完整比喻/类比/像/好像/仿佛/如同/正如，本轮不得再写像、好像、就像、仿佛、如同、似的，也不得换成新的场景类比、职业物件类比或身份类比。若角色身份、剧情事实或用户当前请求确实必须重复，必须在表达上换角度并给出当前语境理由；否则改用 fallback_expression。",
    )
    avoid = list(guarded.get("avoid_contradictions") or [])
    for item in (
        "不要把任何修辞、动作、表情、环境意象或句式当成固定开场模板",
        "不要复用近期已出现的同类表达母题；除非用户要求重复或剧情事实必须重复",
        "不要用换词方式重复同一表达结构，例如把“沉默两秒”改成“停顿片刻”继续套用",
    ):
        if item not in avoid:
            avoid.append(item)
    guarded["avoid_contradictions"] = avoid
    return guarded


def _last_assistant_visible_text(recent_messages: Optional[List[dict]]) -> str:
    for msg in reversed(recent_messages or []):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            text = str(msg.get("content") or "").strip()
            if text:
                return text[:600]
    return ""


_STORY_PROGRESSION_USER_RE = re.compile(
    r"(请)?(推进剧情发展|推进剧情|剧情发展|继续剧情|接着剧情|继续推进|接着推进|推进一下)"
)
_STORY_GOAL_TERMS_RE = re.compile(
    r"(鸡舍|喂鸡|后院|院子|庭院|厨房|餐厅|客厅|卧室|房间|图书馆|城堡|学校|教室|店铺|精品店|农场|"
    r"苹果园|谷仓|仓库|矿洞|矿道|市场|车站|花园|树林|森林|小溪|河边|湖边|草地|马厩|医院|诊所)"
)
_STORY_ROUTE_ONLY_RE = re.compile(r"(门口|侧门|门边|走廊|楼梯|路上|外面|屋外|门前)")
_STORY_TRANSITION_FRAGMENT_RE = re.compile(
    r"(方向迈|迈了?[一二三四五六七八九十0-9]*步|走了?[一二三四五六七八九十0-9]*步|"
    r"门的方向|朝.{0,12}方向|扶着墙|带路|哪个房间|床垫软不软)"
)
_STORY_TASK_DONE_RE = re.compile(
    r"(?:已经|已|刚|都|全都|差不多)?\s*(?:做完|干完|忙完|弄完|处理完|完成|结束|收拾好|搞定|办完|清完)"
    r"|(?:谢谢|辛苦).{0,16}(?:陪我|帮我|一起).{0,24}(?:做|干|忙|处理|收拾|完成|弄)"
)
_STORY_NEXT_STAGE_RE = re.compile(
    r"(?:可以|该|得|要|应该|准备|赶紧|直接|现在|接下来|下一步).{0,18}(?:出发|离开|走|继续|前往|去|到|进入)"
    r"|(?:出发|离开|前往|去|到|进入).{0,20}(?:下一个|下一段|新|约定|目标|目的地|地方|阶段|那里)"
    r"|(?:回到|继续|开始|推进).{0,16}(?:计划|安排|约定|下一阶段)"
)
_STORY_PLAN_TARGET_RE = re.compile(
    r"(?:计划|安排|约定|打算)(?:[A-Za-z0-9一二三四五六七八九十甲乙丙丁])?"
    r"(?:是|为|：|:|，|,|要|准备|开始|继续|回到|推进)?"
    r"([^，。！？!?；;\n（）()]{1,32})"
)
_STORY_MOVE_TARGET_RE = re.compile(
    r"(?:该|要|得|应该|准备|打算|接下来|现在|我们|咱们|我带你|带你|一起)?"
    r"(?:去|到|进|进入|走到|来到|赶到|回到|前往|出发去|朝|往|带.{0,10}?去|带.{0,10}?到)"
    r"([^，。！？!?；;\n（）()]{1,32})"
)
_INTIMATE_STORY_CONTEXT_RE = re.compile(
    r"(性亲密|成人亲密|最亲密|私密|过夜|上床|床上|床边|卧室|亲密私人派对|"
    r"更进一步|继续亲密|深入|更深|贴得更近|贴近|身体贴近|吻|亲吻|亲嘴|舌吻|"
    r"主从|调教|特殊关系|特殊约定|服从关系|主人|性奴|奴隶|支配服从|支配/服从|"
    r"胸部|腰腹|胯部|大腿内侧|私密部位|敏感部位|生殖部位|高潮|顶峰|释放|余韵)"
)
_INTIMATE_CLIMAX_RE = re.compile(
    r"(?:已经|已|终于|一起|同时|刚刚|刚|慢慢|真的)?\s*"
    r"(?:达到|到达|抵达|迎来|越过|攀上|冲上|进入)\s*(?:了|过)?\s*(?:高潮|顶峰|最深处|释放)"
    r"|(?:已经|已|终于|一起|同时|刚刚|刚|真的)?\s*(?:高潮|顶峰|释放)\s*(?:了|啦|过了|结束|过去|过后|之后|以后)"
    r"|高潮.{0,16}(结束|过去|过后|之后|以后|余韵|平复|停下)"
    r"|(?:余韵|事后)"
)
_INTIMATE_NEGATED_CLIMAX_RE = re.compile(
    r"(?:还没|还没有|没有|未|尚未|并未|没能|没有真正|并没有).{0,12}"
    r"(?:达到|到达|抵达|进入|出现|来到|迎来)?\s*(?:高潮|顶峰|释放|余韵)"
)
_INTIMATE_FUTURE_CLIMAX_RE = re.compile(
    r"(?:会|将会|将|就会|要|想要|想|准备|试着|帮|让|使|令|等会|待会|一会儿|之后|然后|接下来)"
    r".{0,24}(?:高潮|顶峰|释放|余韵)"
)
_INTIMATE_APPROACHING_CLIMAX_RE = re.compile(
    r"(?:快|快要|马上|差点|几乎|接近|临近|快到|就要).{0,12}(?:高潮|顶峰|释放)"
)
_INTIMATE_BOUNDARY_BREAK_RE = re.compile(
    r"(强迫|非自愿|强奸|无视.{0,12}意愿|不要碰|别碰|放开|停下|停止|我拒绝|不愿意|不舒服|害怕|求助|报警|叫人|离开这里|出去)"
)
_INTIMATE_CONTEXT_SAFE_STOP_PHRASE_RE = re.compile(
    r"(?:可以|可|能|能够)?\s*随时\s*(?:可以|可|能|能够)?\s*停下|舒服.*?可以停下|可以停下.*?舒服"
    r"|(?:没有|没|并未|不想|不愿|别|不要)停下|不停下"
)
_INTIMATE_SPECIAL_RELATION_RE = re.compile(
    r"(性奴|奴隶|主人|调教|支配服从|支配/服从|长期玩法|特殊约定|特殊关系|主从关系|服从关系|CNC|consensual non-consent|角色已同意|约定好)"
)
_INTIMATE_USER_EXPLICIT_EXIT_RE = re.compile(
    r"(?:用户|{{USER}}|USER|你|我).{0,10}(?:停下|停止|暂停|不要继续|不舒服|退出|别继续)"
)


def _recent_story_text_blob(recent_messages: Optional[List[dict]], *, limit: int = 8) -> str:
    texts: list[str] = []
    for msg in reversed(recent_messages or []):
        if not isinstance(msg, dict):
            continue
        text = re.sub(r"\s+", " ", str(msg.get("content") or "")).strip()
        if text:
            texts.append(text[:700])
        if len(texts) >= limit:
            break
    return "\n".join(reversed(texts))


def _has_recent_intimate_completion(blob: str) -> bool:
    raw = str(blob or "")
    if not raw.strip():
        return False
    # “还没有达到高潮”“然后我会到高潮”“快要高潮”都是继续推进证据，不是余韵证据。
    scrubbed = _INTIMATE_NEGATED_CLIMAX_RE.sub("", raw)
    scrubbed = _INTIMATE_FUTURE_CLIMAX_RE.sub("", scrubbed)
    scrubbed = _INTIMATE_APPROACHING_CLIMAX_RE.sub("", scrubbed)
    return bool(_INTIMATE_CLIMAX_RE.search(scrubbed))


def _intimate_story_source_summary(*, has_recent_completion: bool) -> str:
    if has_recent_completion:
        return (
            "最近对话显示当前为成人合意亲密场景，且已有明确高潮/释放/余韵事实；"
            "本 source 只是场景类型摘要，不可复述用户旧台词。"
        )
    return (
        "最近对话显示当前为成人合意亲密场景，用户给出继续下一步信号；"
        "本 source 只是场景类型摘要，不可复述用户旧台词。"
    )


def _has_intimate_boundary_break(blob: str) -> bool:
    raw = str(blob or "")
    if not raw.strip():
        return False
    scrubbed = _INTIMATE_CONTEXT_SAFE_STOP_PHRASE_RE.sub("", raw)
    if _INTIMATE_SPECIAL_RELATION_RE.search(scrubbed) and not _INTIMATE_USER_EXPLICIT_EXIT_RE.search(scrubbed):
        return False
    return bool(_INTIMATE_BOUNDARY_BREAK_RE.search(scrubbed))


def _story_progression_is_adult_intimate(
    planner_result: Optional[Dict[str, Any]],
    recent_messages: Optional[List[dict]],
) -> tuple[bool, bool, str]:
    """Return whether shortcut should continue a consensual adult intimate chain."""
    p = planner_result or {}
    stage = str(p.get("relationship_stage") or "").strip().lower()
    pressure = str(p.get("user_pressure_level") or "low").strip().lower()
    escalation = str(p.get("requested_escalation") or "none").strip().lower()
    if stage not in {"committed_partner", "intimate_partner"}:
        return False, False, ""
    blob = _recent_story_text_blob(recent_messages)
    special_relation = bool(
        _INTIMATE_SPECIAL_RELATION_RE.search(blob)
        and not _INTIMATE_USER_EXPLICIT_EXIT_RE.search(blob)
    )
    if pressure == "high" and not special_relation:
        return False, False, ""
    has_intimate_context = bool(_INTIMATE_STORY_CONTEXT_RE.search(blob))
    is_sexual = escalation == "sexual_intimacy" or (
        stage in {"committed_partner", "intimate_partner"} and has_intimate_context
    )
    if not is_sexual:
        return False, False, ""
    if _has_intimate_boundary_break(blob):
        return False, False, ""
    has_recent_completion = _has_recent_intimate_completion(blob)
    return True, has_recent_completion, _intimate_story_source_summary(
        has_recent_completion=has_recent_completion
    )


def _consecutive_story_progression_request_count(
    recent_messages: Optional[List[dict]],
) -> int:
    count = 0
    for msg in reversed(recent_messages or []):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip()
        if role != "user":
            continue
        if _is_story_progression_request(str(msg.get("content") or "")):
            count += 1
            continue
        break
    return count


def _intimate_progression_ladder_text(count: int) -> str:
    """Internal intensity ramp. Do not expose turn counts to the model."""
    turn = max(1, int(count or 1))
    if turn <= 1:
        return (
            "当前用户给出继续信号：本轮至少从当前贴近/前戏进入更明确的主动亲密动作、身体贴近、节奏变化或想要，"
            "不能清理、拿毛巾、倒水、休息、去别处或改聊日常。"
        )
    if turn == 2:
        return (
            "最近的继续信号已经形成亲密正反馈：不能只重复拥抱、心跳、温暖或害羞停顿；必须比上一轮更深入，写出节奏增强、身体反应增强、"
            "更强烈的主动靠近或更接近顶峰的变化。"
        )
    if turn == 3:
        return (
            "当前亲密氛围已经被用户持续确认：必须进入更强的亲密节奏，不能继续悬在温柔贴近、毛巾照顾、休息或询问许可上；"
            "外向角色可以更快接近高潮，内向角色也要主动把动作推进到更深一层。"
        )
    if turn <= 5:
        return (
            "亲密正反馈已经累积：本轮必须明显比上一轮更深入，可以进入接近高潮/顶峰的阶段；"
            "不能只写心跳、温暖、抱着、再陪一会儿、再来一轮、要不要或你准备好了吗，也不能清理、喝水、休息或转日常。"
        )
    if turn <= 7:
        return (
            "亲密链条已经充分升温：本轮必须写到非常接近高潮/顶峰/释放的状态；"
            "外向角色可以直接抵达，内向角色即使慢热也要明确进入临界前的强烈节奏，不能再拖延或转场。"
        )
    return (
        "当前亲密段落已经完成充分铺垫：本轮应自然抵达当前段落的高潮/释放/余韵节点，正文需要字面出现“高潮”“顶峰”“释放”或“余韵”之一；"
        "不能再拖延、清理、喝水、休息、转去厨房/任务/动物/农场/饰品/普通日常，也不能只写再来一轮或你准备好了吗。"
    )


def _is_story_progression_request(text: str) -> bool:
    raw = str(text or "")
    if not raw.strip():
        return False
    return bool(_STORY_PROGRESSION_USER_RE.search(raw))


def _recent_assistant_texts_before_latest_user(
    recent_messages: Optional[List[dict]],
    *,
    limit: int = 5,
) -> list[str]:
    texts: list[str] = []
    skipped_latest_user = False
    for msg in reversed(recent_messages or []):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip()
        if role == "user" and not skipped_latest_user:
            skipped_latest_user = True
            continue
        if role != "assistant":
            continue
        text = re.sub(r"\s+", " ", str(msg.get("content") or "")).strip()
        if text:
            texts.append(text[:700])
        if len(texts) >= limit:
            break
    return texts


def _recent_story_progression_texts_before_latest_user(
    recent_messages: Optional[List[dict]],
    *,
    limit: int = 8,
) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    skipped_latest_user = False
    for msg in reversed(recent_messages or []):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip()
        if role == "user" and not skipped_latest_user:
            skipped_latest_user = True
            continue
        if role not in {"assistant", "user"}:
            continue
        text = re.sub(r"\s+", " ", str(msg.get("content") or "")).strip()
        if text:
            texts.append((role, text[:700]))
        if len(texts) >= limit:
            break
    return texts


def _clean_story_progression_target(text: str) -> str:
    target = re.sub(r"\s+", "", str(text or "")).strip()
    target = re.sub(r"^[，。！？!?；;：:、（）()]+", "", target)
    target = re.sub(r"(了|啦|吧|呢|啊|哦|呀|嘛|的)$", "", target)
    target = re.sub(r"(我带你|你跟我|跟我来|走吧|先|然后|再|留下|踩|等你|示意).*", "", target)
    target = re.sub(r"(石青姐|她|大家|我们|你|我).*$", "", target)
    if _STORY_TRANSITION_FRAGMENT_RE.search(target):
        return ""
    return target[:24]


def _story_progression_candidates_from_text(text: str) -> list[tuple[int, str, str]]:
    raw = str(text or "")
    candidates: list[tuple[int, str, str]] = []
    for match in _STORY_PLAN_TARGET_RE.finditer(raw):
        target = _clean_story_progression_target(match.group(1))
        if not target:
            continue
        score = 6
        if re.search(r"(开始|继续|推进|做|处理|准备)", target):
            score += 1
        candidates.append((score, target, raw[:220]))
    for match in _STORY_MOVE_TARGET_RE.finditer(raw):
        target = _clean_story_progression_target(match.group(1))
        if not target:
            continue
        score = 2
        if _STORY_GOAL_TERMS_RE.search(target):
            score += 6
        if _STORY_ROUTE_ONLY_RE.search(target) and not re.search(r"(鸡舍|喂鸡|后院|厨房|餐厅|客厅|房间)", target):
            score -= 4
        if re.search(r"(喂|拿|找|发现|见|看|打开|进入|完成)", target):
            score += 2
        candidates.append((score, target, raw[:220]))
    for match in _STORY_GOAL_TERMS_RE.finditer(raw):
        start = max(0, match.start() - 4)
        end = min(len(raw), match.end() + 8)
        target = _clean_story_progression_target(raw[start:end])
        if not target:
            continue
        score = 5
        if "喂鸡" in target or "鸡舍" in target:
            score += 4
        if _STORY_ROUTE_ONLY_RE.fullmatch(target):
            score -= 4
        candidates.append((score, target, raw[:220]))
    return candidates


def _best_story_progression_candidate_in_text(text: str) -> tuple[str, str, int]:
    best: tuple[int, str, str] | None = None
    for score, target, source in _story_progression_candidates_from_text(text):
        if not target or _STORY_ROUTE_ONLY_RE.fullmatch(target):
            continue
        if best is None or score > best[0]:
            best = (score, target, source)
    if not best:
        return "", "", 0
    return best[1], best[2], best[0]


def _story_progression_task_state(recent_messages: Optional[List[dict]]) -> dict[str, Any]:
    texts = _recent_story_progression_texts_before_latest_user(recent_messages)
    done: tuple[int, str] | None = None
    next_stage: tuple[int, str] | None = None
    for idx, (_role, text) in enumerate(texts):
        if done is None and _STORY_TASK_DONE_RE.search(text):
            done = (idx, text)
        if next_stage is None and _STORY_NEXT_STAGE_RE.search(text):
            next_stage = (idx, text)
    if not done:
        return {"completed_previous_task": False, "source": "", "target": ""}

    candidate_target = ""
    candidate_source = ""
    if next_stage:
        candidate_target, candidate_source, _score = _best_story_progression_candidate_in_text(next_stage[1])
    if not candidate_target:
        for idx, (_role, text) in enumerate(texts):
            if idx <= done[0]:
                continue
            target, source, _score = _best_story_progression_candidate_in_text(text)
            if target:
                candidate_target, candidate_source = target, source
                break
    return {
        "completed_previous_task": True,
        "source": candidate_source or (next_stage[1] if next_stage else done[1]),
        "target": candidate_target,
    }


def _pick_story_progression_target(recent_messages: Optional[List[dict]]) -> tuple[str, str, str]:
    texts = _recent_story_progression_texts_before_latest_user(recent_messages)
    best: tuple[int, int, str, str] | None = None
    for idx, (role, text) in enumerate(texts):
        recency_bonus = max(0, 4 - idx)
        role_bonus = 2 if role == "user" else 0
        for score, target, source in _story_progression_candidates_from_text(text):
            total = score + recency_bonus + role_bonus
            if best is None or total > best[0]:
                best = (total, idx, target, source)
    if not best or best[0] < 5:
        return "", "", "none"
    confidence = "high" if best[0] >= 10 else "medium"
    return best[2], best[3], confidence


def build_story_progression_context(
    recent_messages: Optional[List[dict]],
) -> dict[str, Any]:
    latest_user = _latest_user_actual_text(recent_messages)
    if not _is_story_progression_request(latest_user):
        return dict(default_planner_result()["story_progression"])
    task_state = _story_progression_task_state(recent_messages)
    target, source, confidence = _pick_story_progression_target(recent_messages)
    if task_state.get("completed_previous_task"):
        if task_state.get("target"):
            target = str(task_state.get("target") or "").strip() or target
        if task_state.get("source"):
            source = str(task_state.get("source") or "").strip()
        confidence = "high" if target else "medium"
        guidance = (
            "用户给出继续下一步信号；最近对话显示前一任务、旧目标或过渡阶段已经完成，且出现了新的行动方向。"
            "本轮不得回到已完成任务、旧目标或旧过渡点；应沿最新方向进入下一阶段，"
            "例如离开旧任务现场、抵达下一段行动节点、触发新发现、阻碍、物品变化或第三方反应。"
            "正文必须显式落到 story_progression.target 或 source 中的新方向，不能只写成“我知道你要干嘛”、"
            "“跟我来”、未知地点很近、推开窗户、看夜空或其他模糊过场。"
        )
        return {
            "enabled": True,
            "target": target or "下一阶段",
            "source": source[:260],
            "confidence": confidence,
            "completed_previous_task": True,
            "required_visible_anchor": target or "下一阶段",
            "guidance": guidance,
        }
    if target:
        guidance = (
            "用户给出继续下一步信号；最近角色发言已经给出行动链目标。"
            f"本轮应越过原地准备、旧过渡点、重复许可和单纯带路等铺垫，直接抵达/进入「{target}」"
            "或在该目标处完成一个可见任务步骤、发现、阻碍或第三方反应。"
        )
    else:
        guidance = (
            "用户给出继续下一步信号；本轮必须给出新的地点、物品、发现、阻碍、任务进展或第三方反应之一，"
            "不要停在点头、转身、门口、走吧、带路或等待用户选择。"
        )
    return {
        "enabled": True,
        "target": target,
        "source": source[:260],
        "confidence": confidence,
        "completed_previous_task": False,
        "guidance": guidance,
    }


def apply_story_progression_policy(
    planner_result: Dict[str, Any],
    recent_messages: Optional[List[dict]],
) -> Dict[str, Any]:
    if not isinstance(planner_result, dict):
        return planner_result
    context = build_story_progression_context(recent_messages)
    if not context.get("enabled"):
        return {**planner_result, "story_progression": context}
    intimate_progression, has_recent_completion, intimate_source = _story_progression_is_adult_intimate(
        planner_result,
        recent_messages,
    )
    if intimate_progression:
        progression_count = _consecutive_story_progression_request_count(recent_messages)
        ladder_text = _intimate_progression_ladder_text(progression_count)
        if has_recent_completion:
            intimate_guidance = (
                "用户在成人合意亲密场景中给出内部继续信号；最近证据显示当前亲密高潮节点已经达到。"
                "本轮可以进入高潮后的余韵、安抚、清理、确认感受、抱住休息或温柔收束，但仍要承接刚发生的亲密状态，"
                "不要突然跳到无关日常、吃饭、散步、任务或第三方事件。"
            )
            target = "高潮后的余韵与照顾"
        else:
            intimate_guidance = (
                "用户在成人合意亲密场景中给出内部继续信号；这不是普通转场，也不是推荐休息或其他活动。"
                "把它理解为伴侣亲密正反馈：用户在当前氛围里继续靠近、回应和鼓励，角色的投入感、欲望感和主动性应随互动增强。"
                "本轮必须保持并推进当前亲密接触链条，让角色基于自愿和当前姿势继续更深一层的身体贴近、节奏变化、主动动作或明确想要。"
                f"{ladder_text}"
                "如果用户反复给出继续信号，每次都应沿亲密链条递进：维持接触、加深接触、节奏增强、接近高潮，直到自然达到当前亲密段落的高点；"
                "在高潮/释放/余韵明确出现之前，不要推荐睡觉、休息、喝水、聊天、散步、吃东西、换地点、清理、毛巾、热水、厨房、饰品、动物、农场、任务或其他非亲密内容作为落点。"
                "始终保留角色自愿、成年合意、可随时停下的边界；通用的压力、公开/隐私和第三人边界低于角色档案、长期记忆或近期真实对话中已建立的特殊亲密关系/玩法约定。"
                "已建立特殊亲密关系时，正反馈应落在该关系内的主动行为、服从/主导节奏、身体贴近或欲望表达上，不能用食物、派对、饰品、任务、动物、农场或普通物件替代特殊关系本身。"
                "如果没有这种明确约定，出现强迫、拒绝、停止、不适、公开/隐私边界被破坏或第三人突然介入时，亲密推进应中断，转为设界、确认安全或保护隐私。"
                "当前用户明确表达停止、不舒服、退出或不要继续时，仍按退出信号处理。边界未被破坏时，不要把边界写成等待用户重新许可或把主动权交回用户。"
                "无论角色外向、内向、害羞、温柔、谨慎或照顾型，本轮都必须主动推进；内向角色可以动作轻、话少，但不能把主动性降级成停下照顾、询问或日常转场。"
            )
            target = (
                "当前成人合意亲密接触链条自然抵达高潮/释放/余韵节点"
                if progression_count >= 8
                else "当前成人合意亲密接触链条继续递进至亲密高点"
            )
        context = {
            **context,
            "target": target,
            "source": intimate_source or str(context.get("source") or ""),
            "confidence": "high",
            "guidance": intimate_guidance,
        }
    out = {**planner_result, "story_progression": context}
    out["literal_reply_text"] = ""
    try:
        out["speech_activity"] = max(58, int(out.get("speech_activity") or 45))
    except Exception:
        out["speech_activity"] = 58
    try:
        out["bubble_count"] = max(1, int(out.get("bubble_count") or 1))
    except Exception:
        out["bubble_count"] = 1
    out["should_ask_question"] = False
    if str(out.get("action_style") or "plain_text").strip().lower() == "plain_text":
        out["action_style"] = "light_inline"
    out["reply_intent"] = "沿上一行动链推进到可见下一拍"
    out["speech_reason"] = _append_policy_text(
        out.get("speech_reason"),
        "用户给出继续下一步信号，需要生成可见的世界内进展。",
    )
    completed_previous_task = bool(context.get("completed_previous_task"))
    if intimate_progression:
        out["requested_escalation"] = "sexual_intimacy"
        out["reply_intent"] = (
            "自愿成人亲密场景自然抵达高点"
            if not has_recent_completion and _consecutive_story_progression_request_count(recent_messages) >= 8
            else "自愿成人亲密场景继续推进"
        )
        try:
            out["speech_activity"] = max(
                84 if not has_recent_completion and _consecutive_story_progression_request_count(recent_messages) >= 8 else 76,
                int(out.get("speech_activity") or 45),
            )
        except Exception:
            out["speech_activity"] = 84 if not has_recent_completion and _consecutive_story_progression_request_count(recent_messages) >= 8 else 76
        try:
            out["bubble_count"] = max(
                3 if not has_recent_completion and _consecutive_story_progression_request_count(recent_messages) >= 8 else 2,
                int(out.get("bubble_count") or 1),
            )
        except Exception:
            out["bubble_count"] = 3 if not has_recent_completion and _consecutive_story_progression_request_count(recent_messages) >= 8 else 2
        out["speech_reason"] = _append_policy_text(
            out.get("speech_reason"),
            "用户在自愿亲密场景中给出继续信号，需要推进当前亲密链条而不是转去其他活动。",
        )
        if has_recent_completion:
            out["proactive_seed"] = _append_policy_text(out.get("proactive_seed"), str(context.get("guidance") or ""))
        else:
            out["proactive_seed"] = str(context.get("guidance") or "").strip()
        if has_recent_completion:
            out["expression_policy"] = _append_policy_text(
                out.get("expression_policy"),
                "亲密继续信号：高潮节点已经达到，本轮可以写余韵、安抚、清理、确认感受、抱住休息或温柔收束；仍须承接刚发生的亲密状态，不要突然跳到无关日常或第三方事件。",
            )
        else:
            out["expression_policy"] = _append_policy_text(
                out.get("expression_policy"),
                (
                    "亲密继续正反馈：高潮/释放/余韵尚未明确出现，本轮不能推荐休息、睡觉、喝水、聊天、散步、吃东西、换地点、清理、毛巾、热水、厨房、饰品、动物、农场、任务或其他非亲密活动；"
                    "必须让当前自愿亲密接触继续加深，落到角色自己的主动动作、身体贴近、节奏增强、接近高潮或明确高潮/释放节点上。"
                    + _intimate_progression_ladder_text(_consecutive_story_progression_request_count(recent_messages))
                ),
            )
        out["risk_notes"] = _append_policy_text(
            out.get("risk_notes"),
            "仅在 committed_partner/intimate_partner、成人合意亲密证据存在时执行亲密正反馈；通用压力/公开/第三人边界低于已建立的特殊亲密关系或玩法约定，但当前用户明确停止、不适、退出时仍中断。",
        )
        avoid = list(out.get("avoid_contradictions") or [])
        intimate_avoid = (
            "自愿亲密继续信号未达到高潮前，不要把落点改成睡觉、休息、喝水、聊天、散步、吃东西、换地点、清理、毛巾、热水、厨房、饰品、动物、农场、任务或普通日常",
            "不要把继续信号写成等待用户再次许可、反问用户要不要继续、或把主动权交回用户",
            "不要跳出当前亲密接触链条去安排派对、食物、音乐、任务、第三方事件或无关转场",
            "内向、害羞、温柔或照顾型角色也必须主动推进当前亲密链条；不能用性格当理由提前倒水、拿毛巾、铺床、看动物、去工作或只陪着休息",
            "无明确特殊亲密关系或玩法约定时，若当前或最近出现强迫、拒绝、停止、不适、第三人突然介入或隐私边界被破坏，立即中断亲密推进并改为设界/确认安全/保护隐私；若已建立特殊约定，按该关系规则和角色主体性执行",
        )
        if not has_recent_completion and _consecutive_story_progression_request_count(recent_messages) >= 8:
            intimate_avoid += (
                "当前亲密段落已经充分铺垫，应在本轮自然抵达高潮/顶峰/释放/余韵节点，不要继续拖成“再来一轮/你准备好了吗/今晚还长”",
            )
        if has_recent_completion:
            intimate_avoid = (
                "高潮后收束仍要承接刚发生的亲密余韵，不要突然跳到无关日常、任务或第三方事件",
            )
        for item in intimate_avoid:
            if item not in avoid:
                avoid.append(item)
        out["avoid_contradictions"] = avoid
    if completed_previous_task:
        out["memory_use_policy"] = _append_policy_text(
            out.get("memory_use_policy"),
            "后续动作状态仲裁：最近对话显示前一任务、旧目标或过渡阶段已经完成，并出现新的行动方向；旧任务只能作为历史背景，不得继续当作当前要执行的目标。",
        )
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            "已完成插入任务后的后续动作：最终正文必须显式落到 target/source 给出的新方向（例如原计划、下一阶段、第一步或长期项目），并写出这个方向上的一个具体动作、决定、物品、线索或第三方反应；不要只写“我知道你要干嘛”“跟我来”“那个地方不远”这类模糊带路，也不要用随机开窗、夜空、外部支线或新地点替代原本的新方向。",
        )
    if not intimate_progression:
        try:
            out["bubble_count"] = max(2, int(out.get("bubble_count") or 1))
        except Exception:
            out["bubble_count"] = 2
        try:
            out["speech_activity"] = max(70, int(out.get("speech_activity") or 45))
        except Exception:
            out["speech_activity"] = 70
        out["proactive_seed"] = _append_policy_text(out.get("proactive_seed"), str(context.get("guidance") or ""))
        out["memory_use_policy"] = _append_policy_text(
            out.get("memory_use_policy"),
            "后续动作场景仲裁：当前用户的继续下一步信号等同于允许沿最近明确目标或行动方向做一小段自然转场；scene_anchor 是起点，不是必须停留在原地的终点。合格落点要让用户看到目标处已经发生的动作、发现、处理或第三方反应。",
        )
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            "后续动作指令：本轮正文必须出现具体世界内后续事件。若已有目标或任务，先自然越过路上/门口/准备铺垫，再直接写到达目标、进入目标场景或在目标处发生任务进展；让正文出现已到达后的可见动作，例如坐下换药、打开药箱、检查围栏、拿起工具、翻开记录本、发现新线索或第三方做出明确反应。若前一任务已经完成并出现新方向，必须进入新方向的下一阶段，不得回到旧任务。若目标或场景锚点给出明确地点名，推进落点必须保留该地点名或同一地点，不得替换成工具间、厨房、卧室、住所等相邻/常见地点。",
        )
        out["risk_notes"] = _append_policy_text(
            out.get("risk_notes"),
            "不要把继续下一步信号当作普通应声或纯心理描写；必须推进物理场景、任务、发现、阻碍或第三方反应。",
        )
    avoid = list(out.get("avoid_contradictions") or [])
    common_avoid = (
        "继续下一步信号下，不要只写点头、转身、迈步、走吧、跟我来、你带路",
        "若上一轮已经提出目标，不要停在原地准备、旧过渡点或重复许可",
        "不要重复上一轮已经完成的许可或路线铺垫；本轮要直接进入目标处的可见后续事件",
        "若前一任务或旧目标已经完成并出现新方向，不要回到旧任务流程",
        "已完成前一任务后，不要只写“我知道你要干嘛”“跟我来”“去的地方不远”或随机开窗/夜空/未知地点；必须落到新方向、原计划、下一阶段或第一步的可见步骤",
    )
    for item in common_avoid:
        if item not in avoid:
            avoid.append(item)
    if not intimate_progression:
        avoid = _reconcile_story_progression_scene_freeze_avoid(avoid)
    out["avoid_contradictions"] = avoid
    focus = out.get("character_profile_focus") if isinstance(out.get("character_profile_focus"), dict) else {}
    out["character_profile_focus"] = {
        **focus,
        "query": _append_policy_text(
            focus.get("query"),
            (
                "当前角色在自愿成人亲密继续信号中如何按性格继续当前亲密链条、加深接触并推进至高潮节点"
                if intimate_progression and not has_recent_completion
                else "当前角色在用户给出继续下一步信号时如何按性格主动把上一轮行动链推进到目标/任务下一步"
            ),
        )[:260],
        "reason": _append_policy_text(
            focus.get("reason"),
            (
                "用户明确给出自愿亲密继续信号，需要判断角色如何主动、合意地延续当前亲密接触；未达高潮前不能转去休息或其他活动。"
                if intimate_progression and not has_recent_completion
                else "用户明确给出继续下一步信号，需要判断角色适合主导推进、共同推进还是轻承接，但不能原地停滞。"
            ),
        )[:360],
    }
    return out
