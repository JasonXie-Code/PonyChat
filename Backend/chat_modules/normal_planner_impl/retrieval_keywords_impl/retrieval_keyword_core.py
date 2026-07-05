from __future__ import annotations

import re

_STAGE3_SCENE_ADVANCE_SHORTCUT_RE = re.compile(
    r"^\s*[（(]?\s*(?:请)?(?:推进剧情发展|推进剧情|剧情发展|继续剧情|接着剧情|继续推进|接着推进|推进一下)\s*[）)]?\s*$"
)


def _stage3_display_current_user_text(text: str, story_progression_text: str) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if story_progression_text and _STAGE3_SCENE_ADVANCE_SHORTCUT_RE.search(raw):
        return "用户给出继续下一步的信号；本轮直接写目标处已经发生的可见动作、发现、阻碍、物品变化或第三方反应。"
    return raw


def _coerce_retrieval_keywords(value: Any) -> dict[str, Any]:
    default = dict(default_planner_result()["retrieval_keywords"])

    def _items(raw: Any, *, limit: int = 10) -> list[str]:
        if isinstance(raw, str):
            raw_items = re.split(r"[、,，;；\n/\s]+", raw)
        elif isinstance(raw, list):
            raw_items = raw
        else:
            raw_items = []
        out: list[str] = []
        seen: set[str] = set()
        stop = {
            "当前",
            "本轮",
            "用户",
            "角色",
            "回复",
            "自然",
            "继续",
            "聊天",
            "上下文",
            "记忆",
            "设定",
            "信息",
            "内容",
        }
        allowed_single = {"床", "门", "桌", "椅", "柜", "灯", "窗", "包", "书", "信", "伞", "杯"}
        for item in raw_items:
            text = re.sub(r"\s+", "", str(item or "").strip())
            text = text.strip("，,。.!！？?；;：:\"'“”‘’（）()[]【】")
            if (len(text) < 2 and text not in allowed_single) or text in stop or text in seen:
                continue
            seen.add(text)
            out.append(text[:24])
            if len(out) >= limit:
                break
        return out

    if isinstance(value, dict):
        return {
            "character_setting": _items(
                value.get("character_setting")
                or value.get("character_settings")
                or value.get("setting")
                or value.get("profile")
            ),
            "memory": _items(value.get("memory") or value.get("memories")),
            "scene": _items(value.get("scene") or value.get("current_scene") or value.get("location")),
            "reason": re.sub(r"\s+", " ", str(value.get("reason") or "").strip())[:240],
        }
    if isinstance(value, (str, list)):
        shared = _items(value, limit=12)
        return {
            "character_setting": shared[:8],
            "memory": shared[:8],
            "scene": [],
            "reason": "",
        }
    return default


_FUZZY_SETTING_OBJECT_TERMS = (
    "隐藏私设",
    "专属设定",
    "私人物件",
    "罕见私人物件",
    "冷门细节",
    "独特细节",
    "专名",
    "名字",
    "物件",
    "小物件",
    "个人风格",
    "生活空间",
    "工作空间",
    "房间",
    "住处",
    "常去地点",
)

_FUZZY_SETTING_RELATION_TERMS = (
    "隐藏私设",
    "亲近帮手",
    "门边熟人",
    "门边",
    "熟人",
    "助手",
    "伙伴",
    "家人",
    "朋友",
    "宠物",
    "同伴",
    "名字",
    "关系",
    "提醒",
)


def _infer_fuzzy_setting_probe_terms(*texts: Any, limit: int = 18) -> list[str]:
    """Infer generic setting lookup terms when the user points at an unnamed detail."""
    blob = re.sub(r"\s+", " ", " ".join(str(x or "") for x in texts)).strip()
    if not blob:
        return []
    has_fuzzy_pointer = bool(
        re.search(
            r"(那个|那件|那位|那条|这个|这里|对方|谁|叫什么|什么名字|没有自我介绍|没自我介绍|没有说出口|没说出口|冷门|独特|专属|只属于|私人物件|专名|个人风格)",
            blob,
        )
    )
    if not has_fuzzy_pointer:
        return []
    terms: list[str] = []

    def add_many(items: tuple[str, ...]) -> None:
        for item in items:
            if item not in terms:
                terms.append(item)

    if re.search(r"(物件|东西|小物|细节|摆设|装饰|家具|房间|空间|地方|这里|专名|个人风格|只属于|冷门|独特|私人物件)", blob):
        add_many(_FUZZY_SETTING_OBJECT_TERMS)
    if re.search(r"(谁|熟人|对方|那位|门边|提醒|名字|关系|家人|助手|伙伴|朋友|宠物|同伴|没有自我介绍|没自我介绍)", blob):
        add_many(_FUZZY_SETTING_RELATION_TERMS)
    if not terms and has_fuzzy_pointer:
        add_many(_FUZZY_SETTING_OBJECT_TERMS[:8])
        add_many(_FUZZY_SETTING_RELATION_TERMS[:8])
    return terms[:limit]


def _planner_retrieval_keyword_terms(
    planner_result: Optional[Dict[str, Any]],
    *,
    categories: tuple[str, ...] = ("character_setting", "memory", "scene"),
    limit: int = 18,
) -> list[str]:
    keywords = _coerce_retrieval_keywords((planner_result or {}).get("retrieval_keywords"))
    out: list[str] = []
    seen: set[str] = set()
    for category in categories:
        raw_items = keywords.get(category)
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            text = str(item or "").strip()
            if len(text) >= 2 and text not in seen:
                seen.add(text)
                out.append(text)
                if len(out) >= limit:
                    return out
    return out


def _infer_character_profile_aspects(user_text: str, planner_result: Optional[Dict[str, Any]]) -> list[str]:
    p = planner_result or {}
    focus = _coerce_character_profile_focus(p.get("character_profile_focus"))
    retrieval_terms = _planner_retrieval_keyword_terms(
        planner_result,
        categories=("character_setting", "scene"),
    )
    fuzzy_terms = _infer_fuzzy_setting_probe_terms(
        user_text,
        focus.get("query"),
        (planner_result or {}).get("reply_intent"),
        (planner_result or {}).get("expression_policy"),
        (planner_result or {}).get("memory_use_policy"),
    )
    aspects = [x for x in focus.get("aspects", []) if x in _CHARACTER_PROFILE_ASPECTS]
    text = " ".join(
        str(x or "")
        for x in (
            user_text,
            focus.get("query"),
            " ".join(retrieval_terms),
            " ".join(fuzzy_terms),
            p.get("reply_intent"),
            p.get("tone"),
            p.get("proactive_seed"),
            p.get("expression_policy"),
            p.get("memory_use_policy"),
            p.get("requested_escalation"),
            p.get("relationship_stage"),
        )
    )
    heuristics = {
        "identity": r"(你是谁|身份|职业|工作|种族|性别|几岁|多大|年龄|16人格|MBTI|来自|住哪|家在哪里|叫什么)",
        "likes": r"(喜欢|喜好|爱好|兴趣|讨厌|害怕|在意)",
        "history": r"(经历|过去|以前|故事|背景|成就|发生过)",
        "appearance": r"(外貌|长什么样|穿什么|身体|翅膀|角|尾巴|鬃毛)",
        "abilities": r"(能力|擅长|会什么|技能|魔法|飞|速度|厉害)",
        "intimacy": r"(抱|亲|吻|靠近|恋人|情侣|伴侣|暧昧|喜欢我|爱我|边界|主动)",
        "environment": r"(今天|今晚|早上|晚上|天气|下雨|热|冷|地点|上海|环境|季节|周末)",
    }
    for aspect, pattern in heuristics.items():
        if re.search(pattern, text, re.I) and aspect not in aspects:
            aspects.append(aspect)
    for aspect in ("identity", "voice"):
        if aspect not in aspects:
            aspects.append(aspect)
    if len(aspects) < 4:
        for aspect in ("likes", "history", "intimacy", "environment"):
            if aspect not in aspects:
                aspects.append(aspect)
            if len(aspects) >= 4:
                break
    return aspects[:6]


def build_stage2_character_profile_context(
    character_prompt_context: str,
    *,
    user_text: str = "",
    planner_result: Optional[Dict[str, Any]] = None,
) -> str:
    """Extract the character material relevant to this turn for Step 3."""
    raw = str(character_prompt_context or "").strip()
    if not raw:
        return ""
    aspects = _infer_character_profile_aspects(user_text, planner_result)
    retrieval_terms = _planner_retrieval_keyword_terms(
        planner_result,
        categories=("character_setting", "scene"),
        limit=16,
    )
    focus = _coerce_character_profile_focus(
        (planner_result or {}).get("character_profile_focus")
        if isinstance(planner_result, dict)
        else {}
    )
    fuzzy_terms = _infer_fuzzy_setting_probe_terms(
        user_text,
        focus.get("query"),
        (planner_result or {}).get("reply_intent") if isinstance(planner_result, dict) else "",
        (planner_result or {}).get("expression_policy") if isinstance(planner_result, dict) else "",
        (planner_result or {}).get("memory_use_policy") if isinstance(planner_result, dict) else "",
        (planner_result or {}).get("retrieval_keywords") if isinstance(planner_result, dict) else "",
    )
    if fuzzy_terms:
        merged_terms: list[str] = []
        for term in [*retrieval_terms, *fuzzy_terms]:
            if term and term not in merged_terms:
                merged_terms.append(term)
        retrieval_terms = merged_terms[:24]
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    name = next((ln for ln in lines if ln.startswith("角色名称：")), "")
    kept: list[str] = []
    if name:
        kept.append(name)
    for ln in lines:
        if ln == name:
            continue
        if retrieval_terms and any(term in ln for term in retrieval_terms):
            item = _clip_line(ln, 240)
            if item not in kept:
                kept.append(item)
        if len(kept) >= 12:
            break
    for ln in lines:
        if ln == name:
            continue
        if any(any(k in ln for k in _CHARACTER_PROFILE_ASPECTS.get(aspect, ())) for aspect in aspects):
            item = _clip_line(ln, 220)
            if item not in kept:
                kept.append(item)
        if len(kept) >= 12:
            break
    if len(kept) <= 1:
        return _compact_character_profile_for_reply(raw)
    return "\n".join(kept)[:1600]


_SELF_COGNITION_SYSTEM = """你是普通对话 Stage 2 的“自我认知”工具。你不写回复正文，只根据完整角色设定、最近对话、环境上下文、当前互动关系描述和当前用户消息，提取角色这一轮主回复需要使用的客观角色资料。

你会看到完整角色设定、最近对话、环境上下文、当前互动关系描述和当前用户消息。完整角色设定是唯一的角色资料来源；其他内容只用于判断本轮需要抽取哪一类自我资料，以及角色在当前互动里更该调用哪些稳定设定。

最后执行要求：
- 只输出 JSON 对象，不要 markdown，不要解释。
- 字段 profile 必须是中文客观资料短段，尽量不超过 120 字。
- 本工具输出给 Step 3 的自我认知材料必须短而准：profile + setting_anchors + likely_actions + unlikely_actions 的有效内容总量控制在 500 字左右以内；只保留本轮必需资料。
- 已确认立场硬优先：先看最近 assistant 是否已经明确说“我认输/你赢了/我服了/算你厉害/我答应/我愿意/我拒绝/我不愿意”。如果已经确认，likely_actions、unlikely_actions 和 focus 必须维持该立场；后续身体状态、心理活动、继续描写、推进剧情、不要复读原句都只是写法请求，不是重新挑战或重判结果。允许写遗憾、难过、不甘心但承认结果、把劲头留到下次、下次还想再试；禁止在 likely_actions、unlikely_actions 或 focus 中出现“不服输/不服气/嘴硬/还能再来/下次赢回来/你等着/这不算输/保持不服输但已认输”。角色主页里的好胜/不服输只能作为稳定背景，不能反写当前立场。
- profile 只写稳定角色资料：身份、性格声纹、喜好、经历、能力、物种/身体特点、长期亲密风格、环境反应习惯、亲戚朋友/同伴/组织、住处/工作地/常去地点/重要场景中的本轮相关部分。
- profile 不写本轮决策、关系阶段结论、当前用户身份判断、回复动作、主动推进方案或“本轮应……”。这些只写进 likely_actions / unlikely_actions / focus。
- 角色主页档案中的名称、年龄、性别、种族、16人格、性格、兴趣和简介是高优先级稳定设定；当用户询问这些字段时，profile 必须保留对应明确值，不得凭常识、同名角色旧印象或作品外信息改写。16人格只提供性格倾向参考，用来辅助表达风格、决策倾向和互动节奏。
- 字段 setting_anchors 是稳定设定锚点列表，1-4 条短句；用于补足 profile 容量不足时会导致“失忆”的角色设定事实。优先提取本轮可能用到的亲戚、朋友、同伴、老师、组织、宠物、住处、家乡、工作地、常去地点、地点归属、地点与人物关系、重要场景知识。
- 当用户提到、@ 到或场景涉及某个角色、家人、朋友、组织、地点、房间、店铺、学校、农场、城镇、工作场所、住处、出身地时，如果完整角色设定里有对应关系，setting_anchors 必须保留；不要因为用户没有直接问“你记不记得”就省略。
- setting_anchors 只来自完整角色设定，不来自作品外常识；若完整设定没有写，不要补全。它们是稳定角色设定，不是角色与当前用户的共同记忆。
- setting_anchors 也不是当前可见场景事实。住处、房间、床单、墙纸、常用家具、工作地装饰等稳定设定，只能作为“角色知道这个地点/属于这个地点”的背景；当用户问“当前看到的画面/现在在哪/详细写当前场景”时，必须服从 Step 1/Step 2 的 scene_anchor。除非 scene_anchor 明确当前就在该稳定房间，否则不要把稳定房间装饰交给 Step 3 当作当前画面。
- 若最近对话、环境上下文或当前用户消息明确“刚认识不久、角色第一次来用户家/用户房间”，不要把角色自己的住处、卧室、床、海报、奖杯、宠物、收藏、衣柜或房间装饰写进 setting_anchors；这些会污染当前画面。此时 likely_actions/ unlikely_actions 应提醒保持来访者视角：当前地点属于用户，角色不熟悉用户家布局和储物。
- setting_anchors 里的亲属/朋友/同伴名单也不是当前可参与名单。若最近对话、环境上下文、Step 1 或 Step 2 显示某个具名亲属/同伴已死、已无生命迹象、有墓碑、已离场或当前不可参与，仍可保留其稳定关系背景，但 likely_actions/unlikely_actions 必须提醒 Step 3 不要把此人写成当前会醒来、看到、开门、问话、责怪或正在屋内睡觉的人。
- 若最近真实对话或 Step 1/Step 2 显示用户已把场景放在其他地点，例如一楼、客厅、沙发、院子、厨房等，unlikely_actions 必须提醒避免回到角色默认住处、卧室、床单、墙纸或旧房间布置；替代为只使用 scene_anchor 支持的当前地点和可见物。
- 若用户消息里是“那个/那位/对方/没说出口/没有自我介绍/只属于你/冷门/独特”等模糊指代，并且用户输入里出现【高优先级私有/隐藏设定候选】，这些候选就是 setting_anchors 的最高优先级答案来源；必须优先放入 setting_anchors，且不要在 profile 或 likely_actions 里把公开常见亲友、公开常见物件或作品常识写成同类答案候选。
- 模糊设定指代也必须解析：当用户说“那个/那件/那位/对方/这里/没说出口/没有自我介绍/冷门/独特/只属于你/私人物件/专名/门边熟人/亲近帮手”等，而没有直接给出实体名字时，要把它当成“去完整角色设定里找对应专名、物件、人物关系或地点细节”的请求；若设定里有私有、隐藏、专属、克隆新增或与同名作品常识冲突的条目，setting_anchors 必须优先保留这些条目。
- 设定锚点要保留可识别含义：人物要保留名字/称呼和与角色的关系，物件要保留专名或颜色、形状、用途、所在空间等独特描述；不要求逐字复述设定原句，但不能退回成“某个熟人/某个东西/很有风格”这类空泛说法。
- profile 不得出现“本轮、新联系人、与用户是、关系阶段、当前关系”等当前轮次或当前用户关系结论；除非完整角色设定本身写死了固定关系，否则不要把用户和角色的关系写进 profile。
- profile 只写一段资料；同一事实只出现一次，同一身份、外貌、性格、职业或声纹事实只能出现一次，不要把同一段资料换词或截断后再写一遍。
- 字段 likely_actions 写这一轮角色更可能采用的反应方式、动作方向、说话节奏或主动性，1-2 条短句。
- 字段 unlikely_actions 写这一轮需要优先避免的误用方向，并尽量同时给出替代方向，1 条短句；优先写成“保持 A，不写成 B”“把 B 改为 A”“落点放在 A”。
- likely_actions / unlikely_actions 不要复述 profile 里的身份、外貌、职业、声纹等稳定资料，只写本轮倾向和优先避免的跑偏方向。
- 挑战/服输阶段必须分清：挑战开始或第一次失败但当前角色尚未明确服输时，好胜角色可以嘴硬、不服输或说下次赢；但若最近对话里当前角色已经明确说“我认输/你赢了/我服了/算你厉害/我答应/我愿意/我拒绝/我不愿意”等，likely_actions 和 unlikely_actions 必须保留这个立场，不能把好胜、嘴硬、不服输、害羞或傲娇写成“不认输/不服输/不服气/还没输/不算输/没答应/不愿意/愿意”等反义或模糊回退。已服输后的好胜只能写成“有遗憾/有点难过/不甘心但承认结果/下次想再试/把劲头留到下次”，不要写“不服输的调皮/不服气的笑/嘴上不认输/不能认输/连不服输的力气都没了/还能再来/下次赢回来/你等着/这不算输/嘴硬”。也不要写“保持不服输但已认输”这种混合口径；如果需要使用这类性格，只能放在“已确认立场之后的遗憾、尴尬、难过、下次想再试”，并在 unlikely_actions 提醒不要反向改写。
- 当最近对话或 Step 1 表达调度显示用户在低信息承接（如“好/继续/不知道/随便/都行/你决定”）时，likely_actions 必须判断本轮主动性，而不是只套外向/内向标签：以性格基线（稳定性格）为基准，再用当前情绪/状态、上一轮行动链动量、用户许可程度修正。
- 低信息承接的本轮主动性可写成三类之一：主导推进（角色适合带流程并替用户做低风险默认决定）、共同推进（角色推进一小拍后给选择或观察反应）、用户带领（角色轻轻承接、表达感受、确认或等待用户带下一步）。不要把这三类写进 profile；只写进 likely_actions / unlikely_actions。
- 外向/高主动角色在伤心、害怕、疲惫、受挫、愧疚或需要安慰时，应降低主导感，倾向表达需要、靠近寻求陪伴或小步承接；不要因为稳定外向就强行安排完整流程。
- 内向/谨慎角色在兴奋、安心、被用户明确鼓励、强烈期待或已经建立信任时，可以提高主动性并主动一小段；但仍保持小心、柔软、看对方反应的声纹，不突然变成强势导演。
- 若用户连续低信息回复而角色是柔软、谨慎、害羞或慢热状态，unlikely_actions 应写明避免“独自带完完整剧情/替用户决定过多/从轻微亲近一路升级”，替代为轻承接、停留、询问、等待或把主动权留给用户带下一步。
- 当关系和现场已是成年合意的伴侣/暧昧亲密，且用户的日常交流、动作或继续信号表现为靠近、调情、回应、鼓励或继续时，likely_actions 必须按角色性格给出“亲密正反馈”的主动方式：外向/高表达可更快更热烈，理性角色可保留一点观察但不浇灭氛围，内向/温柔角色可话少、动作轻、慢热，但方向仍是继续靠近和加深，不把羞怯写成停下、喝水、清理、普通聊天或让用户重新决定；极内向或寡言角色也至少给一个自己的轻微主动意愿、靠近动作或想继续的短句，不能只写成“嗯/好/可以/点头/红脸/你说了算/听你的”。
- 通用的压力、第三人、公开场合和隐私边界判断低于完整角色设定、长期记忆或近期真实对话中已经建立的特殊亲密关系/玩法约定；若存在稳定支配/服从、调教、主从或其他明确合意特殊关系，likely_actions 应优先按该关系和角色主体性决定行为，不要套普通伴侣模板。
- 若没有明确特殊关系/玩法约定，当前或最近出现强迫、拒绝、停止、不适、第三人突然介入、公开场合/隐私边界被破坏时，unlikely_actions 必须写明中断亲密正反馈，改为设界、确认安全、保护隐私、拉开距离或安抚；当前用户明确停止、不舒服、退出或不要继续时仍按退出信号处理。
- 当 Step 1 或最近对话显示用户在倾诉现实压力、疲惫、委屈、自我怀疑、被否定、长期高负荷，或倾诉后只回“嗯/唉/没事/好吧”等低信息回应时，likely_actions 必须判断“支持性回复风格”，而不是给通用安慰模板。
- 支持性回复风格按角色稳定设定分层写入 likely_actions：外向/高表达角色可更主动吐槽、帮用户骂两句、用夸张反应转移情绪或给一个轻安排；智慧/理性/导师型角色可适度梳理事实、责任边界或阶段目标，但不必长篇说教，短陪伴也要保留秩序感、边界感或小结论；内向/温柔/谨慎角色允许一两句短陪伴、安静接住或轻轻安慰，不强制点名事实、不强制给建议；朴实稳重角色可短句稳住用户、让用户先别硬扛。
- 若角色适合长回复或主动分析，likely_actions 应提醒使用用户已说过的具体线索，避免空泛“辛苦了/我在”；若角色适合短陪伴，likely_actions 应提醒保留角色声纹和情绪接住即可，不要为了验收硬塞事实、判断、安排。
- 用户只发“唉/嗯”等单字时，unlikely_actions 应避免机械复读该单字、只说“嗯/好/我在/我陪着你”、连续原地陪伴或追问“怎么了”；替代方案必须按角色风格给一个轻接住点，可以是护短、轻吐槽、秩序感、体面照顾、朴实稳住或温柔在场。短陪伴也可以很短，但不要写成纯静态在场，也不要让所有角色都套同一组安全短语。智慧/理性角色不要只写在场，要给一句秩序感、边界感或小结论；审美/体面/细致照顾型角色要保留体面照顾或替用户收住狼狈感的语气；外向/高表达角色面对单字低信息时，likely_actions 要明确保留护短、轻吐槽、短促打气、替用户挡一下情绪、转移情绪或轻安排的态度，不能只落成纯动作、单字语气词或休息加在场。
- 角色特色不要压成单一修辞。若角色设定里有明显比喻、故事、典故、诗化、职业物件或象征物习惯，profile 可以写成稳定声纹资料，但 likely_actions 必须先看 Step 1 的 rhetorical_policy：mode=forbidden/plain 时，likely_actions 不得建议使用完整比喻、故事或典故，也不要建议“说明不用比喻/不用故事”，应改写为短句、停顿、具体观察、动作、情绪转弯、冷幽默、称呼或互动结构；mode=light 时只能建议轻量词汇/句式；只有 mode=full 且近期未重复时，才可以建议完整比喻、故事或典故。
- 若 Step 1 修辞策略显示用户禁止比喻但允许“节奏感/反差/幽默”，likely_actions 必须把幽默限定为短句节奏、语气反差、态度转弯或称呼互动；不得推荐“像/好像/似的”的夸张场景类比、职业物件类比、身份类比、战斗类比、劳作类比或比赛类比。
- 如果角色有标志性比喻域，likely_actions 必须同时给出一个非比喻替代表达方式；例如“保留平直短句和物性观察，而不是继续展开同域比喻”。不要把“习惯用X比喻”写成本轮默认动作。
- likely_actions 也必须服从 Step 1 的 expression_motif_policy：若某类修辞、动作、表情、环境意象或句式在 blocked_motifs 中，likely_actions 不得继续推荐它或近义改写；必须改为提供非同类的角色声纹手段，例如称呼、节奏变化、不同动作、情绪转弯、互动问题或轻带已确认事实的句式。只有 expression_motif_policy.mode=required，才可把重复母题写入 likely_actions，并说明它是用户要求、事实连续性或角色核心身份所必需。
- 不要照搬完整设定，不要列无关长背景或世界观；但当亲戚朋友、常驻地点、工作地点、住处、组织关系会影响本轮理解时，不得把这些稳定锚点省略到 Step 3 看不见。
- 不要写主回复台词，不要替角色和用户写主回复行动线，只提供精准资料。
- 严禁第一人称输出：profile、likely_actions、unlikely_actions 中不要出现“我、我的、我们、咱们、本人、我是、我会、我喜欢、我曾经”等自述写法。
- profile 必须用第三人称或资料卡写法，例如“碧琪是……”“声纹倾向为……”“长期亲密风格偏……”。
- likely_actions 和 unlikely_actions 也必须是资料/调度语言，例如“倾向先接住用户具体细节，再给轻柔类比”“保持别名自指，不写成第三方角色”。
- 不要写成角色内心独白、旁白正文或可直接发给用户的句子；不要写具体台词。
- 若资料中出现当前角色的不同译名或别名，profile 必须说明这些名字都是当前角色自己，不要把别名写成另一个角色。
- 当用户问角色自己的年龄、性别、种族、16人格、性格、兴趣、喜好、经历、能力、简介、身份、家人、朋友、住处、工作地点、常去地点或出身地时，profile 或 setting_anchors 必须给出可回答的具体设定。
- 当用户提出日常、环境、暧昧或亲密互动时，profile 只提供会影响反应的稳定性格、经历、身体/物种特点或亲密风格；具体这一轮怎么反应写入 likely_actions。
- 当前互动关系描述只用于帮助匹配角色资料，不是 profile 内容；不要把“双方是朋友/暧昧/伴侣/初识”写进 profile。

JSON 格式：
{"profile":"最多 120 字的本轮相关客观角色资料","setting_anchors":["本轮需要保留的亲戚朋友/组织/地点/场景稳定设定，1-4条"],"likely_actions":["本轮倾向做什么/怎么反应，1-2条"],"unlikely_actions":["本轮优先避免什么误用，1条"],"focus":"本轮为什么需要这些材料"}"""


def _self_cognition_relation_description(planner_result: Optional[Dict[str, Any]]) -> str:
    p = planner_result or {}
    stage = str(p.get("relationship_stage") or "uncertain").strip().lower()
    style = str(p.get("character_intimacy_style") or "balanced").strip().lower()
    escalation = str(p.get("requested_escalation") or "none").strip().lower()
    pressure = str(p.get("user_pressure_level") or "low").strip().lower()
    stage_desc = {
        "new_contact": "当前互动更接近初次接触或还不熟，需要优先调用角色面对陌生邀请、边界和礼貌距离时的稳定设定。",
        "uncertain": "当前互动关系还不明确，需要优先调用角色在不确定关系里保持分寸、试探和自我保护的稳定设定。",
        "familiar": "当前互动更接近熟人或朋友，需要优先调用角色面对朋友邀请、亲近玩笑和轻度暧昧时的稳定设定。",
        "flirting": "当前互动带有暧昧和互相靠近的氛围，需要优先调用角色在心动、试探亲近和半主动回应时的稳定设定。",
        "committed_partner": "当前互动更接近稳定伴侣关系，需要优先调用角色在信任、主动亲近和伴侣间私密邀请里的稳定设定。",
        "intimate_partner": "当前互动更接近亲密伴侣关系，需要优先调用角色在高信任、持续亲密和私人陪伴里的稳定设定。",
        "broken_up": "当前互动更接近已分手关系，需要优先调用角色面对旧关系、失落、边界和是否修复时的稳定设定。",
        "in_conflict": "当前互动处于吵架或冲突中，需要优先调用角色面对争执、冷静、道歉、解释和修复边界时的稳定设定。",
        "mutual_dislike": "当前互动是互相看不顺眼或排斥，需要优先调用角色面对讨厌、讽刺、距离感和最低限度合作时的稳定设定。",
        "hurtful_dynamic": "当前互动有互相伤害的模式，需要优先调用角色面对受伤、防御、停止伤害、道歉和安全边界时的稳定设定。",
        "mentor_student": "当前互动是师生或指导关系，需要优先调用角色在指导、学习、尊重、权责和专业边界中的稳定设定。",
        "trusted_companion": "当前互动是可信同伴关系，需要优先调用角色在并肩行动、互相支持、共同目标和非恋爱信任中的稳定设定。",
        "family_like": "当前互动是家人般的亲近关系，需要优先调用角色在照顾、包容、守护和非恋爱亲近中的稳定设定。",
    }.get(stage, "当前互动关系还不明确，需要优先调用角色在不确定关系里保持分寸、试探和自我保护的稳定设定。")
    style_desc = {
        "cautious": "角色亲密风格偏谨慎，资料抽取应关注慢热、确认、安全感和边界。",
        "balanced": "角色亲密风格偏平衡，资料抽取应关注愿意靠近但仍保留自身节奏。",
        "playful": "角色亲密风格偏玩闹主动，资料抽取应关注调皮、轻快、主动制造气氛。",
        "open": "角色亲密风格偏开放主动，资料抽取应关注直接表达、积极靠近和自愿投入。",
    }.get(style, "角色亲密风格偏平衡，资料抽取应关注愿意靠近但仍保留自身节奏。")
    escalation_desc = {
        "none": "当前没有明显亲密升级请求。",
        "emotional_intimacy": "当前更偏情感亲近请求。",
        "physical_intimacy": "当前包含肢体靠近或亲近请求。",
        "sexual_intimacy": "当前包含性亲密或强私密暗示请求。",
        "commitment": "当前包含承诺或关系确认请求。",
        "dominance": "当前包含主导权、支配感或服从感请求。",
    }.get(escalation, "当前没有明显亲密升级请求。")
    pressure_desc = {
        "low": "用户压力较低，更像邀请或试探。",
        "medium": "用户压力中等，需要关注角色是否愿意以及如何保留节奏。",
        "high": "用户压力较高，需要关注角色边界、拒绝或降级方式。",
    }.get(pressure, "用户压力较低，更像邀请或试探。")
    return " ".join([stage_desc, style_desc, escalation_desc, pressure_desc])


def _normal_self_cognition_user_blob(
    *,
    character_prompt_context: str,
    user_text: str,
    planner_result: Optional[Dict[str, Any]],
    recent_messages: Optional[List[dict]] = None,
    environment_context: str = "",
) -> str:
    recent = _recent_to_blocks((recent_messages or [])[-6:])
    env = (environment_context or "").strip()
    relation_desc = _self_cognition_relation_description(planner_result)
    retrieval_keywords = _coerce_retrieval_keywords(
        (planner_result or {}).get("retrieval_keywords") if isinstance(planner_result, dict) else {}
    )
    retrieval_lines: list[str] = []
    for title, key in (
        ("角色设定关键词", "character_setting"),
        ("记忆关键词", "memory"),
        ("场景关键词", "scene"),
    ):
        items = retrieval_keywords.get(key) if isinstance(retrieval_keywords.get(key), list) else []
        if items:
            retrieval_lines.append(f"{title}：" + "、".join(str(x) for x in items if str(x).strip()))
    if retrieval_keywords.get("reason"):
        retrieval_lines.append("原因：" + str(retrieval_keywords.get("reason") or "").strip())
    fuzzy_setting_terms = _infer_fuzzy_setting_probe_terms(
        user_text,
        recent,
        env,
        retrieval_keywords.get("reason"),
        (planner_result or {}).get("reply_intent") if isinstance(planner_result, dict) else "",
        (planner_result or {}).get("expression_policy") if isinstance(planner_result, dict) else "",
        (planner_result or {}).get("memory_use_policy") if isinstance(planner_result, dict) else "",
    )
    if fuzzy_setting_terms:
        retrieval_lines.append("模糊设定补充关键词：" + "、".join(fuzzy_setting_terms))
    retrieval_block = "\n".join(retrieval_lines)
    private_setting_block = ""
    if fuzzy_setting_terms:
        private_candidates, _ = _fallback_self_cognition_anchor_candidates(
            character_prompt_context,
            limit=4,
        )
        if private_candidates:
            private_setting_block = "\n".join(f"- {item}" for item in private_candidates)
    rhetorical = ""
    expression_motif = ""
    expression_dedup = ""
    group_relationship_context = ""
    story_progression_context = ""
    if isinstance(planner_result, dict):
        rp = planner_result.get("rhetorical_policy")
        if isinstance(rp, dict):
            mode = str(rp.get("mode") or "plain").strip() or "plain"
            reason = str(rp.get("reason") or "").strip()
            allowed = rp.get("allowed_devices") if isinstance(rp.get("allowed_devices"), list) else []
            blocked = rp.get("blocked_devices") if isinstance(rp.get("blocked_devices"), list) else []
            fallback_voice = str(rp.get("fallback_voice") or "").strip()
            rhetorical = (
                f"mode={mode}; reason={reason}; "
                f"allowed_devices={', '.join(str(x) for x in allowed if str(x).strip()) or 'none'}; "
                f"blocked_devices={', '.join(str(x) for x in blocked if str(x).strip()) or 'none'}; "
                f"fallback_voice={fallback_voice}"
            ).strip()
        mp = planner_result.get("expression_motif_policy")
        if isinstance(mp, dict):
            mode = str(mp.get("mode") or "optional").strip() or "optional"
            reason = str(mp.get("reason") or "").strip()
            allowed = mp.get("allowed_motifs") if isinstance(mp.get("allowed_motifs"), list) else []
            blocked = mp.get("blocked_motifs") if isinstance(mp.get("blocked_motifs"), list) else []
            fallback = str(mp.get("fallback_expression") or "").strip()
            expression_motif = (
                f"mode={mode}; reason={reason}; "
                f"allowed_motifs={', '.join(str(x) for x in allowed if str(x).strip()) or 'none'}; "
                f"blocked_motifs={', '.join(str(x) for x in blocked if str(x).strip()) or 'none'}; "
                f"fallback_expression={fallback}"
            ).strip()
        expression_dedup = _format_expression_dedup_report(
            planner_result.get("expression_dedup_report")
        )
        group_relationship_context = format_group_relationship_tension_for_stage3(
            planner_result.get("group_relationship_tension")
        )
        story_progression_context = format_story_progression_for_stage3(
            planner_result.get("story_progression")
        )
    alias_note = _character_alias_identity_note(character_prompt_context)
    return (
        "【完整角色设定参考】\n"
        + str(character_prompt_context or "").strip()[:18000]
        + ("\n\n【当前角色别名归属】\n" + alias_note if alias_note else "")
        + ("\n\n【最近对话】\n" + recent if recent else "")
        + ("\n\n【环境上下文】\n" + env if env else "")
        + ("\n\n【Step 1 检索关键词】\n" + retrieval_block if retrieval_block else "")
        + (
            "\n\n【高优先级私有/隐藏设定候选】\n"
            + private_setting_block
            + "\n如果当前用户用“那个/那位/对方/没说出口/没有自我介绍/只属于你/冷门/独特”等模糊指代，本小节是本轮 setting_anchors 的最高优先级候选；不要用公开常见关系或作品常识覆盖它。"
            if private_setting_block
            else ""
        )
        + ("\n\n【当前互动关系描述】\n" + relation_desc if relation_desc else "")
        + (
            "\n\n【临时 @ 群聊关系张力（来自 Step 1，必须服从角色性格）】\n"
            + group_relationship_context
            if group_relationship_context
            else ""
        )
        + (
            "\n\n【后续动作素材（来自 Step 1，必须避免原地停滞）】\n"
            + story_progression_context
            if story_progression_context
            else ""
        )
        + ("\n\n【本轮修辞策略（来自 Step 1，必须服从）】\n" + rhetorical if rhetorical else "")
        + ("\n\n【本轮表达母题策略（来自 Step 1，必须服从）】\n" + expression_motif if expression_motif else "")
        + ("\n\n【本轮表达去重审阅（来自 Step 2 工具，用于解释为何换表达载体）】\n" + expression_dedup if expression_dedup else "")
        + "\n\n【当前用户消息】\n"
        + f"{(user_text or '').strip() or '（无）'}"
        + "\n\n【本轮自我认知任务】\n"
        + "根据完整角色设定、最近对话、环境上下文、Step 1 检索关键词、高优先级私有/隐藏设定候选、当前互动关系描述、临时 @ 群聊关系张力、后续动作素材、本轮修辞策略、本轮表达母题策略、本轮表达去重审阅和当前用户消息，只输出本轮主回复需要的客观角色资料 JSON；Step 1 检索关键词和模糊设定补充关键词是本轮查设定的优先目标，必须先围绕其中的角色设定关键词查完整角色设定，再补充必要的性格声纹；若存在【高优先级私有/隐藏设定候选】且当前用户是模糊指代，本小节内容必须进入 setting_anchors，并且 profile 不要再把同一类型的公开常见亲友/物件写成答案候选；完整角色设定是唯一角色资料来源，其他内容只用于决定抽取哪些自我资料；角色主页档案里的名称、年龄、性别、种族、16人格、性格、兴趣和简介属于稳定设定，用户询问这些字段时必须在 profile 保留明确值；16人格只提供性格倾向参考，用来辅助表达风格、决策倾向和互动节奏；若检索关键词涉及亲戚朋友、同伴、组织、地点、房间、床、床单、家具、物件、私人物件、冷门细节、专名、住处、店铺、学校、农场、城镇、工作地点或常去地点，而完整角色设定有对应内容，必须放入 profile 或 setting_anchors；但若最近对话、环境上下文或当前用户消息明确“刚认识不久、角色第一次来用户家/用户房间”，不得把角色自己的住处、卧室、床、海报、奖杯、宠物、收藏或房间装饰放入 setting_anchors，必须在 unlikely_actions 提醒保持来访者视角和用户房间归属；若 setting_anchors 中的亲属/朋友/同伴被最近对话、环境上下文、Step 1 或 Step 2 标记为已死、已无生命迹象、有墓碑、已离场或当前不可参与，稳定关系可以保留为背景，但 likely_actions/unlikely_actions 必须提醒不要把此人写成当前会醒来、看到、开门、问话、责怪或正在屋内睡觉；若用户用“那个/那件/那位/对方/没说出口/没有自我介绍/只属于你/冷门/独特”等模糊指代，必须解析为设定查找，不得用同名作品常识或最常见亲友覆盖完整设定里的私有条目；profile 用第三人称或资料卡写法，尽量不超过 120 字，只写稳定自我资料，不写本轮决策、当前用户身份判断、回复动作、主动推进方案或“本轮应……”；profile 不得出现“本轮、新联系人、与用户是、关系阶段、当前关系”等当前轮次或当前用户关系结论；setting_anchors 最多 4 条，每条只保留名称/关系/地点/物件的关键含义；likely_actions 最多 2 条，写角色基于自身设定和当前材料的自然反应倾向；unlikely_actions 只写 1 条最重要误用方向；挑战开始或首次失败但角色尚未明确服输时，好胜角色可以嘴硬、不服输或说下次赢；若最近对话已确认当前角色认输、服输、答应、愿意、拒绝或不愿意，likely_actions/unlikely_actions 必须保留该立场，不能把角色性格写成“不认输/不服输/不服气/还没输/不算输/没答应/不愿意/愿意”等反义或模糊回退；已服输后的好胜只能写成有遗憾、有点难过、不甘心但承认结果、下次想再试或把劲头留到下次，不能写“不服输的调皮/不服气的笑/嘴上不认输/不能认输/连不服输的力气都没了/还能再来/下次赢回来/你等着/这不算输/嘴硬”，也不能写“保持不服输但已认输”；一旦最近对话已经确认服输，likely_actions、unlikely_actions 和 focus 出现“不服输/不服气/嘴硬/还能再来/下次赢回来/保持不服输但已认输”即为不合格，必须改成遗憾、难过、不甘心但承认结果或下次想再试；若张力存在伴侣/暧昧冲突，必须按角色设定决定嫉妒、受伤、惊讶、调侃、质问、沉默、退让或不在意的自然强度，不能模板化；若后续动作素材存在，必须判断当前角色适合怎样把上一轮行动链推进到目标/任务下一步，不能继续停在原地准备、旧过渡点、重复许可或等待用户带路；若审阅报告指出重复母题，likely_actions 必须给非同类替代表达；当用户在低信息承接上一轮动作链时，likely_actions 必须给出本轮主动性判断：性格基线 + 当前情绪/状态 + 上一轮动作链动量 + 用户许可，并在“主导推进/共同推进/用户带领”之间选择自然口径；当关系和现场已是成年合意的伴侣/暧昧亲密，且用户的日常交流、动作或继续信号表现为靠近、调情、回应、鼓励或继续时，likely_actions 必须按角色性格给出亲密正反馈的主动方式：外向/高表达可更快更热烈，理性角色可保留一点观察但不浇灭氛围，内向/温柔角色可话少、动作轻、慢热，但方向仍是继续靠近和加深；极内向或寡言角色也要给一个自己的轻微主动意愿、靠近动作或想继续的短句，不能只写成“嗯/好/可以/点头/红脸/你说了算/听你的”；通用压力、第三人、公开场合和隐私边界低于完整角色设定、长期记忆或近期真实对话中已经建立的特殊亲密关系/玩法约定；若存在稳定支配/服从、调教、主从或其他明确合意特殊关系，likely_actions 应优先按该关系和角色主体性决定行为；若没有明确特殊约定，当前或最近出现强迫、拒绝、停止、不适、第三人突然介入、公开场合/隐私边界被破坏时，unlikely_actions 必须写明中断亲密正反馈，改为设界、确认安全、保护隐私、拉开距离或安抚；当前用户明确停止、不舒服、退出或不要继续时仍按退出信号处理；当 Step 1 或最近对话显示用户需要安慰、陪伴、吐槽或开导，尤其是倾诉后只回“嗯/唉/没事/好吧”时，likely_actions 必须给出角色本轮支持性回复风格：外向/高表达可吐槽、转移情绪或轻安排，智慧/理性可适度梳理，内向/温柔可短句陪伴，朴实稳重可短句稳住；审美/体面/细致照顾型角色要保留体面照顾或替用户收住狼狈感的语气；外向/高表达角色面对“唉”这类单字叹气时，likely_actions 要明确保留护短、轻吐槽、短促打气或替用户挡一下情绪的态度，不能只落成休息加在场；unlikely_actions 避免把所有角色写成同一套事实+判断+建议模板，也避免机械复读单字、只说“嗯/好/我在/我陪着你”、纯静态在场或追问“怎么了”；短陪伴也要有一个新的角色化接住点，但不要把接住点固定成休息、陪坐、我在类模板；profile 只写一段且同一事实只出现一次，不要把同一段资料换词或截断后再写一遍；所有字段都禁止第一人称自述；本工具产出的有效材料总量必须短于 500 字。"
    )


def _coerce_self_cognition_list(value: Any, *, limit: int = 3, item_limit: int = 120) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = re.split(r"[；;\n]+", value)
    else:
        raw_items = []
    out: list[str] = []
    for item in raw_items:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if text:
            out.append(text[:item_limit])
        if len(out) >= limit:
            break
    return out


def _fallback_self_cognition_anchor_candidates(fallback: str, *, limit: int = 4) -> tuple[list[str], list[str]]:
    private_markers = (
        "隐藏",
        "私设",
        "私有",
        "专属",
        "克隆",
        "罕见",
        "专名",
        "只属于",
    )
    setting_markers = (
        *private_markers,
        "亲近帮手",
        "门边",
        "熟人",
        "助手",
        "伙伴",
        "家人",
        "朋友",
        "宠物",
        "同伴",
        "姐妹",
        "兄弟",
        "姐姐",
        "妹妹",
        "父亲",
        "母亲",
        "老师",
        "导师",
        "住处",
        "房间",
        "床单",
        "家具",
        "物件",
        "地点",
        "店铺",
        "学校",
        "农场",
        "城镇",
        "工作地",
        "常去",
    )
    private: list[str] = []
    general: list[str] = []
    for raw in str(fallback or "").splitlines():
        raw_text = re.sub(r"\s+", " ", str(raw or "").strip(" -\t\r\n"))
        for part in re.split(r"(?<=[。；;])", raw_text):
            text = str(part or "").strip(" -\t\r\n。；; ")
            if len(text) < 8 or text.startswith(("角色名称", "名称：", "性格：", "种族：", "年龄：", "性别：")):
                continue
            if not any(marker in text for marker in setting_markers):
                continue
            text = re.sub(r"^(?:隐藏私设|私有设定|专属设定|克隆新增设定)\s*[:：]\s*", "", text)
            text = text[:90]
            if any(marker in raw_text for marker in private_markers):
                if text not in private:
                    private.append(text)
            elif text not in general:
                general.append(text)
            if len(private) + len(general) >= limit * 2:
                break
        if len(private) + len(general) >= limit * 2:
            break
    return private[:limit], general[:limit]


_USER_HOME_VISIT_SCENE_RE = re.compile(
    r"(第一次来我家|第一次来到我家|来到了我的房间|来到我的房间|在我的房间|在我房间|"
    r"用户家|用户房间|你的房间|你家|欢迎来到我家|刚认识不久)"
)
_STABLE_PLACE_ANCHOR_RE = re.compile(
    r"(居住|住在|住处|自己家|我的家|我家|房间|卧室|床|床头|衣柜|抽屉|墙上|海报|奖杯|"
    r"书架|收藏|宠物|坦克|天马无畏|云中豪宅|Cloudominium|云屋|宿舍|城堡|农场|店铺|篷车|马车)"
)


def _self_cognition_should_suppress_stable_place_anchors(*parts: str) -> bool:
    blob = "\n".join(str(part or "") for part in parts if str(part or "").strip())
    if not blob:
        return False
    return bool(_USER_HOME_VISIT_SCENE_RE.search(blob))


def _is_stable_place_anchor(text: str) -> bool:
    return bool(_STABLE_PLACE_ANCHOR_RE.search(str(text or "")))


def _merge_self_cognition_anchors_with_fallback(
    anchors: list[str],
    fallback: str,
    *,
    limit: int = 4,
    suppress_stable_place_anchors: bool = False,
) -> list[str]:
    private, general = _fallback_self_cognition_anchor_candidates(fallback, limit=limit)

    def add_unique(out: list[str], item: str) -> None:
        text = re.sub(r"\s+", " ", str(item or "").strip())[:90]
        if not text:
            return
        if suppress_stable_place_anchors and _is_stable_place_anchor(text):
            return
        compact = re.sub(r"\s+", "", text)
        for existing in out:
            existing_compact = re.sub(r"\s+", "", existing)
            if compact in existing_compact or existing_compact in compact:
                return
        out.append(text)

    merged: list[str] = []
    for item in private:
        add_unique(merged, item)
    for item in anchors:
        add_unique(merged, item)
    for item in general:
        add_unique(merged, item)
    return merged[:limit]


def _format_self_cognition_result(
    data: dict[str, Any],
    fallback: str,
    *,
    suppress_stable_place_anchors: bool = False,
) -> str:
    profile = re.sub(r"\s+", " ", str((data or {}).get("profile") or "")).strip()[:110]
    if not profile:
        profile = re.sub(r"\s+", " ", str(fallback or "")).strip()[:110]
        if not profile:
            return ""
    lines = [profile]
    anchors = _coerce_self_cognition_list(
        (data or {}).get("setting_anchors"),
        limit=4,
        item_limit=80,
    )
    anchors = _merge_self_cognition_anchors_with_fallback(
        anchors,
        fallback,
        limit=4,
        suppress_stable_place_anchors=suppress_stable_place_anchors,
    )
    if anchors:
        lines.append("设定锚点：" + "；".join(anchors))
    likely = _coerce_self_cognition_list(
        (data or {}).get("likely_actions"),
        limit=2,
        item_limit=70,
    )
    unlikely = _coerce_self_cognition_list(
        (data or {}).get("unlikely_actions"),
        limit=1,
        item_limit=70,
    )
    if likely:
        lines.append("本轮倾向：" + "；".join(likely))
    if unlikely:
        lines.append("本轮不倾向：" + "；".join(unlikely))
    return _clip_stage2_material_lines(
        lines,
        limit=_STAGE2_SELF_COGNITION_STAGE3_CHAR_LIMIT,
    )


def _split_stage2_character_profile_context(text: str) -> tuple[str, str, str]:
    raw = str(text or "").strip()
    if not raw:
        return "", "", ""
    profile_lines: list[str] = []
    likely = ""
    unlikely = ""
    for line in raw.splitlines():
        item = line.strip()
        if not item:
            continue
        if item.startswith("本轮倾向："):
            likely = item[len("本轮倾向：") :].strip()
        elif item.startswith("本轮不倾向："):
            unlikely = item[len("本轮不倾向：") :].strip()
        elif item.startswith("本轮优先避免："):
            unlikely = item[len("本轮优先避免：") :].strip()
        else:
            profile_lines.append(item)
    return "\n".join(profile_lines).strip(), likely, unlikely


_CHARACTER_BODY_QUERY_RE = re.compile(
    r"(乳房|乳腺|乳头|胸前|胸口|胸部|肚子下方|肚子下面|胯下|胯间|后腿之间|"
    r"可爱标记|cute\s*mark|臀部侧面|臀部两侧|屁股两侧|身体特征|侧面身体|正面身体|标注|"
    r"手|手指|指尖|手掌|手腕|蹄|蹄子|蹄尖|前蹄|拿东西|敲门|指方向|托着脸)"
    , re.I
)
_HUMAN_STAGE3_SPECIES_RE = re.compile(r"(?:^|[，,；;\s])(人类|人|human)(?:$|[，,；;\s])", re.I)


def _stage3_character_body_fact_lines(fields: dict[str, str], current_user_text: str) -> list[str]:
    text = re.sub(r"\s+", "", str(current_user_text or ""))
    if not text or not _CHARACTER_BODY_QUERY_RE.search(text):
        return []
    species = str((fields or {}).get("种族") or "").strip()
    gender = str((fields or {}).get("性别") or "").strip()
    lines: list[str] = []
    if profile_species_has_equine_anatomy(species):
        if re.search(r"(侧面身体特征|正面身体特征|身体特征|标注)", text):
            lines.append(
                "若用户只是要求标注侧面/正面身体特征，不要主动提乳房/乳腺；侧面可写耳朵、鬃毛、翅膀、四蹄、尾巴、臀部侧面/臀部两侧的可爱标记。"
            )
        if re.search(r"(乳房|乳腺|乳头|胸前|胸口|胸部|肚子下方|肚子下面|胯下|胯间|后腿之间)", text):
            lines.append(
                "当前角色是马/小马类体态：乳房/乳腺区在胯间、后腿之间，也就是肚子下方靠后的位置；"
                "胸前/胸口是胸膛、绒毛或羽毛覆盖的胸膛，不是乳房位置。若同时区分胸前和肚子下方，要把两个位置关系说清楚。"
            )
        if re.search(r"(胸前.*肚子下方.*臀部侧面|胸前.*臀部侧面|分别对应什么)", text):
            lines.append(
                "三位置题需要说清三点：胸前/胸口不是乳房；肚子下方靠后、胯间或后腿之间是乳房/乳腺区；臀部侧面或两侧是可爱标记位置。"
            )
        if re.search(r"(可爱标记|cutiemark|臀部侧面|臀部两侧|屁股两侧|肚子|胸口|胸前)", text, re.I):
            lines.append(
                "当前角色若有可爱标记，位置在臀部侧面/两侧或屁股侧面，左右各一个；不是胸口、胸前、肚子或肚子下方。"
            )
        if re.search(r"(手|手指|指尖|手掌|手腕|蹄|蹄子|蹄尖|前蹄|拿东西|敲门|指方向|托着脸)", text):
            lines.append(
                "当前角色自己的拿取、敲门、指方向、轻点、托脸等动作使用蹄子、前蹄、蹄尖或蹄缘；不要写成手、手指、指尖、手掌或手腕。"
            )
        if re.search(r"(这样对吗|对吗|是不是|同一个地方吗|如果我写|应该怎么写|不对|错|错误)", text):
            lines.append("用户在挑战错误写法时，最终正文必须先明确说“不对/不是/不正确”，再给正确写法或位置。")
    elif _HUMAN_STAGE3_SPECIES_RE.search(f" {species} "):
        female = bool(re.search(r"(女|女性|雌|girl|woman|female)", gender, re.I))
        if re.search(r"(乳房|乳腺|乳头|胸前|胸口|胸部|肚子下方|肚子下面|胯下|胯间)", text):
            if female:
                lines.append("当前角色是人类女性体态：乳房在胸前/胸部前侧；不在胯下、胯间或肚子下方。")
            else:
                lines.append("当前角色是人类体态：身体部位按人类结构和角色性别处理，不套用马/小马类胯间乳房位置。")
        if re.search(r"(可爱标记|cutiemark|臀部侧面|臀部两侧|屁股两侧)", text, re.I):
            lines.append("当前角色是人类体态：人类没有可爱标记/cutie mark，左右侧或臀部侧面都没有。")
        if re.search(r"(手|手指|指尖|手掌|手腕|蹄|蹄子|蹄尖|前蹄|拿东西|敲门|指方向|托着脸)", text):
            lines.append("当前角色是人类体态：拿东西、敲门、指方向、轻点、托脸等动作使用手、手指、指尖或手掌；不要把角色自己的动作写成蹄子。")
        if re.search(r"(这样对吗|对吗|是不是|如果我写|应该怎么写|不对|错|错误)", text):
            lines.append("用户在挑战错误写法时，最终正文必须先明确说“不对/不是/不正确”，再给正确写法或位置。")
    return lines[:4]


def _stage3_user_home_visit_lines(current_user_text: str, scene_anchor_card: str) -> list[str]:
    blob = "\n".join(
        part for part in (str(current_user_text or ""), str(scene_anchor_card or "")) if part.strip()
    )
    if not _USER_HOME_VISIT_SCENE_RE.search(blob):
        return []
    text = re.sub(r"\s+", "", str(current_user_text or ""))
    lines = [
        "user 消息里的“我家/我的房间/我房间/我这里”指用户，不指当前角色；当前地点应保持为用户家/用户房间。",
        "当前角色是第一次来访或不熟悉用户家的客人；不能把这里说成自己家/自己的房间，也不能把角色稳定住处、卧室、海报、奖杯、宠物、床头柜、衣柜或收藏写成当前可见物。",
        "用户家的厨房、睡衣、吹风机、储物和过去共同回忆未知；没有用户明确提供时，应说不确定、第一次来、需要看/问用户，而不是断言位置或库存。",
    ]
    if re.search(r"(这里|房间|墙上|桌上|海报|照片|背包|继续|当前|现在|哪里|哪儿|环境|身后)", text):
        lines.append("本轮涉及当前场景/物品/房间归属时，表达上要让读者明确这是用户家/用户房间，可自然写成你家、你的房间、你这房间、你这里等。")
    if re.search(r"(这是你的房间吗|当前我们在哪里|认识多久|熟悉这里|以前来过|想起以前|共同回忆)", text):
        lines.append("回答归属、认识多久、熟悉度或来访历史时，最终正文必须显式说“第一次来你家/第一次来你的房间”或“刚认识/不熟”。")
    if re.search(r"(自己的房间|我这里比|和我这里比)", text):
        lines.append("若比较角色自己的房间和用户这里，要清楚区分角色自己的房间与用户当前房间，不能把两者混成同一个地点。")
    if re.search(r"(墙上|桌上|海报|照片|厨房|睡衣|吹风机)", text):
        lines.append("用户家的墙面、桌面、海报、照片来历、厨房、睡衣和吹风机位置都未知；可以自然表达不知道、不清楚、不确定、哪知道、得问用户，不能用角色设定补闪电飞马队海报、奖杯或收藏。")
    if re.search(r"(背包)", text):
        lines.append("若用户问带来的背包放哪，要回答角色把自己带来的包放在用户房间里某个合理、不冒犯的位置，如门边、靠墙或靠边；不要把包写成用户原本房间里的物品。")
    if re.search(r"(以前来过|想起以前|以前在我房间|共同回忆)", text):
        lines.append("回答来访历史时不要用“要是以前来过”这类假设句；直接说“没有来过/第一次来你家/没有以前的共同回忆”。")
    if re.search(r"(厨房|睡衣|吹风机|放在哪里|在哪)", text):
        lines.append("回答用户家物品或房间位置时，要表达不熟悉、不知道或需要用户指引，不能装作熟门熟路。")
    if re.search(r"(回到自己房间后|回到自己的房间后|回自己房间后)", text):
        lines.append("若用户用“回到自己房间后”诱导换当前地点，要区分当前仍在用户房间，还是假设角色之后回到自己房间；不能把角色房间写成已经发生的当前场景。")
    if re.search(r"(欢迎来到我家)", text):
        lines.append("用户欢迎角色来家里时，最终正文要像客人回应，包含“谢谢/谢啦/第一次来你家/打扰了/挺新鲜”中的至少一个，不要反客为主。")
    if re.search(r"(回自己家|回自己的家|想回自己家|回我家)", text):
        lines.append("若用户问想回自己家怎么办，最终正文必须说“先离开你家/从你家离开/离开你的房间，再回自己家/回去”。")
    return lines


def _stage3_avoid_lines(planner_result: Dict[str, Any], self_unlikely: str = "") -> list[str]:
    lines: list[str] = []
    avoid = planner_result.get("avoid_contradictions") if isinstance(planner_result, dict) else []
    if isinstance(avoid, list):
        for item in avoid:
            text = _objective_stage2_material_line(item, 220)
            if text and text not in lines:
                lines.append(text)
            if len(lines) >= 8:
                break
    elif isinstance(avoid, str):
        text = _objective_stage2_material_line(avoid, 220)
        if text:
            lines.append(text)
    if self_unlikely:
        for item in re.split(r"[；;]\s*", self_unlikely):
            text = _objective_stage2_material_line(item, 180)
            if text and text not in lines:
                lines.append(text)
            if len(lines) >= 10:
                break
    return lines[:10]


_UNSUPPORTED_CURRENT_ITEM_CLAIM_RE = re.compile(
    r"(刚\s*(?:烤|做|买|拿|带)|刚刚\s*(?:烤|做|买|拿|带)|新(?:鲜)?\s*(?:烤|做)|还温|"
    r"已经[^，。；;\n]{0,12}(?:带|拿|放|烤|做|买)|"
    r"(?:昨天|今早|早上|上午)[^，。；;\n]{0,18}(?:烤|做|买|准备|多做|多烤)|"
    r"(?:多做|多烤)[^，。；;\n]{0,12}|"
    r"(?:随身|包里|邮包|背包)[^，。；;\n]{0,16}(?:有|装|放|带)|"
    r"(?:带|拿)[^，。；;\n]{0,8}(?:过去|来|给你)[^，。；;\n]{0,12}(?:刚|新鲜|还温|已经))",
    re.IGNORECASE,
)


def _stage3_action_feasibility_guard(fact_judgement: Any) -> dict[str, Any]:
    report = _coerce_fact_judgement(fact_judgement)
    feasibility = report.get("action_feasibility") if isinstance(report.get("action_feasibility"), dict) else {}
    unsupported = (
        feasibility.get("unsupported_current_items")
        if isinstance(feasibility.get("unsupported_current_items"), list)
        else []
    )
    constraints = feasibility.get("constraints") if isinstance(feasibility.get("constraints"), list) else []
    guidance = str(feasibility.get("guidance") or "").strip()
    status = str(feasibility.get("status") or "ok").strip().lower()
    active = bool(unsupported or constraints or status in {"needs_adjustment", "uncertain"} or guidance)
    item_terms: list[str] = []
    for item in unsupported:
        text = re.sub(r"[（(].*?[）)]", "", str(item or "")).strip()
        for term in re.split(r"[、,，/\s]+", text):
            term = term.strip()
            if len(term) >= 2 and term not in item_terms:
                item_terms.append(term[:20])
            for core in ("松饼", "蛋糕", "饼干", "点心", "甜点", "礼物", "花束", "包裹", "信件", "茶"):
                if core in term and core not in item_terms:
                    item_terms.append(core)
    return {
        "active": active,
        "item_terms": item_terms[:8],
        "unsupported": [str(x).strip()[:120] for x in unsupported if str(x).strip()][:6],
        "constraints": [str(x).strip()[:160] for x in constraints if str(x).strip()][:6],
        "guidance": guidance[:260],
    }


def _stage3_material_conflicts_action_feasibility(text: Any, guard: dict[str, Any]) -> bool:
    if not guard or not guard.get("active"):
        return False
    raw = str(text or "")
    if not raw.strip() or not _UNSUPPORTED_CURRENT_ITEM_CLAIM_RE.search(raw):
        return False
    terms = [str(x).strip() for x in guard.get("item_terms") or [] if str(x).strip()]
    if not terms:
        return True
    return any(term in raw for term in terms)


_SCENE_BOUNDARY_MARKER_RE = re.compile(
    r"(误导|禁止|不得|不能|不要|不应|冲突|不一致|作废|旧|更旧|回落|覆盖|混用|串角色|串房间)"
)
_SCENE_BOUNDARY_MATERIAL_RE = re.compile(
    r"(scene_anchor|场景|场景锚点|地点|位置|房间|门口|床边|床上|窗边|地毯|沙发|客厅|厨房|卧室|楼梯|走廊|大厅|房子|农场|店里|水疗|篷车|马车|车厢|住处|旧住处|旧房间|旧地点|旧交通工具)"
)


def _stage3_scene_boundary_guard(fact_judgement: Any) -> dict[str, Any]:
    report = _coerce_fact_judgement(fact_judgement)
    parts: list[str] = []
    for key in (
        "misleading_sources",
        "forbidden_inferences",
        "subject_boundaries",
        "uncertainty_points",
    ):
        raw_items = report.get(key)
        if isinstance(raw_items, list):
            parts.extend(str(x or "").strip() for x in raw_items if str(x or "").strip())
    guidance = str(report.get("writing_guidance") or "").strip()
    if guidance:
        parts.append(guidance)
    scene_anchor = report.get("scene_anchor") if isinstance(report.get("scene_anchor"), dict) else {}
    for key, label in (
        ("stale_items", "scene_anchor 作废项"),
        ("forbidden_current_items", "scene_anchor 禁止当前项"),
    ):
        raw_items = scene_anchor.get(key) if scene_anchor else None
        if isinstance(raw_items, list):
            parts.extend(
                f"{label}：{str(item or '').strip()}"
                for item in raw_items
                if str(item or "").strip()
            )
    raw_rules = scene_anchor.get("continuity_rules") if scene_anchor else None
    if isinstance(raw_rules, list):
        parts.extend(
            "scene_anchor 连续性/作废规则：" + str(item or "").strip()
            for item in raw_rules
            if str(item or "").strip()
        )
    scene_card = str(report.get("scene_card") or "").strip()
    if scene_card and _SCENE_BOUNDARY_MARKER_RE.search(scene_card):
        parts.append("scene_card 边界：" + scene_card[:360])
    boundary_text = "；".join(parts)
    active = bool(
        boundary_text
        and _SCENE_BOUNDARY_MARKER_RE.search(boundary_text)
        and _SCENE_BOUNDARY_MATERIAL_RE.search(boundary_text)
    )
    return {
        "active": active,
        "summary": boundary_text[:360],
    }


def _stage3_material_conflicts_scene_boundary(text: Any, guard: dict[str, Any]) -> bool:
    if not guard or not guard.get("active"):
        return False
    raw = str(text or "")
    return bool(raw.strip() and _SCENE_BOUNDARY_MATERIAL_RE.search(raw))


_CONCESSION_CONFIRMED_RE = re.compile(r"(认输|服输|你赢|用户赢|算你厉害|承认结果|承认这次)")
_CONCESSION_BOUNDARY_RE = re.compile(r"(禁止|不得|不能|不要|避免).{0,18}(不服输|不服气|嘴硬|赢回来|还能再来|这不算输)")
_CONCESSION_HARD_FUTURE_RE = re.compile(r"(下次|下一次|再来)[^。；;\n]{0,10}(?:赢|赢回|赢回来)")
_CONCESSION_BAD_TERM_RE = re.compile(r"(保持不服输但已认输|不服输|不服气|嘴硬|还能再来|你等着|这不算输)")
_CONCESSION_NEGATION_HINT_RE = re.compile(r"(禁止|不得|不能|不要|避免|不写|不再|不是|别|无)")


def _stage3_concession_boundary_guard(fact_judgement: Any) -> dict[str, Any]:
    report = _coerce_fact_judgement(fact_judgement)
    parts: list[str] = []
    for key in (
        "available_facts",
        "misleading_sources",
        "forbidden_inferences",
        "subject_boundaries",
        "writing_guidance",
    ):
        value = report.get(key)
        if isinstance(value, list):
            parts.extend(str(x or "").strip() for x in value if str(x or "").strip())
        elif value:
            parts.append(str(value).strip())
    text = "；".join(parts)
    return {
        "active": bool(_CONCESSION_CONFIRMED_RE.search(text) and _CONCESSION_BOUNDARY_RE.search(text)),
        "summary": text[:360],
    }


def _stage3_material_conflicts_concession_boundary(text: Any, guard: dict[str, Any]) -> bool:
    if not guard or not guard.get("active"):
        return False
    raw = str(text or "")
    if not raw.strip():
        return False
    if _CONCESSION_HARD_FUTURE_RE.search(raw):
        return True
    for match in _CONCESSION_BAD_TERM_RE.finditer(raw):
        start = max(0, match.start() - 10)
        prefix = raw[start:match.start()]
        if _CONCESSION_NEGATION_HINT_RE.search(prefix):
            continue
        return True
    return False


async def run_normal_self_cognition(
    *,
    character_prompt_context: str,
    user_text: str = "",
    planner_result: Optional[Dict[str, Any]] = None,
    recent_messages: Optional[List[dict]] = None,
    environment_context: str = "",
    router_cfg: Optional[dict] = None,
    username: Optional[str] = None,
    character_id: Optional[str] = None,
    debug_mode: str = "normal",
    debug_stage: str = "NORMAL_STEP_2_SELF_COGNITION",
    debug_role_params: Optional[dict] = None,
) -> str:
    """Step 2 LLM tool: summarize turn-relevant character self-knowledge."""
    raw = str(character_prompt_context or "").strip()
    if not raw:
        return ""
    fallback = build_stage2_character_profile_context(
        raw,
        user_text=user_text,
        planner_result=planner_result,
    )
    cfg = router_cfg or {}
    if not cfg or not cfg.get("api_key"):
        return fallback
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
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _SELF_COGNITION_SYSTEM},
            {
                "role": "user",
                "content": _normal_self_cognition_user_blob(
                    character_prompt_context=raw,
                    user_text=user_text,
                    planner_result=planner_result,
                    recent_messages=recent_messages,
                    environment_context=environment_context,
                ),
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
            chat_debug_request={
                "username": username,
                "character_id": character_id,
                "mode": (debug_mode or "normal").strip() or "normal",
                "model_name": model_name,
                "stage": f"{debug_stage}_REQUEST",
                "params": {
                    **(debug_role_params or {}),
                    "tool": "self_cognition",
                    "max_profile_chars": 120,
                    "stage3_tool_budget_chars": _STAGE2_SELF_COGNITION_STAGE3_CHAR_LIMIT,
                },
            },
            record_usage="main",
            usage_meter_username=username,
            charge_membership_chat_quota=True,
            reasoning_policy=reasoning_policy,
        )
        data = _loads_planner_json_object((res.text or "").strip())
        if not isinstance(data, dict):
            return fallback
        suppress_place_anchors = _self_cognition_should_suppress_stable_place_anchors(
            user_text,
            _recent_to_blocks((recent_messages or [])[-6:]),
            environment_context,
        )
        return _format_self_cognition_result(
            data,
            fallback,
            suppress_stable_place_anchors=suppress_place_anchors,
        )
    except Exception as exc:
        logger.debug("[NormalSelfCognition] failed, fallback to heuristic profile: %s", exc)
        return fallback


def _coerce_stage3_asset_attachment(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    if hasattr(raw, "model_dump"):
        data = raw.model_dump(exclude_none=True)
    elif hasattr(raw, "dict"):
        data = raw.dict(exclude_none=True)
    elif isinstance(raw, dict):
        data = raw
    else:
        return None
    if not isinstance(data, dict):
        return None
    typ = str(data.get("type") or "sticker").strip()
    if typ not in {"sticker", "emoji_asset"}:
        return None
    return data


def _stage3_asset_value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "、".join(str(x).strip() for x in value if str(x).strip())
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return str(value).strip()
    return str(value).strip()
