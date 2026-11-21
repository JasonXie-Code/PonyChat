

def _apply_model_description_request_policy(planner_result: dict) -> dict:
    fact = planner_result.get("fact_judgement") if isinstance(planner_result.get("fact_judgement"), dict) else {}
    desc = fact.get("description_request") if isinstance(fact.get("description_request"), dict) else {}
    if not desc.get("enabled"):
        return planner_result
    intensity = str(desc.get("intensity") or "normal").strip().lower()
    dialogue_allowed = bool(desc.get("dialogue_allowed", True))
    reason = str(desc.get("reason") or "")
    pure_description = (
        bool(desc.get("full_bracket_bubbles"))
        or not dialogue_allowed
        or _is_pure_description_instruction_text(reason)
    )
    detailed = intensity in {"detailed", "multi_part"} or pure_description
    target_activity = 95 if (pure_description and intensity == "multi_part") else (82 if pure_description and detailed else 65)
    try:
        current_activity = int(planner_result.get("speech_activity") or 0)
    except Exception:
        current_activity = 0
    final_activity = max(current_activity, target_activity)
    target = str(desc.get("target") or "当前状态").strip()
    if not pure_description:
        final_activity = max(current_activity, 72 if intensity in {"detailed", "multi_part"} else 58)
        try:
            existing_count = int(planner_result.get("bubble_count") or 1)
        except Exception:
            existing_count = 1
        existing_count = max(1, existing_count)
        target_count = min(existing_count, 2)
        if intensity == "multi_part":
            target_count = 2
        policy = (
            f"Step 2 已判断本轮有描写焦点，目标={target}，但 dialogue_allowed=true。"
            "这不是纯描写禁言请求；正文可以混合短台词与括号动作/心理/状态。"
            "不要把每个动作、身体反应、心理活动拆成独立纯括号气泡；"
            "不要套用“身体反应-心理活动-嗯/好”的固定三段模板。"
            "至少让一个气泡包含有信息量的角色态度、选择、事实承接或剧情推进。"
        )
        avoid = list(planner_result.get("avoid_contradictions") or [])
        for item in (
            "不要把 Step 2 的普通描写焦点误判成只能输出完整括号描写",
            "不要输出多个纯括号动作/心理后只用“嗯/好/唔”等低信息短音收尾",
            "不要让描写请求覆盖角色本轮应该表达的态度、选择或剧情推进",
        ):
            if item not in avoid:
                avoid.append(item)
        return {
            **planner_result,
            "action_style": "cinematic" if intensity in {"detailed", "multi_part"} else "light_inline",
            "length": "medium" if intensity in {"detailed", "multi_part"} else planner_result.get("length", "medium"),
            "speech_activity": final_activity,
            "bubble_count": target_count,
            "speech_reason": "Step 2 判断用户有描写焦点但允许台词，需要混合描写与角色回应",
            "should_ask_question": False,
            "expression_policy": _append_service_policy_text(planner_result.get("expression_policy"), policy),
            "avoid_contradictions": avoid,
        }
    policy = (
        f"Step 2 已判断本轮是合法描写/写法请求，目标={target}。"
        "本轮必须按用户要求输出当前心理、身体、环境、画面、动作或感受描写，禁止写成普通聊天台词；"
        "使用 2-4 个非空气泡，每个气泡独立完整闭合为全角括号（……），每个气泡只承载一个镜头或状态层次。"
        "单个气泡宜 60-140 个字符，复杂镜头最多约 180 个字符；如果超过这个长度，必须拆成下一个气泡。"
    )
    avoid = list(planner_result.get("avoid_contradictions") or [])
    for item in (
        "不要把 Step 2 已确认的描写/写法请求当成普通寒暄或反问用户",
        "不要把多层描写合并成一个超长气泡",
        "不要输出任何未包在全角括号里的非空描写段落",
    ):
        if item not in avoid:
            avoid.append(item)
    return {
        **planner_result,
        "action_style": "cinematic",
        "length": "long" if detailed else planner_result.get("length", "medium"),
        "speech_activity": final_activity,
        "bubble_count": _description_instruction_bubble_count_from_activity(final_activity),
        "speech_reason": "Step 2 判断用户当前明确要求描写/写法输出，需要多段完整括号气泡",
        "should_ask_question": False,
        "expression_policy": _append_service_policy_text(planner_result.get("expression_policy"), policy),
        "avoid_contradictions": avoid,
    }


def _fact_judgement_has_terminal_death(planner_result: dict) -> bool:
    fact = planner_result.get("fact_judgement") if isinstance(planner_result.get("fact_judgement"), dict) else {}
    event = fact.get("terminal_event") if isinstance(fact.get("terminal_event"), dict) else {}
    event_type = str(event.get("event_type") or "none").strip().lower()
    confidence = str(event.get("confidence") or "none").strip().lower()
    return event_type in {"current_character_death", "current_character_fatal_wound"} and confidence == "high"


def _apply_model_relationship_evidence_policy(planner_result: dict) -> dict:
    stage = str(planner_result.get("relationship_stage") or "").strip().lower()
    if stage not in {"committed_partner", "intimate_partner"}:
        return planner_result
    fact = planner_result.get("fact_judgement") if isinstance(planner_result.get("fact_judgement"), dict) else {}
    evidence = fact.get("relationship_evidence") if isinstance(fact.get("relationship_evidence"), dict) else {}
    status = str(evidence.get("status") or "unknown").strip().lower()
    if status in {"unknown", "confirmed_current_partner"}:
        return planner_result
    out = dict(planner_result)
    out["relationship_stage"] = "flirting"
    if str(out.get("requested_escalation") or "").strip().lower() in {"sexual_intimacy", "long_term_commitment"}:
        out["requested_escalation"] = "physical_intimacy"
    out["risk_notes"] = _append_service_policy_text(
        out.get("risk_notes"),
        "Step 2 关系证据判断：未确认当前角色与用户是稳定伴侣；暧昧、独处、进房间、喜欢贴近或第三方关系不能升级成当前角色伴侣关系。",
    )
    out["memory_use_policy"] = _append_service_policy_text(
        out.get("memory_use_policy"),
        "若记忆中出现其他角色与用户的恋爱关系，必须保留角色名字，不得转写成当前角色与用户的关系。",
    )
    out["expression_policy"] = _append_service_policy_text(
        out.get("expression_policy"),
        "按 flirting 关系承接：可以半推半就、犹豫后靠近或确认意图，但不要写成已经是伴侣、不要使用伴侣名分作为依据。",
    )
    return out


def _apply_terminal_death_reply_policy(planner_result: dict) -> dict:
    return {
        **planner_result,
        "web_search": False,
        "search_query": None,
        "vision_web": False,
        "use_prior_image_context": False,
        "reply_intent": "临终反应",
        "tone": "符合角色的临终遗言或最后反应，不继续正常对话",
        "length": "short",
        "bubble_count": 1,
        "action_style": "light_inline",
        "initiative_level": 0,
        "speech_activity": max(45, int(planner_result.get("speech_activity") or 45)),
        "speech_reason": "Step 2 判断用户本轮造成明确致命结果；角色死亡前只允许最后一句遗言或临终反应",
        "should_ask_question": False,
        "voice_reply": {"enabled": False, "reason": "临终回复固定文本，避免语音后续任务"},
        "asset_plan": {
            **(planner_result.get("asset_plan") or {}),
            "enabled": False,
            "count": 0,
        },
        "reply_sequence": [{"type": "text", "intent": "terminal_death_reply"}],
        "risk_notes": _append_service_policy_text(
            planner_result.get("risk_notes"),
            "Step 2 判断本轮用户造成百分百明确的致命伤或直接杀死当前角色；这是角色死亡前最后一次可见回应。",
        ),
        "memory_use_policy": _append_service_policy_text(
            planner_result.get("memory_use_policy"),
            "本轮为当前对话的角色死亡节点；保存这次临终回应后，本对话角色状态应变为 dead。",
        ),
        "expression_policy": _append_service_policy_text(
            planner_result.get("expression_policy"),
            "终局死亡回复：承认用户造成的致命结果，只写角色死亡前最后一句遗言、最后反应或短动作；不要继续威胁、提问、安排下一步、求用户解释或正常聊天。普通重伤不适用本规则。",
        ),
        "proactive_seed": _append_service_policy_text(
            planner_result.get("proactive_seed"),
            "角色在死亡前发出最后一句符合性格的遗言或临终反应；正文只有一个短气泡，随后对话进入无回复状态。",
        ),
        "avoid_contradictions": list(planner_result.get("avoid_contradictions") or [])
        + [
            "不要写成角色只是普通受伤后继续战斗",
            "不要写成角色死亡后还能继续正常聊天",
            "不要让用户宣称复活在本轮生效",
        ],
    }


def _apply_dead_spirit_reply_policy(planner_result: dict) -> dict:
    return {
        **planner_result,
        "web_search": False,
        "search_query": None,
        "vision_web": False,
        "use_prior_image_context": False,
        "reply_intent": "死亡后被 @ 召回的一次灵魂残响",
        "tone": "幽灵般、克制、第三者视角；括号内写灵魂/残响显形，括号外只留一句死后残留口吻的短台词",
        "length": "short",
        "bubble_count": 1,
        "action_style": "light_inline",
        "initiative_level": 0,
        "speech_activity": max(45, _normal_planner_int(planner_result.get("speech_activity"), 45)),
        "speech_reason": "当前角色已死亡，但用户本轮明确 @ 主角色；允许以灵魂视角回应一次。",
        "voice_reply": {"enabled": False, "reason": "死亡后灵魂/残响回复需要固定文本格式，避免语音步骤绕过 Step 3 文本守门。"},
        "should_ask_question": False,
        "asset_plan": {
            **(planner_result.get("asset_plan") or {}),
            "enabled": False,
            "count": 0,
        },
        "reply_sequence": [{"type": "text", "intent": "dead_spirit_reply"}],
        "risk_notes": _append_service_policy_text(
            planner_result.get("risk_notes"),
            "当前对话角色生命周期状态已是 dead；本轮 @ 主角色只允许灵魂/残响发言，不代表复活，也不清除死亡状态。",
        ),
        "memory_use_policy": _append_service_policy_text(
            planner_result.get("memory_use_policy"),
            "保持角色已死亡这一事实；用户本轮 @ 主角色时，只允许一次死后灵魂/残响式短回应，不能复活或恢复普通聊天。",
        ),
        "expression_policy": _append_service_policy_text(
            planner_result.get("expression_policy"),
            "死亡后 @ 主角色回复必须一次写成固定形态：「（角色名的灵魂/残响从死亡位置、远处或阴影里渗出/浮起/凝在半空）一句短台词」。括号内必须是第三者角度的灵魂显形描写；括号外只写角色死后残留口吻的直接短台词。保持 dead 状态和灵魂残响性质，不恢复行动、日常互动或当前物理场景参与。",
        ),
        "proactive_seed": _append_service_policy_text(
            planner_result.get("proactive_seed"),
            "按示例方向一次写对：「（某某的灵魂从原处缓缓渗出，像一团冰凉的雾气，残响凝在半空）你喊得再大声，也搬不走已经发生的事。」正文短而明确。",
        ),
        "avoid_contradictions": list(planner_result.get("avoid_contradictions") or [])
        + [
            "不要写成角色已经复活",
            "不要清除或否认当前角色已死亡",
            "不要用普通生者第一人称继续日常聊天",
            "不要安排下一步现实行动或主动任务",
            "不要把灵魂显形描写放在括号外",
        ],
    }


async def _load_cloud_user_settings(username: Optional[str]) -> dict:
    username = (username or "").strip()
    if not username:
        return {}
    try:
        db = get_database()
        await db.init()
        settings = await SettingsDAO(db).load_settings(username)
        return settings if isinstance(settings, dict) else {}
    except Exception as e:
        logger.debug("加载用户云设置失败(%s): %s", username, e)
        return {}


def _coerce_float(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _coerce_int(value) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _coerce_reasoning(value) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text if text in ("minimal", "low", "medium", "high", "max") else None


_LOCAL_SEARCH_RE = re.compile(
    r"(天气|下雨|降雨|雨势|雨量|气温|温度|冷不冷|热不热|穿什么|空气质量|AQI|PM2\.?5|雾霾|"
    r"限行|路况|堵车|附近|周边|本地|当地|同城|营业|开门|关门|餐厅|医院|药店|超市|商场|"
    r"电影院|电影场次|公交|地铁)",
    re.IGNORECASE,
)
_EXPLICIT_LOCATION_RE = re.compile(
    r"(北京|上海|天津|重庆|广州|深圳|杭州|成都|武汉|南京|苏州|西安|长沙|郑州|青岛|济南|厦门|"
    r"福州|沈阳|大连|哈尔滨|长春|昆明|贵阳|南宁|海口|三亚|乌鲁木齐|拉萨|银川|兰州|"
    r"西宁|呼和浩特|太原|石家庄|合肥|南昌|宁波|无锡|佛山|东莞|珠海|香港|澳门|台湾|"
    r"中国|全国|[\u4e00-\u9fff]{2,}(?:省|市|区|县|州|盟|旗|镇|乡))"
)


def _compact_text(value: str) -> str:
    return re.sub(r"[\s,，。；;:：/\\|·\-—_]+", "", value or "")


def _location_aliases(location_name: str) -> set[str]:
    loc = _compact_text(location_name)
    if not loc:
        return set()

    aliases = {loc}
    for prefix in ("中国", "中华人民共和国"):
        if loc.startswith(prefix):
            aliases.add(loc[len(prefix):])

    for suffix in ("省", "市", "区", "县", "州", "盟", "旗", "镇", "乡"):
        idx = loc.find(suffix)
        if idx > 0:
            aliases.add(loc[: idx + 1])
            aliases.add(loc[:idx])

    for alias in list(aliases):
        aliases.add(re.sub(r"(特别行政区|自治区|自治州|自治县|省|市|区|县|州|盟|旗|镇|乡)$", "", alias))

    return {a for a in aliases if len(a) >= 2}


def _query_mentions_location(query: str, location_name: str) -> bool:
    q = _compact_text(query)
    if not q:
        return False
    return any(alias and alias in q for alias in _location_aliases(location_name))


def _localize_search_query(search_query: str, client_context: Any) -> str:
    q = (search_query or "").strip()
    if not q:
        return q

    location_name = str(getattr(client_context, "location_name", "") or "").strip()
    if not location_name:
        return q
    if _query_mentions_location(q, location_name):
        return q
    if not _LOCAL_SEARCH_RE.search(q):
        return q
    if _EXPLICIT_LOCATION_RE.search(_compact_text(q)):
        return q

    return f"{location_name} {q}"


def _apply_cloud_and_request_settings(
    *,
    params: dict,
    request: ChatRequest,
    active_model: dict,
    user_settings: dict,
) -> tuple[dict, dict]:
    merged_model = dict(active_model or {})

    # 游戏/锁分模式：所有用户自定义参数（温度/上限/推理深度/模型大厅覆写）均不生效，
    # 由后续步骤统一固定（基础 temperature=0.3, max_tokens=16k, 禁止思考）
    if request.mode in ("galgame", "galgame_lock"):
        params["web_search"] = False
        return params, merged_model

    model_id = str(merged_model.get("id") or "")
    model_overrides = user_settings.get("model_overrides") if isinstance(user_settings.get("model_overrides"), dict) else {}
    model_override = model_overrides.get(model_id) if isinstance(model_overrides.get(model_id), dict) else {}

    global_temp = _coerce_float(user_settings.get("temp"))
    req_temp = _coerce_float(request.temperature)
    if req_temp is not None:
        params["temperature"] = req_temp
    elif global_temp is not None:
        params["temperature"] = req_temp if req_temp is not None else global_temp

    global_max_tokens = _coerce_int(user_settings.get("n_predict"))
    req_max_tokens = _coerce_int(request.n_predict)
    if req_max_tokens is not None:
        params["max_completion_tokens"] = req_max_tokens
    elif global_max_tokens is not None:
        params["max_completion_tokens"] = global_max_tokens

    global_reasoning = _coerce_reasoning(user_settings.get("reasoning_effort"))
    req_reasoning = _coerce_reasoning(request.reasoning_effort)
    if req_reasoning:
        params["reasoning_effort"] = req_reasoning
    elif global_reasoning:
        params["reasoning_effort"] = global_reasoning

    override_temp = _coerce_float(model_override.get("temperature"))
    if override_temp is not None:
        params["temperature"] = override_temp

    override_max_tokens = _coerce_int(model_override.get("max_tokens"))
    if override_max_tokens is not None:
        params["max_completion_tokens"] = override_max_tokens

    override_reasoning = _coerce_reasoning(model_override.get("reasoning_effort"))
    if override_reasoning:
        params["reasoning_effort"] = override_reasoning

    override_thinking_budget = str(model_override.get("thinking_budget") or "").strip().lower()
    if override_thinking_budget in ("auto", "low", "medium", "high"):
        params["thinking_budget"] = override_thinking_budget

    if "enable_thinking" in model_override:
        merged_model["enable_thinking"] = bool(model_override.get("enable_thinking"))

    # 请求级别的思考开关（Web 端固定传 false）优先级高于模型大厅配置
    if request.enable_thinking is not None:
        merged_model["enable_thinking"] = request.enable_thinking

    if "web_search" in model_override:
        params["web_search"] = bool(model_override.get("web_search"))

    return params, merged_model
