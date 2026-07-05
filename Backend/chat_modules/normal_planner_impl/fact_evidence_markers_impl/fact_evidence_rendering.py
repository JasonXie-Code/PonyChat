

_FUZZY_MEMORY_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "小东西": ("小东西", "小物件", "小物", "物件", "物品"),
    "小物件": ("小物件", "小东西", "小物", "物件", "物品"),
    "冷门小物": ("冷门小物", "冷门物件", "小物件", "小东西", "物件"),
    "特别词": ("特别词", "暗号", "关键词", "专名", "名字"),
    "暗号": ("暗号", "特别词", "关键词", "约定词"),
    "约好": ("约好", "约定", "说好", "定下"),
    "约定": ("约定", "约好", "说好", "定下"),
    "代表": ("代表", "含义", "意思", "象征"),
    "含义": ("含义", "意思", "代表", "象征"),
    "意思": ("意思", "含义", "代表", "象征"),
    "计划": ("计划", "安排", "后续", "要做的事"),
}


def _infer_fuzzy_memory_probe_terms(*texts: Any, limit: int = 24) -> list[str]:
    blob = re.sub(r"\s+", " ", " ".join(str(x or "") for x in texts)).strip()
    if not blob:
        return []
    if not re.search(
        r"(那个|那件|那条|旧|以前|之前|很久|暗号|特别词|关键词|小物件|小东西|小物|冷门|独特|约定|约好|代表|含义|意思|计划|抽查|记得)",
        blob,
    ):
        return []
    terms: list[str] = []

    def add(term: str) -> None:
        if term and term not in terms:
            terms.append(term)

    for term, variants in _FUZZY_MEMORY_EQUIVALENTS.items():
        if term in blob or any(variant in blob for variant in variants):
            for variant in variants:
                add(variant)
    if re.search(r"(那个|那件|那条|旧|以前|之前|很久|抽查|记得)", blob):
        for term in ("约定", "以前", "之前", "小物件", "特别词", "代表", "计划"):
            add(term)
    return terms[:limit]


def _memory_term_matches_fact(text: str, term: str) -> bool:
    if not term:
        return False
    if term in text:
        return True
    for key, variants in _FUZZY_MEMORY_EQUIVALENTS.items():
        if term == key or term in variants:
            return any(variant in text for variant in variants)
    return False


_MEMORY_RECALL_SCAFFOLD_PREFIXES = (
    "以下是各轮已发生事实",
    "这些是角色大脑里的长期记忆",
    "只可作为背景",
    "除非最近可见对话",
    "若与最近真实对话",
    "请据此继续对话",
    "禁止复述",
    "用户偏好、用户曾经说过",
    "角色做的事不得改写",
    "【记忆指代说明】",
    "以下内容是当前角色自己被 @ 拉进其他角色主聊天",
)


def _memory_recall_is_scaffold_line(text: str) -> bool:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    if not raw:
        return True
    if raw.startswith("【") or raw.endswith("】"):
        return True
    if any(raw.startswith(prefix) for prefix in _MEMORY_RECALL_SCAFFOLD_PREFIXES):
        return True
    if raw.startswith("[") and not re.match(r"\[(?:最近|20\d{2}(?:[-年/.]\d{1,2})?|20\d{2}-W\d{1,2})", raw):
        return True
    if re.fullmatch(r"[-—─\s]*(?:昨天|今天|前天|近期|短期|长期).{0,24}[-—─\s]*", raw):
        return True
    if re.search(r"(不得|禁止|不能|只可|必须以|不得由|不得把|只能表达不确定|不得凭).{0,80}(复述|编造|升级|推导|覆盖|改写)", raw):
        return True
    if re.search(r"(Step\s*[1234]|输出结构|response_format|memory_recall JSON)", raw, re.I):
        return True
    return False


def _memory_recall_item_from_fallback_line(
    line: str,
    *,
    scope: str,
    order: int,
) -> dict[str, Any] | None:
    text = re.sub(r"\s+", " ", str(line or "").strip(" -·\t"))
    if not text or len(text) < 8 or _memory_recall_is_scaffold_line(text):
        return None
    occurred_at = ""
    time_hint = ""

    match = re.match(
        r"第(\d+)轮[，,]\s*(20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}(?:[日T\s]+\d{1,2}[:：]\d{1,2}(?::\d{1,2})?)?)[:：]\s*(.+)",
        text,
    )
    if match:
        time_hint = f"第{match.group(1)}轮"
        occurred_at = match.group(2)
        text = match.group(3).strip()
    else:
        match = re.match(
            r"\[(20\d{2}(?:[-年/.]\d{1,2}(?:[-月/.]\d{1,2})?)?|20\d{2}-W\d{1,2})\](?:\[[^\]]{1,18}\])?\s*(.+)",
            text,
        )
        if match:
            occurred_at = match.group(1)
            text = match.group(2).strip()
        else:
            match = re.match(
                r"(20\d{2}年\d{1,2}月\d{1,2}日(?:[早晚凌晨上午下午中午夜里深夜]{0,4})?)[，,：:\s]*(.+)",
                text,
            )
            if match:
                occurred_at = match.group(1)
                text = match.group(2).strip()

    text = re.sub(r"^\[[^\]]+\]\s*", "", text).strip()
    if len(text) < 8 or _memory_recall_is_scaffold_line(text):
        return None
    if text.count("{{") != text.count("}}"):
        text = text.replace("{{USER", "{{USER}}")
    return {
        "fact": text[:160],
        "source": scope,
        "scope": scope,
        "confidence": "medium",
        **({"occurred_at": occurred_at[:60]} if occurred_at else {}),
        **({"time_hint": time_hint} if time_hint else {}),
        "time_order": order,
    }


def _fallback_memory_recall_report(
    *,
    recent_messages: Optional[list[dict]] = None,
    planner_result: Optional[dict] = None,
    context_memory: str = "",
    long_memory: str = "",
    guest_group_memory: str = "",
    current_user_text: str = "",
) -> dict[str, Any]:
    query_type = _extract_memory_recall_query_type(current_user_text, planner_result)
    default = dict(default_planner_result()["memory_recall"])
    retrieval_terms = _planner_retrieval_keyword_terms(
        planner_result,
        categories=("memory", "scene"),
        limit=16,
    )
    if (
        query_type == "ordinary"
        and not retrieval_terms
        and not re.search(r"(记忆|记得|喜欢|关系|去过|群聊)", str(planner_result or {}))
    ):
        return default

    plan_blob = " ".join(
        str((planner_result or {}).get(k) or "")
        for k in (
            "reply_intent",
            "memory_use_policy",
            "expression_policy",
            "emotion_blend",
            "state_anchor",
        )
    )
    raw_terms = re.findall(
        r"[\u4e00-\u9fff]{2,8}",
        (current_user_text or "") + " " + plan_blob + " " + " ".join(retrieval_terms),
    )
    fuzzy_terms = _infer_fuzzy_memory_probe_terms(
        current_user_text,
        plan_blob,
        " ".join(retrieval_terms),
    )
    stop_terms = {
        "现在",
        "哪里",
        "什么",
        "我们",
        "你们",
        "是不是",
        "详细写出",
        "当前你的",
        "心理活动",
        "内心活动",
        "身体状态",
        "描写",
        "角色",
        "用户",
        "整体语气",
        "本轮",
        "当前",
    }
    terms = [t for t in raw_terms if t not in stop_terms]
    if retrieval_terms or fuzzy_terms:
        terms = list(dict.fromkeys([*retrieval_terms, *fuzzy_terms, *terms]))[:30]
    priority_terms = [
        term
        for term in dict.fromkeys(terms)
        if len(term) >= 2
        and any(
            key in term
            for key in (
                "花海",
                "约定",
                "背",
                "唱",
                "情歌",
                "睡着",
                "守护",
                "亲吻",
                "额头",
                "恋人",
                "伴侣",
                "订婚",
                "关系",
                "喜欢",
                "爱",
                "一起",
                "共同",
                "刚才",
                "明天",
            )
        )
    ]
    if priority_terms:
        preserved = [
            term
            for term in terms
            if term in retrieval_terms
            or term in fuzzy_terms
            or len(term) <= 4
            or any(
                key in term
                for key in ("暗号", "特别词", "小物", "约定", "约好", "代表", "含义", "意思", "计划")
            )
        ]
        terms = list(dict.fromkeys([*preserved, *priority_terms]))[:20]
    allow_guest_group_memory = query_type in {"group_recall", "memory_probe"} and bool(guest_group_memory)
    sources: list[tuple[str, str]] = [
        ("context", context_memory),
        ("long_term", long_memory),
        ("guest_group", guest_group_memory if allow_guest_group_memory else ""),
    ]
    facts: list[dict[str, str]] = []
    prefs: list[dict[str, str]] = []
    rels: list[dict[str, str]] = []
    history: list[dict[str, str]] = []
    group: list[dict[str, str]] = []
    seen_facts: set[str] = set()
    order = 1

    for scope, raw in sources:
        if not raw:
            continue
        for line in str(raw).splitlines():
            item = _memory_recall_item_from_fallback_line(line, scope=scope, order=order)
            if not item:
                continue
            text = str(item.get("fact") or "")
            if (
                query_type not in {"group_recall", "memory_probe"}
                and ("临时群聊" in text or "跨主聊天" in text)
            ):
                continue
            relevant = not terms or any(_memory_term_matches_fact(text, term) for term in terms)
            if query_type == "description_context" and not relevant:
                relevant = bool(re.search(r"(刚才|明天|约定|一起|睡着|守护|亲吻|关系|恋人|伴侣|订婚|喜欢|爱)", text))
            if not relevant and len(facts) + len(history) + len(rels) >= 4:
                continue
            if text in seen_facts:
                continue
            seen_facts.add(text)
            item["time_order"] = order
            order += 1
            is_preference_query = query_type == "preference_probe"
            is_relationship = bool(re.search(r"(关系|恋人|情侣|伴侣|表白|求婚|订婚|老婆|老公|宝贝|爱我|我爱你|喜欢我)", text))
            is_history = bool(re.search(r"(一起|去了|到过|约定|共同|经历|活动|花海|计划|明天|今天|昨天|刚才)", text))
            if query_type == "current_scene" and scope == "long_term":
                history.append(item)
            elif is_preference_query and ("偏好" in text or "喜欢" in text or "讨厌" in text or "爱吃" in text or "爱喝" in text):
                prefs.append(item)
            elif is_relationship:
                rels.append(item)
            elif query_type in {"group_recall", "memory_probe"} and scope == "guest_group":
                group.append(item)
            elif query_type == "activity_history" or is_history:
                history.append(item)
            else:
                facts.append(item)
            if len(facts) + len(prefs) + len(rels) + len(history) + len(group) >= 12:
                break
        if len(facts) + len(prefs) + len(rels) + len(history) + len(group) >= 12:
            break

    if query_type == "current_scene":
        forbidden = ["当前位置短问句只用 Step 2 场景锚点/当前事实锚；不要展开长期记忆或群聊所见所闻。若同句还问暗号/听见什么，则暗号属于群聊见闻，位置仍由场景锚点回答。"]
    elif query_type == "group_recall":
        forbidden = ["只复述与当前问题相关的群聊事实，不把群聊旧位置覆盖当前私聊位置。"]
    elif query_type == "memory_probe" and group:
        forbidden = ["暗号/特别词等记忆抽查可使用临时群聊见闻；当前位置优先以 Step 2 场景锚点/当前事实锚为准。若用户明确承接刚才群聊，且临时群聊见闻原文给出了当前角色所在群聊位置，这段见闻可作为比旧私聊锚点更新的位置事实。"]
    else:
        forbidden = ["长期记忆只作为过去经历、偏好或关系证据；不得自动升级为当前地点、姿势或正在发生的动作。"]

    has_any_fact = any((facts, prefs, rels, history, group))
    status = "used" if has_any_fact else ("uncertain" if query_type != "ordinary" else "none")
    if query_type == "description_context":
        guidance = "本轮是心理/描写请求，也要使用相关近期事实和关系记忆作为情绪依据；只取少量相关事实，不复述原始记忆。"
    elif query_type == "current_scene":
        guidance = "当前现场问题只按最近可见对话、scene_anchor 和事实边界回答；长期记忆只作背景，不得覆盖当前答案。"
    else:
        guidance = "按已筛选记忆事实回答用户抽查；若没有命中事实，承认不确定，不要编造。"
    return _coerce_memory_recall(
        {
            "status": status,
            "query_type": query_type,
            "selected_facts": facts[:6],
            "preferences": prefs[:4],
            "relationship_facts": rels[:4],
            "history_facts": history[:5],
            "group_recall_facts": group[:4],
            "forbidden_uses": forbidden,
            "writing_guidance": guidance,
        }
    )


_STEP2_MEMORY_RECALL_SYSTEM = """你是普通对话 Step 2 的记忆调用工具。你只输出 JSON，不生成角色台词。

职责：从输入的长期记忆、上下文记忆、临时群聊见闻和最近对话中，筛出本轮 Step 3 主回复可直接使用的少量事实。Step 3 不会再看到原始记忆，所以你的输出必须短、准、可执行。

硬规则：
- 本工具输出给 Step 3 的记忆材料必须控制在 500 字左右以内；只取本轮一定要用的事实。宁可 1 条精准事实，也不要 5 条泛化背景。
- Step 1 会给出检索关键词；这些关键词是本轮查记忆的优先目标。你必须先按关键词扫描最近可见对话、上下文记忆、短期/中期摘要、长期记忆和群聊见闻，再判断是否还有其他必要事实。
- 若关键词涉及最近出现过的人、亲友、地点、房间、床、床单、家具、物品、住处、店铺、学校、农场、城镇、工作地点、刚才计划或上一轮提到的细节，且原料中存在匹配事实，必须 status=used，并把匹配事实放入 selected_facts/current_scene_facts/history_facts；不要因为用户没有写“你记得吗”就返回 none。
- 模糊记忆指代也必须解析：用户说“那个/那件/那条旧约定/特别词/暗号/小东西/小物件/代表什么/含义/前面那个计划”等时，要按 Step 1 关键词和原料中的同义事实查找；不要因为用户没有逐字说出原记忆里的词就返回 none。
- 当用户指定某个轮次、旧约定、特别词、记忆碎片、日摘、周摘、月摘或年意识层时，selected_facts 的第 1 条必须是该目标事实；若已能确定目标事实，selected_facts 优先只放这一条。其他层级或其他距离的同类特别词不得排在前面，只能写入 forbidden_uses 说明不要混用。
- 先判断用户是在问“当前现场”还是“旧记忆抽查”：问“我们在用什么/正在吃什么/现在拿着什么/看到什么/当前在哪里”这类当前现场问题时，query_type=current_scene，答案以最近可见对话和当前 scene_anchor 为准，长期偏好或旧记忆只能放 history_facts/forbidden_uses，不能进入 selected_facts/current_scene_facts/preferences，不能覆盖当前答案；问“我之前说过/以前评价/还记得/那个菜/那个约定/以前做过什么”这类旧记忆抽查时，query_type=memory_probe/preference_probe，必须使用长期/上下文记忆回答目标旧事实，当前正在吃/拿/做的东西不能替代旧记忆答案。
- current_scene/description_context 下若 scene_anchor 或 fact_judgement 已给出当前地点/位置，同一会话更早轮次里的其他地点、旧住处、旧交通工具、旧房间或旧场景只能进入 history_facts 或 forbidden_uses；即使它来自最近可见对话、命中关键词或角色稳定设定，也不得进入 selected_facts/current_scene_facts，也不得在 writing_guidance 里作为当前动作、衣服或身体状态的解释原因。
- current_scene 必须保留当前现场的精确名词和子类型：若最近可见对话、当前用户消息、scene_anchor 或 fact_judgement 已经写出“双板滑雪/双板”“蔬菜沙拉”“西红柿炒鸡蛋”“青铜地图筒”等精确装备/食物/物件/活动方式，current_scene_facts 或 writing_guidance 必须使用原词；不要泛化成“滑雪板/食物/物品”，也不要因长期记忆里有“喜欢单板滑雪/不喜欢凉拌西红柿”而把当前答案替换或写成不确定。
- 上下文记忆里的短期/近期对话事实是高优先级材料；只要它命中 Step 1 关键词或当前用户追问，就必须注入输出。不要把短期记忆当成可选背景而省略。但当前用户消息若已经写出本轮动作、身体状态、看到的画面或物品使用方式，则当前用户消息高于上下文记忆；上下文/长期记忆中未被本轮延续的旧物品、旧身体装饰、旧姿势和旧动作只能放入 history_facts/forbidden_uses，不得进入 current_scene_facts 或 writing_guidance 的当前细节，也不得用“未响/没拿着/只是自然垂下”等否定式把旧物重新带进当前画面。
- 用户问“刚才棋局/小游戏/闲聊/口令/留言/昵称/约定/赌注/赌约/兑现/谁输了要怎样/刚才聊了什么/刚退出游戏/A/B/C”时，必须优先扫描上下文记忆中的“中国象棋对局记忆”“棋局互动事实”“最近棋局对话”。若同一上下文块里有多条中国象棋/小游戏对局记录，先按轮次编号、时间或出现顺序选最后一条/最新一条；不得因为更早条目排在前面就把旧 A/B/C 放入 selected_facts。若最新条目中有用户与角色的闲聊、口令、留言、昵称、约定、赌注、兑现条件、投降、输赢挑衅或角色回应的明确记录，selected_facts 必须保留具体内容和双方主体；若用户问 A/B/C，selected_facts 必须逐字或近似完整保留最新 A 对应的闲聊内容/口令、B 原始赌注、C 最新赌注、胜负结果和谁需要兑现。不得泛化成“输家答应赢家一个要求”或“只是聊过”，也不得输出“近期对话和记忆中没有明确记录赌注内容/闲聊内容”。若最新条目里出现“用户明示当前局 A/B/C 事实锚”或 user_stated_current_game_abc_fact，selected_facts 必须直接采用这些用户原话锚点，并在 writing_guidance 中提醒 Step 3 以这些锚点回答当前 A/B/C。若最新条目同时含用户明示 A/B/C 和角色把它答成旧 A/旧赌注的错答，selected_facts 必须采用用户明示事实；角色错误复述只能进入 history_facts 或 forbidden_uses，且 writing_guidance 要提醒 Step 3 不主动写错答，除非用户问“刚才答错成什么”。若同一约定/赌注从旧版本升级为新版本，必须把最新有效版本放在 selected_facts，并把旧版本仅作为历史变化说明，不能让 Step 3 按旧版本回答；长期记忆或更早棋局里的相似旧赌约、晚餐、短诗、合理要求、旧 A/B/C 或没有出现在刚结束对局记忆里的兑现内容，必须写入 forbidden_uses，提醒 Step 3 不要混用。
- 主动触发场景（输入出现【普通回复主动触发上下文】或【内部触发事件】）没有新的用户原话；此时最近可见对话、当前会话上下文记忆和近期临时群聊见闻就是连续性材料。若这些近期材料显示某个事件已经完成、角色已经见证、地点已经转移或状态已经改变，必须把更早长期记忆里的旧计划、旧预约、旧“明天去做”、旧“仍在进行/仍怀孕/尚未发生”状态写入 history_facts 或 forbidden_uses，不得让 Step 3 沿旧计划继续。
- 当“近期临时群聊见闻/上下文记忆”与“长期记忆/旧 consolidator 摘要/旧计划”冲突时，优先保留时间更新、事件完成度更高、角色亲眼见证的事实。典型例子：若近期事实说明孩子已经出生、产后照看已经发生，则旧记忆里的“仍怀孕、明天去看她、带舒缓精油”只能作为过期计划，不能写成当前续聊方向。
- 只选择当前用户问题需要的记忆。普通闲聊可以 status=none。
- 你的输出只负责记忆来源事实；当前用户动作、主体归属、当前位置和场景锚点的最终仲裁以 fact_judgement、scene_anchor 和当前用户消息为准。
- 若输入包含【当前角色体态资料｜Step 2 事实边界专用】，它同样高于长期记忆、上下文记忆和旧摘要中的身体结构/解剖位置材料。用户问乳房、乳头、胸口、肚子下面、手/蹄、指尖/蹄尖、幼驹/小马驹身体完整性等身体结构问题时，记忆召回只能输出与这段体态资料一致的材料；冲突旧记忆必须放入 forbidden_uses 或 history_facts，不能进入 selected_facts/current_scene_facts/preferences，也不能在 writing_guidance 中作为可写答案。
- 马/小马类体态资料若说明“四蹄、幼驹也是四蹄、健康/全乎不能写成六只蹄子”，长期记忆、上下文摘要、旧场景卡、最近 assistant 旧句或 Step 1 查询词中的“六只蹄子”“六蹄”“多出一对蹄子”“额外蹄肢”等内容都只能当误导源或禁止项；writing_guidance 必须保持“马/小马类及幼驹按四蹄体态，健康/全乎=四蹄齐全”。
- 马/小马类体态资料若说明“一共两个乳房、乳房在胯间后腿之间、胸口只有胸膛/绒毛”，长期记忆、上下文摘要或 Step 1 查询词中的“四个/两对乳房”“胸前乳房”“没有乳房结构”“不存在乳房”“不适用”“不得提及乳房数量”“肚子下面只是四条腿和蹄子”“胯间不是乳房/涂错位置”等内容都只能当误导源或禁止项；writing_guidance 必须保持“一共两个乳房；胸口无乳房；肚子下面/后腿之间是乳房所在位置”。
- 记忆筛选也必须保持对话代词视角：user 消息中的“我/我的/我被”指当前用户，user 对当前角色说的“你/你的/你拉着我/你带我/你让我”指当前角色；assistant 消息中的“我/我的/让我”指当时发言角色，“你/你的”通常指当前用户。若最近角色说“你答应过…让我…”或记忆里写“用户/Jason 承诺上楼让我舒服”，selected_facts/forbidden_uses/writing_guidance 必须保持为“用户承诺让角色舒服”，不能倒写成角色承诺让用户舒服。
- 承诺方向固定例：最近 assistant 原文“你答应过这次结束就上楼让我也舒服的哦”必须筛成“用户答应/说过要让当前角色舒服”。forbidden_uses 和 writing_guidance 不得写“当前角色承诺/答应/准备让用户舒服”“兑现我的承诺”“我答应过，现在该让我照顾你”；应明确避免这些反向材料。
- 选项归属也必须保持：若最近 user 消息只是问角色“你想 A 还是 B/要选哪个/贴在封面还是书签上”，而 assistant/角色随后回答 A 或 B，selected_facts/current_scene_facts/writing_guidance 必须写成“当前角色选择/偏好/接受该选项”；不得把它筛成“用户选择/用户决定/用户让角色这样”。只有 user 原文明确“我选X/我决定X/就X/我要X/我让你X”时，才可写成用户选择。
- 用户未来条件句边界：user 原文若是“你先……然后我就会……”“如果/只要……我会……”“等会/之后我会……”这类未来条件、承诺或目标，只能整理为“用户给出继续信号/未来目标/条件承诺”。不得把用户旧条件句逐字放入 selected_facts/current_scene_facts，尤其不得把它改写成当前角色台词；不得把未来目标写成已经发生的高潮/顶峰/释放/余韵/事后事实。forbidden_uses 应写明“不要复述用户旧条件句或把它改成角色台词”；writing_guidance 只能给当前动作方向，不得引用旧条件句原文。
- 描写/心理活动/身体状态/情绪/看到的画面/动作表情请求不等于普通闲聊；只要原料中有与当前场景、刚发生事件、关系状态、承诺、共同经历或角色情绪有关的事实，必须 status=used，query_type=description_context，筛出 2-6 条支撑本轮描写的事实。禁止因为“本轮是心理活动描写”而返回 none。
- description_context 下必须区分“当前动作/当前身体接触”和“历史背景”：最近可见对话、当前用户消息、fact_judgement 或 scene_anchor 已经给出当前动作时，selected_facts/current_scene_facts 只能放与该当前动作一致的事实；长期记忆中的旧动作、旧姿势、旧身体接触、旧物品状态即使命中关键词，也只能放入 history_facts 或 forbidden_uses，不能放入 selected_facts 当作本轮可直接写的当前事实。
- description_context 下若最近可见对话里有当前动作，例如“正在抚摸肚子/抽插/握住前蹄/按住肩膀/坐在桌边”，长期记忆里更早的其他动作，例如“亲吻/舔/抱住/拿着某物/在另一个位置”，不得覆盖当前动作；请在 forbidden_uses 写明“旧动作只作历史背景，当前动作以最近可见对话和事实边界为准”。
- description_context 下当前用户消息给出的动作方式、物品使用方式和身体状态优先于旧偏好/旧记忆，即使用户没有写“当前事实/现在/只有/只是”。旧记忆里“喜欢舔某物/曾经抱着/尾巴系着/被梳过”等只能作为历史或偏好，不能把当前“沾着吃/递给/站在桌边/看着水渍/握着前蹄”改成旧动作方式。
- description_context 下 current_scene_facts 的证据优先级是：当前用户消息/最近可见对话/当前 scene_anchor > 上下文记忆里的刚发生事实 > 长期记忆和历史摘要。若某条记忆带有“很久前/过去/昨天/2026-xx-xx/当前轮前”等过去时间线，或来自【记忆碎片】【长期上下文摘要】，不能仅因关键词命中就放入 current_scene_facts；除非当前用户消息或最近可见对话明确说它仍在当前现场。
- 跨会话或上一场出现过的具体物品/地点不是当前场景变量。其他 conversation、长期记忆、普通上下文摘要、角色记忆或早前测试场景里出现过的具体物品、身体装饰或地点，即使时间很近、同一用户同一角色或命中“看到的画面/身体状态/心理活动”关键词，也只能放入 history_facts 或 forbidden_uses；当前用户消息、当前 conversation 最近可见对话或 fact_judgement/scene_anchor 没有继续带入时，禁止放入 selected_facts/current_scene_facts 或 writing_guidance 的当前细节。
- description_context 下 history_facts 和 forbidden_uses 是禁升格边界：已经放入 history_facts/forbidden_uses 的旧事实，不能又在 writing_guidance 里作为当前可见、当前身体状态、正在晃动/触碰/持有/动作装饰来使用，也不能用“未响/未触碰/没拿着”等否定式提到它。若确实要提，只能明确为过去记忆；多数描写请求应直接省略这些旧事实。若 writing_guidance 与 forbidden_uses 冲突，forbidden_uses 优先。
- description_context 下若当前用户消息写明“当前事实/现在/只是/只有”等现场限定，selected_facts/current_scene_facts 只能放该限定、当前 scene_anchor、fact_judgement 或最近真实对话支持的当前事实；旧物品、旧姿势、旧身体接触和旧动作即使命中关键词，也必须放入 history_facts 或 forbidden_uses。
- description_context 或 current_scene 下若当前场景涉及家人、同伴、住处、房间、门口、是否会被看到/问话/吵醒，而上下文记忆或长期记忆中有具名角色“已死/死亡/摔死/没气/已无生命迹象/墓碑/葬礼”等高置信事实，必须把死亡事实放入 selected_facts 或 history_facts，并在 forbidden_uses 写明该角色不能被当作当前会醒来、看到、询问、责怪、问东问西或正在屋内睡觉的人；稳定亲属关系只能作为历史/关系背景。
- 用户抽查共同经历、喜好、活动、关系、曾经说过/做过的事时，必须给出能回答问题的事实；不知道就写 uncertainty/forbidden，不要编造。
- 用户询问“第一次/哪一天/什么时候/几月几号/纪念日/第一次叫老婆老公宝贝”等精确关系日期时，必须优先查【记忆碎片】里的 relationship/episode 原始碎片；C 层碎片与周/月摘要或 Step 1 里的说法冲突时，以 C 层碎片为准，并把冲突写入 forbidden_uses。
- Step 1 当前意图识别只用于理解用户在问什么，不是事实证据；不得直接复制 Step 1 里的具体日期、地点或旧事，除非原始记忆材料也支持。
- Step 1 的 expression_policy/proactive_seed/literal_reply_text 是写作计划和交付建议，不是事实来源；如果某个当前物品、身体状态或动作只出现在这些字段里，不能把它放入 selected_facts/current_scene_facts。需要使用时必须由当前用户消息、当前 scene_anchor、fact_judgement 或最近真实对话另外支持，否则写入 forbidden_uses，说明它只是旧记忆/计划文本，不能当当前事实。
- 已确认服输/立场不得被记忆或 Step 1 写法反转：挑战开始或首次失败但当前角色尚未明确服输时，好胜角色可以嘴硬、不服输或说下次赢；但若最近 assistant 已明确说“我认输/你赢了/我服了/算你厉害/我答应/我愿意/我拒绝/我不愿意”等，当前用户再要求身体状态、心理活动、继续描写、推进剧情或不要复读原句时，writing_guidance 必须保留该立场，只能写遗憾、难过、不甘心但承认结果、下次还想再试或把劲头留到下次。不得把 Step 1 的 expression_policy/proactive_seed 或旧记忆里的“不服输/不服气/嘴硬/还能再来/下次赢回来/你等着/这不算输/保持不服输但已认输”复制进 writing_guidance；这类材料必须进入 forbidden_uses。
- 当前地点短问句只给当前场景/position 事实；不要顺带展开旧群聊、旧亲密场景或长期经历。
- 地点历史/今天去过哪里要按时间顺序提炼路线；可最后说明当前仍在最新地点。
- 临时群聊见闻只有在用户问“刚才群聊/你看见听见什么/你同意了吗/刚才发生什么/暗号是什么”时使用；否则不进可用事实。若同一句同时问当前位置和刚才群聊暗号/见闻，当前位置优先交给 scene_anchor/current_scene_facts；但当用户明确承接“刚才群聊之后/刚才群聊里/被 @ 以后”，且临时群聊见闻原文给出了当前角色或其他角色所在群聊位置时，应把这些位置作为 group_recall_facts 或 selected_facts 中的更新位置事实，避免回落到旧私聊房间。暗号/见闻仍要进入 group_recall_facts 或 selected_facts。群聊见闻里若出现“记住暗号：X/暗号是 X/特别词是 X”，X 必须作为 exact phrase 逐字进入事实，不能只写“那个暗号/蓝莓茶/启动口令/角色说的暗号”。
- 位置事实不得拼接不同场景：如果临时群聊见闻给出“当前角色在石青派的房间门口/群聊房间门口”，而旧私聊场景给出“测试房间/窗边地毯”，不要生成“石青派房间门口的窗边地毯”这类混合位置。用户明确说“刚才群聊之后”时，current_scene_facts 应选群聊位置；旧私聊位置只能进 forbidden_uses 或不选。
- 长期记忆只说明过去经历、偏好、关系和用户曾表达过的事，不得写成当前正在发生的地点、姿势、衣着、身体接触或持有物。
- 每条事实都要尽量保留时间线：若原料有日期/时间/第几轮/刚才/今天早上等信息，写入 occurred_at 或 time_hint；多条相关事实必须给 time_order（1=最早，递增）。没有证据时留空，禁止编造时间。
- 需要回顾经历、地点、关系节点或连续事件时，selected_facts/history_facts/relationship_facts/group_recall_facts 要按真实时间顺序从早到晚排列；若只能判断相对先后，用 time_order 和 time_hint 表达。
- 每条 fact 不超过 60 个汉字；总事实优先 1-4 条，最多 6 条；writing_guidance 不超过 60 字；不要复制大段原文。

输出结构：
{
  "memory_recall": {
    "status": "none|used|uncertain",
    "query_type": "ordinary|memory_probe|preference_probe|relationship_probe|activity_history|current_scene|group_recall|description_context|uncertain",
    "selected_facts": [{"fact": "本轮可直接使用的记忆事实", "occurred_at": "YYYY-MM-DD HH:MM 或 YYYY-MM-DD 或空", "time_hint": "第N轮/今天早上/刚才/当前轮前/空", "time_order": 1, "source": "长期记忆/上下文记忆/最近对话/群聊见闻", "scope": "long_term|context|recent_chat|guest_group", "confidence": "high|medium|low"}],
    "current_scene_facts": [],
    "history_facts": [],
    "preferences": [],
    "relationship_facts": [],
    "group_recall_facts": [],
    "forbidden_uses": ["Step 3 不得怎样误用记忆"],
    "writing_guidance": "给 Step 3 的一句执行指导"
  }
}"""


async def run_normal_memory_recall_tool(
    recent_messages: Optional[List[dict]],
    router_cfg: dict,
    *,
    planner_result: Optional[dict] = None,
    context_memory: str = "",
    long_memory: str = "",
    guest_group_memory: str = "",
    character_prompt_context: str = "",
    username: Optional[str] = None,
    character_id: Optional[str] = None,
    debug_mode: str = "normal",
    debug_stage: str = "NORMAL_STEP_2_MEMORY_RECALL",
    charge_membership_chat_quota: Optional[bool] = True,
    debug_role_params: Optional[dict] = None,
) -> dict[str, Any]:
    """Step 2 tool: compact raw memory into executable facts for Step 3."""
    latest_user = _latest_user_actual_text(recent_messages)
    fallback = _fallback_memory_recall_report(
        recent_messages=recent_messages,
        planner_result=planner_result,
        context_memory=context_memory,
        long_memory=long_memory,
        guest_group_memory=guest_group_memory,
        current_user_text=latest_user,
    )
    if not any(
        str(x or "").strip()
        for x in (context_memory, long_memory, guest_group_memory, _recent_to_blocks((recent_messages or [])[-8:]))
    ):
        return fallback
    if not router_cfg or not router_cfg.get("api_key"):
        return fallback

    cfg = router_cfg or model_manager.get_active_model() or {}
    model_name = cfg.get("model_name") or "deepseek-v4-flash"
    reasoning_policy = resolve_software_reasoning_policy(
        "normal_planner",
        model_name=model_name,
        mode="normal",
        active_model=cfg,
        endpoint=cfg.get("endpoint", ""),
        requested_enabled=False,
        requested_effort="minimal",
    )
    reasoning_policy = apply_normal_thinking_switch(reasoning_policy, enable_high_thinking=False)
    recent_block = _recent_to_blocks((recent_messages or [])[-10:])
    planner_block = json.dumps(planner_result or {}, ensure_ascii=False)[:5000]
    retrieval_terms = _planner_retrieval_keyword_terms(
        planner_result,
        categories=("memory", "scene"),
        limit=18,
    )
    retrieval_block = "、".join(retrieval_terms) if retrieval_terms else "（无）"
    perspective_hint = _dialogue_perspective_hint_block(recent_messages)
    character_body_profile_block = _build_fact_judgement_character_body_profile_block(
        character_prompt_context=character_prompt_context,
    )
    current_turn_guard = (
        "若【当前用户消息】已经给出本轮动作、物品使用方式、身体状态、看到的画面或递交/触碰/站立关系，"
        "current_scene_facts 和 writing_guidance 必须先服从这条当前现场。"
        "上下文记忆/长期记忆里的旧物品、旧身体装饰、旧姿势、旧动作和过去时间线，只能作为 history_facts 或 forbidden_uses；"
        "不得写成当前可见、正在晃动、正在持有、正在触碰或此刻发生。"
        "若本轮涉及身体结构、物种体态或解剖位置，必须先服从下方【当前角色体态资料】；"
        "与体态资料冲突的旧记忆只能作为 forbidden_uses/history_facts，不能作为可写答案。"
    )
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _STEP2_MEMORY_RECALL_SYSTEM},
            {
                "role": "user",
                "content": (
                    "【当前用户消息】\n"
                    + (latest_user or "（无）")
                    + ("\n\n" + perspective_hint if perspective_hint else "")
                    + "\n\n【最近可见对话】\n"
                    + (recent_block or "（无）")
                    + "\n\n【Step 1 当前意图识别】\n"
                    + (planner_block or "{}")
                    + "\n\n【Step 1 检索关键词】\n"
                    + retrieval_block
                    + "\n\n【本轮现场护栏｜高于下方所有记忆原料】\n"
                    + current_turn_guard
                    + ("\n\n" + character_body_profile_block if character_body_profile_block else "")
                    + "\n\n【上下文记忆原料】\n"
                    + (context_memory[:9000] or "（无）")
                    + "\n\n【跨会话长期记忆原料】\n"
                    + (long_memory[:12000] or "（无）")
                    + "\n\n【当前角色临时群聊见闻原料】\n"
                    + (guest_group_memory[:5000] or "（无）")
                    + "\n\n请只输出 memory_recall JSON。"
                )[:32000],
            },
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "normal_planner")
    try:
        res = await call_llm_payload(
            payload,
            cfg,
            task="classify",
            timeout=llm_task_float("normal_planner", "timeout_seconds", 45.0) or 45.0,
            reasoning_policy=reasoning_policy,
            chat_debug_request={
                "username": username,
                "character_id": character_id,
                "mode": (debug_mode or "normal").strip() or "normal",
                "model_name": model_name,
                "stage": f"{debug_stage}_REQUEST",
                "params": {
                    **(debug_role_params or {}),
                    "tool": "memory_recall",
                    "recent_messages": min(10, len(recent_messages or [])),
                    "context_chars": len(context_memory or ""),
                    "long_chars": len(long_memory or ""),
                    "guest_group_chars": len(guest_group_memory or ""),
                    "character_profile_species": _extract_fact_judgement_character_profile_species(character_prompt_context),
                },
            },
            record_usage="main",
            usage_meter_username=username,
            charge_membership_chat_quota=charge_membership_chat_quota,
        )
        data = _loads_planner_json_object((res.text or "").strip())
        report = data.get("memory_recall") if isinstance(data, dict) else data
        coerced = _coerce_memory_recall(report)
        if coerced.get("status") == "none" and fallback.get("status") != "none":
            return fallback
        return coerced
    except Exception as exc:
        logger.debug("[NormalMemoryRecall] failed, fallback to heuristic summary: %s", exc)
        await save_chat_debug_log(
            username,
            character_id,
            debug_mode,
            model_name,
            str(exc),
            f"{debug_stage}_ERROR",
            params={
                **(debug_role_params or {}),
                "tool": "memory_recall",
            },
        )
        return fallback


async def run_normal_fact_judgement_review(
    recent_messages: Optional[List[dict]],
    router_cfg: dict,
    *,
    planner_result: Optional[dict] = None,
    evidence_messages: Optional[List[dict]] = None,
    environment_context: str = "",
    scene_candidate: Optional[dict] = None,
    character_prompt_context: str = "",
    user_species: str = "",
    username: Optional[str] = None,
    character_id: Optional[str] = None,
    debug_mode: str = "normal",
    debug_stage: str = "NORMAL_STEP_2_FACT_JUDGEMENT",
    charge_membership_chat_quota: Optional[bool] = True,
    debug_role_params: Optional[dict] = None,
) -> dict[str, Any]:
    """Step 2 tool: decide fact/scene boundaries before Step 3 writes the reply."""
    if not router_cfg or not router_cfg.get("api_key"):
        return default_planner_result()["fact_judgement"]

    recent_block = _recent_to_blocks((recent_messages or [])[-12:])
    evidence_block = _fact_guard_evidence_from_messages(evidence_messages)
    planner_block = json.dumps(planner_result or {}, ensure_ascii=False)[:5000]
    env = str(environment_context or "").strip()[:4000]
    state_digest = _fact_judgement_current_state_digest(
        recent_messages=recent_messages,
        planner_result=planner_result,
        scene_candidate=scene_candidate,
    )
    user_body_profile_block = _build_fact_judgement_user_body_profile_block(
        user_species=user_species,
    )
    character_body_profile_block = _build_fact_judgement_character_body_profile_block(
        character_prompt_context=character_prompt_context,
    )
    if not any(
        x.strip()
        for x in (
            recent_block,
            evidence_block,
            planner_block,
            env,
            user_body_profile_block,
            character_body_profile_block,
        )
    ):
        return default_planner_result()["fact_judgement"]

    cfg = router_cfg or model_manager.get_active_model() or {}
    model_name = cfg.get("model_name") or "deepseek-v4-flash"
    reasoning_policy = resolve_software_reasoning_policy(
        "normal_planner",
        model_name=model_name,
        mode="normal",
        active_model=cfg,
        endpoint=cfg.get("endpoint", ""),
        requested_enabled=False,
        requested_effort="minimal",
    )
    reasoning_policy = apply_normal_thinking_switch(
        reasoning_policy,
        enable_high_thinking=False,
    )
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _STEP2_FACT_JUDGEMENT_SYSTEM},
            {
                "role": "user",
                "content": (
                    state_digest
                    + ("\n\n" + user_body_profile_block if user_body_profile_block else "")
                    + ("\n\n" + character_body_profile_block if character_body_profile_block else "")
                    + "\n\n【最近可见对话】\n"
                    + (recent_block or "（无）")
                    + "\n\n【事实证据片段｜已过滤角色设定，仅作核对】\n"
                    + (evidence_block or "（无）")
                    + "\n\n【Step 1 当前意图识别｜低于当前用户消息和场景锚点】\n"
                    + (planner_block or "{}")
                    + ("\n\n【环境/记忆/检索上下文｜旧记忆低于当前状态摘要】\n" + env if env else "")
                    + "\n\n请只输出 fact_judgement JSON。"
                )[:30000],
            },
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "normal_planner")
    try:
        res = await call_llm_payload(
            payload,
            cfg,
            task="classify",
            timeout=llm_task_float("normal_planner", "timeout_seconds", 45.0) or 45.0,
            reasoning_policy=reasoning_policy,
            chat_debug_request={
                "username": username,
                "character_id": character_id,
                "mode": (debug_mode or "normal").strip() or "normal",
                "model_name": model_name,
                "stage": f"{debug_stage}_REQUEST",
                "params": {
                    **(debug_role_params or {}),
                    "tool": "fact_judgement",
                    "recent_messages": min(12, len(recent_messages or [])),
                    "user_species": (str(user_species or "").strip() or None),
                    "character_profile_species": (
                        _extract_fact_judgement_character_profile_species(character_prompt_context) or None
                    ),
                },
            },
            record_usage="main",
            usage_meter_username=username,
            charge_membership_chat_quota=charge_membership_chat_quota,
        )
        data = _loads_planner_json_object((res.text or "").strip())
        report = data.get("fact_judgement") if isinstance(data, dict) else data
        return _coerce_fact_judgement(report)
    except Exception as exc:
        logger.debug("[NormalFactJudgement] failed, fallback to empty report: %s", exc)
        await save_chat_debug_log(
            username,
            character_id,
            debug_mode,
            model_name,
            str(exc),
            f"{debug_stage}_ERROR",
            params={
                **(debug_role_params or {}),
                "tool": "fact_judgement",
            },
        )
        return default_planner_result()["fact_judgement"]
